"""Deterministic distributed-job contracts and a local reference coordinator.

The coordinator is intentionally not advertised as a cluster.  It implements
the hard semantics a future queue/database backend must preserve: immutable job
identity, idempotent submission, fenced leases, bounded retries and
content-addressed artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from threading import RLock
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4


DISTRIBUTED_CONTRACT_VERSION = "backtest-job-contract-1"


def _utc(value: datetime | None = None) -> datetime:
    stamp = value or datetime.now(timezone.utc)
    if stamp.tzinfo is None:
        raise ValueError("distributed timestamps must be timezone-aware")
    return stamp.astimezone(timezone.utc)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


@dataclass(frozen=True)
class DistributedJobSpec:
    source_sha256: str
    dataset_sha256: str
    engine_sha256: str
    parameters: Mapping[str, Any]
    seed: int
    task_kind: str = "BACKTEST"
    max_attempts: int = 3
    priority: int = 0
    contract_version: str = DISTRIBUTED_CONTRACT_VERSION
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("source_sha256", "dataset_sha256", "engine_sha256"):
            value = str(getattr(self, name)).strip().lower()
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError(f"{name} must be a SHA-256 digest")
            object.__setattr__(self, name, value)
        if int(self.max_attempts) < 1 or int(self.max_attempts) > 20:
            raise ValueError("max_attempts must be between 1 and 20")
        if self.contract_version != DISTRIBUTED_CONTRACT_VERSION:
            raise ValueError("unsupported distributed contract version")
        if not str(self.task_kind).strip():
            raise ValueError("task_kind is required")
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def job_id(self) -> str:
        payload = {
            "source_sha256": self.source_sha256,
            "dataset_sha256": self.dataset_sha256,
            "engine_sha256": self.engine_sha256,
            "parameters": dict(self.parameters),
            "seed": int(self.seed),
            "task_kind": self.task_kind,
            "max_attempts": int(self.max_attempts),
            "priority": int(self.priority),
            "contract_version": self.contract_version,
            "metadata": dict(self.metadata),
        }
        return "BTJ-" + sha256(_canonical(payload)).hexdigest()[:32].upper()


@dataclass(frozen=True)
class JobLease:
    job_id: str
    worker_id: str
    token: str
    attempt: int
    leased_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class JobRecord:
    spec: DistributedJobSpec
    state: JobState
    submitted_at: datetime
    updated_at: datetime
    attempt: int = 0
    result_sha256: str = ""
    error: str = ""
    next_eligible_at: datetime | None = None
    lease: JobLease | None = None

    @property
    def job_id(self) -> str:
        return self.spec.job_id


class LeaseConflict(RuntimeError):
    pass


class ContentAddressedArtifactStore:
    """Thread-safe in-memory reference; replaceable by object storage."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = RLock()

    def put(self, payload: bytes) -> str:
        content = bytes(payload)
        digest = sha256(content).hexdigest()
        with self._lock:
            existing = self._objects.setdefault(digest, content)
            if existing != content:
                raise RuntimeError("SHA-256 collision in artifact store")
        return digest

    def get(self, digest: str) -> bytes:
        with self._lock:
            try:
                return self._objects[str(digest).lower()]
            except KeyError as exc:
                raise KeyError(f"unknown artifact: {digest}") from exc

    def has(self, digest: str) -> bool:
        with self._lock:
            return str(digest).lower() in self._objects


