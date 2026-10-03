from __future__ import annotations

import csv
import io
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scientific_research.direct_bis_reconciliation import (
    BisArchivePayload,
    DirectBisDataError,
    build_prospective_vintage_summary,
    execute_direct_bis_reconciliation,
    freeze_direct_bis_reconciliation,
    load_persisted_direct_bis_snapshot,
    parse_bis_eer_archive,
)
from scientific_research.phase66_registry import Phase66Registry
from scientific_research.replication_engine import ALFRED_BIS_MARKETS, AlfredInitialReleaseRow


FIELDS = (
    "STRUCTURE",
    "STRUCTURE_ID",
    "ACTION",
    "FREQ:Frequency",
    "EER_TYPE:Type",
    "EER_BASKET:Basket",
    "REF_AREA:Reference area",
    "TIME_PERIOD:Time period or range",
    "OBS_VALUE:Observation Value",
    "TIME_FORMAT:Time Format",
    "COLLECTION:Collection Indicator",
    "TITLE_TS:Title (tseries level)",
    "UNIT_MEASURE:Unit of measure",
    "OBS_STATUS:Observation Status",
    "OBS_CONF:Observation confidentiality",
    "OBS_PRE_BREAK:Pre-Break Observation",
)


def _months(count: int = 130) -> list[str]:
    rows = []
    year, month = 2015, 1
    for _ in range(count):
        rows.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return rows


def _archive(*, abnormal: bool = False) -> tuple[bytes, dict[str, dict[str, float]]]:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=FIELDS)
    writer.writeheader()
    values: dict[str, dict[str, float]] = {}
    for market, metadata in sorted(ALFRED_BIS_MARKETS.items()):
        for kind, series_id, label in (
            ("R", metadata["real_series_id"], "Real"),
            ("N", metadata["nominal_series_id"], "Nominal"),
        ):
            values[series_id] = {}
            for index, period in enumerate(_months()):
                value = 80.0 + index / 10.0 + (3.0 if kind == "R" else 0.0)
                values[series_id][f"{period}-01"] = value
                writer.writerow({
                    "STRUCTURE": "dataflow",
                    "STRUCTURE_ID": "BIS:WS_EER(1.0): Effective exchange rates",
                    "ACTION": "I",
                    "FREQ:Frequency": "M: Monthly",
                    "EER_TYPE:Type": f"{kind}: {label}",
                    "EER_BASKET:Basket": "B: Broad (64 economies)",
                    "REF_AREA:Reference area": f"{market}: {metadata['label']}",
                    "TIME_PERIOD:Time period or range": period,
                    "OBS_VALUE:Observation Value": f"{value:.4f}",
                    "TIME_FORMAT:Time Format": "",
                    "COLLECTION:Collection Indicator": "A: Average of observations through period",
                    "TITLE_TS:Title (tseries level)": f"{metadata['label']} - {label} - Broad (64 economies)",
                    "UNIT_MEASURE:Unit of measure": "",
                    "OBS_STATUS:Observation Status": (
                        "P: Provisional value" if abnormal and index == 0 and market == "GB" and kind == "R" else "A: Normal value"
                    ),
                    "OBS_CONF:Observation confidentiality": "",
                    "OBS_PRE_BREAK:Pre-Break Observation": "",
                })
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("WS_EER_csv_flat.csv", handle.getvalue().encode("utf-8"))
    return raw.getvalue(), values


def _replication() -> dict[str, object]:
    return {
        "replication_id": "IRP-DIRECT-TEST",
        "protocol_version": "SRB_INDEPENDENT_REPLICATION_V1",
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "point_in_time_status": "PASS",
        "snapshot_id": "ALFREDIR-0123456789abcdef",
        "source_snapshot_fingerprint": "sha256:reference",
        "series_matrix": ALFRED_BIS_MARKETS,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }


class DirectBisReconciliationTests(unittest.TestCase):
    def test_freeze_precedes_acquisition_and_registry_is_append_only(self) -> None:
        frozen = freeze_direct_bis_reconciliation(
            _replication(),
            created_at="2026-01-15T12:00:00+00:00",
        )
        self.assertEqual(frozen.execution_status, "NOT_RUN")
        self.assertEqual(frozen.point_in_time_status, "NOT_POINT_IN_TIME")
        self.assertFalse(frozen.historical_evidence_eligible)
        self.assertEqual(frozen.expected_series_count, 6)
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase66Registry(directory)
            forged = freeze_direct_bis_reconciliation(
                _replication(),
                created_at="2026-01-15T12:01:00+00:00",
            )
            with self.assertRaisesRegex(ValueError, "persisted FROZEN before acquisition"):
                registry.save_reconciliation(replace(forged, status="COMPLETE", execution_status="COMPLETE"))
            registry.save_reconciliation(frozen)

    def test_realistic_archive_executes_six_series_revision_ledger(self) -> None:
        raw, direct_values = _archive()
        frozen = freeze_direct_bis_reconciliation(
            _replication(),
            created_at="2026-01-15T12:00:00+00:00",
        )

        def reference_loader(**_: object) -> dict[str, object]:
            result = {}
            for series_id, values in direct_values.items():
                selected = sorted(values)[-40:]
                result[series_id] = SimpleNamespace(rows=tuple(
                    AlfredInitialReleaseRow(
                        period_start_date=period,
                        value=value - (0.5 if index % 2 else 0.0),
                        realtime_start_date=period,
                    )
                    for index, (period, value) in enumerate((period, values[period]) for period in selected)
                ))
            return result

        with tempfile.TemporaryDirectory() as directory:
            completed = execute_direct_bis_reconciliation(
                frozen,
                data_root=directory,
                archive_fetcher=lambda: BisArchivePayload(
                    raw_archive=raw,
                    retrieved_at="2026-01-15T12:05:00+00:00",
                    response_metadata={"etag": "test"},
                ),
                reference_loader=reference_loader,
            )
            registry = Phase66Registry(directory)
            registry.save_reconciliation(frozen)
            registry.save_reconciliation(completed)
            self.assertEqual(completed.execution_status, "COMPLETE")
            self.assertEqual(completed.series_count, 6)
            self.assertEqual(completed.total_overlap_rows, 240)
            self.assertEqual(completed.total_revised_rows, 120)
            self.assertEqual(completed.reconciliation_status, "RECONCILED_WITH_REVISIONS")
            self.assertEqual(completed.prospective_vintage_status, "WARMING_UP")
            self.assertFalse(completed.historical_evidence_eligible)
            artifact = Path(directory) / completed.direct_snapshot_path
            self.assertTrue((artifact / "manifest.json").is_file())
            self.assertTrue((artifact / "WS_EER_csv_flat.zip").is_file())
            verified = load_persisted_direct_bis_snapshot(
                directory,
                completed.direct_snapshot_id,
                series_matrix=ALFRED_BIS_MARKETS,
                expected_fingerprint=completed.direct_snapshot_fingerprint,
            )
            self.assertEqual(verified["snapshot_fingerprint"], completed.direct_snapshot_fingerprint)
            with self.assertRaisesRegex(ValueError, "append-only"):
                registry.save_reconciliation(replace(completed, total_revised_rows=0))
            canonical = artifact / "RBUSBIS_canonical.csv"
            canonical.write_text(
                canonical.read_text(encoding="utf-8")
                + "2099-01-01,100.0,A,A: Average of observations through period,Tampered title\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DirectBisDataError, "canonical"):
                load_persisted_direct_bis_snapshot(
                    directory,
                    completed.direct_snapshot_id,
                    series_matrix=ALFRED_BIS_MARKETS,
                    expected_fingerprint=completed.direct_snapshot_fingerprint,
                )

    def test_parser_rejects_non_normal_required_observation(self) -> None:
        raw, _ = _archive(abnormal=True)
        with self.assertRaisesRegex(DirectBisDataError, "not normal"):
            parse_bis_eer_archive(raw, ALFRED_BIS_MARKETS)

    def test_forward_readiness_counts_only_distinct_observed_contents(self) -> None:
        records = []
        for index in range(12):
            month = index + 1
            records.append({
                "replication_id": "IRP-1",
                "execution_status": "COMPLETE",
                "direct_snapshot_fingerprint": f"sha256:{index:064x}",
                "direct_snapshot_id": f"BISREV-{index:016x}",
                "retrieved_at": datetime(2026, month, 1, tzinfo=timezone.utc).isoformat(),
                "latest_period": date(2025 + (month // 12), (month % 12) + 1, 1).isoformat(),
            })
        records.append(dict(records[-1]))
        summary = build_prospective_vintage_summary(records, replication_id="IRP-1")

        self.assertEqual(summary["status"], "READY_FOR_FORWARD_VINTAGE_STUDY")
        self.assertEqual(summary["distinct_snapshots"], 12)
        self.assertEqual(summary["distinct_latest_periods"], 12)
        self.assertGreaterEqual(summary["span_days"], 300)
        self.assertFalse(summary["historical_backfill_permitted"])


if __name__ == "__main__":
    unittest.main()
