"""Facade that composes the authoritative institutional backtest pipeline.

The execution ledger is the single source of truth for performance.  The
legacy vectorised frame is retained only as an input target and a comparison
artifact; it is never used to approve a run.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import re
from typing import Any

import numpy as np
import pandas as pd

from .data_catalog import DataCatalogAssessment, assess_market_data
from .evidence import SIGNATURE_ALGORITHM, verify_trusted_manifest_signature
from .execution import ExecutionModelConfig, simulate_execution
from .registry import build_run_manifest, data_hash, semantic_provenance, stable_hash
from .reporting import build_governance_bundle, build_model_card
from .scenarios import ScenarioConfig, run_institutional_scenario_suite
from .statistics import (
    benjamini_hochberg,
    holm_bonferroni,
    institutional_validation_suite,
    purged_combinatorial_splits,
    sharpe_hac_diagnostics,
)
from .types import AvailabilityState, RunManifest, ValidationState


@dataclass
class InstitutionalRun:
    manifest: RunManifest
    data_catalog: DataCatalogAssessment
    execution: Any
    validation: dict[str, Any]
    scenarios: dict[str, Any]
    gate: dict[str, Any]
    model_card: dict[str, Any]
    bundle: bytes
    authoritative_returns: pd.Series | None = None
    authoritative_source: str = "execution_ledger"


def _legacy_frame(result: dict[str, Any]) -> pd.DataFrame:
    frame = result.get("data")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(result.get("error", "Legacy backtest result has no data"))
    return frame.copy()


def _finite_number(value: Any, default: float = np.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def _state(value: str, *, unavailable_is_fail: bool = False) -> str:
    normalized = str(value or "UNAVAILABLE").upper()
    if normalized in {"AVAILABLE", "PASS"}:
        return "PASS"
    if normalized in {"ESTIMATED", "PARTIAL", "STALE", "WARN"}:
        return "WARN"
    if normalized == "UNAVAILABLE":
        return "FAIL" if unavailable_is_fail else "UNAVAILABLE"
    return "FAIL"


def _authoritative_execution_returns(execution: Any) -> pd.Series:
    daily = getattr(execution, "daily", None)
    if not isinstance(daily, pd.DataFrame) or daily.empty or "return" not in daily:
        raise ValueError("Execution ledger did not produce an authoritative return series")
    returns = pd.to_numeric(daily["return"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    if returns.notna().sum() < 30:
        raise ValueError("DATA REQUIRED: at least 30 executed return observations")
    return returns.dropna().astype(float)


def _validation_value(validation: dict[str, Any], section: str, key: str) -> float:
    block = validation.get(section, {})
    return _finite_number(block.get(key) if isinstance(block, dict) else np.nan)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _sha256_value(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if _SHA256_RE.fullmatch(text) else ""


def _timestamp_available(value: Any) -> bool:
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    if pd.isna(parsed):
        return False
    return bool(parsed <= pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=5))


def _manifest_value(manifest: Mapping[str, Any], *names: str) -> Any:
    """Return a value only from the object covered by the trusted signature.

    Frame attributes transport the manifest, its digest and the detached
    signature.  They are not themselves authenticated and therefore must
    never supply semantic fields used by a gate.
    """
    for name in names:
        if name in manifest:
            return manifest[name]
    return None


def _matrix_evidence_assessment(
    frame: pd.DataFrame | None,
    *,
    kind: str,
    interval_label: str,
    periods_per_year: int,
    market_data_hash: str,
    authoritative_returns: pd.Series | None = None,
) -> dict[str, Any]:
    """Verify a hash-bound semantic contract for uploaded return evidence.

    A UI checkbox is not evidence.  The numeric payload, its canonical manifest,
    units, clock, currency and (for candidate families) every trial identity must
    agree before the matrix may unlock an institutional gate.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {
            "state": "UNAVAILABLE",
            "certified": False,
            "kind": kind,
            "reasons": [f"{kind} matrix not supplied"],
        }

    attrs = dict(getattr(frame, "attrs", {}) or {})
    raw_manifest = attrs.get("evidence_manifest_payload", attrs.get("evidence_manifest"))
    manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
    reasons: list[str] = []
    columns = [str(column) for column in frame.columns]
    payload_hash = data_hash(frame)
    declared_payload_hash = _sha256_value(
        _manifest_value(manifest, "evidence_payload_hash", "payload_sha256", "payload_hash")
    )
    declared_manifest_hash = _sha256_value(
        attrs.get("evidence_manifest_hash", attrs.get("manifest_sha256"))
    )

    if not manifest:
        reasons.append("canonical evidence manifest missing")
    elif not declared_manifest_hash:
        reasons.append("evidence manifest SHA-256 missing or invalid")
    elif stable_hash(manifest) != declared_manifest_hash:
        reasons.append("evidence manifest hash mismatch")
    if not declared_payload_hash:
        reasons.append("numeric payload SHA-256 missing or invalid")
    elif declared_payload_hash != payload_hash:
        reasons.append("numeric payload hash does not match the aligned matrix")

    evidence_signature = attrs.get(
        "evidence_signature_base64",
        attrs.get("signature_base64", attrs.get("manifest_signature_base64")),
    )
    authenticity = verify_trusted_manifest_signature(
        manifest_hash=declared_manifest_hash,
        signing_key_id=_manifest_value(manifest, "signing_key_id"),
        signature_algorithm=_manifest_value(manifest, "signature_algorithm"),
        signature_base64=evidence_signature,
    )
    if not authenticity["verified"]:
        reasons.extend(f"authenticity: {reason}" for reason in authenticity["reasons"])

    declared_kind = str(
        _manifest_value(manifest, "dataset_kind", "evidence_kind") or ""
    ).strip().lower()
    if str(_manifest_value(manifest, "schema_version") or "").strip() != "institutional_returns_v1":
        reasons.append("schema_version must be institutional_returns_v1")
    if declared_kind != kind:
        reasons.append(f"dataset_kind must be {kind}")
    if str(_manifest_value(manifest, "return_convention") or "").strip().lower() != "simple":
        reasons.append("return_convention must be simple")
    if str(_manifest_value(manifest, "return_unit") or "").strip().lower() != "decimal":
        reasons.append("return_unit must be decimal")
    if str(_manifest_value(manifest, "frequency") or "").strip().lower() != str(interval_label).strip().lower():
        reasons.append(f"frequency must match {interval_label}")
    try:
        declared_periods = int(_manifest_value(manifest, "periods_per_year"))
    except (TypeError, ValueError):
        declared_periods = 0
    if declared_periods != int(periods_per_year):
        reasons.append(f"periods_per_year must match {int(periods_per_year)}")
    currency = str(_manifest_value(manifest, "currency") or "").strip().upper()
    if not _ISO_CURRENCY_RE.fullmatch(currency):
        reasons.append("ISO-4217 currency is missing or invalid")
    if not str(_manifest_value(manifest, "evidence_id") or "").strip():
        reasons.append("evidence_id is missing")
    if not str(_manifest_value(manifest, "evidence_authority") or "").strip():
        reasons.append("evidence_authority is missing")
    if not _timestamp_available(_manifest_value(manifest, "manifest_timestamp")):
        reasons.append("manifest_timestamp is missing, invalid or in the future")
    if _manifest_value(manifest, "point_in_time") is not True:
        reasons.append("evidence manifest must declare point_in_time=true")
    source_snapshot_id = str(
        _manifest_value(manifest, "source_snapshot_id") or ""
    ).strip()
    if not source_snapshot_id:
        reasons.append("source_snapshot_id is missing")
    source_snapshot_hash = _sha256_value(
        _manifest_value(manifest, "source_snapshot_hash")
    )
    if source_snapshot_hash != payload_hash:
        reasons.append("source_snapshot_hash must bind the exact uploaded return matrix")
    declared_market_hash = _sha256_value(
        _manifest_value(manifest, "market_data_snapshot_hash")
    )
    if declared_market_hash != _sha256_value(market_data_hash):
        reasons.append("market_data_snapshot_hash does not match the exact bars under test")
    knowledge_cutoff = pd.to_datetime(
        _manifest_value(manifest, "knowledge_cutoff"),
        errors="coerce",
        utc=True,
    )
    if pd.isna(knowledge_cutoff):
        reasons.append("knowledge_cutoff is missing or invalid")
    elif len(frame.index):
        frame_end = pd.to_datetime(frame.index, errors="coerce", utc=True).max()
        if pd.isna(frame_end) or frame_end > knowledge_cutoff:
            reasons.append("return evidence extends beyond knowledge_cutoff")
    revision_policy = str(
        _manifest_value(manifest, "revision_policy") or ""
    ).strip().lower()
    allowed_revision_policies = {
        "as_released",
        "vintage_locked",
        "non_revisable",
        "point_in_time_snapshot",
        "derived_from_pit_snapshot",
    }
    if revision_policy not in allowed_revision_policies:
        reasons.append("revision_policy is not an accepted point-in-time policy")

    finite = frame.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    vintage_ledger_hash = ""
    if kind == "factor_returns":
        vintage_ledger = attrs.get("factor_vintage_ledger")
        declared_vintage_hash = _sha256_value(
            _manifest_value(manifest, "vintage_ledger_hash")
        )
        if not isinstance(vintage_ledger, pd.DataFrame) or vintage_ledger.empty:
            reasons.append("per-observation factor vintage ledger is missing")
        else:
            vintage_ledger_hash = data_hash(vintage_ledger)
            if declared_vintage_hash != vintage_ledger_hash:
                reasons.append("vintage_ledger_hash does not bind the supplied vintage ledger")
            required_ledger_columns = {
                "observation_at", "factor", "available_at", "vintage_id"
            }
            if set(map(str, vintage_ledger.columns)) != required_ledger_columns:
                reasons.append(
                    "factor vintage ledger columns must be exactly observation_at, factor, "
                    "available_at, vintage_id"
                )
            else:
                ledger = vintage_ledger.copy()
                ledger["observation_at"] = pd.to_datetime(
                    ledger["observation_at"], errors="coerce", utc=True
                )
                ledger["available_at"] = pd.to_datetime(
                    ledger["available_at"], errors="coerce", utc=True
                )
                ledger["factor"] = ledger["factor"].astype(str)
                ledger["vintage_id"] = ledger["vintage_id"].fillna("").astype(str).str.strip()
                if ledger[["observation_at", "available_at"]].isna().any(axis=None):
                    reasons.append("factor vintage ledger contains invalid timestamps")
                if bool((ledger["vintage_id"].str.len() == 0).any()):
                    reasons.append("every factor observation requires a non-empty vintage_id")
                if bool((ledger["available_at"] > ledger["observation_at"]).any()):
                    reasons.append("factor value was not available at its decision/bar cutoff")
                ledger_pairs = pd.MultiIndex.from_arrays(
                    [ledger["observation_at"], ledger["factor"]]
                )
                if ledger_pairs.has_duplicates:
                    reasons.append("factor vintage ledger contains duplicate observation/factor pairs")
                expected_observations: list[pd.Timestamp] = []
                expected_factors: list[str] = []
                utc_index = pd.to_datetime(frame.index, errors="coerce", utc=True)
                for column in frame.columns:
                    populated = finite[column].notna().to_numpy()
                    expected_observations.extend(list(utc_index[populated]))
                    expected_factors.extend([str(column)] * int(populated.sum()))
                expected_pairs = pd.MultiIndex.from_arrays(
                    [expected_observations, expected_factors]
                )
                if set(ledger_pairs.tolist()) != set(expected_pairs.tolist()):
                    reasons.append(
                        "factor vintage ledger must cover exactly every non-null factor observation"
                    )

    if bool((finite.abs() > 1.0).any(axis=None)):
        reasons.append("decimal simple returns outside [-1, 1] detected")
    per_column_coverage = finite.notna().mean()
    low_coverage = [
        str(column)
        for column, coverage in per_column_coverage.items()
        if float(coverage) < 0.80
    ]
    if low_coverage:
        reasons.append(
            "every signed trial/factor must retain at least 80% history coverage: "
            + ", ".join(low_coverage)
        )
    complete_rows = int(finite.dropna(how="any").shape[0])
    required_complete_rows = min(len(finite), max(30, int(np.ceil(len(finite) * 0.70))))
    if complete_rows < required_complete_rows:
        reasons.append(
            f"signed matrix has only {complete_rows}/{len(finite)} complete rows; "
            f"{required_complete_rows} required"
        )

    selected_column = ""
    if kind == "candidate_returns":
        if frame.shape[1] < 2:
            reasons.append("at least two genuine candidate trials are required")
        if _manifest_value(manifest, "net_of_costs") is not True:
            reasons.append("candidate returns must be explicitly net_of_costs=true")
        if _manifest_value(manifest, "complete_trial_ledger") is not True:
            reasons.append("complete_trial_ledger=true is required")
        if _manifest_value(manifest, "candidate_family_certified") is not True:
            reasons.append("candidate_family_certified=true is required in the manifest")

        trial_hashes = _manifest_value(manifest, "trial_config_hashes")
        trial_ids = _manifest_value(manifest, "trial_ids")
        if not isinstance(trial_hashes, Mapping) or set(map(str, trial_hashes)) != set(columns):
            reasons.append("trial_config_hashes must cover every candidate column exactly")
        elif any(not _sha256_value(value) for value in trial_hashes.values()):
            reasons.append("every trial config hash must be a valid SHA-256")
        if not isinstance(trial_ids, Mapping) or set(map(str, trial_ids)) != set(columns):
            reasons.append("trial_ids must cover every candidate column exactly")
        elif any(not str(value).strip() for value in trial_ids.values()):
            reasons.append("every candidate must have a non-empty trial_id")
        elif len({str(value).strip() for value in trial_ids.values()}) != len(columns):
            reasons.append("trial_ids must be unique")

        aliases = {str(column).strip().lower(): column for column in frame.columns}
        selected_key = next(
            (
                aliases[name]
                for name in ("__selected_executed__", "selected", "current", "base", "champion")
                if name in aliases
            ),
            "",
        )
        selected_column = str(selected_key) if selected_key != "" else ""
        if selected_key == "":
            reasons.append("selected executed candidate column is missing")
        elif not isinstance(authoritative_returns, pd.Series):
            reasons.append("canonical executed returns are unavailable for selected-trial verification")
        else:
            declared = pd.to_numeric(frame[selected_key], errors="coerce")
            canonical = pd.to_numeric(authoritative_returns, errors="coerce")
            if not frame.index.equals(canonical.index):
                reasons.append("selected trial index must exactly equal the canonical execution index")
            elif len(declared) != len(canonical) or declared.isna().any() or canonical.isna().any():
                reasons.append("selected trial must contain every canonical executed observation without NA")
            elif not np.allclose(
                declared.to_numpy(dtype=float),
                canonical.to_numpy(dtype=float),
                rtol=1e-9,
                atol=1e-12,
            ):
                reasons.append("selected trial does not match canonical net executed returns")

    return {
        "state": "AVAILABLE" if not reasons else "UNAVAILABLE",
        "certified": not reasons,
        "kind": kind,
        "reasons": reasons,
        "payload_hash": payload_hash,
        "declared_payload_hash": declared_payload_hash,
        "manifest_hash": declared_manifest_hash,
        "manifest": manifest,
        "signature_base64": str(evidence_signature or ""),
        "evidence_id": str(_manifest_value(manifest, "evidence_id") or ""),
        "evidence_authority": str(_manifest_value(manifest, "evidence_authority") or ""),
        "authenticity": authenticity,
        "source_snapshot_id": source_snapshot_id,
        "source_snapshot_hash": source_snapshot_hash,
        "market_data_snapshot_hash": declared_market_hash,
        "knowledge_cutoff": None if pd.isna(knowledge_cutoff) else knowledge_cutoff.isoformat(),
        "revision_policy": revision_policy,
        "vintage_ledger_hash": vintage_ledger_hash,
        "selected_column": selected_column,
        "columns": columns,
        "rows": int(len(frame)),
    }


