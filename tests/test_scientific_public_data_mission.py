from __future__ import annotations

import unittest
import copy
import hashlib
from dataclasses import asdict

from scientific_research.direct_bis_reconciliation import (
    direct_bis_reconciliation_fingerprint,
    freeze_direct_bis_reconciliation,
)
from scientific_research.mission_control_engine import (
    build_epistemic_timeline,
    build_mission_snapshot,
    build_run_room,
)
from scientific_research.prospective_observation import freeze_prospective_observation_program


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _complete_direct(
    replication: dict[str, object],
    *,
    token: str,
    frozen_at: str,
    retrieved_at: str,
    completed_at: str,
    latest_period: str = "2025-12-01",
) -> dict[str, object]:
    frozen = freeze_direct_bis_reconciliation(replication, created_at=frozen_at)
    snapshot_fingerprint = _sha256(f"direct-snapshot-{token}")
    snapshot_id = f"BISREV-{snapshot_fingerprint.split(':', 1)[1][:16]}"
    results = tuple({
        "series_id": series_id,
        "overlap_row_count": 40,
        "exact_match_row_count": 39,
        "revised_row_count": 1,
        "comparison_fingerprint": _sha256(f"comparison-{token}-{series_id}"),
        "direct_row_fingerprint": _sha256(f"direct-rows-{token}-{series_id}"),
        "history_semantics": "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE",
        "historical_evidence_eligible": False,
    } for series_id in ("RBUSBIS", "NBUSBIS"))
    row: dict[str, object] = {
        **asdict(frozen),
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "completed_at": completed_at,
        "source_integrity_status": "PASS",
        "coverage_status": "PASS",
        "reconciliation_status": "RECONCILED_WITH_REVISIONS",
        "direct_snapshot_id": snapshot_id,
        "direct_snapshot_path": f"public_data/bis_revised_history/{snapshot_id}",
        "direct_snapshot_fingerprint": snapshot_fingerprint,
        "raw_archive_sha256": _sha256(f"raw-{token}"),
        "raw_archive_bytes": 100,
        "raw_csv_bytes": 500,
        "retrieved_at": retrieved_at,
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
        "at": completed_at,
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


def _complete_snapshot(
    *,
    point_in_time_status: str = "PASS",
    revision_risk_status: str = "CONTROLLED",
) -> dict[str, object]:
    primary_run = {
        "run_id": "RUN-PRIMARY",
        "experiment_id": "EXPERIMENT-1",
        "stage": "HISTORICAL_OOS",
        "observable_id": "OBS-PRIMARY",
        "dataset_manifest_id": "MANIFEST-1",
        "created_at": "2026-01-03T00:00:00+00:00",
        "verdict": "PASS",
        "forecast_timestamps": ["2025-11-01", "2025-12-01"],
        "actual_values": [0.2, 0.1],
        "candidate_errors": [0.1, -0.1],
        "forecast_trace_fingerprint": "sha256:forecast-primary",
        "selection_context": {
            "snapshot_id": "SELECTION-1",
            "total_attempts": 1,
            "observed_screens": 1,
            "selection_risk": "LOW",
        },
        "production_status": "RESEARCH_ONLY",
    }
    robustness_run = {
        "run_id": "RUN-COMPETITOR",
        "experiment_id": "EXPERIMENT-1",
        "stage": "HISTORICAL_OOS",
        "observable_id": "OBS-COMPETITOR",
        "dataset_manifest_id": "MANIFEST-COMPETITOR",
        "created_at": "2026-01-02T00:00:00+00:00",
        "verdict": "PASS",
        "forecast_timestamps": ["2025-11-01"],
        "actual_values": [0.2],
        "candidate_errors": [0.1],
        "forecast_trace_fingerprint": "sha256:forecast-competitor",
        "production_status": "RESEARCH_ONLY",
    }
    snapshot = {
        "captured_at": "2026-01-05T00:00:00+00:00",
        "registry_health": [],
        "questions": [
            {
                "question_id": "QUESTION-1",
                "plan_id": "PLAN-1",
                "experiment_id": "EXPERIMENT-1",
                "selected_observable_id": "OBS-PRIMARY",
                "title": "Housing residual persistence",
                "status": "PLANNED",
            }
        ],
        "plans": [
            {
                "plan_id": "PLAN-1",
                "question_id": "QUESTION-1",
                "selected_hypothesis_id": "HYPOTHESIS-1",
                "blockers": [],
            }
        ],
        "hypotheses": [
            {
                "hypothesis_id": "HYPOTHESIS-1",
                "question_id": "QUESTION-1",
                "label": "Mean-reverting housing residual",
                "priority_score": 1.0,
            }
        ],
        "experiment_specs": [
            {
                "experiment_id": "EXPERIMENT-1",
                "status": "READY",
                "transfer_verdict": "PARTIAL_TRANSFER",
                "transfer_audit_id": "TRANSFER-1",
                "experimental_family": "OU_MEAN_REVERTING_SDE",
                "code_policy": "NO_EVAL_NO_EXEC",
            }
        ],
        "measurement_models": [
            {
                "measurement_model_id": "MODEL-1",
                "question_id": "QUESTION-1",
                "primary_observable_id": "OBS-PRIMARY",
            }
        ],
        "measurement_decisions": [
            {
                "decision_id": "DECISION-1",
                "question_id": "QUESTION-1",
                "selected_observable_id": "OBS-PRIMARY",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "observables": [
            {
                "observable_id": "OBS-PRIMARY",
                "question_id": "QUESTION-1",
                "label": "Price-to-rent residual",
                "status": "SELECTED",
            },
            {
                "observable_id": "OBS-COMPETITOR",
                "question_id": "QUESTION-1",
                "label": "Competing residual",
                "status": "RETAINED_COMPETITOR",
            },
        ],
        "evidence": [
            {
                "evidence_id": "EVIDENCE-1",
                "question_id": "QUESTION-1",
                "status": "GROUNDED_REVIEWED",
                "claim_ids": ["CLAIM-1"],
                "mechanism_keys": [],
                "semantic_entity_ids": [],
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "evidence_assessments": [],
        "evidence_syntheses": [],
        "data_contracts": [
            {
                "contract_id": "CONTRACT-1",
                "question_id": "QUESTION-1",
                "observable_id": "OBS-PRIMARY",
                "status": "VALIDATED",
                "market": "US housing",
                "anchor_family": "rent",
                "created_at": "2026-01-01T00:00:00+00:00",
                "blockers": [],
            }
        ],
        "contract_audits": [
            {
                "audit_id": "AUDIT-1",
                "contract_id": "CONTRACT-1",
                "overall_status": "VALIDATED",
                "point_in_time_status": "PASS",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "dataset_manifests": [
            {
                "manifest_id": "MANIFEST-1",
                "contract_id": "CONTRACT-1",
                "status": "VALIDATED_WITH_WARNINGS",
                "valid_row_count": 120,
                "materialized_fingerprint": "sha256:materialized",
                "point_in_time_status": point_in_time_status,
                "revision_risk_status": revision_risk_status,
                "created_at": "2026-01-02T00:00:00+00:00",
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "attempts": [
            {
                "attempt_id": "ATTEMPT-1",
                "experiment_id": "EXPERIMENT-1",
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "runs": [primary_run, robustness_run],
        "capsules": [
            {
                "capsule_id": "CAPSULE-1",
                "run_id": "RUN-PRIMARY",
                "status": "COMPLETE",
                "replay_grade": "EXACT",
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "measurement_protocols": [
            {
                "protocol_id": "MRP-1",
                "question_id": "QUESTION-1",
                "experiment_id": "EXPERIMENT-1",
                "snapshot_id": "PUBLIC-SNAPSHOT-1",
                "snapshot_fingerprint": "sha256:public-snapshot",
                "executor_code_digest": "sha256:measurement-executor",
                "status": "FROZEN",
                "production_status": "RESEARCH_ONLY",
                "variants": [
                    {"variant_id": "MEASURE-A", "counts_as_distinct_measurement": True},
                    {"variant_id": "MEASURE-B", "counts_as_distinct_measurement": True},
                    {"variant_id": "MEASURE-C", "counts_as_distinct_measurement": True},
                ],
            }
        ],
        "measurement_reports": [
            {
                "report_id": "MRR-1",
                "protocol_id": "MRP-1",
                "question_id": "QUESTION-1",
                "experiment_id": "EXPERIMENT-1",
                "snapshot_id": "PUBLIC-SNAPSHOT-1",
                "snapshot_fingerprint": "sha256:public-snapshot",
                "executor_code_digest": "sha256:measurement-executor",
                "status": "COMPLETE",
                "gate_status": "PASS",
                "common_support_status": "PASS",
                "common_split_status": "PASS",
                "point_in_time_status": "PASS",
                "variant_count": 3,
                "conclusion": "CONSISTENT_NO_OOS_IMPROVEMENT",
                "production_status": "RESEARCH_ONLY",
                "variant_results": [
                    {"variant_id": "MEASURE-A", "verdict": "NO_OOS_IMPROVEMENT"},
                    {"variant_id": "MEASURE-B", "verdict": "NO_OOS_IMPROVEMENT"},
                    {"variant_id": "MEASURE-C", "verdict": "NO_OOS_IMPROVEMENT"},
                ],
            }
        ],
        "reviews": [{
            "review_id": "REVIEW-1",
            "run_id": "RUN-PRIMARY",
            "review_protocol_version": "SRB_COUNCIL_REVIEW_V2",
            "review_mode": "COMPUTATIONAL_COUNCIL_DOSSIER",
            "human_attestation_status": "NOT_A_HUMAN_PANEL",
            "decision_scope": "RESEARCH_WORKFLOW_ONLY",
            "gate_eligibility": "ELIGIBLE_COMPUTATIONAL_REVIEW",
            "measurement_report_id": "MRR-1",
            "evidence_refs": ["RUN-PRIMARY", "MRR-1"],
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }],
        "replications": [
            {
                "replication_id": "REPLICATION-1",
                "experiment_id": "EXPERIMENT-1",
                "protocol_version": "SRB_INDEPENDENT_REPLICATION_V1",
                "event_time_support_policy": "STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_EXCLUDE_NON_ADVANCING_BACKFILLS",
                "reference_run_id": "RUN-PRIMARY",
                "execution_status": "COMPLETE",
                "independence_gate_status": "PASS",
                "independence_dimensions": {
                    "market": True,
                    "period": False,
                    "implementation": False,
                },
                "point_in_time_status": "PASS",
                "snapshot_id": "ALFRED-SNAPSHOT-1",
                "source_snapshot_fingerprint": _sha256("replication-source"),
                "series_matrix": {
                    "US": {
                        "label": "United States",
                        "real_series_id": "RBUSBIS",
                        "nominal_series_id": "NBUSBIS",
                    },
                },
                "execution_fingerprint": "sha256:replication-execution",
                "replication_outcome": "NO_OOS_IMPROVEMENT",
                "automatic_promotion_authorized": False,
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "cross_runtime_verifications": [{
            "verification_id": "XRV-1",
            "replication_id": "REPLICATION-1",
            "protocol_version": "SRB_CROSS_RUNTIME_VERIFICATION_V1",
            "execution_status": "COMPLETE",
            "implementation_gate_status": "PASS",
            "parity_status": "PASS",
            "challenge_fingerprint": "sha256:challenge",
            "engine_source_fingerprint": "sha256:source",
            "engine_build_fingerprint": "sha256:build",
            "result_fingerprint": "sha256:result",
            "result_count": 9,
            "matched_result_count": 9,
            "discrepancy_count": 0,
            "discrepancies": [],
            "independence_dimensions": {
                "implementation": True,
                "investigator": False,
            },
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }],
        "direct_source_reconciliations": [{
            "reconciliation_id": "DBR-1",
            "replication_id": "REPLICATION-1",
            "protocol_version": "SRB_DIRECT_BIS_RECONCILIATION_V1",
            "status": "COMPLETE",
            "execution_status": "COMPLETE",
            "source_integrity_status": "PASS",
            "coverage_status": "PASS",
            "reconciliation_status": "RECONCILED_WITH_REVISIONS",
            "direct_snapshot_id": "BISREV-1",
            "direct_snapshot_fingerprint": "sha256:direct-snapshot",
            "raw_archive_sha256": "sha256:raw-archive",
            "reconciliation_fingerprint": "sha256:reconciliation",
            "history_semantics": "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE",
            "point_in_time_status": "NOT_POINT_IN_TIME",
            "historical_evidence_eligible": False,
            "expected_series_count": 1,
            "series_count": 1,
            "min_overlap_rows": 24,
            "created_at": "2026-01-03T23:50:00+00:00",
            "protocol_frozen_at": "2026-01-03T23:55:00+00:00",
            "retrieved_at": "2026-01-04T00:00:00+00:00",
            "completed_at": "2026-01-04T00:05:00+00:00",
            "latest_period": "2025-12-01",
            "prospective_min_distinct_snapshots": 12,
            "prospective_min_distinct_latest_periods": 12,
            "prospective_min_span_days": 300,
            "series_results": [{
                "series_id": "RBUSBIS",
                "overlap_row_count": 40,
                "comparison_fingerprint": "sha256:comparison",
                "historical_evidence_eligible": False,
            }],
            "independence_dimensions": {
                "distribution_channel": True,
                "source_host": True,
                "underlying_data_lineage": False,
                "methodology": False,
                "point_in_time": False,
                "investigator": False,
            },
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }],
        "cross_provider_triangulations": [{
            "triangulation_id": "CPT-1",
            "replication_id": "REPLICATION-1",
            "direct_reconciliation_id": "DBR-1",
            "protocol_version": "SRB_CROSS_PROVIDER_TRIANGULATION_V1",
            "execution_status": "COMPLETE",
            "source_integrity_status": "PASS",
            "coverage_status": "PASS",
            "comparability_status": "PASS",
            "triangulation_outcome": "CONCORDANT",
            "oecd_snapshot_id": "OECDCCRE-1",
            "oecd_snapshot_fingerprint": "sha256:oecd-snapshot",
            "raw_csv_sha256": "sha256:oecd-raw",
            "triangulation_fingerprint": "sha256:triangulation",
            "history_semantics": "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE",
            "point_in_time_status": "NOT_POINT_IN_TIME",
            "historical_evidence_eligible": False,
            "expected_series_count": 3,
            "source_series_count": 3,
            "comparable_series_count": 3,
            "concordant_series_count": 3,
            "divergent_series_count": 0,
            "min_overlap_rows": 120,
            "retrieved_at": "2026-01-04T01:00:00+00:00",
            "series_results": [
                {
                    "market": market,
                    "status": "CONCORDANT",
                    "overlap_row_count": 392,
                    "comparison_fingerprint": f"sha256:comparison-{market}",
                    "historical_evidence_eligible": False,
                    "threshold_checks": {
                        "change_correlation": True,
                        "sign_agreement": True,
                        "mean_absolute_change_gap": True,
                    },
                }
                for market in ("GB", "JP", "US")
            ],
            "independence_dimensions": {
                "distribution_channel": True,
                "source_host": True,
                "provider_organization": True,
                "underlying_data_lineage": False,
                "methodology": False,
                "point_in_time": False,
                "investigator": False,
            },
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }],
        "failures": [],
        "surprises": [],
        "budgets": [],
        "break_diagnostics": [],
    }
    governed_direct = _complete_direct(
        snapshot["replications"][0],
        token="primary",
        frozen_at="2026-01-03T23:50:00+00:00",
        retrieved_at="2026-01-04T00:00:00+00:00",
        completed_at="2026-01-04T00:05:00+00:00",
    )
    snapshot["direct_source_reconciliations"] = [governed_direct]
    snapshot["cross_provider_triangulations"][0]["direct_reconciliation_id"] = governed_direct["reconciliation_id"]
    snapshot["cross_provider_triangulations"][0]["direct_snapshot_id"] = governed_direct["direct_snapshot_id"]
    snapshot["cross_provider_triangulations"][0]["direct_snapshot_fingerprint"] = governed_direct["direct_snapshot_fingerprint"]
    snapshot["prospective_observation_programs"] = [asdict(
        freeze_prospective_observation_program(
            snapshot["direct_source_reconciliations"][0],
            created_at="2026-01-04T02:00:00+00:00",
        )
    )]
    return snapshot


class PublicDataMissionGateTests(unittest.TestCase):
    @staticmethod
    def _historical_gate(mission):
        return next(
            gate for gate in mission.gates
            if gate.gate_id == "HISTORICAL_OOS_COMPLETE"
        )

    def test_revised_or_non_point_in_time_manifest_cannot_satisfy_historical_gate(self) -> None:
        cases = (
            ("PASS", "PRESENT"),
            ("WARNING", "CONTROLLED"),
        )
        for point_in_time_status, revision_risk_status in cases:
            with self.subTest(
                point_in_time_status=point_in_time_status,
                revision_risk_status=revision_risk_status,
            ):
                mission = build_mission_snapshot(
                    _complete_snapshot(
                        point_in_time_status=point_in_time_status,
                        revision_risk_status=revision_risk_status,
                    ),
                    "QUESTION-1",
                )
                gate = self._historical_gate(mission)

                self.assertEqual(gate.status, "WARNING")
                self.assertIn("revised diagnostic, not point-in-time", gate.summary)
                self.assertIn("vintage-aware data", gate.next_action)
                self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")

    def test_controlled_point_in_time_manifest_still_satisfies_historical_gate(self) -> None:
        mission = build_mission_snapshot(_complete_snapshot(), "QUESTION-1")

        self.assertEqual(self._historical_gate(mission).status, "SATISFIED")
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_ready_mission_replaces_stale_plan_action_with_final_review(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["plans"][0]["next_action"] = "Provide a chronological dataset before review."

        mission = build_mission_snapshot(snapshot, "QUESTION-1")

        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")
        self.assertEqual(
            mission.next_action,
            "Review the completed mission with the Validation Council.",
        )
        self.assertNotIn("Provide a chronological dataset", mission.next_action)

    def test_completed_cross_runtime_disagreement_blocks_ready_state(self) -> None:
        snapshot = _complete_snapshot()
        verification = snapshot["cross_runtime_verifications"][0]
        verification["parity_status"] = "FAIL"
        verification["implementation_gate_status"] = "FAIL"
        verification["matched_result_count"] = 8
        verification["discrepancy_count"] = 1
        verification["discrepancies"] = ["GB/RELATIVE_PRICE_WEDGE: candidate RMSE differs"]

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "CROSS_RUNTIME_REPRODUCIBILITY")

        self.assertEqual(gate.status, "CONFLICT")
        self.assertEqual(mission.overall_status, "BLOCKED")
        self.assertIn("retain every cross-runtime discrepancy", mission.next_action)

    def test_direct_revised_history_closes_only_the_provenance_gate(self) -> None:
        mission = build_mission_snapshot(_complete_snapshot(), "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "DIRECT_SOURCE_RECONCILIATION")

        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn("not point-in-time historical evidence", gate.summary)
        self.assertIn("WARMING_UP", gate.summary)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_frozen_prospective_protocol_closes_operations_not_maturity(self) -> None:
        mission = build_mission_snapshot(_complete_snapshot(), "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")

        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn("WARMING_UP", gate.summary)
        self.assertIn("not longitudinal scientific maturity", gate.summary)
        self.assertEqual(len(mission.gates), 22)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")
        self.assertEqual(mission.core_study_status, "READY_FOR_REVIEW")
        self.assertEqual(mission.prospective_operations_status, "SATISFIED")

    def test_missing_or_tampered_prospective_protocol_fails_closed(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["prospective_observation_programs"] = []
        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")
        self.assertEqual(gate.status, "NOT_EVALUATED")
        self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")
        self.assertEqual(mission.core_study_status, "READY_FOR_REVIEW")
        self.assertEqual(mission.prospective_operations_status, "NOT_EVALUATED")

        snapshot = _complete_snapshot()
        snapshot["prospective_observation_programs"][0]["historical_backfill_permitted"] = True
        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")
        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("historical backfill", " ".join(gate.blockers))
        self.assertEqual(mission.overall_status, "BLOCKED")
        self.assertEqual(mission.core_study_status, "READY_FOR_REVIEW")
        self.assertEqual(mission.prospective_operations_status, "CONFLICT")

    def test_duplicate_program_rows_fail_closed_even_with_the_same_identity(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["prospective_observation_programs"].append(
            copy.deepcopy(snapshot["prospective_observation_programs"][0])
        )

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("exactly one", " ".join(gate.blockers))
        self.assertEqual(mission.core_study_status, "READY_FOR_REVIEW")

    def test_each_replication_can_have_one_program_without_global_conflict(self) -> None:
        snapshot = _complete_snapshot()
        second_replication = copy.deepcopy(snapshot["replications"][0])
        second_replication["replication_id"] = "REPLICATION-2"
        second_replication["snapshot_id"] = "ALFRED-SNAPSHOT-2"
        second_replication["source_snapshot_fingerprint"] = _sha256("replication-source-2")
        second_replication["execution_fingerprint"] = "sha256:replication-execution-2"
        snapshot["replications"].append(second_replication)
        second_direct = _complete_direct(
            second_replication,
            token="second-replication",
            frozen_at="2026-01-04T02:50:00+00:00",
            retrieved_at="2026-01-04T03:00:00+00:00",
            completed_at="2026-01-04T03:05:00+00:00",
        )
        snapshot["direct_source_reconciliations"].append(second_direct)
        snapshot["prospective_observation_programs"].append(asdict(
            freeze_prospective_observation_program(
                second_direct,
                created_at="2026-01-04T04:00:00+00:00",
            )
        ))

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")

        self.assertEqual(gate.status, "SATISFIED")
        self.assertEqual(mission.counts["prospective_observation_programs"], 2)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_prospective_seed_must_be_latest_observation_available_at_freeze(self) -> None:
        snapshot = _complete_snapshot()
        newer = _complete_direct(
            snapshot["replications"][0],
            token="newer-at-freeze",
            frozen_at="2026-01-04T01:20:00+00:00",
            retrieved_at="2026-01-04T01:30:00+00:00",
            completed_at="2026-01-04T01:35:00+00:00",
        )
        snapshot["direct_source_reconciliations"].append(newer)

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")
        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("not the latest eligible", " ".join(gate.blockers))

    def test_seed_recency_excludes_an_observation_completed_after_freeze(self) -> None:
        snapshot = _complete_snapshot()
        later_completion = _complete_direct(
            snapshot["replications"][0],
            token="retrieved-before-freeze-completed-after",
            frozen_at="2026-01-04T01:20:00+00:00",
            retrieved_at="2026-01-04T01:30:00+00:00",
            completed_at="2026-01-04T02:30:00+00:00",
        )
        snapshot["direct_source_reconciliations"].append(later_completion)

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "PROSPECTIVE_OBSERVATION_PROTOCOL")

        self.assertEqual(gate.status, "SATISFIED")
        self.assertNotIn("not the latest eligible", " ".join(gate.blockers))

    def test_direct_record_must_bind_exact_parent_replication_snapshot_and_matrix(self) -> None:
        snapshot = _complete_snapshot()
        foreign_parent = copy.deepcopy(snapshot["replications"][0])
        foreign_parent["snapshot_id"] = "ALFRED-FOREIGN-SNAPSHOT"
        foreign_parent["source_snapshot_fingerprint"] = _sha256("foreign-reference-snapshot")
        internally_valid_but_foreign = _complete_direct(
            foreign_parent,
            token="foreign-parent",
            frozen_at="2026-01-03T23:50:00+00:00",
            retrieved_at="2026-01-04T00:00:00+00:00",
            completed_at="2026-01-04T00:05:00+00:00",
        )
        snapshot["direct_source_reconciliations"] = [internally_valid_but_foreign]
        snapshot["cross_provider_triangulations"] = []
        snapshot["prospective_observation_programs"] = []

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "DIRECT_SOURCE_RECONCILIATION")

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("differs from its parent replication", " ".join(gate.blockers))

    def test_replication_with_contradictory_experiment_and_reference_run_is_conflict(self) -> None:
        snapshot = _complete_snapshot()
        contradictory = copy.deepcopy(snapshot["replications"][0])
        contradictory["replication_id"] = "REPLICATION-CONTRADICTORY"
        contradictory["experiment_id"] = "EXPERIMENT-FOREIGN"
        snapshot["replications"].append(contradictory)

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "INDEPENDENT_REPLICATION")

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("experiment foreign key conflicts", " ".join(gate.blockers))

    def test_cross_provider_direct_parent_mismatch_is_conflict(self) -> None:
        snapshot = _complete_snapshot()
        second_replication = copy.deepcopy(snapshot["replications"][0])
        second_replication["replication_id"] = "REPLICATION-2"
        second_replication["snapshot_id"] = "ALFRED-SNAPSHOT-2"
        second_replication["source_snapshot_fingerprint"] = _sha256("replication-source-2")
        second_replication["execution_fingerprint"] = "sha256:replication-execution-2"
        snapshot["replications"].append(second_replication)
        second_direct = _complete_direct(
            second_replication,
            token="triangulation-parent-mismatch",
            frozen_at="2026-01-04T02:50:00+00:00",
            retrieved_at="2026-01-04T03:00:00+00:00",
            completed_at="2026-01-04T03:05:00+00:00",
        )
        snapshot["direct_source_reconciliations"].append(second_direct)
        triangulation = snapshot["cross_provider_triangulations"][0]
        triangulation["direct_reconciliation_id"] = second_direct["reconciliation_id"]
        triangulation["direct_snapshot_id"] = second_direct["direct_snapshot_id"]
        triangulation["direct_snapshot_fingerprint"] = second_direct["direct_snapshot_fingerprint"]

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(
            gate for gate in mission.gates
            if gate.gate_id == "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION"
        )

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("does not belong to the declared replication", " ".join(gate.blockers))

    def test_direct_source_point_in_time_overclaim_blocks_mission(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["direct_source_reconciliations"][0]["point_in_time_status"] = "PASS"

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "DIRECT_SOURCE_RECONCILIATION")

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("overstated as point-in-time", " ".join(gate.blockers))
        self.assertEqual(mission.overall_status, "BLOCKED")

    def test_missing_direct_source_observation_remains_waiting(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["direct_source_reconciliations"] = []
        snapshot["prospective_observation_programs"] = []
        snapshot["cross_provider_triangulations"] = []

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(gate for gate in mission.gates if gate.gate_id == "DIRECT_SOURCE_RECONCILIATION")

        self.assertEqual(gate.status, "NOT_EVALUATED")
        self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")

    def test_cross_provider_concordance_closes_only_the_measurement_gate(self) -> None:
        mission = build_mission_snapshot(_complete_snapshot(), "QUESTION-1")
        gate = next(
            gate for gate in mission.gates
            if gate.gate_id == "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION"
        )

        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn("CONCORDANT", gate.summary)
        self.assertIn("neither source is ground truth", gate.summary)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_cross_provider_divergence_is_retained_without_blocking_execution_quality(self) -> None:
        snapshot = _complete_snapshot()
        record = snapshot["cross_provider_triangulations"][0]
        record["triangulation_outcome"] = "MEASUREMENT_DIVERGENCE"
        record["concordant_series_count"] = 2
        record["divergent_series_count"] = 1
        record["series_results"][1]["status"] = "MEASUREMENT_DIVERGENCE"
        record["series_results"][1]["threshold_checks"]["change_correlation"] = False

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(
            gate for gate in mission.gates
            if gate.gate_id == "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION"
        )

        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn("MEASUREMENT_DIVERGENCE", gate.summary)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_cross_provider_independence_overclaim_blocks_mission(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["cross_provider_triangulations"][0]["independence_dimensions"]["methodology"] = True

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(
            gate for gate in mission.gates
            if gate.gate_id == "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION"
        )

        self.assertEqual(gate.status, "CONFLICT")
        self.assertIn("overstated as independent", " ".join(gate.blockers))
        self.assertEqual(mission.overall_status, "BLOCKED")

    def test_missing_cross_provider_triangulation_remains_waiting(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["cross_provider_triangulations"] = []

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = next(
            gate for gate in mission.gates
            if gate.gate_id == "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION"
        )

        self.assertEqual(gate.status, "NOT_EVALUATED")
        self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")

    def test_legacy_review_and_status_only_replication_cannot_close_governed_gates(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["reviews"] = [{"review_id": "LEGACY-REVIEW", "run_id": "RUN-PRIMARY"}]
        snapshot["replications"] = [{
            "replication_id": "LEGACY-REPLICATION",
            "experiment_id": "EXPERIMENT-1",
            "status": "REPLICATED",
        }]

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        council = next(gate for gate in mission.gates if gate.gate_id == "VALIDATION_COUNCIL_REVIEWED")
        replication = next(gate for gate in mission.gates if gate.gate_id == "INDEPENDENT_REPLICATION")

        self.assertEqual(council.status, "WARNING")
        self.assertIn("legacy review protocol", " ".join(council.blockers))
        self.assertEqual(replication.status, "NOT_EVALUATED")
        self.assertIn("missing governed replication protocol", " ".join(replication.blockers))
        self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")

    def test_eligible_replication_supersedes_legacy_plan_defects_without_erasing_history(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["replications"].append({
            "replication_id": "LEGACY-REPLICATION",
            "experiment_id": "EXPERIMENT-1",
            "status": "DATA_REQUIRED",
        })

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        replication = next(gate for gate in mission.gates if gate.gate_id == "INDEPENDENT_REPLICATION")

        self.assertEqual(replication.status, "SATISFIED")
        self.assertEqual(replication.blockers, ())
        self.assertIn("REPLICATION-1", replication.artifact_refs)
        self.assertIn("LEGACY-REPLICATION", replication.artifact_refs)
        self.assertEqual(mission.overall_status, "READY_FOR_REVIEW")

    def test_unlinked_question_cannot_inherit_another_missions_experiment_or_timeline(self) -> None:
        snapshot = _complete_snapshot()
        snapshot["questions"].append({
            "question_id": "QUESTION-2",
            "plan_id": "PLAN-2",
            "title": "Unrelated mission",
            "status": "PLANNED",
        })
        snapshot["plans"].append({
            "plan_id": "PLAN-2",
            "question_id": "QUESTION-2",
            "selected_hypothesis_id": "",
            "blockers": ["Unrelated historical planning debt"],
            "created_at": "2026-01-05T00:00:00+00:00",
        })

        mission = build_mission_snapshot(snapshot, "QUESTION-2")
        transfer = next(gate for gate in mission.gates if gate.gate_id == "PARTIAL_TRANSFER_ELIGIBLE")
        attempt = next(gate for gate in mission.gates if gate.gate_id == "ATTEMPT_REGISTERED")
        room = build_run_room(snapshot, "QUESTION-2")
        timeline = build_epistemic_timeline(snapshot, "QUESTION-2")

        self.assertEqual(transfer.status, "BLOCKED")
        self.assertNotIn("TRANSFER-1", transfer.artifact_refs)
        self.assertEqual(attempt.status, "NOT_EVALUATED")
        self.assertEqual(room["specification"], {})
        self.assertEqual(room["run"], {})
        self.assertNotIn("RUN-PRIMARY", {row.get("ref_id") for row in timeline})
        self.assertIn("QUESTION-2", {row.get("ref_id") for row in timeline})
        self.assertNotIn("Unrelated historical planning debt", mission.blockers)

    def test_explicit_foreign_question_run_cannot_leak_through_shared_experiment(self) -> None:
        snapshot = _complete_snapshot()
        foreign = copy.deepcopy(snapshot["runs"][0])
        foreign.update({
            "run_id": "RUN-FOREIGN-QUESTION",
            "question_id": "QUESTION-2",
            "created_at": "2026-01-10T00:00:00+00:00",
            "verdict": "FAIL",
        })
        snapshot["runs"].append(foreign)

        mission = build_mission_snapshot(snapshot, "QUESTION-1")
        room = build_run_room(snapshot, "QUESTION-1")
        timeline = build_epistemic_timeline(snapshot, "QUESTION-1")

        self.assertEqual(room["run"].get("run_id"), "RUN-PRIMARY")
        self.assertNotIn("RUN-FOREIGN-QUESTION", {row.get("ref_id") for row in timeline})
        self.assertEqual(mission.counts["historical_runs"], 2)


if __name__ == "__main__":
    unittest.main()
