from __future__ import annotations

import tempfile
import unittest
import hashlib
import inspect
from dataclasses import asdict, replace
from datetime import datetime, timedelta

from scientific_research.direct_bis_reconciliation import (
    direct_bis_reconciliation_fingerprint,
    freeze_direct_bis_reconciliation,
    validate_completed_direct_bis_reconciliation,
)
from scientific_research.phase68_registry import Phase68Registry
from scientific_research.phase63_registry import RegistryCorruptionError
from scientific_research.prospective_observation import (
    build_research_closure_dossier,
    evaluate_prospective_observation_program,
    freeze_prospective_observation_program,
    validate_prospective_observation_program,
)


def _direct(
    *,
    identity: str = "DBR-SEED",
    fingerprint: str = "snapshot-a",
    frozen_at: str | None = None,
    retrieved_at: str = "2026-10-03T12:00:00+00:00",
    latest_period: str = "2026-08-01",
) -> dict[str, object]:
    retrieved = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
    frozen = (
        datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
        if frozen_at is not None
        else retrieved - timedelta(minutes=10)
    )
    digest = lambda value: "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    source = {
        "protocol_version": "SRB_INDEPENDENT_REPLICATION_V1",
        "replication_id": "IRP-PROSPECTIVE-1",
        "execution_status": "COMPLETE",
        "point_in_time_status": "PASS",
        "snapshot_id": "ALFRED-PROSPECTIVE-1",
        "source_snapshot_fingerprint": digest("reference-snapshot"),
        "series_matrix": {
            "US": {
                "label": "United States",
                "real_series_id": "RBUSBIS",
                "nominal_series_id": "NBUSBIS",
            },
        },
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }
    frozen = freeze_direct_bis_reconciliation(
        source,
        created_at=frozen.isoformat(),
    )
    snapshot_fingerprint = digest(fingerprint)
    snapshot_id = f"BISREV-{snapshot_fingerprint.split(':', 1)[1][:16]}"
    results = tuple({
        "series_id": series_id,
        "overlap_row_count": 40,
        "exact_match_row_count": 39,
        "revised_row_count": 1,
        "comparison_fingerprint": digest(f"comparison-{identity}-{series_id}"),
        "direct_row_fingerprint": digest(f"rows-{identity}-{series_id}"),
        "history_semantics": "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE",
        "historical_evidence_eligible": False,
    } for series_id in ("RBUSBIS", "NBUSBIS"))
    row = {
        **asdict(frozen),
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "source_integrity_status": "PASS",
        "coverage_status": "PASS",
        "reconciliation_status": "RECONCILED_WITH_REVISIONS",
        "direct_snapshot_id": snapshot_id,
        "direct_snapshot_path": f"public_data/bis_revised_history/{snapshot_id}",
        "direct_snapshot_fingerprint": snapshot_fingerprint,
        "raw_archive_sha256": digest(f"raw-{identity}"),
        "raw_archive_bytes": 100,
        "raw_csv_bytes": 500,
        "retrieved_at": retrieved_at,
        "completed_at": (retrieved + timedelta(minutes=5)).isoformat(),
        "response_metadata": {},
        "latest_period": latest_period,
        "series_count": 2,
        "total_overlap_rows": 80,
        "total_exact_match_rows": 78,
        "total_revised_rows": 2,
        "series_results": results,
    }
    row["reconciliation_fingerprint"] = direct_bis_reconciliation_fingerprint(row)
    row["lifecycle_history"] = tuple(row["lifecycle_history"]) + ({
        "at": row["completed_at"],
        "event": "DIRECT_BIS_ACQUISITION_AND_RECONCILIATION_COMPLETE",
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "source_integrity_status": "PASS",
        "coverage_status": "PASS",
        "reconciliation_status": row["reconciliation_status"],
        "direct_snapshot_id": row["direct_snapshot_id"],
        "direct_snapshot_fingerprint": row["direct_snapshot_fingerprint"],
        "historical_evidence_eligible": False,
        "production_status": "RESEARCH_ONLY",
    },)
    return row


