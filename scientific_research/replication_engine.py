from __future__ import annotations

import calendar
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
import time
import zipfile
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx
import requests

from .experiment_factory import run_historical_oos_experiment


INDEPENDENT_REPLICATION_PROTOCOL_VERSION = "SRB_INDEPENDENT_REPLICATION_V1"
ALFRED_DOWNLOAD_BASE = "https://alfred.stlouisfed.org/series/downloaddata"
ALFRED_GRAPH_BASE = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
ALFRED_HELP_URL = "https://alfred.stlouisfed.org/help/downloaddata"
FRED_TERMS_URL = "https://fred.stlouisfed.org/legal"
BIS_TERMS_URL = "https://data.bis.org/help/legal"
ALFRED_VINTAGE_BATCH_SIZE = 1000
# The public graph endpoint silently truncates matrices above 12 series/vintage
# columns, so every request is capped and its exact returned header is audited.
ALFRED_GRAPH_BATCH_SIZE = 12
ALFRED_MAX_ARCHIVE_BYTES = 5_000_000
ALFRED_FORM_ACCESS_MODE = "PUBLIC_ALFRED_FORM_INITIAL_RELEASE_DOWNLOAD"
ALFRED_GRAPH_ACCESS_MODE = "PUBLIC_ALFRED_GRAPH_DAILY_VINTAGE_RECONSTRUCTION"
ALFRED_FORM_POINT_IN_TIME_POLICY = "FIRST_RELEASE_VALUE_PER_OBSERVATION"
ALFRED_GRAPH_POINT_IN_TIME_POLICY = "FIRST_OBSERVED_DAILY_VINTAGE_PER_OBSERVATION"
REPLICATION_EVENT_TIME_SUPPORT_POLICY = (
    "STRICT_RELEASE_EVENT_TIME_KEEP_LATEST_PERIOD_PER_CO_RELEASE_"
    "EXCLUDE_NON_ADVANCING_BACKFILLS"
)
ALFRED_USER_AGENT = (
    "ScientificResearchBrain/0.6.6.1 research-only replication; "
    "public initial-release download; no automated production use"
)

ALFRED_BIS_MARKETS: dict[str, dict[str, str]] = {
    "US": {
        "label": "United States",
        "real_series_id": "RBUSBIS",
        "nominal_series_id": "NBUSBIS",
    },
    "GB": {
        "label": "United Kingdom",
        "real_series_id": "RBGBBIS",
        "nominal_series_id": "NBGBBIS",
    },
    "JP": {
        "label": "Japan",
        "real_series_id": "RBJPBIS",
        "nominal_series_id": "NBJPBIS",
    },
}

REPLICATION_MEASUREMENTS: tuple[dict[str, str], ...] = (
    {
        "variant_id": "REAL_EER_LOG",
        "label": "log real broad effective exchange rate",
        "formula": "log(REER_t)",
    },
    {
        "variant_id": "NOMINAL_EER_LOG",
        "label": "log nominal broad effective exchange rate",
        "formula": "log(NEER_t)",
    },
    {
        "variant_id": "RELATIVE_PRICE_WEDGE",
        "label": "relative-price competitiveness wedge",
        "formula": "log(REER_t) - log(NEER_t)",
    },
)


class ReplicationDataError(RuntimeError):
    """Raised when public replication data fail a provenance or integrity gate."""


@dataclass(frozen=True)
class AlfredInitialReleaseRow:
    period_start_date: str
    value: float
    realtime_start_date: str


@dataclass(frozen=True)
class AlfredSeriesSnapshot:
    series_id: str
    title: str
    source_url: str
    retrieved_at: str
    observation_start: str
    observation_end: str
    vintage_dates: tuple[str, ...]
    rows: tuple[AlfredInitialReleaseRow, ...]
    row_fingerprint: str
    raw_archives: tuple[bytes, ...] = field(repr=False, compare=False)
    response_metadata: tuple[dict[str, str], ...] = ()
    point_in_time_status: str = "PASS"
    revision_policy: str = "INITIAL_RELEASE_ONLY"


@dataclass(frozen=True)
class IndependentReplicationRecord:
    replication_id: str
    created_at: str
    experiment_id: str
    reference_run_id: str
    reference_measurement_report_id: str
    protocol_frozen_at: str
    protocol_fingerprint: str
    hypothesis_scope: str
    null_hypothesis: str
    markets: tuple[str, ...]
    measurement_variants: tuple[dict[str, str], ...]
    series_matrix: dict[str, dict[str, str]]
    train_fraction: float
    forecast_horizon: int
    min_common_rows: int
    source_provider: str = "Federal Reserve Bank of St. Louis ALFRED"
    underlying_provider: str = "Bank for International Settlements"
    source_access_mode: str = "PUBLIC_ALFRED_FORM_INITIAL_RELEASE_DOWNLOAD"
    source_url: str = ALFRED_DOWNLOAD_BASE
    source_documentation_url: str = ALFRED_HELP_URL
    source_terms_urls: tuple[str, ...] = (FRED_TERMS_URL, BIS_TERMS_URL)
    access_cost: str = "FREE"
    credentials_required: bool = False
    point_in_time_policy: str = "FIRST_RELEASE_VALUE_PER_OBSERVATION"
    event_time_support_policy: str = ""
    point_in_time_status: str = "PENDING_EXECUTION"
    independence_dimensions: dict[str, bool] = field(default_factory=lambda: {
        "market": True,
        "period": False,
        "implementation": False,
        "data_lineage": True,
        "provider": True,
        "investigator": False,
    })
    independence_gate_status: str = "PENDING_EXECUTION"
    estimator_protocol: str = "SRB_OU_HISTORICAL_V2"
    baseline_policy: str = "RANDOM_WALK_LAST_OBSERVATION_AND_TRAINING_MEAN"
    multiplicity_policy: str = "HOLM_BONFERRONI_ACROSS_ALL_MARKET_MEASUREMENT_TESTS"
    status: str = "FROZEN"
    execution_status: str = "NOT_RUN"
    completed_at: str = ""
    snapshot_id: str = ""
    snapshot_path: str = ""
    source_snapshot_fingerprint: str = ""
    execution_fingerprint: str = ""
    replication_outcome: str = ""
    result_count: int = 0
    promising_result_count: int = 0
    no_improvement_result_count: int = 0
    results: tuple[dict[str, Any], ...] = ()
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = (
        "This protocol tests independent markets and data lineage, not an independent human investigator or independent implementation.",
        "Initial-release values are used to prevent revised-history leakage; ALFRED coverage begins later than the underlying BIS series history.",
        "A completed replication gate records execution regardless of outcome sign and never authorizes production or belief promotion.",
    )
    lifecycle_history: tuple[dict[str, Any], ...] = ()
    protocol_version: str = INDEPENDENT_REPLICATION_PROTOCOL_VERSION
    automatic_promotion_authorized: bool = False
    production_status: str = "RESEARCH_ONLY"


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


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_digest(parts).split(':', 1)[1][:16]}"


