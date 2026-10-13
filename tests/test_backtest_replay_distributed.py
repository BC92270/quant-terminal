from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from backtest_universal.data_contracts import (
    DataCapability,
    DataMode,
    DatasetManifest,
    DatasetPartition,
    DatasetRegistry,
)
from backtest_universal.distributed import (
    DistributedJobSpec,
    JobState,
    LeaseConflict,
    LocalJobCoordinator,
)
from backtest_universal.orderbook import (
    BookDepth,
    BookEvent,
    BookEventKind,
    BookSide,
    OrderBookReplay,
    ReplayMode,
    SequenceIntegrityError,
)


UTC = timezone.utc
NOW = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()


def test_point_in_time_manifest_fails_closed_until_verified() -> None:
    partition = DatasetPartition(
        partition_id="spy-2024-01-02",
        uri="s3://vendor/spy/2024-01-02.parquet",
        sha256=_digest("partition"),
        observed_from=NOW,
        observed_to=NOW + timedelta(hours=6),
        available_at=NOW + timedelta(microseconds=1),
        rows=100,
    )
    manifest = DatasetManifest(
        dataset_id="vendor-spy-pit-1",
        vendor="Example Vendor",
        mode=DataMode.POINT_IN_TIME,
        capabilities=(DataCapability.BARS, DataCapability.CORPORATE_ACTIONS),
        partitions=(partition,),
        created_at=NOW + timedelta(days=1),
        schema_version="bars-1",
        license_id="LIC-1",
        signer="vendor-key-1",
        signature="signed-payload",
    )
    not_verified = manifest.assess((DataCapability.BARS,))
    assert not not_verified.ready
    assert "externally verified" in " ".join(not_verified.blockers)

    verified = manifest.assess(
        (DataCapability.BARS,),
        verified_manifest_sha256=manifest.content_sha256,
    )
    assert verified.ready
    assert verified.state == "CERTIFIED"
    assert DatasetManifest.from_dict(manifest.payload(include_signature=True)).content_sha256 == manifest.content_sha256

    missing = manifest.assess(
        (DataCapability.BARS, DataCapability.L3),
        verified_manifest_sha256=manifest.content_sha256,
    )
    assert not missing.ready
    assert missing.missing_capabilities == (DataCapability.L3,)


def test_dataset_registry_rejects_mutable_identity() -> None:
    partition = DatasetPartition(
        "p1", "memory://p1", _digest("p1"), NOW, NOW, NOW, 1
    )
    first = DatasetManifest(
        "data-1", "vendor", DataMode.SYNTHETIC, (DataCapability.BARS,),
        (partition,), NOW, "1"
    )
    second = DatasetManifest(
        "data-1", "vendor", DataMode.SYNTHETIC, (DataCapability.BARS,),
        (partition,), NOW + timedelta(seconds=1), "1"
    )
    registry = DatasetRegistry()
    registry.register(first)
    assert registry.register(first) is first
    with pytest.raises(ValueError, match="different immutable content"):
        registry.register(second)


def _event(
    sequence: int,
    kind: BookEventKind,
    side: BookSide | None = None,
    price: float | None = None,
    size: float | None = None,
    order_id: str = "",
) -> BookEvent:
    stamp = NOW + timedelta(microseconds=sequence)
    return BookEvent(
        instrument_id="XNAS:NVDA",
        sequence=sequence,
        event_time=stamp,
        available_at=stamp,
        kind=kind,
        side=side,
        price=price,
        size=size,
        order_id=order_id,
        source="ITCH",
    )


def test_l3_replay_is_deterministic_and_certification_is_explicit() -> None:
    events = (
        _event(10, BookEventKind.UPSERT, BookSide.BID, 100.0, 5.0, "b1"),
        _event(11, BookEventKind.UPSERT, BookSide.ASK, 101.0, 4.0, "a1"),
        _event(12, BookEventKind.TRADE, price=101.0, size=1.5, order_id="a1"),
    )
    hashes = []
    for _ in range(2):
        replay = OrderBookReplay(
            "XNAS:NVDA",
            depth=BookDepth.L3,
            mode=ReplayMode.REAL_REPLAY,
            source_authenticated=True,
        )
        report = replay.replay(events)
        snapshot = replay.snapshot()
        assert report.certified_real_replay
        assert snapshot.best_bid == 100.0
        assert snapshot.best_ask == 101.0
        assert snapshot.asks[0].size == pytest.approx(2.5)
        hashes.append(snapshot.state_sha256)
    assert hashes[0] == hashes[1]


def test_synthetic_book_never_claims_real_replay_and_gaps_are_rejected() -> None:
    replay = OrderBookReplay(
        "XNAS:NVDA", depth=BookDepth.L2, mode=ReplayMode.SYNTHETIC_MODEL
    )
    replay.apply(_event(1, BookEventKind.UPSERT, BookSide.BID, 100.0, 5.0))
    with pytest.raises(SequenceIntegrityError, match="sequence gap"):
        replay.apply(_event(3, BookEventKind.UPSERT, BookSide.ASK, 101.0, 4.0))
    assert replay.snapshot().replay_mode is ReplayMode.SYNTHETIC_MODEL


def _job(max_attempts: int = 2) -> DistributedJobSpec:
    return DistributedJobSpec(
        source_sha256=_digest("source"),
        dataset_sha256=_digest("dataset"),
        engine_sha256=_digest("engine"),
        parameters={"lookback": 20},
        seed=41,
        max_attempts=max_attempts,
    )


def test_local_coordinator_is_idempotent_fenced_and_content_addressed() -> None:
    coordinator = LocalJobCoordinator()
    spec = _job()
    first = coordinator.submit(spec, now=NOW)
    second = coordinator.submit(spec, now=NOW + timedelta(seconds=1))
    assert first.job_id == second.job_id
    assert coordinator.capability["distributed_cluster"] is False

    lease = coordinator.claim("worker-a", now=NOW + timedelta(seconds=2))
    assert lease is not None
    stale = type(lease)(**{**lease.__dict__, "token": "foreign"})
    with pytest.raises(LeaseConflict):
        coordinator.succeed(stale, b"result", now=NOW + timedelta(seconds=3))

    complete = coordinator.succeed(
        lease, b"result", now=NOW + timedelta(seconds=3)
    )
    assert complete.state is JobState.SUCCEEDED
    assert coordinator.artifacts.get(complete.result_sha256) == b"result"


def test_local_coordinator_bounded_retry_and_lease_expiry() -> None:
    coordinator = LocalJobCoordinator()
    record = coordinator.submit(_job(max_attempts=2), now=NOW)
    lease = coordinator.claim("worker-a", lease_seconds=1, now=NOW)
    assert lease is not None

    replacement = coordinator.claim(
        "worker-b", lease_seconds=5, now=NOW + timedelta(seconds=2)
    )
    assert replacement is not None
    assert replacement.attempt == 2
    with pytest.raises(LeaseConflict):
        coordinator.fail(lease, "late result", now=NOW + timedelta(seconds=2))

    failed = coordinator.fail(
        replacement, "deterministic failure", now=NOW + timedelta(seconds=3)
    )
    assert failed.state is JobState.FAILED
    assert coordinator.get(record.job_id).attempt == 2