def _point_in_time_evidence_assessment(
    bars: pd.DataFrame,
    *,
    requested: bool,
) -> dict[str, Any]:
    """Cryptographically bind a PIT declaration to the exact market-data frame."""
    if not requested:
        return {
            "state": "UNAVAILABLE",
            "verified": False,
            "requested": False,
            "reasons": ["point-in-time certification not requested"],
        }

    attrs = dict(getattr(bars, "attrs", {}) or {})
    raw_manifest = attrs.get("point_in_time_manifest")
    manifest = dict(raw_manifest) if isinstance(raw_manifest, Mapping) else {}
    reasons: list[str] = []
    manifest_hash = _sha256_value(attrs.get("point_in_time_manifest_hash"))
    snapshot_hash = _sha256_value(
        _manifest_value(manifest, "source_snapshot_hash")
    )
    actual_snapshot_hash = data_hash(bars)
    snapshot_id = str(_manifest_value(manifest, "source_snapshot_id") or "").strip()

    if not manifest:
        reasons.append("point-in-time manifest missing")
    elif not manifest_hash:
        reasons.append("point-in-time manifest SHA-256 missing or invalid")
    elif stable_hash(manifest) != manifest_hash:
        reasons.append("point-in-time manifest hash mismatch")
    pit_signature = attrs.get(
        "point_in_time_signature_base64",
        attrs.get("signature_base64", attrs.get("manifest_signature_base64")),
    )
    authenticity = verify_trusted_manifest_signature(
        manifest_hash=manifest_hash,
        signing_key_id=_manifest_value(manifest, "signing_key_id"),
        signature_algorithm=_manifest_value(manifest, "signature_algorithm"),
        signature_base64=pit_signature,
    )
    if not authenticity["verified"]:
        reasons.extend(f"authenticity: {reason}" for reason in authenticity["reasons"])
    if str(_manifest_value(manifest, "schema_version") or "").strip() != "institutional_pit_manifest_v1":
        reasons.append("schema_version must be institutional_pit_manifest_v1")
    if not snapshot_id:
        reasons.append("source_snapshot_id missing")
    if not snapshot_hash:
        reasons.append("source_snapshot_hash missing or invalid")
    elif snapshot_hash != actual_snapshot_hash:
        reasons.append("source snapshot hash does not match the exact bars under test")
    if _manifest_value(manifest, "point_in_time") is not True:
        reasons.append("manifest does not declare point_in_time=true")
    if not _timestamp_available(_manifest_value(manifest, "manifest_timestamp")):
        reasons.append("point-in-time manifest timestamp missing, invalid or in the future")
    if not str(_manifest_value(manifest, "evidence_authority") or "").strip():
        reasons.append("point-in-time evidence_authority missing")
    knowledge_cutoff = pd.to_datetime(
        _manifest_value(manifest, "knowledge_cutoff"), errors="coerce", utc=True
    )
    if pd.isna(knowledge_cutoff):
        reasons.append("point-in-time knowledge_cutoff missing or invalid")
    elif len(bars.index):
        data_end = pd.to_datetime(bars.index, errors="coerce", utc=True).max()
        if pd.isna(data_end) or data_end > knowledge_cutoff:
            reasons.append("market data extends beyond point-in-time knowledge_cutoff")
    manifest_source = str(_manifest_value(manifest, "source") or "").strip()
    active_source = str(attrs.get("data_source", "")).strip()
    if not manifest_source:
        reasons.append("point-in-time source is missing")
    elif active_source and manifest_source != active_source:
        reasons.append("point-in-time source does not match active market-data adapter")

    return {
        "state": "AVAILABLE" if not reasons else "UNAVAILABLE",
        "verified": not reasons,
        "requested": True,
        "reasons": reasons,
        "manifest_hash": manifest_hash,
        "manifest": manifest,
        "signature_base64": str(pit_signature or ""),
        "source_snapshot_id": snapshot_id,
        "source_snapshot_hash": snapshot_hash,
        "actual_snapshot_hash": actual_snapshot_hash,
        "knowledge_cutoff": None if pd.isna(knowledge_cutoff) else knowledge_cutoff.isoformat(),
        "source": manifest_source,
        "authenticity": authenticity,
    }


