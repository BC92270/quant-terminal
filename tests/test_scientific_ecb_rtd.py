from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from scientific_research.data_contract_engine import (
    audit_historical_data_contract,
    build_historical_data_contract,
    materialize_price_to_fundamental,
)
from scientific_research.public_data_pipeline import (
    ECB_RTD_COLUMNS,
    ECB_RTD_DATASET_ID,
    ECB_RTD_NOMINAL_SERIES_KEY,
    ECB_RTD_NOMINAL_URL,
    ECB_RTD_REAL_SERIES_KEY,
    ECB_RTD_REAL_URL,
    PublicDataError,
    build_ecb_rtd_eer_bundle,
    ecb_rtd_contract_preset,
    fetch_ecb_rtd_eer_bundle,
    parse_ecb_rtd_first_vintages,
    persist_public_data_bundle,
)


UTC = timezone.utc


def _month(index: int) -> tuple[int, int]:
    return 2018 + index // 12, index % 12 + 1


def _ecb_fixture(
    series_key: str,
    *,
    count: int = 64,
    bump: float = 0.0,
    conflict: bool = False,
) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=ECB_RTD_COLUMNS, lineterminator="\n")
    writer.writeheader()
    rows: list[dict[str, str]] = []
    concept = series_key.split(".")[4]
    for index in range(count):
        year, month = _month(index)
        reference_period = f"{year:04d}-{month:02d}"
        release_index = 12 if index in {10, 11, 12} else index
        release_year, release_month = _month(release_index + 1)
        valid_from = datetime(release_year, release_month, 10, 15, 30, tzinfo=UTC)
        row = {field: "" for field in ECB_RTD_COLUMNS}
        row.update({
            "KEY": series_key,
            "FREQ": "M",
            "REF_AREA": "S0",
            "ADJUSTMENT": "N",
            "RT_ECON_CONCEPT": concept,
            "RT_DENOM": "X",
            "TIME_PERIOD": reference_period,
            "OBS_VALUE": f"{95.0 + index * 0.25 + bump:.6f}",
            "OBS_STATUS": "P" if index == count - 1 else "A",
            "TIME_FORMAT": "P1M",
            "UNIT": "Index",
            "ACTION": "Replace",
            "VALID_FROM": valid_from.isoformat(),
        })
        rows.append(row)

    # A later revision proves that parsing keeps the earliest exposed vintage.
    revised = dict(rows[0])
    revised["OBS_VALUE"] = f"{float(revised['OBS_VALUE']) + 5.0:.6f}"
    revised["VALID_FROM"] = (
        datetime.fromisoformat(rows[0]["VALID_FROM"]) + timedelta(days=35)
    ).isoformat()
    rows.append(revised)
    if conflict:
        conflicting = dict(rows[1])
        conflicting["OBS_VALUE"] = f"{float(conflicting['OBS_VALUE']) + 1.0:.6f}"
        rows.append(conflicting)
    for row in rows:
        writer.writerow(row)
    return output.getvalue().encode("utf-8")


class EcbRtdParserTests(unittest.TestCase):
    def test_exact_series_keeps_earliest_recorded_vintage_and_status(self) -> None:
        parsed = parse_ecb_rtd_first_vintages(
            _ecb_fixture(ECB_RTD_REAL_SERIES_KEY),
            series_key=ECB_RTD_REAL_SERIES_KEY,
        )

        self.assertEqual(len(parsed), 64)
        self.assertAlmostEqual(parsed["2018-01"]["value"], 95.0)
        self.assertEqual(parsed["2023-04"]["obs_status"], "P")
        self.assertEqual(parsed["2018-01"]["action"], "Replace")

    def test_schema_and_conflicting_vintage_fail_closed(self) -> None:
        with self.assertRaisesRegex(PublicDataError, "pinned csvdata schema"):
            parse_ecb_rtd_first_vintages(
                b"TIME_PERIOD,OBS_VALUE\n2018-01,1\n",
                series_key=ECB_RTD_REAL_SERIES_KEY,
            )
        with self.assertRaisesRegex(PublicDataError, "conflicting duplicate vintages"):
            parse_ecb_rtd_first_vintages(
                _ecb_fixture(ECB_RTD_REAL_SERIES_KEY, conflict=True),
                series_key=ECB_RTD_REAL_SERIES_KEY,
            )


