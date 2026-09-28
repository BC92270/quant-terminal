from __future__ import annotations

import base64
import json

import numpy as np
import pandas as pd
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backtest_institutional.evidence import SIGNATURE_ALGORITHM, TRUST_STORE_ENV
from backtest_institutional.engine import run_institutional_stack
from backtest_institutional.execution import ExecutionModelConfig
from backtest_institutional.registry import data_hash, stable_hash
from backtest_institutional.scenarios import ScenarioConfig


def _market(n: int = 180) -> pd.DataFrame:
    index = pd.bdate_range("2025-01-02", periods=n)
    close = 100.0 * np.cumprod(1.0 + 0.0005 + 0.003 * np.sin(np.linspace(0, 12, n)))
    frame = pd.DataFrame(
        {
            "Open": close * 0.999,
            "High": close * 1.004,
            "Low": close * 0.996,
            "Close": close,
            "Volume": 4_000_000.0,
        },
        index=index,
    )
    frame.attrs.update({
        "price_basis": "adjusted_total_return",
        "periods_per_year": 252,
        "interval_label": "1d",
        "data_source": "unit/pit",
    })
    return frame


def _legacy(bars: pd.DataFrame) -> dict[str, object]:
    exposure = pd.Series(0.0, index=bars.index)
    exposure.iloc[20:95] = 0.6
    exposure.iloc[120:165] = 0.35
    return {"data": pd.DataFrame({"exposure": exposure}, index=bars.index)}


def _run(
    bars: pd.DataFrame,
    *,
    candidates: pd.DataFrame | None = None,
    factors: pd.DataFrame | None = None,
    point_in_time: bool = False,
):
    return run_institutional_stack(
        bars=bars,
        legacy_result=_legacy(bars),
        strategy="Evidence oracle",
        symbol="TEST",
        config_payload={
            "capital": 1_000_000.0,
            "periods_per_year": 252,
            "interval_label": "1d",
        },
        execution_config=ExecutionModelConfig(
            model="constant",
            commission_bps=0.5,
            spread_bps=1.0,
            slippage_bps=0.5,
        ),
        scenario_config=ScenarioConfig(horizon_days=20, paths=20, seed=23),
        candidate_returns=candidates,
        factor_returns=factors,
        point_in_time=point_in_time,
        seed=23,
    )


@pytest.fixture
def evidence_signer(monkeypatch: pytest.MonkeyPatch) -> Ed25519PrivateKey:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv(
        TRUST_STORE_ENV,
        json.dumps({"unit-control": base64.b64encode(public_key).decode("ascii")}),
    )
    return private_key


def _signature(private_key: Ed25519PrivateKey, manifest_hash: str) -> str:
    return base64.b64encode(private_key.sign(manifest_hash.encode("ascii"))).decode("ascii")


def _certify_candidates(
    frame: pd.DataFrame,
    bars: pd.DataFrame,
    private_key: Ed25519PrivateKey,
) -> None:
    columns = [str(column) for column in frame.columns]
    payload_hash = data_hash(frame)
    manifest = {
        "schema_version": "institutional_returns_v1",
        "dataset_kind": "candidate_returns",
        "frequency": "1d",
        "periods_per_year": 252,
        "return_convention": "simple",
        "return_unit": "decimal",
        "currency": "USD",
        "net_of_costs": True,
        "evidence_id": "UNIT-CANDIDATES-001",
        "evidence_authority": "unit-test-controlled-ledger",
        "manifest_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "evidence_payload_hash": payload_hash,
        "point_in_time": True,
        "source_snapshot_id": "UNIT-CANDIDATE-LEDGER-001",
        "source_snapshot_hash": payload_hash,
        "market_data_snapshot_hash": data_hash(bars),
        "knowledge_cutoff": pd.Timestamp.now(tz="UTC").isoformat(),
        "revision_policy": "derived_from_pit_snapshot",
        "trial_ids": {column: f"trial-{i}" for i, column in enumerate(columns)},
        "trial_config_hashes": {
            column: stable_hash({"trial": column, "version": 1}) for column in columns
        },
        "complete_trial_ledger": True,
        "signing_key_id": "unit-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "candidate_family_certified": True,
    }
    manifest_hash = stable_hash(manifest)
    frame.attrs.update({
        "evidence_manifest_payload": manifest,
        "evidence_manifest_hash": manifest_hash,
        "evidence_payload_hash": payload_hash,
        "evidence_signature_base64": _signature(private_key, manifest_hash),
        **manifest,
    })


