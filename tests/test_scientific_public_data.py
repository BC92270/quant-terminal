from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scientific_research.data_contract_engine import (
    audit_historical_data_contract,
    build_historical_data_contract,
    materialize_price_to_fundamental,
)
from scientific_research.public_data_pipeline import (
    BLS_HOUSING_URL,
    FHFA_HPI_URL,
    PUBLIC_DATASET_ID,
    PublicDataError,
    build_fhfa_bls_housing_bundle,
    fetch_fhfa_bls_housing_bundle,
    parse_bls_rent_sa,
    parse_fhfa_monthly_us_sa,
    persist_public_data_bundle,
    public_data_contract_preset,
)


UTC = timezone.utc


def _months(start_year: int = 2018, count: int = 72) -> list[tuple[int, int]]:
    output: list[tuple[int, int]] = []
    year = start_year
    month = 1
    for _ in range(count):
        output.append((year, month))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return output


def _fhfa_fixture(*, count: int = 72, bump: float = 0.0) -> bytes:
    lines = ["hpi_type,hpi_flavor,frequency,level,place_name,place_id,yr,period,index_nsa,index_sa,rstderr,note"]
    for index, (year, month) in enumerate(_months(count=count)):
        value = 200.0 + index * 0.8 + bump
        lines.append(
            f"traditional,purchase-only,monthly,USA or Census Division,United States,USA,"
            f"{year},{month},{value:.3f},{value + 0.2:.3f},,"
        )
    lines.append("traditional,purchase-only,monthly,USA or Census Division,Pacific Division,DV_PAC,2018,1,100,100,,")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _bls_fixture(*, count: int = 72) -> bytes:
    lines = ["series_id        \tyear\tperiod\t       value\tfootnote_codes"]
    for index, (year, month) in enumerate(_months(count=count)):
        value = 300.0 + index * 0.45
        lines.append(f"CUSR0000SEHA      \t{year}\tM{month:02d}\t{value:12.3f}\t")
    lines.append("CUUR0000SA0       \t2018\tM01\t     250.000\t")
    return ("\n".join(lines) + "\n").encode("utf-8")


class PublicDataParserTests(unittest.TestCase):
    def test_official_shapes_parse_and_filter_exact_series(self) -> None:
        hpi = parse_fhfa_monthly_us_sa(_fhfa_fixture())
        rent = parse_bls_rent_sa(_bls_fixture())

        self.assertEqual(len(hpi), 72)
        self.assertEqual(len(rent), 72)
        self.assertAlmostEqual(hpi[(2018, 1)], 200.2)
        self.assertAlmostEqual(rent[(2018, 1)], 300.0)

    def test_missing_schema_fails_closed(self) -> None:
        with self.assertRaisesRegex(PublicDataError, "missing required columns"):
            parse_fhfa_monthly_us_sa(b"<html>not a csv</html>")
        with self.assertRaisesRegex(PublicDataError, "missing required columns"):
            parse_bls_rent_sa(b"series\tvalue\nX\t1\n")

    def test_duplicate_month_is_rejected(self) -> None:
        payload = _fhfa_fixture()
        duplicate = payload + payload.decode("utf-8").splitlines()[1].encode("utf-8") + b"\n"
        with self.assertRaisesRegex(PublicDataError, "duplicate observation"):
            parse_fhfa_monthly_us_sa(duplicate)


