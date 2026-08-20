from datetime import datetime, timezone
import json

from fixed_income.contracts import DataClassification, DataPoint
from fixed_income.data.store import PointInTimeStore
from fixed_income.governance.audit import AuditTrail, ModelRegistry


def _point(value: float, available_day: int, vintage: str) -> DataPoint:
    return DataPoint(
        series_id="SERIES_A",
        value=value,
        observation_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        available_time=datetime(2026, 1, available_day, tzinfo=timezone.utc),
        source="unit-test",
        classification=DataClassification.OBSERVED,
        unit="bp",
        vintage_id=vintage,
    )


def test_point_in_time_store_respects_vintages(tmp_path) -> None:
    store = PointInTimeStore(tmp_path / "pit.sqlite3")
    store.insert_observations([_point(100.0, 5, "v1"), _point(120.0, 20, "v2")])

    early = store.latest_as_of(
        "SERIES_A", datetime(2026, 1, 10, tzinfo=timezone.utc)
    )
    late = store.latest_as_of(
        "SERIES_A", datetime(2026, 1, 25, tzinfo=timezone.utc)
    )
    assert early is not None and early.value == 100.0
    assert late is not None and late.value == 120.0

    run_id = store.record_research_run(
        model_name="credit-score",
        model_version="1.0.0",
        as_of_time=datetime(2026, 1, 10, tzinfo=timezone.utc),
        payload={"score": 72.0},
        inputs={"issuer": "TEST"},
    )
    health = store.health()
    assert run_id
    assert health["integrity"] == "ok"
    assert health["observations"] == 2
    assert health["research_runs"] == 1


def test_audit_hash_chain_detects_tampering(tmp_path) -> None:
    path = tmp_path / "audit.jsonl"
    trail = AuditTrail(path)
    trail.append("analyst", "CREATE", "decision", "d1", {"score": 70})
    trail.append("risk", "APPROVE", "decision", "d1", {"limit": 1_000_000})
    assert trail.verify()["ok"]

    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["actor"] = "tampered"
    lines[0] = json.dumps(event)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    verification = trail.verify()
    assert not verification["ok"]
    assert "mismatch" in verification["error"]


def test_model_registry_tracks_approval_state(tmp_path) -> None:
    registry = ModelRegistry(tmp_path / "models.json")
    registry.register(
        "portfolio-optimizer",
        "1.0.0",
        "quant-research",
        "VALIDATION",
        {"tests": "passed"},
    )
    registry.register(
        "portfolio-optimizer",
        "1.0.1",
        "independent-risk",
        "APPROVED",
        {"tests": "passed", "challenger": "reviewed"},
    )
    approved = registry.approved()
    assert len(approved) == 1
    assert approved[0]["version"] == "1.0.1"
