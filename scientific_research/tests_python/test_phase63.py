from __future__ import annotations

import json
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scientific_research.data_contract_engine import (
    audit_historical_data_contract,
    build_experiment_attempt,
    build_reproducibility_capsule,
    build_selection_pressure_snapshot,
    build_historical_data_contract,
    materialize_price_to_fundamental,
)
from scientific_research.experiment_factory import (
    dataset_fingerprint,
    run_historical_oos_experiment,
)
from scientific_research.experiment_registry import ExperimentRegistry
from scientific_research.mission_control_engine import (
    build_mission_snapshot,
    inspect_registry_file,
)
from scientific_research.phase63_registry import (
    Phase63Registry,
    RegistryCorruptionError,
)


UTC = timezone.utc


class Phase63FixtureMixin:
    def setUp(self) -> None:
        self.question = {
            "question_id": "QUESTION-1",
            "plan_id": "PLAN-1",
            "experiment_id": "EXPERIMENT-1",
            "selected_observable_id": "OBS-PRIMARY",
            "title": "Does a price-to-fundamental residual mean revert?",
            "target_variable": "market_state",
            "status": "PLANNED",
            "priority_score": 0.91,
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.plan = {
            "plan_id": "PLAN-1",
            "question_id": "QUESTION-1",
            "selected_hypothesis_id": "HYP-OU",
            "status": "WAITING_INPUT",
            "blockers": [],
            "created_at": "2026-01-02T00:00:00+00:00",
        }
        self.experiment = {
            "experiment_id": "EXPERIMENT-1",
            "candidate_id": "CANDIDATE-1",
            "transfer_audit_id": "TRANSFER-AUDIT-1",
            "transfer_verdict": "PARTIAL_TRANSFER",
            "stage": "HISTORICAL_OOS",
            "status": "READY",
            "experimental_family": "OU_MEAN_REVERTING_SDE",
            "seed": 17,
            "code_policy": "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC",
            "dataset_contract": {
                "contract_id": "LEGACY-CONTRACT-1",
                "train_fraction": 0.70,
                "max_rows": 250000,
            },
            "created_at": "2026-01-03T00:00:00+00:00",
        }
        self.measurement_model = {
            "measurement_model_id": "MMODEL-1",
            "question_id": "QUESTION-1",
            "observable_ids": ["OBS-PRIMARY", "OBS-COMPETITOR"],
            "primary_observable_id": "OBS-PRIMARY",
            "target_concept": "market_state",
            "created_at": "2026-01-04T00:00:00+00:00",
        }
        self.measurement_decision = {
            "decision_id": "MDECISION-1",
            "question_id": "QUESTION-1",
            "measurement_model_id": "MMODEL-1",
            "selected_observable_id": "OBS-PRIMARY",
            "evidence_refs": ["SOURCE-1"],
            "created_at": "2026-01-05T00:00:00+00:00",
        }
        self.observable = {
            "observable_id": "OBS-PRIMARY",
            "question_id": "QUESTION-1",
            "label": "Price-to-fundamental log residual",
            "mathematical_definition": "log(price_t) - log(fundamental_anchor_t)",
            "unit": "log-ratio",
            "frequency": "MONTHLY",
            "required_columns": ["price", "fundamental_anchor"],
            "total_score": 0.88,
            "status": "SELECTED",
            "created_at": "2026-01-04T00:00:00+00:00",
        }
        self.competitor = {
            "observable_id": "OBS-COMPETITOR",
            "question_id": "QUESTION-1",
            "label": "Alternative price-to-fundamental residual",
            "mathematical_definition": "log(price_t) - log(alternative_fundamental_t)",
            "unit": "log-ratio",
            "frequency": "MONTHLY",
            "required_columns": ["price", "alternative_fundamental"],
            "total_score": 0.67,
            "status": "PROPOSED",
            "created_at": "2026-01-04T00:00:00+00:00",
        }

    def make_contract(self, **overrides):
        params = {
            "question": self.question,
            "plan": self.plan,
            "experiment": self.experiment,
            "measurement_model": self.measurement_model,
            "measurement_decision": self.measurement_decision,
            "observable": self.observable,
            "market": "US equities",
            "universe": "S&P 500",
            "asset_identifier": "SPX",
            "provider": "A point-in-time provider",
            "raw_data_uri": "https://data.example.test/spx-pit.csv",
            "license_or_terms": "Research licence",
            "anchor_family": "CAPE_STYLE_EARNINGS",
            "price_field": "price",
            "fundamental_field": "fundamental_anchor",
            "event_time_field": "timestamp",
            "availability_time_field": "release_timestamp",
            "vintage_time_field": "vintage_timestamp",
            "frequency": "MONTHLY",
            "publication_lag_days": 0,
            "revision_policy": "POINT_IN_TIME_VINTAGES",
            "source_refs": ["SOURCE-1", "SOURCE-2"],
            "rationale": "Predeclare a causal, point-in-time price-to-fundamental measurement.",
        }
        params.update(overrides)
        return build_historical_data_contract(**params)

    @staticmethod
    def make_rows(count: int = 72) -> list[dict[str, object]]:
        start = datetime(2015, 1, 1, tzinfo=UTC)
        rows: list[dict[str, object]] = []
        for index in range(count):
            event = start + timedelta(days=30 * index)
            anchor = 100.0 + 0.12 * index
            # Deterministic variation keeps the AR(1) fit non-degenerate.
            state = 0.12 * math.sin(index / 4.0) + 0.025 * math.cos(index / 2.7)
            rows.append(
                {
                    "timestamp": event.isoformat(),
                    "price": anchor * math.exp(state),
                    "fundamental_anchor": anchor,
                    "release_timestamp": (event - timedelta(days=2)).isoformat(),
                    "vintage_timestamp": (event - timedelta(days=2)).isoformat(),
                }
            )
        return rows

    def materialize(self, **contract_overrides):
        contract = self.make_contract(**contract_overrides)
        audit = audit_historical_data_contract(contract)
        dataset = materialize_price_to_fundamental(
            self.make_rows(), contract, dataset_label="PIT residual fixture", contract_audit=audit
        )
        return contract, audit, dataset

    def run_materialized(self):
        contract, audit, dataset = self.materialize()
        attempt = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        run = run_historical_oos_experiment(
            self.experiment,
            dataset.values,
            labels=dataset.timestamps,
            attempt_id=attempt.attempt_id,
            run_signature=attempt.run_signature,
            evidence_unit_id=attempt.evidence_unit_id,
            data_contract_id=contract.contract_id,
            data_contract_audit_id=audit.audit_id,
            dataset_manifest_id=dataset.manifest.manifest_id,
            measurement_model_id=contract.measurement_model_id,
            measurement_decision_id=contract.measurement_decision_id,
            observable_id=contract.observable_id,
            forecast_horizon=contract.forecast_horizon,
        )
        return contract, audit, dataset, attempt, run


class HistoricalDataContractTests(Phase63FixtureMixin, unittest.TestCase):
    def test_complete_point_in_time_contract_and_audit_validate(self) -> None:
        contract = self.make_contract()
        audit = audit_historical_data_contract(contract)

        self.assertEqual(contract.status, "VALIDATED")
        self.assertEqual(audit.overall_status, "VALIDATED")
        self.assertEqual(audit.point_in_time_status, "PASS")
        self.assertEqual(
            [step.operation for step in contract.transform_steps],
            [
                "ASSERT_STRICT_CHRONOLOGY",
                "ALIGN_BY_PUBLIC_AVAILABILITY",
                "FORWARD_FILL_AFTER_RELEASE_ONLY",
                "POSITIVE_LOG_RATIO",
            ],
        )
        self.assertEqual(contract.production_status, "RESEARCH_ONLY")

    def test_point_in_time_policy_without_vintage_field_is_blocked(self) -> None:
        contract = self.make_contract(vintage_time_field="")
        audit = audit_historical_data_contract(contract)

        self.assertEqual(contract.status, "BLOCKED")
        self.assertEqual(audit.overall_status, "BLOCKED")
        self.assertIn("requires a vintage timestamp field", " ".join(contract.blockers))

    def test_revised_history_retains_visible_revision_risk(self) -> None:
        contract = self.make_contract(
            revision_policy="REVISED_WITH_RISK_FLAG", vintage_time_field=""
        )
        audit = audit_historical_data_contract(contract)
        dataset = materialize_price_to_fundamental(
            self.make_rows(), contract, dataset_label="Revised fixture", contract_audit=audit
        )

        self.assertEqual(contract.status, "VALIDATED")
        self.assertEqual(audit.overall_status, "VALIDATED_WITH_WARNINGS")
        self.assertEqual(audit.point_in_time_status, "WARNING")
        self.assertEqual(dataset.manifest.revision_risk_status, "PRESENT")
        self.assertIn("REVISION_RISK_PRESENT", " ".join(dataset.manifest.warnings))

    def test_measurement_lineage_conflict_blocks_contract(self) -> None:
        conflicting_decision = dict(self.measurement_decision)
        conflicting_decision["selected_observable_id"] = "OBS-COMPETITOR"
        contract = self.make_contract(measurement_decision=conflicting_decision)

        self.assertEqual(contract.status, "BLOCKED")
        self.assertIn("explicit primary MeasurementDecision", " ".join(contract.blockers))

    def test_non_price_to_fundamental_observable_is_blocked(self) -> None:
        observable = dict(self.observable)
        observable.update(label="Raw close", mathematical_definition="price_t")
        contract = self.make_contract(observable=observable)

        self.assertEqual(contract.status, "BLOCKED")
        self.assertIn("price-to-fundamental", " ".join(contract.blockers))


class MaterializationTests(Phase63FixtureMixin, unittest.TestCase):
    def test_materialization_is_strictly_chronological_and_fingerprinted(self) -> None:
        contract, audit, dataset = self.materialize()

        self.assertEqual(len(dataset.timestamps), 72)
        self.assertEqual(dataset.manifest.valid_row_count, 72)
        self.assertEqual(dataset.manifest.excluded_row_count, 0)
        self.assertEqual(dataset.manifest.point_in_time_status, "PASS")
        self.assertEqual(dataset.manifest.revision_risk_status, "CONTROLLED")
        self.assertEqual(
            dataset.manifest.materialized_fingerprint,
            dataset_fingerprint(dataset.values, dataset.timestamps),
        )
        self.assertEqual(dataset.values[0], math.log(dataset.prices[0]) - math.log(dataset.fundamental_anchors[0]))
        self.assertEqual(audit.contract_id, contract.contract_id)

    def test_duplicate_or_nonmonotonic_event_timestamp_is_rejected(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[24]["timestamp"] = rows[23]["timestamp"]

        with self.assertRaisesRegex(ValueError, "strictly increasing and unique"):
            materialize_price_to_fundamental(rows, contract, dataset_label="Bad chronology")

    def test_future_publication_is_rejected(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[12]["release_timestamp"] = (
            datetime.fromisoformat(str(rows[12]["timestamp"])) + timedelta(days=1)
        ).isoformat()

        with self.assertRaisesRegex(ValueError, "before its public availability"):
            materialize_price_to_fundamental(rows, contract, dataset_label="Future release")

    def test_future_vintage_is_rejected(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[12]["vintage_timestamp"] = (
            datetime.fromisoformat(str(rows[12]["timestamp"])) + timedelta(days=1)
        ).isoformat()

        with self.assertRaisesRegex(ValueError, "vintage not available"):
            materialize_price_to_fundamental(rows, contract, dataset_label="Future vintage")

    def test_availability_lineage_cannot_move_backward(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[20]["release_timestamp"] = (
            datetime.fromisoformat(str(rows[18]["release_timestamp"])) - timedelta(days=1)
        ).isoformat()

        with self.assertRaisesRegex(ValueError, "availability timestamps move backward"):
            materialize_price_to_fundamental(rows, contract, dataset_label="Backward release")

    def test_nonpositive_log_input_is_rejected(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[31]["fundamental_anchor"] = 0.0

        with self.assertRaisesRegex(ValueError, "strictly positive"):
            materialize_price_to_fundamental(rows, contract, dataset_label="Zero anchor")

    def test_fewer_than_forty_rows_is_rejected(self) -> None:
        contract = self.make_contract()

        with self.assertRaisesRegex(ValueError, "At least 40"):
            materialize_price_to_fundamental(self.make_rows(39), contract, dataset_label="Too short")

    def test_future_anchor_change_does_not_rewrite_prior_states(self) -> None:
        contract = self.make_contract()
        original_rows = self.make_rows()
        revised_rows = self.make_rows()
        revised_rows[50]["fundamental_anchor"] = 250.0

        original = materialize_price_to_fundamental(original_rows, contract, dataset_label="Original")
        revised = materialize_price_to_fundamental(revised_rows, contract, dataset_label="Changed future")

        self.assertEqual(original.values[:50], revised.values[:50])
        self.assertNotEqual(original.values[50], revised.values[50])
        self.assertNotEqual(original.manifest.raw_fingerprint, revised.manifest.raw_fingerprint)

    def test_declared_publication_lag_is_executed_not_merely_documented(self) -> None:
        contract = self.make_contract(publication_lag_days=5)
        compliant_rows = self.make_rows()
        for row in compliant_rows:
            event = datetime.fromisoformat(str(row["timestamp"]))
            row["release_timestamp"] = (event - timedelta(days=5)).isoformat()
        dataset = materialize_price_to_fundamental(
            compliant_rows, contract, dataset_label="Five-day publication lag"
        )
        availability_check = next(
            check for check in dataset.manifest.checks if check["check"] == "public_availability"
        )

        self.assertEqual(dataset.manifest.valid_row_count, len(compliant_rows))
        self.assertIn("+ 5 day lag", availability_check["detail"])

        too_early = [dict(row) for row in compliant_rows]
        event = datetime.fromisoformat(str(too_early[18]["timestamp"]))
        too_early[18]["release_timestamp"] = (event - timedelta(days=4)).isoformat()
        with self.assertRaisesRegex(ValueError, "declared publication lag"):
            materialize_price_to_fundamental(
                too_early, contract, dataset_label="Lag violation"
            )

    def test_only_jointly_missing_leading_anchor_rows_are_excluded_and_counted(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows(75)
        for row in rows[:3]:
            row["fundamental_anchor"] = None
            row["release_timestamp"] = None
            row["vintage_timestamp"] = None

        dataset = materialize_price_to_fundamental(
            rows, contract, dataset_label="Leading pre-release observations"
        )
        leading_check = next(
            check for check in dataset.manifest.checks if check["check"] == "leading_missing_policy"
        )

        self.assertEqual(dataset.manifest.row_count, 75)
        self.assertEqual(dataset.manifest.valid_row_count, 72)
        self.assertEqual(dataset.manifest.excluded_row_count, 3)
        self.assertEqual(dataset.manifest.start_timestamp, rows[3]["timestamp"])
        self.assertEqual(
            dataset.manifest.row_count,
            dataset.manifest.valid_row_count + dataset.manifest.excluded_row_count,
        )
        self.assertIn("3 leading", leading_check["detail"])

    def test_partial_anchor_pair_is_never_treated_as_an_excludable_leading_row(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[0]["fundamental_anchor"] = None

        with self.assertRaisesRegex(ValueError, "anchor.*availability|availability.*anchor|both"):
            materialize_price_to_fundamental(
                rows, contract, dataset_label="Partial leading anchor pair"
            )

    def test_joint_interior_gap_carries_last_public_anchor_without_dropping_row(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        prior_anchor = float(rows[19]["fundamental_anchor"])
        prior_release = str(rows[19]["release_timestamp"])
        prior_vintage = str(rows[19]["vintage_timestamp"])
        rows[20]["fundamental_anchor"] = None
        rows[20]["release_timestamp"] = None
        rows[20]["vintage_timestamp"] = None

        dataset = materialize_price_to_fundamental(
            rows, contract, dataset_label="Causal carry-forward"
        )

        self.assertEqual(dataset.manifest.row_count, 72)
        self.assertEqual(dataset.manifest.valid_row_count, 72)
        self.assertEqual(dataset.manifest.excluded_row_count, 0)
        self.assertEqual(dataset.fundamental_anchors[20], prior_anchor)
        self.assertEqual(dataset.availability_timestamps[20], prior_release)
        self.assertEqual(dataset.vintage_timestamps[20], prior_vintage)
        self.assertAlmostEqual(
            dataset.values[20], math.log(dataset.prices[20]) - math.log(prior_anchor), places=12
        )
        carry_check = next(
            check for check in dataset.manifest.checks if check["check"] == "causal_forward_fill"
        )
        self.assertEqual(carry_check["status"], "PASS")
        self.assertIn("1 post-release row", carry_check["detail"])

    def test_partial_interior_anchor_pair_is_blocked(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[20]["fundamental_anchor"] = None

        with self.assertRaisesRegex(ValueError, "interior|anchor.*availability|availability.*anchor|both"):
            materialize_price_to_fundamental(
                rows, contract, dataset_label="Partial interior anchor pair"
            )

    def test_carry_forward_with_incoherent_vintage_is_blocked(self) -> None:
        contract = self.make_contract()
        rows = self.make_rows()
        rows[20]["fundamental_anchor"] = None
        rows[20]["release_timestamp"] = None
        # This row's original vintage belongs to a different as-of state than the
        # carried row 19 anchor, so it must not be silently paired with that anchor.

        with self.assertRaisesRegex(ValueError, "vintage"):
            materialize_price_to_fundamental(
                rows, contract, dataset_label="Incoherent carried vintage"
            )


class HistoricalRunTests(Phase63FixtureMixin, unittest.TestCase):
    def test_historical_run_requires_explicit_iso_timestamps(self) -> None:
        values = [math.sin(index / 5.0) for index in range(60)]

        with self.assertRaisesRegex(ValueError, "explicit ISO-8601 timestamps"):
            run_historical_oos_experiment(self.experiment, values)
        bad_labels = [f"row-{index}" for index in range(60)]
        with self.assertRaisesRegex(ValueError, "not ISO-8601 parseable"):
            run_historical_oos_experiment(self.experiment, values, labels=bad_labels)

    def test_run_trace_is_aligned_and_manifest_fingerprint_matches(self) -> None:
        contract, audit, dataset, attempt, run = self.run_materialized()

        self.assertEqual(run.data_fingerprint, dataset.manifest.materialized_fingerprint)
        self.assertEqual(run.attempt_id, attempt.attempt_id)
        self.assertEqual(run.run_signature, attempt.run_signature)
        self.assertEqual(run.evidence_unit_id, attempt.evidence_unit_id)
        self.assertEqual(run.data_contract_id, contract.contract_id)
        self.assertEqual(run.data_contract_audit_id, audit.audit_id)
        self.assertEqual(run.dataset_manifest_id, dataset.manifest.manifest_id)
        self.assertTrue(run.forecast_trace_fingerprint)
        self.assertEqual(len(run.actual_values), run.test_size)
        self.assertEqual(len(run.forecast_timestamps), run.test_size)
        self.assertEqual(len(run.forecast_origin_timestamps), run.test_size)
        self.assertEqual(len(run.candidate_predictions), run.test_size)
        self.assertEqual(len(run.candidate_errors), run.test_size)
        for actual, prediction, error in zip(
            run.actual_values, run.candidate_predictions, run.candidate_errors
        ):
            self.assertAlmostEqual(actual - prediction, error, places=10)

    def test_identical_reruns_have_unique_run_and_attempt_ids_but_same_evidence_identity(self) -> None:
        contract, audit, dataset = self.materialize()
        attempt_one = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        attempt_two = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )

        def execute(attempt):
            return run_historical_oos_experiment(
                self.experiment,
                dataset.values,
                labels=dataset.timestamps,
                attempt_id=attempt.attempt_id,
                run_signature=attempt.run_signature,
                evidence_unit_id=attempt.evidence_unit_id,
                data_contract_id=contract.contract_id,
                data_contract_audit_id=audit.audit_id,
                dataset_manifest_id=dataset.manifest.manifest_id,
                measurement_model_id=contract.measurement_model_id,
                measurement_decision_id=contract.measurement_decision_id,
                observable_id=contract.observable_id,
            )

        run_one = execute(attempt_one)
        run_two = execute(attempt_two)

        self.assertNotEqual(attempt_one.attempt_id, attempt_two.attempt_id)
        self.assertEqual(attempt_one.run_signature, attempt_two.run_signature)
        self.assertEqual(attempt_one.evidence_unit_id, attempt_two.evidence_unit_id)
        self.assertNotEqual(run_one.run_id, run_two.run_id)
        self.assertEqual(run_one.run_signature, run_two.run_signature)
        self.assertEqual(run_one.evidence_unit_id, run_two.evidence_unit_id)
        self.assertEqual(run_one.forecast_trace_fingerprint, run_two.forecast_trace_fingerprint)

    def test_experiment_registry_retains_identical_reruns(self) -> None:
        _, _, _, _, run_one = self.run_materialized()
        _, _, _, _, run_two = self.run_materialized()
        with tempfile.TemporaryDirectory() as directory:
            registry = ExperimentRegistry(directory)
            registry.save_run(run_one)
            registry.save_run(run_two)
            registry.save_run(run_one)  # exact re-save is idempotent

            runs = registry.list_runs()
            self.assertEqual(len(runs), 2)
            self.assertEqual({row["run_id"] for row in runs}, {run_one.run_id, run_two.run_id})

    def test_selection_pressure_counts_attempts_but_deduplicates_evidence_units(self) -> None:
        contract, audit, dataset, attempt_one, run_one = self.run_materialized()
        attempt_two = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        run_two = run_historical_oos_experiment(
            self.experiment,
            dataset.values,
            labels=dataset.timestamps,
            attempt_id=attempt_two.attempt_id,
            run_signature=attempt_two.run_signature,
            evidence_unit_id=attempt_two.evidence_unit_id,
            data_contract_id=contract.contract_id,
            data_contract_audit_id=audit.audit_id,
            dataset_manifest_id=dataset.manifest.manifest_id,
            measurement_model_id=contract.measurement_model_id,
            measurement_decision_id=contract.measurement_decision_id,
            observable_id=contract.observable_id,
        )
        pressure = build_selection_pressure_snapshot(
            question_id=self.question["question_id"],
            experiment_id=self.experiment["experiment_id"],
            attempts=[asdict(attempt_one), asdict(attempt_two)],
            runs=[asdict(run_one), asdict(run_two)],
        )

        self.assertEqual(pressure.total_attempts, 2)
        self.assertEqual(pressure.completed_runs, 2)
        self.assertEqual(pressure.unique_run_signatures, 1)
        self.assertEqual(pressure.unique_evidence_units, 1)
        self.assertEqual(pressure.unique_data_fingerprints, 1)


class RegistryAndCapsuleTests(Phase63FixtureMixin, unittest.TestCase):
    def test_phase63_registry_is_immutable_and_attempts_are_append_only(self) -> None:
        contract, audit, dataset = self.materialize()
        attempt_one = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        attempt_two = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase63Registry(directory)
            registry.save_contract(contract)
            registry.save_contract(contract)
            registry.save_contract_audit(audit)
            registry.save_manifest(dataset.manifest)
            registry.save_attempt(attempt_one)
            registry.save_attempt(attempt_two)

            self.assertEqual(len(registry.list_contracts()), 1)
            self.assertEqual(len(registry.list_attempts()), 2)
            with self.assertRaisesRegex(ValueError, "already exists"):
                registry.save_attempt(attempt_one)
            with self.assertRaisesRegex(ValueError, "Immutable registry identity collision"):
                registry.save_contract(replace(contract, rationale="Mutated after registration"))

    def test_corrupted_registry_blocks_reads_and_writes_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase63Registry(directory)
            corrupt_path = registry.paths["contracts"]
            corrupt_path.write_text('{"not": "an array"}', encoding="utf-8")
            before = corrupt_path.read_text(encoding="utf-8")

            with self.assertRaises(RegistryCorruptionError):
                registry.list_contracts()
            with self.assertRaises(RegistryCorruptionError):
                registry.save_contract(self.make_contract())
            self.assertEqual(corrupt_path.read_text(encoding="utf-8"), before)

    def test_attempt_lifecycle_is_guarded_and_failure_is_retained(self) -> None:
        contract, _, dataset = self.materialize()
        attempt = build_experiment_attempt(
            experiment=self.experiment,
            contract=contract,
            manifest=dataset.manifest,
            purpose="PREDECLARED_HISTORICAL_OOS",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase63Registry(directory)
            registry.save_attempt(attempt)
            running = registry.transition_attempt(
                attempt.attempt_id, "RUNNING", "Executor started after registration."
            )
            failed = registry.transition_attempt(
                attempt.attempt_id,
                "FAILED",
                "Input failed a predeclared check.",
                error=ValueError("bad input"),
            )

            self.assertTrue(running["started_at"])
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(failed["error_type"], "ValueError")
            self.assertEqual(len(failed["lifecycle_history"]), 3)
            with self.assertRaisesRegex(ValueError, "Invalid attempt transition"):
                registry.transition_attempt(attempt.attempt_id, "RUNNING", "Illegal retry")
            self.assertEqual(registry.list_attempts()[0]["status"], "FAILED")

    def test_reproducibility_capsule_is_exact_only_when_lineage_aligns(self) -> None:
        contract, _, dataset, attempt, run = self.run_materialized()
        capsule = build_reproducibility_capsule(
            run=run,
            attempt=attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="sha256:executor-v2",
            source_refs=["SOURCE-3"],
        )

        self.assertEqual(capsule.status, "COMPLETE")
        self.assertEqual(capsule.replay_grade, "EXACT")
        self.assertEqual(capsule.run_id, run.run_id)
        self.assertEqual(capsule.data_fingerprint, dataset.manifest.materialized_fingerprint)
        self.assertIn("SOURCE-3", capsule.source_refs)
        self.assertEqual(capsule.production_status, "RESEARCH_ONLY")

        broken = build_reproducibility_capsule(
            run=replace(run, data_fingerprint="wrong-fingerprint"),
            attempt=attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="sha256:executor-v2",
        )
        self.assertEqual(broken.status, "INCOMPLETE")
        self.assertEqual(broken.replay_grade, "NON_REPLAYABLE")
        self.assertIn("does not match", " ".join(broken.blockers))

    def test_capsule_never_persists_secret_like_environment_fields(self) -> None:
        contract, _, dataset, attempt, run = self.run_materialized()
        exposed_run = replace(
            run,
            environment={
                **run.environment,
                "api_key": "do-not-persist",
                "access_token": "do-not-persist",
                "secret": "do-not-persist",
            },
        )
        capsule = build_reproducibility_capsule(
            run=exposed_run,
            attempt=attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="sha256:executor-v2",
        )

        self.assertNotIn("api_key", capsule.environment)
        self.assertNotIn("access_token", capsule.environment)
        self.assertNotIn("secret", capsule.environment)

    def test_capsule_rejects_mismatched_attempt_and_run_protocol_identity(self) -> None:
        contract, _, dataset, attempt, run = self.run_materialized()
        unrelated_attempt = replace(
            attempt,
            attempt_id="ATTEMPT-unrelated",
            run_signature="RUNSIG-unrelated",
            evidence_unit_id="EUNIT-unrelated",
        )
        capsule = build_reproducibility_capsule(
            run=run,
            attempt=unrelated_attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="sha256:executor-v2",
        )

        self.assertEqual(capsule.status, "INCOMPLETE")
        self.assertEqual(capsule.replay_grade, "NON_REPLAYABLE")
        self.assertTrue(
            any("attempt" in blocker.lower() or "signature" in blocker.lower() for blocker in capsule.blockers)
        )

    def test_capsule_without_executor_digest_is_non_replayable(self) -> None:
        contract, _, dataset, attempt, run = self.run_materialized()
        capsule = build_reproducibility_capsule(
            run=run,
            attempt=attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="",
        )

        self.assertEqual(capsule.status, "INCOMPLETE")
        self.assertEqual(capsule.replay_grade, "NON_REPLAYABLE")
        self.assertIn("code digest", " ".join(capsule.blockers).lower())

    def test_registry_health_inspection_distinguishes_missing_valid_and_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.json"
            self.assertEqual(inspect_registry_file("fixture", path).status, "MISSING")
            path.write_text(json.dumps([{"id": "A"}, {"id": "B"}]), encoding="utf-8")
            valid = inspect_registry_file("fixture", path)
            self.assertEqual(valid.status, "OK")
            self.assertEqual(valid.row_count, 2)
            path.write_text("{", encoding="utf-8")
            invalid = inspect_registry_file("fixture", path)
            self.assertEqual(invalid.status, "INVALID")
            self.assertIn("JSONDecodeError", invalid.detail)


class MissionControlGateTests(Phase63FixtureMixin, unittest.TestCase):
    @staticmethod
    def gate(mission, gate_id: str):
        return next(gate for gate in mission.gates if gate.gate_id == gate_id)

    def make_snapshot(self) -> dict[str, object]:
        contract, audit, dataset, attempt, run = self.run_materialized()
        capsule = build_reproducibility_capsule(
            run=run,
            attempt=attempt,
            contract=contract,
            manifest=dataset.manifest,
            code_digest="sha256:executor-v2",
        )
        return {
            "captured_at": "2026-01-10T00:00:00+00:00",
            "registry_health": [],
            "questions": [dict(self.question)],
            "plans": [dict(self.plan)],
            "hypotheses": [
                {
                    "hypothesis_id": "HYP-OU",
                    "question_id": "QUESTION-1",
                    "label": "Regime-switching OU",
                    "priority_score": 0.9,
                },
                {
                    "hypothesis_id": "HYP-NULL",
                    "question_id": "QUESTION-1",
                    "label": "No stable mean-reversion mechanism",
                    "priority_score": 0.1,
                },
            ],
            "experiment_specs": [dict(self.experiment)],
            "measurement_models": [dict(self.measurement_model)],
            "measurement_decisions": [dict(self.measurement_decision)],
            "observables": [dict(self.observable), dict(self.competitor)],
            "measurement_hypotheses": [],
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
            "data_contracts": [asdict(contract)],
            "contract_audits": [asdict(audit)],
            "dataset_manifests": [asdict(dataset.manifest)],
            "attempts": [asdict(attempt)],
            "runs": [asdict(run)],
            "capsules": [asdict(capsule)],
            "reviews": [],
            "replications": [],
            "failures": [],
            "surprises": [],
            "budgets": [],
        }

    def test_mission_gates_recognize_audited_historical_lineage(self) -> None:
        mission = build_mission_snapshot(self.make_snapshot(), "QUESTION-1")

        for gate_id in (
            "REGISTRY_INTEGRITY",
            "PARTIAL_TRANSFER_ELIGIBLE",
            "SOURCE_GROUNDED_EVIDENCE",
            "MEASUREMENT_DECISION_RECORDED",
            "MEASUREMENT_STATE_CONSISTENT",
            "DATA_CONTRACT_VALIDATED",
            "POINT_IN_TIME_AUDITED",
            "MATERIALIZED_DATA_FINGERPRINTED",
            "BUILTIN_EXECUTOR_AUDITED",
            "ATTEMPT_REGISTERED",
            "HISTORICAL_OOS_COMPLETE",
            "FORECAST_TRACE_AVAILABLE",
            "REPRODUCIBILITY_CAPSULE",
            "PRODUCTION_PROMOTION_LOCK",
        ):
            self.assertEqual(self.gate(mission, gate_id).status, "SATISFIED", gate_id)
        self.assertEqual(
            self.gate(mission, "SELECTION_PRESSURE_RECORDED").status,
            "NOT_EVALUATED",
        )
        self.assertEqual(mission.counts["historical_runs"], 1)
        self.assertEqual(mission.counts["capsules"], 1)
        self.assertEqual(mission.overall_status, "WAITING_EVIDENCE")

    def test_selection_pressure_gate_requires_and_accepts_attached_snapshot(self) -> None:
        snapshot = self.make_snapshot()
        missing = build_mission_snapshot(snapshot, "QUESTION-1")
        self.assertEqual(
            self.gate(missing, "SELECTION_PRESSURE_RECORDED").status,
            "NOT_EVALUATED",
        )

        pressure = build_selection_pressure_snapshot(
            question_id="QUESTION-1",
            experiment_id="EXPERIMENT-1",
            attempts=snapshot["attempts"],
            runs=snapshot["runs"],
        )
        snapshot["runs"][0]["selection_context"] = asdict(pressure)
        recorded = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = self.gate(recorded, "SELECTION_PRESSURE_RECORDED")

        self.assertEqual(gate.status, "SATISFIED")
        self.assertIn(pressure.snapshot_id, gate.artifact_refs)
        self.assertIn("1 attempt", gate.summary)
        self.assertIn("screen", gate.summary)

    def test_reproducibility_gate_requires_complete_replayable_capsule_for_latest_run(self) -> None:
        snapshot = self.make_snapshot()
        satisfied = build_mission_snapshot(snapshot, "QUESTION-1")
        self.assertEqual(
            self.gate(satisfied, "REPRODUCIBILITY_CAPSULE").status,
            "SATISFIED",
        )

        snapshot["capsules"][0]["status"] = "INCOMPLETE"
        snapshot["capsules"][0]["replay_grade"] = "NON_REPLAYABLE"
        blocked = build_mission_snapshot(snapshot, "QUESTION-1")
        gate = self.gate(blocked, "REPRODUCIBILITY_CAPSULE")
        self.assertEqual(gate.status, "NOT_EVALUATED")
        self.assertIn("identity-aligned capsule", gate.next_action)

        snapshot["capsules"] = []
        missing = build_mission_snapshot(snapshot, "QUESTION-1")
        self.assertEqual(
            self.gate(missing, "REPRODUCIBILITY_CAPSULE").status,
            "NOT_EVALUATED",
        )

    def test_empty_reviewed_evidence_blocks_source_gate(self) -> None:
        snapshot = self.make_snapshot()
        snapshot["evidence"][0].update(
            claim_ids=[], mechanism_keys=[], semantic_entity_ids=[]
        )
        mission = build_mission_snapshot(snapshot, "QUESTION-1")

        self.assertEqual(self.gate(mission, "SOURCE_GROUNDED_EVIDENCE").status, "BLOCKED")
        self.assertEqual(mission.overall_status, "BLOCKED")
        self.assertTrue(any("contains no claims" in item for item in mission.inconsistencies))

    def test_invalid_registry_health_blocks_integrity_gate(self) -> None:
        snapshot = self.make_snapshot()
        snapshot["registry_health"] = [
            {
                "registry": "runs",
                "path": "/tmp/runs.json",
                "status": "INVALID",
                "row_count": 0,
                "detail": "JSONDecodeError",
            }
        ]
        mission = build_mission_snapshot(snapshot, "QUESTION-1")

        gate = self.gate(mission, "REGISTRY_INTEGRITY")
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIn("runs", gate.blockers)
        self.assertTrue(any("Registry runs is invalid" in item for item in mission.inconsistencies))

    def test_primary_measurement_lifecycle_conflict_is_visible(self) -> None:
        snapshot = self.make_snapshot()
        snapshot["observables"][0]["status"] = "PROPOSED"
        mission = build_mission_snapshot(snapshot, "QUESTION-1")

        self.assertEqual(self.gate(mission, "MEASUREMENT_STATE_CONSISTENT").status, "CONFLICT")
        self.assertTrue(any("instead of SELECTED" in item for item in mission.inconsistencies))

    def test_production_or_automatic_belief_promotion_blocks_lock(self) -> None:
        snapshot = self.make_snapshot()
        snapshot["runs"][0]["production_status"] = "PRODUCTION"
        snapshot["evidence_syntheses"] = [
            {
                "synthesis_id": "SYNTHESIS-1",
                "question_id": "QUESTION-1",
                "belief_update_authorized": True,
                "production_status": "RESEARCH_ONLY",
            }
        ]
        mission = build_mission_snapshot(snapshot, "QUESTION-1")

        gate = self.gate(mission, "PRODUCTION_PROMOTION_LOCK")
        self.assertEqual(gate.status, "BLOCKED")
        self.assertTrue(any("belief" in blocker.lower() for blocker in gate.blockers))
        self.assertTrue(any("runs:" in blocker for blocker in gate.blockers))


if __name__ == "__main__":
    unittest.main(verbosity=2)