class PublicDataBundleTests(unittest.TestCase):
    fetched_at = datetime(2025, 1, 15, 12, 0, tzinfo=UTC)

    def make_bundle(self, *, bump: float = 0.0):
        return build_fhfa_bls_housing_bundle(
            fhfa_content=_fhfa_fixture(bump=bump),
            bls_content=_bls_fixture(),
            fetched_at=self.fetched_at,
        )

    def test_bundle_is_chronological_fingerprinted_and_explicitly_revised(self) -> None:
        bundle = self.make_bundle()

        self.assertGreaterEqual(bundle.manifest.row_count, 60)
        self.assertEqual(bundle.manifest.revision_policy, "REVISED_WITH_RISK_FLAG")
        self.assertEqual(bundle.manifest.availability_time_quality, "CONSERVATIVE_PROXY")
        self.assertEqual(bundle.manifest.production_status, "RESEARCH_ONLY")
        self.assertEqual(bundle.manifest.dataset_id, PUBLIC_DATASET_ID)
        self.assertTrue(any("CURRENT-VIEW REVISED HISTORY" in item for item in bundle.manifest.warnings))
        timestamps = [row["timestamp"] for row in bundle.rows]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertEqual(len(timestamps), len(set(timestamps)))
        self.assertTrue(all(row["fundamental_release_timestamp"] <= row["timestamp"] for row in bundle.rows))

    def test_raw_byte_change_changes_source_and_dataset_fingerprints(self) -> None:
        first = self.make_bundle()
        second = self.make_bundle(bump=0.001)

        self.assertNotEqual(first.manifest.dataset_fingerprint, second.manifest.dataset_fingerprint)
        self.assertNotEqual(
            first.manifest.source_metadata[0]["sha256"],
            second.manifest.source_metadata[0]["sha256"],
        )

    def test_fetch_is_injectable_bounded_and_uses_both_official_urls(self) -> None:
        calls: list[tuple[str, int, int, str]] = []

        def fake_fetch(url: str, timeout: int, max_bytes: int, user_agent: str):
            calls.append((url, timeout, max_bytes, user_agent))
            if url == FHFA_HPI_URL:
                return _fhfa_fixture(), {"content-type": "text/csv", "etag": "fhfa-tag"}, url
            if url == BLS_HOUSING_URL:
                return _bls_fixture(), {"content-type": "text/plain", "last-modified": "today"}, url
            raise AssertionError(url)

        bundle = fetch_fhfa_bls_housing_bundle(
            timeout=17,
            user_agent="SRB-Test-Agent",
            fetched_at=self.fetched_at,
            fetcher=fake_fetch,
        )

        self.assertEqual([call[0] for call in calls], [FHFA_HPI_URL, BLS_HOUSING_URL])
        self.assertEqual([call[1] for call in calls], [17, 17])
        self.assertEqual([call[2] for call in calls], [25_000_000, 5_000_000])
        self.assertTrue(all(call[3] == "SRB-Test-Agent" for call in calls))
        self.assertEqual(bundle.manifest.source_metadata[0]["etag"], "fhfa-tag")

    def test_append_only_persistence_keeps_raw_payloads_and_is_idempotent(self) -> None:
        bundle = self.make_bundle()
        with tempfile.TemporaryDirectory() as tmp:
            target = persist_public_data_bundle(bundle, tmp)
            same_target = persist_public_data_bundle(bundle, tmp)

            self.assertEqual(target, same_target)
            self.assertEqual((target / "fhfa_hpi_master.csv").read_bytes(), _fhfa_fixture())
            self.assertEqual((target / "bls_us_housing.tsv").read_bytes(), _bls_fixture())
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["dataset_fingerprint"], bundle.manifest.dataset_fingerprint)
            self.assertEqual(manifest["production_status"], "RESEARCH_ONLY")
            self.assertEqual(len(list((Path(tmp) / "public_data_snapshots").iterdir())), 1)

    def test_bundle_materializes_under_the_existing_guarded_contract(self) -> None:
        bundle = self.make_bundle()
        preset = public_data_contract_preset()
        question = {
            "question_id": "QUESTION-PUBLIC", "plan_id": "PLAN-PUBLIC",
            "experiment_id": "EXPERIMENT-PUBLIC", "selected_observable_id": "OBS-PUBLIC",
            "target_variable": "market_state", "status": "PLANNED",
        }
        plan = {"plan_id": "PLAN-PUBLIC", "question_id": "QUESTION-PUBLIC"}
        experiment = {
            "experiment_id": "EXPERIMENT-PUBLIC", "status": "READY",
            "transfer_verdict": "PARTIAL_TRANSFER",
        }
        model = {
            "measurement_model_id": "MODEL-PUBLIC", "question_id": "QUESTION-PUBLIC",
            "primary_observable_id": "OBS-PUBLIC", "observable_ids": ["OBS-PUBLIC"],
            "target_concept": "market_state",
        }
        decision = {
            "decision_id": "DECISION-PUBLIC", "question_id": "QUESTION-PUBLIC",
            "measurement_model_id": "MODEL-PUBLIC", "selected_observable_id": "OBS-PUBLIC",
        }
        observable = {
            "observable_id": "OBS-PUBLIC", "question_id": "QUESTION-PUBLIC", "status": "SELECTED",
            "label": "House-price-to-fundamental rent residual",
            "mathematical_definition": "log(price_t) - log(fundamental_anchor_t)",
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
        self.assertEqual(audit.overall_status, "VALIDATED_WITH_WARNINGS")
        self.assertEqual(materialized.manifest.revision_risk_status, "PRESENT")
        self.assertEqual(materialized.manifest.valid_row_count, bundle.manifest.row_count)


if __name__ == "__main__":
    unittest.main()
