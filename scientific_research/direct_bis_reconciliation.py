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
import zipfile
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

import requests

from .phase66_models import DirectSourceReconciliationRecord
from .replication_engine import load_persisted_alfred_snapshot_bundle


DIRECT_BIS_PROTOCOL_VERSION = "SRB_DIRECT_BIS_RECONCILIATION_V1"
DIRECT_BIS_SOURCE_URL = "https://data.bis.org/static/bulk/WS_EER_csv_flat.zip"
DIRECT_BIS_EXPORT_HELP_URL = "https://data.bis.org/help/export"
DIRECT_BIS_TERMS_URL = "https://data.bis.org/help/legal"
DIRECT_BIS_TOPIC_URL = "https://data.bis.org/topics/EER?lang=en"
DIRECT_BIS_ACCESS_MODE = "PUBLIC_BIS_BULK_CSV_FLAT_ZIP"
DIRECT_BIS_HISTORY_SEMANTICS = "CURRENT_REVISED_HISTORY_NOT_A_VINTAGE_ARCHIVE"
DIRECT_BIS_MAX_ARCHIVE_BYTES = 20_000_000
DIRECT_BIS_MAX_UNCOMPRESSED_BYTES = 400_000_000
DIRECT_BIS_REQUIRED_MEMBER = "WS_EER_csv_flat.csv"
DIRECT_BIS_USER_AGENT = (
    "ScientificResearchBrain/0.6.6.1 research-only direct-source reconciliation; "
    "explicit public BIS bulk download; no unattended production use"
)


class DirectBisDataError(RuntimeError):
    """Raised when a direct BIS source artifact fails a governed gate."""


@dataclass(frozen=True)
class BisArchivePayload:
    raw_archive: bytes
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


def _record(value: Any) -> DirectSourceReconciliationRecord:
    if isinstance(value, DirectSourceReconciliationRecord):
        return value
    source = _row(value)
    allowed = {item.name for item in fields(DirectSourceReconciliationRecord)}
    return DirectSourceReconciliationRecord(**{key: source[key] for key in allowed if key in source})