class ProspectiveObservationProgramTests(unittest.TestCase):
    def test_freeze_starts_only_with_the_next_real_month(self) -> None:
        program = freeze_prospective_observation_program(
            _direct(),
            created_at="2026-10-04T08:30:00+00:00",
        )

        self.assertEqual(program.first_future_window, "2026-11-01T00:00:00+00:00")
        self.assertFalse(program.historical_backfill_permitted)
        self.assertFalse(program.automatic_execution_authorized)
        self.assertEqual(validate_prospective_observation_program(program)["status"], "PASS")
        state = evaluate_prospective_observation_program(
            program,
            [_direct()],
            as_of="2026-10-04T09:00:00+00:00",
        )
        self.assertEqual(state["program_status"], "WAITING_NEXT_WINDOW")
        self.assertFalse(state["observation_due"])
        self.assertEqual(state["maturity"]["distinct_snapshots"], 1)

    def test_due_missed_and_duplicate_windows_are_retained_without_backfill(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        november = _direct(
            identity="DBR-NOVEMBER",
            fingerprint="snapshot-b",
            retrieved_at="2026-11-12T10:00:00+00:00",
            latest_period="2026-09-01",
        )
        november_duplicate = _direct(
            identity="DBR-NOVEMBER-DUP",
            fingerprint="snapshot-b",
            retrieved_at="2026-11-20T10:00:00+00:00",
            latest_period="2026-09-01",
        )
        state = evaluate_prospective_observation_program(
            program,
            [seed, november, november_duplicate],
            as_of="2027-01-18T10:00:00+00:00",
        )

        self.assertEqual([row["status"] for row in state["calendar"]], [
            "CAPTURED", "MISSED_RETAINED", "OPEN_DUE",
        ])
        self.assertEqual(state["captured_windows"], 1)
        self.assertEqual(state["missed_windows"], 1)
        self.assertEqual(state["duplicate_window_observations"], 1)
        self.assertEqual(state["maturity"]["distinct_snapshots"], 2)
        self.assertEqual(state["program_status"], "ACTIVE_WITH_RETAINED_GAPS")
        self.assertTrue(state["observation_due"])
        self.assertFalse(state["calendar"][1]["backfillable"])

    def test_only_one_distinct_observation_per_month_advances_maturity(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        same_month = [
            _direct(
                identity=f"DBR-NOVEMBER-{index:02d}",
                fingerprint=f"snapshot-{index:02d}",
                retrieved_at=f"2026-11-{index + 1:02d}T10:00:00+00:00",
                latest_period=f"2025-{index + 1:02d}-01",
            )
            for index in range(11)
        ]

        state = evaluate_prospective_observation_program(
            program,
            [seed, *same_month],
            as_of="2026-11-30T20:00:00+00:00",
        )

        self.assertEqual(state["captured_windows"], 1)
        self.assertEqual(state["duplicate_window_observations"], 10)
        self.assertEqual(state["maturity"]["distinct_snapshots"], 2)
        self.assertEqual(state["maturity"]["distinct_latest_periods"], 2)
        self.assertEqual(state["maturity"]["status"], "WARMING_UP")

    def test_exact_monthly_ledger_reaches_real_12_12_300_maturity(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        windows = (
            ("2026-11-10T10:00:00+00:00", "2026-09-01"),
            ("2026-12-10T10:00:00+00:00", "2026-10-01"),
            ("2027-01-10T10:00:00+00:00", "2026-11-01"),
            ("2027-02-10T10:00:00+00:00", "2026-12-01"),
            ("2027-03-10T10:00:00+00:00", "2027-01-01"),
            ("2027-04-10T10:00:00+00:00", "2027-02-01"),
            ("2027-05-10T10:00:00+00:00", "2027-03-01"),
            ("2027-06-10T10:00:00+00:00", "2027-04-01"),
            ("2027-07-10T10:00:00+00:00", "2027-05-01"),
            ("2027-08-10T10:00:00+00:00", "2027-06-01"),
            ("2027-09-10T10:00:00+00:00", "2027-07-01"),
        )
        observations = [
            _direct(
                identity=f"DBR-MONTH-{index:02d}",
                fingerprint=f"snapshot-month-{index:02d}",
                retrieved_at=retrieved_at,
                latest_period=latest_period,
            )
            for index, (retrieved_at, latest_period) in enumerate(windows, start=1)
        ]

        state = evaluate_prospective_observation_program(
            program,
            [seed, *observations],
            as_of="2027-09-30T20:00:00+00:00",
        )

        self.assertEqual(state["captured_windows"], 11)
        self.assertEqual(state["missed_windows"], 0)
        self.assertEqual(state["maturity"]["distinct_snapshots"], 12)
        self.assertEqual(state["maturity"]["distinct_latest_periods"], 12)
        self.assertGreaterEqual(state["maturity"]["span_days"], 300)
        self.assertEqual(state["maturity"]["status"], "READY_FOR_FORWARD_VINTAGE_STUDY")
        self.assertEqual(state["program_status"], "MATURE_FOR_FORWARD_VINTAGE_STUDY")

    def test_monthly_credit_tie_breaks_by_retrieval_then_reconciliation_id(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        first = _direct(
            identity="DBR-TIE-A",
            fingerprint="snapshot-tie-a",
            retrieved_at="2026-11-12T10:00:00+00:00",
            latest_period="2026-09-01",
        )
        second = _direct(
            identity="DBR-TIE-B",
            fingerprint="snapshot-tie-b",
            frozen_at="2026-11-12T09:51:00+00:00",
            retrieved_at="2026-11-12T10:00:00+00:00",
            latest_period="2026-10-01",
        )

        state = evaluate_prospective_observation_program(
            program,
            [seed, first, second],
            as_of="2026-11-20T00:00:00+00:00",
        )

        expected = min(str(first["reconciliation_id"]), str(second["reconciliation_id"]))
        self.assertEqual(state["calendar"][0]["credited_reconciliation_id"], expected)
        self.assertEqual(state["duplicate_window_observations"], 1)

    def test_late_completion_cannot_repair_a_missed_window(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        late = _direct(
            identity="DBR-LATE-NOVEMBER",
            fingerprint="snapshot-late",
            retrieved_at="2026-11-30T23:59:00+00:00",
            latest_period="2026-09-01",
        )
        late["completed_at"] = "2026-12-01T00:01:00+00:00"
        late["lifecycle_history"] = (
            late["lifecycle_history"][0],
            {**late["lifecycle_history"][1], "at": late["completed_at"]},
        )

        state = evaluate_prospective_observation_program(
            program,
            [seed, late],
            as_of="2026-12-15T00:00:00+00:00",
        )

        self.assertEqual(state["calendar"][0]["status"], "MISSED_RETAINED_LATE_COMPLETION")
        self.assertEqual(state["calendar"][0]["credited_observation_count"], 0)
        self.assertEqual(state["late_window_observations"], 1)
        self.assertEqual(state["maturity"]["distinct_snapshots"], 1)

    def test_malformed_completed_observation_never_advances_maturity(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        malformed = _direct(
            identity="DBR-MALFORMED",
            fingerprint="snapshot-malformed",
            retrieved_at="2026-11-12T10:00:00+00:00",
            latest_period="2026-09-01",
        )
        malformed["raw_archive_sha256"] = ""
        malformed["series_results"] = ()
        with self.assertRaisesRegex(ValueError, "raw_archive_sha256|series coverage"):
            evaluate_prospective_observation_program(
                program,
                [seed, malformed],
                as_of="2026-11-15T00:00:00+00:00",
            )

    def test_latest_period_must_be_a_real_month_start(self) -> None:
        invalid = _direct(latest_period="2026-99-99")
        with self.assertRaisesRegex(ValueError, "ISO-8601 date"):
            freeze_prospective_observation_program(invalid)
        invalid = _direct(latest_period="2026-08-17")
        with self.assertRaisesRegex(ValueError, "first day"):
            freeze_prospective_observation_program(invalid)

    def test_registry_and_fingerprint_tamper_fail_closed(self) -> None:
        program = freeze_prospective_observation_program(
            _direct(),
            created_at="2026-10-04T08:30:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase68Registry(directory)
            registry.save_program(program)
            registry.save_program(program)
            with self.assertRaisesRegex(ValueError, "fingerprint|append-only"):
                registry.save_program(replace(program, warnings=("tampered",)))
        tampered = replace(program, prospective_min_span_days=1)
        self.assertEqual(validate_prospective_observation_program(tampered)["status"], "FAIL")
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            evaluate_prospective_observation_program(
                tampered,
                [_direct()],
                as_of="2026-10-04T09:00:00+00:00",
            )

    def test_program_contract_rejects_every_governance_tamper_dimension(self) -> None:
        program = freeze_prospective_observation_program(
            _direct(),
            created_at="2026-10-04T08:30:00+00:00",
        )
        cases = {
            "cadence": replace(program, cadence="DAILY"),
            "identity": replace(program, program_id="POP-FOREIGN"),
            "seed": replace(program, seed_snapshot_id="BISREV-FOREIGN"),
            "float threshold": replace(program, prospective_min_span_days=300.0),
            "boolean threshold": replace(program, prospective_min_distinct_snapshots=True),
            "automatic execution": replace(program, automatic_execution_authorized=True),
            "production": replace(program, production_status="LIVE"),
            "lifecycle": replace(
                program,
                lifecycle_history=program.lifecycle_history + ({"event": "UNDECLARED_EVENT"},),
            ),
            "warnings": replace(program, warnings=("weakened boundary",)),
        }

        for label, tampered in cases.items():
            with self.subTest(label=label):
                self.assertEqual(validate_prospective_observation_program(tampered)["status"], "FAIL")

    def test_registry_rejects_a_second_distinct_program_for_same_replication(self) -> None:
        seed = _direct()
        first = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        second = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:31:00+00:00")
        self.assertNotEqual(first.program_id, second.program_id)

        with tempfile.TemporaryDirectory() as directory:
            registry = Phase68Registry(directory)
            registry.save_program(first)
            with self.assertRaisesRegex(ValueError, "already governs this replication"):
                registry.save_program(second)

    def test_completed_direct_seed_validator_rejects_protocol_hash_count_and_lifecycle_tamper(self) -> None:
        valid = _direct()
        self.assertEqual(validate_completed_direct_bis_reconciliation(valid)["status"], "PASS")
        cases = {
            "protocol": {**valid, "protocol_fingerprint": ""},
            "hash": {**valid, "raw_archive_sha256": "not-a-sha256"},
            "fractional count": {**valid, "series_count": 2.0},
            "boolean count": {**valid, "total_overlap_rows": True},
            "lifecycle": {**valid, "lifecycle_history": tuple(valid["lifecycle_history"]) + ({"event": "EXTRA"},)},
        }
        for label, tampered in cases.items():
            with self.subTest(label=label):
                self.assertEqual(validate_completed_direct_bis_reconciliation(tampered)["status"], "FAIL")

    def test_corrupt_program_registry_is_never_treated_as_empty_or_overwritten(self) -> None:
        program = freeze_prospective_observation_program(
            _direct(),
            created_at="2026-10-04T08:30:00+00:00",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase68Registry(directory)
            path = registry.paths["programs"]
            path.write_text('{"truncated":', encoding="utf-8")
            before = path.read_bytes()
            with self.assertRaises(RegistryCorruptionError):
                registry.list_programs()
            with self.assertRaises(RegistryCorruptionError):
                registry.save_program(program)
            self.assertEqual(path.read_bytes(), before)

    def test_closure_dossier_separates_review_from_longitudinal_maturity(self) -> None:
        seed = _direct()
        pre_program = _direct(
            identity="DBR-PRE-PROGRAM",
            fingerprint="snapshot-pre-program",
            retrieved_at="2026-09-03T12:00:00+00:00",
            latest_period="2026-07-01",
        )
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        dossier = build_research_closure_dossier(
            program,
            [pre_program, seed],
            as_of="2026-10-04T09:00:00+00:00",
            mission_status="READY_FOR_REVIEW",
            core_study_status="READY_FOR_REVIEW",
            mission_gate_count=22,
        )

        self.assertEqual(dossier["current_study_review_status"], "CORE_DOSSIER_READY_FOR_REVIEW")
        self.assertEqual(dossier["longitudinal_program_status"], "WAITING_NEXT_WINDOW")
        self.assertFalse(dossier["evidence_boundaries"]["prospective_vintage_study_ready"])
        self.assertFalse(dossier["evidence_boundaries"]["production_authorized"])
        self.assertEqual(
            dossier["evidence_boundaries"]["historical_oos_result_status"],
            "NOT_EVALUATED_BY_THIS_EXPORT",
        )
        self.assertEqual(dossier["prospective_observation_inventory"][0]["program_role"], "FROZEN_SEED")
        self.assertEqual(len(dossier["prospective_observation_inventory"]), 1)
        self.assertIn("calendar_fingerprint", dossier["schedule"])
        self.assertEqual(len(dossier["dossier_fingerprint"]), 64)

    def test_closure_dossier_excludes_cross_provider_production_overclaim(self) -> None:
        seed = _direct()
        program = freeze_prospective_observation_program(seed, created_at="2026-10-04T08:30:00+00:00")
        triangulation = {
            "triangulation_id": "CPT-MALICIOUS",
            "replication_id": seed["replication_id"],
            "direct_reconciliation_id": seed["reconciliation_id"],
            "direct_snapshot_id": seed["direct_snapshot_id"],
            "direct_snapshot_fingerprint": seed["direct_snapshot_fingerprint"],
            "protocol_version": "SRB_CROSS_PROVIDER_TRIANGULATION_V1",
            "execution_status": "COMPLETE",
            "source_integrity_status": "PASS",
            "coverage_status": "PASS",
            "comparability_status": "PASS",
            "triangulation_outcome": "CONCORDANT",
            "history_semantics": "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE",
            "point_in_time_status": "NOT_POINT_IN_TIME",
            "historical_evidence_eligible": False,
            "automatic_promotion_authorized": False,
            "production_status": "LIVE",
            "expected_series_count": 3,
            "source_series_count": 3,
            "oecd_snapshot_id": "OECDCCRE-MALICIOUS",
            "oecd_snapshot_fingerprint": "sha256:" + "1" * 64,
            "oecd_snapshot_path": "public_data/oecd/malicious",
            "raw_csv_sha256": "sha256:" + "2" * 64,
            "triangulation_fingerprint": "sha256:" + "3" * 64,
            "retrieved_at": "2026-10-04T08:00:00+00:00",
            "series_results": [
                {
                    "status": "CONCORDANT",
                    "comparison_fingerprint": "sha256:" + str(index) * 64,
                    "historical_evidence_eligible": False,
                }
                for index in (4, 5, 6)
            ],
        }

        dossier = build_research_closure_dossier(
            program,
            [seed],
            as_of="2026-10-04T09:00:00+00:00",
            triangulation_records=[triangulation],
        )

        self.assertEqual(dossier["latest_cross_provider_outcome"], "NOT_AVAILABLE")
        self.assertEqual(dossier["latest_cross_provider_artifact_verification"], "NOT_AVAILABLE")
        self.assertIsNone(dossier["latest_cross_provider_artifact"]["triangulation_id"])

        valid_id = "OECDCCRE-0123456789abcdef"
        admissible = {
            **triangulation,
            "triangulation_id": "CPT-ADMISSIBLE",
            "production_status": "RESEARCH_ONLY",
            "oecd_snapshot_id": valid_id,
            "oecd_snapshot_path": f"public_data/oecd_reer_current_history/{valid_id}",
            "series_results": [
                {
                    "market": market,
                    "status": "CONCORDANT",
                    "comparison_fingerprint": "sha256:" + str(index) * 64,
                    "historical_evidence_eligible": False,
                }
                for market, index in (("GB", 4), ("JP", 5), ("US", 6))
            ],
        }
        dossier = build_research_closure_dossier(
            program,
            [seed],
            as_of="2026-10-04T09:00:00+00:00",
            triangulation_records=[triangulation, admissible],
        )
        self.assertEqual(dossier["latest_cross_provider_outcome"], "CONCORDANT")
        self.assertEqual(dossier["latest_cross_provider_artifact"]["triangulation_id"], "CPT-ADMISSIBLE")

    def test_handoff_chart_and_accessibility_helpers_preserve_phase68_contract(self) -> None:
        from scientific_research_lab import (
            _closure_dossier_markdown,
            _finite_time_chart,
            _inject_css,
        )

        frame = _finite_time_chart(
            ["2026-02-01", "invalid", "2026-01-01", "2026-03-01"],
            {"value": [2.0, 3.0, float("inf"), None]},
        )
        self.assertEqual(len(frame), 1)
        self.assertEqual(float(frame.iloc[0]["value"]), 2.0)
        self.assertTrue(frame.index.is_monotonic_increasing)

        dossier = {
            "dossier_fingerprint": "dossier-fingerprint",
            "artifact_inventory_fingerprint": "inventory-fingerprint",
            "verification_scope": "INDEX_ONLY_REFERENCED_STATE_AND_CONTENT_ADDRESSED_ARTIFACTS_REQUIRED",
            "generated_at": "2027-01-02T00:00:00+00:00",
            "question_id": "QUESTION-1",
            "mission_snapshot_id": "MISSION-1",
            "mission_status": "READY_FOR_REVIEW",
            "core_study_status": "READY_FOR_REVIEW",
            "current_study_review_status": "CORE_DOSSIER_READY_FOR_REVIEW",
            "longitudinal_program_status": "ACTIVE_WITH_RETAINED_GAPS",
            "production_status": "RESEARCH_ONLY",
            "program_id": "POP-1",
            "program_protocol_fingerprint": "program-fingerprint",
            "replication_id": "IRP-1",
            "seed": {
                "reconciliation_id": "DBR-SEED",
                "snapshot_id": "BISREV-SEED",
                "snapshot_fingerprint": "seed-fingerprint",
            },
            "forward_vintage_maturity": {
                "distinct_snapshots": 1,
                "required_distinct_snapshots": 12,
                "distinct_latest_periods": 1,
                "required_distinct_latest_periods": 12,
                "span_days": 0,
                "required_span_days": 300,
            },
            "schedule": {
                "next_observation_at": "2027-01-01T00:00:00+00:00",
                "missed_windows": 1,
                "calendar_fingerprint": "calendar-fingerprint",
            },
            "historical_artifact_index": {
                "report_id": "MRR-1",
                "protocol_id": "MRP-1",
                "conclusion": "CONSISTENT_NO_OOS_IMPROVEMENT",
            },
            "mission_gate_index": [{
                "gate_id": "PROSPECTIVE_OBSERVATION_PROTOCOL",
                "status": "SATISFIED",
                "artifact_refs": ["POP-1"],
            }],
            "prospective_observation_inventory": [{
                "reconciliation_id": "DBR-SEED",
                "program_role": "FROZEN_SEED",
                "schedule_window": "SEED",
                "schedule_credit": True,
                "raw_archive_sha256": "raw-hash",
                "reconciliation_fingerprint": "reconciliation-hash",
            }],
            "latest_cross_provider_artifact": {
                "triangulation_id": "CPT-1",
                "oecd_snapshot_id": "OECD-1",
            },
            "latest_cross_provider_artifact_verification": "BASIC_PROVENANCE_CHECK_PASS_NOT_FULL_RECOMPUTATION",
            "prospective_calendar": [{
                "window": "2026-12",
                "status": "MISSED_RETAINED",
                "reconciliation_ids": [],
            }],
            "timing_authority": "RUNTIME_ASSERTED_NOT_THIRD_PARTY_ATTESTED",
            "evidence_boundaries": {
                "peer_review_established": False,
                "production_authorized": False,
            },
            "closure_interpretation": "No production or scientific-truth claim.",
        }
        handoff = _closure_dossier_markdown(dossier)
        for expected in (
            "Question: `QUESTION-1`",
            "Mission snapshot: `MISSION-1`",
            "CONSISTENT_NO_OOS_IMPROVEMENT",
            "PROSPECTIVE_OBSERVATION_PROTOCOL",
            "DBR-SEED",
            "CPT-1",
            "MISSED_RETAINED",
            "production authorized: **FALSE**",
        ):
            self.assertIn(expected, handoff)

        css_source = inspect.getsource(_inject_css)
        self.assertIn("focus-visible", css_source)
        self.assertIn("max-width: 900px", css_source)
        self.assertIn("prefers-reduced-motion", css_source)

    def test_freeze_rejects_point_in_time_and_promotion_overclaims(self) -> None:
        invalid = _direct()
        invalid["point_in_time_status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "point-in-time boundary"):
            freeze_prospective_observation_program(invalid)
        invalid = _direct()
        invalid["automatic_promotion_authorized"] = True
        with self.assertRaisesRegex(ValueError, "promotion lock"):
            freeze_prospective_observation_program(invalid)


if __name__ == "__main__":
    unittest.main()