def _certify_pit(bars: pd.DataFrame, private_key: Ed25519PrivateKey) -> None:
    manifest = {
        "schema_version": "institutional_pit_manifest_v1",
        "point_in_time": True,
        "source_snapshot_id": "UNIT-PIT-2025",
        "source_snapshot_hash": data_hash(bars),
        "source": "unit/pit",
        "manifest_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "knowledge_cutoff": pd.Timestamp.now(tz="UTC").isoformat(),
        "evidence_authority": "unit-test-market-data-control",
        "signing_key_id": "unit-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }
    manifest_hash = stable_hash(manifest)
    bars.attrs.update({
        "point_in_time_manifest": manifest,
        "point_in_time_manifest_hash": manifest_hash,
        "point_in_time_signature_base64": _signature(private_key, manifest_hash),
        "source_snapshot_id": manifest["source_snapshot_id"],
        "source_snapshot_hash": manifest["source_snapshot_hash"],
    })


def _certify_factors(
    frame: pd.DataFrame,
    bars: pd.DataFrame,
    private_key: Ed25519PrivateKey,
) -> None:
    columns = [str(column) for column in frame.columns]
    payload_hash = data_hash(frame)
    vintage_ledger = pd.DataFrame(
        [
            {
                "observation_at": pd.Timestamp(observation).isoformat(),
                "factor": column,
                "available_at": pd.Timestamp(observation).isoformat(),
                "vintage_id": f"vintage-{pd.Timestamp(observation).date().isoformat()}",
            }
            for observation in frame.index
            for column in columns
            if pd.notna(frame.at[observation, column])
        ],
        columns=["observation_at", "factor", "available_at", "vintage_id"],
    ).sort_values(["observation_at", "factor"], kind="stable", ignore_index=True)
    manifest = {
        "schema_version": "institutional_returns_v1",
        "dataset_kind": "factor_returns",
        "frequency": "1d",
        "periods_per_year": 252,
        "return_convention": "simple",
        "return_unit": "decimal",
        "currency": "USD",
        "net_of_costs": False,
        "evidence_id": "UNIT-FACTORS-001",
        "evidence_authority": "unit-test-vintage-store",
        "manifest_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "evidence_payload_hash": payload_hash,
        "point_in_time": True,
        "source_snapshot_id": "UNIT-FACTOR-VINTAGE-001",
        "source_snapshot_hash": payload_hash,
        "market_data_snapshot_hash": data_hash(bars),
        "knowledge_cutoff": pd.Timestamp.now(tz="UTC").isoformat(),
        "revision_policy": "vintage_locked",
        "vintage_ledger_hash": data_hash(vintage_ledger),
        "trial_ids": {column: f"factor-{i}" for i, column in enumerate(columns)},
        "trial_config_hashes": {
            column: stable_hash({"factor": column, "vintage": 1}) for column in columns
        },
        "complete_trial_ledger": False,
        "signing_key_id": "unit-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "candidate_family_certified": False,
    }
    manifest_hash = stable_hash(manifest)
    frame.attrs.update({
        "evidence_manifest_payload": manifest,
        "evidence_manifest_hash": manifest_hash,
        "evidence_payload_hash": payload_hash,
        "evidence_signature_base64": _signature(private_key, manifest_hash),
        "factor_vintage_ledger": vintage_ledger,
        **manifest,
    })


def test_candidate_gate_requires_trusted_signature_semantics_and_selected_execution(
    evidence_signer: Ed25519PrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bars = _market()
    baseline = _run(bars)
    selected = baseline.authoritative_returns.reindex(bars.index)
    candidates = pd.DataFrame(
        {
            "selected": selected,
            "challenger": selected.shift(1).fillna(0.0) * 0.75,
        },
        index=bars.index,
    )
    _certify_candidates(candidates, bars, evidence_signer)

    certified = _run(bars, candidates=candidates)
    evidence = certified.validation["candidate_evidence"]
    assert evidence["certified"] is True
    assert certified.validation["candidate_family_certified"] is True
    check = certified.gate["checks"].set_index("gate").loc["Candidate trial provenance"]
    assert check["state"] == "PASS"

    monkeypatch.delenv(TRUST_STORE_ENV)
    untrusted = _run(bars, candidates=candidates)
    assert untrusted.validation["candidate_family_certified"] is False
    assert any(
        "trust store" in reason
        for reason in untrusted.validation["candidate_evidence"]["reasons"]
    )
    # Restore the independently installed trust anchor for tamper checks below.
    public_key = evidence_signer.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    monkeypatch.setenv(
        TRUST_STORE_ENV,
        json.dumps({"unit-control": base64.b64encode(public_key).decode("ascii")}),
    )

    boolean_only = candidates.copy()
    boolean_only.attrs = {"candidate_family_certified": True, "complete_trial_ledger": True}
    rejected = _run(bars, candidates=boolean_only)
    assert rejected.validation["candidate_family_certified"] is False
    assert "canonical evidence manifest missing" in rejected.validation["candidate_evidence"]["reasons"]

    tampered = candidates.copy()
    tampered.attrs = dict(candidates.attrs)
    tampered.iloc[10, 1] += 0.01
    rejected_tamper = _run(bars, candidates=tampered)
    assert rejected_tamper.validation["candidate_family_certified"] is False
    assert any("payload hash" in reason for reason in rejected_tamper.validation["candidate_evidence"]["reasons"])


def test_signed_minimal_manifest_cannot_borrow_candidate_semantics_from_unsigned_attrs(
    evidence_signer: Ed25519PrivateKey,
) -> None:
    bars = _market()
    baseline = _run(bars)
    selected = baseline.authoritative_returns.reindex(bars.index)
    candidates = pd.DataFrame(
        {"selected": selected, "challenger": selected.shift(1).fillna(0.0)},
        index=bars.index,
    )
    payload_hash = data_hash(candidates)
    forged_semantics = {
        "schema_version": "institutional_returns_v1",
        "dataset_kind": "candidate_returns",
        "frequency": "1d",
        "periods_per_year": 252,
        "return_convention": "simple",
        "return_unit": "decimal",
        "currency": "USD",
        "net_of_costs": True,
        "evidence_id": "FORGED-ATTRS",
        "evidence_authority": "not-signed",
        "manifest_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "evidence_payload_hash": payload_hash,
        "point_in_time": True,
        "source_snapshot_id": "FORGED-SNAPSHOT",
        "source_snapshot_hash": payload_hash,
        "market_data_snapshot_hash": data_hash(bars),
        "knowledge_cutoff": pd.Timestamp.now(tz="UTC").isoformat(),
        "revision_policy": "derived_from_pit_snapshot",
        "trial_ids": {"selected": "trial-0", "challenger": "trial-1"},
        "trial_config_hashes": {
            "selected": stable_hash({"trial": 0}),
            "challenger": stable_hash({"trial": 1}),
        },
        "complete_trial_ledger": True,
        "candidate_family_certified": True,
        "signing_key_id": "unit-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
    }
    minimal_manifest = {"unrelated_document": "validly signed but not evidence"}
    manifest_hash = stable_hash(minimal_manifest)
    candidates.attrs.update(
        forged_semantics
        | {
            "evidence_manifest_payload": minimal_manifest,
            "evidence_manifest_hash": manifest_hash,
            "evidence_signature_base64": _signature(evidence_signer, manifest_hash),
        }
    )

    rejected = _run(bars, candidates=candidates)
    evidence = rejected.validation["candidate_evidence"]
    assert evidence["certified"] is False
    assert "schema_version must be institutional_returns_v1" in evidence["reasons"]
    assert "numeric payload SHA-256 missing or invalid" in evidence["reasons"]


def test_signed_candidate_selected_series_must_match_full_canonical_history(
    evidence_signer: Ed25519PrivateKey,
) -> None:
    bars = _market()
    baseline = _run(bars)
    selected = baseline.authoritative_returns.reindex(bars.index)
    sparse_selected = selected.copy()
    sparse_selected.iloc[30:] = np.nan
    candidates = pd.DataFrame(
        {"selected": sparse_selected, "challenger": selected.shift(1).fillna(0.0)},
        index=bars.index,
    )
    _certify_candidates(candidates, bars, evidence_signer)

    rejected = _run(bars, candidates=candidates)
    evidence = rejected.validation["candidate_evidence"]
    assert evidence["certified"] is False
    assert any("every canonical executed observation" in reason for reason in evidence["reasons"])
    assert rejected.validation["candidate_alignment"]["observations"] == 30


def test_point_in_time_gate_is_signed_and_bound_to_exact_market_snapshot(
    evidence_signer: Ed25519PrivateKey,
) -> None:
    bars = _market()
    _certify_pit(bars, evidence_signer)
    verified = _run(bars, point_in_time=True)
    assert verified.data_catalog.point_in_time is True
    assert verified.execution.diagnostics["point_in_time_verified"] is True

    tampered = bars.copy()
    tampered.attrs = dict(bars.attrs)
    tampered.loc[tampered.index[15], ["Open", "High", "Low", "Close"]] *= 1.01
    rejected = _run(tampered, point_in_time=True)
    assert rejected.data_catalog.point_in_time is False
    assert rejected.execution.diagnostics["point_in_time_verified"] is False
    reasons = rejected.execution.diagnostics["point_in_time_evidence"]["reasons"]
    assert any("exact bars" in reason for reason in reasons)


def test_signed_minimal_manifest_cannot_borrow_pit_semantics_from_unsigned_attrs(
    evidence_signer: Ed25519PrivateKey,
) -> None:
    bars = _market()
    minimal_manifest = {"unrelated_document": "validly signed but not PIT evidence"}
    manifest_hash = stable_hash(minimal_manifest)
    bars.attrs.update({
        "point_in_time_manifest": minimal_manifest,
        "point_in_time_manifest_hash": manifest_hash,
        "point_in_time_signature_base64": _signature(evidence_signer, manifest_hash),
        "schema_version": "institutional_pit_manifest_v1",
        "point_in_time": True,
        "source_snapshot_id": "FORGED-PIT",
        "source_snapshot_hash": data_hash(bars),
        "source": "unit/pit",
        "manifest_timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "knowledge_cutoff": pd.Timestamp.now(tz="UTC").isoformat(),
        "evidence_authority": "not-signed",
        "signing_key_id": "unit-control",
        "signature_algorithm": SIGNATURE_ALGORITHM,
    })

    rejected = _run(bars, point_in_time=True)
    evidence = rejected.execution.diagnostics["point_in_time_evidence"]
    assert evidence["verified"] is False
    assert "schema_version must be institutional_pit_manifest_v1" in evidence["reasons"]
    assert "source_snapshot_id missing" in evidence["reasons"]


def test_stack_run_identity_ignores_only_acquisition_wall_clock() -> None:
    bars = _market()
    bars.attrs["retrieved_at"] = "2026-01-01T09:00:00Z"
    first = _run(bars)

    refetched = bars.copy()
    refetched.attrs = dict(bars.attrs) | {"retrieved_at": "2026-09-28T17:30:00Z"}
    second = _run(refetched)

    assert first.manifest.run_id == second.manifest.run_id
    assert first.manifest.config_hash == second.manifest.config_hash


def test_multivariate_factor_scenario_requires_signed_vintage_contract(
    evidence_signer: Ed25519PrivateKey,
) -> None:
    bars = _market()
    rng = np.random.default_rng(77)
    factors = pd.DataFrame(
        {
            "market": rng.normal(0.0003, 0.01, len(bars)),
            "rates_vintage": rng.normal(0.0, 0.004, len(bars)),
        },
        index=bars.index,
    )
    _certify_factors(factors, bars, evidence_signer)
    signed = _run(bars, factors=factors)
    assert signed.scenarios["factor_evidence"]["certified"] is True
    assert signed.scenarios["availability"]["Multivariate Student-t"]["state"] == "AVAILABLE"

    unsigned = factors.copy()
    unsigned.attrs = dict(factors.attrs)
    unsigned.attrs.pop("evidence_signature_base64")
    blocked = _run(bars, factors=unsigned)
    assert blocked.scenarios["factor_evidence"]["certified"] is False
    assert blocked.scenarios["availability"]["Multivariate Student-t"]["state"] == "UNAVAILABLE"

    delayed = factors.copy()
    delayed.attrs = dict(factors.attrs)
    delayed_ledger = delayed.attrs["factor_vintage_ledger"].copy()
    delayed_ledger.loc[0, "available_at"] = (
        pd.Timestamp(delayed_ledger.loc[0, "observation_at"]) + pd.Timedelta(days=1)
    ).isoformat()
    delayed.attrs["factor_vintage_ledger"] = delayed_ledger
    delayed_manifest = dict(delayed.attrs["evidence_manifest_payload"])
    delayed_manifest["vintage_ledger_hash"] = data_hash(delayed_ledger)
    delayed_hash = stable_hash(delayed_manifest)
    delayed.attrs["evidence_manifest_payload"] = delayed_manifest
    delayed.attrs["evidence_manifest_hash"] = delayed_hash
    delayed.attrs["evidence_signature_base64"] = _signature(evidence_signer, delayed_hash)
    lookahead = _run(bars, factors=delayed)
    assert lookahead.scenarios["factor_evidence"]["certified"] is False
    assert any(
        "decision/bar cutoff" in reason
        for reason in lookahead.scenarios["factor_evidence"]["reasons"]
    )
