"""Streamlit cockpit for the institutional V7 layer."""
from __future__ import annotations

from dataclasses import asdict
from io import BytesIO
import json
from collections.abc import Mapping
import re
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .engine import InstitutionalRun, run_institutional_stack
from .evidence import SIGNATURE_ALGORITHM
from .execution import ExecutionModelConfig
from .registry import ExperimentRegistry, _json_safe, data_hash, stable_hash
from .scenarios import ScenarioConfig


_EVIDENCE_SCHEMA = "institutional_returns_v1"
_PIT_SCHEMA = "institutional_pit_manifest_v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_EVIDENCE_METADATA = (
    "meta_schema_version",
    "meta_dataset_kind",
    "meta_frequency",
    "meta_periods_per_year",
    "meta_return_convention",
    "meta_return_unit",
    "meta_currency",
    "meta_net_of_costs",
    "meta_evidence_id",
    "meta_evidence_authority",
    "meta_manifest_timestamp",
    "meta_payload_sha256",
    "meta_point_in_time",
    "meta_source_snapshot_id",
    "meta_source_snapshot_sha256",
    "meta_market_data_snapshot_sha256",
    "meta_knowledge_cutoff",
    "meta_revision_policy",
    "meta_vintage_ledger_sha256",
    "meta_trial_ids_json",
    "meta_trial_config_sha256_json",
    "meta_complete_trial_ledger",
    "meta_signing_key_id",
    "meta_signature_algorithm",
    "meta_signature_base64",
    "meta_manifest_sha256",
)


def _config_payload(cfg: Any) -> dict[str, Any]:
    values = vars(cfg) if hasattr(cfg, "__dict__") else dict(cfg or {})
    return {
        str(key): _json_safe(value)
        for key, value in values.items()
        if not isinstance(value, (pd.DataFrame, pd.Series))
    }


def _metric(value: Any, *, percent: bool = False, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "DATA REQUIRED"
    if not np.isfinite(number):
        return "DATA REQUIRED"
    return f"{number:.{decimals}%}" if percent else f"{number:.{decimals}f}"


def _normalised_timestamp_index(values: Any, *, label: str) -> pd.DatetimeIndex:
    parsed = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce", utc=True))
    if parsed.isna().any():
        raise ValueError(f"{label}: one or more timestamps are invalid")
    return parsed.tz_convert(None)


def _upload_bytes(upload: Any) -> bytes:
    """Snapshot an upload so lazy Streamlit tabs cannot discard the evidence."""
    if isinstance(upload, Mapping) and isinstance(upload.get("bytes"), (bytes, bytearray)):
        return bytes(upload["bytes"])
    if isinstance(upload, (bytes, bytearray)):
        return bytes(upload)
    if not hasattr(upload, "read"):
        raise ValueError("uploaded evidence is not a readable file")
    if hasattr(upload, "seek"):
        upload.seek(0)
    try:
        payload = upload.read()
    finally:
        if hasattr(upload, "seek"):
            upload.seek(0)
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError("uploaded evidence did not produce bytes")
    return bytes(payload)


def _read_csv_upload(upload: Any) -> pd.DataFrame:
    return pd.read_csv(BytesIO(_upload_bytes(upload)))


def _metadata_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return ""
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value).strip()


def _constant_metadata(
    raw: pd.DataFrame,
    columns: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for name in _EVIDENCE_METADATA:
        column = columns.get(name)
        if column is None:
            raise ValueError(f"{label}: required metadata column '{name}' is missing")
        values = [_metadata_text(value) for value in raw[column].tolist()]
        nonempty = {value for value in values if value}
        if len(nonempty) != 1 or any(not value for value in values):
            raise ValueError(f"{label}: metadata '{name}' must be non-empty and constant on every row")
        metadata[name] = nonempty.pop()
    return metadata


def _strict_bool(value: Any, *, label: str) -> bool:
    normalised = _metadata_text(value).lower()
    if normalised in {"true", "1", "yes"}:
        return True
    if normalised in {"false", "0", "no"}:
        return False
    raise ValueError(f"{label}: expected an explicit true/false value")


def _aware_timestamp(value: Any, *, label: str) -> pd.Timestamp:
    raw = _metadata_text(value)
    if not re.search(r"(?:Z|[+-]\d{2}:?\d{2})$", raw, flags=re.IGNORECASE):
        raise ValueError(f"{label}: an ISO-8601 timezone is required")
    parsed = pd.to_datetime(raw, errors="coerce", utc=True)
    if pd.isna(parsed):
        raise ValueError(f"{label}: invalid ISO-8601 timestamp")
    if parsed > pd.Timestamp.now(tz="UTC") + pd.Timedelta(minutes=5):
        raise ValueError(f"{label}: timestamp is in the future")
    return pd.Timestamp(parsed)


def _json_string_mapping(value: Any, *, label: str) -> dict[str, str]:
    try:
        decoded = json.loads(_metadata_text(value))
    except Exception as exc:
        raise ValueError(f"{label}: invalid JSON object") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label}: a JSON object is required")
    return {str(key): _metadata_text(item) for key, item in decoded.items()}


def _frequency_signature(value: Any) -> tuple[str, int | None]:
    raw = _metadata_text(value).lower().replace(" ", "").replace("_", "")
    aliases = {
        "daily": ("daily", 1),
        "businessdaily": ("daily", 1),
        "b": ("daily", 1),
        "1d": ("daily", 1),
        "weekly": ("weekly", 1),
        "1w": ("weekly", 1),
        "1wk": ("weekly", 1),
        "monthly": ("monthly", 1),
        "1mo": ("monthly", 1),
        "quarterly": ("quarterly", 1),
        "3mo": ("quarterly", 1),
    }
    if raw in aliases:
        return aliases[raw]
    match = re.fullmatch(r"(\d+)(m|min|minute|minutes|h|hr|hour|hours)", raw)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        return "intraday", amount * (60 if unit.startswith("h") else 1)
    return raw, None


def _validate_frequency(
    declared: str,
    source_index: pd.DatetimeIndex,
    *,
    expected_frequency: str | None,
    label: str,
) -> None:
    declared_signature = _frequency_signature(declared)
    if expected_frequency:
        expected_signature = _frequency_signature(expected_frequency)
        if (
            declared_signature != expected_signature
            or _metadata_text(declared).lower() != _metadata_text(expected_frequency).lower()
        ):
            raise ValueError(
                f"{label}: declared frequency '{declared}' is incompatible with "
                f"market interval '{expected_frequency}'; use the exact interval label"
            )
    if len(source_index) < 2:
        return
    deltas = pd.Series(source_index).sort_values().diff().dropna().dt.total_seconds().div(60.0)
    if deltas.empty:
        return
    median_minutes = float(deltas.median())
    family, amount = declared_signature
    compatible = True
    if family == "intraday" and amount:
        compatible = abs(median_minutes - amount) <= max(1.0, amount * 0.10)
    elif family == "daily":
        compatible = 18 * 60 <= median_minutes <= 4 * 24 * 60
    elif family == "weekly":
        compatible = 4 * 24 * 60 <= median_minutes <= 10 * 24 * 60
    elif family == "monthly":
        compatible = 20 * 24 * 60 <= median_minutes <= 40 * 24 * 60
    elif family == "quarterly":
        compatible = 60 * 24 * 60 <= median_minutes <= 110 * 24 * 60
    else:
        compatible = False
    if not compatible:
        raise ValueError(
            f"{label}: timestamp cadence ({median_minutes:.1f} minutes median) is incompatible "
            f"with declared frequency '{declared}'"
        )


def _returns_semantic_checks(values: pd.DataFrame, *, label: str) -> None:
    finite = values.replace([np.inf, -np.inf], np.nan)
    if bool((finite <= -1.0).to_numpy().any()):
        raise ValueError(f"{label}: simple returns must be strictly greater than -100%")
    for column in finite.columns:
        series = finite[column].dropna().astype(float)
        if series.empty:
            continue
        absolute = series.abs()
        nonnegative_share = float((series >= 0.0).mean())
        if float(absolute.median()) > 0.25 or float(absolute.max()) > 1.0:
            raise ValueError(
                f"{label}: column '{column}' resembles a price/level or percent-scaled series, "
                "not decimal simple returns"
            )
        if nonnegative_share >= 0.98 and float(series.median()) > 0.10:
            raise ValueError(
                f"{label}: column '{column}' is almost entirely positive at level-like magnitudes"
            )


