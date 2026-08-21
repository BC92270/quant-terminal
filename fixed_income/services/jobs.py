"""Bounded in-process job service for heavy analytical calculations."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, Callable
from uuid import uuid4


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@dataclass
class JobRecord:
    job_id: str
    name: str
    status: JobStatus
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class JobManager:
    """Execute bounded background jobs without coupling them to Streamlit."""

    def __init__(self, max_workers: int = 2, max_jobs: int = 100) -> None:
        if max_workers < 1 or max_jobs < 1:
            raise ValueError("max_workers and max_jobs must be positive")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="fixed-income",
        )
        self._max_jobs = int(max_jobs)
        self._lock = Lock()
        self._records: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[Any]] = {}

    def submit(
        self,
        name: str,
        function: Callable[..., Any],
        *args: Any,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        if not str(name).strip():
            raise ValueError("job name is required")
        with self._lock:
            active = sum(
                record.status in {JobStatus.QUEUED, JobStatus.RUNNING}
                for record in self._records.values()
            )
            if active >= self._max_jobs:
                raise RuntimeError("job capacity reached")
            job_id = str(uuid4())
            self._records[job_id] = JobRecord(
                job_id=job_id,
                name=str(name),
                status=JobStatus.QUEUED,
                submitted_at=_now(),
                metadata=dict(metadata or {}),
            )
            future = self._executor.submit(
                self._execute,
                job_id,
                function,
                args,
                kwargs,
            )
            self._futures[job_id] = future
            return job_id

    def get(self, job_id: str) -> JobRecord:
        with self._lock:
            if job_id not in self._records:
                raise KeyError(job_id)
            record = self._records[job_id]
            return JobRecord(
                job_id=record.job_id,
                name=record.name,
                status=record.status,
                submitted_at=record.submitted_at,
                started_at=record.started_at,
                completed_at=record.completed_at,
                result=record.result,
                error=record.error,
                metadata=dict(record.metadata),
            )

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            if job_id not in self._futures:
                raise KeyError(job_id)
            cancelled = self._futures[job_id].cancel()
            if cancelled:
                record = self._records[job_id]
                record.status = JobStatus.CANCELLED
                record.completed_at = _now()
            return cancelled

    def list(self, limit: int = 100) -> list[JobRecord]:
        with self._lock:
            records = sorted(
                self._records.values(),
                key=lambda item: item.submitted_at,
                reverse=True,
            )[: max(int(limit), 0)]
            return [
                JobRecord(
                    job_id=record.job_id,
                    name=record.name,
                    status=record.status,
                    submitted_at=record.submitted_at,
                    started_at=record.started_at,
                    completed_at=record.completed_at,
                    result=record.result,
                    error=record.error,
                    metadata=dict(record.metadata),
                )
                for record in records
            ]

    def shutdown(self, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _execute(
        self,
        job_id: str,
        function: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        with self._lock:
            record = self._records[job_id]
            record.status = JobStatus.RUNNING
            record.started_at = _now()
        try:
            result = function(*args, **kwargs)
        except Exception as exc:
            with self._lock:
                record = self._records[job_id]
                record.status = JobStatus.FAILED
                record.error = f"{type(exc).__name__}: {exc}"
                record.completed_at = _now()
            raise
        with self._lock:
            record = self._records[job_id]
            record.status = JobStatus.COMPLETED
            record.result = result
            record.completed_at = _now()
        return result


def _now() -> datetime:
    return datetime.now(timezone.utc)
