from __future__ import annotations

import unittest

from scientific_research.mission_control_engine import build_mission_snapshot


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
    return {
        "captured_at": "2026-01-04T00:00:00+00:00",
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
                "source_snapshot_fingerprint": "sha256:replication-source",
                "execution_fingerprint": "sha256:replication-execution",
                "replication_outcome": "NO_OOS_IMPROVEMENT",
                "automatic_promotion_authorized": False,
                "production_status": "RESEARCH_ONLY",
            }
        ],
        "failures": [],
        "surprises": [],
        "budgets": [],
        "break_diagnostics": [],
    }


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


if __name__ == "__main__":
    unittest.main()