def _canonical_evidence_manifest(
    metadata: Mapping[str, str],
    *,
    columns: list[str],
    label: str,
) -> dict[str, Any]:
    try:
        periods_per_year = float(metadata["meta_periods_per_year"])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: meta_periods_per_year must be numeric") from exc
    if not np.isfinite(periods_per_year) or periods_per_year <= 0:
        raise ValueError(f"{label}: meta_periods_per_year must be positive")
    trial_ids = _json_string_mapping(metadata["meta_trial_ids_json"], label=f"{label} trial ids")
    trial_config_hashes = _json_string_mapping(
        metadata["meta_trial_config_sha256_json"],
        label=f"{label} trial config hashes",
    )
    expected = set(columns)
    if set(trial_ids) != expected or set(trial_config_hashes) != expected:
        raise ValueError(
            f"{label}: trial_ids and trial_config_hashes must cover exactly every return column"
        )
    if len(set(trial_ids.values())) != len(trial_ids) or any(not value for value in trial_ids.values()):
        raise ValueError(f"{label}: every return column needs a unique, non-empty trial identity")
    bad_hashes = [
        name for name, value in trial_config_hashes.items()
        if not _SHA256_RE.fullmatch(value.lower())
    ]
    if bad_hashes:
        raise ValueError(f"{label}: invalid SHA-256 config provenance for {', '.join(bad_hashes)}")
    manifest_timestamp = _aware_timestamp(
        metadata["meta_manifest_timestamp"],
        label=f"{label} manifest timestamp",
    ).isoformat()
    net_of_costs = _strict_bool(metadata["meta_net_of_costs"], label=f"{label} net_of_costs")
    complete_trial_ledger = _strict_bool(
        metadata["meta_complete_trial_ledger"],
        label=f"{label} complete_trial_ledger",
    )
    point_in_time = _strict_bool(
        metadata["meta_point_in_time"],
        label=f"{label} point_in_time",
    )
    if not point_in_time:
        raise ValueError(f"{label}: point_in_time must be explicitly true")
    knowledge_cutoff = _aware_timestamp(
        metadata["meta_knowledge_cutoff"],
        label=f"{label} knowledge cutoff",
    ).isoformat()
    source_snapshot_hash = metadata["meta_source_snapshot_sha256"].lower()
    market_data_snapshot_hash = metadata["meta_market_data_snapshot_sha256"].lower()
    if not _SHA256_RE.fullmatch(source_snapshot_hash):
        raise ValueError(f"{label}: meta_source_snapshot_sha256 is invalid")
    if not _SHA256_RE.fullmatch(market_data_snapshot_hash):
        raise ValueError(f"{label}: meta_market_data_snapshot_sha256 is invalid")
    signing_key_id = metadata["meta_signing_key_id"].strip()
    if not signing_key_id:
        raise ValueError(f"{label}: meta_signing_key_id is required")
    signature_algorithm = metadata["meta_signature_algorithm"].strip().lower()
    if signature_algorithm != SIGNATURE_ALGORITHM:
        raise ValueError(
            f"{label}: meta_signature_algorithm must be {SIGNATURE_ALGORITHM}"
        )
    manifest = {
        "schema_version": metadata["meta_schema_version"],
        "dataset_kind": metadata["meta_dataset_kind"],
        "frequency": metadata["meta_frequency"],
        "periods_per_year": periods_per_year,
        "return_convention": metadata["meta_return_convention"].lower(),
        "return_unit": metadata["meta_return_unit"].lower(),
        "currency": metadata["meta_currency"].upper(),
        "net_of_costs": net_of_costs,
        "evidence_id": metadata["meta_evidence_id"],
        "evidence_authority": metadata["meta_evidence_authority"],
        "manifest_timestamp": manifest_timestamp,
        "evidence_payload_hash": metadata["meta_payload_sha256"].lower(),
        "point_in_time": True,
        "source_snapshot_id": metadata["meta_source_snapshot_id"],
        "source_snapshot_hash": source_snapshot_hash,
        "market_data_snapshot_hash": market_data_snapshot_hash,
        "knowledge_cutoff": knowledge_cutoff,
        "revision_policy": metadata["meta_revision_policy"].lower(),
        "trial_ids": trial_ids,
        "trial_config_hashes": {key: value.lower() for key, value in trial_config_hashes.items()},
        "complete_trial_ledger": complete_trial_ledger,
        "signing_key_id": signing_key_id,
        "signature_algorithm": signature_algorithm,
        "candidate_family_certified": bool(
            metadata["meta_dataset_kind"] == "candidate_returns"
            and complete_trial_ledger
            and net_of_costs
        ),
    }
    if metadata["meta_dataset_kind"] == "factor_returns":
        vintage_hash = metadata["meta_vintage_ledger_sha256"].lower()
        if not _SHA256_RE.fullmatch(vintage_hash):
            raise ValueError(f"{label}: meta_vintage_ledger_sha256 is invalid")
        manifest["vintage_ledger_hash"] = vintage_hash
    elif metadata["meta_vintage_ledger_sha256"].upper() != "NOT_APPLICABLE":
        raise ValueError(
            f"{label}: meta_vintage_ledger_sha256 must be NOT_APPLICABLE for candidate returns"
        )
    return manifest


