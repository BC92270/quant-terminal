from __future__ import annotations

import tempfile
import unittest

from scientific_research import scientific_understanding as understanding_engine
from scientific_research.closed_loop_engine import build_grounded_evidence_record
from scientific_research.closed_loop_registry import ClosedLoopRegistry
from scientific_research.phase62_registry import Phase62Registry
from scientific_research.validation_registry import ValidationRegistry


class SourceRevisionTests(unittest.TestCase):
    OFFICIAL_MATHNET_ABSTRACT = (
        "The article considers using a trending Ornstein–Uhlenbeck process, driven by a Levy process, for "
        "modeling financial time series. The authors demonstrate that the Levy driven model gives more flexibility to "
        "describe financial time series than the simple classical model. In particular, the Levy driven model allows modeling "
        "distributions with heavy tails, which is a common property of time series in real applications. The authors describe "
        "efficient methods for estimating model parameters using such methods as OLS (ordinary least squares) and RLS "
        "(regularized least squares). The article also solves the regime switching problem in a real time data stream. The "
        "authors built an algorithm based on CUSUM (CUmulative SUM) methods that is capable of determining regime switches "
        "consecutively as they happen online and keep model parameters up to date. Solution of the regime switching problem "
        "is important in real applications, since the dynamics of real systems tend to change over time under the influence "
        "of external factors."
    )

    @staticmethod
    def _build():
        return understanding_engine.build_understanding_bundle(
            paper_id="PAPER-1",
            paper_title="A declared scientific source",
            source_text="We demonstrate that a stochastic process changes regime. We develop a CUSUM method.",
            source_kind="full_text",
            domain="Statistics",
            problem="Detect regime changes.",
            mechanisms={"stochasticity": 0.9, "change_point_detection": 0.8},
        )[0]

    def test_understanding_identity_is_stable_within_extractor_version(self) -> None:
        first = self._build()
        second = self._build()
        self.assertEqual(first.understanding_id, second.understanding_id)
        self.assertEqual(first.extractor_version, understanding_engine.EXTRACTOR_VERSION)
        self.assertTrue(first.compiler_signature)
        self.assertTrue(first.revision_id)

    def test_extractor_version_change_creates_new_understanding_identity(self) -> None:
        first = self._build()
        original = understanding_engine.EXTRACTOR_VERSION
        try:
            understanding_engine.EXTRACTOR_VERSION = "TEST_NEXT_EXTRACTOR_VERSION"
            revised = self._build()
        finally:
            understanding_engine.EXTRACTOR_VERSION = original
        self.assertNotEqual(first.understanding_id, revised.understanding_id)

    def test_official_abstract_extracts_structure_without_inventing_equations(self) -> None:
        bundle, provenance = understanding_engine.build_understanding_bundle(
            paper_id="PAPER-MATHNET-IA444",
            paper_title="Regime switching detection for the Levy driven Ornstein–Uhlenbeck process using CUSUM methods",
            source_text=self.OFFICIAL_MATHNET_ABSTRACT,
            source_kind="abstract",
            domain="Financial time series",
            problem="Online regime-switch detection in a Levy-driven Ornstein–Uhlenbeck process.",
            mechanisms={
                "change_point_detection": 1.0,
                "heavy_tails": 1.0,
                "online_adaptation": 1.0,
                "regime_switching": 1.0,
                "stochasticity": 1.0,
            },
        )
        self.assertEqual(bundle.source_digest, "695402c8304e19ee663154b4979317a8fffc39933bf34695bedc638d883ca137")
        self.assertEqual(len(bundle.claims), 3)
        self.assertEqual(len(bundle.mechanisms), 5)
        self.assertEqual(len(bundle.semantic_entities), 9)
        self.assertEqual(len(bundle.equations), 0)
        self.assertTrue(provenance)


class EvidenceLifecycleTests(unittest.TestCase):
    def test_empty_extraction_is_retained_but_never_grounded(self) -> None:
        evidence = build_grounded_evidence_record(
            {
                "question_id": "QUESTION-1",
                "paper_id": "PAPER-1",
                "promotion_id": "PROMO-1",
                "title": "Source",
            },
            {
                "understanding_id": "UNDERSTAND-1",
                "claims": [],
                "mechanisms": {},
                "mechanism_families": {},
                "semantic_entities": [],
            },
            source_level="USER_SUPPLIED_TEXT",
        )
        self.assertEqual(evidence.status, "INCOMPLETE_EXTRACTION")
        self.assertFalse(evidence.claim_ids)

    def test_recompilation_collision_preserves_prior_extraction_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ClosedLoopRegistry(directory)
            base = {
                "evidence_id": "EVIDENCE-1",
                "question_id": "QUESTION-1",
                "paper_id": "PAPER-1",
                "understanding_id": "UNDERSTAND-1",
                "status": "INCOMPLETE_EXTRACTION",
                "claim_ids": [],
            }
            registry.save_evidence(base)
            revised = dict(base, status="GROUNDED_REVIEWED", claim_ids=["CLAIM-1"])
            registry.save_evidence(revised)
            stored = registry.list_evidence()[0]
            self.assertEqual(stored["status"], "GROUNDED_REVIEWED")
            self.assertEqual(len(stored["extraction_history"]), 1)
            self.assertEqual(stored["extraction_history"][0]["prior"]["status"], "INCOMPLETE_EXTRACTION")


