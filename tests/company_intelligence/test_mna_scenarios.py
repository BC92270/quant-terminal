"""Governance tests for the append-only M&A scenario ledger."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from company_intelligence.mna_scenarios import (
    GENESIS_HASH,
    ScenarioLedgerIntegrityError,
    append_scenario,
    load_scenarios,
    verify_ledger,
)


def test_append_only_revisions_form_a_verified_hash_chain(tmp_path):
    first = append_scenario(
        "nvda",
        "Base target case",
        {"premium": 0.30, "non_finite": float("nan")},
        context={"owner": "Analyst A", "review_status": "DRAFT", "scenario": "Base"},
        root=tmp_path,
    )
    second = append_scenario(
        "NVDA",
        "Base target case · revision 2",
        {"premium": 0.32},
        context={"owner": "Analyst A", "reviewer": "Reviewer B", "review_status": "READY FOR HUMAN REVIEW"},
        root=tmp_path,
    )

    records = load_scenarios("NVDA", root=tmp_path)
    status = verify_ledger("NVDA", root=tmp_path)

    assert [record["sequence"] for record in records] == [1, 2]
    assert first["prior_hash"] == GENESIS_HASH
    assert second["prior_hash"] == first["record_hash"]
    assert records[0]["payload"]["non_finite"] is None
    assert status["valid"] is True
    assert status["count"] == 2
    assert status["head_hash"] == second["record_hash"]


def test_tampering_is_detected_and_blocks_the_next_append(tmp_path):
    append_scenario("TST", "Original", {"premium": 0.20}, root=tmp_path)
    path = tmp_path / "TST.jsonl"
    record = json.loads(path.read_text(encoding="utf-8").strip())
    record["payload"]["premium"] = 0.90
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    status = verify_ledger("TST", root=tmp_path)

    assert status["valid"] is False
    assert status["reason"] == "record_hash"
    with pytest.raises(ScenarioLedgerIntegrityError):
        load_scenarios("TST", root=tmp_path)
    with pytest.raises(ScenarioLedgerIntegrityError):
        append_scenario("TST", "Must fail closed", {"premium": 0.10}, root=tmp_path)


def test_parallel_appends_are_serialized_without_lost_revisions(tmp_path):
    def save(index: int):
        return append_scenario(
            "../TST unsafe",
            f"Revision {index}",
            {"index": index},
            root=tmp_path,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(save, range(8)))

    files = sorted(path.name for path in tmp_path.glob("*.jsonl"))
    assert files == ["TST_UNSAFE.jsonl"]
    records = load_scenarios("TST unsafe", root=tmp_path)
    assert [record["sequence"] for record in records] == list(range(1, 9))
    assert {record["payload"]["index"] for record in records} == set(range(8))
    assert verify_ledger("TST unsafe", root=tmp_path)["valid"] is True


def test_environment_root_is_honored(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPANY_INTELLIGENCE_MNA_DIR", str(tmp_path))
    append_scenario("ENV", "Configured root", {"value": 1})

    assert (tmp_path / "ENV.jsonl").exists()
    assert load_scenarios("ENV")[0]["label"] == "Configured root"
