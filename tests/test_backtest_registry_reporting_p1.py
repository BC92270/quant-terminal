from __future__ import annotations

import base64
from dataclasses import replace
from io import BytesIO
import json
import subprocess
from zipfile import ZipFile

import pandas as pd
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backtest_institutional.evidence import SIGNATURE_ALGORITHM, TRUST_STORE_ENV
from backtest_institutional.registry import build_run_manifest, data_hash, stable_hash
from backtest_institutional.reporting import build_governance_bundle, build_model_card


def _bars() -> pd.DataFrame:
    frame = pd.DataFrame(
        {"close": [100.0, 101.0, 100.5], "volume": [1_000, 1_100, 900]},
        index=pd.date_range("2026-01-05", periods=3, freq="B"),
    )
    frame.attrs.update({
        "data_source": "vendor-a/pit-equities",
        "price_basis": "adjusted_total_return",
        "data_quality_issues": ["volume provenance inferred"],
        "provenance": {"dataset_version": "v4", "retrieved_at": "2026-01-10T09:00:00Z"},
        "retrieved_at": "2026-01-10T09:00:00Z",
    })
    return frame


def _manifest(tmp_path, bars: pd.DataFrame, *, created_at: str):
    package = tmp_path / "pkg"
    package.mkdir(exist_ok=True)
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return build_run_manifest(
        config={"capital": 1_000_000},
        market_data=bars,
        strategy="Unit",
        symbol="TEST",
        seed=3,
        code_path=package,
        package_path=package,
        metadata={"authoritative_source": "execution_ledger"},
        created_at=created_at,
    )


def _bundle(manifest) -> bytes:
    availability = {
        "Historical bootstrap": {"state": "AVAILABLE", "reason": "calibrated"},
        "Multivariate Student-t": {"state": "AVAILABLE", "reason": "calibrated"},
        "Markov regime switching": {"state": "AVAILABLE", "reason": "calibrated"},
        "EVT empirical tail": {"state": "UNAVAILABLE", "reason": "insufficient tail observations"},
        "Liquidity spiral": {"state": "AVAILABLE", "reason": "calibrated"},
    }
    return build_governance_bundle(
        manifest=manifest,
        config={"capital": 1_000_000},
        data_catalog={"verdict": "WARN", "capabilities": {}},
        execution={"model": "square_root"},
        validation={"candidate_count": 2},
        scenarios={"availability": availability, "reverse_stress": {"status": "AVAILABLE"}},
    )


def test_run_identity_includes_market_source_and_quality_but_not_fetch_clock(tmp_path):
    bars = _bars()
    first = _manifest(tmp_path, bars, created_at="2026-01-11T00:00:00Z")

    refetched = bars.copy()
    refetched.attrs = dict(bars.attrs) | {
        "provenance": {"dataset_version": "v4", "retrieved_at": "2026-02-20T15:30:00Z"},
        "retrieved_at": "2026-02-20T15:30:00Z",
    }
    same_snapshot = _manifest(tmp_path, refetched, created_at="2026-02-21T00:00:00Z")
    assert same_snapshot.run_id == first.run_id

    new_source = bars.copy()
    new_source.attrs = dict(bars.attrs) | {"data_source": "vendor-b/pit-equities"}
    assert _manifest(tmp_path, new_source, created_at=first.created_at).run_id != first.run_id

    new_quality = bars.copy()
    new_quality.attrs = dict(bars.attrs) | {"data_quality_issues": ["close synthesized"]}
    assert _manifest(tmp_path, new_quality, created_at=first.created_at).run_id != first.run_id
    assert first.metadata["identity_provenance"]["market_data_attrs"]["data_source"] == "vendor-a/pit-equities"


def test_run_identity_distinguishes_currency_venue_and_index_timezone(tmp_path):
    bars = _bars()
    bars.attrs.update({"currency": "USD", "exchange": "XNYS", "timezone": "UTC"})
    first = _manifest(tmp_path, bars, created_at="2026-01-11T00:00:00Z")

    euros = bars.copy()
    euros.attrs = dict(bars.attrs) | {"currency": "EUR"}
    assert _manifest(tmp_path, euros, created_at=first.created_at).run_id != first.run_id

    another_venue = bars.copy()
    another_venue.attrs = dict(bars.attrs) | {"exchange": "XPAR"}
    assert _manifest(tmp_path, another_venue, created_at=first.created_at).run_id != first.run_id

    utc = bars.copy()
    utc.index = utc.index.tz_localize("UTC")
    new_york = utc.copy()
    new_york.index = utc.index.tz_convert("America/New_York")
    assert data_hash(utc) != data_hash(new_york)


