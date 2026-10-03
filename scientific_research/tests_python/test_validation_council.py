from __future__ import annotations

import unittest

from scientific_research.validation_engine import build_validation_review


class ValidationCouncilV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = {
            "experiment_id": "EXPERIMENT-1",
            "status": "READY",
            "experimental_family": "OU_MEAN_REVERTING_SDE",
            "code_policy": "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC",
            "transfer_verdict": "PARTIAL_TRANSFER",
            "target_variable": "real_effective_exchange_rate",
        }
        self.run = {
            "run_id": "RUN-NEGATIVE",
            "attempt_id": "ATTEMPT-1",
            "experiment_id": "EXPERIMENT-1",
            "stage": "HISTORICAL_OOS",
            "verdict": "NO_OOS_IMPROVEMENT",
            "test_size": 15,
            "dataset_manifest_id": "MANIFEST-1",
            "baseline_metrics": {
                "RANDOM_WALK_LAST_OBSERVATION": {"RMSE": 0.018},
            },
            "deltas_vs_baseline": {
                "RANDOM_WALK_LAST_OBSERVATION": {"RMSE_IMPROVEMENT_PCT": -1.12},
            },
            "production_status": "RESEARCH_ONLY",
        }
        self.report = {
            "report_id": "MRR-1",
            "protocol_id": "MRP-1",
            "experiment_id": "EXPERIMENT-1",
            "status": "COMPLETE",
            "gate_status": "PASS",
            "common_support_status": "PASS",
            "common_split_status": "PASS",
            "point_in_time_status": "PASS",
            "variant_count": 3,
            "conclusion": "CONSISTENT_NO_OOS_IMPROVEMENT",
            "production_status": "RESEARCH_ONLY",
        }

    def test_negative_result_is_retained_without_human_or_promotion_claim(self) -> None:
        review = build_validation_review(
            self.spec,
            self.run,
            measurement_report=self.report,
            all_runs=[self.run],
            evidence_refs=("CAPSULE-1",),
        )

        self.assertEqual(review.review_protocol_version, "SRB_COUNCIL_REVIEW_V2")
        self.assertEqual(review.review_mode, "COMPUTATIONAL_COUNCIL_DOSSIER")
        self.assertEqual(review.human_attestation_status, "NOT_A_HUMAN_PANEL")
        self.assertEqual(review.council_decision, "REVISE_OR_REJECT")
        self.assertEqual(review.scientific_grade, "FAILED_SCREEN")
        self.assertEqual(review.evidence_tier, "NEGATIVE_EVIDENCE")
        self.assertEqual(review.disposition, "RETAIN_NEGATIVE_RESULT_AND_DO_NOT_ADVANCE_CLAIM")
        self.assertEqual(review.gate_eligibility, "ELIGIBLE_COMPUTATIONAL_REVIEW")
        self.assertFalse(review.automatic_promotion_authorized)
        self.assertEqual(review.production_status, "RESEARCH_ONLY")
        self.assertIn("RUN-NEGATIVE", review.evidence_refs)
        self.assertIn("MRR-1", review.evidence_refs)
        self.assertIn("CAPSULE-1", review.evidence_refs)
        self.assertEqual(review.multiple_testing.robustness_variants, 3)
        measurement = next(item for item in review.auditor_findings if item.auditor == "MEASUREMENT")
        self.assertEqual(measurement.status, "PASS")

    def test_historical_review_without_measurement_report_fails_closed(self) -> None:
        review = build_validation_review(self.spec, self.run, all_runs=[self.run])

        self.assertEqual(review.gate_eligibility, "PENDING_EVIDENCE")
        measurement = next(item for item in review.auditor_findings if item.auditor == "MEASUREMENT")
        self.assertEqual(measurement.status, "PENDING")
        self.assertIn("No frozen measurement-robustness report", " ".join(measurement.requirements))

    def test_mismatched_measurement_report_is_not_eligible(self) -> None:
        report = dict(self.report)
        report["experiment_id"] = "EXPERIMENT-OTHER"

        review = build_validation_review(
            self.spec,
            self.run,
            measurement_report=report,
            all_runs=[self.run],
        )

        self.assertEqual(review.gate_eligibility, "PENDING_EVIDENCE")
        measurement = next(item for item in review.auditor_findings if item.auditor == "MEASUREMENT")
        self.assertEqual(measurement.status, "FAIL")

    def test_governed_complete_replication_is_recognized_outcome_neutrally(self) -> None:
        replication = {
            "replication_id": "REPLICATION-1",
            "experiment_id": "EXPERIMENT-1",
            "protocol_version": "SRB_INDEPENDENT_REPLICATION_V1",
            "event_time_support_policy": "STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_EXCLUDE_NON_ADVANCING_BACKFILLS",
            "execution_status": "COMPLETE",
            "independence_gate_status": "PASS",
            "independence_dimensions": {
                "market": True,
                "period": False,
                "implementation": False,
            },
            "point_in_time_status": "PASS",
            "source_snapshot_fingerprint": "sha256:source",
            "execution_fingerprint": "sha256:execution",
            "replication_outcome": "CONSISTENT_NO_OOS_IMPROVEMENT",
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }

        review = build_validation_review(
            self.spec,
            self.run,
            measurement_report=self.report,
            replication_plans=[replication],
            all_runs=[self.run],
        )

        finding = next(item for item in review.auditor_findings if item.auditor == "REPLICATION")
        self.assertEqual(finding.status, "PASS")
        self.assertIn("sign of the outcome", " ".join(finding.rationale))


if __name__ == "__main__":
    unittest.main()
