"""SQLite point-in-time store with explicit vintages and run metadata."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator
from uuid import uuid4

from fixed_income.contracts import DataClassification, DataPoint


SCHEMA_VERSION = 1


class PointInTimeStore:
    """Small production-shaped store suitable for local and validation use."""

    def __init__(self, path: str | Path = ".quant_data/fixed_income.sqlite3") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_observations (
                    series_id TEXT NOT NULL,
                    observation_time TEXT NOT NULL,
                    available_time TEXT NOT NULL,
                    vintage_id TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    classification TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    transformation TEXT NOT NULL,
                    ingested_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    PRIMARY KEY (series_id, observation_time, available_time, vintage_id)
                );

                CREATE INDEX IF NOT EXISTS idx_market_asof
                ON market_observations (series_id, available_time, observation_time);

                CREATE TABLE IF NOT EXISTS research_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    as_of_time TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT INTO schema_metadata(key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def insert_observations(self, observations: Iterable[DataPoint]) -> int:
        rows = []
        ingested_at = _iso(datetime.now(timezone.utc))
        for point in observations:
            value_json = json.dumps(point.value, sort_keys=True, separators=(",", ":"), default=str)
            digest = hashlib.sha256(
                (
                    point.series_id
                    + _iso(point.observation_time)
                    + _iso(point.available_time)
                    + point.vintage_id
                    + value_json
                    + point.source
                    + point.classification.value
                    + point.unit
                    + point.transformation
                ).encode("utf-8")
            ).hexdigest()
            rows.append(
                (
                    point.series_id,
                    _iso(point.observation_time),
                    _iso(point.available_time),
                    point.vintage_id,
                    value_json,
                    point.source,
                    point.classification.value,
                    point.unit,
                    point.transformation,
                    ingested_at,
                    digest,
                )
            )
        if not rows:
            return 0
        with self.connection() as connection:
            before = connection.total_changes
            connection.executemany(
                """
                INSERT INTO market_observations(
                    series_id, observation_time, available_time, vintage_id,
                    value_json, source, classification, unit, transformation,
                    ingested_at, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, observation_time, available_time, vintage_id)
                DO UPDATE SET
                    value_json=excluded.value_json,
                    source=excluded.source,
                    classification=excluded.classification,
                    unit=excluded.unit,
                    transformation=excluded.transformation,
                    ingested_at=excluded.ingested_at,
                    content_hash=excluded.content_hash
                """,
                rows,
            )
            return int(connection.total_changes - before)

    def latest_as_of(
        self,
        series_id: str,
        decision_time: datetime,
    ) -> DataPoint | None:
        cutoff = _iso(decision_time)
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM market_observations
                WHERE series_id = ?
                  AND available_time <= ?
                  AND observation_time <= ?
                ORDER BY observation_time DESC, available_time DESC, vintage_id DESC
                LIMIT 1
                """,
                (str(series_id), cutoff, cutoff),
            ).fetchone()
        return _row_to_point(row) if row is not None else None

    def history_as_of(
        self,
        series_id: str,
        decision_time: datetime,
    ) -> list[DataPoint]:
        cutoff = _iso(decision_time)
        with self.connection() as connection:
            rows = connection.execute(
                """
                WITH eligible AS (
                    SELECT *,
                           ROW_NUMBER() OVER (
                               PARTITION BY series_id, observation_time
                               ORDER BY available_time DESC, vintage_id DESC
                           ) AS vintage_rank
                    FROM market_observations
                    WHERE series_id = ?
                      AND available_time <= ?
                      AND observation_time <= ?
                )
                SELECT *
                FROM eligible
                WHERE vintage_rank = 1
                ORDER BY observation_time
                """,
                (str(series_id), cutoff, cutoff),
            ).fetchall()
        return [_row_to_point(row) for row in rows]

    def record_research_run(
        self,
        model_name: str,
        model_version: str,
        as_of_time: datetime,
        payload: dict[str, Any],
        inputs: Any,
        status: str = "COMPLETED",
    ) -> str:
        run_id = str(uuid4())
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        input_json = json.dumps(inputs, sort_keys=True, separators=(",", ":"), default=str)
        input_hash = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO research_runs(
                    run_id, created_at, as_of_time, model_name, model_version,
                    input_hash, payload_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _iso(datetime.now(timezone.utc)),
                    _iso(as_of_time),
                    str(model_name),
                    str(model_version),
                    input_hash,
                    payload_json,
                    str(status).upper(),
                ),
            )
        return run_id

    def health(self) -> dict[str, Any]:
        with self.connection() as connection:
            observation_count = int(
                connection.execute("SELECT COUNT(*) FROM market_observations").fetchone()[0]
            )
            run_count = int(connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0])
            version = connection.execute(
                "SELECT value FROM schema_metadata WHERE key='schema_version'"
            ).fetchone()[0]
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "path": str(self.path),
            "schema_version": int(version),
            "observations": observation_count,
            "research_runs": run_count,
            "integrity": integrity,
        }


def _row_to_point(row: sqlite3.Row) -> DataPoint:
    return DataPoint(
        series_id=row["series_id"],
        value=json.loads(row["value_json"]),
        observation_time=datetime.fromisoformat(row["observation_time"]),
        available_time=datetime.fromisoformat(row["available_time"]),
        source=row["source"],
        classification=DataClassification(row["classification"]),
        unit=row["unit"],
        vintage_id=row["vintage_id"],
        transformation=row["transformation"],
    )


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
