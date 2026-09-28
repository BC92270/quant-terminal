"""Governance model cards and reproducible export bundles."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from io import BytesIO
import json
import re
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pandas as pd

from .evidence import verify_trusted_manifest_signature
from .registry import _json_safe, stable_hash
from .types import RunManifest


_SCENARIO_FAMILIES = (
    "Historical bootstrap",
    "Multivariate Student-t",
    "Markov regime switching",
    "EVT empirical tail",
    "Liquidity spiral",
)


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _archive_component(value: str) -> str:
    """Return a stable, traversal-safe archive filename component."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value)).strip("._")
    return cleaned or "artifact"


def _table_bytes(table: pd.DataFrame | pd.Series) -> bytes:
    frame = table.to_frame() if isinstance(table, pd.Series) else table
    return frame.to_csv(index=True, lineterminator="\n").encode("utf-8")


def _zip_write(archive: ZipFile, name: str, content: bytes) -> None:
    # Zip defaults embed wall-clock time, which makes otherwise identical bundles
    # byte-different. A fixed timestamp keeps the evidence package reproducible.
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _canonical_manifest_payload(manifest: RunManifest) -> dict[str, Any]:
    """Return the identity-bearing manifest used inside reproducible bundles.

    ``created_at`` is intentionally absent: it is registry provenance rather than
    part of ``run_id``. Keeping it in the archive would make two exports of the
    same semantic run byte-different.
    """
    payload = asdict(manifest)
    payload.pop("created_at", None)
    if isinstance(payload.get("metadata"), dict):
        payload["metadata"].pop("_bundle_evidence", None)
    payload["non_identity_fields_omitted"] = ["created_at"]
    return payload


def _scenario_coverage(scenarios: Mapping[str, Any]) -> dict[str, Any]:
    raw = scenarios.get("availability", {})
    availability = raw if isinstance(raw, Mapping) else {}
    families: dict[str, dict[str, str]] = {}
    for name in _SCENARIO_FAMILIES:
        item = availability.get(name, {})
        if isinstance(item, Mapping):
            state = str(item.get("state", "UNAVAILABLE")).upper()
            reason = str(item.get("reason", "availability evidence not supplied"))
        else:
            state = "UNAVAILABLE"
            reason = "availability evidence not supplied"
        state = "AVAILABLE" if state in {"AVAILABLE", "PASS"} else "UNAVAILABLE"
        families[name] = {"state": state, "reason": reason}
    raw_policy = availability.get("Institutional scenario policy", {})
    policy_state = (
        "AVAILABLE"
        if isinstance(raw_policy, Mapping)
        and str(raw_policy.get("state", "UNAVAILABLE")).upper() in {"AVAILABLE", "PASS"}
        else "UNAVAILABLE"
    )
    policy = {
        "state": policy_state,
        "reason": (
            str(raw_policy.get("reason", "institutional scenario policy evidence not supplied"))
            if isinstance(raw_policy, Mapping)
            else "institutional scenario policy evidence not supplied"
        ),
    }
    return {
        "families": families,
        "available": [name for name, item in families.items() if item["state"] == "AVAILABLE"],
        "unavailable": [name for name, item in families.items() if item["state"] == "UNAVAILABLE"],
        "institutional_policy": policy,
    }