class EcbRtdBundleTests(unittest.TestCase):
    fetched_at = datetime(2030, 1, 1, tzinfo=UTC)

    def make_bundle(self, *, bump: float = 0.0):
        return build_ecb_rtd_eer_bundle(
            nominal_content=_ecb_fixture(ECB_RTD_NOMINAL_SERIES_KEY),
            real_content=_ecb_fixture(ECB_RTD_REAL_SERIES_KEY, bump=bump),
            fetched_at=self.fetched_at,
        )

    def test_release_batches_become_exact_unique_causal_events(self) -> None:
        bundle = self.make_bundle()

        self.assertEqual(bundle.manifest.dataset_id, ECB_RTD_DATASET_ID)
        self.assertEqual(bundle.manifest.revision_policy, "POINT_IN_TIME_VINTAGES")
        self.assertEqual(bundle.manifest.availability_time_quality, "CONTROLLED")
        self.assertEqual(bundle.manifest.status, "VALIDATED")
        self.assertEqual(bundle.manifest.production_status, "RESEARCH_ONLY")
        self.assertEqual(bundle.manifest.row_count, 62)
        timestamps = [row["timestamp"] for row in bundle.rows]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len(timestamps), len(set(timestamps)))
        batched = next(row for row in bundle.rows if row["release_batch_size"] == 3)
        self.assertEqual(batched["reference_period"], "2019-01")
        self.assertEqual(batched["release_batch_first_reference_period"], "2018-11")
        self.assertEqual(batched["vintage_timestamp"], batched["timestamp"])
        self.assertEqual(batched["price_series_id"], ECB_RTD_REAL_SERIES_KEY)

    def test_raw_change_changes_dataset_fingerprint(self) -> None:
        first = self.make_bundle()
        second = self.make_bundle(bump=0.001)
        self.assertNotEqual(first.manifest.dataset_fingerprint, second.manifest.dataset_fingerprint)
        self.assertNotEqual(
            first.manifest.source_metadata[1]["sha256"],
            second.manifest.source_metadata[1]["sha256"],
        )

    def test_fetch_is_bounded_no_key_and_html_fails_closed(self) -> None:
        calls: list[tuple[str, int, int, str]] = []

        def fake_fetch(url: str, timeout: int, max_bytes: int, user_agent: str):
            calls.append((url, timeout, max_bytes, user_agent))
            payload = (
                _ecb_fixture(ECB_RTD_NOMINAL_SERIES_KEY)
                if url == ECB_RTD_NOMINAL_URL
                else _ecb_fixture(ECB_RTD_REAL_SERIES_KEY)
            )
            return payload, {"content-type": "text/csv"}, url

        bundle = fetch_ecb_rtd_eer_bundle(
            timeout=23,
            user_agent="SRB-Test-Agent contact=test@example.invalid",
            fetched_at=self.fetched_at,
            fetcher=fake_fetch,
        )
        self.assertGreaterEqual(bundle.manifest.row_count, 40)
        self.assertEqual([call[0] for call in calls], [ECB_RTD_NOMINAL_URL, ECB_RTD_REAL_URL])
        self.assertEqual([call[1] for call in calls], [23, 23])
        self.assertEqual([call[2] for call in calls], [5_000_000, 5_000_000])
        self.assertTrue(all("contact=" in call[3] for call in calls))

        def html_fetch(url: str, timeout: int, max_bytes: int, user_agent: str):
            return b"<html>blocked</html>", {"content-type": "text/html"}, url

        with self.assertRaisesRegex(PublicDataError, "returned HTML"):
            fetch_ecb_rtd_eer_bundle(fetcher=html_fetch, fetched_at=self.fetched_at)

    def test_append_only_archive_and_guarded_materializer(self) -> None:
        bundle = self.make_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            target = persist_public_data_bundle(bundle, tmp)
            same = persist_public_data_bundle(bundle, tmp)
            self.assertEqual(target, same)
            self.assertTrue((target / "ecb_rtd_nominal_eer.csv").is_file())
            self.assertTrue((target / "ecb_rtd_real_eer.csv").is_file())
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["dataset_fingerprint"], bundle.manifest.dataset_fingerprint)

        preset = ecb_rtd_contract_preset()
        question = {
            "question_id": "QUESTION-ECB", "plan_id": "PLAN-ECB",
            "experiment_id": "EXPERIMENT-ECB", "selected_observable_id": "OBS-ECB",
            "target_variable": "competitiveness_wedge", "status": "PLANNED",
        }
        plan = {"plan_id": "PLAN-ECB", "question_id": "QUESTION-ECB"}
        experiment = {
            "experiment_id": "EXPERIMENT-ECB", "status": "READY",
            "transfer_verdict": "PARTIAL_TRANSFER",
        }
        model = {
            "measurement_model_id": "MODEL-ECB", "question_id": "QUESTION-ECB",
            "primary_observable_id": "OBS-ECB", "observable_ids": ["OBS-ECB"],
            "target_concept": "competitiveness_wedge",
        }
        decision = {
            "decision_id": "DECISION-ECB", "question_id": "QUESTION-ECB",
            "measurement_model_id": "MODEL-ECB", "selected_observable_id": "OBS-ECB",
        }
        observable = {
            "observable_id": "OBS-ECB", "question_id": "QUESTION-ECB", "status": "SELECTED",
            "label": "Real-to-nominal fundamental competitiveness wedge",
            "mathematical_definition": "log(real_eer_t) - log(nominal_eer_t)",
        }
        contract = build_historical_data_contract(
            question=question,
            plan=plan,
            experiment=experiment,
            measurement_model=model,
            measurement_decision=decision,
            observable=observable,
            **preset,
        )
        audit = audit_historical_data_contract(contract)
        materialized = materialize_price_to_fundamental(
            bundle.rows,
            contract,
            dataset_label=bundle.manifest.dataset_label,
            contract_audit=audit,
        )

        self.assertEqual(contract.status, "VALIDATED")
        self.assertEqual(audit.point_in_time_status, "PASS")
        self.assertEqual(materialized.manifest.point_in_time_status, "PASS")
        self.assertEqual(materialized.manifest.revision_risk_status, "CONTROLLED")
        self.assertEqual(materialized.manifest.valid_row_count, bundle.manifest.row_count)


if __name__ == "__main__":
    unittest.main()
