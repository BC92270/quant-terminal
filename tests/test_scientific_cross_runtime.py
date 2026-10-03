from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scientific_research.cross_runtime_verification import (
    compare_cross_runtime_results,
    freeze_cross_runtime_verification,
)
from scientific_research.phase65_registry import Phase65Registry


ROOT = Path(__file__).resolve().parents[1]


def _result() -> dict[str, object]:
    return {
        "market": "US",
        "market_label": "United States",
        "variant_id": "REAL_EER_LOG",
        "variant_label": "real",
        "formula": "log(REER_t)",
        "real_series_id": "RBUSBIS",
        "nominal_series_id": "NBUSBIS",
        "event_time_support_policy": "STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_EXCLUDE_NON_ADVANCING_BACKFILLS",
        "raw_common_row_count": 50,
        "co_release_excluded_count": 0,
        "non_advancing_backfill_excluded_count": 0,
        "excluded_support_rows": [],
        "row_count": 50,
        "verdict": "NO_OOS_IMPROVEMENT",
        "train_size": 35,
        "test_size": 15,
        "split_timestamp": "2020-01-20",
        "candidate_metrics": {"RMSE": 1.2, "MAE": 1.0, "DIRECTIONAL_ACCURACY": 0.5},
        "baseline_metrics": {"Random Walk / Last Observation": {"RMSE": 1.1}},
        "deltas_vs_baseline": {"Random Walk / Last Observation": {"RMSE_IMPROVEMENT_PCT": -9.09}},
        "fitted_parameters": {"intercept": 0.1, "phi": 0.9},
        "forecast_origin_timestamps": ["2019-12-20"],
        "forecast_timestamps": ["2020-01-20"],
        "actual_values": [1.0],
        "candidate_predictions": [0.8],
        "candidate_errors": [0.2],
        "baseline_predictions": {"Random Walk / Last Observation": [0.9]},
        "baseline_errors": {"Random Walk / Last Observation": [0.1]},
        "forecast_comparison": {"status": "INSUFFICIENT_OBSERVATIONS", "sample_size": 1},
        "production_status": "RESEARCH_ONLY",
    }


def _replication() -> dict[str, object]:
    result = _result()
    return {
        "replication_id": "IRP-TEST",
        "protocol_version": "SRB_INDEPENDENT_REPLICATION_V1",
        "protocol_fingerprint": "sha256:protocol",
        "status": "COMPLETE",
        "execution_status": "COMPLETE",
        "point_in_time_status": "PASS",
        "independence_gate_status": "PASS",
        "event_time_support_policy": "STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_EXCLUDE_NON_ADVANCING_BACKFILLS",
        "snapshot_id": "ALFREDIR-0123456789abcdef",
        "source_snapshot_fingerprint": "sha256:snapshot",
        "execution_fingerprint": "sha256:execution",
        "markets": ["US"],
        "measurement_variants": [{"variant_id": "REAL_EER_LOG", "label": "real", "formula": "log(REER_t)"}],
        "series_matrix": {"US": {"label": "United States", "real_series_id": "RBUSBIS", "nominal_series_id": "NBUSBIS"}},
        "train_fraction": 0.7,
        "forecast_horizon": 1,
        "min_common_rows": 40,
        "multiplicity_policy": "HOLM_BONFERRONI_ACROSS_ALL_MARKET_MEASUREMENT_TESTS",
        "replication_outcome": "CONSISTENT_NO_OOS_IMPROVEMENT",
        "result_count": 1,
        "promising_result_count": 0,
        "no_improvement_result_count": 1,
        "results": [result],
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }


