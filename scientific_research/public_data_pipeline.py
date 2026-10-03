from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


UTC = timezone.utc
PUBLIC_DATA_PARSER_VERSION = "SRB_PUBLIC_DATA_V1"
PUBLIC_DATASET_ID = "FHFA_US_HPI_TO_BLS_RENT_REVISED"
FHFA_HPI_URL = "https://www.fhfa.gov/hpi/download/monthly/hpi_master.csv"
BLS_HOUSING_URL = "https://download.bls.gov/pub/time.series/cu/cu.data.12.USHousing"
FHFA_TERMS_URL = "https://www.fhfa.gov/faqs/hpi"
BLS_TERMS_URL = "https://www.bls.gov/bls/linksite.htm"
FHFA_SERIES_ID = "FHFA_TRADITIONAL_PURCHASE_ONLY_MONTHLY_US_SA"
BLS_RENT_SERIES_ID = "CUSR0000SEHA"
AVAILABILITY_POLICY = "REFERENCE_MONTH_END_PLUS_90_DAYS_CONSERVATIVE_PROXY"
DEFAULT_USER_AGENT = (
    "ScientificResearchBrain/0.6.4.1 "
    "(research-only; contact=research-operations@users.noreply.github.com)"
)

# ECB Data Portal / Real Time Database (RTD).  These URLs deliberately pin a
# bounded start period: the 2018-present window already exceeds the laboratory's
# 40-observation minimum and avoids downloading the full RTD history.
ECB_RTD_DATASET_ID = "ECB_RTD_EER_NOMINAL_REAL_FIRST_VINTAGES"
ECB_RTD_NOMINAL_SERIES_KEY = "RTD.M.S0.N.E_EN00_BGR.X"
ECB_RTD_REAL_SERIES_KEY = "RTD.M.S0.N.E_ERC0_BGR.X"
ECB_RTD_NOMINAL_URL = (
    "https://data-api.ecb.europa.eu/service/data/RTD/M.S0.N.E_EN00_BGR.X"
    "?startPeriod=2018-01&format=csvdata&includeHistory=true"
)
ECB_RTD_REAL_URL = (
    "https://data-api.ecb.europa.eu/service/data/RTD/M.S0.N.E_ERC0_BGR.X"
    "?startPeriod=2018-01&format=csvdata&includeHistory=true"
)
ECB_RTD_TERMS_URL = "https://www.ecb.europa.eu/services/disclaimer/html/index.en.html"
ECB_RTD_USAGE_POLICY_URL = (
    "https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/"
    "html/usage_policy.en.html"
)
ECB_RTD_AVAILABILITY_POLICY = "LATEST_REFERENCE_PERIOD_PER_UNIQUE_FIRST_RECORDED_RELEASE_EVENT"
ECB_RTD_PARSER_VERSION = "SRB_ECB_RTD_FIRST_VINTAGE_V1"
ECB_DEFAULT_USER_AGENT = (
    "ScientificResearchBrain/0.6.4.1 "
    "(research-only; contact=research-operations@users.noreply.github.com)"
)
ECB_RTD_COLUMNS = (
    "KEY", "FREQ", "REF_AREA", "ADJUSTMENT", "RT_ECON_CONCEPT", "RT_DENOM",
    "TIME_PERIOD", "OBS_VALUE", "OBS_STATUS", "OBS_CONF", "OBS_PRE_BREAK", "OBS_COM",
    "TIME_FORMAT", "COLLECTION", "COMPILING_ORG", "DISS_ORG", "DOM_SER_IDS", "PUBL_MU",
    "PUBL_PUBLIC", "UNIT_INDEX_BASE", "UNIT_PRICE_BASE", "AGG_EQUN", "COMPILATION",
    "COVERAGE", "DECIMALS", "SOURCE_AGENCY", "SOURCE_DETAIL", "TITLE", "TITLE_COMPL",
    "UNIT", "UNIT_MULT", "ACTION", "VALID_FROM", "VALID_TO",
)


class PublicDataError(RuntimeError):
    """Fail-closed public-data acquisition or validation error."""


@dataclass(frozen=True)
class RetrievedSource:
    source_id: str
    url: str
    terms_url: str
    retrieved_at: str
    sha256: str
    byte_count: int
    content_type: str = ""
    etag: str = ""
    last_modified: str = ""
    content: bytes = field(default=b"", repr=False, compare=False)


@dataclass(frozen=True)
class PublicDataManifest:
    snapshot_id: str
    created_at: str
    dataset_id: str
    dataset_label: str
    row_count: int
    start_reference_period: str
    end_reference_period: str
    start_timestamp: str
    end_timestamp: str
    dataset_fingerprint: str
    parser_version: str
    revision_policy: str
    availability_policy: str
    availability_time_quality: str
    price_series_id: str
    anchor_series_id: str
    source_metadata: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    status: str = "VALIDATED_WITH_WARNINGS"
    production_status: str = "RESEARCH_ONLY"


@dataclass(frozen=True)
class PublicDataBundle:
    manifest: PublicDataManifest
    rows: tuple[dict[str, Any], ...]
    sources: tuple[RetrievedSource, ...] = field(default=(), repr=False, compare=False)