def _row(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Expected dataclass or mapping")


def _record(value: Any) -> IndependentReplicationRecord:
    if isinstance(value, IndependentReplicationRecord):
        return value
    row = _row(value)
    allowed = {item.name for item in fields(IndependentReplicationRecord)}
    return IndependentReplicationRecord(**{key: row[key] for key in allowed if key in row})


def _protocol_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": record.get("protocol_version"),
        "experiment_id": record.get("experiment_id"),
        "reference_run_id": record.get("reference_run_id"),
        "reference_measurement_report_id": record.get("reference_measurement_report_id"),
        "hypothesis_scope": record.get("hypothesis_scope"),
        "null_hypothesis": record.get("null_hypothesis"),
        "markets": record.get("markets"),
        "measurement_variants": record.get("measurement_variants"),
        "series_matrix": record.get("series_matrix"),
        "train_fraction": record.get("train_fraction"),
        "forecast_horizon": record.get("forecast_horizon"),
        "min_common_rows": record.get("min_common_rows"),
        "source_provider": record.get("source_provider"),
        "underlying_provider": record.get("underlying_provider"),
        "source_access_mode": record.get("source_access_mode"),
        "point_in_time_policy": record.get("point_in_time_policy"),
        "event_time_support_policy": record.get("event_time_support_policy"),
        "independence_dimensions": record.get("independence_dimensions"),
        "estimator_protocol": record.get("estimator_protocol"),
        "baseline_policy": record.get("baseline_policy"),
        "multiplicity_policy": record.get("multiplicity_policy"),
        "automatic_promotion_authorized": record.get("automatic_promotion_authorized"),
        "production_status": record.get("production_status"),
    }


def build_alfred_bis_replication_protocol(
    reference_run: Any,
    measurement_report: Any,
    *,
    markets: Sequence[str] = ("US", "GB", "JP"),
    train_fraction: float = 0.70,
    min_common_rows: int = 96,
    source_access_mode: str = ALFRED_FORM_ACCESS_MODE,
) -> IndependentReplicationRecord:
    run = _row(reference_run)
    report = _row(measurement_report)
    if str(run.get("stage") or "") != "HISTORICAL_OOS":
        raise ValueError("Independent replication requires a persisted HISTORICAL_OOS reference run.")
    if not str(run.get("run_id") or ""):
        raise ValueError("Reference run_id is required.")
    if str(run.get("production_status") or "RESEARCH_ONLY") != "RESEARCH_ONLY":
        raise ValueError("Reference run must remain RESEARCH_ONLY.")
    required_report_states = {
        "status": "COMPLETE",
        "gate_status": "PASS",
        "common_support_status": "PASS",
        "common_split_status": "PASS",
        "point_in_time_status": "PASS",
        "production_status": "RESEARCH_ONLY",
    }
    for field_name, expected in required_report_states.items():
        if str(report.get(field_name) or "") != expected:
            raise ValueError(f"Measurement report {field_name} must be {expected} before replication is frozen.")
    if str(report.get("experiment_id") or "") != str(run.get("experiment_id") or ""):
        raise ValueError("Reference run and measurement report must belong to the same experiment.")
    selected_markets = tuple(dict.fromkeys(str(item).strip().upper() for item in markets if str(item).strip()))
    if len(selected_markets) < 2:
        raise ValueError("At least two independent target markets must be predeclared.")
    unknown = [item for item in selected_markets if item not in ALFRED_BIS_MARKETS]
    if unknown:
        raise ValueError(f"Unsupported ALFRED/BIS market codes: {', '.join(unknown)}")
    if not 0.5 <= float(train_fraction) <= 0.85:
        raise ValueError("train_fraction must be between 0.50 and 0.85.")
    if int(min_common_rows) < 60:
        raise ValueError("min_common_rows must be at least 60.")
    source_access_mode = str(source_access_mode or "").strip()
    allowed_access_modes = {ALFRED_FORM_ACCESS_MODE, ALFRED_GRAPH_ACCESS_MODE}
    if source_access_mode not in allowed_access_modes:
        raise ValueError(f"Unsupported ALFRED access mode: {source_access_mode or 'MISSING'}")
    point_in_time_policy = (
        ALFRED_FORM_POINT_IN_TIME_POLICY
        if source_access_mode == ALFRED_FORM_ACCESS_MODE
        else ALFRED_GRAPH_POINT_IN_TIME_POLICY
    )
    source_url = ALFRED_DOWNLOAD_BASE if source_access_mode == ALFRED_FORM_ACCESS_MODE else ALFRED_GRAPH_BASE

    frozen_at = _now_iso()
    matrix = {market: dict(ALFRED_BIS_MARKETS[market]) for market in selected_markets}
    preliminary = {
        "protocol_version": INDEPENDENT_REPLICATION_PROTOCOL_VERSION,
        "experiment_id": str(run.get("experiment_id") or ""),
        "reference_run_id": str(run.get("run_id") or ""),
        "reference_measurement_report_id": str(report.get("report_id") or ""),
        "hypothesis_scope": (
            "Test whether the predeclared OU/AR(1) surrogate improves one-step chronological forecasts "
            "versus random walk for real EER, nominal EER and their log wedge across non-euro markets."
        ),
        "null_hypothesis": (
            "The candidate does not improve the random-walk baseline out of sample across independent markets and measurements."
        ),
        "markets": selected_markets,
        "measurement_variants": REPLICATION_MEASUREMENTS,
        "series_matrix": matrix,
        "train_fraction": float(train_fraction),
        "forecast_horizon": 1,
        "min_common_rows": int(min_common_rows),
        "source_provider": "Federal Reserve Bank of St. Louis ALFRED",
        "underlying_provider": "Bank for International Settlements",
        "source_access_mode": source_access_mode,
        "point_in_time_policy": point_in_time_policy,
        "event_time_support_policy": REPLICATION_EVENT_TIME_SUPPORT_POLICY,
        "independence_dimensions": {
            "market": True,
            "period": False,
            "implementation": False,
            "data_lineage": True,
            "provider": True,
            "investigator": False,
        },
        "estimator_protocol": "SRB_OU_HISTORICAL_V2",
        "baseline_policy": "RANDOM_WALK_LAST_OBSERVATION_AND_TRAINING_MEAN",
        "multiplicity_policy": "HOLM_BONFERRONI_ACROSS_ALL_MARKET_MEASUREMENT_TESTS",
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }
    protocol_fingerprint = _digest(preliminary)
    replication_id = _stable_id("IRP", protocol_fingerprint)
    lifecycle = ({
        "at": frozen_at,
        "from": "",
        "to": "FROZEN",
        "actor": "SYSTEM_ON_EXPLICIT_USER_ACTION",
        "reason": "Independent-market replication protocol persisted before public data retrieval.",
        "evidence_refs": [str(run.get("run_id") or ""), str(report.get("report_id") or "")],
    },)
    return IndependentReplicationRecord(
        replication_id=replication_id,
        created_at=frozen_at,
        experiment_id=preliminary["experiment_id"],
        reference_run_id=preliminary["reference_run_id"],
        reference_measurement_report_id=preliminary["reference_measurement_report_id"],
        protocol_frozen_at=frozen_at,
        protocol_fingerprint=protocol_fingerprint,
        hypothesis_scope=preliminary["hypothesis_scope"],
        null_hypothesis=preliminary["null_hypothesis"],
        markets=selected_markets,
        measurement_variants=REPLICATION_MEASUREMENTS,
        series_matrix=matrix,
        train_fraction=float(train_fraction),
        forecast_horizon=1,
        min_common_rows=int(min_common_rows),
        source_access_mode=source_access_mode,
        source_url=source_url,
        point_in_time_policy=point_in_time_policy,
        event_time_support_policy=REPLICATION_EVENT_TIME_SUPPORT_POLICY,
        warnings=(
            "This protocol tests independent markets and data lineage, not an independent human investigator or independent implementation.",
            (
                "First-release values come from the ALFRED initial-release form."
                if source_access_mode == ALFRED_FORM_ACCESS_MODE
                else "First observed values are reconstructed from official daily ALFRED graph vintages; left-censored observations are excluded."
            ),
            "Co-released observations are reduced to the latest reference period and non-advancing backfills are excluded before forecasting.",
            "A completed replication gate records execution regardless of outcome sign and never authorizes production or belief promotion.",
        ),
        lifecycle_history=lifecycle,
    )


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(response, "content", b"")
    return bytes(content).decode("utf-8", errors="replace")