def _operational_qa_status(
    run_manifest: RunManifest,
    execution: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    evidence = validation.get("operational_qa", execution.get("operational_qa"))
    if isinstance(evidence, Mapping):
        payload = evidence.get("evidence_payload")
        qa_manifest = evidence.get("evidence_manifest")
        digest = str(evidence.get("evidence_manifest_hash", "")).strip().lower()
        payload_hash = stable_hash(payload) if isinstance(payload, Mapping) else ""
        timestamp = pd.to_datetime(
            qa_manifest.get("manifest_timestamp") if isinstance(qa_manifest, Mapping) else None,
            errors="coerce",
            utc=True,
        )
        expires_at = pd.to_datetime(
            qa_manifest.get("expires_at") if isinstance(qa_manifest, Mapping) else None,
            errors="coerce",
            utc=True,
        )
        now = pd.Timestamp.now(tz="UTC")
        artifact_hashes = (
            run_manifest.metadata.get("artifact_hashes", {})
            if isinstance(run_manifest.metadata, Mapping)
            else {}
        )
        expected_bindings = {
            "run_id": run_manifest.run_id,
            "config_hash": run_manifest.config_hash,
            "data_hash": run_manifest.data_hash,
            "code_hash": run_manifest.code_hash,
            "environment_hash": run_manifest.environment_hash,
            "artifact_hashes_hash": stable_hash(artifact_hashes),
        }
        try:
            signed_failures = int(payload.get("failures", 0) or 0) if isinstance(payload, Mapping) else -1
        except (TypeError, ValueError):
            signed_failures = -1
        requirements = {
            "evidence_payload": isinstance(payload, Mapping),
            "evidence_manifest": isinstance(qa_manifest, Mapping),
            "schema_version": isinstance(qa_manifest, Mapping)
            and qa_manifest.get("schema_version") == "institutional_operational_qa_v1",
            "evidence_manifest_hash": bool(re.fullmatch(r"[0-9a-f]{64}", digest)),
            "manifest_binding": isinstance(qa_manifest, Mapping)
            and stable_hash(qa_manifest) == digest,
            "payload_binding": isinstance(qa_manifest, Mapping)
            and str(qa_manifest.get("evidence_payload_hash", "")).lower() == payload_hash,
            "signed_outcome_pass": isinstance(payload, Mapping)
            and str(payload.get("result", "")).upper() == "PASS"
            and signed_failures == 0,
            "evidence_id": isinstance(qa_manifest, Mapping)
            and bool(str(qa_manifest.get("evidence_id", "")).strip()),
            "evidence_authority": isinstance(qa_manifest, Mapping)
            and bool(str(qa_manifest.get("evidence_authority", "")).strip()),
            "manifest_timestamp": not pd.isna(timestamp)
            and timestamp <= now + pd.Timedelta(minutes=5),
            "expires_at": not pd.isna(expires_at)
            and expires_at >= now
            and not pd.isna(timestamp)
            and expires_at > timestamp,
            "run_bindings": isinstance(qa_manifest, Mapping)
            and all(qa_manifest.get(key) == value for key, value in expected_bindings.items()),
        }
        missing = [name for name, available in requirements.items() if not available]
        authenticity = verify_trusted_manifest_signature(
            manifest_hash=digest,
            signing_key_id=(qa_manifest or {}).get("signing_key_id") if isinstance(qa_manifest, Mapping) else "",
            signature_algorithm=(qa_manifest or {}).get("signature_algorithm") if isinstance(qa_manifest, Mapping) else "",
            signature_base64=evidence.get("signature_base64"),
        )
        if not missing and authenticity["verified"]:
            return {
                "state": "PASS",
                "reason": str(
                    payload.get("summary", "Authenticated, run-bound operational QA PASS")
                ),
                "evidence_id": str(qa_manifest.get("evidence_id", "")),
                "expires_at": expires_at.isoformat(),
                "signing_key_id": authenticity["signing_key_id"],
                "public_key_sha256": authenticity["public_key_sha256"],
                "manifest_hash": digest,
            }
        missing.extend(f"authenticity: {item}" for item in authenticity["reasons"])
        return {
            "state": "UNAVAILABLE",
            "reason": "Operational QA claim is not authenticated and run-bound: " + ", ".join(missing),
        }
    return {
        "state": "UNAVAILABLE",
        "reason": "No hash-bound operational QA evidence was supplied to this research bundle",
    }


def build_model_card(
    *,
    manifest: RunManifest,
    data_catalog: dict[str, Any],
    execution: dict[str, Any],
    validation: dict[str, Any],
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    capabilities = data_catalog.get("capabilities", {})
    unavailable = [name for name, item in capabilities.items() if item.get("state") == "UNAVAILABLE"]
    limitations = []
    if unavailable:
        limitations.append("Unavailable data capabilities: " + ", ".join(unavailable))
    if execution.get("short_borrow_available") is False:
        limitations.append("Short borrow/rebate was not fully observable")
    if validation.get("candidate_count", 1) <= 1:
        limitations.append("Multiple-testing gates are unavailable without a genuine multi-candidate trial family")
    if execution.get("cash_settlement_enforced") is False:
        limitations.append("Settlement dates are recorded, but cash-account buying power is not simulated")
    if execution.get("risk_order_replay_available") is False:
        limitations.append(
            "Legacy intrabar/close risk exits are blocked until conditional orders and fills are replayed "
            "inside the canonical event ledger"
        )
    if execution.get("custom_signal_provenance_available") is False:
        limitations.append(
            "Custom Signal promotion is blocked without a valid available_at clock and a clean provenance gate"
        )
    scenario_coverage = _scenario_coverage(scenarios)
    if scenario_coverage["unavailable"]:
        limitations.append(
            "Unavailable scenario families: " + ", ".join(scenario_coverage["unavailable"])
        )
    if scenario_coverage["institutional_policy"]["state"] != "AVAILABLE":
        limitations.append(
            "Institutional scenario policy unavailable: "
            + scenario_coverage["institutional_policy"]["reason"]
        )
    operational_qa = _operational_qa_status(manifest, execution, validation)
    if operational_qa["state"] != "PASS":
        limitations.append("Operational QA is unavailable: " + operational_qa["reason"])
    repository = manifest.metadata.get("repository", {}) if isinstance(manifest.metadata, Mapping) else {}
    if isinstance(repository, Mapping) and repository.get("captured_scope_dirty"):
        if not repository.get("patch_reconstruction_complete", False):
            limitations.append(
                "Repository reconstruction is incomplete because redactions or untracked hashed files are present"
            )
    return {
        "model_id": "Institutional-Backtest-V7",
        "run_id": manifest.run_id,
        "purpose": "Research validation, execution realism, scenario analysis and research-promotion gating",
        "intended_use": "Decision support; not an order-routing or accounting book of record",
        "methodology": {
            "signal_timing": execution.get(
                "target_timing_contract",
                "Signal is executed no earlier than the next eligible bar",
            ),
            "execution": execution.get("model", "UNAVAILABLE"),
            "performance_source": "Net returns reconstructed from the canonical event execution ledger",
            "statistics": ["PSR", "DSR", "CSCV/PBO", "White Reality Check", "Hansen SPA", "Holm", "BH/FDR"],
            "scenarios": scenario_coverage["available"],
            "scenario_coverage": scenario_coverage,
            "reverse_stress": scenarios.get("reverse_stress", {"status": "UNAVAILABLE"}),
        },
        "data_verdict": data_catalog.get("verdict", "UNAVAILABLE"),
        "strategy_coverage": {
            "completeness_claim": False,
            "native_engine_scope": (
                "Single-instrument, timestamped bar strategies with next-eligible-bar execution "
                "and an authoritative event ledger"
            ),
            "native_families": [
                "directional trend and breakout",
                "single-instrument mean reversion",
                "volatility-filtered directional signals",
                "benchmark-relative directional signals",
                "governed manual rule compositions",
                "external causal target/exposure signals",
            ],
            "conditional_families": {
                "short and long-short": "requires timestamped locate, shortable and borrow evidence",
                "event driven": "requires available_at provenance strictly before execution",
                "factor or macro": "requires trusted-signed, vintage-aware point-in-time factor histories",
                "raw-price total return": "requires exact split, dividend and delisting event replay",
            },
            "dedicated_engine_required": [
                "cross-sectional universe and survivorship-aware portfolios",
                "multi-asset portfolio optimisation and portfolio-level constraints",
                "options/futures Greeks, expiry, roll, margin and multi-leg exercise",
                "order-book, queue-position, market-making and sub-bar latency strategies",
                "prime-broker cash, collateral and settlement accounting",
            ],
        },
        "limitations": limitations,
        "approval_policy": {
            "fail_closed": True,
            "data_unavailable_is_not_zero": True,
            "required_gates": ["data", "execution", "statistical validity", "scenario resilience"],
            "operational_qa": operational_qa,
            "unevaluated_production_prerequisites": (
                ["operational QA"] if operational_qa["state"] != "PASS" else []
            ),
            "automatic_production_authorization": False,
        },
    }


def build_governance_bundle(
    *,
    manifest: RunManifest,
    config: dict[str, Any],
    data_catalog: dict[str, Any],
    execution: dict[str, Any],
    validation: dict[str, Any],
    scenarios: dict[str, Any],
    tables: dict[str, pd.DataFrame] | None = None,
    v7_configs: Mapping[str, Any] | None = None,
    candidate_returns: pd.DataFrame | pd.Series | None = None,
    factor_returns: pd.DataFrame | pd.Series | None = None,
    legacy_result: Any = None,
    additional_artifacts: Mapping[str, Any] | None = None,
) -> bytes:
    model_card = build_model_card(
        manifest=manifest,
        data_catalog=data_catalog,
        execution=execution,
        validation=validation,
        scenarios=scenarios,
    )
    payloads: dict[str, Any] = {
        "manifest.json": _canonical_manifest_payload(manifest),
        "config.json": config,
        "data_catalog.json": data_catalog,
        "execution_diagnostics.json": execution,
        "validation.json": validation,
        "scenario_metadata.json": scenarios,
        "model_card.json": model_card,
    }
    if v7_configs is not None:
        payloads["configs/v7.json"] = v7_configs

    files = {name: _json_bytes(payload) for name, payload in payloads.items()}
    repository = manifest.metadata.get("repository", {}) if isinstance(manifest.metadata, Mapping) else {}
    if isinstance(repository, Mapping) and repository.get("state") == "AVAILABLE":
        files["repository/commit.txt"] = (str(repository.get("commit", "UNAVAILABLE")) + "\n").encode("utf-8")
        files["repository/provenance.json"] = _json_bytes(repository)
        files["repository/untracked_inventory.json"] = _json_bytes(
            repository.get("untracked_inventory", {})
        )
        evidence = manifest.metadata.get("_bundle_evidence", {})
        if isinstance(evidence, Mapping):
            dirty_patch = evidence.get("dirty.patch")
            if isinstance(dirty_patch, bytes):
                files["repository/dirty.patch"] = dirty_patch
            dependency_patch = evidence.get("dependencies.patch")
            if isinstance(dependency_patch, bytes):
                files["repository/dependencies.patch"] = dependency_patch
    for name, table in (tables or {}).items():
        files[f"tables/{_archive_component(name)}.csv"] = _table_bytes(table)
    if candidate_returns is not None:
        files["artifacts/candidate_returns.csv"] = _table_bytes(candidate_returns)
    if factor_returns is not None:
        files["artifacts/factor_returns.csv"] = _table_bytes(factor_returns)
    if legacy_result is not None:
        if isinstance(legacy_result, (pd.DataFrame, pd.Series)):
            files["artifacts/legacy_result.csv"] = _table_bytes(legacy_result)
        else:
            files["artifacts/legacy_result.json"] = _json_bytes(legacy_result)
    for name, artifact in sorted((additional_artifacts or {}).items(), key=lambda pair: str(pair[0])):
        safe_name = _archive_component(str(name))
        if isinstance(artifact, (pd.DataFrame, pd.Series)):
            files[f"artifacts/{safe_name}.csv"] = _table_bytes(artifact)
        elif isinstance(artifact, bytes):
            files[f"artifacts/{safe_name}.bin"] = artifact
        elif isinstance(artifact, str):
            files[f"artifacts/{safe_name}.txt"] = artifact.encode("utf-8")
        else:
            files[f"artifacts/{safe_name}.json"] = _json_bytes(artifact)

    readme = (
        "Institutional Backtest V7 reproducibility bundle\n"
        "All N/A states are explicit; unavailable external data is never coerced to zero.\n"
        "created_at is omitted from manifest.json because it is registry provenance, not run identity.\n"
        "Repository code and dependency patches are execution-scope evidence with credential-shaped "
        "values redacted; provenance.json states whether reconstruction remains complete. "
        "Untracked content is represented by SHA-256 only.\n"
        "artifact_manifest.json contains SHA-256 checksums for every evidence file.\n"
        "Validate the code, data licence and approvals before production use.\n"
    ).encode("utf-8")
    files["README.txt"] = readme
    artifact_manifest = {
        "run_id": manifest.run_id,
        "algorithm": "sha256",
        "files": {
            name: {"sha256": sha256(content).hexdigest(), "bytes": len(content)}
            for name, content in sorted(files.items())
        },
    }
    files["artifact_manifest.json"] = _json_bytes(artifact_manifest)

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            _zip_write(archive, name, content)
    return buffer.getvalue()