def _aligned_numeric_matrix(
    upload: Any,
    index: pd.Index,
    *,
    label: str,
    minimum_columns: int,
    dataset_kind: str,
    expected_frequency: str | None = None,
    expected_periods_per_year: float | None = None,
    expected_currency: str | None = None,
    require_metadata: bool = False,
) -> pd.DataFrame | None:
    """Load timestamped evidence without any positional alignment fallback."""
    if upload is None:
        return None
    raw = _read_csv_upload(upload)
    if raw.empty:
        raise ValueError(f"{label}: uploaded CSV is empty")

    normalised = {
        str(column).strip().lower().replace(" ", "_"): column
        for column in raw.columns
    }
    if len(normalised) != len(raw.columns):
        raise ValueError(f"{label}: duplicate or ambiguous column names")
    date_column = next(
        (
            normalised[name]
            for name in ("timestamp", "date", "datetime", "time")
            if name in normalised
        ),
        None,
    )
    if date_column is None:
        raise ValueError(
            f"{label}: an explicit timestamp/date column is required; positional alignment is forbidden"
        )

    source_index = _normalised_timestamp_index(raw[date_column], label=label)
    if source_index.has_duplicates:
        duplicates = int(source_index.duplicated(keep=False).sum())
        raise ValueError(f"{label}: {duplicates} duplicate timestamps")
    target_index = _normalised_timestamp_index(index, label="market data")
    if target_index.has_duplicates:
        raise ValueError("market data: duplicate timestamps prevent evidentiary alignment")

    metadata_columns = [column for name, column in normalised.items() if name.startswith("meta_")]
    evidence_columns = [
        column
        for name, column in normalised.items()
        if name.startswith("available_at__") or name.startswith("vintage_id__")
    ]
    value_columns = [
        column
        for column in raw.columns
        if column not in {date_column, *metadata_columns, *evidence_columns}
    ]
    candidates = raw[value_columns].copy()
    candidates.columns = [str(column).strip() for column in candidates.columns]
    candidates = candidates.apply(pd.to_numeric, errors="coerce")
    candidates.index = source_index
    candidates = candidates.replace([np.inf, -np.inf], np.nan)
    _returns_semantic_checks(candidates, label=label)
    candidates = candidates.reindex(target_index)
    candidates.index = index

    vintage_ledger: pd.DataFrame | None = None
    if dataset_kind == "factor_returns":
        factor_names = [str(column).strip() for column in value_columns]
        expected_companions: set[Any] = set()
        ledger_rows: list[dict[str, str]] = []
        utc_observations = source_index.tz_localize("UTC")
        target_pairs = pd.DataFrame(index=target_index)
        for original_column, factor_name in zip(value_columns, factor_names):
            normalised_factor = factor_name.lower().replace(" ", "_")
            available_column = normalised.get(f"available_at__{normalised_factor}")
            vintage_column = normalised.get(f"vintage_id__{normalised_factor}")
            if available_column is None or vintage_column is None:
                raise ValueError(
                    f"{label}: factor '{factor_name}' requires available_at__{factor_name} "
                    f"and vintage_id__{factor_name}"
                )
            expected_companions.update({available_column, vintage_column})
            available = pd.Series(
                pd.to_datetime(raw[available_column], errors="coerce", utc=True).array,
                index=source_index,
            )
            vintage = pd.Series(
                [_metadata_text(value) for value in raw[vintage_column]],
                index=source_index,
                dtype="object",
            )
            source_values = pd.to_numeric(raw[original_column], errors="coerce")
            populated = source_values.notna().to_numpy()
            if available[populated].isna().any():
                raise ValueError(f"{label}: factor '{factor_name}' has missing available_at evidence")
            if (vintage[populated].str.len() == 0).any():
                raise ValueError(f"{label}: factor '{factor_name}' has missing vintage_id evidence")
            if bool((available[populated].array > utc_observations[populated]).any()):
                raise ValueError(
                    f"{label}: factor '{factor_name}' contains observations unavailable at the bar cutoff"
                )
            target_pairs[f"available_at__{factor_name}"] = available.reindex(target_index).array
            target_pairs[f"vintage_id__{factor_name}"] = vintage.reindex(target_index).array
        unexpected = set(evidence_columns) - expected_companions
        if unexpected:
            raise ValueError(
                f"{label}: companion evidence does not map to a factor column: "
                + ", ".join(sorted(map(str, unexpected)))
            )
        target_pairs.index = index
        for factor_name in factor_names:
            mask = candidates[factor_name].notna()
            for observation, available, vintage in zip(
                pd.Index(candidates.index)[mask],
                target_pairs.loc[mask, f"available_at__{factor_name}"],
                target_pairs.loc[mask, f"vintage_id__{factor_name}"],
            ):
                if pd.isna(available) or not _metadata_text(vintage):
                    raise ValueError(
                        f"{label}: aligned factor '{factor_name}' lacks vintage evidence"
                    )
                ledger_rows.append({
                    "observation_at": pd.Timestamp(observation).isoformat(),
                    "factor": factor_name,
                    "available_at": pd.Timestamp(available).isoformat(),
                    "vintage_id": _metadata_text(vintage),
                })
        vintage_ledger = pd.DataFrame(
            ledger_rows,
            columns=["observation_at", "factor", "available_at", "vintage_id"],
        ).sort_values(["observation_at", "factor"], kind="stable", ignore_index=True)
    elif evidence_columns:
        raise ValueError(f"{label}: vintage companion columns are only valid for factor returns")

    per_column_coverage = candidates.notna().mean()
    below_threshold = [
        str(column) for column, coverage in per_column_coverage.items()
        if float(coverage) < 0.80
    ]
    if below_threshold:
        raise ValueError(
            f"{label}: no trial/factor column may be silently discarded; <80% coverage for "
            + ", ".join(below_threshold)
        )
    if candidates.shape[1] < minimum_columns:
        raise ValueError(
            f"{label}: at least {minimum_columns} numeric columns with >=80% timestamp coverage are required"
        )
    complete = int(candidates.dropna(how="any").shape[0])
    required_complete = min(len(candidates), max(30, int(np.ceil(len(candidates) * 0.70))))
    if complete < required_complete:
        raise ValueError(
            f"{label}: only {complete}/{len(candidates)} complete aligned rows; "
            f"{required_complete} are required"
        )
    candidates.attrs["alignment"] = {
        "policy": "timestamp_exact_no_positional_fallback",
        "source_rows": int(len(raw)),
        "market_rows": int(len(index)),
        "complete_rows": complete,
        "coverage": {str(key): float(value) for key, value in per_column_coverage.items()},
    }
    if require_metadata:
        metadata = _constant_metadata(raw, normalised, label=label)
        if metadata["meta_schema_version"] != _EVIDENCE_SCHEMA:
            raise ValueError(
                f"{label}: unsupported schema '{metadata['meta_schema_version']}', "
                f"expected '{_EVIDENCE_SCHEMA}'"
            )
        if metadata["meta_dataset_kind"] != dataset_kind:
            raise ValueError(f"{label}: meta_dataset_kind must be '{dataset_kind}'")
        if metadata["meta_return_convention"].lower() != "simple":
            raise ValueError(f"{label}: only simple-return convention is accepted")
        if metadata["meta_return_unit"].lower() != "decimal":
            raise ValueError(f"{label}: returns must use decimal units, not percentages or levels")
        currency = metadata["meta_currency"].upper()
        if not _ISO_CURRENCY_RE.fullmatch(currency):
            raise ValueError(f"{label}: currency must be an ISO-style three-letter code")
        if expected_currency and _ISO_CURRENCY_RE.fullmatch(str(expected_currency).upper()):
            if currency != str(expected_currency).upper():
                raise ValueError(
                    f"{label}: currency '{currency}' is incompatible with market currency "
                    f"'{str(expected_currency).upper()}'"
                )
        _validate_frequency(
            metadata["meta_frequency"],
            source_index,
            expected_frequency=expected_frequency,
            label=label,
        )
        manifest = _canonical_evidence_manifest(
            metadata,
            columns=[str(column) for column in candidates.columns],
            label=label,
        )
        if expected_periods_per_year is not None:
            tolerance = max(1.0, abs(float(expected_periods_per_year)) * 0.01)
            if abs(float(manifest["periods_per_year"]) - float(expected_periods_per_year)) > tolerance:
                raise ValueError(
                    f"{label}: periods_per_year {manifest['periods_per_year']} is incompatible with "
                    f"the market contract {expected_periods_per_year}"
                )
        if dataset_kind == "candidate_returns" and not bool(manifest["net_of_costs"]):
            raise ValueError(f"{label}: candidate returns must be explicitly net of execution costs")
        payload_hash = data_hash(candidates)
        if not _SHA256_RE.fullmatch(str(manifest["evidence_payload_hash"])):
            raise ValueError(f"{label}: meta_payload_sha256 is not a valid SHA-256 digest")
        if manifest["evidence_payload_hash"] != payload_hash:
            raise ValueError(
                f"{label}: payload hash mismatch; aligned evidence computes to {payload_hash}"
            )
        if manifest["source_snapshot_hash"] != payload_hash:
            raise ValueError(
                f"{label}: source snapshot hash must bind the exact aligned matrix ({payload_hash})"
            )
        if dataset_kind == "factor_returns":
            if not isinstance(vintage_ledger, pd.DataFrame) or vintage_ledger.empty:
                raise ValueError(f"{label}: a non-empty per-observation vintage ledger is required")
            vintage_hash = data_hash(vintage_ledger)
            if manifest.get("vintage_ledger_hash") != vintage_hash:
                raise ValueError(
                    f"{label}: vintage ledger hash mismatch; aligned evidence computes to {vintage_hash}"
                )
        evidence_end = pd.Timestamp(_normalised_timestamp_index(candidates.index, label=label).max(), tz="UTC")
        if evidence_end > pd.Timestamp(manifest["knowledge_cutoff"]):
            raise ValueError(f"{label}: evidence extends beyond meta_knowledge_cutoff")
        declared_manifest_hash = metadata["meta_manifest_sha256"].lower()
        computed_manifest_hash = stable_hash(manifest)
        if not _SHA256_RE.fullmatch(declared_manifest_hash):
            raise ValueError(f"{label}: meta_manifest_sha256 is not a valid SHA-256 digest")
        if declared_manifest_hash != computed_manifest_hash:
            raise ValueError(
                f"{label}: manifest hash mismatch; canonical metadata computes to {computed_manifest_hash}"
            )
        candidates.attrs.update({
            "dataset_kind": dataset_kind,
            "evidence_manifest_hash": computed_manifest_hash,
            "evidence_manifest_payload": manifest,
            "evidence_payload_hash": payload_hash,
            "evidence_signature_base64": metadata["meta_signature_base64"],
            "return_convention": "simple",
            "return_unit": "decimal",
            "net_of_costs": bool(manifest["net_of_costs"]),
            "frequency": str(manifest["frequency"]),
            "periods_per_year": float(manifest["periods_per_year"]),
            "currency": str(manifest["currency"]),
            "evidence_id": str(manifest["evidence_id"]),
            "manifest_timestamp": str(manifest["manifest_timestamp"]),
            "point_in_time": True,
            "source_snapshot_id": str(manifest["source_snapshot_id"]),
            "source_snapshot_hash": str(manifest["source_snapshot_hash"]),
            "market_data_snapshot_hash": str(manifest["market_data_snapshot_hash"]),
            "knowledge_cutoff": str(manifest["knowledge_cutoff"]),
            "revision_policy": str(manifest["revision_policy"]),
            "signing_key_id": str(manifest["signing_key_id"]),
            "signature_algorithm": str(manifest["signature_algorithm"]),
            "trial_ids": dict(manifest["trial_ids"]),
            "trial_config_hashes": dict(manifest["trial_config_hashes"]),
            "complete_trial_ledger": bool(manifest["complete_trial_ledger"]),
            "candidate_family_certified": bool(
                dataset_kind == "candidate_returns"
                and manifest["complete_trial_ledger"]
                and manifest["net_of_costs"]
            ),
        })
        if isinstance(vintage_ledger, pd.DataFrame):
            candidates.attrs["factor_vintage_ledger"] = vintage_ledger
    else:
        # Parsing-only compatibility for callers that lack a sampling contract.
        # The operational V7 path always requires the manifest above.
        candidates.attrs.update({
            "dataset_kind": dataset_kind,
            "semantic_validation": "UNAVAILABLE — no evidence manifest supplied",
            "candidate_family_certified": False,
        })
    return candidates


def _candidate_matrix(
    upload: Any,
    index: pd.Index,
    *,
    expected_frequency: str | None = None,
    expected_periods_per_year: float | None = None,
    expected_currency: str | None = None,
    require_metadata: bool = False,
) -> pd.DataFrame | None:
    return _aligned_numeric_matrix(
        upload,
        index,
        label="candidate returns",
        minimum_columns=2,
        dataset_kind="candidate_returns",
        expected_frequency=expected_frequency,
        expected_periods_per_year=expected_periods_per_year,
        expected_currency=expected_currency,
        require_metadata=require_metadata,
    )


def _factor_matrix(
    upload: Any,
    index: pd.Index,
    *,
    expected_frequency: str | None = None,
    expected_periods_per_year: float | None = None,
    expected_currency: str | None = None,
    require_metadata: bool = False,
) -> pd.DataFrame | None:
    return _aligned_numeric_matrix(
        upload,
        index,
        label="factor returns",
        minimum_columns=1,
        dataset_kind="factor_returns",
        expected_frequency=expected_frequency,
        expected_periods_per_year=expected_periods_per_year,
        expected_currency=expected_currency,
        require_metadata=require_metadata,
    )