def _raise_for_status(response: Any) -> None:
    method = getattr(response, "raise_for_status", None)
    if callable(method):
        method()
        return
    status = int(getattr(response, "status_code", 200) or 200)
    if status >= 400:
        raise ReplicationDataError(f"ALFRED request failed with HTTP {status}.")


def _request_with_retry(client: Any, method: str, url: str, **kwargs: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            response = getattr(client, method)(url, **kwargs)
            status = int(getattr(response, "status_code", 200) or 200)
            if status in {429, 500, 502, 503, 504}:
                raise requests.ConnectionError(f"retryable HTTP {status}")
            return response
        except (
            requests.Timeout,
            requests.ConnectionError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(float(attempt))
    detail = (
        f"{type(last_error).__name__}: {str(last_error)[:180]}"
        if last_error is not None else "unknown transport error"
    )
    raise ReplicationDataError(
        f"ALFRED {method.upper()} request failed after three attempts ({detail})."
    ) from last_error


def _month_end_vintages(start: date, end: date) -> tuple[str, ...]:
    if end < start:
        raise ValueError("ALFRED graph discovery end precedes start.")
    cursor = date(start.year, start.month, 1)
    values: list[date] = []
    while cursor <= end:
        month_end = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        if month_end >= start and month_end <= end:
            values.append(month_end)
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
    if not values or values[-1] < end:
        values.append(end)
    return tuple(item.isoformat() for item in values)


def _parse_alfred_graph_matrix(
    raw: bytes,
    series_id: str,
    vintage_dates: Sequence[str],
) -> dict[str, dict[str, float]]:
    if not raw or len(raw) > ALFRED_MAX_ARCHIVE_BYTES:
        raise ReplicationDataError(f"ALFRED graph response for {series_id} is empty or exceeds the safety limit.")
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ReplicationDataError(f"ALFRED graph response for {series_id} is empty.") from exc
    expected = [f"{series_id}_{item.replace('-', '')}" for item in vintage_dates]
    if len(header) != len(expected) + 1 or header[0] != "observation_date" or header[1:] != expected:
        raise ReplicationDataError(
            f"ALFRED graph columns for {series_id} do not match the requested vintage sequence "
            f"(received={max(0, len(header) - 1)}, expected={len(expected)})."
        )
    matrix: dict[str, dict[str, float]] = {item: {} for item in vintage_dates}
    for source in reader:
        if len(source) != len(header):
            raise ReplicationDataError(f"ALFRED graph row width changed for {series_id}.")
        period = str(source[0] or "").strip()
        try:
            date.fromisoformat(period)
        except Exception as exc:
            raise ReplicationDataError(f"ALFRED graph returned an invalid observation date for {series_id}.") from exc
        for index, vintage in enumerate(vintage_dates, start=1):
            raw_value = str(source[index] or "").strip()
            if raw_value in {"", ".", "NA", "#NA"}:
                continue
            try:
                value = float(raw_value)
            except Exception as exc:
                raise ReplicationDataError(f"ALFRED graph returned a non-numeric value for {series_id}.") from exc
            if not math.isfinite(value) or value <= 0:
                raise ReplicationDataError(f"ALFRED graph returned a non-positive/non-finite value for {series_id}.")
            matrix[vintage][period] = round(value, 12)
    return matrix


def fetch_alfred_graph_initial_release_series(
    series_id: str,
    *,
    session: Any | None = None,
    timeout: float = 45.0,
    discovery_start: date = date(2014, 2, 1),
    as_of_date: date | None = None,
    batch_size: int = ALFRED_GRAPH_BATCH_SIZE,
) -> AlfredSeriesSnapshot:
    """Reconstruct the first daily ALFRED vintage in which each observation exists.

    The official graph endpoint is queried first at month ends, then with a bounded
    parallel binary search inside each first-appearance month. Observations already
    present at the first sampled vintage are excluded as left-censored.
    """
    series_id = str(series_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,20}", series_id):
        raise ValueError("ALFRED series_id must be an uppercase alphanumeric identifier.")
    end = as_of_date or datetime.now(timezone.utc).date()
    if int(batch_size) < 1 or int(batch_size) > ALFRED_GRAPH_BATCH_SIZE:
        raise ValueError(
            f"ALFRED graph batch_size must be between 1 and {ALFRED_GRAPH_BATCH_SIZE}; "
            "the public endpoint truncates wider matrices."
        )
    # ALFRED's HTTP/2 edge resets graph streams when SRB's descriptive custom
    # User-Agent is sent. Preserve the client's standards-compliant default UA
    # for this endpoint and identify the requested representation explicitly.
    graph_headers = {"Accept": "text/csv,application/csv"}
    if session is None:
        with httpx.Client(
            http2=True,
            follow_redirects=True,
            timeout=timeout,
            headers=graph_headers,
        ) as client:
            return fetch_alfred_graph_initial_release_series(
                series_id,
                session=client,
                timeout=timeout,
                discovery_start=discovery_start,
                as_of_date=end,
                batch_size=batch_size,
            )
    client = session
    headers = graph_headers
    observation_start = date(discovery_start.year, discovery_start.month, 1).isoformat()
    observation_end = end.isoformat()
    raw_responses: list[tuple[bytes, dict[str, str]]] = []
    cache: dict[str, dict[str, float]] = {}

    def load(vintages: Sequence[str], stage: str) -> None:
        needed = tuple(dict.fromkeys(item for item in vintages if item not in cache))
        for offset in range(0, len(needed), int(batch_size)):
            batch = needed[offset: offset + int(batch_size)]
            params = {
                "id": ",".join(series_id for _ in batch),
                "vintage_date": ",".join(batch),
                "cosd": observation_start,
                "coed": observation_end,
            }
            response = _request_with_retry(
                client, "get", ALFRED_GRAPH_BASE,
                params=params, headers=headers, timeout=timeout,
            )
            _raise_for_status(response)
            raw = bytes(getattr(response, "content", b""))
            parsed = _parse_alfred_graph_matrix(raw, series_id, batch)
            cache.update(parsed)
            response_headers = getattr(response, "headers", {}) or {}
            meta = {
                "stage": stage,
                "vintage_start": batch[0],
                "vintage_end": batch[-1],
                "vintage_count": str(len(batch)),
                "content_type": str(response_headers.get("content-type") or ""),
                "source_url": str(getattr(response, "url", ALFRED_GRAPH_BASE) or ALFRED_GRAPH_BASE),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            raw_responses.append((raw, meta))

    month_ends = _month_end_vintages(discovery_start, end)
    load(month_ends, "MONTH_END_DISCOVERY")
    periods = sorted({period for vintage in month_ends for period in cache.get(vintage, {})})
    intervals: dict[str, list[date]] = {}
    for period in periods:
        first_index = next((index for index, vintage in enumerate(month_ends) if period in cache.get(vintage, {})), None)
        if first_index is None or first_index == 0:
            continue
        intervals[period] = [
            date.fromisoformat(month_ends[first_index - 1]),
            date.fromisoformat(month_ends[first_index]),
        ]
    if len(intervals) < 12:
        raise ReplicationDataError(
            f"ALFRED graph reconstruction found only {len(intervals)} non-left-censored observations for {series_id}."
        )

    for _ in range(7):
        unresolved = {
            period: bounds for period, bounds in intervals.items()
            if (bounds[1] - bounds[0]).days > 1
        }
        if not unresolved:
            break
        mids = tuple(sorted({
            (bounds[0] + timedelta(days=(bounds[1] - bounds[0]).days // 2)).isoformat()
            for bounds in unresolved.values()
        }))
        load(mids, "DAILY_BINARY_SEARCH")
        for period, bounds in unresolved.items():
            midpoint = bounds[0] + timedelta(days=(bounds[1] - bounds[0]).days // 2)
            if period in cache.get(midpoint.isoformat(), {}):
                bounds[1] = midpoint
            else:
                bounds[0] = midpoint
    if any((high - low).days != 1 for low, high in intervals.values()):
        raise ReplicationDataError(f"ALFRED graph release-date search did not converge for {series_id}.")

    rows: list[AlfredInitialReleaseRow] = []
    for period, (low, high) in sorted(intervals.items()):
        value = cache.get(high.isoformat(), {}).get(period)
        if value is None or period in cache.get(low.isoformat(), {}):
            raise ReplicationDataError(f"ALFRED graph release boundary is inconsistent for {series_id} {period}.")
        rows.append(AlfredInitialReleaseRow(period, value, high.isoformat()))
    release_dates = [row.realtime_start_date for row in rows]
    release_date_duplicate_rows = len(release_dates) - len(set(release_dates))
    release_date_inversions = sum(
        release_dates[index] < release_dates[index - 1]
        for index in range(1, len(release_dates))
    )

    raw_buffer = io.BytesIO()
    request_manifest: list[dict[str, str]] = []
    with zipfile.ZipFile(raw_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (raw, meta) in enumerate(raw_responses, start=1):
            info = zipfile.ZipInfo(f"request_{index:03d}.csv")
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, raw)
            request_manifest.append({"member": info.filename, **meta})
        manifest_info = zipfile.ZipInfo("request_manifest.json")
        manifest_info.date_time = (1980, 1, 1, 0, 0, 0)
        manifest_info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(
            manifest_info,
            json.dumps(request_manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
        )
    row_fingerprint = _digest([asdict(item) for item in rows])
    snapshot = AlfredSeriesSnapshot(
        series_id=series_id,
        title=f"{series_id} daily first-observed vintage",
        source_url=ALFRED_GRAPH_BASE,
        retrieved_at=_now_iso(),
        observation_start=rows[0].period_start_date,
        observation_end=rows[-1].period_start_date,
        vintage_dates=tuple(release_dates),
        rows=tuple(rows),
        row_fingerprint=row_fingerprint,
        raw_archives=(raw_buffer.getvalue(),),
        response_metadata=({
            "access_mode": ALFRED_GRAPH_ACCESS_MODE,
            "request_count": str(len(raw_responses)),
            "discovery_start": discovery_start.isoformat(),
            "as_of_date": end.isoformat(),
            "left_censored_policy": "EXCLUDED",
            "release_date_duplicate_rows": str(release_date_duplicate_rows),
            "release_date_inversions": str(release_date_inversions),
        },),
        point_in_time_status="PASS",
        revision_policy=ALFRED_GRAPH_POINT_IN_TIME_POLICY,
    )
    return snapshot


def _parse_form(html: str, series_id: str) -> tuple[str, str, tuple[str, ...], str]:
    start_match = re.search(r'id="form_obs_start_date"[^>]*value="(\d{4}-\d{2}-\d{2})"', html)
    end_match = re.search(r'id="form_obs_end_date"[^>]*value="(\d{4}-\d{2}-\d{2})"', html)
    vintage_block = re.search(
        r'<select[^>]*id="form_selected_vintage_dates"[^>]*>(.*?)</select>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    vintages = tuple(
        re.findall(r'<option\s+value="(\d{4}-\d{2}-\d{2})"', vintage_block.group(1) if vintage_block else "")
    )
    title_match = re.search(r'<h1[^>]*>\s*Download Data for\s+(.+?)\s*\([^()]+\)\s*</h1>', html, re.I | re.S)
    title = re.sub(r'<[^>]+>', " ", title_match.group(1)).strip() if title_match else series_id
    if not start_match or not end_match or not vintages:
        raise ReplicationDataError(f"ALFRED download form for {series_id} is missing range or vintage metadata.")
    return start_match.group(1), end_match.group(1), tuple(dict.fromkeys(vintages)), title


def _parse_initial_release_zip(raw: bytes, series_id: str) -> tuple[AlfredInitialReleaseRow, ...]:
    if not raw.startswith(b"PK"):
        raise ReplicationDataError(f"ALFRED response for {series_id} is not a ZIP archive.")
    if len(raw) > ALFRED_MAX_ARCHIVE_BYTES:
        raise ReplicationDataError(f"ALFRED archive for {series_id} exceeds the safety limit.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ReplicationDataError(f"ALFRED archive for {series_id} is invalid.") from exc
    members = archive.infolist()
    if len(members) > 6 or sum(item.file_size for item in members) > ALFRED_MAX_ARCHIVE_BYTES:
        raise ReplicationDataError(f"ALFRED archive for {series_id} fails the decompression safety limit.")
    for item in members:
        normalized = item.filename.replace("\\", "/")
        if normalized.startswith("/") or "../" in normalized:
            raise ReplicationDataError("ALFRED archive contains an unsafe member path.")
    csv_members = [item for item in members if item.filename.lower().endswith(".csv")]
    if len(csv_members) != 1:
        raise ReplicationDataError(f"ALFRED archive for {series_id} must contain exactly one CSV data file.")
    text = archive.read(csv_members[0]).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    required = {"period_start_date", series_id, "realtime_start_date"}
    if not required.issubset(set(reader.fieldnames or ())):
        raise ReplicationDataError(f"ALFRED CSV for {series_id} is missing initial-release fields.")
    rows: list[AlfredInitialReleaseRow] = []
    seen_periods: set[str] = set()
    for source in reader:
        period = str(source.get("period_start_date") or "").strip()
        realtime = str(source.get("realtime_start_date") or "").strip()
        raw_value = str(source.get(series_id) or "").strip()
        if not period or not realtime or raw_value in {"", ".", "NA", "#NA"}:
            continue
        try:
            period_date = date.fromisoformat(period)
            realtime_date = date.fromisoformat(realtime)
            value = float(raw_value)
        except Exception as exc:
            raise ReplicationDataError(f"ALFRED CSV for {series_id} contains an invalid row.") from exc
        if not math.isfinite(value) or value <= 0:
            raise ReplicationDataError(f"ALFRED CSV for {series_id} contains a non-positive/non-finite index.")
        if realtime_date < period_date:
            raise ReplicationDataError(f"ALFRED initial release for {series_id} predates its observation period.")
        if period in seen_periods:
            raise ReplicationDataError(f"ALFRED initial-release output for {series_id} duplicates {period}.")
        seen_periods.add(period)
        rows.append(AlfredInitialReleaseRow(period, round(value, 12), realtime))
    rows.sort(key=lambda item: (item.period_start_date, item.realtime_start_date))
    if not rows:
        raise ReplicationDataError(f"ALFRED returned no valid initial-release rows for {series_id}.")
    return tuple(rows)


def fetch_alfred_initial_release_series(
    series_id: str,
    *,
    session: Any | None = None,
    timeout: float = 90.0,
) -> AlfredSeriesSnapshot:
    series_id = str(series_id or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{3,20}", series_id):
        raise ValueError("ALFRED series_id must be an uppercase alphanumeric identifier.")
    client = session or requests.Session()
    url = f"{ALFRED_DOWNLOAD_BASE}?seid={series_id}"
    headers = {"User-Agent": ALFRED_USER_AGENT, "Accept": "text/html,application/zip"}
    form_response = _request_with_retry(client, "get", url, headers=headers, timeout=timeout)
    _raise_for_status(form_response)
    observation_start, observation_end, vintages, title = _parse_form(_response_text(form_response), series_id)

    row_index: dict[str, AlfredInitialReleaseRow] = {}
    raw_archives: list[bytes] = []
    metadata: list[dict[str, str]] = []
    for offset in range(0, len(vintages), ALFRED_VINTAGE_BATCH_SIZE):
        batch = vintages[offset: offset + ALFRED_VINTAGE_BATCH_SIZE]
        payload = {
            "form[units]": "lin",
            "form[obs_start_date]": observation_start,
            "form[obs_end_date]": observation_end,
            "form[entered_vintage_dates]": " ".join(batch),
            "form[file_type]": "4",
            "form[file_format]": "csv",
            "form[download_data]": "Download data",
        }
        response = _request_with_retry(client, "post", url, data=payload, headers=headers, timeout=timeout)
        _raise_for_status(response)
        raw = bytes(getattr(response, "content", b""))
        batch_rows = _parse_initial_release_zip(raw, series_id)
        for row in batch_rows:
            prior = row_index.get(row.period_start_date)
            if prior is not None and prior != row:
                raise ReplicationDataError(
                    f"ALFRED batches disagree on the first release for {series_id} {row.period_start_date}."
                )
            row_index[row.period_start_date] = row
        response_headers = getattr(response, "headers", {}) or {}
        metadata.append({
            "content_type": str(response_headers.get("content-type") or ""),
            "content_disposition": str(response_headers.get("content-disposition") or ""),
            "vintage_start": batch[0],
            "vintage_end": batch[-1],
        })
        raw_archives.append(raw)

    rows = tuple(sorted(row_index.values(), key=lambda item: (item.period_start_date, item.realtime_start_date)))
    if len(rows) < 12:
        raise ReplicationDataError(f"ALFRED returned only {len(rows)} usable initial releases for {series_id}.")
    fingerprint = _digest([asdict(item) for item in rows])
    return AlfredSeriesSnapshot(
        series_id=series_id,
        title=title,
        source_url=url,
        retrieved_at=_now_iso(),
        observation_start=observation_start,
        observation_end=observation_end,
        vintage_dates=vintages,
        rows=rows,
        row_fingerprint=fingerprint,
        raw_archives=tuple(raw_archives),
        response_metadata=tuple(metadata),
    )


def _persist_snapshot_bundle(
    data_root: str | os.PathLike[str],
    snapshots: Mapping[str, AlfredSeriesSnapshot],
) -> tuple[str, str, str]:
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    canonical = {
        series_id: {
            "title": snapshot.title,
            "source_url": snapshot.source_url,
            "row_fingerprint": snapshot.row_fingerprint,
            "rows": [asdict(row) for row in snapshot.rows],
        }
        for series_id, snapshot in sorted(snapshots.items())
    }
    snapshot_fingerprint = _digest(canonical)
    snapshot_id = f"ALFREDIR-{snapshot_fingerprint.split(':', 1)[1][:16]}"
    base = root / "public_data" / "alfred_initial_release"
    base.mkdir(parents=True, exist_ok=True)
    target = base / snapshot_id
    revision_policies = {snapshot.revision_policy for snapshot in snapshots.values()}
    if len(revision_policies) != 1:
        raise ReplicationDataError("Replication snapshots disagree on the point-in-time revision policy.")
    manifest = {
        "snapshot_id": snapshot_id,
        "snapshot_fingerprint": snapshot_fingerprint,
        "created_at": _now_iso(),
        "provider": "Federal Reserve Bank of St. Louis ALFRED",
        "underlying_provider": "Bank for International Settlements",
        "access_cost": "FREE",
        "credentials_required": False,
        "point_in_time_policy": next(iter(revision_policies)),
        "source_documentation_url": ALFRED_HELP_URL,
        "source_terms_urls": [FRED_TERMS_URL, BIS_TERMS_URL],
        "series": {
            series_id: {
                "title": snapshot.title,
                "source_url": snapshot.source_url,
                "retrieved_at": snapshot.retrieved_at,
                "row_count": len(snapshot.rows),
                "row_fingerprint": snapshot.row_fingerprint,
                "observation_start": snapshot.rows[0].period_start_date,
                "observation_end": snapshot.rows[-1].period_start_date,
                "first_release_start": snapshot.rows[0].realtime_start_date,
                "first_release_end": snapshot.rows[-1].realtime_start_date,
                "raw_archive_count": len(snapshot.raw_archives),
                "response_metadata": list(snapshot.response_metadata),
            }
            for series_id, snapshot in sorted(snapshots.items())
        },
        "production_status": "RESEARCH_ONLY",
    }
    temp_dir: Path | None = Path(tempfile.mkdtemp(prefix=".alfred-initial-", dir=str(base)))
    try:
        assert temp_dir is not None
        for series_id, snapshot in sorted(snapshots.items()):
            for index, raw in enumerate(snapshot.raw_archives, start=1):
                (temp_dir / f"{series_id}_part{index:02d}.zip").write_bytes(raw)
            with (temp_dir / f"{series_id}_canonical.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("period_start_date", "value", "realtime_start_date"))
                writer.writeheader()
                writer.writerows(asdict(row) for row in snapshot.rows)
        (temp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if target.exists():
            existing_path = target / "manifest.json"
            if not existing_path.exists():
                raise ReplicationDataError(f"Existing snapshot directory is incomplete: {target}")
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            if str(existing.get("snapshot_fingerprint") or "") != snapshot_fingerprint:
                raise ReplicationDataError(f"Snapshot identity collision detected: {snapshot_id}")
        else:
            os.replace(temp_dir, target)
            temp_dir = None
    finally:
        if temp_dir is not None and temp_dir.exists():
            shutil.rmtree(temp_dir)
    return snapshot_id, snapshot_fingerprint, str(target.relative_to(root))


def load_persisted_alfred_snapshot_bundle(
    data_root: str | os.PathLike[str],
    snapshot_id: str,
    *,
    expected_fingerprint: str = "",
    required_series: Sequence[str] = (),
) -> dict[str, AlfredSeriesSnapshot]:
    """Reload and verify a previously sealed ALFRED acquisition bundle.

    This is the fail-closed restart path for an execution that acquired and
    persisted every declared series but failed later in the computation or
    registry transition. It never contacts ALFRED. Canonical rows are
    re-fingerprinted, the bundle identity is recomputed, and every raw archive
    must still be a structurally valid bounded ZIP before any snapshot is
    returned to the executor.
    """
    identity = str(snapshot_id or "").strip()
    if not re.fullmatch(r"ALFREDIR-[0-9a-f]{16}", identity):
        raise ReplicationDataError("Persisted ALFRED snapshot_id is invalid.")
    root = Path(data_root)
    base = (root / "public_data" / "alfred_initial_release").resolve()
    target = (base / identity).resolve()
    if target.parent != base or not target.is_dir():
        raise ReplicationDataError(f"Persisted ALFRED snapshot is missing: {identity}")
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 2_000_000:
        raise ReplicationDataError(f"Persisted ALFRED manifest is missing or oversized: {identity}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReplicationDataError(f"Persisted ALFRED manifest is invalid JSON: {identity}") from exc
    if not isinstance(manifest, dict):
        raise ReplicationDataError("Persisted ALFRED manifest must be an object.")
    if str(manifest.get("snapshot_id") or "") != identity:
        raise ReplicationDataError("Persisted ALFRED snapshot identity does not match its directory.")
    if str(manifest.get("production_status") or "") != "RESEARCH_ONLY":
        raise ReplicationDataError("Persisted ALFRED snapshot lost its RESEARCH_ONLY lock.")
    revision_policy = str(manifest.get("point_in_time_policy") or "")
    if revision_policy not in {
        "INITIAL_RELEASE_ONLY",
        ALFRED_FORM_POINT_IN_TIME_POLICY,
        ALFRED_GRAPH_POINT_IN_TIME_POLICY,
    }:
        raise ReplicationDataError("Persisted ALFRED snapshot has an unsupported point-in-time policy.")
    series_manifest = manifest.get("series")
    if not isinstance(series_manifest, dict) or not series_manifest:
        raise ReplicationDataError("Persisted ALFRED manifest has no series inventory.")
    required = tuple(dict.fromkeys(str(item).strip().upper() for item in required_series if str(item).strip()))
    if required and set(series_manifest) != set(required):
        raise ReplicationDataError("Persisted ALFRED snapshot does not exactly match the required series set.")

    snapshots: dict[str, AlfredSeriesSnapshot] = {}
    for series_id, raw_metadata in sorted(series_manifest.items()):
        if not re.fullmatch(r"[A-Z0-9]{3,20}", str(series_id)) or not isinstance(raw_metadata, dict):
            raise ReplicationDataError("Persisted ALFRED series inventory is malformed.")
        canonical_path = target / f"{series_id}_canonical.csv"
        if not canonical_path.is_file() or canonical_path.stat().st_size > ALFRED_MAX_ARCHIVE_BYTES:
            raise ReplicationDataError(f"Persisted canonical rows are missing or oversized for {series_id}.")
        rows: list[AlfredInitialReleaseRow] = []
        try:
            with canonical_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames != ["period_start_date", "value", "realtime_start_date"]:
                    raise ReplicationDataError(f"Persisted canonical schema changed for {series_id}.")
                for source in reader:
                    period = str(source.get("period_start_date") or "").strip()
                    release = str(source.get("realtime_start_date") or "").strip()
                    try:
                        period_date = date.fromisoformat(period)
                        release_date = date.fromisoformat(release)
                        value = float(str(source.get("value") or ""))
                    except Exception as exc:
                        raise ReplicationDataError(f"Persisted canonical row is invalid for {series_id}.") from exc
                    if release_date < period_date or not math.isfinite(value) or value <= 0:
                        raise ReplicationDataError(f"Persisted canonical row violates causal/value gates for {series_id}.")
                    rows.append(AlfredInitialReleaseRow(period, round(value, 12), release))
        except ReplicationDataError:
            raise
        except Exception as exc:
            raise ReplicationDataError(f"Persisted canonical rows cannot be read for {series_id}.") from exc
        periods = [row.period_start_date for row in rows]
        if not rows or periods != sorted(periods) or len(periods) != len(set(periods)):
            raise ReplicationDataError(f"Persisted canonical periods are empty, unordered or duplicated for {series_id}.")
        row_fingerprint = _digest([asdict(row) for row in rows])
        if row_fingerprint != str(raw_metadata.get("row_fingerprint") or ""):
            raise ReplicationDataError(f"Persisted canonical fingerprint mismatch for {series_id}.")
        if len(rows) != int(raw_metadata.get("row_count") or -1):
            raise ReplicationDataError(f"Persisted canonical row count mismatch for {series_id}.")
        if (
            periods[0] != str(raw_metadata.get("observation_start") or "")
            or periods[-1] != str(raw_metadata.get("observation_end") or "")
            or rows[0].realtime_start_date != str(raw_metadata.get("first_release_start") or "")
            or rows[-1].realtime_start_date != str(raw_metadata.get("first_release_end") or "")
        ):
            raise ReplicationDataError(f"Persisted canonical boundary metadata mismatch for {series_id}.")

        archive_count = int(raw_metadata.get("raw_archive_count") or 0)
        if archive_count < 1 or archive_count > 20:
            raise ReplicationDataError(f"Persisted raw archive inventory is invalid for {series_id}.")
        raw_archives: list[bytes] = []
        for index in range(1, archive_count + 1):
            archive_path = target / f"{series_id}_part{index:02d}.zip"
            if not archive_path.is_file() or archive_path.stat().st_size > ALFRED_MAX_ARCHIVE_BYTES:
                raise ReplicationDataError(f"Persisted raw archive is missing or oversized for {series_id}.")
            raw = archive_path.read_bytes()
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    members = archive.infolist()
                    if not members or len(members) > 2_000 or sum(item.file_size for item in members) > 50_000_000:
                        raise ReplicationDataError(f"Persisted raw archive exceeds structural limits for {series_id}.")
                    if archive.testzip() is not None:
                        raise ReplicationDataError(f"Persisted raw archive CRC check failed for {series_id}.")
            except ReplicationDataError:
                raise
            except Exception as exc:
                raise ReplicationDataError(f"Persisted raw archive is not a valid ZIP for {series_id}.") from exc
            raw_archives.append(raw)
        response_metadata = raw_metadata.get("response_metadata") or ()
        if not isinstance(response_metadata, (list, tuple)) or any(not isinstance(item, dict) for item in response_metadata):
            raise ReplicationDataError(f"Persisted response metadata is invalid for {series_id}.")
        snapshots[series_id] = AlfredSeriesSnapshot(
            series_id=series_id,
            title=str(raw_metadata.get("title") or ""),
            source_url=str(raw_metadata.get("source_url") or ""),
            retrieved_at=str(raw_metadata.get("retrieved_at") or ""),
            observation_start=periods[0],
            observation_end=periods[-1],
            vintage_dates=tuple(row.realtime_start_date for row in rows),
            rows=tuple(rows),
            row_fingerprint=row_fingerprint,
            raw_archives=tuple(raw_archives),
            response_metadata=tuple(dict(item) for item in response_metadata),
            point_in_time_status="PASS",
            revision_policy=revision_policy,
        )

    canonical = {
        series_id: {
            "title": snapshot.title,
            "source_url": snapshot.source_url,
            "row_fingerprint": snapshot.row_fingerprint,
            "rows": [asdict(row) for row in snapshot.rows],
        }
        for series_id, snapshot in sorted(snapshots.items())
    }
    fingerprint = _digest(canonical)
    if fingerprint != str(manifest.get("snapshot_fingerprint") or ""):
        raise ReplicationDataError("Persisted ALFRED bundle fingerprint mismatch.")
    if identity != f"ALFREDIR-{fingerprint.split(':', 1)[1][:16]}":
        raise ReplicationDataError("Persisted ALFRED bundle id is not derived from its fingerprint.")
    if expected_fingerprint and fingerprint != str(expected_fingerprint):
        raise ReplicationDataError("Persisted ALFRED bundle does not match the expected fingerprint.")
    return snapshots


def _paired_forecast_test(candidate_errors: Sequence[float], baseline_errors: Sequence[float]) -> dict[str, Any]:
    if len(candidate_errors) != len(baseline_errors) or len(candidate_errors) < 8:
        return {
            "method": "DIEBOLD_MARIANO_NORMAL_APPROX_H1",
            "status": "INSUFFICIENT_OBSERVATIONS",
            "sample_size": min(len(candidate_errors), len(baseline_errors)),
        }
    differential = [float(base) ** 2 - float(candidate) ** 2 for candidate, base in zip(candidate_errors, baseline_errors)]
    mean_diff = statistics.fmean(differential)
    variance = statistics.variance(differential) if len(differential) > 1 else 0.0
    if variance <= 0:
        statistic = 0.0 if mean_diff == 0 else math.copysign(float("inf"), mean_diff)
        p_value = 1.0 if mean_diff == 0 else 0.0
    else:
        raw_statistic = mean_diff / math.sqrt(variance / len(differential))
        # Harvey-Leybourne-Newbold finite-sample correction for forecast horizon h=1.
        statistic = raw_statistic * math.sqrt((len(differential) - 1) / len(differential))
        p_value = math.erfc(abs(statistic) / math.sqrt(2.0))
    return {
        "method": "DIEBOLD_MARIANO_NORMAL_APPROX_H1",
        "status": "COMPUTED",
        "sample_size": len(differential),
        "mean_squared_loss_advantage": round(mean_diff, 12),
        "statistic": round(statistic, 8) if math.isfinite(statistic) else statistic,
        "p_value_two_sided": round(max(0.0, min(1.0, p_value)), 10),
        "direction": "CANDIDATE_BETTER" if mean_diff > 0 else "RANDOM_WALK_BETTER" if mean_diff < 0 else "TIE",
        "caveat": "Normal approximation with horizon one; multiplicity is controlled separately with Holm-Bonferroni.",
    }


def _apply_holm(results: list[dict[str, Any]]) -> None:
    eligible: list[tuple[int, float]] = []
    for index, result in enumerate(results):
        test = result.get("forecast_comparison") or {}
        if test.get("status") == "COMPUTED":
            eligible.append((index, float(test.get("p_value_two_sided") or 1.0)))
    eligible.sort(key=lambda item: item[1])
    running = 0.0
    total = len(eligible)
    for rank, (index, p_value) in enumerate(eligible, start=1):
        adjusted = min(1.0, (total - rank + 1) * p_value)
        running = max(running, adjusted)
        test = dict(results[index]["forecast_comparison"])
        test["holm_adjusted_p_value"] = round(running, 10)
        test["holm_family_size"] = total
        test["candidate_better_after_holm_5pct"] = bool(
            test.get("direction") == "CANDIDATE_BETTER" and running <= 0.05
        )
        results[index]["forecast_comparison"] = test


def _values_for_variant(
    variant_id: str,
    real_values: Sequence[float],
    nominal_values: Sequence[float],
) -> list[float]:
    if variant_id == "REAL_EER_LOG":
        return [math.log(value) for value in real_values]
    if variant_id == "NOMINAL_EER_LOG":
        return [math.log(value) for value in nominal_values]
    if variant_id == "RELATIVE_PRICE_WEDGE":
        return [math.log(real) - math.log(nominal) for real, nominal in zip(real_values, nominal_values)]
    raise ValueError(f"Unsupported replication measurement variant: {variant_id}")


def _select_strict_event_time_support(
    aligned_rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build a causal, strictly unique release-event sequence.

    ALFRED may first expose two reference periods on the same day. Treating one
    co-released value as the lag of the other would leak information within the
    event. The conservative rule keeps only the latest reference period in each
    release event, then excludes later backfills that do not advance reference
    time. Raw rows remain preserved in the point-in-time snapshot.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for source in aligned_rows:
        row = dict(source)
        available_at = str(row.get("available_at") or "")
        period = str(row.get("period_start_date") or "")
        try:
            available_date = date.fromisoformat(available_at)
            period_date = date.fromisoformat(period)
        except Exception as exc:
            raise ReplicationDataError("Aligned replication support contains an invalid ISO date.") from exc
        if available_date < period_date:
            raise ReplicationDataError(
                f"Aligned replication row {period} is marked available before its reference period."
            )
        grouped.setdefault(available_at, []).append(row)

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    last_period = ""
    for available_at in sorted(grouped):
        event_rows = sorted(grouped[available_at], key=lambda row: str(row["period_start_date"]))
        selected = event_rows[-1]
        for row in event_rows[:-1]:
            excluded.append({
                **row,
                "exclusion_reason": "CO_RELEASE_KEEP_LATEST_REFERENCE_PERIOD",
                "selected_period_start_date": selected["period_start_date"],
            })
        selected_period = str(selected["period_start_date"])
        if last_period and selected_period <= last_period:
            excluded.append({
                **selected,
                "exclusion_reason": "NON_ADVANCING_BACKFILL",
                "last_included_period_start_date": last_period,
            })
            continue
        included.append(selected)
        last_period = selected_period

    labels = [str(row["available_at"]) for row in included]
    periods = [str(row["period_start_date"]) for row in included]
    if labels != sorted(labels) or len(labels) != len(set(labels)):
        raise ReplicationDataError("Event-time support is not strictly increasing and unique.")
    if periods != sorted(periods) or len(periods) != len(set(periods)):
        raise ReplicationDataError("Event-time support does not preserve advancing reference periods.")
    return included, excluded


def execute_alfred_bis_replication(
    protocol: Any,
    *,
    data_root: str | os.PathLike[str],
    fetcher: Callable[[str], AlfredSeriesSnapshot] | None = None,
) -> IndependentReplicationRecord:
    record = _record(protocol)
    if record.protocol_version != INDEPENDENT_REPLICATION_PROTOCOL_VERSION:
        raise ValueError("Unsupported independent-replication protocol version.")
    if record.status != "FROZEN" or record.execution_status != "NOT_RUN":
        raise ValueError("Only a persisted, unexecuted FROZEN replication protocol may run.")
    if record.event_time_support_policy != REPLICATION_EVENT_TIME_SUPPORT_POLICY:
        raise ValueError(
            "Frozen replication lacks the current co-release/backfill event-time policy; "
            "freeze a new protocol before requesting data."
        )
    if _digest(_protocol_payload(asdict(record))) != record.protocol_fingerprint:
        raise ValueError("Replication protocol fingerprint mismatch; execution refused.")
    if record.automatic_promotion_authorized or record.production_status != "RESEARCH_ONLY":
        raise ValueError("Replication production/promotion lock is not intact.")

    if fetcher is None:
        if record.source_access_mode == ALFRED_FORM_ACCESS_MODE:
            effective_fetcher = fetch_alfred_initial_release_series
            expected_revision_policy = "INITIAL_RELEASE_ONLY"
        elif record.source_access_mode == ALFRED_GRAPH_ACCESS_MODE:
            effective_fetcher = fetch_alfred_graph_initial_release_series
            expected_revision_policy = ALFRED_GRAPH_POINT_IN_TIME_POLICY
        else:
            raise ValueError(f"Unsupported frozen ALFRED access mode: {record.source_access_mode or 'MISSING'}")
    else:
        effective_fetcher = fetcher
        expected_revision_policy = (
            ALFRED_GRAPH_POINT_IN_TIME_POLICY
            if record.source_access_mode == ALFRED_GRAPH_ACCESS_MODE
            else "INITIAL_RELEASE_ONLY"
        )
    required_series = tuple(dict.fromkeys(
        series_id
        for market in record.markets
        for series_id in (
            record.series_matrix[market]["real_series_id"],
            record.series_matrix[market]["nominal_series_id"],
        )
    ))
    snapshots = {series_id: effective_fetcher(series_id) for series_id in required_series}
    for series_id, snapshot in snapshots.items():
        if snapshot.series_id != series_id:
            raise ReplicationDataError(f"Fetcher returned {snapshot.series_id} for requested {series_id}.")
        if snapshot.point_in_time_status != "PASS" or snapshot.revision_policy != expected_revision_policy:
            raise ReplicationDataError(
                f"Series {series_id} is not certified for frozen point-in-time policy {expected_revision_policy}."
            )
    snapshot_id, snapshot_fingerprint, snapshot_path = _persist_snapshot_bundle(data_root, snapshots)

    results: list[dict[str, Any]] = []
    for market in record.markets:
        matrix = record.series_matrix[market]
        real_snapshot = snapshots[matrix["real_series_id"]]
        nominal_snapshot = snapshots[matrix["nominal_series_id"]]
        real_index = {row.period_start_date: row for row in real_snapshot.rows}
        nominal_index = {row.period_start_date: row for row in nominal_snapshot.rows}
        common_periods = sorted(set(real_index).intersection(nominal_index))
        if len(common_periods) < record.min_common_rows:
            raise ReplicationDataError(
                f"{market} has only {len(common_periods)} common initial-release rows; {record.min_common_rows} required."
            )
        aligned_rows: list[dict[str, Any]] = []
        for period in common_periods:
            real_row = real_index[period]
            nominal_row = nominal_index[period]
            available_at = max(real_row.realtime_start_date, nominal_row.realtime_start_date)
            aligned_rows.append({
                "period_start_date": period,
                "available_at": available_at,
                "real_value": real_row.value,
                "nominal_value": nominal_row.value,
                "real_first_release": real_row.realtime_start_date,
                "nominal_first_release": nominal_row.realtime_start_date,
            })
        event_time_rows, excluded_rows = _select_strict_event_time_support(aligned_rows)
        if len(event_time_rows) < record.min_common_rows:
            raise ReplicationDataError(
                f"{market} has only {len(event_time_rows)} causal release-event rows after "
                f"co-release/backfill exclusions; {record.min_common_rows} required."
            )
        release_dates = [str(row["available_at"]) for row in event_time_rows]
        real_values = [float(row["real_value"]) for row in event_time_rows]
        nominal_values = [float(row["nominal_value"]) for row in event_time_rows]
        co_release_excluded = sum(
            row.get("exclusion_reason") == "CO_RELEASE_KEEP_LATEST_REFERENCE_PERIOD"
            for row in excluded_rows
        )
        backfill_excluded = sum(
            row.get("exclusion_reason") == "NON_ADVANCING_BACKFILL"
            for row in excluded_rows
        )
        aligned_fingerprint = _digest({
            "event_time_support_policy": record.event_time_support_policy,
            "included_rows": event_time_rows,
            "excluded_rows": excluded_rows,
        })
        for variant in record.measurement_variants:
            variant_id = str(variant.get("variant_id") or "")
            values = _values_for_variant(variant_id, real_values, nominal_values)
            observable_id = f"ALFRED_BIS_{market}_{variant_id}"
            spec = {
                "experiment_id": record.experiment_id,
                "status": "READY",
                "experimental_family": "OU_MEAN_REVERTING_SDE",
                "seed": 17,
                "code_policy": "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC",
                "dataset_contract": {
                    "contract_id": record.replication_id,
                    "train_fraction": record.train_fraction,
                    "max_rows": 250000,
                },
            }
            run = run_historical_oos_experiment(
                spec,
                values,
                labels=release_dates,
                train_fraction=record.train_fraction,
                attempt_id=_stable_id("RATTEMPT", record.replication_id, market, variant_id),
                evidence_unit_id=_stable_id("REVIDENCE", snapshot_fingerprint, market, variant_id),
                data_contract_id=record.replication_id,
                data_contract_audit_id=_stable_id("RAUDIT", record.replication_id),
                dataset_manifest_id=snapshot_id,
                observable_id=observable_id,
                forecast_horizon=record.forecast_horizon,
                selection_context={
                    "replication_id": record.replication_id,
                    "reference_run_id": record.reference_run_id,
                    "market": market,
                    "variant_id": variant_id,
                    "observed_screens": len(record.markets) * len(record.measurement_variants),
                    "multiplicity_policy": record.multiplicity_policy,
                },
            )
            run_row = asdict(run)
            random_walk_errors = run_row["baseline_errors"].get("Random Walk / Last Observation") or ()
            forecast_test = _paired_forecast_test(run_row["candidate_errors"], random_walk_errors)
            results.append({
                "result_id": _stable_id("IRR", record.replication_id, market, variant_id, run.run_id),
                "market": market,
                "market_label": matrix["label"],
                "variant_id": variant_id,
                "variant_label": variant.get("label"),
                "formula": variant.get("formula"),
                "real_series_id": matrix["real_series_id"],
                "nominal_series_id": matrix["nominal_series_id"],
                "aligned_support_fingerprint": aligned_fingerprint,
                "event_time_support_policy": record.event_time_support_policy,
                "raw_common_row_count": len(aligned_rows),
                "co_release_excluded_count": co_release_excluded,
                "non_advancing_backfill_excluded_count": backfill_excluded,
                "excluded_support_rows": excluded_rows,
                "row_count": len(values),
                "run_id": run.run_id,
                "verdict": run.verdict,
                "train_size": run.train_size,
                "test_size": run.test_size,
                "split_timestamp": run.split_timestamp,
                "data_fingerprint": run.data_fingerprint,
                "forecast_trace_fingerprint": run.forecast_trace_fingerprint,
                "candidate_metrics": run_row["candidate_metrics"],
                "baseline_metrics": run_row["baseline_metrics"],
                "deltas_vs_baseline": run_row["deltas_vs_baseline"],
                "fitted_parameters": run_row["fitted_parameters"],
                "chronological_split_robustness": run_row["robustness"],
                "forecast_origin_timestamps": run_row["forecast_origin_timestamps"],
                "forecast_timestamps": run_row["forecast_timestamps"],
                "actual_values": run_row["actual_values"],
                "candidate_predictions": run_row["candidate_predictions"],
                "candidate_errors": run_row["candidate_errors"],
                "baseline_predictions": run_row["baseline_predictions"],
                "baseline_errors": run_row["baseline_errors"],
                "forecast_comparison": forecast_test,
                "production_status": "RESEARCH_ONLY",
            })
    _apply_holm(results)

    promising = sum(result["verdict"] == "PROMISING_OOS" for result in results)
    no_improvement = sum(result["verdict"] == "NO_OOS_IMPROVEMENT" for result in results)
    if no_improvement == len(results):
        outcome = "CONSISTENT_NO_OOS_IMPROVEMENT"
    elif promising == len(results):
        outcome = "CONSISTENT_PROMISING_REQUIRES_EXTERNAL_REVIEW"
    else:
        outcome = "MIXED_REPLICATION_EVIDENCE"
    execution_fingerprint = _digest({
        "protocol_fingerprint": record.protocol_fingerprint,
        "snapshot_fingerprint": snapshot_fingerprint,
        "results": [{
            "result_id": row["result_id"],
            "verdict": row["verdict"],
            "data_fingerprint": row["data_fingerprint"],
            "forecast_trace_fingerprint": row["forecast_trace_fingerprint"],
            "holm_adjusted_p_value": (row.get("forecast_comparison") or {}).get("holm_adjusted_p_value"),
        } for row in results],
        "outcome": outcome,
    })
    completed_at = _now_iso()
    # JSON registries deserialize tuple-valued dataclass fields as lists.  The
    # executor must therefore normalize the frozen lifecycle before appending
    # the terminal transition; otherwise a correctly persisted protocol can be
    # tested in memory but fail only after a real save -> reload cycle.
    lifecycle = tuple(record.lifecycle_history) + ({
        "at": completed_at,
        "from": "FROZEN",
        "to": "COMPLETE",
        "actor": "SYSTEM_ON_EXPLICIT_USER_ACTION",
        "reason": f"Frozen independent-market replication executed through {record.source_access_mode}.",
        "evidence_refs": [record.reference_run_id, record.reference_measurement_report_id, snapshot_id],
    },)
    return replace(
        record,
        point_in_time_status="PASS",
        independence_gate_status="PASS",
        status="COMPLETE",
        execution_status="COMPLETE",
        completed_at=completed_at,
        snapshot_id=snapshot_id,
        snapshot_path=snapshot_path,
        source_snapshot_fingerprint=snapshot_fingerprint,
        execution_fingerprint=execution_fingerprint,
        replication_outcome=outcome,
        result_count=len(results),
        promising_result_count=promising,
        no_improvement_result_count=no_improvement,
        results=tuple(results),
        lifecycle_history=lifecycle,
        blockers=(),
    )


__all__ = [
    "ALFRED_BIS_MARKETS",
    "ALFRED_FORM_ACCESS_MODE",
    "ALFRED_GRAPH_ACCESS_MODE",
    "ALFRED_GRAPH_BASE",
    "ALFRED_HELP_URL",
    "BIS_TERMS_URL",
    "FRED_TERMS_URL",
    "INDEPENDENT_REPLICATION_PROTOCOL_VERSION",
    "REPLICATION_EVENT_TIME_SUPPORT_POLICY",
    "IndependentReplicationRecord",
    "AlfredInitialReleaseRow",
    "AlfredSeriesSnapshot",
    "ReplicationDataError",
    "build_alfred_bis_replication_protocol",
    "execute_alfred_bis_replication",
    "fetch_alfred_graph_initial_release_series",
    "fetch_alfred_initial_release_series",
    "load_persisted_alfred_snapshot_bundle",
]