class LocalJobCoordinator:
    """Reference state machine for future Redis/Postgres/Kubernetes backends."""

    def __init__(self, artifact_store: ContentAddressedArtifactStore | None = None) -> None:
        self.artifacts = artifact_store or ContentAddressedArtifactStore()
        self._records: dict[str, JobRecord] = {}
        self._lock = RLock()

    @property
    def capability(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "backend": "LOCAL_REFERENCE",
                "distributed_cluster": False,
                "idempotent_submission": True,
                "content_addressed_artifacts": True,
                "fenced_leases": True,
                "bounded_retries": True,
                "production_ready": False,
            }
        )

    def submit(self, spec: DistributedJobSpec, *, now: datetime | None = None) -> JobRecord:
        stamp = _utc(now)
        with self._lock:
            current = self._records.get(spec.job_id)
            if current is not None:
                if current.spec != spec:
                    raise RuntimeError("job identity collision")
                return current
            record = JobRecord(spec, JobState.QUEUED, stamp, stamp)
            self._records[spec.job_id] = record
            return record

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            try:
                return self._records[str(job_id)]
            except KeyError as exc:
                raise KeyError(f"unknown job_id: {job_id}") from exc

    def _reap_expired(self, stamp: datetime) -> None:
        for job_id, record in tuple(self._records.items()):
            if (
                record.state is JobState.RUNNING
                and record.lease is not None
                and record.lease.expires_at <= stamp
            ):
                terminal = record.attempt >= record.spec.max_attempts
                self._records[job_id] = replace(
                    record,
                    state=JobState.FAILED if terminal else JobState.RETRY_WAIT,
                    updated_at=stamp,
                    error="worker lease expired",
                    next_eligible_at=None if terminal else stamp,
                    lease=None,
                )

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> JobLease | None:
        worker = str(worker_id).strip()
        if not worker:
            raise ValueError("worker_id is required")
        if int(lease_seconds) < 1 or int(lease_seconds) > 3600:
            raise ValueError("lease_seconds must be between 1 and 3600")
        stamp = _utc(now)
        with self._lock:
            self._reap_expired(stamp)
            eligible = [
                record
                for record in self._records.values()
                if record.state in {JobState.QUEUED, JobState.RETRY_WAIT}
                and (record.next_eligible_at is None or record.next_eligible_at <= stamp)
            ]
            if not eligible:
                return None
            record = sorted(
                eligible,
                key=lambda item: (-item.spec.priority, item.submitted_at, item.job_id),
            )[0]
            lease = JobLease(
                job_id=record.job_id,
                worker_id=worker,
                token=uuid4().hex,
                attempt=record.attempt + 1,
                leased_at=stamp,
                expires_at=stamp + timedelta(seconds=int(lease_seconds)),
            )
            self._records[record.job_id] = replace(
                record,
                state=JobState.RUNNING,
                updated_at=stamp,
                attempt=lease.attempt,
                lease=lease,
                next_eligible_at=None,
                error="",
            )
            return lease

    def _active(self, lease: JobLease, stamp: datetime) -> JobRecord:
        record = self.get(lease.job_id)
        if record.state is not JobState.RUNNING or record.lease is None:
            raise LeaseConflict("job is not running")
        if record.lease.token != lease.token or record.lease.worker_id != lease.worker_id:
            raise LeaseConflict("stale or foreign lease token")
        if record.lease.expires_at <= stamp:
            raise LeaseConflict("lease expired")
        return record

    def heartbeat(
        self,
        lease: JobLease,
        *,
        lease_seconds: int = 30,
        now: datetime | None = None,
    ) -> JobLease:
        stamp = _utc(now)
        with self._lock:
            record = self._active(lease, stamp)
            renewed = replace(
                record.lease,
                expires_at=stamp + timedelta(seconds=int(lease_seconds)),
            )
            self._records[record.job_id] = replace(
                record, updated_at=stamp, lease=renewed
            )
            return renewed

    def succeed(
        self,
        lease: JobLease,
        payload: bytes,
        *,
        now: datetime | None = None,
    ) -> JobRecord:
        stamp = _utc(now)
        with self._lock:
            record = self._active(lease, stamp)
            digest = self.artifacts.put(payload)
            completed = replace(
                record,
                state=JobState.SUCCEEDED,
                updated_at=stamp,
                result_sha256=digest,
                lease=None,
            )
            self._records[record.job_id] = completed
            return completed

    def fail(
        self,
        lease: JobLease,
        error: str,
        *,
        retry_delay_seconds: int = 0,
        now: datetime | None = None,
    ) -> JobRecord:
        stamp = _utc(now)
        with self._lock:
            record = self._active(lease, stamp)
            terminal = record.attempt >= record.spec.max_attempts
            updated = replace(
                record,
                state=JobState.FAILED if terminal else JobState.RETRY_WAIT,
                updated_at=stamp,
                error=str(error)[:4000],
                next_eligible_at=(
                    None
                    if terminal
                    else stamp + timedelta(seconds=max(0, int(retry_delay_seconds)))
                ),
                lease=None,
            )
            self._records[record.job_id] = updated
            return updated

    def cancel(self, job_id: str, *, now: datetime | None = None) -> JobRecord:
        stamp = _utc(now)
        with self._lock:
            record = self.get(job_id)
            if record.state.terminal:
                return record
            updated = replace(
                record,
                state=JobState.CANCELLED,
                updated_at=stamp,
                lease=None,
                next_eligible_at=None,
            )
            self._records[record.job_id] = updated
            return updated


__all__ = [
    "DISTRIBUTED_CONTRACT_VERSION",
    "ContentAddressedArtifactStore",
    "DistributedJobSpec",
    "JobLease",
    "JobRecord",
    "JobState",
    "LeaseConflict",
    "LocalJobCoordinator",
]