def _gate(
    catalog: DataCatalogAssessment,
    execution: Any,
    validation: dict[str, Any],
    scenarios: dict[str, Any],
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    diagnostics = execution.diagnostics if isinstance(execution.diagnostics, dict) else {}
    pit_evidence = diagnostics.get("point_in_time_evidence", {})
    if not isinstance(pit_evidence, Mapping):
        pit_evidence = {}
    pit_reasons = (
        list(pit_evidence.get("reasons", []))
        if isinstance(pit_evidence.get("reasons", []), (list, tuple))
        else []
    )
    checks.append({
        "gate": "Point-in-time data contract",
        "state": "PASS" if bool(pit_evidence.get("verified", False)) else "UNAVAILABLE",
        "detail": (
            "Trusted Ed25519-signed point-in-time source contract verified"
            if bool(pit_evidence.get("verified", False))
            else "DATA REQUIRED: " + "; ".join(pit_reasons[:3])
            if pit_reasons
            else "DATA REQUIRED: hash-bound point-in-time manifest"
        ),
    })
    checks.append({
        "gate": "Market-data integrity & capabilities",
        "state": _state(catalog.verdict.value),
        "detail": "; ".join(catalog.issues[:5]) or "All strategy-required capabilities passed",
    })

    execution_state = _state(execution.status.value)
    fill_ratio = _finite_number(diagnostics.get("fill_ratio"), 1.0 if execution.fills else 0.0)
    causal = bool(diagnostics.get("causal_inputs_only", False))
    execution_detail = (
        f"{execution.reason}; fill ratio {fill_ratio:.1%}; "
        f"causal inputs {'certified' if causal else 'not certified'}"
    )
    if not causal:
        execution_state = "FAIL"
    elif fill_ratio < 0.90:
        execution_state = "FAIL"
    elif fill_ratio < 0.98 and execution_state == "PASS":
        execution_state = "WARN"
    checks.append({"gate": "Canonical event ledger", "state": execution_state, "detail": execution_detail})

    # The legacy OHLC risk layer can decide a stop/take/trailing/max-holding
    # exit from the current bar and then zero the target on that same bar.  A
    # bar-open ledger must not interpret that post-observation target as if it
    # had been known at the open.  Until those resting/conditional orders are
    # replayed as timestamped ledger events, the run is explicitly unavailable
    # for institutional approval (the base ledger remains visible for audit).
    risk_replay_available = bool(diagnostics.get("risk_order_replay_available", True))
    risk_event_count = int(diagnostics.get("legacy_risk_event_count", 0) or 0)
    checks.append({
        "gate": "Risk-order event replay",
        "state": "PASS" if risk_replay_available else "UNAVAILABLE",
        "detail": (
            "No active legacy intrabar/close risk overlay"
            if risk_replay_available
            else (
                "DATA REQUIRED: replay resting stop/take/trailing/max-holding orders and their fills "
                f"inside the canonical ledger ({risk_event_count} observed legacy events)"
            )
        ),
    })

    signal_provenance_available = bool(
        diagnostics.get("custom_signal_provenance_available", True)
    )
    signal_decision = str(
        diagnostics.get("custom_signal_safety_decision", "NOT APPLICABLE")
    )
    checks.append({
        "gate": "Custom-signal availability provenance",
        "state": "PASS" if signal_provenance_available else "UNAVAILABLE",
        "detail": (
            "Not applicable or safety gate PASS with a valid available_at clock"
            if signal_provenance_available
            else (
                "DATA REQUIRED: Custom Signal needs valid available_at timestamps, post-availability "
                f"execution and a clean safety gate (current: {signal_decision})"
            )
        ),
    })

    daily = getattr(execution, "daily", None)
    min_nav = np.nan
    max_drawdown = np.nan
    if isinstance(daily, pd.DataFrame) and not daily.empty:
        min_nav = _finite_number(pd.to_numeric(daily.get("nav"), errors="coerce").min())
        max_drawdown = _finite_number(pd.to_numeric(daily.get("drawdown"), errors="coerce").min())
    economic_state = "PASS"
    if not np.isfinite(min_nav) or min_nav <= 0:
        economic_state = "FAIL"
    elif np.isfinite(max_drawdown) and max_drawdown <= -0.50:
        economic_state = "FAIL"
    elif np.isfinite(max_drawdown) and max_drawdown <= -0.30:
        economic_state = "WARN"
    checks.append({
        "gate": "Executed capital integrity",
        "state": economic_state,
        "detail": (
            f"Minimum NAV {min_nav:,.2f}; max drawdown {max_drawdown:.1%}"
            if np.isfinite(min_nav) and np.isfinite(max_drawdown)
            else "Execution NAV unavailable"
        ),
    })

    psr = _finite_number(validation.get("psr"))
    checks.append({
        "gate": "Probabilistic Sharpe",
        "state": "PASS" if psr >= 0.95 else ("WARN" if psr >= 0.80 else ("FAIL" if np.isfinite(psr) else "UNAVAILABLE")),
        "detail": f"PSR {psr:.1%}" if np.isfinite(psr) else "DATA REQUIRED",
    })

    candidate_count = int(validation.get("candidate_count", 0) or 0)
    candidate_certified = bool(validation.get("candidate_family_certified", False))
    candidate_evidence = validation.get("candidate_evidence", {})
    candidate_reasons = (
        list(candidate_evidence.get("reasons", []))
        if isinstance(candidate_evidence, Mapping)
        else []
    )
    checks.append({
        "gate": "Candidate trial provenance",
        "state": "PASS" if candidate_count >= 2 and candidate_certified else "UNAVAILABLE",
        "detail": (
            f"Trusted-signed complete net-executed trial ledger certified ({candidate_count} candidates)"
            if candidate_count >= 2 and candidate_certified
            else (
                "DATA REQUIRED: " + "; ".join(candidate_reasons[:4])
                if candidate_reasons
                else "DATA REQUIRED: certified complete family including rejected/abandoned trials"
            )
        ),
    })
    dsr = _validation_value(validation, "dsr", "deflated_sharpe_probability")
    checks.append({
        "gate": "Deflated Sharpe",
        "state": (
            "UNAVAILABLE" if candidate_count < 2 or not candidate_certified or not np.isfinite(dsr)
            else ("PASS" if dsr >= 0.95 else ("WARN" if dsr >= 0.80 else "FAIL"))
        ),
        "detail": (
            f"DSR probability {dsr:.1%} across {candidate_count} candidates"
            if candidate_count >= 2 and candidate_certified and np.isfinite(dsr)
            else "DATA REQUIRED: complete candidate family"
        ),
    })
    pbo = _validation_value(validation, "pbo", "pbo")
    checks.append({
        "gate": "Selection overfit",
        "state": (
            "UNAVAILABLE" if not candidate_certified
            else "PASS" if np.isfinite(pbo) and pbo <= 0.20
            else "WARN" if np.isfinite(pbo) and pbo <= 0.50
            else "FAIL" if np.isfinite(pbo)
            else "UNAVAILABLE"
        ),
        "detail": f"PBO {pbo:.1%}" if candidate_certified and np.isfinite(pbo) else "DATA REQUIRED: certified candidate family",
    })

    white_p = _validation_value(validation, "white_reality_check", "p_value")
    spa_p = _validation_value(validation, "hansen_spa", "p_value")
    if not candidate_certified or not np.isfinite(white_p) or not np.isfinite(spa_p) or candidate_count < 2:
        multiple_state = "UNAVAILABLE"
    elif white_p <= 0.05 and spa_p <= 0.05:
        multiple_state = "PASS"
    elif white_p <= 0.10 and spa_p <= 0.10:
        multiple_state = "WARN"
    else:
        multiple_state = "FAIL"
    checks.append({
        "gate": "Data-snooping controls",
        "state": multiple_state,
        "detail": (
            f"White p={white_p:.3f}; SPA p={spa_p:.3f}"
            if np.isfinite(white_p) and np.isfinite(spa_p)
            else "DATA REQUIRED: aligned candidate family"
        ),
    })

    cpcv = validation.get("cpcv", {})
    cpcv_available = bool(cpcv.get("available", False)) if isinstance(cpcv, dict) else False
    cpcv_positive = _finite_number(cpcv.get("positive_oos_share") if isinstance(cpcv, dict) else np.nan)
    cpcv_median = _finite_number(cpcv.get("median_oos_sharpe") if isinstance(cpcv, dict) else np.nan)
    if not candidate_certified or not cpcv_available:
        cpcv_state = "UNAVAILABLE"
    elif cpcv_positive >= 0.60 and cpcv_median > 0:
        cpcv_state = "PASS"
    elif cpcv_positive >= 0.50:
        cpcv_state = "WARN"
    else:
        cpcv_state = "FAIL"
    checks.append({
        "gate": "Purged CPCV out-of-sample",
        "state": cpcv_state,
        "detail": (
            f"Positive OOS paths {cpcv_positive:.1%}; median OOS Sharpe {cpcv_median:.2f}"
            if candidate_certified and cpcv_available and np.isfinite(cpcv_positive) and np.isfinite(cpcv_median)
            else "DATA REQUIRED: executed purged paths"
        ),
    })

    summary = scenarios.get("summary", pd.DataFrame())
    scenario_availability = scenarios.get("availability", {})
    unavailable_scenarios = [
        str(name)
        for name, item in scenario_availability.items()
        if not isinstance(item, dict) or str(item.get("state")) != "AVAILABLE"
    ] if isinstance(scenario_availability, dict) else ["Scenario availability contract"]
    worst_es = float(summary["expected_shortfall"].min()) if isinstance(summary, pd.DataFrame) and not summary.empty else np.nan
    worst_breach = float(summary["breach_probability"].max()) if isinstance(summary, pd.DataFrame) and not summary.empty and "breach_probability" in summary else np.nan
    if unavailable_scenarios:
        scenario_state = "UNAVAILABLE"
    elif np.isfinite(worst_es) and np.isfinite(worst_breach):
        scenario_state = "PASS" if worst_es > -0.25 and worst_breach <= 0.20 else ("WARN" if worst_es > -0.45 and worst_breach <= 0.40 else "FAIL")
    else:
        scenario_state = "UNAVAILABLE"
    checks.append({
        "gate": "Scenario resilience",
        "state": scenario_state,
        "detail": (
            "DATA REQUIRED: " + ", ".join(unavailable_scenarios)
            if unavailable_scenarios
            else f"Worst terminal ES {worst_es:.1%}; breach probability {worst_breach:.1%}"
            if np.isfinite(worst_es) and np.isfinite(worst_breach)
            else "DATA REQUIRED"
        ),
    })

    states = [row["state"] for row in checks]
    if "FAIL" in states:
        decision = "REJECT / REDESIGN"
    elif "UNAVAILABLE" in states:
        decision = "HOLD — DATA REQUIRED"
    elif "WARN" in states or "PARTIAL" in states:
        decision = "CONDITIONAL REVIEW"
    else:
        decision = "RESEARCH APPROVED"
    return {
        "decision": decision,
        "checks": pd.DataFrame(checks),
        "fail_closed": True,
        "production_authorized": False,
        "authoritative_source": "execution_ledger",
        "blocking_gates": [row["gate"] for row in checks if row["state"] in {"FAIL", "UNAVAILABLE"}],
    }


def run_institutional_stack(
    *,
    bars: pd.DataFrame,
    legacy_result: dict[str, Any],
    strategy: str,
    symbol: str,
    config_payload: dict[str, Any],
    execution_config: ExecutionModelConfig | None = None,
    scenario_config: ScenarioConfig | None = None,
    candidate_returns: pd.DataFrame | None = None,
    factor_returns: pd.DataFrame | None = None,
    seed: int = 41,
    point_in_time: bool = False,
    source: str = "Active market-data adapter",
) -> InstitutionalRun:
    legacy = _legacy_frame(legacy_result)
    if "exposure" not in legacy:
        raise ValueError("Legacy result is missing the target exposure contract")
    target = pd.to_numeric(legacy["exposure"], errors="coerce").reindex(bars.index).ffill().fillna(0.0)
    execution_config = execution_config or ExecutionModelConfig(
        initial_capital=float(config_payload.get("capital", 1_000_000.0))
    )
    scenario_config = scenario_config or ScenarioConfig(seed=seed)
    periods_per_year = int(config_payload.get("periods_per_year", 252) or 252)
    interval_label = str(config_payload.get("interval_label", "1d") or "1d")
    price_basis = str(bars.attrs.get("price_basis", config_payload.get("price_basis", "raw"))).lower()
    if price_basis in {"adjusted", "adjusted_total_return", "total_return"}:
        execution_price_basis = "adjusted_total_return"
        corporate_action_policy = "ignore"
    elif price_basis == "total_return_adjusted":
        execution_price_basis = "total_return_adjusted"
        corporate_action_policy = "ignore"
    else:
        execution_price_basis = "raw"
        corporate_action_policy = execution_config.corporate_action_policy

    # ``legacy['exposure']`` is the already-lagged, executable target emitted by
    # the reference engine.  Re-lagging it here would silently move every order
    # one additional bar into the future.  The contract is made explicit in the
    # ledger configuration and recorded in the manifest.
    execution_config = replace(
        execution_config,
        target_timing="pre_lagged_target",
        signal_latency_bars=0,
        periods_per_year=float(periods_per_year),
        bar_frequency=interval_label,
        trading_calendar="CALENDAR_DAY" if "24x7" in interval_label else execution_config.trading_calendar,
        price_basis=execution_price_basis,
        corporate_action_policy=corporate_action_policy,
        short_sale_policy="require" if bool((target < 0).any()) else execution_config.short_sale_policy,
        require_locate=True if bool((target < 0).any()) else execution_config.require_locate,
    )
    required_capabilities = ["bar_execution", "point_in_time"]
    if execution_config.model != "constant":
        required_capabilities.extend(["volume_impact", "capacity"])
    if price_basis not in {"adjusted", "adjusted_total_return", "total_return", "total_return_adjusted"}:
        required_capabilities.append("corporate_actions")
    if bool((target < 0).any()):
        required_capabilities.append("short_financing")
    strategy_lower = str(strategy).lower()
    if any(token in strategy_lower for token in ("cross-sectional", "universe", "market neutral", "factor")):
        required_capabilities.append("survivorship_control")

    pit_evidence = _point_in_time_evidence_assessment(bars, requested=bool(point_in_time))
    verified_point_in_time = bool(pit_evidence.get("verified", False))
    catalog = assess_market_data(
        bars,
        symbol=symbol,
        source=source,
        point_in_time=verified_point_in_time,
        required_capabilities=tuple(dict.fromkeys(required_capabilities)),
    )
    execution = simulate_execution(
        bars,
        target,
        symbol=symbol,
        config=execution_config,
    )
    legacy_risk_events = legacy_result.get("risk_events")
    legacy_risk_event_count = (
        int(len(legacy_risk_events))
        if isinstance(legacy_risk_events, pd.DataFrame)
        else 0
    )
    legacy_risk_markers = 0
    if "risk_exit_reason" in legacy:
        markers = legacy["risk_exit_reason"].fillna("").astype(str).str.strip()
        legacy_risk_markers = int(markers.ne("").sum())
    legacy_metrics = legacy_result.get("metrics")
    metrics_risk_enabled = bool(
        legacy_metrics.get("Risk Layer Enabled", False)
        if isinstance(legacy_metrics, dict)
        else False
    )
    risk_layer_enabled = bool(
        config_payload.get("risk_layer_enabled", False)
        or metrics_risk_enabled
        or legacy_risk_event_count
        or legacy_risk_markers
    )
    execution.diagnostics.update({
        "point_in_time_requested": bool(point_in_time),
        "point_in_time_verified": verified_point_in_time,
        "point_in_time_evidence": pit_evidence,
        "legacy_risk_layer_enabled": risk_layer_enabled,
        "legacy_risk_event_count": legacy_risk_event_count,
        "legacy_risk_exit_markers": legacy_risk_markers,
        "risk_order_replay_available": not risk_layer_enabled,
        "risk_order_replay_reason": (
            "No active legacy intrabar/close risk overlay"
            if not risk_layer_enabled
            else (
                "Legacy risk exits are not yet represented as resting conditional orders and "
                "timestamped fills in the canonical ledger"
            )
        ),
    })
    is_custom_signal = str(strategy).strip().lower() == "custom signal import"
    custom_signal_safety_decision = str(
        config_payload.get("custom_signal_safety_decision", "UNAVAILABLE")
    ).upper()
    custom_signal_provenance_available = (
        not is_custom_signal or custom_signal_safety_decision == "PASS"
    )
    execution.diagnostics.update({
        "custom_signal_safety_decision": custom_signal_safety_decision,
        "custom_signal_provenance_available": custom_signal_provenance_available,
    })
    returns = _authoritative_execution_returns(execution)
    supplied_candidates = (
        candidate_returns.copy()
        if isinstance(candidate_returns, pd.DataFrame)
        else None
    )
    candidate_evidence = _matrix_evidence_assessment(
        supplied_candidates,
        kind="candidate_returns",
        interval_label=interval_label,
        periods_per_year=periods_per_year,
        market_data_hash=data_hash(bars),
        authoritative_returns=returns,
    )
    factor_evidence = _matrix_evidence_assessment(
        factor_returns if isinstance(factor_returns, pd.DataFrame) else None,
        kind="factor_returns",
        interval_label=interval_label,
        periods_per_year=periods_per_year,
        market_data_hash=data_hash(bars),
    )
    # Preserve the exact signed payload for every downstream statistic.  No
    # reindexing, imputation, selected-series insertion or overwrite is allowed
    # after the payload hash and signature have been verified.
    candidates = supplied_candidates.copy() if supplied_candidates is not None else None
    validation = institutional_validation_suite(
        returns,
        candidates=candidates,
        num_trials=max(1, 1 if candidates is None else candidates.shape[1]),
        bootstrap_samples=350,
        seed=seed,
        periods=periods_per_year,
    )
    validation["candidate_names"] = list(candidates.columns) if candidates is not None else []
    validation["candidate_evidence"] = candidate_evidence
    validation["candidate_family_certified"] = bool(candidate_evidence.get("certified", False))
    # Explicit family-wise and false-discovery controls for candidate p-values.
    candidate_p = []
    if candidates is not None and not candidates.empty:
        for column in candidates:
            series = pd.to_numeric(candidates[column], errors="coerce").dropna()
            if len(series) < 3 or series.std(ddof=1) <= 0:
                candidate_p.append(np.nan)
            else:
                # Candidate family controls use the same conservative effective
                # sample size as PSR/DSR.  An iid t-stat here would reopen the
                # serial-correlation confidence inflation closed elsewhere.
                hac = sharpe_hac_diagnostics(series)
                effective_n = _finite_number(hac.get("effective_sample_size"))
                if not np.isfinite(effective_n) or effective_n < 2:
                    candidate_p.append(np.nan)
                    continue
                z = series.mean() / (series.std(ddof=1) / np.sqrt(effective_n))
                candidate_p.append(float(2.0 * (1.0 - 0.5 * (1.0 + __import__("math").erf(abs(z) / np.sqrt(2.0))))))
    validation["holm"] = holm_bonferroni(candidate_p).to_dict(orient="records") if candidate_p else []
    validation["benjamini_hochberg"] = benjamini_hochberg(candidate_p).to_dict(orient="records") if candidate_p else []
    validation.setdefault("cpcv_splits", len(purged_combinatorial_splits(len(returns))) if len(returns) >= 30 else 0)
    scenario_factor_returns = (
        factor_returns
        if isinstance(factor_returns, pd.DataFrame) and bool(factor_evidence.get("certified", False))
        else None
    )
    scenarios = run_institutional_scenario_suite(
        returns,
        factor_returns=scenario_factor_returns,
        config=scenario_config,
    )
    scenarios["factor_evidence"] = factor_evidence
    if not execution.diagnostics.get("risk_order_replay_available", True):
        authoritative_source = "UNAVAILABLE — risk-order replay required"
    elif not execution.diagnostics.get("custom_signal_provenance_available", True):
        authoritative_source = "UNAVAILABLE — custom-signal provenance required"
    else:
        authoritative_source = "execution_ledger"
    # Acquisition wall clocks such as retrieved_at are descriptive operations,
    # not semantic research inputs.  Only the stable provenance contract enters
    # config/artifact identity; signed snapshot hashes retain the exact dataset.
    market_data_attrs = semantic_provenance(
        dict(getattr(bars, "attrs", {}) or {})
    )
    full_config = config_payload | {
        "execution": asdict(execution_config),
        "scenario": asdict(scenario_config),
        "point_in_time_requested": bool(point_in_time),
        "point_in_time": verified_point_in_time,
        "point_in_time_evidence": pit_evidence,
        "periods_per_year": periods_per_year,
        "interval_label": interval_label,
        "data_source": str(source),
        "market_data_attrs": market_data_attrs,
        "candidate_family_certified": bool(candidate_evidence.get("certified", False)),
        "candidate_evidence": candidate_evidence,
        "factor_evidence_certified": bool(factor_evidence.get("certified", False)),
        "factor_evidence": factor_evidence,
        "candidate_alignment": (
            dict(getattr(candidate_returns, "attrs", {}).get("alignment", {}))
            if isinstance(candidate_returns, pd.DataFrame)
            else {"state": "UNAVAILABLE", "reason": "candidate family not supplied"}
        ),
        "factor_alignment": (
            dict(getattr(factor_returns, "attrs", {}).get("alignment", {}))
            if isinstance(factor_returns, pd.DataFrame)
            else {"state": "UNAVAILABLE", "reason": "factor history not supplied"}
        ),
    }
    manifest = build_run_manifest(
        config=full_config,
        market_data=bars,
        strategy=strategy,
        symbol=symbol,
        seed=seed,
        tags=("institutional-v7", "research"),
        metadata={
            "legacy_rows": len(legacy),
            "candidate_count": validation["candidate_count"],
            "authoritative_source": authoritative_source,
            "required_capabilities": required_capabilities,
            "price_basis": price_basis,
            "data_source": str(source),
            "catalog_fingerprint": catalog.fingerprint,
            "catalog_verdict": catalog.verdict.value,
            "catalog_issues": list(catalog.issues),
            "point_in_time_evidence": pit_evidence,
            "candidate_evidence": candidate_evidence,
            "factor_evidence": factor_evidence,
        },
        candidate_returns=supplied_candidates,
        factor_returns=factor_returns,
        legacy_result=legacy,
        additional_artifacts={
            "market_data_attrs": market_data_attrs,
            "point_in_time_evidence": pit_evidence,
            "candidate_evidence": candidate_evidence,
            "factor_evidence": factor_evidence,
            # These legacy inputs change the risk-overlay gate and are exported
            # below; they must therefore participate in the immutable run ID.
            "legacy_risk_events": (
                legacy_risk_events.copy()
                if isinstance(legacy_risk_events, pd.DataFrame)
                else legacy_risk_events
            ),
            "legacy_metrics": legacy_metrics if isinstance(legacy_metrics, Mapping) else {},
        },
    )
    gate = _gate(catalog, execution, validation, scenarios)
    gate["authoritative_source"] = authoritative_source
    scenario_metadata = {
        "summary": scenarios["summary"].to_dict(orient="index"),
        "availability": scenarios.get("availability", {}),
        "reverse_stress": scenarios["reverse_stress"],
        "evt": scenarios["evt"],
        "regime_mix": scenarios["regime_mix"],
        "markov": scenarios.get("markov", {}),
        "multivariate": scenarios.get("multivariate", {}),
        "factor_model": scenarios.get("factor_model", {}),
        "historical_bootstrap": scenarios.get("historical_bootstrap", {}),
        "factor_evidence": factor_evidence,
        "seed": scenarios["seed"],
    }
    model_card = build_model_card(
        manifest=manifest,
        data_catalog=catalog.to_dict(),
        execution=execution.diagnostics,
        validation=validation,
        scenarios=scenario_metadata,
    )
    tables = {
        "market_data_input": bars.copy(),
        "legacy_backtest": legacy,
        "authoritative_returns": returns.to_frame("executed_return"),
        "scenario_summary": scenarios["summary"],
        "gate_checks": gate["checks"],
    }
    if supplied_candidates is not None and not supplied_candidates.empty:
        tables["candidate_returns_supplied"] = supplied_candidates
    if candidates is not None and not candidates.empty:
        tables["candidate_returns_analysis"] = candidates
    if execution.daily is not None:
        tables["execution_daily"] = execution.daily
    if execution.fills:
        tables["fills"] = pd.DataFrame(execution.records()["fills"])
    if execution.orders:
        tables["orders"] = pd.DataFrame(execution.records()["orders"])
    if isinstance(legacy_risk_events, pd.DataFrame) and not legacy_risk_events.empty:
        tables["legacy_risk_events"] = legacy_risk_events.copy()
    bundle = build_governance_bundle(
        manifest=manifest,
        config=full_config,
        data_catalog=catalog.to_dict(),
        execution=execution.diagnostics | {"status": execution.status.value, "reason": execution.reason},
        validation=validation,
        scenarios=scenario_metadata,
        tables=tables,
        v7_configs={
            "execution": asdict(execution_config),
            "scenario": asdict(scenario_config),
            "data": {
                "point_in_time_requested": bool(point_in_time),
                "point_in_time": verified_point_in_time,
                "point_in_time_evidence": pit_evidence,
                "price_basis": price_basis,
                "periods_per_year": periods_per_year,
                "interval_label": interval_label,
                "source": str(source),
                "market_data_attrs": market_data_attrs,
                "required_capabilities": required_capabilities,
            },
        },
        candidate_returns=supplied_candidates,
        factor_returns=factor_returns,
        legacy_result=legacy,
        additional_artifacts={
            "market_data_attrs": market_data_attrs,
            "data_catalog_fingerprint": {
                "source": str(source),
                "fingerprint": catalog.fingerprint,
                "verdict": catalog.verdict.value,
                "issues": list(catalog.issues),
            },
            "point_in_time_evidence": pit_evidence,
            "candidate_evidence": candidate_evidence,
            "factor_evidence": factor_evidence,
            "legacy_risk_events": (
                legacy_risk_events.copy()
                if isinstance(legacy_risk_events, pd.DataFrame)
                else legacy_risk_events
            ),
            "legacy_metrics": legacy_metrics if isinstance(legacy_metrics, Mapping) else {},
        },
    )
    return InstitutionalRun(
        manifest,
        catalog,
        execution,
        validation,
        scenarios,
        gate,
        model_card,
        bundle,
        authoritative_returns=returns,
        authoritative_source=authoritative_source,
    )