class CrossRuntimeVerificationTests(unittest.TestCase):
    def test_freeze_is_deterministic_and_excludes_python_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "public_data" / "alfred_initial_release" / "ALFREDIR-0123456789abcdef"
            snapshot.mkdir(parents=True)
            snapshot.joinpath("manifest.json").write_text("{}\n", encoding="utf-8")
            fake = {}
            for series_id in ("RBUSBIS", "NBUSBIS"):
                path = snapshot / f"{series_id}_canonical.csv"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=("period_start_date", "value", "realtime_start_date"))
                    writer.writeheader()
                    writer.writerow({"period_start_date": "2020-01-01", "value": 100, "realtime_start_date": "2020-02-20"})
                fake[series_id] = SimpleNamespace(rows=[object()])
            with patch(
                "scientific_research.cross_runtime_verification.load_persisted_alfred_snapshot_bundle",
                return_value=fake,
            ):
                first = freeze_cross_runtime_verification(
                    _replication(), data_root=root, package_root=ROOT / "scientific_research",
                )
                second = freeze_cross_runtime_verification(
                    _replication(), data_root=root, package_root=ROOT / "scientific_research",
                )
            self.assertEqual(first.verification_id, second.verification_id)
            self.assertEqual(first.challenge_fingerprint, second.challenge_fingerprint)
            manifest = json.loads((root / first.challenge_manifest_path).read_text(encoding="utf-8"))
            self.assertNotIn("results", manifest)
            self.assertEqual(manifest["investigator_independent"], False)
            self.assertEqual(manifest["implementation_independence_claim"], "SEPARATE_TYPESCRIPT_NODE_CODEPATH")

    def test_comparator_passes_equal_result_and_retains_mismatch(self) -> None:
        reference = _replication()
        output = {
            "engine_protocol_version": "SRB_TYPESCRIPT_REPLICATION_ENGINE_V1",
            "implementation_separation": "SEPARATE_TYPESCRIPT_NODE_CODEPATH",
            "investigator_independent": False,
            "replication_id": reference["replication_id"],
            "snapshot_id": reference["snapshot_id"],
            "snapshot_fingerprint": reference["source_snapshot_fingerprint"],
            "replication_outcome": reference["replication_outcome"],
            "result_count": 1,
            "promising_result_count": 0,
            "no_improvement_result_count": 1,
            "results": [dict(reference["results"][0])],
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }
        passed = compare_cross_runtime_results(reference, output)
        self.assertEqual(passed["parity_status"], "PASS")
        self.assertEqual(passed["matched_result_count"], 1)
        output["results"][0]["candidate_predictions"] = [0.7]
        failed = compare_cross_runtime_results(reference, output)
        self.assertEqual(failed["parity_status"], "FAIL")
        self.assertGreater(failed["discrepancy_count"], 0)

    def test_registry_requires_freeze_then_append_only_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry = Phase65Registry(directory)
            frozen = {
                "verification_id": "XRV-1", "created_at": "2026-01-01T00:00:00+00:00",
                "replication_id": "IRP-1", "challenge_fingerprint": "sha256:challenge",
                "challenge_manifest_path": "cross_runtime/XRV-1/challenge.json",
                "source_snapshot_id": "S-1", "source_snapshot_fingerprint": "sha256:snapshot",
                "reference_execution_fingerprint": "sha256:reference", "engine_source_fingerprint": "sha256:source",
                "protocol_version": "SRB_CROSS_RUNTIME_VERIFICATION_V1", "status": "FROZEN",
                "execution_status": "NOT_RUN", "automatic_promotion_authorized": False,
                "production_status": "RESEARCH_ONLY",
            }
            registry.save_verification(frozen)
            completed = {
                **frozen, "status": "COMPLETE", "execution_status": "COMPLETE", "parity_status": "PASS",
                "implementation_gate_status": "PASS", "engine_build_fingerprint": "sha256:build",
                "result_fingerprint": "sha256:result", "result_count": 9, "matched_result_count": 9,
            }
            registry.save_verification(completed)
            with self.assertRaisesRegex(ValueError, "append-only"):
                registry.save_verification({**completed, "matched_result_count": 8})


if __name__ == "__main__":
    unittest.main()
