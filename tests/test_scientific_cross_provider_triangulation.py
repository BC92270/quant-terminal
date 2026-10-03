from __future__ import annotations

import csv
import io
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from scientific_research.cross_provider_triangulation import (
    CrossProviderDataError,
    OECD_BIS_REAL_MATRIX,
    OecdCsvPayload,
    execute_cross_provider_triangulation,
    freeze_cross_provider_triangulation,
    load_persisted_oecd_snapshot,
    parse_oecd_reer_csv,
)
from scientific_research.phase67_registry import Phase67Registry
from scientific_research.replication_engine import ALFRED_BIS_MARKETS


def _months(count: int = 140) -> list[str]:
    year, month = 2014, 1
    result = []
    for _ in range(count):
        result.append(date(year, month, 1).isoformat())
        month += 1
        if month == 13:
            month = 1
            year += 1
    return result


def _direct_reconciliation() -> dict[str, object]:
    return {
        "reconciliation_id": "DBR-P67-TEST",
        "replication_id": "IRP-P67-TEST",
        "protocol_version": "SRB_DIRECT_BIS_RECONCILIATION_V1",
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "source_integrity_status": "PASS",
        "coverage_status": "PASS",
        "point_in_time_status": "NOT_POINT_IN_TIME",
        "historical_evidence_eligible": False,
        "direct_snapshot_id": "BISREV-0123456789abcdef",
        "direct_snapshot_fingerprint": "sha256:direct-bis-snapshot",
        "series_matrix": ALFRED_BIS_MARKETS,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }


def _histories(*, divergent_market: str = "") -> tuple[bytes, dict[str, list[dict[str, object]]]]:
    periods = _months()
    direct: dict[str, list[dict[str, object]]] = {}
    oecd_values: dict[str, list[float]] = {}
    for market, metadata in OECD_BIS_REAL_MATRIX.items():
        bis_series = metadata["bis_series_id"]
        bis_level = 90.0 + 10.0 * (list(sorted(OECD_BIS_REAL_MATRIX)).index(market) + 1)
        oecd_level = bis_level * 1.37
        direct[bis_series] = []
        oecd_values[market] = []
        for index, period in enumerate(periods):
            if index:
                change = 0.004 * math.sin(index / 5.0) + 0.0015 * math.cos(index / 11.0)
                bis_level *= math.exp(change)
                oecd_change = -change if market == divergent_market else change + 0.00005 * math.sin(index / 3.0)
                oecd_level *= math.exp(oecd_change)
            direct[bis_series].append({"period_start_date": period, "value": round(bis_level, 12)})
            oecd_values[market].append(round(oecd_level, 12))

    fields = [
        "STRUCTURE", "STRUCTURE_ID", "STRUCTURE_NAME", "ACTION", "REF_AREA", "Reference area",
        "FREQ", "Frequency of observation", "MEASURE", "Measure", "UNIT_MEASURE", "Unit of measure",
        "ACTIVITY", "ADJUSTMENT", "TRANSFORMATION", "TIME_HORIZ", "METHODOLOGY",
        "Calculation methodology", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT",
        "DECIMALS", "BASE_PER",
    ]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    for market, metadata in sorted(OECD_BIS_REAL_MATRIX.items()):
        for period, value in zip(periods, oecd_values[market]):
            writer.writerow({
                "STRUCTURE": "DATAFLOW",
                "STRUCTURE_ID": "OECD.SDD.STES:DSD_STES@DF_FINMARK(4.0)",
                "STRUCTURE_NAME": "Financial market",
                "ACTION": "I",
                "REF_AREA": metadata["oecd_ref_area"],
                "Reference area": metadata["label"],
                "FREQ": "M",
                "Frequency of observation": "Monthly",
                "MEASURE": "CCRE",
                "Measure": "Real effective exchange rates - CPI based",
                "UNIT_MEASURE": "IX",
                "Unit of measure": "Index",
                "ACTIVITY": "_Z",
                "ADJUSTMENT": "_Z",
                "TRANSFORMATION": "_Z",
                "TIME_HORIZ": "_Z",
                "METHODOLOGY": "N",
                "Calculation methodology": "National",
                "TIME_PERIOD": period[:7],
                "OBS_VALUE": value,
                "OBS_STATUS": "A",
                "UNIT_MULT": "0",
                "DECIMALS": "2",
                "BASE_PER": "2015",
            })
    return handle.getvalue().encode("utf-8"), direct