FetchResult = tuple[bytes, Mapping[str, str], str]
FetchCallable = Callable[[str, int, int, str], FetchResult]


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _default_fetch(url: str, timeout: int, max_bytes: int, user_agent: str) -> FetchResult:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/csv,text/plain,application/octet-stream;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()))
            if status != 200:
                raise PublicDataError(f"Official source returned HTTP {status}.")
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise PublicDataError(f"Official source exceeded the {max_bytes:,}-byte safety limit.")
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            final_url = str(response.geturl())
    except PublicDataError:
        raise
    except urllib.error.HTTPError as exc:
        raise PublicDataError(f"Official source returned HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        reason = type(getattr(exc, "reason", exc)).__name__
        raise PublicDataError(f"Official source could not be reached ({reason}).") from exc
    except TimeoutError as exc:
        raise PublicDataError("Official source timed out.") from exc
    if not content:
        raise PublicDataError("Official source returned an empty payload.")
    prefix = content[:256].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise PublicDataError("Official source returned HTML instead of the declared dataset.")
    return content, headers, final_url


def _retrieve(
    *,
    source_id: str,
    url: str,
    terms_url: str,
    fetched_at: datetime,
    timeout: int,
    max_bytes: int,
    user_agent: str,
    fetcher: FetchCallable,
) -> RetrievedSource:
    content, headers, final_url = fetcher(url, timeout, max_bytes, user_agent)
    if not isinstance(content, (bytes, bytearray)):
        raise PublicDataError(f"{source_id} fetcher must return raw bytes.")
    raw = bytes(content)
    if not raw:
        raise PublicDataError(f"{source_id} returned an empty payload.")
    if len(raw) > max_bytes:
        raise PublicDataError(f"{source_id} exceeded the {max_bytes:,}-byte safety limit.")
    prefix = raw[:256].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        raise PublicDataError(f"{source_id} returned HTML instead of the declared dataset.")
    return RetrievedSource(
        source_id=source_id,
        url=final_url or url,
        terms_url=terms_url,
        retrieved_at=_iso(fetched_at),
        sha256=_sha256(raw),
        byte_count=len(raw),
        content_type=str(headers.get("content-type") or ""),
        etag=str(headers.get("etag") or ""),
        last_modified=str(headers.get("last-modified") or ""),
        content=raw,
    )


def _decode(content: bytes, source_id: str) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PublicDataError(f"{source_id} is not valid UTF-8 text.") from exc


def _positive_number(value: Any, field: str) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise PublicDataError(f"{field} contains a non-numeric value.") from exc
    if not math.isfinite(number) or number <= 0:
        raise PublicDataError(f"{field} must remain finite and strictly positive.")
    return number


def parse_fhfa_monthly_us_sa(content: bytes) -> dict[tuple[int, int], float]:
    text = _decode(content, "FHFA_HPI")
    reader = csv.DictReader(io.StringIO(text))
    required = {
        "hpi_type", "hpi_flavor", "frequency", "place_name", "place_id",
        "yr", "period", "index_sa",
    }
    if reader.fieldnames is None or not required.issubset({str(name).strip() for name in reader.fieldnames}):
        raise PublicDataError("FHFA HPI payload is missing required columns.")
    values: dict[tuple[int, int], float] = {}
    for raw_row in reader:
        row = {str(key).strip(): str(value or "").strip() for key, value in raw_row.items()}
        if not (
            row.get("hpi_type") == "traditional"
            and row.get("hpi_flavor") == "purchase-only"
            and row.get("frequency") == "monthly"
            and row.get("place_id") == "USA"
            and row.get("place_name") == "United States"
        ):
            continue
        try:
            year = int(row.get("yr") or "")
            month = int(row.get("period") or "")
        except ValueError as exc:
            raise PublicDataError("FHFA HPI contains an invalid year or month.") from exc
        if not 1900 <= year <= 2200 or not 1 <= month <= 12:
            raise PublicDataError("FHFA HPI contains an out-of-range year or month.")
        key = (year, month)
        if key in values:
            raise PublicDataError(f"FHFA HPI contains a duplicate observation for {year:04d}-{month:02d}.")
        values[key] = _positive_number(row.get("index_sa"), "FHFA index_sa")
    if len(values) < 40:
        raise PublicDataError("FHFA HPI returned fewer than 40 usable U.S. monthly observations.")
    return values


def parse_bls_rent_sa(content: bytes, *, series_id: str = BLS_RENT_SERIES_ID) -> dict[tuple[int, int], float]:
    text = _decode(content, "BLS_RENT")
    reader = csv.DictReader(io.StringIO(text), delimiter="\t")
    if reader.fieldnames is None:
        raise PublicDataError("BLS housing payload has no header.")
    normalized_fields = {str(name).strip() for name in reader.fieldnames}
    if not {"series_id", "year", "period", "value"}.issubset(normalized_fields):
        raise PublicDataError("BLS housing payload is missing required columns.")
    values: dict[tuple[int, int], float] = {}
    for raw_row in reader:
        row = {str(key).strip(): str(value or "").strip() for key, value in raw_row.items()}
        if row.get("series_id") != series_id:
            continue
        period = row.get("period") or ""
        if len(period) != 3 or not period.startswith("M") or not period[1:].isdigit():
            continue
        month = int(period[1:])
        if not 1 <= month <= 12:
            continue
        raw_value = row.get("value") or ""
        if raw_value in {"", "-"}:
            continue
        try:
            year = int(row.get("year") or "")
        except ValueError as exc:
            raise PublicDataError("BLS housing payload contains an invalid year.") from exc
        if not 1900 <= year <= 2200:
            raise PublicDataError("BLS housing payload contains an out-of-range year.")
        key = (year, month)
        if key in values:
            raise PublicDataError(f"BLS rent series contains a duplicate observation for {year:04d}-{month:02d}.")
        values[key] = _positive_number(raw_value, f"BLS {series_id} value")
    if len(values) < 40:
        raise PublicDataError(f"BLS series {series_id} returned fewer than 40 usable monthly observations.")
    return values


def _month_end(year: int, month: int) -> datetime:
    if month == 12:
        next_month = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        next_month = datetime(year, month + 1, 1, tzinfo=UTC)
    return next_month - timedelta(days=1)


def _source_metadata(source: RetrievedSource) -> dict[str, Any]:
    row = asdict(source)
    row.pop("content", None)
    return row


def build_fhfa_bls_housing_bundle(
    *,
    fhfa_content: bytes,
    bls_content: bytes,
    fetched_at: datetime | None = None,
    fhfa_headers: Mapping[str, str] | None = None,
    bls_headers: Mapping[str, str] | None = None,
    fhfa_url: str = FHFA_HPI_URL,
    bls_url: str = BLS_HOUSING_URL,
    start_year: int = 1991,
    availability_lag_days: int = 90,
) -> PublicDataBundle:
    fetched = fetched_at or _now()
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    fetched = fetched.astimezone(UTC)
    if not 60 <= int(availability_lag_days) <= 180:
        raise PublicDataError("The conservative availability lag must be between 60 and 180 days.")
    fhfa_source = RetrievedSource(
        source_id="FHFA_HPI",
        url=fhfa_url,
        terms_url=FHFA_TERMS_URL,
        retrieved_at=_iso(fetched),
        sha256=_sha256(fhfa_content),
        byte_count=len(fhfa_content),
        content_type=str((fhfa_headers or {}).get("content-type") or ""),
        etag=str((fhfa_headers or {}).get("etag") or ""),
        last_modified=str((fhfa_headers or {}).get("last-modified") or ""),
        content=fhfa_content,
    )
    bls_source = RetrievedSource(
        source_id="BLS_RENT",
        url=bls_url,
        terms_url=BLS_TERMS_URL,
        retrieved_at=_iso(fetched),
        sha256=_sha256(bls_content),
        byte_count=len(bls_content),
        content_type=str((bls_headers or {}).get("content-type") or ""),
        etag=str((bls_headers or {}).get("etag") or ""),
        last_modified=str((bls_headers or {}).get("last-modified") or ""),
        content=bls_content,
    )
    hpi = parse_fhfa_monthly_us_sa(fhfa_content)
    rent = parse_bls_rent_sa(bls_content)
    common = sorted(key for key in set(hpi).intersection(rent) if key[0] >= int(start_year))
    rows: list[dict[str, Any]] = []
    for year, month in common:
        reference_end = _month_end(year, month)
        available_at = reference_end + timedelta(days=int(availability_lag_days), hours=14)
        if available_at > fetched:
            continue
        reference_period = f"{year:04d}-{month:02d}"
        rows.append({
            "timestamp": _iso(available_at),
            "reference_period": reference_period,
            "price": round(hpi[(year, month)], 8),
            "fundamental_anchor": round(rent[(year, month)], 8),
            "fundamental_release_timestamp": _iso(available_at),
            "availability_policy": AVAILABILITY_POLICY,
            "price_series_id": FHFA_SERIES_ID,
            "anchor_series_id": BLS_RENT_SERIES_ID,
            "fhfa_raw_sha256": fhfa_source.sha256,
            "bls_raw_sha256": bls_source.sha256,
            "snapshot_observed_at": _iso(fetched),
        })
    if len(rows) < 40:
        raise PublicDataError("FHFA/BLS join produced fewer than 40 causally available observations.")
    timestamps = [str(row["timestamp"]) for row in rows]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise PublicDataError("FHFA/BLS join did not produce strict unique chronology.")
    source_metadata = (_source_metadata(fhfa_source), _source_metadata(bls_source))
    fingerprint_payload = {
        "dataset_id": PUBLIC_DATASET_ID,
        "parser_version": PUBLIC_DATA_PARSER_VERSION,
        "availability_policy": AVAILABILITY_POLICY,
        "source_sha256": [fhfa_source.sha256, bls_source.sha256],
        "rows": rows,
    }
    fingerprint = hashlib.sha256(_canonical_json(fingerprint_payload).encode("utf-8")).hexdigest()
    snapshot_id = f"PUBDATA-{fetched.strftime('%Y%m%dT%H%M%SZ')}-{fingerprint[:12]}"
    warnings = (
        "CURRENT-VIEW REVISED HISTORY: FHFA and BLS snapshots do not reconstruct every historical first release.",
        "Availability timestamps use a conservative reference-month-end plus 90-day proxy, not observed historical release timestamps.",
        "This pilot is valid only under REVISED_WITH_RISK_FLAG and must not be represented as point-in-time vintage evidence.",
    )
    manifest = PublicDataManifest(
        snapshot_id=snapshot_id,
        created_at=_iso(fetched),
        dataset_id=PUBLIC_DATASET_ID,
        dataset_label="FHFA U.S. purchase-only HPI / BLS rent log-ratio pilot",
        row_count=len(rows),
        start_reference_period=str(rows[0]["reference_period"]),
        end_reference_period=str(rows[-1]["reference_period"]),
        start_timestamp=str(rows[0]["timestamp"]),
        end_timestamp=str(rows[-1]["timestamp"]),
        dataset_fingerprint=fingerprint,
        parser_version=PUBLIC_DATA_PARSER_VERSION,
        revision_policy="REVISED_WITH_RISK_FLAG",
        availability_policy=AVAILABILITY_POLICY,
        availability_time_quality="CONSERVATIVE_PROXY",
        price_series_id=FHFA_SERIES_ID,
        anchor_series_id=BLS_RENT_SERIES_ID,
        source_metadata=source_metadata,
        warnings=warnings,
    )
    return PublicDataBundle(manifest=manifest, rows=tuple(rows), sources=(fhfa_source, bls_source))


def fetch_fhfa_bls_housing_bundle(
    *,
    timeout: int = 45,
    user_agent: str = DEFAULT_USER_AGENT,
    fetched_at: datetime | None = None,
    fetcher: FetchCallable | None = None,
) -> PublicDataBundle:
    fetched = fetched_at or _now()
    active_fetcher = fetcher or _default_fetch
    fhfa = _retrieve(
        source_id="FHFA_HPI",
        url=FHFA_HPI_URL,
        terms_url=FHFA_TERMS_URL,
        fetched_at=fetched,
        timeout=int(timeout),
        max_bytes=25_000_000,
        user_agent=user_agent,
        fetcher=active_fetcher,
    )
    bls = _retrieve(
        source_id="BLS_RENT",
        url=BLS_HOUSING_URL,
        terms_url=BLS_TERMS_URL,
        fetched_at=fetched,
        timeout=int(timeout),
        max_bytes=5_000_000,
        user_agent=user_agent,
        fetcher=active_fetcher,
    )
    return build_fhfa_bls_housing_bundle(
        fhfa_content=fhfa.content,
        bls_content=bls.content,
        fetched_at=fetched,
        fhfa_headers={
            "content-type": fhfa.content_type,
            "etag": fhfa.etag,
            "last-modified": fhfa.last_modified,
        },
        bls_headers={
            "content-type": bls.content_type,
            "etag": bls.etag,
            "last-modified": bls.last_modified,
        },
        fhfa_url=fhfa.url,
        bls_url=bls.url,
    )


def _parse_aware_timestamp(value: Any, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise PublicDataError(f"ECB RTD {field} is missing.")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PublicDataError(f"ECB RTD {field} is not a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PublicDataError(f"ECB RTD {field} must include an explicit UTC offset.")
    return parsed.astimezone(UTC)


def parse_ecb_rtd_first_vintages(
    content: bytes,
    *,
    series_key: str,
) -> dict[str, dict[str, Any]]:
    """Parse one exact ECB RTD series and retain its first recorded vintage.

    The API's ``includeHistory=true`` response also contains later replacements
    and deletion tombstones.  Tombstones remain preserved in the raw source
    bytes; only a numeric ``Replace`` event can establish an available vintage.
    Identical repeated rows are harmless, while conflicting rows for the same
    period/vintage timestamp fail closed.
    """

    expected_key = str(series_key or "").strip()
    key_parts = expected_key.split(".")
    if len(key_parts) != 6 or key_parts[:4] != ["RTD", "M", "S0", "N"] or key_parts[5] != "X":
        raise PublicDataError("ECB RTD series_key is not one of the expected monthly RTD key shapes.")
    text = _decode(content, expected_key)
    reader = csv.DictReader(io.StringIO(text))
    fields = tuple(str(name) for name in (reader.fieldnames or ()))
    if fields != ECB_RTD_COLUMNS:
        raise PublicDataError("ECB RTD payload columns do not match the pinned csvdata schema.")

    expected_dimensions = {
        "KEY": expected_key,
        "FREQ": "M",
        "REF_AREA": "S0",
        "ADJUSTMENT": "N",
        "RT_ECON_CONCEPT": key_parts[4],
        "RT_DENOM": "X",
    }
    replacement_rows: dict[tuple[str, str], dict[str, Any]] = {}
    replacement_canonical: dict[tuple[str, str], str] = {}
    deletion_canonical: dict[tuple[str, str], str] = {}
    row_count = 0
    for raw_row in reader:
        row_count += 1
        if None in raw_row:
            raise PublicDataError("ECB RTD payload contains a row with an unexpected number of columns.")
        row = {str(key): str(value or "").strip() for key, value in raw_row.items()}
        for field_name, expected in expected_dimensions.items():
            if row.get(field_name) != expected:
                raise PublicDataError(
                    f"ECB RTD payload escaped the requested series dimensions in {field_name}."
                )
        period = row.get("TIME_PERIOD") or ""
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise PublicDataError("ECB RTD TIME_PERIOD must be an exact YYYY-MM monthly period.")
        action = row.get("ACTION") or ""
        if action not in {"Replace", "Delete"}:
            raise PublicDataError(f"ECB RTD contains unsupported ACTION={action or 'EMPTY'}.")
        valid_to_raw = row.get("VALID_TO") or ""
        valid_to = _iso(_parse_aware_timestamp(valid_to_raw, "VALID_TO")) if valid_to_raw else ""
        canonical = _canonical_json(row)
        if action == "Delete":
            if not valid_to:
                raise PublicDataError("ECB RTD Delete tombstone is missing VALID_TO.")
            delete_key = (period, valid_to)
            existing_delete = deletion_canonical.get(delete_key)
            if existing_delete is not None and existing_delete != canonical:
                raise PublicDataError(f"ECB RTD contains conflicting deletion events for {period}.")
            deletion_canonical[delete_key] = canonical
            continue

        valid_from_dt = _parse_aware_timestamp(row.get("VALID_FROM"), "VALID_FROM")
        valid_from = _iso(valid_from_dt)
        if valid_to and _parse_aware_timestamp(valid_to, "VALID_TO") < valid_from_dt:
            raise PublicDataError(f"ECB RTD VALID_TO precedes VALID_FROM for {period}.")
        value = _positive_number(row.get("OBS_VALUE"), f"ECB RTD {expected_key} OBS_VALUE")
        obs_status = row.get("OBS_STATUS") or ""
        if not obs_status:
            raise PublicDataError(f"ECB RTD numeric replacement is missing OBS_STATUS for {period}.")
        vintage_key = (period, valid_from)
        existing = replacement_canonical.get(vintage_key)
        if existing is not None and existing != canonical:
            raise PublicDataError(f"ECB RTD contains conflicting duplicate vintages for {period} at {valid_from}.")
        replacement_canonical[vintage_key] = canonical
        replacement_rows[vintage_key] = {
            "reference_period": period,
            "value": value,
            "obs_status": obs_status,
            "action": action,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "raw_row_sha256": _sha256(canonical.encode("utf-8")),
        }
    if row_count == 0:
        raise PublicDataError("ECB RTD payload contains no data rows.")

    first_by_period: dict[str, dict[str, Any]] = {}
    for (period, _valid_from), row in replacement_rows.items():
        current = first_by_period.get(period)
        if current is None or str(row["valid_from"]) < str(current["valid_from"]):
            first_by_period[period] = row
    if len(first_by_period) < 40:
        raise PublicDataError(
            f"ECB RTD series {expected_key} returned fewer than 40 usable first-vintage monthly observations."
        )
    return dict(sorted(first_by_period.items()))


def build_ecb_rtd_eer_bundle(
    *,
    nominal_content: bytes,
    real_content: bytes,
    fetched_at: datetime | None = None,
    nominal_headers: Mapping[str, str] | None = None,
    real_headers: Mapping[str, str] | None = None,
    nominal_url: str = ECB_RTD_NOMINAL_URL,
    real_url: str = ECB_RTD_REAL_URL,
) -> PublicDataBundle:
    """Join first-vintage nominal and real ECB EER observations as-of retrieval."""

    fetched = fetched_at or _now()
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=UTC)
    fetched = fetched.astimezone(UTC)
    nominal_source = RetrievedSource(
        source_id="ECB_RTD_NOMINAL_EER",
        url=nominal_url,
        terms_url=ECB_RTD_TERMS_URL,
        retrieved_at=_iso(fetched),
        sha256=_sha256(nominal_content),
        byte_count=len(nominal_content),
        content_type=str((nominal_headers or {}).get("content-type") or ""),
        etag=str((nominal_headers or {}).get("etag") or ""),
        last_modified=str((nominal_headers or {}).get("last-modified") or ""),
        content=nominal_content,
    )
    real_source = RetrievedSource(
        source_id="ECB_RTD_REAL_EER",
        url=real_url,
        terms_url=ECB_RTD_TERMS_URL,
        retrieved_at=_iso(fetched),
        sha256=_sha256(real_content),
        byte_count=len(real_content),
        content_type=str((real_headers or {}).get("content-type") or ""),
        etag=str((real_headers or {}).get("etag") or ""),
        last_modified=str((real_headers or {}).get("last-modified") or ""),
        content=real_content,
    )
    nominal = parse_ecb_rtd_first_vintages(
        nominal_content,
        series_key=ECB_RTD_NOMINAL_SERIES_KEY,
    )
    real = parse_ecb_rtd_first_vintages(
        real_content,
        series_key=ECB_RTD_REAL_SERIES_KEY,
    )
    common_periods = sorted(set(nominal).intersection(real))
    candidates_by_event: dict[str, list[dict[str, Any]]] = {}
    for period in common_periods:
        nominal_row = nominal[period]
        real_row = real[period]
        nominal_available = _parse_aware_timestamp(nominal_row["valid_from"], "nominal VALID_FROM")
        real_available = _parse_aware_timestamp(real_row["valid_from"], "real VALID_FROM")
        event_time = max(nominal_available, real_available)
        if event_time > fetched:
            continue
        event_iso = _iso(event_time)
        candidate = {
            "timestamp": event_iso,
            "reference_period": period,
            # The existing guarded materializer computes log(price) - log(anchor).
            # Mapping real EER to price and nominal EER to anchor therefore yields
            # the declared real/nominal competitiveness wedge without changing it.
            "price": round(float(real_row["value"]), 12),
            "fundamental_anchor": round(float(nominal_row["value"]), 12),
            "fundamental_release_timestamp": event_iso,
            "vintage_timestamp": event_iso,
            "price_valid_from": str(real_row["valid_from"]),
            "anchor_valid_from": str(nominal_row["valid_from"]),
            "price_valid_to": str(real_row["valid_to"]),
            "anchor_valid_to": str(nominal_row["valid_to"]),
            "price_action": str(real_row["action"]),
            "anchor_action": str(nominal_row["action"]),
            "price_obs_status": str(real_row["obs_status"]),
            "anchor_obs_status": str(nominal_row["obs_status"]),
            "price_series_id": ECB_RTD_REAL_SERIES_KEY,
            "anchor_series_id": ECB_RTD_NOMINAL_SERIES_KEY,
            "nominal_raw_sha256": nominal_source.sha256,
            "real_raw_sha256": real_source.sha256,
            "nominal_first_vintage_row_sha256": str(nominal_row["raw_row_sha256"]),
            "real_first_vintage_row_sha256": str(real_row["raw_row_sha256"]),
            "availability_policy": ECB_RTD_AVAILABILITY_POLICY,
            "snapshot_observed_at": _iso(fetched),
        }
        candidates_by_event.setdefault(event_iso, []).append(candidate)

    # The RTD can publish many historical periods in one atomic release batch.
    # Event-time must stay exact: no artificial microseconds are introduced to
    # manufacture uniqueness.  Instead, retain the latest reference period from
    # each unique information event and record the size/range of the batch.
    rows: list[dict[str, Any]] = []
    for event_iso in sorted(candidates_by_event):
        batch = candidates_by_event[event_iso]
        selected = dict(max(batch, key=lambda item: str(item["reference_period"])))
        selected["release_batch_size"] = len(batch)
        selected["release_batch_first_reference_period"] = min(
            str(item["reference_period"]) for item in batch
        )
        selected["release_batch_last_reference_period"] = max(
            str(item["reference_period"]) for item in batch
        )
        rows.append(selected)
    if len(rows) < 40:
        raise PublicDataError(
            "ECB RTD nominal/real join produced fewer than 40 unique causal release events."
        )
    timestamps = [str(row["timestamp"]) for row in rows]
    if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
        raise PublicDataError("ECB RTD release-event timestamps are not strictly unique and chronological.")
    periods = [str(row["reference_period"]) for row in rows]
    if periods != sorted(periods) or len(periods) != len(set(periods)):
        raise PublicDataError("ECB RTD release-event selection did not preserve reference-period chronology.")
    if any(
        _parse_aware_timestamp(row["vintage_timestamp"], "vintage_timestamp")
        > _parse_aware_timestamp(row["timestamp"], "timestamp")
        for row in rows
    ):
        raise PublicDataError("ECB RTD release-event selection contains a future vintage.")

    source_metadata = (_source_metadata(nominal_source), _source_metadata(real_source))
    fingerprint_payload = {
        "dataset_id": ECB_RTD_DATASET_ID,
        "parser_version": ECB_RTD_PARSER_VERSION,
        "availability_policy": ECB_RTD_AVAILABILITY_POLICY,
        "source_sha256": [nominal_source.sha256, real_source.sha256],
        "rows": rows,
    }
    fingerprint = _sha256(_canonical_json(fingerprint_payload).encode("utf-8"))
    snapshot_id = f"ECBRTD-{fetched.strftime('%Y%m%dT%H%M%SZ')}-{fingerprint[:12]}"
    warnings = (
        "RESEARCH_ONLY: this first-vintage statistical dataset is not approved for production decisions.",
        "NON-TRADABLE: ECB effective exchange-rate indices are analytical series, not executable market prices.",
        "Each unique release event retains its latest common reference period; batch size and range remain explicit.",
        "First vintage means the earliest version exposed by the current RTD history, not a claim about records outside that archive.",
        "RTD ACTION and VALID_TO history is retained in the immutable raw CSV; joined rows expose the selected first Replace vintage.",
    )
    manifest = PublicDataManifest(
        snapshot_id=snapshot_id,
        created_at=_iso(fetched),
        dataset_id=ECB_RTD_DATASET_ID,
        dataset_label="ECB RTD first-vintage real / nominal broad EER release-event pilot",
        row_count=len(rows),
        start_reference_period=periods[0],
        end_reference_period=periods[-1],
        start_timestamp=str(rows[0]["timestamp"]),
        end_timestamp=str(rows[-1]["timestamp"]),
        dataset_fingerprint=fingerprint,
        parser_version=ECB_RTD_PARSER_VERSION,
        revision_policy="POINT_IN_TIME_VINTAGES",
        availability_policy=ECB_RTD_AVAILABILITY_POLICY,
        availability_time_quality="CONTROLLED",
        price_series_id=ECB_RTD_REAL_SERIES_KEY,
        anchor_series_id=ECB_RTD_NOMINAL_SERIES_KEY,
        source_metadata=source_metadata,
        warnings=warnings,
        status="VALIDATED",
        production_status="RESEARCH_ONLY",
    )
    return PublicDataBundle(
        manifest=manifest,
        rows=tuple(rows),
        sources=(nominal_source, real_source),
    )


def fetch_ecb_rtd_eer_bundle(
    *,
    timeout: int = 60,
    user_agent: str = ECB_DEFAULT_USER_AGENT,
    fetched_at: datetime | None = None,
    fetcher: FetchCallable | None = None,
) -> PublicDataBundle:
    fetched = fetched_at or _now()
    active_fetcher = fetcher or _default_fetch
    nominal = _retrieve(
        source_id="ECB_RTD_NOMINAL_EER",
        url=ECB_RTD_NOMINAL_URL,
        terms_url=ECB_RTD_TERMS_URL,
        fetched_at=fetched,
        timeout=int(timeout),
        max_bytes=5_000_000,
        user_agent=user_agent,
        fetcher=active_fetcher,
    )
    real = _retrieve(
        source_id="ECB_RTD_REAL_EER",
        url=ECB_RTD_REAL_URL,
        terms_url=ECB_RTD_TERMS_URL,
        fetched_at=fetched,
        timeout=int(timeout),
        max_bytes=5_000_000,
        user_agent=user_agent,
        fetcher=active_fetcher,
    )
    return build_ecb_rtd_eer_bundle(
        nominal_content=nominal.content,
        real_content=real.content,
        fetched_at=fetched,
        nominal_headers={
            "content-type": nominal.content_type,
            "etag": nominal.etag,
            "last-modified": nominal.last_modified,
        },
        real_headers={
            "content-type": real.content_type,
            "etag": real.etag,
            "last-modified": real.last_modified,
        },
        nominal_url=nominal.url,
        real_url=real.url,
    )


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _write_text(path: Path, content: str) -> None:
    _write_bytes(path, content.encode("utf-8"))


def _dataset_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise PublicDataError("Cannot persist an empty public-data dataset.")
    fields = list(rows[0].keys())
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="raise", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return buffer.getvalue().encode("utf-8")


def persist_public_data_bundle(bundle: PublicDataBundle, root: str | Path) -> Path:
    base = Path(root).expanduser().resolve() / "public_data_snapshots"
    base.mkdir(parents=True, exist_ok=True)
    target = base / bundle.manifest.snapshot_id
    if target.exists():
        manifest_path = target / "manifest.json"
        if manifest_path.is_file():
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if str(existing.get("dataset_fingerprint") or "") == bundle.manifest.dataset_fingerprint:
                return target
        raise PublicDataError("Snapshot ID already exists with different content; refusing to overwrite it.")
    pending = Path(tempfile.mkdtemp(prefix=".pending-public-data-", dir=str(base)))
    try:
        source_by_id = {source.source_id: source for source in bundle.sources}
        if len(source_by_id) != len(bundle.sources):
            raise PublicDataError("Raw official source IDs must be unique for append-only persistence.")
        layouts = {
            PUBLIC_DATASET_ID: {
                "FHFA_HPI": "fhfa_hpi_master.csv",
                "BLS_RENT": "bls_us_housing.tsv",
            },
            ECB_RTD_DATASET_ID: {
                "ECB_RTD_NOMINAL_EER": "ecb_rtd_nominal_eer.csv",
                "ECB_RTD_REAL_EER": "ecb_rtd_real_eer.csv",
            },
        }
        source_files = layouts.get(bundle.manifest.dataset_id)
        if source_files is None:
            raise PublicDataError("No append-only raw-source layout is registered for this public dataset.")
        if set(source_files) != set(source_by_id):
            raise PublicDataError("Raw official source payloads are required for append-only persistence.")
        for source_id, filename in source_files.items():
            source = source_by_id[source_id]
            if _sha256(source.content) != source.sha256:
                raise PublicDataError(f"Raw source digest mismatch for {source_id}.")
            _write_bytes(pending / filename, source.content)
        dataset_content = _dataset_csv(bundle.rows)
        _write_bytes(pending / "contract_rows.csv", dataset_content)
        manifest = asdict(bundle.manifest)
        manifest["dataset_file_sha256"] = _sha256(dataset_content)
        manifest["files"] = dict(source_files)
        manifest["files"]["CONTRACT_ROWS"] = "contract_rows.csv"
        _write_text(pending / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        os.rename(pending, target)
    except Exception:
        shutil.rmtree(pending, ignore_errors=True)
        raise
    return target


def _snapshot_directory(root: str | Path, snapshot_id: str) -> Path:
    identity = str(snapshot_id or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{5,127}", identity):
        raise PublicDataError("Snapshot ID contains unsupported path characters.")
    base = (Path(root).expanduser().resolve() / "public_data_snapshots").resolve()
    target = (base / identity).resolve()
    if target.parent != base:
        raise PublicDataError("Snapshot path escapes the append-only public-data archive.")
    return target


def load_public_data_snapshot(root: str | Path, snapshot_id: str) -> dict[str, Any]:
    """Load and re-verify one persisted public-data snapshot without mutation."""

    target = _snapshot_directory(root, snapshot_id)
    if not target.is_dir():
        raise PublicDataError(f"Unknown persisted public-data snapshot: {snapshot_id}")
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        raise PublicDataError("Persisted snapshot is missing manifest.json.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublicDataError("Persisted snapshot manifest is not valid JSON.") from exc
    if not isinstance(manifest, Mapping):
        raise PublicDataError("Persisted snapshot manifest must be a JSON object.")
    manifest = dict(manifest)
    if str(manifest.get("snapshot_id") or "") != target.name:
        raise PublicDataError("Persisted snapshot identity does not match its directory.")
    if str(manifest.get("production_status") or "") != "RESEARCH_ONLY":
        raise PublicDataError("Persisted public data must remain RESEARCH_ONLY.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("dataset_fingerprint") or "")):
        raise PublicDataError("Persisted snapshot has no valid dataset fingerprint.")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or "CONTRACT_ROWS" not in files:
        raise PublicDataError("Persisted snapshot manifest has no contract-row file mapping.")

    verified_files: dict[str, str] = {}
    for source_id, raw_filename in files.items():
        filename = str(raw_filename or "")
        if not filename or Path(filename).name != filename:
            raise PublicDataError(f"Unsafe snapshot file mapping for {source_id}.")
        file_path = (target / filename).resolve()
        if file_path.parent != target or not file_path.is_file():
            raise PublicDataError(f"Persisted snapshot file is missing: {filename}")
        verified_files[str(source_id)] = _sha256(file_path.read_bytes())

    dataset_sha = verified_files["CONTRACT_ROWS"]
    if dataset_sha != str(manifest.get("dataset_file_sha256") or ""):
        raise PublicDataError("Persisted contract_rows.csv SHA-256 verification failed.")
    source_metadata = manifest.get("source_metadata") or ()
    if not isinstance(source_metadata, (list, tuple)):
        raise PublicDataError("Persisted source metadata has an invalid shape.")
    for source in source_metadata:
        if not isinstance(source, Mapping):
            raise PublicDataError("Persisted source metadata contains a non-object row.")
        source_id = str(source.get("source_id") or "")
        if source_id not in verified_files:
            raise PublicDataError(f"Raw source mapping is missing for {source_id or 'unnamed source'}.")
        if verified_files[source_id] != str(source.get("sha256") or ""):
            raise PublicDataError(f"Raw source SHA-256 verification failed for {source_id}.")

    dataset_path = target / str(files["CONTRACT_ROWS"])
    try:
        with dataset_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise PublicDataError("Persisted contract_rows.csv has no header.")
            rows = [dict(row) for row in reader]
    except PublicDataError:
        raise
    except Exception as exc:
        raise PublicDataError("Persisted contract_rows.csv could not be parsed.") from exc
    if len(rows) != int(manifest.get("row_count") or -1):
        raise PublicDataError("Persisted contract_rows.csv row count does not match the manifest.")
    if not rows:
        raise PublicDataError("Persisted contract_rows.csv is empty.")
    return {
        "manifest": manifest,
        "rows": rows,
        "snapshot_path": str(target),
        "verification_status": "VERIFIED",
        "verified_file_sha256": verified_files,
    }


def list_public_data_snapshots(root: str | Path, dataset_id: str = "") -> list[dict[str, Any]]:
    """List persisted snapshots and surface corruption instead of hiding it."""

    base = Path(root).expanduser().resolve() / "public_data_snapshots"
    if not base.exists():
        return []
    if not base.is_dir():
        raise PublicDataError("The public_data_snapshots archive path is not a directory.")
    records: list[dict[str, Any]] = []
    for child in sorted(base.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name.startswith(".pending-"):
            continue
        try:
            loaded = load_public_data_snapshot(root, child.name)
            manifest = dict(loaded["manifest"])
            if dataset_id and str(manifest.get("dataset_id") or "") != str(dataset_id):
                continue
            manifest["verification_status"] = "VERIFIED"
            manifest["snapshot_path"] = loaded["snapshot_path"]
            records.append(manifest)
        except PublicDataError as exc:
            records.append({
                "snapshot_id": child.name,
                "dataset_id": "",
                "verification_status": "INVALID",
                "verification_error": str(exc),
                "snapshot_path": str(child),
            })
    return sorted(records, key=lambda row: str(row.get("created_at") or row.get("snapshot_id") or ""), reverse=True)


def public_data_contract_preset() -> dict[str, Any]:
    return {
        "market": "United States residential housing",
        "universe": "FHFA national purchase-only single-family house price index",
        "asset_identifier": PUBLIC_DATASET_ID,
        "provider": "FHFA + U.S. Bureau of Labor Statistics direct official sources",
        "raw_data_uri": f"{FHFA_HPI_URL} | {BLS_HOUSING_URL}",
        "license_or_terms": (
            "Public official statistics; Source: FHFA HPI and U.S. Bureau of Labor Statistics; "
            f"terms: {FHFA_TERMS_URL} | {BLS_TERMS_URL}"
        ),
        "anchor_family": "OTHER_DECLARED",
        "price_field": "price",
        "fundamental_field": "fundamental_anchor",
        "event_time_field": "timestamp",
        "availability_time_field": "fundamental_release_timestamp",
        "vintage_time_field": "",
        "frequency": "MONTHLY",
        "publication_lag_days": 0,
        "revision_policy": "REVISED_WITH_RISK_FLAG",
        "source_refs": [FHFA_HPI_URL, BLS_HOUSING_URL, FHFA_TERMS_URL, BLS_TERMS_URL],
        "rationale": (
            "Zero-cost official public-data pilot. The market measure is the seasonally adjusted FHFA national "
            "purchase-only HPI and the declared anchor is the seasonally adjusted BLS rent-of-primary-residence "
            "index. Availability is conservatively delayed 90 days from the reference month end. The downloadable "
            "histories are revised current-view snapshots, so every manifest must retain REVISION_RISK_PRESENT."
        ),
    }


def ecb_rtd_contract_preset() -> dict[str, Any]:
    """Return the immutable contract fields for the free vintage-aware pilot."""

    return {
        "market": "Euro-area broad effective exchange-rate research indices",
        "universe": "ECB RTD nominal and CPI-deflated real broad EER release events",
        "asset_identifier": ECB_RTD_DATASET_ID,
        "provider": "European Central Bank Data Portal · Real Time Database",
        "raw_data_uri": f"{ECB_RTD_NOMINAL_URL} | {ECB_RTD_REAL_URL}",
        "license_or_terms": (
            "Source: ECB statistics. Free reuse with attribution subject to the ECB policy and disclaimer; "
            f"{ECB_RTD_USAGE_POLICY_URL} | {ECB_RTD_TERMS_URL}"
        ),
        "anchor_family": "OTHER_DECLARED",
        "price_field": "price",
        "fundamental_field": "fundamental_anchor",
        "event_time_field": "timestamp",
        "availability_time_field": "fundamental_release_timestamp",
        "vintage_time_field": "vintage_timestamp",
        "frequency": "MONTHLY",
        "publication_lag_days": 0,
        "revision_policy": "POINT_IN_TIME_VINTAGES",
        "source_refs": [
            ECB_RTD_NOMINAL_URL,
            ECB_RTD_REAL_URL,
            "https://data.ecb.europa.eu/help/api/data",
            ECB_RTD_USAGE_POLICY_URL,
            ECB_RTD_TERMS_URL,
        ],
        "rationale": (
            "Zero-cost, no-key, vintage-aware official pilot. Each row is a unique recorded ECB RTD release "
            "event and retains the latest common reference period in that atomic batch. The guarded transform "
            "is log(real broad EER) minus log(nominal broad EER), a non-tradable competitiveness wedge. "
            "VALID_FROM supplies public availability and vintage time; full raw ACTION/VALID_TO history is "
            "archived by SHA-256. Results remain RESEARCH_ONLY."
        ),
    }


__all__ = [
    "AVAILABILITY_POLICY",
    "BLS_HOUSING_URL",
    "BLS_RENT_SERIES_ID",
    "BLS_TERMS_URL",
    "FHFA_HPI_URL",
    "FHFA_SERIES_ID",
    "FHFA_TERMS_URL",
    "ECB_RTD_AVAILABILITY_POLICY",
    "ECB_RTD_DATASET_ID",
    "ECB_RTD_NOMINAL_SERIES_KEY",
    "ECB_RTD_NOMINAL_URL",
    "ECB_RTD_PARSER_VERSION",
    "ECB_RTD_REAL_SERIES_KEY",
    "ECB_RTD_REAL_URL",
    "ECB_RTD_TERMS_URL",
    "ECB_RTD_USAGE_POLICY_URL",
    "PUBLIC_DATA_PARSER_VERSION",
    "PUBLIC_DATASET_ID",
    "PublicDataBundle",
    "PublicDataError",
    "PublicDataManifest",
    "RetrievedSource",
    "build_fhfa_bls_housing_bundle",
    "build_ecb_rtd_eer_bundle",
    "ecb_rtd_contract_preset",
    "fetch_ecb_rtd_eer_bundle",
    "fetch_fhfa_bls_housing_bundle",
    "parse_bls_rent_sa",
    "parse_ecb_rtd_first_vintages",
    "parse_fhfa_monthly_us_sa",
    "persist_public_data_bundle",
    "public_data_contract_preset",
]
