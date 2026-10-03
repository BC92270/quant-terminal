from __future__ import annotations

import hashlib
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from scientific_research.measurement_robustness import (
    build_ecb_measurement_robustness_protocol,
    execute_ecb_measurement_robustness,
)
from scientific_research.mission_control_engine import build_mission_snapshot
from scientific_research.phase63_registry import Phase63Registry
from scientific_research.public_data_pipeline import (
    ECB_RTD_DATASET_ID,
    ECB_RTD_NOMINAL_SERIES_KEY,
    ECB_RTD_REAL_SERIES_KEY,
    PublicDataBundle,
    PublicDataError,
    PublicDataManifest,
    RetrievedSource,
    list_public_data_snapshots,
    load_public_data_snapshot,
    persist_public_data_bundle,
)


UTC = timezone.utc


class MeasurementRobustnessFixtureMixin:
    def setUp(self) -> None:
        self.rows = self.make_rows()
        self.manifest = {
            "snapshot_id": "ECBRTD-20260101T000000Z-aaaaaaaaaaaa",
            "created_at": "2026-01-01T00:00:00+00:00",
            "dataset_id": ECB_RTD_DATASET_ID,
            "dataset_label": "ECB RTD fixture",
            "row_count": len(self.rows),
            "start_reference_period": self.rows[0]["reference_period"],
            "end_reference_period": self.rows[-1]["reference_period"],
            "start_timestamp": self.rows[0]["timestamp"],
            "end_timestamp": self.rows[-1]["timestamp"],
            "dataset_fingerprint": "a" * 64,
            "dataset_file_sha256": "b" * 64,
            "parser_version": "SRB_ECB_RTD_FIRST_VINTAGE_V1",
            "revision_policy": "POINT_IN_TIME_VINTAGES",
            "availability_policy": "LATEST_REFERENCE_PERIOD_PER_UNIQUE_FIRST_RECORDED_RELEASE_EVENT",
            "availability_time_quality": "CONTROLLED",
            "price_series_id": ECB_RTD_REAL_SERIES_KEY,
            "anchor_series_id": ECB_RTD_NOMINAL_SERIES_KEY,
            "source_metadata": [],
            "warnings": [],
            "status": "VALIDATED",
            "production_status": "RESEARCH_ONLY",
        }
        self.contract = {
            "contract_id": "HDC-ECB-1",
            "question_id": "QUESTION-ECB-1",
            "experiment_id": "EXPERIMENT-ECB-1",
            "measurement_model_id": "MMODEL-ECB-1",
            "measurement_decision_id": "MDECISION-ECB-1",
            "observable_id": "OBS-ECB-WEDGE",
            "asset_identifier": ECB_RTD_DATASET_ID,
            "status": "VALIDATED",
            "revision_policy": "POINT_IN_TIME_VINTAGES",
            "price_field": "price",
            "fundamental_field": "fundamental_anchor",
            "event_time_field": "timestamp",
            "vintage_time_field": "vintage_timestamp",
            "train_fraction": 0.70,
            "forecast_horizon": 1,
            "production_status": "RESEARCH_ONLY",
        }
        self.audit = {
            "audit_id": "HDCAUDIT-ECB-1",
            "contract_id": "HDC-ECB-1",
            "overall_status": "VALIDATED",
            "point_in_time_status": "PASS",
            "production_status": "RESEARCH_ONLY",
        }
        self.experiment = {
            "experiment_id": "EXPERIMENT-ECB-1",
            "status": "READY",
            "transfer_verdict": "PARTIAL_TRANSFER",
            "experimental_family": "OU_MEAN_REVERTING_SDE",
            "code_policy": "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC",
            "seed": 17,
            "dataset_contract": {"train_fraction": 0.70, "max_rows": 250000},
        }

    @staticmethod
    def make_rows(count: int = 47) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        year = 2018
        month = 1
        for index in range(count):
            reference_period = f"{year:04d}-{month:02d}"
            event = datetime(year, month, 20, 10, 0, tzinfo=UTC).isoformat()
            nominal = 98.0 + 0.21 * index + 0.3 * math.sin(index / 4.0)
            real = nominal * math.exp(0.012 * math.sin(index / 3.2) + 0.004 * math.cos(index / 2.1))
            rows.append({
                "timestamp": event,
                "reference_period": reference_period,
                "price": round(real, 12),
                "fundamental_anchor": round(nominal, 12),
                "fundamental_release_timestamp": event,
                "vintage_timestamp": event,
                "price_valid_from": event,
                "anchor_valid_from": event,
                "price_series_id": ECB_RTD_REAL_SERIES_KEY,
                "anchor_series_id": ECB_RTD_NOMINAL_SERIES_KEY,
            })
            month += 1
            if month == 13:
                year += 1
                month = 1
        return rows

    def build_protocol(self):
        return build_ecb_measurement_robustness_protocol(
            snapshot_manifest=self.manifest,
            rows=self.rows,
            contract=self.contract,
            contract_audit=self.audit,
            experiment=self.experiment,
        )