class CrossProviderTriangulationTests(unittest.TestCase):
    def test_freeze_must_precede_network_and_registry_is_append_only(self) -> None:
        frozen = freeze_cross_provider_triangulation(
            _direct_reconciliation(),
            created_at="2026-10-04T10:00:00+00:00",
        )
        self.assertEqual(frozen.execution_status, "NOT_RUN")
        self.assertEqual(frozen.expected_series_count, 3)
        self.assertFalse(frozen.independence_dimensions["underlying_data_lineage"])
        self.assertEqual(frozen.point_in_time_status, "NOT_POINT_IN_TIME")
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase67Registry(directory)
            registry.save_triangulation(frozen)
            with self.assertRaisesRegex(ValueError, "cannot be edited"):
                registry.save_triangulation(replace(frozen, min_change_correlation=0.50))

    def test_concordant_histories_execute_and_every_snapshot_byte_is_verified(self) -> None:
        raw, direct = _histories()
        frozen = freeze_cross_provider_triangulation(
            _direct_reconciliation(),
            created_at="2026-10-04T10:00:00+00:00",
        )

        def direct_loader(*_: object, **__: object) -> dict[str, object]:
            return {"rows": direct}

        with tempfile.TemporaryDirectory() as directory:
            registry = Phase67Registry(directory)
            registry.save_triangulation(frozen)
            completed = execute_cross_provider_triangulation(
                frozen,
                data_root=directory,
                csv_fetcher=lambda: OecdCsvPayload(
                    raw_csv=raw,
                    retrieved_at="2026-10-04T10:05:00+00:00",
                    response_metadata={"etag": "test"},
                ),
                direct_loader=direct_loader,
            )
            registry.save_triangulation(completed)
            self.assertEqual(completed.triangulation_outcome, "CONCORDANT")
            self.assertEqual(completed.comparable_series_count, 3)
            self.assertEqual(completed.concordant_series_count, 3)
            self.assertEqual(completed.divergent_series_count, 0)
            self.assertTrue(all(item["change_correlation"] > 0.99 for item in completed.series_results))
            verified = load_persisted_oecd_snapshot(
                directory,
                completed.oecd_snapshot_id,
                expected_fingerprint=completed.oecd_snapshot_fingerprint,
            )
            self.assertEqual(verified["base_period"], "2015")
            self.assertEqual(set(verified["rows"]), {"GB", "JP", "US"})
            with self.assertRaisesRegex(ValueError, "append-only"):
                registry.save_triangulation(replace(completed, concordant_series_count=0))
            canonical = Path(directory) / completed.oecd_snapshot_path / "US_canonical.csv"
            canonical.write_text(
                canonical.read_text(encoding="utf-8")
                + "2099-01-01,100.0,A,USA,CCRE,N,2015\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(CrossProviderDataError, "canonical"):
                load_persisted_oecd_snapshot(
                    directory,
                    completed.oecd_snapshot_id,
                    expected_fingerprint=completed.oecd_snapshot_fingerprint,
                )

    def test_divergence_is_retained_as_a_valid_scientific_outcome(self) -> None:
        raw, direct = _histories(divergent_market="JP")
        frozen = freeze_cross_provider_triangulation(
            _direct_reconciliation(),
            created_at="2026-10-04T10:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            completed = execute_cross_provider_triangulation(
                frozen,
                data_root=directory,
                csv_fetcher=lambda: OecdCsvPayload(raw, "2026-10-04T10:05:00+00:00", {}),
                direct_loader=lambda *_args, **_kwargs: {"rows": direct},
            )
        self.assertEqual(completed.triangulation_outcome, "MEASUREMENT_DIVERGENCE")
        self.assertEqual(completed.comparability_status, "PASS")
        japan = next(item for item in completed.series_results if item["market"] == "JP")
        self.assertEqual(japan["status"], "MEASUREMENT_DIVERGENCE")
        self.assertFalse(japan["threshold_checks"]["change_correlation"])
        self.assertFalse(completed.historical_evidence_eligible)
        self.assertEqual(completed.production_status, "RESEARCH_ONLY")

    def test_parser_rejects_non_normal_observation(self) -> None:
        raw, _ = _histories()
        text = raw.decode("utf-8").replace(",A,0,2,2015", ",P,0,2,2015", 1)
        with self.assertRaisesRegex(CrossProviderDataError, "OBS_STATUS"):
            parse_oecd_reer_csv(text.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
