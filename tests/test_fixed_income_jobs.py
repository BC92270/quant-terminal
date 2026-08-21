import time

from fixed_income.services.jobs import JobManager, JobStatus


def _wait(manager: JobManager, job_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = manager.get(job_id)
        if record.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            return record
        time.sleep(0.01)
    raise AssertionError("job did not complete before timeout")


def test_background_job_success() -> None:
    manager = JobManager(max_workers=1, max_jobs=5)
    try:
        job_id = manager.submit("sum", lambda left, right: left + right, 20, 22)
        record = _wait(manager, job_id)
        assert record.status == JobStatus.COMPLETED
        assert record.result == 42
        assert record.started_at is not None
        assert record.completed_at is not None
    finally:
        manager.shutdown()


def test_background_job_failure_is_observable() -> None:
    manager = JobManager(max_workers=1, max_jobs=5)
    try:
        def fail() -> None:
            raise ValueError("controlled failure")

        job_id = manager.submit("failure", fail)
        record = _wait(manager, job_id)
        assert record.status == JobStatus.FAILED
        assert "controlled failure" in record.error
    finally:
        manager.shutdown()