class MeasurementDecisionHistoryTests(unittest.TestCase):
    def test_decision_history_and_primary_survive_model_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase62Registry(directory)
            model = {
                "measurement_model_id": "MODEL-1",
                "question_id": "QUESTION-1",
                "observable_ids": ["OBS-1", "OBS-2"],
                "primary_observable_id": "",
                "status": "COMPETING_MEASUREMENTS",
            }
            registry.save_measurement_model(model)
            decision = {
                "decision_id": "DECISION-1",
                "measurement_model_id": "MODEL-1",
                "question_id": "QUESTION-1",
                "selected_observable_id": "OBS-1",
                "rationale": "Predeclared primary measurement.",
                "evidence_refs": [],
            }
            registry.save_measurement_decision(decision)
            registry.save_measurement_decision(dict(decision, rationale="Refined explicit rationale."))
            stored_decision = registry.list_measurement_decisions()[0]
            self.assertEqual(len(stored_decision["decision_history"]), 1)

            registry.save_measurement_model(dict(model, status="REFRESHED"))
            stored_model = registry.list_measurement_models()[0]
            self.assertEqual(stored_model["primary_observable_id"], "OBS-1")
            self.assertEqual(stored_model["status"], "PRIMARY_SELECTED_MEASUREMENT_UNCERTAINTY_OPEN")


class LegacyLifecycleAlignmentTests(unittest.TestCase):
    def test_failure_alignment_preserves_status_without_asserting_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ValidationRegistry(directory)
            registry.save_failure({
                "failure_id": "FAIL-1",
                "status": "ADDRESSED",
                "lifecycle_history": [{"at": "2025-01-01T00:00:00+00:00", "from": "", "to": "OPEN"}],
            })
            aligned = registry.reconcile_failure_history(
                "FAIL-1", "Legacy transition metadata is unavailable.", actor="TEST_MIGRATION",
            )
            self.assertEqual(aligned["status"], "ADDRESSED")
            event = aligned["lifecycle_history"][-1]
            self.assertEqual((event["from"], event["to"]), ("OPEN", "ADDRESSED"))
            self.assertEqual(event["transition_kind"], "LEGACY_STATE_ALIGNMENT")
            self.assertFalse(event["historical_transition_asserted"])
            self.assertEqual(event["original_transition_time"], "UNKNOWN")
            registry.reconcile_failure_history(
                "FAIL-1", "A repeated alignment is a no-op.", actor="TEST_MIGRATION",
            )
            self.assertEqual(len(registry.list_failures()[0]["lifecycle_history"]), 2)

    def test_surprise_alignment_is_explicit_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ValidationRegistry(directory)
            registry.save_surprise({
                "surprise_id": "SURPRISE-1",
                "status": "ACKNOWLEDGED",
                "lifecycle_history": [{"at": "2025-01-01T00:00:00+00:00", "from": "", "to": "NEW"}],
            })
            aligned = registry.reconcile_surprise_history(
                "SURPRISE-1", "Legacy transition metadata is unavailable.", actor="TEST_MIGRATION",
            )
            self.assertEqual(aligned["status"], "ACKNOWLEDGED")
            event = aligned["lifecycle_history"][-1]
            self.assertEqual((event["from"], event["to"]), ("NEW", "ACKNOWLEDGED"))
            self.assertFalse(event["historical_transition_asserted"])
            registry.reconcile_surprise_history(
                "SURPRISE-1", "A repeated alignment is a no-op.", actor="TEST_MIGRATION",
            )
            self.assertEqual(len(registry.list_surprises()[0]["lifecycle_history"]), 2)

    def test_alignment_requires_reason_and_known_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = ValidationRegistry(directory)
            registry.save_failure({"failure_id": "FAIL-1", "status": "ADDRESSED"})
            with self.assertRaisesRegex(ValueError, "explicit migration rationale"):
                registry.reconcile_failure_history("FAIL-1", "")
            registry.save_surprise({"surprise_id": "SURPRISE-1", "status": "IMPOSSIBLE"})
            with self.assertRaisesRegex(ValueError, "Unsupported stored lifecycle status"):
                registry.reconcile_surprise_history("SURPRISE-1", "Inspect the invalid state.")


if __name__ == "__main__":
    unittest.main()