def _read_json_upload(upload: Any) -> dict[str, Any]:
    if isinstance(upload, Mapping) and "bytes" not in upload:
        return dict(upload)
    try:
        value = json.loads(_upload_bytes(upload).decode("utf-8"))
    except Exception as exc:
        raise ValueError("PIT manifest: invalid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("PIT manifest: the root must be a JSON object")
    return value


def _verified_point_in_time_manifest(
    upload: Any,
    bars: pd.DataFrame,
) -> tuple[dict[str, Any] | None, str, str, str]:
    """Verify a PIT manifest against the exact bars sent to the engine."""
    if upload is None:
        return None, "", "", "PIT manifest unavailable"
    try:
        raw = _read_json_upload(upload)
        declared_hash = _metadata_text(
            raw.pop("manifest_sha256", raw.pop("point_in_time_manifest_hash", ""))
        ).lower()
        signature_base64 = _metadata_text(
            raw.pop(
                "signature_base64",
                raw.pop("manifest_signature_base64", raw.pop("point_in_time_signature_base64", "")),
            )
        )
        required = {
            "schema_version",
            "point_in_time",
            "source_snapshot_id",
            "source_snapshot_hash",
            "source",
            "manifest_timestamp",
            "knowledge_cutoff",
            "evidence_authority",
            "signing_key_id",
            "signature_algorithm",
        }
        missing = sorted(required.difference(raw))
        if missing:
            raise ValueError("missing fields: " + ", ".join(missing))
        if raw["schema_version"] != _PIT_SCHEMA:
            raise ValueError(f"schema_version must be '{_PIT_SCHEMA}'")
        if raw["point_in_time"] is not True:
            raise ValueError("point_in_time must be the JSON boolean true")
        source_snapshot_id = _metadata_text(raw["source_snapshot_id"])
        evidence_authority = _metadata_text(raw["evidence_authority"])
        if not source_snapshot_id:
            raise ValueError("source_snapshot_id must be non-empty")
        if not evidence_authority:
            raise ValueError("evidence_authority must be non-empty")
        signing_key_id = _metadata_text(raw["signing_key_id"])
        signature_algorithm = _metadata_text(raw["signature_algorithm"]).lower()
        if not signing_key_id:
            raise ValueError("signing_key_id must be non-empty")
        if signature_algorithm != SIGNATURE_ALGORITHM:
            raise ValueError(f"signature_algorithm must be {SIGNATURE_ALGORITHM}")
        if not signature_base64:
            raise ValueError("signature_base64 must be supplied")
        manifest_timestamp = _aware_timestamp(
            raw["manifest_timestamp"], label="PIT manifest timestamp"
        )
        knowledge_cutoff = _aware_timestamp(
            raw["knowledge_cutoff"], label="PIT knowledge cutoff"
        )
        if knowledge_cutoff > manifest_timestamp:
            raise ValueError("knowledge_cutoff cannot be later than manifest_timestamp")
        if len(bars.index):
            data_end = pd.Timestamp(_normalised_timestamp_index(bars.index, label="market data").max(), tz="UTC")
            if data_end > knowledge_cutoff:
                raise ValueError("market data extends beyond the manifest knowledge_cutoff")
        snapshot_hash = _metadata_text(raw["source_snapshot_hash"]).lower()
        computed_snapshot_hash = data_hash(bars)
        if not _SHA256_RE.fullmatch(snapshot_hash):
            raise ValueError("source_snapshot_hash is not a valid SHA-256 digest")
        if snapshot_hash != computed_snapshot_hash:
            raise ValueError(
                f"source snapshot hash mismatch; active bars compute to {computed_snapshot_hash}"
            )
        active_source = _metadata_text(bars.attrs.get("data_source", ""))
        manifest_source = _metadata_text(raw["source"])
        if active_source and manifest_source and active_source != manifest_source:
            raise ValueError(
                f"source '{manifest_source}' does not match active adapter '{active_source}'"
            )
        manifest = {
            "schema_version": _PIT_SCHEMA,
            "point_in_time": True,
            "source_snapshot_id": source_snapshot_id,
            "source_snapshot_hash": snapshot_hash,
            "source": manifest_source,
            "manifest_timestamp": manifest_timestamp.isoformat(),
            "knowledge_cutoff": knowledge_cutoff.isoformat(),
            "evidence_authority": evidence_authority,
            "signing_key_id": signing_key_id,
            "signature_algorithm": signature_algorithm,
        }
        computed_manifest_hash = stable_hash(manifest)
        if not _SHA256_RE.fullmatch(declared_hash):
            raise ValueError("manifest_sha256 is not a valid SHA-256 digest")
        if declared_hash != computed_manifest_hash:
            raise ValueError(
                f"manifest hash mismatch; canonical PIT manifest computes to {computed_manifest_hash}"
            )
        return manifest, computed_manifest_hash, signature_base64, ""
    except Exception as exc:
        return None, "", "", f"PIT manifest: {exc}"


def _commit_scalar_widget(stable_key: str, widget_key: str) -> None:
    st.session_state[stable_key] = st.session_state.get(widget_key)


def _scalar_widget_key(stable_key: str, default: Any) -> str:
    """Use a durable shadow value because V7 is rendered in a lazy tab."""
    widget_key = f"_{stable_key}_widget"
    if stable_key not in st.session_state:
        st.session_state[stable_key] = default
    stable_value = st.session_state.get(stable_key, default)
    if widget_key not in st.session_state or st.session_state.get(widget_key) != stable_value:
        # A lazy tab may disappear while the sampling contract changes.  Keep
        # the widget shadow synchronized with the validated durable value so a
        # stale option can never diverge from the run configuration.
        st.session_state[widget_key] = stable_value
    return widget_key


def _scalar_widget_callback(stable_key: str) -> tuple[Any, tuple[str, str]]:
    widget_key = f"_{stable_key}_widget"
    return _commit_scalar_widget, (stable_key, widget_key)


def _scalar_widget_kwargs(stable_key: str, default: Any) -> dict[str, Any]:
    callback, args = _scalar_widget_callback(stable_key)
    return {
        "key": _scalar_widget_key(stable_key, default),
        "on_change": callback,
        "args": args,
    }


def _commit_upload_widget(stable_key: str, widget_key: str) -> None:
    upload = st.session_state.get(widget_key)
    if upload is None:
        st.session_state.pop(stable_key, None)
        return
    st.session_state[stable_key] = {
        "bytes": _upload_bytes(upload),
        "name": str(getattr(upload, "name", "evidence")),
        "type": str(getattr(upload, "type", "application/octet-stream")),
    }


def _upload_widget_key(stable_key: str) -> str:
    return f"_{stable_key}_widget"


def _persisted_upload_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return _metadata_text(value.get("name"))
    return _metadata_text(getattr(value, "name", ""))


def _state_value(state: Mapping[str, Any], key: str, default: Any) -> Any:
    try:
        value = state.get(key, default)
    except Exception:
        return default
    return default if value is None else value


def _horizon_options(periods_per_year: int) -> list[int]:
    ppy = max(int(periods_per_year), 4)
    return sorted({max(4, int(round(ppy / 4))), max(8, int(round(ppy / 2))), ppy, ppy * 2})


def _candidate_template(
    index: pd.Index,
    authoritative_returns: pd.Series | None,
    *,
    frequency: str = "1d",
    periods_per_year: int = 252,
    currency: str = "USD",
    market_data_snapshot_hash: str = "",
) -> pd.DataFrame:
    """Return an evidentiary template without fabricating a challenger.

    The selected column may be prefilled only from the canonical execution
    ledger.  Candidate columns are intentionally empty: multiplying the
    champion by an arbitrary constant would manufacture a trial and could
    contaminate DSR/PBO and data-snooping controls.
    """
    selected = pd.Series(np.nan, index=index, dtype=float)
    if isinstance(authoritative_returns, pd.Series):
        selected = pd.to_numeric(authoritative_returns, errors="coerce").reindex(index)
    frame = pd.DataFrame({
        "timestamp": pd.Index(index).astype(str),
        "selected": selected.to_numpy(dtype=float),
        "candidate_A": np.nan,
    })
    return _attach_evidence_template_metadata(
        frame,
        dataset_kind="candidate_returns",
        frequency=frequency,
        periods_per_year=periods_per_year,
        currency=currency,
        net_of_costs=True,
        complete_trial_ledger=False,
        market_data_snapshot_hash=market_data_snapshot_hash,
        revision_policy="derived_from_pit_snapshot",
    )


def _factor_template(
    index: pd.Index,
    *,
    frequency: str = "1d",
    periods_per_year: int = 252,
    currency: str = "USD",
    market_data_snapshot_hash: str = "",
) -> pd.DataFrame:
    frame = pd.DataFrame({
        "timestamp": pd.Index(index).astype(str),
        "factor_A": np.nan,
        # Every usable factor value needs a causal release clock and immutable
        # vintage identity.  Providers replace these placeholders before they
        # hash and sign the aligned factor payload plus vintage ledger.
        "available_at__factor_A": pd.Index(index).astype(str),
        "vintage_id__factor_A": "REPLACE_WITH_VINTAGE_ID",
    })
    return _attach_evidence_template_metadata(
        frame,
        dataset_kind="factor_returns",
        frequency=frequency,
        periods_per_year=periods_per_year,
        currency=currency,
        net_of_costs=False,
        complete_trial_ledger=False,
        market_data_snapshot_hash=market_data_snapshot_hash,
        revision_policy="vintage_locked",
    )


def _attach_evidence_template_metadata(
    frame: pd.DataFrame,
    *,
    dataset_kind: str,
    frequency: str,
    periods_per_year: int,
    currency: str,
    net_of_costs: bool,
    complete_trial_ledger: bool,
    market_data_snapshot_hash: str,
    revision_policy: str,
) -> pd.DataFrame:
    """Add a manifest skeleton while deliberately leaving proof fields blank."""
    value_columns = [
        str(column)
        for column in frame.columns
        if column != "timestamp"
        and not str(column).lower().startswith("available_at__")
        and not str(column).lower().startswith("vintage_id__")
    ]
    placeholders = {column: "REPLACE_WITH_STABLE_ID" for column in value_columns}
    placeholder_hashes = {column: "REPLACE_WITH_SHA256" for column in value_columns}
    metadata: dict[str, Any] = {
        "meta_schema_version": _EVIDENCE_SCHEMA,
        "meta_dataset_kind": dataset_kind,
        "meta_frequency": frequency,
        "meta_periods_per_year": int(periods_per_year),
        "meta_return_convention": "simple",
        "meta_return_unit": "decimal",
        "meta_currency": str(currency).upper() if _ISO_CURRENCY_RE.fullmatch(str(currency).upper()) else "USD",
        "meta_net_of_costs": bool(net_of_costs),
        "meta_evidence_id": "REPLACE_WITH_EVIDENCE_ID",
        "meta_evidence_authority": "REPLACE_WITH_EVIDENCE_AUTHORITY",
        "meta_manifest_timestamp": "REPLACE_WITH_ISO8601_UTC",
        "meta_payload_sha256": "REPLACE_WITH_ALIGNED_MATRIX_SHA256",
        "meta_point_in_time": True,
        "meta_source_snapshot_id": "REPLACE_WITH_IMMUTABLE_SNAPSHOT_ID",
        "meta_source_snapshot_sha256": "REPLACE_WITH_ALIGNED_MATRIX_SHA256",
        "meta_market_data_snapshot_sha256": (
            market_data_snapshot_hash
            if _SHA256_RE.fullmatch(str(market_data_snapshot_hash).lower())
            else "REPLACE_WITH_MARKET_DATA_SHA256"
        ),
        "meta_knowledge_cutoff": "REPLACE_WITH_ISO8601_UTC",
        "meta_revision_policy": revision_policy,
        "meta_vintage_ledger_sha256": (
            "REPLACE_WITH_VINTAGE_LEDGER_SHA256"
            if dataset_kind == "factor_returns"
            else "NOT_APPLICABLE"
        ),
        "meta_trial_ids_json": json.dumps(placeholders, sort_keys=True, separators=(",", ":")),
        "meta_trial_config_sha256_json": json.dumps(placeholder_hashes, sort_keys=True, separators=(",", ":")),
        "meta_complete_trial_ledger": bool(complete_trial_ledger),
        "meta_signing_key_id": "REPLACE_WITH_TRUSTED_KEY_ID",
        "meta_signature_algorithm": SIGNATURE_ALGORITHM,
        "meta_signature_base64": "REPLACE_WITH_ED25519_SIGNATURE_BASE64",
        "meta_manifest_sha256": "REPLACE_WITH_CANONICAL_MANIFEST_SHA256",
    }
    for name in _EVIDENCE_METADATA:
        frame[name] = metadata[name]
    return frame


def _pit_manifest_template(bars: pd.DataFrame) -> dict[str, Any]:
    return {
        "schema_version": _PIT_SCHEMA,
        "point_in_time": True,
        "source_snapshot_id": "REPLACE_WITH_IMMUTABLE_SNAPSHOT_ID",
        "source_snapshot_hash": data_hash(bars),
        "source": str(bars.attrs.get("data_source", "REPLACE_WITH_SOURCE")),
        "manifest_timestamp": "REPLACE_WITH_ISO8601_UTC",
        "knowledge_cutoff": "REPLACE_WITH_ISO8601_UTC",
        "evidence_authority": "REPLACE_WITH_EVIDENCE_AUTHORITY",
        "signing_key_id": "REPLACE_WITH_TRUSTED_KEY_ID",
        "signature_algorithm": SIGNATURE_ALGORITHM,
        "signature_base64": "REPLACE_WITH_ED25519_SIGNATURE_BASE64",
        "manifest_sha256": "REPLACE_WITH_CANONICAL_MANIFEST_SHA256",
    }


def build_institutional_v70_run(
    *,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    symbol: str,
    state: Mapping[str, Any] | None = None,
) -> tuple[InstitutionalRun, dict[str, Any]]:
    """Build the one canonical run shared by the certificate and V7 cockpit."""
    state = st.session_state if state is None else state
    legacy = result.get("data", pd.DataFrame())
    if not isinstance(legacy, pd.DataFrame) or legacy.empty:
        raise ValueError(result.get("error", "The reference engine returned no executable target"))

    periods_per_year = int(
        getattr(cfg, "periods_per_year", 0)
        or bars.attrs.get("periods_per_year", 252)
        or 252
    )
    interval_label = str(
        getattr(cfg, "interval_label", "")
        or bars.attrs.get("interval_label", "1d")
        or "1d"
    )
    currency = str(
        getattr(cfg, "currency", "")
        or bars.attrs.get("currency", "")
        or "USD"
    ).upper()
    horizons = _horizon_options(periods_per_year)
    requested_horizon = int(_state_value(state, "bt_v70_horizon", periods_per_year))
    scenario_horizon = min(horizons, key=lambda value: abs(value - requested_horizon))
    candidate_file = _state_value(state, "bt_v70_candidates", None)
    factor_file = _state_value(state, "bt_v70_factors", None)
    pit_file = _state_value(state, "bt_v70_pit_manifest", None)
    if pit_file is None and isinstance(bars.attrs.get("point_in_time_manifest"), Mapping):
        pit_file = dict(bars.attrs["point_in_time_manifest"]) | {
            "manifest_sha256": bars.attrs.get("point_in_time_manifest_hash", ""),
            "signature_base64": bars.attrs.get("point_in_time_signature_base64", ""),
        }
    candidate_returns = None
    factor_returns = None
    candidate_error = ""
    factor_error = ""
    try:
        candidate_returns = _candidate_matrix(
            candidate_file,
            legacy.index,
            expected_frequency=interval_label,
            expected_periods_per_year=periods_per_year,
            expected_currency=currency,
            require_metadata=True,
        )
    except Exception as exc:
        candidate_error = str(exc)
        candidate_returns = None
    try:
        factor_returns = _factor_matrix(
            factor_file,
            legacy.index,
            expected_frequency=interval_label,
            expected_periods_per_year=periods_per_year,
            expected_currency=currency,
            require_metadata=True,
        )
    except Exception as exc:
        factor_error = str(exc)
        factor_returns = None

    pit_manifest, pit_manifest_hash, pit_signature, pit_error = _verified_point_in_time_manifest(
        pit_file, bars
    )
    pit_self_attested = bool(
        _state_value(
            state,
            "bt_v70_point_in_time_self_attested",
            _state_value(state, "bt_v70_point_in_time", False),
        )
    )
    candidate_self_attested = bool(
        _state_value(
            state,
            "bt_v70_candidates_self_attested",
            _state_value(state, "bt_v70_candidates_certified", False),
        )
    )
    if pit_manifest is None and pit_self_attested:
        pit_error = (
            (pit_error + " · ") if pit_error else ""
        ) + "checkbox is self-attestation only and cannot promote the PIT gate"
    candidate_evidence_state = "UNAVAILABLE"
    if isinstance(candidate_returns, pd.DataFrame):
        if bool(candidate_returns.attrs.get("candidate_family_certified", False)):
            candidate_evidence_state = "INTEGRITY VERIFIED — AUTHORITY PENDING ENGINE"
        elif candidate_self_attested:
            candidate_evidence_state = "SELF_ATTESTED — UNAVAILABLE FOR GATE"
        else:
            candidate_evidence_state = "INCOMPLETE_TRIAL_LEDGER — UNAVAILABLE FOR GATE"

    bars_for_engine = bars.copy(deep=False)
    bars_for_engine.attrs = dict(bars.attrs)
    for key in (
        "point_in_time_manifest",
        "point_in_time_manifest_hash",
        "source_snapshot_id",
        "source_snapshot_hash",
        "point_in_time_signature_base64",
    ):
        bars_for_engine.attrs.pop(key, None)
    if pit_manifest is not None:
        bars_for_engine.attrs.update({
            "point_in_time_manifest": pit_manifest,
            "point_in_time_manifest_hash": pit_manifest_hash,
            "source_snapshot_id": pit_manifest["source_snapshot_id"],
            "source_snapshot_hash": pit_manifest["source_snapshot_hash"],
            "point_in_time_signature_base64": pit_signature,
        })

    capital = float(getattr(cfg, "capital", 1_000_000.0))
    annual_borrow_bps = float(_state_value(state, "bt_v70_borrow", 0.0))
    has_short_target = bool(
        (pd.to_numeric(legacy.get("exposure"), errors="coerce").fillna(0.0) < 0.0).any()
    )
    execution_config = ExecutionModelConfig(
        model=str(_state_value(state, "bt_v70_execution_model", "square_root")),
        initial_capital=capital,
        commission_bps=float(getattr(cfg, "fee_bps", 0.5)),
        spread_bps=float(_state_value(state, "bt_v70_spread", 2.0)),
        slippage_bps=float(getattr(cfg, "slippage_bps", 1.0)),
        impact_coefficient=float(_state_value(state, "bt_v70_impact", 0.10)),
        max_participation=float(_state_value(state, "bt_v70_participation", 0.10)),
        annual_borrow_bps=annual_borrow_bps if annual_borrow_bps > 0 else None,
        target_timing="pre_lagged_target",
        signal_latency_bars=0,
        bar_frequency=interval_label,
        periods_per_year=float(periods_per_year),
        trading_calendar="CALENDAR_DAY" if "24x7" in interval_label else "BUSINESS_DAY",
        short_sale_policy="require" if has_short_target else "allow_unverified",
        require_locate=has_short_target,
    )
    seed = int(_state_value(state, "bt_v70_seed", 41))
    scenario_config = ScenarioConfig(
        horizon_days=scenario_horizon,
        paths=int(_state_value(state, "bt_v70_paths", 250)),
        seed=seed,
        confidence=float(_state_value(state, "bt_v70_confidence", 0.975)),
        target_drawdown=float(_state_value(state, "bt_v70_reverse_dd", -0.20)),
    )
    payload = _config_payload(cfg) | {
        "periods_per_year": periods_per_year,
        "interval_label": interval_label,
        "price_basis": str(bars.attrs.get("price_basis", "unspecified")),
        "currency": currency,
        "point_in_time_manifest_hash": pit_manifest_hash,
        "source_snapshot_id": pit_manifest["source_snapshot_id"] if pit_manifest else "",
        "candidate_family_certified": bool(
            candidate_returns is not None
            and candidate_returns.attrs.get("candidate_family_certified", False)
        ),
    }
    institutional = run_institutional_stack(
        bars=bars_for_engine,
        legacy_result=result,
        strategy=str(getattr(cfg, "strategy", "UNSPECIFIED")),
        symbol=symbol,
        config_payload=payload,
        execution_config=execution_config,
        scenario_config=scenario_config,
        candidate_returns=candidate_returns,
        factor_returns=factor_returns,
        seed=seed,
        point_in_time=pit_manifest is not None,
        source=str(bars.attrs.get("data_source", "Active market-data adapter")),
    )
    candidate_contract = institutional.validation.get("candidate_evidence", {})
    candidate_authenticated = bool(
        institutional.validation.get("candidate_family_certified", False)
    )
    if isinstance(candidate_returns, pd.DataFrame):
        candidate_evidence_state = (
            "AUTHENTICATED SIGNED MANIFEST"
            if candidate_authenticated
            else "INTEGRITY ONLY — UNAVAILABLE FOR GATE"
        )
        if not candidate_authenticated and isinstance(candidate_contract, Mapping):
            reasons = candidate_contract.get("reasons", [])
            if isinstance(reasons, (list, tuple)) and reasons:
                candidate_error = "; ".join(str(reason) for reason in reasons[:4])
    pit_contract = institutional.execution.diagnostics.get("point_in_time_evidence", {})
    point_in_time_authenticated = bool(
        isinstance(pit_contract, Mapping) and pit_contract.get("verified", False)
    )
    if pit_manifest is not None and not point_in_time_authenticated and isinstance(pit_contract, Mapping):
        reasons = pit_contract.get("reasons", [])
        if isinstance(reasons, (list, tuple)) and reasons:
            pit_error = "; ".join(str(reason) for reason in reasons[:4])
    return institutional, {
        "candidate_returns": candidate_returns,
        "factor_returns": factor_returns,
        "candidate_error": candidate_error,
        "factor_error": factor_error,
        "candidate_evidence_state": candidate_evidence_state,
        "candidate_authenticated": candidate_authenticated,
        "candidate_self_attested": candidate_self_attested,
        "point_in_time": pit_manifest is not None,
        "point_in_time_authenticated": point_in_time_authenticated,
        "pit_error": pit_error,
        "point_in_time_manifest_hash": pit_manifest_hash,
        "point_in_time_manifest": pit_manifest,
        "point_in_time_signature_base64": pit_signature,
        "source_snapshot_id": pit_manifest["source_snapshot_id"] if pit_manifest else "",
        "pit_self_attested": pit_self_attested,
        "periods_per_year": periods_per_year,
        "interval_label": interval_label,
        "currency": currency,
        "scenario_horizon": scenario_horizon,
        "horizon_options": horizons,
        "price_basis": str(bars.attrs.get("price_basis", "unspecified")),
    }


def institutional_gate_summary(
    institutional: InstitutionalRun | None,
    *,
    error: str = "",
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if institutional is None:
        return {
            "decision": "HOLD — DATA REQUIRED",
            "run_id": "",
            "authoritative_source": "UNAVAILABLE",
            "fail_closed": True,
            "production_authorized": False,
            "blocking_gates": ["Institutional V7 engine"],
            "engine_error": str(error or "Institutional engine unavailable"),
        }
    validation = institutional.validation
    return {
        "decision": str(institutional.gate.get("decision", "HOLD — DATA REQUIRED")),
        "run_id": institutional.manifest.run_id,
        "authoritative_source": institutional.authoritative_source,
        "fail_closed": bool(institutional.gate.get("fail_closed", True)),
        "production_authorized": bool(institutional.gate.get("production_authorized", False)),
        "blocking_gates": list(institutional.gate.get("blocking_gates", [])),
        "data_verdict": institutional.data_catalog.verdict.value,
        "execution_status": institutional.execution.status.value,
        "psr": validation.get("psr", np.nan),
        "dsr": validation.get("dsr", {}).get("deflated_sharpe_probability", np.nan),
        "pbo": validation.get("pbo", {}).get("pbo", np.nan),
        "candidate_count": int(validation.get("candidate_count", 0) or 0),
        "candidate_error": str((context or {}).get("candidate_error", "")),
        "factor_error": str((context or {}).get("factor_error", "")),
        "candidate_evidence_state": str((context or {}).get("candidate_evidence_state", "UNAVAILABLE")),
        "candidate_authenticated": bool((context or {}).get("candidate_authenticated", False)),
        "point_in_time_manifest_hash": str((context or {}).get("point_in_time_manifest_hash", "")),
        "point_in_time_authenticated": bool(
            (context or {}).get("point_in_time_authenticated", False)
        ),
        "source_snapshot_id": str((context or {}).get("source_snapshot_id", "")),
        "pit_error": str((context or {}).get("pit_error", "")),
        "checks": institutional.gate["checks"].to_dict(orient="records"),
    }


def render_institutional_v70(
    *,
    bars: pd.DataFrame,
    result: dict[str, Any],
    cfg: Any,
    symbol: str,
    institutional: InstitutionalRun | None = None,
    context: dict[str, Any] | None = None,
    engine_error: str = "",
) -> None:
    st.markdown("## Institutional Backtest V7")
    st.caption(
        "Couche auditable et fail-closed : données, ledger événementiel, coûts calibrables, "
        "validation multi-tests, scénarios de rupture, registre et dossier de gouvernance."
    )
    legacy = result.get("data", pd.DataFrame())
    if not isinstance(legacy, pd.DataFrame) or legacy.empty:
        st.error(result.get("error", "Le moteur de référence ne fournit aucune série exploitable."))
        return

    periods_per_year = int(
        getattr(cfg, "periods_per_year", 0)
        or bars.attrs.get("periods_per_year", 252)
        or 252
    )
    interval_label = str(
        getattr(cfg, "interval_label", "")
        or bars.attrs.get("interval_label", "1d")
        or "1d"
    )
    currency = str(
        getattr(cfg, "currency", "")
        or bars.attrs.get("currency", "")
        or "USD"
    ).upper()
    horizon_options = _horizon_options(periods_per_year)
    if st.session_state.get("bt_v70_horizon") not in horizon_options:
        st.session_state["bt_v70_horizon"] = min(
            horizon_options,
            key=lambda value: abs(value - int(st.session_state.get("bt_v70_horizon", periods_per_year))),
        )

    with st.expander("V7 · Assumptions, evidence & calibration", expanded=True):
        st.caption(
            f"Sampling contract · {interval_label} · {periods_per_year} periods/year · "
            f"price basis {bars.attrs.get('price_basis', 'unspecified')} · fills at next executable open."
        )
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.selectbox(
                "Execution model",
                ["square_root", "volume_share", "almgren_chriss_proxy", "constant"],
                **_scalar_widget_kwargs("bt_v70_execution_model", "square_root"),
            )
            st.checkbox(
                "PIT declared (self-attestation only)",
                help=(
                    "Cette case seule ne certifie rien. Le gate exige un manifeste JSON horodaté et "
                    "hashé, lié exactement au snapshot actif."
                ),
                **_scalar_widget_kwargs("bt_v70_point_in_time_self_attested", False),
            )
            pit_widget_key = _upload_widget_key("bt_v70_pit_manifest")
            st.file_uploader(
                "Point-in-time manifest (JSON)",
                type=["json"],
                key=pit_widget_key,
                on_change=_commit_upload_widget,
                args=("bt_v70_pit_manifest", pit_widget_key),
            )
        with c2:
            st.number_input(
                "Spread (bps)", min_value=0.0, max_value=500.0, step=0.25,
                **_scalar_widget_kwargs("bt_v70_spread", 2.0),
            )
            st.number_input(
                "Impact coefficient", min_value=0.0, max_value=5.0, step=0.01,
                **_scalar_widget_kwargs("bt_v70_impact", 0.10),
            )
        with c3:
            st.slider(
                "Max participation", min_value=0.01, max_value=0.50, step=0.01,
                **_scalar_widget_kwargs("bt_v70_participation", 0.10),
            )
            st.number_input(
                "Borrow fallback (bps, 0 = unavailable)",
                min_value=0.0, max_value=5000.0, step=5.0,
                **_scalar_widget_kwargs("bt_v70_borrow", 0.0),
            )
        with c4:
            st.select_slider(
                "Scenario paths", options=[100, 250, 500, 800],
                **_scalar_widget_kwargs("bt_v70_paths", 250),
            )
            st.select_slider(
                "Scenario horizon (periods)",
                options=horizon_options,
                **_scalar_widget_kwargs("bt_v70_horizon", periods_per_year),
            )

        s1, s2, s3, s4, s5 = st.columns(5)
        with s1:
            st.number_input(
                "Reproducibility seed", min_value=1, max_value=1_000_000, step=1,
                **_scalar_widget_kwargs("bt_v70_seed", 41),
            )
        with s2:
            st.selectbox(
                "Tail confidence", [0.95, 0.975, 0.99],
                **_scalar_widget_kwargs("bt_v70_confidence", 0.975),
            )
        with s3:
            st.slider(
                "Reverse-stress drawdown", min_value=-0.60, max_value=-0.05, step=0.01,
                **_scalar_widget_kwargs("bt_v70_reverse_dd", -0.20),
            )
        with s4:
            candidate_widget_key = _upload_widget_key("bt_v70_candidates")
            st.file_uploader(
                "Candidate family (CSV)",
                type=["csv"],
                key=candidate_widget_key,
                on_change=_commit_upload_widget,
                args=("bt_v70_candidates", candidate_widget_key),
                help=(
                    "Timestamp + rendements simples décimaux + métadonnées de fréquence, devise, coûts, "
                    "identités/configs d’essais et hashes du payload/manifeste."
                ),
            )
            st.checkbox(
                "Trial ledger complete (self-attested)",
                help=(
                    "Ne certifie pas le ledger. Seul meta_complete_trial_ledger=true dans un manifeste "
                    "horodaté dont les hashes sont vérifiés peut satisfaire le gate."
                ),
                **_scalar_widget_kwargs("bt_v70_candidates_self_attested", False),
            )
        with s5:
            factor_widget_key = _upload_widget_key("bt_v70_factors")
            st.file_uploader(
                "Factor history (CSV)",
                type=["csv"],
                key=factor_widget_key,
                on_change=_commit_upload_widget,
                args=("bt_v70_factors", factor_widget_key),
                help=(
                    "Même contrat institutionnel : rendements simples décimaux, fréquence/devise explicites, "
                    "provenance par série, available_at + vintage_id pour chaque observation, et hashes "
                    "vérifiables du payload et du ledger de millésimes."
                ),
            )

        template = _candidate_template(
            legacy.index,
            institutional.authoritative_returns if institutional is not None else None,
            frequency=interval_label,
            periods_per_year=periods_per_year,
            currency=currency,
            market_data_snapshot_hash=data_hash(bars),
        )
        factor_template = _factor_template(
            legacy.index,
            frequency=interval_label,
            periods_per_year=periods_per_year,
            currency=currency,
            market_data_snapshot_hash=data_hash(bars),
        )
        d1, d2, d3 = st.columns(3)
        d1.download_button(
            "Candidate evidence template",
            data=template.to_csv(index=False).encode("utf-8"),
            file_name=f"{symbol}_candidate_family_template.csv",
            mime="text/csv",
            key="bt_v70_candidate_template",
        )
        d2.download_button(
            "Factor evidence template",
            data=factor_template.to_csv(index=False).encode("utf-8"),
            file_name=f"{symbol}_factor_history_template.csv",
            mime="text/csv",
            key="bt_v70_factor_template",
        )
        d3.download_button(
            "PIT manifest draft",
            data=json.dumps(_pit_manifest_template(bars), indent=2).encode("utf-8"),
            file_name=f"{symbol}_pit_manifest_draft.json",
            mime="application/json",
            key="bt_v70_pit_template",
        )
        st.caption(
            "Les champs REPLACE_WITH_* restent volontairement invalides : le terminal ne fabrique ni "
            "identité d’essai, ni autorité, ni hash de preuve. Le challenger est vide et aucune variante "
            "synthétique n’est injectée dans DSR/PBO. Une signature ne passe que si son key_id est installé "
            "indépendamment dans le trust store serveur BACKTEST_TRUSTED_EVIDENCE_ED25519_KEYS_JSON."
        )
        persisted = [
            ("PIT", _persisted_upload_name(st.session_state.get("bt_v70_pit_manifest"))),
            ("Candidates", _persisted_upload_name(st.session_state.get("bt_v70_candidates"))),
            ("Factors", _persisted_upload_name(st.session_state.get("bt_v70_factors"))),
        ]
        persisted = [f"{label}: {name}" for label, name in persisted if name]
        if persisted:
            st.caption("Persistent evidence snapshots · " + " · ".join(persisted))

    context = dict(context or {})
    if institutional is None and not engine_error:
        try:
            institutional, context = build_institutional_v70_run(
                bars=bars,
                result=result,
                cfg=cfg,
                symbol=symbol,
            )
        except Exception as exc:
            engine_error = str(exc)
    candidate_returns = context.get("candidate_returns")
    factor_returns = context.get("factor_returns")
    if context.get("candidate_error"):
        st.error(f"Candidate evidence rejected · {context['candidate_error']}")
    if context.get("factor_error"):
        st.warning(f"Factor evidence rejected · {context['factor_error']}")
    if context.get("candidate_evidence_state") not in {None, "", "UNAVAILABLE"}:
        state_value = str(context["candidate_evidence_state"])
        if state_value == "AUTHENTICATED SIGNED MANIFEST":
            st.success("Candidate evidence · AUTHENTICATED SIGNED MANIFEST")
        else:
            st.warning(f"Candidate evidence · {state_value}")
    if context.get("pit_error") and (
        context.get("pit_self_attested")
        or _state_value(st.session_state, "bt_v70_pit_manifest", None) is not None
    ):
        st.warning(f"Point-in-time evidence unavailable · {context['pit_error']}")
    elif context.get("point_in_time_authenticated"):
        st.success(
            "Point-in-time evidence · TRUSTED SIGNATURE VERIFIED · snapshot "
            f"{context.get('source_snapshot_id', 'n/a')}"
        )
    elif context.get("point_in_time_manifest_hash"):
        st.warning("Point-in-time evidence · integrity verified, authority unavailable")
    if institutional is None:
        st.error(f"Institutional V7 engine · HOLD — DATA REQUIRED · {engine_error or 'unavailable'}")
        st.info(
            "Le moteur reste fail-closed : aucun verdict legacy ou proxy ne peut remplacer le ledger exécuté."
        )
        return

    decision = institutional.gate["decision"]
    if decision == "RESEARCH APPROVED":
        st.success(f"Decision gate · {decision}")
    elif decision in {"CONDITIONAL REVIEW", "HOLD — DATA REQUIRED"}:
        st.warning(f"Decision gate · {decision}")
    else:
        st.error(f"Decision gate · {decision}")

    k1, k2, k3 = st.columns(3)
    k4, k5, k6 = st.columns(3)
    candidate_family_certified = bool(
        institutional.validation.get("candidate_family_certified", False)
    )
    dsr = institutional.validation["dsr"]["deflated_sharpe_probability"]
    pbo = institutional.validation["pbo"]["pbo"]
    reverse = institutional.scenarios["reverse_stress"]
    k1.metric("Run ID", institutional.manifest.run_id[-10:])
    k2.metric("Data gate", institutional.data_catalog.verdict.value)
    k3.metric(
        "DSR probability",
        _metric(dsr, percent=True) if candidate_family_certified else "DATA REQUIRED",
    )
    k4.metric(
        "PBO",
        _metric(pbo, percent=True) if candidate_family_certified else "DATA REQUIRED",
    )
    k5.metric("Reverse shock ×", _metric(reverse.get("multiplier")))
    k6.metric(
        "Source of truth",
        (
            "EXECUTED LEDGER"
            if institutional.execution.diagnostics.get("risk_order_replay_available", True)
            else "RISK REPLAY REQUIRED"
        ),
    )

    cockpit_tab, data_tab, stats_tab, scenario_tab, governance_tab = st.tabs([
        "Decision Cockpit", "Data & Execution", "Statistical Validation",
        "Scenario Lab", "Registry & Governance",
    ])

    with cockpit_tab:
        st.dataframe(institutional.gate["checks"], width="stretch", hide_index=True)
        blockers = list(institutional.gate.get("blocking_gates", []))
        if blockers:
            st.warning("Blocking gates · " + " · ".join(blockers))
        st.caption(
            "Autorité du verdict : rendements nets du ledger exécuté. Les métriques legacy restent des "
            "diagnostics comparatifs et ne peuvent pas promouvoir le run."
        )
        st.markdown("#### Institutional architecture")
        st.dataframe(pd.DataFrame([
            ["Data Catalog", institutional.data_catalog.verdict.value, "PIT, OHLC QA, actions, survivorship, borrow, capacity"],
            ["Event Ledger", institutional.execution.status.value, "Orders, fills, partials, settlement, cash, positions"],
            ["Research Validation", "ACTIVE", "DSR, CSCV/PBO, CPCV, Reality Check, SPA, Holm, FDR"],
            ["Scenario Engine", "ACTIVE", "Student-t, Markov, EVT, liquidity spiral, reverse stress"],
            ["Governance", "ACTIVE", "Immutable run ID, lineage, model card, export bundle"],
        ], columns=["Layer", "State", "Decision use"]), width="stretch", hide_index=True)
        st.info("Le verdict V7 reste un gate de recherche. Il n’autorise jamais automatiquement un déploiement production.")

    with data_tab:
        catalog_rows = []
        for name, status in institutional.data_catalog.fields.items():
            catalog_rows.append({
                "field": name, "state": status.state.value, "required": status.required,
                "missing": status.missing_ratio, "reason": status.reason,
            })
        st.markdown("#### Data Catalog")
        st.dataframe(pd.DataFrame(catalog_rows), width="stretch", hide_index=True)
        st.markdown("#### Capability matrix")
        capability_rows = [
            {"capability": name, "state": item.state.value, "reason": item.reason}
            for name, item in institutional.data_catalog.capabilities.items()
        ]
        st.dataframe(pd.DataFrame(capability_rows), width="stretch", hide_index=True)
        e1, e2, e3, e4 = st.columns(4)
        diagnostics = institutional.execution.diagnostics
        e1.metric("Ledger state", institutional.execution.status.value)
        e2.metric("Fill ratio", _metric(diagnostics.get("fill_ratio"), percent=True))
        e3.metric("Partial / rejected", f"{diagnostics.get('partial_orders', 0)} / {diagnostics.get('rejected_orders', 0)}")
        e4.metric("Total costs", f"{diagnostics.get('total_cost', 0.0):,.0f}")
        st.caption(
            f"Timing contract: {diagnostics.get('target_timing_contract', 'UNAVAILABLE')} · "
            f"market inputs causal: {diagnostics.get('causal_inputs_only', False)} · "
            f"risk-order replay: {diagnostics.get('risk_order_replay_available', False)} · "
            f"corporate actions: {diagnostics.get('corporate_action_policy', 'UNAVAILABLE')} · "
            f"settlement: {diagnostics.get('settlement_assumption', 'UNAVAILABLE')}"
        )
        if institutional.execution.daily is not None and not institutional.execution.daily.empty:
            daily = institutional.execution.daily
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=daily.index, y=daily["nav"], name="Execution NAV", line=dict(color="#38bdf8")))
            fig.update_layout(template="plotly_dark", height=360, margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig, width="stretch")
        fills = pd.DataFrame(institutional.execution.records()["fills"])
        st.dataframe(fills.tail(250), width="stretch", hide_index=True)

    with stats_tab:
        validation = institutional.validation
        certified = bool(validation.get("candidate_family_certified", False))
        v1, v2, v3, v4, v5 = st.columns(5)
        v1.metric("Sharpe", _metric(validation["sharpe"]))
        v2.metric("PSR", _metric(validation["psr"], percent=True))
        v3.metric(
            "DSR",
            _metric(validation["dsr"]["deflated_sharpe_probability"], percent=True)
            if certified else "DATA REQUIRED",
        )
        v4.metric(
            "CSCV / PBO",
            _metric(validation["pbo"]["pbo"], percent=True)
            if certified else "DATA REQUIRED",
        )
        v5.metric("Min track record", _metric(validation["minimum_track_record_observations"]) + " obs")
        tests = pd.DataFrame([
            ["White Reality Check", _metric(validation["white_reality_check"]["p_value"], percent=True) if certified else "DATA REQUIRED", "Bootstrap max-performance"],
            ["Hansen SPA", _metric(validation["hansen_spa"]["p_value"], percent=True) if certified else "DATA REQUIRED", "Studentized superior predictive ability"],
            ["CPCV paths", str(validation["cpcv_splits"]) if certified else "DATA REQUIRED", "Train selection + purged OOS path returns"],
            ["Candidate family", str(validation["candidate_count"]), "Uploaded strategies / parameter trials"],
            ["Aligned observations", str(validation.get("candidate_alignment", {}).get("observations", 0)), "Complete-case timestamp intersection"],
        ], columns=["Test", "Value", "Method"])
        st.dataframe(tests, width="stretch", hide_index=True)
        cpcv = validation.get("cpcv", {})
        st.json({
            "candidate_alignment": validation.get("candidate_alignment", {}),
            "cpcv": {
                "available": bool(certified and cpcv.get("available", False)),
                "paths_executed": cpcv.get("paths_executed", 0) if certified else 0,
                "positive_oos_share": cpcv.get("positive_oos_share") if certified else None,
                "median_oos_sharpe": cpcv.get("median_oos_sharpe") if certified else None,
                "missing_policy": cpcv.get("missing_policy"),
            },
        })
        if not isinstance(candidate_returns, pd.DataFrame) or not certified:
            st.warning(
                "DSR, PBO, Reality Check, SPA, Holm et FDR restent DATA REQUIRED tant que la famille "
                "complète n’est pas vérifiée par un manifeste hashé. Les calculs diagnostiques non certifiés "
                "ne sont pas affichés comme preuves."
            )
        else:
            candidate_names = list(validation.get("candidate_names") or candidate_returns.columns)
            corrections = pd.DataFrame({
                "candidate": candidate_names,
                "Holm adjusted p": [row.get("adjusted_p") for row in validation["holm"]],
                "BH/FDR adjusted p": [row.get("adjusted_p") for row in validation["benjamini_hochberg"]],
            })
            st.dataframe(corrections, width="stretch", hide_index=True)

    with scenario_tab:
        summary = institutional.scenarios["summary"].copy()
        st.dataframe(summary.style.format("{:.2%}"), width="stretch")
        availability = institutional.scenarios.get("availability", {})
        if isinstance(availability, dict):
            st.dataframe(
                pd.DataFrame([
                    {"scenario": name, **item}
                    for name, item in availability.items()
                ]),
                width="stretch",
                hide_index=True,
            )
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=summary.index, y=summary["expected_shortfall"],
            name="Terminal Expected Shortfall", marker_color="#fb7185",
        ))
        fig.add_trace(go.Bar(
            x=summary.index, y=summary["median_max_drawdown"],
            name="Median Max Drawdown", marker_color="#fbbf24",
        ))
        fig.update_layout(template="plotly_dark", barmode="group", height=390, margin=dict(l=20, r=20, t=30, b=80))
        st.plotly_chart(fig, width="stretch")
        r1, r2, r3 = st.columns(3)
        r1.metric("Reverse multiplier", _metric(reverse.get("multiplier")))
        r2.metric("EVT threshold", _metric(institutional.scenarios["evt"].get("threshold"), percent=True))
        r3.metric("Crisis regime share", _metric(institutional.scenarios["regime_mix"].get("crisis"), percent=True))
        st.json({
            "reverse_stress": reverse,
            "evt_calibration": institutional.scenarios["evt"],
            "regime_mix": institutional.scenarios["regime_mix"],
            "seed": institutional.scenarios["seed"],
            "factor_evidence": institutional.scenarios.get("factor_evidence", {}),
            "factor_history": (
                factor_returns.attrs.get("alignment", {})
                if isinstance(factor_returns, pd.DataFrame)
                else "UNAVAILABLE — univariate fallback only"
            ),
        })

    with governance_tab:
        registry = ExperimentRegistry()
        g1, g2 = st.columns([1, 1])
        with g1:
            if st.button("Register immutable experiment", type="primary", key="bt_v70_register"):
                path = registry.persist(institutional.manifest, {
                    "decision": institutional.gate["decision"],
                    "model_card": institutional.model_card,
                    "data_verdict": institutional.data_catalog.verdict.value,
                    "execution": institutional.execution.diagnostics,
                    "validation": institutional.validation,
                    "scenario_summary": institutional.scenarios["summary"],
                })
                st.success(f"Registered · {path}")
        with g2:
            st.download_button(
                "Download reproducibility bundle",
                data=institutional.bundle,
                file_name=f"{institutional.manifest.run_id}.zip",
                mime="application/zip",
                key="bt_v70_download",
            )
        runs = registry.list_runs()
        st.dataframe(runs, width="stretch", hide_index=True)
        st.markdown("#### Model card")
        st.json(institutional.model_card)
        st.markdown("#### Strategy coverage")
        strategy_coverage = institutional.model_card.get("strategy_coverage")
        if strategy_coverage:
            st.json(strategy_coverage)
        else:
            st.warning("Strategy coverage · DATA REQUIRED in model card")
        st.markdown("#### Reproducibility manifest")
        manifest_view = asdict(institutional.manifest)
        if isinstance(manifest_view.get("metadata"), dict):
            # Raw/redacted patches are downloadable governance evidence, not
            # inline UI content.  Keeping them out of the DOM also prevents an
            # accidental disclosure through browser inspection or screenshots.
            manifest_view["metadata"].pop("_bundle_evidence", None)
        st.json(_json_safe(manifest_view))
