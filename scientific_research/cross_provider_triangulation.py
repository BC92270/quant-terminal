from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import statistics
import tempfile
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import requests

from .direct_bis_reconciliation import load_persisted_direct_bis_snapshot
from .phase67_models import CrossProviderTriangulationRecord


CROSS_PROVIDER_PROTOCOL_VERSION = "SRB_CROSS_PROVIDER_TRIANGULATION_V1"
OECD_SOURCE_URL = (
    "https://sdmx.oecd.org/public/rest/data/"
    "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0/"
    "USA+GBR+JPN.M.CCRE......?startPeriod=1994-01&"
    "dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
)
OECD_API_DOCUMENTATION_URL = "https://www.oecd.org/en/data/insights/data-explainers/2024/09/api.html"
OECD_STRUCTURE_URL = (
    "https://sdmx.oecd.org/public/rest/dataflow/"
    "OECD.SDD.STES/DSD_STES@DF_FINMARK/4.0?references=all"
)
OECD_TERMS_URL = "https://www.oecd.org/en/about/terms-conditions.html"
OECD_HISTORY_SEMANTICS = "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE"
OECD_MAX_CSV_BYTES = 5_000_000
OECD_USER_AGENT = (
    "ScientificResearchBrain/0.6.7.0 research-only cross-provider triangulation; "
    "bounded public OECD SDMX request; no unattended production use"
)
OECD_EXPECTED_STRUCTURE_ID = "OECD.SDD.STES:DSD_STES@DF_FINMARK(4.0)"

OECD_BIS_REAL_MATRIX: dict[str, dict[str, str]] = {
    "GB": {
        "label": "United Kingdom",
        "oecd_ref_area": "GBR",
        "bis_series_id": "RBGBBIS",
        "lineage_assessment": "COUNTRY_SPECIFIC_LINEAGE_UNRESOLVED_FROM_OECD_FEED_METADATA",
    },
    "JP": {
        "label": "Japan",
        "oecd_ref_area": "JPN",
        "bis_series_id": "RBJPBIS",
        "lineage_assessment": "BIS_DEPENDENCE_RISK_REQUIRES_COUNTRY_SOURCE_AUDIT",
    },
    "US": {
        "label": "United States",
        "oecd_ref_area": "USA",
        "bis_series_id": "RBUSBIS",
        "lineage_assessment": "COUNTRY_SPECIFIC_LINEAGE_UNRESOLVED_FROM_OECD_FEED_METADATA",
    },
}


class CrossProviderDataError(RuntimeError):
    """Raised when a governed OECD/BIS triangulation gate fails."""


@dataclass(frozen=True)
class OecdCsvPayload:
    raw_csv: bytes
    retrieved_at: str
    response_metadata: dict[str, str]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=lambda item: str(item))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite numeric value cannot be fingerprinted.")
        return round(value, 12)
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_digest(parts).split(':', 1)[1][:16]}"