def test_same_run_bundle_is_byte_identical_across_created_at(tmp_path):
    first = _manifest(tmp_path, _bars(), created_at="2026-01-11T00:00:00Z")
    later = replace(first, created_at="2026-09-30T23:59:59Z")
    assert _bundle(first) == _bundle(later)

    with ZipFile(BytesIO(_bundle(first))) as archive:
        manifest_payload = json.loads(archive.read("manifest.json"))
        assert "created_at" not in manifest_payload
        assert manifest_payload["non_identity_fields_omitted"] == ["created_at"]


def test_model_card_declares_unavailable_scenarios_and_operational_qa(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    manifest = _manifest(tmp_path, _bars(), created_at="2026-01-11T00:00:00Z")
    with ZipFile(BytesIO(_bundle(manifest))) as archive:
        card = json.loads(archive.read("model_card.json"))

    coverage = card["methodology"]["scenario_coverage"]
    assert coverage["families"]["EVT empirical tail"]["state"] == "UNAVAILABLE"
    assert "EVT empirical tail" not in card["methodology"]["scenarios"]
    assert any("Unavailable scenario families" in item for item in card["limitations"])
    assert card["approval_policy"]["operational_qa"]["state"] == "UNAVAILABLE"
    assert card["approval_policy"]["automatic_production_authorization"] is False
    assert "operational QA" not in card["approval_policy"]["required_gates"]
    assert card["strategy_coverage"]["completeness_claim"] is False
    assert "options/futures Greeks, expiry, roll, margin and multi-leg exercise" in card[
        "strategy_coverage"
    ]["dedicated_engine_required"]

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv(
        TRUST_STORE_ENV,
        json.dumps({"qa-control": base64.b64encode(public_key).decode("ascii")}),
    )
    now = pd.Timestamp.now(tz="UTC")
    qa_payload = {
        "report_id": "QA-UNIT-1",
        "suite": "controlled-replay",
        "result": "PASS",
        "failures": 0,
    }
    qa_manifest = {
        "schema_version": "institutional_operational_qa_v1",
        "evidence_id": "QA-UNIT-1",
        "evidence_authority": "unit-test-control",
        "manifest_timestamp": now.isoformat(),
        "expires_at": (now + pd.Timedelta(hours=1)).isoformat(),
        "evidence_payload_hash": stable_hash(qa_payload),
        "run_id": manifest.run_id,
        "config_hash": manifest.config_hash,
        "data_hash": manifest.data_hash,
        "code_hash": manifest.code_hash,
        "environment_hash": manifest.environment_hash,
        "artifact_hashes_hash": stable_hash(manifest.metadata.get("artifact_hashes", {})),
        "signing_key_id": "qa-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }
    qa_manifest_hash = stable_hash(qa_manifest)
    direct = build_model_card(
        manifest=manifest,
        data_catalog={"verdict": "PASS", "capabilities": {}},
        execution={"model": "square_root"},
        validation={
            "candidate_count": 2,
            "operational_qa": {
                "state": "PASS",
                "reason": "hash-bound controlled report",
                "evidence_payload": qa_payload,
                "evidence_manifest": qa_manifest,
                "evidence_manifest_hash": qa_manifest_hash,
                "signature_base64": base64.b64encode(
                    private_key.sign(qa_manifest_hash.encode("ascii"))
                ).decode("ascii"),
            },
        },
        scenarios={
            "availability": {
                family: {"state": "AVAILABLE", "reason": "calibrated"}
                for family in coverage["families"]
            }
        },
    )
    assert direct["approval_policy"]["operational_qa"]["state"] == "PASS"
    assert direct["approval_policy"]["unevaluated_production_prerequisites"] == []

    failed_payload = dict(qa_payload) | {"result": "FAIL", "failures": 99}
    failed_manifest = dict(qa_manifest) | {
        "evidence_payload_hash": stable_hash(failed_payload),
    }
    failed_hash = stable_hash(failed_manifest)
    forged_wrapper = build_model_card(
        manifest=manifest,
        data_catalog={"verdict": "PASS", "capabilities": {}},
        execution={"model": "square_root"},
        validation={
            "candidate_count": 2,
            "operational_qa": {
                "state": "PASS",
                "reason": "unsigned wrapper claims success",
                "evidence_payload": failed_payload,
                "evidence_manifest": failed_manifest,
                "evidence_manifest_hash": failed_hash,
                "signature_base64": base64.b64encode(
                    private_key.sign(failed_hash.encode("ascii"))
                ).decode("ascii"),
            },
        },
        scenarios={"availability": {}},
    )
    assert forged_wrapper["approval_policy"]["operational_qa"]["state"] == "UNAVAILABLE"

    replay_manifest = dict(qa_manifest) | {"data_hash": "0" * 64}
    replay_hash = stable_hash(replay_manifest)
    replayed = build_model_card(
        manifest=manifest,
        data_catalog={"verdict": "PASS", "capabilities": {}},
        execution={"model": "square_root"},
        validation={
            "candidate_count": 2,
            "operational_qa": {
                "evidence_payload": qa_payload,
                "evidence_manifest": replay_manifest,
                "evidence_manifest_hash": replay_hash,
                "signature_base64": base64.b64encode(
                    private_key.sign(replay_hash.encode("ascii"))
                ).decode("ascii"),
            },
        },
        scenarios={"availability": {}},
    )
    assert replayed["approval_policy"]["operational_qa"]["state"] == "UNAVAILABLE"

    boolean_claim = build_model_card(
        manifest=manifest,
        data_catalog={"verdict": "PASS", "capabilities": {}},
        execution={"model": "square_root", "operational_qa": True},
        validation={"candidate_count": 2},
        scenarios={"availability": {}},
    )
    assert boolean_claim["approval_policy"]["operational_qa"]["state"] == "UNAVAILABLE"


def test_repository_provenance_is_cwd_independent_and_exported(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    package = repo / "backtest_institutional"
    package.mkdir(parents=True)
    module = package / "module.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    entrypoint = repo / "backtest_lab.py"
    entrypoint.write_text("from backtest_institutional import module\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("pandas==2.2.3\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(repo), "-c", "user.name=Test", "-c",
            "user.email=test@example.invalid", "commit", "-qm", "base",
        ],
        check=True,
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    manifest_args = dict(
        config={"capital": 100},
        market_data=_bars(),
        strategy="Unit",
        symbol="TEST",
        seed=3,
        code_path="backtest_lab.py",
        package_path=package,
        created_at="2026-01-11T00:00:00Z",
    )
    clean_manifest = build_run_manifest(**manifest_args)
    (repo / "requirements.txt").write_text("pandas==2.2.4\n", encoding="utf-8")
    dependency_changed = build_run_manifest(**manifest_args)
    assert dependency_changed.run_id != clean_manifest.run_id

    module.write_text(
        'VALUE = 2\n'
        'API_KEY = "alpha beta gamma"\n'
        'JSON_SECRET = \'{"X-API-Key": "delta epsilon zeta"}\'\n'
        'AUTH = "Authorization: Bearer bearer-secret-value"\n'
        'URL = "https://person:password@example.invalid/path"\n'
        'PEM = """-----BEGIN PRIVATE KEY-----\nsecret-material\n-----END PRIVATE KEY-----"""\n',
        encoding="utf-8",
    )
    (package / "untracked.py").write_text("EXTRA = True\n", encoding="utf-8")
    (repo / "requirements-private.txt").write_text(
        "private-wheel==1.0\n", encoding="utf-8"
    )
    manifest = build_run_manifest(**manifest_args)
    provenance = manifest.metadata["repository"]
    assert provenance["state"] == "AVAILABLE"
    assert provenance["commit"] != "UNAVAILABLE"
    assert len(provenance["tracked_diff_sha256"]) == 64
    assert provenance["captured_scope_dirty"] is True
    assert provenance["dependency_manifests"]["requirements.txt"]["bytes"] > 0
    assert "backtest_institutional/untracked.py" in provenance["untracked_inventory"]
    assert "requirements-private.txt" in provenance["untracked_inventory"]
    assert provenance["patch_reconstruction_complete"] is False

    bundle = _bundle(manifest)
    with ZipFile(BytesIO(bundle)) as archive:
        names = set(archive.namelist())
        assert {
            "repository/commit.txt",
            "repository/dirty.patch",
            "repository/dependencies.patch",
            "repository/provenance.json",
            "repository/untracked_inventory.json",
        }.issubset(names)
        patch = archive.read("repository/dirty.patch").decode("utf-8")
        for fragment in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta"):
            assert fragment not in patch
        assert "bearer-secret-value" not in patch
        assert "person:password@" not in patch
        assert "secret-material" not in patch
        assert "[REDACTED]" in patch
        dependency_patch = archive.read("repository/dependencies.patch").decode("utf-8")
        assert "pandas==2.2.4" in dependency_patch
        embedded_manifest = json.loads(archive.read("manifest.json"))
        assert "_bundle_evidence" not in embedded_manifest["metadata"]