class MeasurementRobustnessTests(MeasurementRobustnessFixtureMixin, unittest.TestCase):
    def test_frozen_protocol_executes_three_measurements_on_identical_support(self) -> None:
        protocol = self.build_protocol()
        report = execute_ecb_measurement_robustness(
            protocol=protocol,
            snapshot_manifest=self.manifest,
            rows=self.rows,
            experiment=self.experiment,
            executor_code_digest=protocol.executor_code_digest,
        )

        self.assertEqual(protocol.status, "FROZEN")
        self.assertEqual(len(protocol.variants), 3)
        self.assertEqual(report.gate_status, "PASS")
        self.assertEqual(report.common_support_status, "PASS")
        self.assertEqual(report.common_split_status, "PASS")
        self.assertEqual(report.point_in_time_status, "PASS")
        self.assertEqual(report.variant_count, 3)
        self.assertEqual(len({row.variant_id for row in report.variant_results}), 3)
        self.assertEqual(len({row.split_timestamp for row in report.variant_results}), 1)
        self.assertEqual(len({row.forecast_timestamps for row in report.variant_results}), 1)
        self.assertEqual(
            report.promising_variant_count + report.no_improvement_variant_count,
            3,
        )
        self.assertEqual(report.production_status, "RESEARCH_ONLY")

    def test_snapshot_change_after_freeze_fails_closed(self) -> None:
        protocol = self.build_protocol()
        changed_rows = [dict(row) for row in self.rows]
        changed_rows[-1]["price"] = float(changed_rows[-1]["price"]) + 0.5

        with self.assertRaisesRegex(ValueError, "changed after protocol freeze"):
            execute_ecb_measurement_robustness(
                protocol=protocol,
                snapshot_manifest=self.manifest,
                rows=changed_rows,
                experiment=self.experiment,
                executor_code_digest=protocol.executor_code_digest,
            )

    def test_variant_change_after_freeze_fails_closed(self) -> None:
        protocol = self.build_protocol()
        protocol_row = asdict(protocol)
        protocol_row["variants"] = protocol_row["variants"][:2]

        with self.assertRaisesRegex(ValueError, "allow-list"):
            execute_ecb_measurement_robustness(
                protocol=protocol_row,
                snapshot_manifest=self.manifest,
                rows=self.rows,
                experiment=self.experiment,
                executor_code_digest=protocol.executor_code_digest,
            )

    def test_protocol_and_report_registries_are_immutable_and_idempotent(self) -> None:
        protocol = self.build_protocol()
        report = execute_ecb_measurement_robustness(
            protocol=protocol,
            snapshot_manifest=self.manifest,
            rows=self.rows,
            experiment=self.experiment,
            executor_code_digest=protocol.executor_code_digest,
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase63Registry(directory)
            registry.save_measurement_protocol(protocol)
            registry.save_measurement_protocol(protocol)
            registry.save_measurement_report(report)
            registry.save_measurement_report(report)

            self.assertEqual(len(registry.list_measurement_protocols()), 1)
            self.assertEqual(len(registry.list_measurement_reports()), 1)
            with self.assertRaisesRegex(ValueError, "Immutable registry identity collision"):
                registry.save_measurement_report(replace(report, conclusion="FORGED_AFTER_REGISTRATION"))

    def test_mission_gate_requires_complete_predeclared_report(self) -> None:
        protocol = self.build_protocol()
        report = execute_ecb_measurement_robustness(
            protocol=protocol,
            snapshot_manifest=self.manifest,
            rows=self.rows,
            experiment=self.experiment,
            executor_code_digest=protocol.executor_code_digest,
        )
        base = {
            "captured_at": "2026-01-02T00:00:00+00:00",
            "questions": [{
                "question_id": "QUESTION-ECB-1",
                "experiment_id": "EXPERIMENT-ECB-1",
                "title": "ECB measurement robustness",
                "status": "PLANNED",
                "priority_score": 1.0,
            }],
            "experiment_specs": [self.experiment],
            "measurement_protocols": [asdict(protocol)],
            "measurement_reports": [asdict(report)],
        }
        mission = build_mission_snapshot(base, "QUESTION-ECB-1")
        gate = next(item for item in mission.gates if item.gate_id == "MEASUREMENT_ROBUSTNESS")
        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn(report.conclusion, gate.summary)

        ordinary_runs_only = dict(base)
        ordinary_runs_only["measurement_reports"] = []
        ordinary_runs_only["runs"] = [
            {"experiment_id": "EXPERIMENT-ECB-1", "stage": "HISTORICAL_OOS", "observable_id": "OBS-A"},
            {"experiment_id": "EXPERIMENT-ECB-1", "stage": "HISTORICAL_OOS", "observable_id": "OBS-B"},
        ]
        mission = build_mission_snapshot(ordinary_runs_only, "QUESTION-ECB-1")
        gate = next(item for item in mission.gates if item.gate_id == "MEASUREMENT_ROBUSTNESS")
        self.assertEqual(gate.status, "WARNING")


class PublicSnapshotReloadTests(MeasurementRobustnessFixtureMixin, unittest.TestCase):
    def _bundle(self) -> PublicDataBundle:
        raw_nominal = b"nominal fixture\n"
        raw_real = b"real fixture\n"
        nominal = RetrievedSource(
            source_id="ECB_RTD_NOMINAL_EER",
            url="https://example.test/nominal",
            terms_url="https://example.test/terms",
            retrieved_at="2026-01-01T00:00:00+00:00",
            sha256=hashlib.sha256(raw_nominal).hexdigest(),
            byte_count=len(raw_nominal),
            content=raw_nominal,
        )
        real = RetrievedSource(
            source_id="ECB_RTD_REAL_EER",
            url="https://example.test/real",
            terms_url="https://example.test/terms",
            retrieved_at="2026-01-01T00:00:00+00:00",
            sha256=hashlib.sha256(raw_real).hexdigest(),
            byte_count=len(raw_real),
            content=raw_real,
        )
        source_metadata = []
        for source in (nominal, real):
            row = asdict(source)
            row.pop("content", None)
            source_metadata.append(row)
        manifest = PublicDataManifest(
            snapshot_id="ECBRTD-20260101T000000Z-aaaaaaaaaaaa",
            created_at="2026-01-01T00:00:00+00:00",
            dataset_id=ECB_RTD_DATASET_ID,
            dataset_label="ECB RTD fixture",
            row_count=len(self.rows),
            start_reference_period=str(self.rows[0]["reference_period"]),
            end_reference_period=str(self.rows[-1]["reference_period"]),
            start_timestamp=str(self.rows[0]["timestamp"]),
            end_timestamp=str(self.rows[-1]["timestamp"]),
            dataset_fingerprint="a" * 64,
            parser_version="SRB_ECB_RTD_FIRST_VINTAGE_V1",
            revision_policy="POINT_IN_TIME_VINTAGES",
            availability_policy="LATEST_REFERENCE_PERIOD_PER_UNIQUE_FIRST_RECORDED_RELEASE_EVENT",
            availability_time_quality="CONTROLLED",
            price_series_id=ECB_RTD_REAL_SERIES_KEY,
            anchor_series_id=ECB_RTD_NOMINAL_SERIES_KEY,
            source_metadata=tuple(source_metadata),
            warnings=(),
            status="VALIDATED",
            production_status="RESEARCH_ONLY",
        )
        return PublicDataBundle(manifest=manifest, rows=tuple(self.rows), sources=(nominal, real))

    def test_persisted_snapshot_reloads_with_all_file_digests_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = persist_public_data_bundle(self._bundle(), directory)
            loaded = load_public_data_snapshot(directory, path.name)
            listed = list_public_data_snapshots(directory, dataset_id=ECB_RTD_DATASET_ID)

            self.assertEqual(loaded["verification_status"], "VERIFIED")
            self.assertEqual(len(loaded["rows"]), len(self.rows))
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["verification_status"], "VERIFIED")

    def test_persisted_snapshot_tampering_is_visible_and_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = persist_public_data_bundle(self._bundle(), directory)
            dataset_path = Path(path) / "contract_rows.csv"
            dataset_path.write_bytes(dataset_path.read_bytes() + b"tampered\n")

            with self.assertRaisesRegex(PublicDataError, "SHA-256"):
                load_public_data_snapshot(directory, path.name)
            listed = list_public_data_snapshots(directory, dataset_id=ECB_RTD_DATASET_ID)
            self.assertEqual(listed[0]["verification_status"], "INVALID")


if __name__ == "__main__":
    unittest.main()