def _row(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Expected a dataclass or mapping.")


def _record(value: Any) -> CrossProviderTriangulationRecord:
    if isinstance(value, CrossProviderTriangulationRecord):
        return value
    source = _row(value)
    allowed = {item.name for item in fields(CrossProviderTriangulationRecord)}
    return CrossProviderTriangulationRecord(**{key: source[key] for key in allowed if key in source})


def _parse_instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _comparison_matrix(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or set(value) != set(OECD_BIS_REAL_MATRIX):
        raise ValueError("The OECD/BIS comparison matrix must cover GB, JP and US exactly.")
    matrix: dict[str, dict[str, str]] = {}
    areas: set[str] = set()
    bis_ids: set[str] = set()
    for market, expected in sorted(OECD_BIS_REAL_MATRIX.items()):
        item = value.get(market)
        if not isinstance(item, Mapping):
            raise ValueError(f"The comparison mapping for {market} is malformed.")
        normalized = {key: str(item.get(key) or "").strip() for key in expected}
        if normalized != expected:
            raise ValueError(f"The frozen OECD/BIS comparison mapping changed for {market}.")
        if normalized["oecd_ref_area"] in areas or normalized["bis_series_id"] in bis_ids:
            raise ValueError("The OECD/BIS comparison matrix contains duplicate identities.")
        areas.add(normalized["oecd_ref_area"])
        bis_ids.add(normalized["bis_series_id"])
        matrix[market] = normalized
    return matrix


def _direct_series_matrix(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or set(value) != {"GB", "JP", "US"}:
        raise ValueError("A complete frozen BIS series matrix is required.")
    matrix: dict[str, dict[str, str]] = {}
    for market, item in sorted(value.items()):
        if not isinstance(item, Mapping):
            raise ValueError(f"The direct BIS matrix is malformed for {market}.")
        real_id = str(item.get("real_series_id") or "").strip().upper()
        nominal_id = str(item.get("nominal_series_id") or "").strip().upper()
        if real_id != OECD_BIS_REAL_MATRIX[market]["bis_series_id"]:
            raise ValueError(f"The direct BIS real series changed for {market}.")
        if not re.fullmatch(r"[A-Z0-9]{3,20}", nominal_id) or nominal_id == real_id:
            raise ValueError(f"The direct BIS nominal series is invalid for {market}.")
        matrix[market] = {
            "label": str(item.get("label") or OECD_BIS_REAL_MATRIX[market]["label"]).strip(),
            "real_series_id": real_id,
            "nominal_series_id": nominal_id,
        }
    return matrix


def _protocol_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "protocol_version",
        "replication_id",
        "direct_reconciliation_id",
        "direct_snapshot_id",
        "direct_snapshot_fingerprint",
        "protocol_frozen_at",
        "comparison_matrix",
        "direct_series_matrix",
        "source_provider",
        "source_dataset",
        "source_access_mode",
        "source_url",
        "source_documentation_url",
        "source_structure_url",
        "source_terms_url",
        "access_cost",
        "credentials_required",
        "frequency",
        "measure",
        "history_semantics",
        "point_in_time_status",
        "historical_evidence_eligible",
        "min_rows_per_series",
        "min_overlap_rows",
        "min_change_correlation",
        "min_sign_agreement",
        "max_mean_absolute_change_gap_pp",
        "rolling_window_months",
        "independence_dimensions",
        "lineage_assessment",
        "automatic_promotion_authorized",
        "production_status",
    )
    return {key: record.get(key) for key in keys}


def freeze_cross_provider_triangulation(
    direct_reconciliation: Any,
    *,
    created_at: str | None = None,
) -> CrossProviderTriangulationRecord:
    """Freeze thresholds, mappings and inference boundaries before OECD access."""
    source = _row(direct_reconciliation)
    if str(source.get("protocol_version") or "") != "SRB_DIRECT_BIS_RECONCILIATION_V1":
        raise ValueError("A governed Phase 6.6 direct BIS reconciliation is required.")
    if str(source.get("execution_status") or "") != "COMPLETE":
        raise ValueError("The direct BIS reconciliation must be complete before triangulation.")
    if str(source.get("source_integrity_status") or "") != "PASS" or str(source.get("coverage_status") or "") != "PASS":
        raise ValueError("The direct BIS snapshot must pass source-integrity and coverage gates.")
    if str(source.get("point_in_time_status") or "") != "NOT_POINT_IN_TIME" or source.get("historical_evidence_eligible") is not False:
        raise ValueError("The direct BIS revised-history boundary is not intact.")
    if source.get("automatic_promotion_authorized") is not False or str(source.get("production_status") or "") != "RESEARCH_ONLY":
        raise ValueError("The direct BIS research-only promotion lock is not intact.")
    direct_snapshot_id = str(source.get("direct_snapshot_id") or "").strip()
    direct_snapshot_fingerprint = str(source.get("direct_snapshot_fingerprint") or "").strip()
    if not direct_snapshot_id or not direct_snapshot_fingerprint:
        raise ValueError("The direct BIS reconciliation has no sealed snapshot.")
    series_matrix = _direct_series_matrix(source.get("series_matrix"))

    frozen_at = str(created_at or _now_iso())
    if _parse_instant(frozen_at) is None:
        raise ValueError("created_at must be an ISO-8601 timestamp with timezone.")
    base = CrossProviderTriangulationRecord(
        triangulation_id="",
        created_at=frozen_at,
        replication_id=str(source.get("replication_id") or ""),
        direct_reconciliation_id=str(source.get("reconciliation_id") or ""),
        direct_snapshot_id=direct_snapshot_id,
        direct_snapshot_fingerprint=direct_snapshot_fingerprint,
        protocol_frozen_at=frozen_at,
        protocol_fingerprint="",
        comparison_matrix={key: dict(value) for key, value in OECD_BIS_REAL_MATRIX.items()},
        direct_series_matrix=series_matrix,
        lifecycle_history=({
            "at": frozen_at,
            "event": "CROSS_PROVIDER_PROTOCOL_FROZEN_BEFORE_NETWORK",
            "status": "FROZEN",
            "execution_status": "NOT_RUN",
            "historical_evidence_eligible": False,
            "production_status": "RESEARCH_ONLY",
        },),
    )
    fingerprint = _digest(_protocol_payload(asdict(base)))
    identity = _stable_id(
        "CPT",
        base.replication_id,
        base.direct_snapshot_fingerprint,
        frozen_at,
        fingerprint,
    )
    return replace(base, triangulation_id=identity, protocol_fingerprint=fingerprint)


def download_oecd_reer_csv(
    *,
    request_get: Callable[..., Any] = requests.get,
) -> OecdCsvPayload:
    """Download the exact bounded OECD SDMX query with no key or credential."""
    response = request_get(
        OECD_SOURCE_URL,
        headers={"User-Agent": OECD_USER_AGENT, "Accept": "text/csv,application/vnd.sdmx.data+csv"},
        timeout=(10, 90),
        stream=True,
    )
    try:
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            raise CrossProviderDataError(f"OECD SDMX download failed with HTTP {status}.")
        headers = getattr(response, "headers", {}) or {}
        declared = str(headers.get("Content-Length") or "").strip()
        if declared:
            try:
                if int(declared) > OECD_MAX_CSV_BYTES:
                    raise CrossProviderDataError("OECD CSV exceeds the bounded download limit.")
            except ValueError as exc:
                raise CrossProviderDataError("OECD response Content-Length is invalid.") from exc
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=131_072):
            if not chunk:
                continue
            size += len(chunk)
            if size > OECD_MAX_CSV_BYTES:
                raise CrossProviderDataError("OECD CSV exceeds the bounded download limit.")
            chunks.append(bytes(chunk))
        raw = b"".join(chunks)
        if not raw:
            raise CrossProviderDataError("OECD SDMX response is empty.")
        metadata = {
            "content_type": str(headers.get("Content-Type") or ""),
            "content_length": str(headers.get("Content-Length") or ""),
            "etag": str(headers.get("ETag") or ""),
            "last_modified": str(headers.get("Last-Modified") or ""),
            "date": str(headers.get("Date") or ""),
        }
        return OecdCsvPayload(raw_csv=raw, retrieved_at=_now_iso(), response_metadata=metadata)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def parse_oecd_reer_csv(
    raw_csv: bytes,
    comparison_matrix: Mapping[str, Mapping[str, str]] = OECD_BIS_REAL_MATRIX,
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Parse and validate only the three frozen monthly CPI-based REER series."""
    raw = bytes(raw_csv)
    if not raw or len(raw) > OECD_MAX_CSV_BYTES:
        raise CrossProviderDataError("OECD CSV is empty or exceeds the bounded download limit.")
    matrix = _comparison_matrix(comparison_matrix)
    area_to_market = {item["oecd_ref_area"]: market for market, item in matrix.items()}
    expected_fields = {
        "STRUCTURE", "STRUCTURE_ID", "ACTION", "REF_AREA", "FREQ", "MEASURE",
        "UNIT_MEASURE", "ACTIVITY", "ADJUSTMENT", "TRANSFORMATION", "TIME_HORIZ",
        "METHODOLOGY", "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "UNIT_MULT",
        "DECIMALS", "BASE_PER",
    }
    rows: dict[str, list[dict[str, Any]]] = {market: [] for market in matrix}
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    except UnicodeDecodeError as exc:
        raise CrossProviderDataError("OECD CSV is not valid UTF-8.") from exc
    if not reader.fieldnames or not expected_fields.issubset(set(reader.fieldnames)):
        raise CrossProviderDataError("OECD SDMX CSV schema is incomplete or changed.")
    for source in reader:
        area = str(source.get("REF_AREA") or "").strip().upper()
        market = area_to_market.get(area)
        if market is None:
            raise CrossProviderDataError(f"OECD response contains an undeclared reference area: {area or 'MISSING'}.")
        exact_codes = {
            "STRUCTURE": "DATAFLOW",
            "STRUCTURE_ID": OECD_EXPECTED_STRUCTURE_ID,
            "ACTION": "I",
            "FREQ": "M",
            "MEASURE": "CCRE",
            "UNIT_MEASURE": "IX",
            "ACTIVITY": "_Z",
            "ADJUSTMENT": "_Z",
            "TRANSFORMATION": "_Z",
            "TIME_HORIZ": "_Z",
            "METHODOLOGY": "N",
            "OBS_STATUS": "A",
            "UNIT_MULT": "0",
        }
        for field, expected in exact_codes.items():
            actual = str(source.get(field) or "").strip()
            if actual != expected:
                raise CrossProviderDataError(
                    f"OECD {field} changed for {area}: expected {expected}, observed {actual or 'MISSING'}."
                )
        period = str(source.get("TIME_PERIOD") or "").strip()
        base_period = str(source.get("BASE_PER") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise CrossProviderDataError(f"OECD monthly period is invalid for {area}: {period or 'MISSING'}.")
        if not re.fullmatch(r"\d{4}(?:-\d{2})?", base_period):
            raise CrossProviderDataError(f"OECD base period is invalid for {area}: {base_period or 'MISSING'}.")
        try:
            canonical_period = date(int(period[:4]), int(period[5:7]), 1).isoformat()
            value = float(str(source.get("OBS_VALUE") or ""))
            decimals = int(str(source.get("DECIMALS") or ""))
        except Exception as exc:
            raise CrossProviderDataError(f"OECD value metadata is invalid for {area} {period}.") from exc
        if not math.isfinite(value) or value <= 0:
            raise CrossProviderDataError(f"OECD value is non-positive or non-finite for {area} {period}.")
        if decimals < 0 or decimals > 12:
            raise CrossProviderDataError(f"OECD decimal metadata is invalid for {area} {period}.")
        rows[market].append({
            "period_start_date": canonical_period,
            "value": round(value, 12),
            "observation_status": "A",
            "ref_area": area,
            "measure": "CCRE",
            "methodology": "N",
            "base_period": base_period,
        })

    base_periods: set[str] = set()
    for market, series_rows in rows.items():
        series_rows.sort(key=lambda item: str(item["period_start_date"]))
        periods = [str(item["period_start_date"]) for item in series_rows]
        if not series_rows:
            raise CrossProviderDataError(f"OECD response contains no declared rows for {market}.")
        if len(periods) != len(set(periods)):
            raise CrossProviderDataError(f"OECD response contains duplicate monthly rows for {market}.")
        for prior, current in zip(periods, periods[1:]):
            prior_month = int(prior[:4]) * 12 + int(prior[5:7])
            current_month = int(current[:4]) * 12 + int(current[5:7])
            if current_month - prior_month != 1:
                raise CrossProviderDataError(f"OECD monthly coverage is discontinuous for {market}: {prior} -> {current}.")
        area_values = {str(item["ref_area"]) for item in series_rows}
        if area_values != {matrix[market]["oecd_ref_area"]}:
            raise CrossProviderDataError(f"OECD reference-area identity changed for {market}.")
        base_periods.update(str(item["base_period"]) for item in series_rows)
    if len(base_periods) != 1:
        raise CrossProviderDataError("OECD series do not share one explicit base period.")
    return rows, next(iter(base_periods))


def _persist_oecd_snapshot(
    data_root: str | os.PathLike[str],
    payload: OecdCsvPayload,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    base_period: str,
) -> tuple[str, str, str, str, dict[str, dict[str, Any]]]:
    root = Path(data_root)
    base = root / "public_data" / "oecd_reer_current_history"
    base.mkdir(parents=True, exist_ok=True)
    raw_sha = _sha256_bytes(payload.raw_csv)
    series_manifest: dict[str, dict[str, Any]] = {}
    for market, series_rows in sorted(rows.items()):
        canonical_rows = [dict(item) for item in series_rows]
        series_manifest[market] = {
            "row_count": len(canonical_rows),
            "observation_start": canonical_rows[0]["period_start_date"],
            "observation_end": canonical_rows[-1]["period_start_date"],
            "row_fingerprint": _digest(canonical_rows),
            "ref_area": canonical_rows[0]["ref_area"],
            "base_period": base_period,
        }
    snapshot_fingerprint = _digest({
        "source_url": OECD_SOURCE_URL,
        "history_semantics": OECD_HISTORY_SEMANTICS,
        "raw_csv_sha256": raw_sha,
        "series": series_manifest,
    })
    snapshot_id = f"OECDCCRE-{snapshot_fingerprint.split(':', 1)[1][:16]}"
    target = base / snapshot_id
    manifest = {
        "snapshot_id": snapshot_id,
        "snapshot_fingerprint": snapshot_fingerprint,
        "source_provider": "Organisation for Economic Co-operation and Development",
        "source_dataset": "OECD Financial market (DF_FINMARK 4.0) — CPI-based real effective exchange rates",
        "source_url": OECD_SOURCE_URL,
        "source_documentation_url": OECD_API_DOCUMENTATION_URL,
        "source_structure_url": OECD_STRUCTURE_URL,
        "source_terms_url": OECD_TERMS_URL,
        "access_cost": "FREE",
        "credentials_required": False,
        "history_semantics": OECD_HISTORY_SEMANTICS,
        "point_in_time_status": "NOT_POINT_IN_TIME",
        "historical_evidence_eligible": False,
        "retrieved_at": payload.retrieved_at,
        "raw_csv_sha256": raw_sha,
        "raw_csv_bytes": len(payload.raw_csv),
        "response_metadata": dict(payload.response_metadata),
        "base_period": base_period,
        "series": series_manifest,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }
    temp_dir: Path | None = Path(tempfile.mkdtemp(prefix=".oecd-reer-", dir=str(base)))
    try:
        assert temp_dir is not None
        (temp_dir / "oecd_finmark_ccre.csv").write_bytes(payload.raw_csv)
        fieldnames = (
            "period_start_date", "value", "observation_status", "ref_area",
            "measure", "methodology", "base_period",
        )
        for market, series_rows in sorted(rows.items()):
            with (temp_dir / f"{market}_canonical.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(dict(item) for item in series_rows)
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            existing_path = target / "manifest.json"
            if not existing_path.is_file():
                raise CrossProviderDataError(f"Existing OECD snapshot directory is incomplete: {snapshot_id}")
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            if (
                str(existing.get("snapshot_fingerprint") or "") != snapshot_fingerprint
                or str(existing.get("raw_csv_sha256") or "") != raw_sha
            ):
                raise CrossProviderDataError(f"OECD snapshot identity collision detected: {snapshot_id}")
        else:
            os.replace(temp_dir, target)
            temp_dir = None
    finally:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir)
    return snapshot_id, snapshot_fingerprint, str(target.relative_to(root)), raw_sha, series_manifest


def load_persisted_oecd_snapshot(
    data_root: str | os.PathLike[str],
    snapshot_id: str,
    *,
    comparison_matrix: Mapping[str, Mapping[str, str]] = OECD_BIS_REAL_MATRIX,
    expected_fingerprint: str = "",
) -> dict[str, Any]:
    """Reload and revalidate raw and canonical bytes of a sealed OECD snapshot."""
    identity = str(snapshot_id or "").strip()
    if not re.fullmatch(r"OECDCCRE-[0-9a-f]{16}", identity):
        raise CrossProviderDataError("Persisted OECD snapshot_id is invalid.")
    matrix = _comparison_matrix(comparison_matrix)
    root = Path(data_root).resolve()
    base = (root / "public_data" / "oecd_reer_current_history").resolve()
    target = (base / identity).resolve()
    if target.parent != base or not target.is_dir():
        raise CrossProviderDataError(f"Persisted OECD snapshot is missing: {identity}")
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 1_000_000:
        raise CrossProviderDataError("Persisted OECD manifest is missing or oversized.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CrossProviderDataError("Persisted OECD manifest is invalid JSON.") from exc
    if not isinstance(manifest, dict) or str(manifest.get("snapshot_id") or "") != identity:
        raise CrossProviderDataError("Persisted OECD snapshot identity is inconsistent.")
    if str(manifest.get("history_semantics") or "") != OECD_HISTORY_SEMANTICS:
        raise CrossProviderDataError("Persisted OECD revised-history semantics changed.")
    if str(manifest.get("point_in_time_status") or "") != "NOT_POINT_IN_TIME":
        raise CrossProviderDataError("Persisted OECD snapshot is overstated as point-in-time.")
    if manifest.get("historical_evidence_eligible") is not False:
        raise CrossProviderDataError("Persisted OECD snapshot is incorrectly eligible as historical evidence.")
    if manifest.get("automatic_promotion_authorized") is not False or str(manifest.get("production_status") or "") != "RESEARCH_ONLY":
        raise CrossProviderDataError("Persisted OECD snapshot lost its research-only promotion lock.")
    series_manifest = manifest.get("series")
    if not isinstance(series_manifest, dict) or set(series_manifest) != set(matrix):
        raise CrossProviderDataError("Persisted OECD manifest does not exactly cover the frozen matrix.")
    raw_path = target / "oecd_finmark_ccre.csv"
    if not raw_path.is_file() or raw_path.stat().st_size > OECD_MAX_CSV_BYTES:
        raise CrossProviderDataError("Persisted OECD raw CSV is missing or oversized.")
    raw = raw_path.read_bytes()
    raw_sha = _sha256_bytes(raw)
    if raw_sha != str(manifest.get("raw_csv_sha256") or ""):
        raise CrossProviderDataError("Persisted OECD raw CSV fingerprint mismatch.")
    if len(raw) != int(manifest.get("raw_csv_bytes") or -1):
        raise CrossProviderDataError("Persisted OECD raw CSV byte count mismatch.")
    parsed_rows, base_period = parse_oecd_reer_csv(raw, matrix)
    if base_period != str(manifest.get("base_period") or ""):
        raise CrossProviderDataError("Persisted OECD base-period metadata mismatch.")
    verified_manifest: dict[str, dict[str, Any]] = {}
    expected_fieldnames = [
        "period_start_date", "value", "observation_status", "ref_area",
        "measure", "methodology", "base_period",
    ]
    for market, parsed in sorted(parsed_rows.items()):
        metadata = series_manifest.get(market)
        if not isinstance(metadata, Mapping):
            raise CrossProviderDataError(f"Persisted OECD metadata is malformed for {market}.")
        parsed_fingerprint = _digest(parsed)
        if parsed_fingerprint != str(metadata.get("row_fingerprint") or ""):
            raise CrossProviderDataError(f"Persisted OECD raw row fingerprint mismatch for {market}.")
        if (
            len(parsed) != int(metadata.get("row_count") or -1)
            or parsed[0]["period_start_date"] != str(metadata.get("observation_start") or "")
            or parsed[-1]["period_start_date"] != str(metadata.get("observation_end") or "")
            or parsed[0]["ref_area"] != str(metadata.get("ref_area") or "")
            or base_period != str(metadata.get("base_period") or "")
        ):
            raise CrossProviderDataError(f"Persisted OECD series inventory mismatch for {market}.")
        canonical_path = target / f"{market}_canonical.csv"
        if not canonical_path.is_file() or canonical_path.stat().st_size > 5_000_000:
            raise CrossProviderDataError(f"Persisted OECD canonical file is missing or oversized for {market}.")
        canonical: list[dict[str, Any]] = []
        try:
            with canonical_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != expected_fieldnames:
                    raise CrossProviderDataError(f"Persisted OECD canonical schema changed for {market}.")
                for source in reader:
                    canonical.append({
                        "period_start_date": str(source.get("period_start_date") or ""),
                        "value": round(float(str(source.get("value") or "")), 12),
                        "observation_status": str(source.get("observation_status") or ""),
                        "ref_area": str(source.get("ref_area") or ""),
                        "measure": str(source.get("measure") or ""),
                        "methodology": str(source.get("methodology") or ""),
                        "base_period": str(source.get("base_period") or ""),
                    })
        except CrossProviderDataError:
            raise
        except Exception as exc:
            raise CrossProviderDataError(f"Persisted OECD canonical rows are invalid for {market}.") from exc
        if canonical != parsed or _digest(canonical) != parsed_fingerprint:
            raise CrossProviderDataError(f"Persisted OECD canonical content mismatch for {market}.")
        verified_manifest[market] = dict(metadata)
    snapshot_fingerprint = _digest({
        "source_url": OECD_SOURCE_URL,
        "history_semantics": OECD_HISTORY_SEMANTICS,
        "raw_csv_sha256": raw_sha,
        "series": verified_manifest,
    })
    if snapshot_fingerprint != str(manifest.get("snapshot_fingerprint") or ""):
        raise CrossProviderDataError("Persisted OECD snapshot fingerprint mismatch.")
    if expected_fingerprint and snapshot_fingerprint != str(expected_fingerprint):
        raise CrossProviderDataError("Persisted OECD snapshot does not match the expected fingerprint.")
    return {
        "snapshot_id": identity,
        "snapshot_fingerprint": snapshot_fingerprint,
        "manifest": manifest,
        "rows": parsed_rows,
        "base_period": base_period,
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    left_delta = [value - left_mean for value in left]
    right_delta = [value - right_mean for value in right]
    denominator = math.sqrt(
        sum(value * value for value in left_delta)
        * sum(value * value for value in right_delta)
    )
    if denominator <= 0:
        return None
    return sum(a * b for a, b in zip(left_delta, right_delta)) / denominator


def _monthly_change_rows(
    periods: Sequence[str],
    bis_values: Mapping[str, float],
    oecd_values: Mapping[str, float],
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for prior, current in zip(periods, periods[1:]):
        prior_month = int(prior[:4]) * 12 + int(prior[5:7])
        current_month = int(current[:4]) * 12 + int(current[5:7])
        if current_month - prior_month != 1:
            continue
        bis_change = 100.0 * math.log(float(bis_values[current]) / float(bis_values[prior]))
        oecd_change = 100.0 * math.log(float(oecd_values[current]) / float(oecd_values[prior]))
        gap = oecd_change - bis_change
        changes.append({
            "period_start_date": current,
            "bis_log_change_pct": round(bis_change, 12),
            "oecd_log_change_pct": round(oecd_change, 12),
            "change_gap_pp": round(gap, 12),
            "absolute_change_gap_pp": round(abs(gap), 12),
            "same_direction": (
                None
                if bis_change == 0.0 or oecd_change == 0.0
                else (bis_change > 0.0) == (oecd_change > 0.0)
            ),
        })
    return changes


def _series_diagnostic(
    *,
    market: str,
    metadata: Mapping[str, str],
    bis_rows: Sequence[Mapping[str, Any]],
    oecd_rows: Sequence[Mapping[str, Any]],
    record: CrossProviderTriangulationRecord,
) -> dict[str, Any]:
    bis_values = {str(row.get("period_start_date") or ""): float(row.get("value")) for row in bis_rows}
    oecd_values = {str(row.get("period_start_date") or ""): float(row.get("value")) for row in oecd_rows}
    overlap = sorted(set(bis_values).intersection(oecd_values))
    base = {
        "market": market,
        "market_label": metadata["label"],
        "bis_series_id": metadata["bis_series_id"],
        "oecd_ref_area": metadata["oecd_ref_area"],
        "lineage_assessment": metadata["lineage_assessment"],
        "bis_row_count": len(bis_rows),
        "oecd_row_count": len(oecd_rows),
        "overlap_row_count": len(overlap),
        "history_semantics": OECD_HISTORY_SEMANTICS,
        "historical_evidence_eligible": False,
    }
    if len(overlap) < record.min_overlap_rows:
        return base | {
            "status": "NOT_COMPARABLE",
            "blockers": [
                f"Only {len(overlap)} overlapping monthly levels; {record.min_overlap_rows} required."
            ],
            "comparison_fingerprint": _digest(base | {"overlap": overlap}),
            "change_rows": [],
        }
    change_rows = _monthly_change_rows(overlap, bis_values, oecd_values)
    if len(change_rows) < record.min_overlap_rows - 1:
        return base | {
            "status": "NOT_COMPARABLE",
            "blockers": ["The overlapping histories do not provide enough consecutive monthly changes."],
            "comparison_fingerprint": _digest(base | {"overlap": overlap, "changes": change_rows}),
            "change_rows": change_rows,
        }
    bis_changes = [float(row["bis_log_change_pct"]) for row in change_rows]
    oecd_changes = [float(row["oecd_log_change_pct"]) for row in change_rows]
    correlation = _pearson(bis_changes, oecd_changes)
    directions = [bool(row["same_direction"]) for row in change_rows if row["same_direction"] is not None]
    if correlation is None or not directions:
        return base | {
            "status": "NOT_COMPARABLE",
            "blockers": ["Monthly changes have zero variance or no directionally comparable observations."],
            "comparison_fingerprint": _digest(base | {"changes": change_rows}),
            "change_rows": change_rows,
        }
    absolute_gaps = [float(row["absolute_change_gap_pp"]) for row in change_rows]
    rolling_correlations: list[float] = []
    window = int(record.rolling_window_months)
    for end in range(window, len(change_rows) + 1):
        value = _pearson(bis_changes[end - window:end], oecd_changes[end - window:end])
        if value is not None:
            rolling_correlations.append(value)
    sign_agreement = sum(directions) / len(directions)
    mean_absolute_gap = statistics.fmean(absolute_gaps)
    checks = {
        "change_correlation": correlation >= record.min_change_correlation,
        "sign_agreement": sign_agreement >= record.min_sign_agreement,
        "mean_absolute_change_gap": mean_absolute_gap <= record.max_mean_absolute_change_gap_pp,
    }
    status = "CONCORDANT" if all(checks.values()) else "MEASUREMENT_DIVERGENCE"
    first = overlap[0]
    bis_scale = 100.0 / bis_values[first]
    oecd_scale = 100.0 / oecd_values[first]
    rebased_level_gaps = [
        (oecd_values[period] * oecd_scale) - (bis_values[period] * bis_scale)
        for period in overlap
    ]
    result = base | {
        "status": status,
        "blockers": [],
        "overlap_start": overlap[0],
        "overlap_end": overlap[-1],
        "monthly_change_count": len(change_rows),
        "change_correlation": round(correlation, 12),
        "sign_agreement": round(sign_agreement, 12),
        "mean_absolute_change_gap_pp": round(mean_absolute_gap, 12),
        "median_absolute_change_gap_pp": round(statistics.median(absolute_gaps), 12),
        "max_absolute_change_gap_pp": round(max(absolute_gaps), 12),
        "mean_signed_change_gap_pp": round(statistics.fmean(
            float(row["change_gap_pp"]) for row in change_rows
        ), 12),
        "rolling_window_months": window,
        "rolling_correlation_count": len(rolling_correlations),
        "rolling_correlation_median": (
            round(statistics.median(rolling_correlations), 12) if rolling_correlations else None
        ),
        "rolling_correlation_min": round(min(rolling_correlations), 12) if rolling_correlations else None,
        "mean_absolute_rebased_level_gap": round(statistics.fmean(map(abs, rebased_level_gaps)), 12),
        "threshold_checks": checks,
        "thresholds": {
            "min_change_correlation": record.min_change_correlation,
            "min_sign_agreement": record.min_sign_agreement,
            "max_mean_absolute_change_gap_pp": record.max_mean_absolute_change_gap_pp,
        },
        "change_rows": change_rows,
    }
    result["comparison_fingerprint"] = _digest(result)
    return result


def execute_cross_provider_triangulation(
    protocol: Any,
    *,
    data_root: str | os.PathLike[str],
    csv_fetcher: Callable[[], OecdCsvPayload | bytes] | None = None,
    direct_loader: Callable[..., Mapping[str, Any]] | None = None,
) -> CrossProviderTriangulationRecord:
    """Acquire OECD data, seal it and compare monthly changes with sealed BIS rows."""
    record = _record(protocol)
    if record.protocol_version != CROSS_PROVIDER_PROTOCOL_VERSION:
        raise ValueError("Unsupported cross-provider triangulation protocol version.")
    if record.status != "FROZEN" or record.execution_status != "NOT_RUN":
        raise ValueError("Only a persisted, unexecuted FROZEN cross-provider protocol may run.")
    if _digest(_protocol_payload(asdict(record))) != record.protocol_fingerprint:
        raise ValueError("Cross-provider protocol fingerprint mismatch; acquisition refused.")
    if record.history_semantics != OECD_HISTORY_SEMANTICS:
        raise ValueError("Cross-provider revised-history semantics are not intact.")
    if record.point_in_time_status != "NOT_POINT_IN_TIME" or record.historical_evidence_eligible:
        raise ValueError("Cross-provider revised histories cannot be treated as point-in-time evidence.")
    if record.automatic_promotion_authorized or record.production_status != "RESEARCH_ONLY":
        raise ValueError("Cross-provider production/promotion lock is not intact.")
    matrix = _comparison_matrix(record.comparison_matrix)
    direct_matrix = _direct_series_matrix(record.direct_series_matrix)
    if len(matrix) != record.expected_series_count:
        raise ValueError("Frozen cross-provider expected series count is inconsistent.")

    loader = direct_loader or load_persisted_direct_bis_snapshot
    direct = loader(
        data_root,
        record.direct_snapshot_id,
        series_matrix=direct_matrix,
        expected_fingerprint=record.direct_snapshot_fingerprint,
    )
    direct_rows = direct.get("rows") if isinstance(direct, Mapping) else None
    if not isinstance(direct_rows, Mapping):
        raise CrossProviderDataError("The sealed direct BIS snapshot could not be reloaded.")

    fetched = csv_fetcher() if csv_fetcher is not None else download_oecd_reer_csv()
    payload = (
        fetched
        if isinstance(fetched, OecdCsvPayload)
        else OecdCsvPayload(raw_csv=bytes(fetched), retrieved_at=_now_iso(), response_metadata={})
    )
    if _parse_instant(payload.retrieved_at) is None:
        raise CrossProviderDataError("OECD retrieval timestamp is missing its timezone.")
    oecd_rows, base_period = parse_oecd_reer_csv(payload.raw_csv, matrix)
    for market, rows in oecd_rows.items():
        if len(rows) < record.min_rows_per_series:
            raise CrossProviderDataError(
                f"OECD series {market} has only {len(rows)} monthly rows; {record.min_rows_per_series} required."
            )
    snapshot_id, snapshot_fingerprint, snapshot_path, raw_sha, _ = _persist_oecd_snapshot(
        data_root,
        payload,
        oecd_rows,
        base_period,
    )
    verified = load_persisted_oecd_snapshot(
        data_root,
        snapshot_id,
        comparison_matrix=matrix,
        expected_fingerprint=snapshot_fingerprint,
    )
    oecd_rows = verified["rows"]

    results: list[dict[str, Any]] = []
    for market, metadata in sorted(matrix.items()):
        bis_series_id = metadata["bis_series_id"]
        series = direct_rows.get(bis_series_id)
        if not isinstance(series, Sequence):
            raise CrossProviderDataError(f"The sealed BIS snapshot is missing {bis_series_id}.")
        results.append(_series_diagnostic(
            market=market,
            metadata=metadata,
            bis_rows=series,
            oecd_rows=oecd_rows[market],
            record=record,
        ))
    comparable = [row for row in results if str(row.get("status")) != "NOT_COMPARABLE"]
    concordant = [row for row in comparable if str(row.get("status")) == "CONCORDANT"]
    divergent = [row for row in comparable if str(row.get("status")) == "MEASUREMENT_DIVERGENCE"]
    if len(comparable) != len(results):
        outcome = "NOT_COMPARABLE"
        comparability_status = "FAIL"
    elif divergent:
        outcome = "MEASUREMENT_DIVERGENCE"
        comparability_status = "PASS"
    else:
        outcome = "CONCORDANT"
        comparability_status = "PASS"
    latest_period = max(rows[-1]["period_start_date"] for rows in oecd_rows.values())
    triangulation_fingerprint = _digest({
        "protocol_fingerprint": record.protocol_fingerprint,
        "direct_snapshot_fingerprint": record.direct_snapshot_fingerprint,
        "oecd_snapshot_fingerprint": snapshot_fingerprint,
        "series_results": results,
        "triangulation_outcome": outcome,
        "history_semantics": OECD_HISTORY_SEMANTICS,
    })
    completed_at = _now_iso()
    blockers = tuple(
        f"{row.get('market')}: {item}"
        for row in results
        for item in (row.get("blockers") or ())
    )
    return replace(
        record,
        status="COMPLETE",
        execution_status="COMPLETE",
        completed_at=completed_at,
        source_integrity_status="PASS",
        coverage_status="PASS",
        comparability_status=comparability_status,
        triangulation_outcome=outcome,
        oecd_snapshot_id=snapshot_id,
        oecd_snapshot_path=snapshot_path,
        oecd_snapshot_fingerprint=snapshot_fingerprint,
        raw_csv_sha256=raw_sha,
        raw_csv_bytes=len(payload.raw_csv),
        retrieved_at=payload.retrieved_at,
        response_metadata=dict(payload.response_metadata),
        base_period=base_period,
        latest_period=latest_period,
        source_series_count=len(results),
        comparable_series_count=len(comparable),
        concordant_series_count=len(concordant),
        divergent_series_count=len(divergent),
        series_results=tuple(results),
        triangulation_fingerprint=triangulation_fingerprint,
        blockers=blockers,
        lifecycle_history=record.lifecycle_history + ({
            "at": completed_at,
            "event": "OECD_BIS_CROSS_PROVIDER_TRIANGULATION_COMPLETE",
            "status": "COMPLETE",
            "execution_status": "COMPLETE",
            "source_integrity_status": "PASS",
            "coverage_status": "PASS",
            "comparability_status": comparability_status,
            "triangulation_outcome": outcome,
            "oecd_snapshot_id": snapshot_id,
            "oecd_snapshot_fingerprint": snapshot_fingerprint,
            "historical_evidence_eligible": False,
            "production_status": "RESEARCH_ONLY",
        },),
    )


__all__ = [
    "CROSS_PROVIDER_PROTOCOL_VERSION",
    "CrossProviderDataError",
    "OECD_API_DOCUMENTATION_URL",
    "OECD_BIS_REAL_MATRIX",
    "OECD_HISTORY_SEMANTICS",
    "OECD_SOURCE_URL",
    "OECD_STRUCTURE_URL",
    "OECD_TERMS_URL",
    "OecdCsvPayload",
    "download_oecd_reer_csv",
    "execute_cross_provider_triangulation",
    "freeze_cross_provider_triangulation",
    "load_persisted_oecd_snapshot",
    "parse_oecd_reer_csv",
]
