from __future__ import annotations

import unittest

from scientific_research.autonomy_engine import evaluate_stop_conditions
from scientific_research.validation_engine import build_theory_population


class TheoryPopulationEvidenceUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.specification = {
            "experiment_id": "EXPERIMENT-1",
            "target_variable": "spread",
        }

    @staticmethod
    def _run(run_id: str, evidence_unit_id: str = "") -> dict[str, str]:
        return {
            "run_id": run_id,
            "evidence_unit_id": evidence_unit_id,
            "experiment_id": "EXPERIMENT-1",
            "stage": "HISTORICAL_OOS",
            "verdict": "PROMISING_OOS",
        }

    def test_shared_evidence_unit_contributes_only_once(self) -> None:
        population = build_theory_population(
            self.specification,
            [self._run("RUN-1", "EUNIT-SHARED"), self._run("RUN-2", "EUNIT-SHARED")],
        )

        pass_events = [
            event for event in population.evidence_events
            if event.event_type == "HISTORICAL_OOS_PASS"
        ]
        generalizes, regime_dependent, no_persistent_edge = population.theories

        self.assertEqual(1, len(pass_events))
        self.assertEqual("RUN-1", pass_events[0].run_id)
        self.assertEqual(0.20, generalizes.support_score)
        self.assertEqual(0.08, regime_dependent.support_score)
        self.assertEqual(0.15, no_persistent_edge.challenge_score)

    def test_legacy_runs_fall_back_to_distinct_run_ids(self) -> None:
        population = build_theory_population(
            self.specification,
            [self._run("RUN-LEGACY-1"), self._run("RUN-LEGACY-1"), self._run("RUN-LEGACY-2")],
        )

        pass_events = [
            event for event in population.evidence_events
            if event.event_type == "HISTORICAL_OOS_PASS"
        ]

        self.assertEqual(2, len(pass_events))
        self.assertEqual({"RUN-LEGACY-1", "RUN-LEGACY-2"}, {event.run_id for event in pass_events})

    def test_noncontributing_run_does_not_consume_the_evidence_unit(self) -> None:
        ignored = self._run("RUN-IGNORED", "EUNIT-SHARED")
        ignored["verdict"] = "INVALID"

        population = build_theory_population(
            self.specification,
            [ignored, self._run("RUN-PASS", "EUNIT-SHARED")],
        )

        pass_events = [
            event for event in population.evidence_events
            if event.event_type == "HISTORICAL_OOS_PASS"
        ]
        self.assertEqual(1, len(pass_events))
        self.assertEqual("RUN-PASS", pass_events[0].run_id)


class StopConditionEvidenceUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.question = {
            "experiment_id": "EXPERIMENT-1",
            "target_variable": "spread",
        }

    @staticmethod
    def _failure(run_id: str, evidence_unit_id: str = "") -> dict[str, str]:
        return {
            "run_id": run_id,
            "evidence_unit_id": evidence_unit_id,
            "experiment_id": "EXPERIMENT-1",
            "stage": "HISTORICAL_OOS",
            "verdict": "NO_OOS_IMPROVEMENT",
        }

    def test_repeated_attempts_on_one_evidence_unit_do_not_trigger_stop(self) -> None:
        status, reasons = evaluate_stop_conditions(
            self.question,
            runs=[
                self._failure("RUN-1", "EUNIT-SHARED"),
                self._failure("RUN-2", "EUNIT-SHARED"),
                self._failure("RUN-3", "EUNIT-SHARED"),
            ],
        )

        self.assertEqual("CONTINUE_BOUNDED", status)
        self.assertNotIn("Three independent historical OOS failures reached the stop threshold.", reasons)

    def test_three_distinct_units_trigger_stop_with_legacy_fallback(self) -> None:
        status, reasons = evaluate_stop_conditions(
            self.question,
            runs=[
                self._failure("RUN-1", "EUNIT-1"),
                self._failure("RUN-2", "EUNIT-2"),
                self._failure("RUN-LEGACY-3"),
                self._failure("RUN-4", "EUNIT-1"),
            ],
        )

        self.assertEqual("STOP_RECOMMENDED", status)
        self.assertIn("Three independent historical OOS failures reached the stop threshold.", reasons)


if __name__ == "__main__":
    unittest.main()