def _series_matrix(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("A governed replication series matrix is required.")
    matrix: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for market, raw in sorted(value.items()):
        code = str(market or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", code) or not isinstance(raw, Mapping):
            raise ValueError("The direct BIS series matrix is malformed.")
        real_id = str(raw.get("real_series_id") or "").strip().upper()
        nominal_id = str(raw.get("nominal_series_id") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9]{3,20}", real_id) or not re.fullmatch(r"[A-Z0-9]{3,20}", nominal_id):
            raise ValueError(f"The direct BIS series IDs are invalid for {code}.")
        if real_id == nominal_id or real_id in seen or nominal_id in seen:
            raise ValueError("The direct BIS series matrix contains duplicate identities.")
        seen.update((real_id, nominal_id))
        matrix[code] = {
            "label": str(raw.get("label") or code).strip(),
            "real_series_id": real_id,
            "nominal_series_id": nominal_id,
        }
    return matrix


def _protocol_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "protocol_version",
        "replication_id",
        "reference_snapshot_id",
        "reference_snapshot_fingerprint",
        "protocol_frozen_at",
        "series_matrix",
        "source_provider",
        "source_dataset",
        "source_access_mode",
        "source_url",
        "source_documentation_url",
        "source_terms_url",
        "access_cost",
        "credentials_required",
        "frequency",
        "basket",
        "history_semantics",
        "point_in_time_status",
        "historical_evidence_eligible",
        "min_rows_per_series",
        "min_overlap_rows",
        "equality_tolerance",
        "prospective_min_distinct_snapshots",
        "prospective_min_distinct_latest_periods",
        "prospective_min_span_days",
        "independence_dimensions",
        "automatic_promotion_authorized",
        "production_status",
    )
    return {key: record.get(key) for key in keys}


def freeze_direct_bis_reconciliation(
    replication: Any,
    *,
    created_at: str | None = None,
) -> DirectSourceReconciliationRecord:
    """Freeze one explicit as-observed BIS acquisition before network access."""
    source = _row(replication)
    if str(source.get("protocol_version") or "") != "SRB_INDEPENDENT_REPLICATION_V1":
        raise ValueError("A governed independent replication is required.")
    if str(source.get("execution_status") or "") != "COMPLETE":
        raise ValueError("The independent replication must be complete before direct-source reconciliation.")
    if str(source.get("point_in_time_status") or "") != "PASS":
        raise ValueError("The reference replication must preserve its point-in-time PASS status.")
    if not str(source.get("snapshot_id") or "") or not str(source.get("source_snapshot_fingerprint") or ""):
        raise ValueError("The reference replication has no sealed source snapshot.")
    if source.get("automatic_promotion_authorized") is not False or str(source.get("production_status") or "") != "RESEARCH_ONLY":
        raise ValueError("The reference replication lost its research-only promotion lock.")

    frozen_at = str(created_at or _now_iso())
    try:
        parsed = datetime.fromisoformat(frozen_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("created_at must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError("created_at must include a timezone.")
    matrix = _series_matrix(source.get("series_matrix"))
    base = DirectSourceReconciliationRecord(
        reconciliation_id="",
        created_at=frozen_at,
        replication_id=str(source.get("replication_id") or ""),
        reference_snapshot_id=str(source.get("snapshot_id") or ""),
        reference_snapshot_fingerprint=str(source.get("source_snapshot_fingerprint") or ""),
        protocol_frozen_at=frozen_at,
        protocol_fingerprint="",
        series_matrix=matrix,
        expected_series_count=len(matrix) * 2,
        lifecycle_history=({
            "at": frozen_at,
            "event": "DIRECT_BIS_PROTOCOL_FROZEN_BEFORE_NETWORK",
            "status": "FROZEN",
            "execution_status": "NOT_RUN",
            "historical_evidence_eligible": False,
            "production_status": "RESEARCH_ONLY",
        },),
    )
    payload = _protocol_payload(asdict(base))
    fingerprint = _digest(payload)
    identity = _stable_id(
        "DBR",
        base.replication_id,
        base.reference_snapshot_fingerprint,
        frozen_at,
        fingerprint,
    )
    return replace(base, reconciliation_id=identity, protocol_fingerprint=fingerprint)


def download_bis_eer_archive(
    *,
    request_get: Callable[..., Any] = requests.get,
) -> BisArchivePayload:
    """Download the public BIS EER bulk archive with strict byte bounds."""
    response = request_get(
        DIRECT_BIS_SOURCE_URL,
        headers={"User-Agent": DIRECT_BIS_USER_AGENT, "Accept": "application/zip,application/octet-stream"},
        timeout=(10, 180),
        stream=True,
    )
    try:
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            raise DirectBisDataError(f"BIS bulk download failed with HTTP {status}.")
        headers = getattr(response, "headers", {}) or {}
        declared = str(headers.get("Content-Length") or "").strip()
        if declared:
            try:
                if int(declared) > DIRECT_BIS_MAX_ARCHIVE_BYTES:
                    raise DirectBisDataError("BIS bulk archive exceeds the compressed safety limit.")
            except ValueError as exc:
                raise DirectBisDataError("BIS response Content-Length is invalid.") from exc
        chunks: list[bytes] = []
        size = 0
        iterator = response.iter_content(chunk_size=262_144)
        for chunk in iterator:
            if not chunk:
                continue
            size += len(chunk)
            if size > DIRECT_BIS_MAX_ARCHIVE_BYTES:
                raise DirectBisDataError("BIS bulk archive exceeds the compressed safety limit.")
            chunks.append(bytes(chunk))
        raw = b"".join(chunks)
        if not raw:
            raise DirectBisDataError("BIS bulk archive is empty.")
        metadata = {
            "content_type": str(headers.get("Content-Type") or ""),
            "content_length": str(headers.get("Content-Length") or ""),
            "etag": str(headers.get("ETag") or ""),
            "last_modified": str(headers.get("Last-Modified") or ""),
            "date": str(headers.get("Date") or ""),
        }
        return BisArchivePayload(raw_archive=raw, retrieved_at=_now_iso(), response_metadata=metadata)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _code(value: Any) -> str:
    return str(value or "").split(":", 1)[0].strip().upper()


def parse_bis_eer_archive(
    raw_archive: bytes,
    series_matrix: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    """Stream the one official CSV member and retain only declared monthly series."""
    raw = bytes(raw_archive)
    if not raw or len(raw) > DIRECT_BIS_MAX_ARCHIVE_BYTES:
        raise DirectBisDataError("BIS bulk archive is empty or exceeds the compressed safety limit.")
    matrix = _series_matrix(series_matrix)
    targets: dict[tuple[str, str], str] = {}
    for market, metadata in matrix.items():
        targets[(market, "R")] = metadata["real_series_id"]
        targets[(market, "N")] = metadata["nominal_series_id"]
    rows: dict[str, list[dict[str, Any]]] = {series_id: [] for series_id in targets.values()}
    expected_fields = {
        "STRUCTURE",
        "STRUCTURE_ID",
        "ACTION",
        "FREQ:Frequency",
        "EER_TYPE:Type",
        "EER_BASKET:Basket",
        "REF_AREA:Reference area",
        "TIME_PERIOD:Time period or range",
        "OBS_VALUE:Observation Value",
        "COLLECTION:Collection Indicator",
        "TITLE_TS:Title (tseries level)",
        "OBS_STATUS:Observation Status",
    }
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            csv_members = [item for item in members if not item.is_dir() and item.filename.lower().endswith(".csv")]
            if len(members) != 1 or len(csv_members) != 1:
                raise DirectBisDataError("BIS bulk archive must contain exactly one CSV member.")
            member = csv_members[0]
            pure = PurePosixPath(member.filename)
            if pure.is_absolute() or ".." in pure.parts or member.filename != DIRECT_BIS_REQUIRED_MEMBER:
                raise DirectBisDataError("BIS bulk archive member path is unexpected or unsafe.")
            if member.file_size <= 0 or member.file_size > DIRECT_BIS_MAX_UNCOMPRESSED_BYTES:
                raise DirectBisDataError("BIS bulk CSV exceeds the uncompressed safety limit.")
            if archive.testzip() is not None:
                raise DirectBisDataError("BIS bulk archive failed its CRC check.")
            with archive.open(member, "r") as binary:
                reader = csv.DictReader(io.TextIOWrapper(binary, encoding="utf-8-sig", newline=""))
                if not reader.fieldnames or not expected_fields.issubset(set(reader.fieldnames)):
                    raise DirectBisDataError("BIS bulk CSV schema is incomplete or changed.")
                for source in reader:
                    if _code(source.get("FREQ:Frequency")) != "M":
                        continue
                    market = _code(source.get("REF_AREA:Reference area"))
                    kind = _code(source.get("EER_TYPE:Type"))
                    series_id = targets.get((market, kind))
                    if series_id is None or _code(source.get("EER_BASKET:Basket")) != "B":
                        continue
                    if str(source.get("STRUCTURE") or "").strip() != "dataflow":
                        raise DirectBisDataError(f"BIS structure changed for {series_id}.")
                    if not str(source.get("STRUCTURE_ID") or "").startswith("BIS:WS_EER(1.0):"):
                        raise DirectBisDataError(f"BIS dataset identity changed for {series_id}.")
                    if str(source.get("ACTION") or "").strip() != "I":
                        raise DirectBisDataError(f"BIS row action is not information for {series_id}.")
                    status = _code(source.get("OBS_STATUS:Observation Status"))
                    if status != "A":
                        raise DirectBisDataError(f"BIS observation status {status or 'MISSING'} is not normal for {series_id}.")
                    period = str(source.get("TIME_PERIOD:Time period or range") or "").strip()
                    if not re.fullmatch(r"\d{4}-\d{2}", period):
                        raise DirectBisDataError(f"BIS monthly period is invalid for {series_id}.")
                    try:
                        canonical_period = date(int(period[:4]), int(period[5:7]), 1).isoformat()
                        value = float(str(source.get("OBS_VALUE:Observation Value") or ""))
                    except Exception as exc:
                        raise DirectBisDataError(f"BIS value is invalid for {series_id} {period}.") from exc
                    if not math.isfinite(value) or value <= 0:
                        raise DirectBisDataError(f"BIS value is non-positive or non-finite for {series_id} {period}.")
                    rows[series_id].append({
                        "period_start_date": canonical_period,
                        "value": round(value, 12),
                        "observation_status": status,
                        "collection": str(source.get("COLLECTION:Collection Indicator") or "").strip(),
                        "title": str(source.get("TITLE_TS:Title (tseries level)") or "").strip(),
                    })
            uncompressed_bytes = int(member.file_size)
    except DirectBisDataError:
        raise
    except zipfile.BadZipFile as exc:
        raise DirectBisDataError("BIS response is not a valid ZIP archive.") from exc

    for series_id, series_rows in rows.items():
        series_rows.sort(key=lambda item: str(item["period_start_date"]))
        periods = [str(item["period_start_date"]) for item in series_rows]
        titles = {str(item["title"]) for item in series_rows}
        collections = {str(item["collection"]) for item in series_rows}
        if not series_rows:
            raise DirectBisDataError(f"BIS archive contains no declared rows for {series_id}.")
        if len(periods) != len(set(periods)):
            raise DirectBisDataError(f"BIS archive contains duplicate monthly rows for {series_id}.")
        if len(titles) != 1 or not next(iter(titles)):
            raise DirectBisDataError(f"BIS title metadata is inconsistent for {series_id}.")
        if collections != {"A: Average of observations through period"}:
            raise DirectBisDataError(f"BIS collection semantics changed for {series_id}.")
    return rows, uncompressed_bytes


def _persist_direct_snapshot(
    data_root: str | os.PathLike[str],
    payload: BisArchivePayload,
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    uncompressed_bytes: int,
) -> tuple[str, str, str, str, dict[str, dict[str, Any]]]:
    root = Path(data_root)
    base = root / "public_data" / "bis_revised_history"
    base.mkdir(parents=True, exist_ok=True)
    raw_sha = _sha256_bytes(payload.raw_archive)
    series_manifest: dict[str, dict[str, Any]] = {}
    for series_id, series_rows in sorted(rows.items()):
        canonical_rows = [dict(item) for item in series_rows]
        series_manifest[series_id] = {
            "row_count": len(canonical_rows),
            "observation_start": canonical_rows[0]["period_start_date"],
            "observation_end": canonical_rows[-1]["period_start_date"],
            "row_fingerprint": _digest(canonical_rows),
            "title": canonical_rows[0]["title"],
        }
    snapshot_fingerprint = _digest({
        "source_url": DIRECT_BIS_SOURCE_URL,
        "history_semantics": DIRECT_BIS_HISTORY_SEMANTICS,
        "raw_archive_sha256": raw_sha,
        "series": series_manifest,
    })
    snapshot_id = f"BISREV-{snapshot_fingerprint.split(':', 1)[1][:16]}"
    target = base / snapshot_id
    manifest = {
        "snapshot_id": snapshot_id,
        "snapshot_fingerprint": snapshot_fingerprint,
        "source_provider": "Bank for International Settlements",
        "source_dataset": "BIS Effective exchange rates (WS_EER 1.0)",
        "source_url": DIRECT_BIS_SOURCE_URL,
        "source_documentation_url": DIRECT_BIS_EXPORT_HELP_URL,
        "source_terms_url": DIRECT_BIS_TERMS_URL,
        "access_cost": "FREE",
        "credentials_required": False,
        "history_semantics": DIRECT_BIS_HISTORY_SEMANTICS,
        "point_in_time_status": "NOT_POINT_IN_TIME",
        "historical_evidence_eligible": False,
        "retrieved_at": payload.retrieved_at,
        "raw_archive_sha256": raw_sha,
        "raw_archive_bytes": len(payload.raw_archive),
        "raw_csv_bytes": int(uncompressed_bytes),
        "response_metadata": dict(payload.response_metadata),
        "series": series_manifest,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }
    temp_dir: Path | None = Path(tempfile.mkdtemp(prefix=".bis-revised-", dir=str(base)))
    try:
        assert temp_dir is not None
        (temp_dir / DIRECT_BIS_REQUIRED_MEMBER.replace(".csv", ".zip")).write_bytes(payload.raw_archive)
        for series_id, series_rows in sorted(rows.items()):
            with (temp_dir / f"{series_id}_canonical.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=("period_start_date", "value", "observation_status", "collection", "title"),
                )
                writer.writeheader()
                writer.writerows(dict(item) for item in series_rows)
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if target.exists():
            existing_path = target / "manifest.json"
            if not existing_path.is_file():
                raise DirectBisDataError(f"Existing BIS snapshot directory is incomplete: {snapshot_id}")
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            if (
                str(existing.get("snapshot_fingerprint") or "") != snapshot_fingerprint
                or str(existing.get("raw_archive_sha256") or "") != raw_sha
            ):
                raise DirectBisDataError(f"BIS snapshot identity collision detected: {snapshot_id}")
        else:
            os.replace(temp_dir, target)
            temp_dir = None
    finally:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir)
    return snapshot_id, snapshot_fingerprint, str(target.relative_to(root)), raw_sha, series_manifest


def load_persisted_direct_bis_snapshot(
    data_root: str | os.PathLike[str],
    snapshot_id: str,
    *,
    series_matrix: Mapping[str, Mapping[str, str]],
    expected_fingerprint: str = "",
) -> dict[str, Any]:
    """Reload and revalidate every raw/canonical byte of a sealed BIS snapshot."""
    identity = str(snapshot_id or "").strip()
    if not re.fullmatch(r"BISREV-[0-9a-f]{16}", identity):
        raise DirectBisDataError("Persisted direct BIS snapshot_id is invalid.")
    matrix = _series_matrix(series_matrix)
    required_series = {
        series_id
        for metadata in matrix.values()
        for series_id in (metadata["real_series_id"], metadata["nominal_series_id"])
    }
    root = Path(data_root).resolve()
    base = (root / "public_data" / "bis_revised_history").resolve()
    target = (base / identity).resolve()
    if target.parent != base or not target.is_dir():
        raise DirectBisDataError(f"Persisted direct BIS snapshot is missing: {identity}")
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2_000_000:
        raise DirectBisDataError("Persisted direct BIS manifest is missing or oversized.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DirectBisDataError("Persisted direct BIS manifest is invalid JSON.") from exc
    if not isinstance(manifest, dict) or str(manifest.get("snapshot_id") or "") != identity:
        raise DirectBisDataError("Persisted direct BIS snapshot identity is inconsistent.")
    if str(manifest.get("history_semantics") or "") != DIRECT_BIS_HISTORY_SEMANTICS:
        raise DirectBisDataError("Persisted direct BIS revised-history semantics changed.")
    if str(manifest.get("point_in_time_status") or "") != "NOT_POINT_IN_TIME":
        raise DirectBisDataError("Persisted direct BIS snapshot is overstated as point-in-time.")
    if manifest.get("historical_evidence_eligible") is not False:
        raise DirectBisDataError("Persisted direct BIS snapshot is incorrectly eligible as historical evidence.")
    if manifest.get("automatic_promotion_authorized") is not False or str(manifest.get("production_status") or "") != "RESEARCH_ONLY":
        raise DirectBisDataError("Persisted direct BIS snapshot lost its research-only promotion lock.")
    series_manifest = manifest.get("series")
    if not isinstance(series_manifest, dict) or set(series_manifest) != required_series:
        raise DirectBisDataError("Persisted direct BIS manifest does not exactly cover the frozen series matrix.")

    raw_path = target / DIRECT_BIS_REQUIRED_MEMBER.replace(".csv", ".zip")
    if not raw_path.is_file() or raw_path.stat().st_size > DIRECT_BIS_MAX_ARCHIVE_BYTES:
        raise DirectBisDataError("Persisted direct BIS raw archive is missing or oversized.")
    raw = raw_path.read_bytes()
    raw_sha = _sha256_bytes(raw)
    if raw_sha != str(manifest.get("raw_archive_sha256") or ""):
        raise DirectBisDataError("Persisted direct BIS raw archive fingerprint mismatch.")
    if len(raw) != int(manifest.get("raw_archive_bytes") or -1):
        raise DirectBisDataError("Persisted direct BIS raw archive byte count mismatch.")
    parsed_rows, raw_csv_bytes = parse_bis_eer_archive(raw, matrix)
    if raw_csv_bytes != int(manifest.get("raw_csv_bytes") or -1):
        raise DirectBisDataError("Persisted direct BIS uncompressed byte count mismatch.")

    verified_manifest: dict[str, dict[str, Any]] = {}
    for series_id, parsed in sorted(parsed_rows.items()):
        metadata = series_manifest.get(series_id)
        if not isinstance(metadata, Mapping):
            raise DirectBisDataError(f"Persisted direct BIS metadata is malformed for {series_id}.")
        parsed_fingerprint = _digest(parsed)
        if parsed_fingerprint != str(metadata.get("row_fingerprint") or ""):
            raise DirectBisDataError(f"Persisted direct BIS raw row fingerprint mismatch for {series_id}.")
        if (
            len(parsed) != int(metadata.get("row_count") or -1)
            or parsed[0]["period_start_date"] != str(metadata.get("observation_start") or "")
            or parsed[-1]["period_start_date"] != str(metadata.get("observation_end") or "")
            or parsed[0]["title"] != str(metadata.get("title") or "")
        ):
            raise DirectBisDataError(f"Persisted direct BIS series inventory mismatch for {series_id}.")
        canonical_path = target / f"{series_id}_canonical.csv"
        if not canonical_path.is_file() or canonical_path.stat().st_size > 5_000_000:
            raise DirectBisDataError(f"Persisted direct BIS canonical file is missing or oversized for {series_id}.")
        canonical: list[dict[str, Any]] = []
        try:
            with canonical_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != ["period_start_date", "value", "observation_status", "collection", "title"]:
                    raise DirectBisDataError(f"Persisted direct BIS canonical schema changed for {series_id}.")
                for source in reader:
                    canonical.append({
                        "period_start_date": str(source.get("period_start_date") or ""),
                        "value": round(float(str(source.get("value") or "")), 12),
                        "observation_status": str(source.get("observation_status") or ""),
                        "collection": str(source.get("collection") or ""),
                        "title": str(source.get("title") or ""),
                    })
        except DirectBisDataError:
            raise
        except Exception as exc:
            raise DirectBisDataError(f"Persisted direct BIS canonical rows are invalid for {series_id}.") from exc
        if canonical != parsed or _digest(canonical) != parsed_fingerprint:
            raise DirectBisDataError(f"Persisted direct BIS canonical content mismatch for {series_id}.")
        verified_manifest[series_id] = dict(metadata)

    snapshot_fingerprint = _digest({
        "source_url": DIRECT_BIS_SOURCE_URL,
        "history_semantics": DIRECT_BIS_HISTORY_SEMANTICS,
        "raw_archive_sha256": raw_sha,
        "series": verified_manifest,
    })
    if snapshot_fingerprint != str(manifest.get("snapshot_fingerprint") or ""):
        raise DirectBisDataError("Persisted direct BIS snapshot fingerprint mismatch.")
    if identity != f"BISREV-{snapshot_fingerprint.split(':', 1)[1][:16]}":
        raise DirectBisDataError("Persisted direct BIS snapshot ID is not derived from its fingerprint.")
    if expected_fingerprint and snapshot_fingerprint != str(expected_fingerprint):
        raise DirectBisDataError("Persisted direct BIS snapshot does not match the expected fingerprint.")
    return {
        "snapshot_id": identity,
        "snapshot_fingerprint": snapshot_fingerprint,
        "manifest": manifest,
        "rows": parsed_rows,
        "path": str(target.relative_to(root)),
    }


def _reference_rows(value: Any) -> list[dict[str, Any]]:
    source_rows = value.rows if hasattr(value, "rows") else value.get("rows") if isinstance(value, Mapping) else None
    rows: list[dict[str, Any]] = []
    for item in source_rows or ():
        row = _row(item)
        period = str(row.get("period_start_date") or "")
        try:
            date.fromisoformat(period)
            numeric = float(row.get("value"))
        except Exception as exc:
            raise DirectBisDataError("Reference ALFRED snapshot contains an invalid canonical row.") from exc
        if not math.isfinite(numeric) or numeric <= 0:
            raise DirectBisDataError("Reference ALFRED snapshot contains a non-positive/non-finite value.")
        rows.append({"period_start_date": period, "value": round(numeric, 12)})
    periods = [row["period_start_date"] for row in rows]
    if not rows or periods != sorted(periods) or len(periods) != len(set(periods)):
        raise DirectBisDataError("Reference ALFRED canonical periods are empty, unordered or duplicated.")
    return rows


def _parse_instant(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def build_prospective_vintage_summary(
    records: Sequence[Mapping[str, Any] | DirectSourceReconciliationRecord],
    *,
    replication_id: str,
    min_distinct_snapshots: int = 12,
    min_distinct_latest_periods: int = 12,
    min_span_days: int = 300,
) -> dict[str, Any]:
    """Derive readiness from genuinely observed, content-distinct snapshots only."""
    unique: dict[str, dict[str, Any]] = {}
    for value in records:
        row = _row(value)
        if str(row.get("replication_id") or "") != str(replication_id):
            continue
        if str(row.get("execution_status") or "") != "COMPLETE":
            continue
        fingerprint = str(row.get("direct_snapshot_fingerprint") or "")
        retrieved = _parse_instant(str(row.get("retrieved_at") or ""))
        latest_period = str(row.get("latest_period") or "")
        if not fingerprint or retrieved is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", latest_period):
            continue
        prior = unique.get(fingerprint)
        candidate = {"retrieved": retrieved, "latest_period": latest_period, "snapshot_id": row.get("direct_snapshot_id")}
        if prior is None or retrieved < prior["retrieved"]:
            unique[fingerprint] = candidate
    observed = sorted(unique.values(), key=lambda item: item["retrieved"])
    span_days = (observed[-1]["retrieved"] - observed[0]["retrieved"]).days if len(observed) >= 2 else 0
    latest_periods = sorted({str(item["latest_period"]) for item in observed})
    ready = (
        len(observed) >= int(min_distinct_snapshots)
        and len(latest_periods) >= int(min_distinct_latest_periods)
        and span_days >= int(min_span_days)
    )
    return {
        "status": "READY_FOR_FORWARD_VINTAGE_STUDY" if ready else "WARMING_UP",
        "distinct_snapshots": len(observed),
        "distinct_latest_periods": len(latest_periods),
        "span_days": span_days,
        "first_observed_at": observed[0]["retrieved"].isoformat() if observed else "",
        "last_observed_at": observed[-1]["retrieved"].isoformat() if observed else "",
        "latest_periods": latest_periods,
        "required_distinct_snapshots": int(min_distinct_snapshots),
        "required_distinct_latest_periods": int(min_distinct_latest_periods),
        "required_span_days": int(min_span_days),
        "historical_backfill_permitted": False,
        "historical_evidence_eligible": False,
    }


def execute_direct_bis_reconciliation(
    protocol: Any,
    *,
    data_root: str | os.PathLike[str],
    prior_records: Sequence[Mapping[str, Any] | DirectSourceReconciliationRecord] = (),
    archive_fetcher: Callable[[], BisArchivePayload | bytes] | None = None,
    reference_loader: Callable[..., Mapping[str, Any]] | None = None,
) -> DirectSourceReconciliationRecord:
    """Acquire, seal and reconcile current BIS history against initial releases."""
    record = _record(protocol)
    if record.protocol_version != DIRECT_BIS_PROTOCOL_VERSION:
        raise ValueError("Unsupported direct-source reconciliation protocol version.")
    if record.status != "FROZEN" or record.execution_status != "NOT_RUN":
        raise ValueError("Only a persisted, unexecuted FROZEN direct-source protocol may run.")
    if _digest(_protocol_payload(asdict(record))) != record.protocol_fingerprint:
        raise ValueError("Direct-source protocol fingerprint mismatch; acquisition refused.")
    if record.history_semantics != DIRECT_BIS_HISTORY_SEMANTICS:
        raise ValueError("Direct BIS revised-history semantics are not intact.")
    if record.point_in_time_status != "NOT_POINT_IN_TIME" or record.historical_evidence_eligible:
        raise ValueError("Direct BIS revised history cannot be treated as point-in-time evidence.")
    if record.automatic_promotion_authorized or record.production_status != "RESEARCH_ONLY":
        raise ValueError("Direct-source production/promotion lock is not intact.")
    matrix = _series_matrix(record.series_matrix)
    required_series = tuple(sorted(
        series_id
        for metadata in matrix.values()
        for series_id in (metadata["real_series_id"], metadata["nominal_series_id"])
    ))
    if len(required_series) != record.expected_series_count:
        raise ValueError("Frozen direct-source expected series count is inconsistent.")

    if reference_loader is None:
        reference = load_persisted_alfred_snapshot_bundle(
            data_root,
            record.reference_snapshot_id,
            expected_fingerprint=record.reference_snapshot_fingerprint,
            required_series=required_series,
        )
    else:
        reference = reference_loader(
            data_root=data_root,
            snapshot_id=record.reference_snapshot_id,
            expected_fingerprint=record.reference_snapshot_fingerprint,
            required_series=required_series,
        )
    if set(reference) != set(required_series):
        raise DirectBisDataError("Reference ALFRED bundle does not exactly cover the frozen series matrix.")

    fetched = archive_fetcher() if archive_fetcher is not None else download_bis_eer_archive()
    payload = (
        fetched
        if isinstance(fetched, BisArchivePayload)
        else BisArchivePayload(raw_archive=bytes(fetched), retrieved_at=_now_iso(), response_metadata={})
    )
    if _parse_instant(payload.retrieved_at) is None:
        raise DirectBisDataError("BIS retrieval timestamp is missing its timezone.")
    direct_rows, raw_csv_bytes = parse_bis_eer_archive(payload.raw_archive, matrix)
    for series_id, rows in direct_rows.items():
        if len(rows) < record.min_rows_per_series:
            raise DirectBisDataError(
                f"BIS direct series {series_id} has only {len(rows)} monthly rows; {record.min_rows_per_series} required."
            )
    snapshot_id, snapshot_fingerprint, snapshot_path, raw_sha, series_manifest = _persist_direct_snapshot(
        data_root,
        payload,
        direct_rows,
        raw_csv_bytes,
    )
    verified_direct = load_persisted_direct_bis_snapshot(
        data_root,
        snapshot_id,
        series_matrix=matrix,
        expected_fingerprint=snapshot_fingerprint,
    )
    direct_rows = verified_direct["rows"]

    results: list[dict[str, Any]] = []
    total_overlap = 0
    total_exact = 0
    for market, metadata in sorted(matrix.items()):
        for measurement, series_id in (
            ("REAL_EER", metadata["real_series_id"]),
            ("NOMINAL_EER", metadata["nominal_series_id"]),
        ):
            initial_rows = _reference_rows(reference[series_id])
            initial = {row["period_start_date"]: float(row["value"]) for row in initial_rows}
            revised = {row["period_start_date"]: float(row["value"]) for row in direct_rows[series_id]}
            overlap = sorted(set(initial).intersection(revised))
            if len(overlap) < record.min_overlap_rows:
                raise DirectBisDataError(
                    f"Direct BIS/reference overlap for {series_id} has only {len(overlap)} rows; {record.min_overlap_rows} required."
                )
            comparisons: list[dict[str, Any]] = []
            for period in overlap:
                initial_value = initial[period]
                revised_value = revised[period]
                delta = revised_value - initial_value
                comparisons.append({
                    "period_start_date": period,
                    "initial_release_value": round(initial_value, 12),
                    "current_revised_value": round(revised_value, 12),
                    "revision_delta": round(delta, 12),
                    "absolute_revision": round(abs(delta), 12),
                    "revision_pct_of_initial": round((delta / initial_value) * 100.0, 12),
                    "equal_within_tolerance": abs(delta) <= record.equality_tolerance,
                })
            exact = sum(bool(item["equal_within_tolerance"]) for item in comparisons)
            deltas = [float(item["revision_delta"]) for item in comparisons]
            absolute = [float(item["absolute_revision"]) for item in comparisons]
            absolute_pct = [abs(float(item["revision_pct_of_initial"])) for item in comparisons]
            result = {
                "market": market,
                "market_label": metadata["label"],
                "measurement": measurement,
                "series_id": series_id,
                "title": series_manifest[series_id]["title"],
                "initial_release_row_count": len(initial_rows),
                "current_revised_row_count": len(direct_rows[series_id]),
                "overlap_row_count": len(overlap),
                "overlap_start": overlap[0],
                "overlap_end": overlap[-1],
                "initial_only_row_count": len(set(initial).difference(revised)),
                "revised_only_row_count": len(set(revised).difference(initial)),
                "exact_match_row_count": exact,
                "revised_row_count": len(overlap) - exact,
                "exact_match_rate": round(exact / len(overlap), 12),
                "mean_signed_revision": round(statistics.fmean(deltas), 12),
                "mean_absolute_revision": round(statistics.fmean(absolute), 12),
                "max_absolute_revision": round(max(absolute), 12),
                "mean_absolute_revision_pct": round(statistics.fmean(absolute_pct), 12),
                "max_absolute_revision_pct": round(max(absolute_pct), 12),
                "latest_overlap_initial_value": comparisons[-1]["initial_release_value"],
                "latest_overlap_revised_value": comparisons[-1]["current_revised_value"],
                "latest_overlap_revision_delta": comparisons[-1]["revision_delta"],
                "direct_row_fingerprint": series_manifest[series_id]["row_fingerprint"],
                "comparison_fingerprint": _digest(comparisons),
                "comparison_rows": comparisons,
                "history_semantics": DIRECT_BIS_HISTORY_SEMANTICS,
                "historical_evidence_eligible": False,
            }
            results.append(result)
            total_overlap += len(overlap)
            total_exact += exact

    total_revised = total_overlap - total_exact
    latest_period = max(rows[-1]["period_start_date"] for rows in direct_rows.values())
    reconciliation_status = "RECONCILED_WITH_REVISIONS" if total_revised else "EXACT_MATCH"
    reconciliation_fingerprint = _digest({
        "protocol_fingerprint": record.protocol_fingerprint,
        "reference_snapshot_fingerprint": record.reference_snapshot_fingerprint,
        "direct_snapshot_fingerprint": snapshot_fingerprint,
        "series_results": results,
        "history_semantics": DIRECT_BIS_HISTORY_SEMANTICS,
    })
    completed_at = _now_iso()
    completed = replace(
        record,
        status="COMPLETE",
        execution_status="COMPLETE",
        completed_at=completed_at,
        source_integrity_status="PASS",
        coverage_status="PASS",
        reconciliation_status=reconciliation_status,
        direct_snapshot_id=snapshot_id,
        direct_snapshot_path=snapshot_path,
        direct_snapshot_fingerprint=snapshot_fingerprint,
        raw_archive_sha256=raw_sha,
        raw_archive_bytes=len(payload.raw_archive),
        raw_csv_bytes=raw_csv_bytes,
        retrieved_at=payload.retrieved_at,
        response_metadata=dict(payload.response_metadata),
        latest_period=latest_period,
        series_count=len(results),
        total_overlap_rows=total_overlap,
        total_exact_match_rows=total_exact,
        total_revised_rows=total_revised,
        series_results=tuple(results),
        reconciliation_fingerprint=reconciliation_fingerprint,
        lifecycle_history=record.lifecycle_history + ({
            "at": completed_at,
            "event": "DIRECT_BIS_ACQUISITION_AND_RECONCILIATION_COMPLETE",
            "status": "COMPLETE",
            "execution_status": "COMPLETE",
            "source_integrity_status": "PASS",
            "coverage_status": "PASS",
            "reconciliation_status": reconciliation_status,
            "direct_snapshot_id": snapshot_id,
            "direct_snapshot_fingerprint": snapshot_fingerprint,
            "historical_evidence_eligible": False,
            "production_status": "RESEARCH_ONLY",
        },),
    )
    prospective = build_prospective_vintage_summary(
        [*prior_records, completed],
        replication_id=record.replication_id,
        min_distinct_snapshots=record.prospective_min_distinct_snapshots,
        min_distinct_latest_periods=record.prospective_min_distinct_latest_periods,
        min_span_days=record.prospective_min_span_days,
    )
    return replace(
        completed,
        prospective_distinct_snapshots=int(prospective["distinct_snapshots"]),
        prospective_distinct_latest_periods=int(prospective["distinct_latest_periods"]),
        prospective_span_days=int(prospective["span_days"]),
        prospective_vintage_status=str(prospective["status"]),
    )


__all__ = [
    "BisArchivePayload",
    "DIRECT_BIS_ACCESS_MODE",
    "DIRECT_BIS_EXPORT_HELP_URL",
    "DIRECT_BIS_HISTORY_SEMANTICS",
    "DIRECT_BIS_PROTOCOL_VERSION",
    "DIRECT_BIS_SOURCE_URL",
    "DIRECT_BIS_TERMS_URL",
    "DIRECT_BIS_TOPIC_URL",
    "DirectBisDataError",
    "build_prospective_vintage_summary",
    "download_bis_eer_archive",
    "execute_direct_bis_reconciliation",
    "freeze_direct_bis_reconciliation",
    "load_persisted_direct_bis_snapshot",
    "parse_bis_eer_archive",
]
