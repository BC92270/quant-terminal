from __future__ import annotations

import csv
import io
import json
import math
import tempfile
import unittest
import zipfile
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from scientific_research.experiment_registry import ExperimentRegistry
from scientific_research.replication_engine import (
    ALFRED_BIS_MARKETS,
    ALFRED_GRAPH_ACCESS_MODE,
    ALFRED_GRAPH_BATCH_SIZE,
    ALFRED_GRAPH_POINT_IN_TIME_POLICY,
    REPLICATION_EVENT_TIME_SUPPORT_POLICY,
    AlfredInitialReleaseRow,
    AlfredSeriesSnapshot,
    _digest,
    _parse_initial_release_zip,
    build_alfred_bis_replication_protocol,
    execute_alfred_bis_replication,
    fetch_alfred_graph_initial_release_series,
    load_persisted_alfred_snapshot_bundle,
)


def _month(index: int) -> date:
    year = 2014 + index // 12
    month = index % 12 + 1
    return date(year, month, 1)


def _next_release(period: date) -> date:
    if period.month == 12:
        return date(period.year + 1, 1, 20)
    return date(period.year, period.month + 1, 20)


def _zip_rows(series_id: str, rows: list[AlfredInitialReleaseRow]) -> bytes:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=("period_start_date", series_id, "realtime_start_date"))
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "period_start_date": row.period_start_date,
            series_id: row.value,
            "realtime_start_date": row.realtime_start_date,
        })
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", "Output Format: Observations, Initial Release Only")
        archive.writestr("initial_release.csv", out.getvalue())
    return buffer.getvalue()


def _snapshot(series_id: str, *, real: bool) -> AlfredSeriesSnapshot:
    rows: list[AlfredInitialReleaseRow] = []
    for index in range(132):
        period = _month(index)
        base = 100.0 + 0.04 * index
        wave = (2.2 if real else 1.5) * math.sin(index / (5.5 if real else 7.0))
        value = base + wave + (0.3 * math.cos(index / 2.9))
        rows.append(AlfredInitialReleaseRow(
            period.isoformat(),
            round(value, 8),
            _next_release(period).isoformat(),
        ))
    raw = _zip_rows(series_id, rows)
    return AlfredSeriesSnapshot(
        series_id=series_id,
        title=series_id,
        source_url=f"https://alfred.stlouisfed.org/series/downloaddata?seid={series_id}",
        retrieved_at="2026-10-02T00:00:00+00:00",
        observation_start=rows[0].period_start_date,
        observation_end=rows[-1].period_start_date,
        vintage_dates=tuple(row.realtime_start_date for row in rows),
        rows=tuple(rows),
        row_fingerprint=_digest([asdict(row) for row in rows]),
        raw_archives=(raw,),
    )


class IndependentReplicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.run = {
            "run_id": "RUN-REFERENCE",
            "experiment_id": "EXPERIMENT-1",
            "stage": "HISTORICAL_OOS",
            "verdict": "NO_OOS_IMPROVEMENT",
            "production_status": "RESEARCH_ONLY",
        }
        self.report = {
            "report_id": "MRR-REFERENCE",
            "experiment_id": "EXPERIMENT-1",
            "status": "COMPLETE",
            "gate_status": "PASS",
            "common_support_status": "PASS",
            "common_split_status": "PASS",
            "point_in_time_status": "PASS",
            "production_status": "RESEARCH_ONLY",
        }
        self.snapshots: dict[str, AlfredSeriesSnapshot] = {}
        for market in ALFRED_BIS_MARKETS.values():
            self.snapshots[market["real_series_id"]] = _snapshot(market["real_series_id"], real=True)
            self.snapshots[market["nominal_series_id"]] = _snapshot(market["nominal_series_id"], real=False)

    def test_protocol_is_frozen_before_data_and_declares_independence_limits(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)

        self.assertEqual(protocol.status, "FROZEN")
        self.assertEqual(protocol.execution_status, "NOT_RUN")
        self.assertEqual(protocol.point_in_time_status, "PENDING_EXECUTION")
        self.assertEqual(protocol.access_cost, "FREE")
        self.assertFalse(protocol.credentials_required)
        self.assertTrue(protocol.independence_dimensions["market"])
        self.assertTrue(protocol.independence_dimensions["data_lineage"])
        self.assertFalse(protocol.independence_dimensions["implementation"])
        self.assertFalse(protocol.independence_dimensions["investigator"])
        self.assertFalse(protocol.automatic_promotion_authorized)
        self.assertEqual(protocol.production_status, "RESEARCH_ONLY")
        self.assertEqual(protocol.event_time_support_policy, REPLICATION_EVENT_TIME_SUPPORT_POLICY)

    def test_graph_fallback_is_a_distinct_frozen_protocol(self) -> None:
        form_protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        graph_protocol = build_alfred_bis_replication_protocol(
            self.run,
            self.report,
            source_access_mode=ALFRED_GRAPH_ACCESS_MODE,
        )

        self.assertNotEqual(form_protocol.replication_id, graph_protocol.replication_id)
        self.assertNotEqual(form_protocol.protocol_fingerprint, graph_protocol.protocol_fingerprint)
        self.assertEqual(graph_protocol.source_access_mode, ALFRED_GRAPH_ACCESS_MODE)
        self.assertEqual(graph_protocol.point_in_time_policy, ALFRED_GRAPH_POINT_IN_TIME_POLICY)
        self.assertEqual(ALFRED_GRAPH_BATCH_SIZE, 12)
        self.assertEqual(graph_protocol.execution_status, "NOT_RUN")

    def test_graph_vintage_reconstruction_finds_exact_first_observed_day(self) -> None:
        observations = []
        for index in range(20):
            period = date(2020 + index // 12, index % 12 + 1, 1)
            release = date(2021, 1, 20) if index == 10 else _next_release(period)
            observations.append((period, release, 100.0 + index / 10.0))

        class FakeResponse:
            status_code = 200
            headers = {"content-type": "application/csv"}

            def __init__(self, content: bytes, url: str):
                self.content = content
                self.url = url

            def raise_for_status(self) -> None:
                return None

        class FakeSession:
            def get(self, url: str, **kwargs):
                params = kwargs["params"]
                vintages = str(params["vintage_date"]).split(",")
                series_ids = str(params["id"]).split(",")
                output = io.StringIO()
                writer = csv.writer(output)
                writer.writerow(["observation_date"] + [
                    f"{series_id}_{vintage.replace('-', '')}"
                    for series_id, vintage in zip(series_ids, vintages)
                ])
                for period, release, value in observations:
                    writer.writerow([
                        period.isoformat(),
                        *[
                            value if date.fromisoformat(vintage) >= release else "."
                            for vintage in vintages
                        ],
                    ])
                return FakeResponse(output.getvalue().encode("utf-8"), url)

        snapshot = fetch_alfred_graph_initial_release_series(
            "RBUSBIS",
            session=FakeSession(),
            discovery_start=date(2020, 1, 1),
            as_of_date=date(2021, 10, 31),
            batch_size=6,
        )

        self.assertEqual(snapshot.revision_policy, ALFRED_GRAPH_POINT_IN_TIME_POLICY)
        self.assertEqual(snapshot.point_in_time_status, "PASS")
        self.assertEqual(len(snapshot.rows), len(observations))
        self.assertEqual(
            [row.realtime_start_date for row in snapshot.rows],
            [release.isoformat() for _, release, _ in observations],
        )
        self.assertEqual(snapshot.response_metadata[0]["release_date_duplicate_rows"], "1")
        with zipfile.ZipFile(io.BytesIO(snapshot.raw_archives[0])) as archive:
            self.assertIn("request_manifest.json", archive.namelist())

    def test_default_graph_transport_uses_http2_and_closes_on_failure(self) -> None:
        session = MagicMock()
        session.get.side_effect = ValueError("synthetic parser failure")
        managed_client = MagicMock()
        managed_client.__enter__.return_value = session

        with patch(
            "scientific_research.replication_engine.httpx.Client",
            return_value=managed_client,
        ) as constructor:
            with self.assertRaisesRegex(ValueError, "synthetic parser failure"):
                fetch_alfred_graph_initial_release_series(
                    "RBUSBIS",
                    discovery_start=date(2020, 1, 1),
                    as_of_date=date(2021, 10, 31),
                )

        self.assertTrue(constructor.call_args.kwargs["http2"])
        self.assertEqual(
            constructor.call_args.kwargs["headers"],
            {"Accept": "text/csv,application/csv"},
        )
        managed_client.__exit__.assert_called_once()

    def test_legacy_protocol_without_event_time_policy_fails_before_fetch(self) -> None:
        protocol = replace(
            build_alfred_bis_replication_protocol(self.run, self.report),
            event_time_support_policy="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "co-release/backfill event-time policy"):
                execute_alfred_bis_replication(
                    protocol,
                    data_root=tmp,
                    fetcher=lambda series_id: self.fail(f"unexpected fetch for {series_id}"),
                )

    def test_co_released_rows_are_excluded_before_forecasting(self) -> None:
        snapshots: dict[str, AlfredSeriesSnapshot] = {}
        for series_id, snapshot in self.snapshots.items():
            rows = list(snapshot.rows)
            rows[10] = replace(rows[10], realtime_start_date=rows[11].realtime_start_date)
            raw = _zip_rows(series_id, rows)
            snapshots[series_id] = replace(
                snapshot,
                vintage_dates=tuple(row.realtime_start_date for row in rows),
                rows=tuple(rows),
                row_fingerprint=_digest([asdict(row) for row in rows]),
                raw_archives=(raw,),
            )

        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: snapshots[series_id],
            )

        self.assertEqual(completed.result_count, 9)
        for result in completed.results:
            self.assertEqual(result["raw_common_row_count"], 132)
            self.assertEqual(result["row_count"], 131)
            self.assertEqual(result["co_release_excluded_count"], 1)
            self.assertEqual(result["non_advancing_backfill_excluded_count"], 0)
            self.assertEqual(result["event_time_support_policy"], REPLICATION_EVENT_TIME_SUPPORT_POLICY)
            self.assertEqual(len(set(result["forecast_timestamps"])), result["test_size"])

    def test_non_advancing_backfills_are_excluded_from_event_time_support(self) -> None:
        snapshots: dict[str, AlfredSeriesSnapshot] = {}
        for series_id, snapshot in self.snapshots.items():
            rows = list(snapshot.rows)
            rows[5] = replace(rows[5], realtime_start_date="2025-02-20")
            raw = _zip_rows(series_id, rows)
            snapshots[series_id] = replace(
                snapshot,
                vintage_dates=tuple(row.realtime_start_date for row in rows),
                rows=tuple(rows),
                row_fingerprint=_digest([asdict(row) for row in rows]),
                raw_archives=(raw,),
            )

        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: snapshots[series_id],
            )

        for result in completed.results:
            self.assertEqual(result["row_count"], 131)
            self.assertEqual(result["co_release_excluded_count"], 0)
            self.assertEqual(result["non_advancing_backfill_excluded_count"], 1)

    def test_execution_persists_initial_release_snapshot_and_full_oos_results(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: self.snapshots[series_id],
            )
            snapshot_path = Path(tmp) / completed.snapshot_path

            self.assertTrue((snapshot_path / "manifest.json").exists())
            manifest = json.loads((snapshot_path / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["snapshot_fingerprint"], completed.source_snapshot_fingerprint)
            self.assertEqual(completed.execution_status, "COMPLETE")
            self.assertEqual(completed.point_in_time_status, "PASS")
            self.assertEqual(completed.independence_gate_status, "PASS")
            self.assertEqual(completed.result_count, 9)
            self.assertEqual(len(completed.results), 9)
            self.assertTrue(completed.execution_fingerprint.startswith("sha256:"))
            self.assertIn(completed.replication_outcome, {
                "CONSISTENT_NO_OOS_IMPROVEMENT",
                "CONSISTENT_PROMISING_REQUIRES_EXTERNAL_REVIEW",
                "MIXED_REPLICATION_EVIDENCE",
            })
            for result in completed.results:
                self.assertGreaterEqual(result["row_count"], 96)
                self.assertEqual(len(result["forecast_timestamps"]), result["test_size"])
                self.assertIn("holm_adjusted_p_value", result["forecast_comparison"])
                self.assertEqual(result["production_status"], "RESEARCH_ONLY")

    def test_json_reloaded_protocol_completes_lifecycle_transition(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        persisted_protocol = json.loads(json.dumps(asdict(protocol)))

        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                persisted_protocol,
                data_root=tmp,
                fetcher=lambda series_id: self.snapshots[series_id],
            )

        self.assertEqual(completed.execution_status, "COMPLETE")
        self.assertEqual(completed.lifecycle_history[-1]["to"], "COMPLETE")
        self.assertEqual(len(completed.lifecycle_history), 2)

    def test_persisted_snapshot_bundle_can_resume_without_network(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        required_series = tuple(self.snapshots)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: self.snapshots[series_id],
            )
            loaded = load_persisted_alfred_snapshot_bundle(
                tmp,
                completed.snapshot_id,
                expected_fingerprint=completed.source_snapshot_fingerprint,
                required_series=required_series,
            )

        self.assertEqual(set(loaded), set(required_series))
        self.assertEqual(loaded["RBUSBIS"].row_fingerprint, self.snapshots["RBUSBIS"].row_fingerprint)
        self.assertEqual(len(loaded["NBJPBIS"].rows), 132)

    def test_persisted_snapshot_resume_rejects_canonical_tampering(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: self.snapshots[series_id],
            )
            canonical_path = Path(tmp) / completed.snapshot_path / "RBUSBIS_canonical.csv"
            payload = canonical_path.read_text(encoding="utf-8")
            canonical_path.write_text(payload.replace(",100.3,", ",999.3,", 1), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "fingerprint mismatch"):
                load_persisted_alfred_snapshot_bundle(
                    tmp,
                    completed.snapshot_id,
                    required_series=tuple(self.snapshots),
                )

    def test_registry_requires_frozen_predeclaration_and_locks_completion(self) -> None:
        protocol = build_alfred_bis_replication_protocol(self.run, self.report)
        with tempfile.TemporaryDirectory() as tmp:
            completed = execute_alfred_bis_replication(
                protocol,
                data_root=tmp,
                fetcher=lambda series_id: self.snapshots[series_id],
            )
            registry = ExperimentRegistry(Path(tmp) / "registry")
            with self.assertRaisesRegex(ValueError, "persisted FROZEN"):
                registry.save_replication(completed)

            registry.save_replication(protocol)
            registry.save_replication(completed)
            self.assertEqual(registry.list_replications()[0]["execution_status"], "COMPLETE")
            with self.assertRaisesRegex(ValueError, "append-only"):
                registry.save_replication(replace(completed, replication_outcome="MUTATED"))

    def test_initial_release_zip_parser_rejects_duplicate_periods(self) -> None:
        row = AlfredInitialReleaseRow("2025-01-01", 101.0, "2025-02-20")
        raw = _zip_rows("RBUSBIS", [row, row])

        with self.assertRaisesRegex(Exception, "duplicates"):
            _parse_initial_release_zip(raw, "RBUSBIS")


if __name__ == "__main__":
    unittest.main()
