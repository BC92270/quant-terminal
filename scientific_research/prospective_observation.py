from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from typing import Any, Mapping, Sequence

from .direct_bis_reconciliation import (
    DIRECT_BIS_HISTORY_SEMANTICS,
    build_prospective_vintage_summary,
    validate_completed_direct_bis_reconciliation,
)
from .phase68_models import PROSPECTIVE_PROGRAM_WARNINGS, ProspectiveObservationProgram


PROSPECTIVE_OBSERVATION_PROTOCOL_VERSION = "SRB_PROSPECTIVE_OBSERVATION_PROGRAM_V1"


def _row(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return dict(value)


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_instant(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _month_start(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(value: datetime) -> datetime:
    current = _month_start(value)
    if current.month == 12:
        return current.replace(year=current.year + 1, month=1)
    return current.replace(month=current.month + 1)


def _month_key(value: datetime) -> str:
    return value.strftime("%Y-%m")


def _parse_month_start(value: Any, *, field: str) -> date:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 date.") from exc
    if parsed.day != 1:
        raise ValueError(f"{field} must be the first day of a calendar month.")
    return parsed


def _exact_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"sha256:[0-9a-f]{64}", str(value or "")))


def _program_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "protocol_version",
        "replication_id",
        "seed_reconciliation_id",
        "seed_snapshot_id",
        "seed_snapshot_fingerprint",
        "seed_retrieved_at",
        "seed_latest_period",
        "protocol_frozen_at",
        "first_future_window",
        "cadence",
        "maximum_credited_observations_per_window",
        "duplicate_content_policy",
        "missed_window_policy",
        "prospective_min_distinct_snapshots",
        "prospective_min_distinct_latest_periods",
        "prospective_min_span_days",
        "history_semantics",
        "point_in_time_status",
        "historical_backfill_permitted",
        "historical_evidence_eligible",
        "automatic_execution_authorized",
        "automatic_promotion_authorized",
        "production_status",
        "lifecycle_history",
        "warnings",
    )
    return {key: row.get(key) for key in keys}


def _direct_observation_receipt(row: Mapping[str, Any]) -> str:
    """Bind the runtime-asserted acquisition clock to the immutable observation row."""
    return _digest({
        "protocol_version": row.get("protocol_version"),
        "reconciliation_id": row.get("reconciliation_id"),
        "replication_id": row.get("replication_id"),
        "protocol_fingerprint": row.get("protocol_fingerprint"),
        "protocol_frozen_at": row.get("protocol_frozen_at"),
        "direct_snapshot_id": row.get("direct_snapshot_id"),
        "direct_snapshot_fingerprint": row.get("direct_snapshot_fingerprint"),
        "raw_archive_sha256": row.get("raw_archive_sha256"),
        "reconciliation_fingerprint": row.get("reconciliation_fingerprint"),
        "retrieved_at": row.get("retrieved_at"),
        "completed_at": row.get("completed_at"),
        "response_metadata": row.get("response_metadata") or {},
        "latest_period": row.get("latest_period"),
    })


def _validate_direct_observation(row: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one complete Phase-6.6 observation before it can accrue evidence."""
    authoritative = validate_completed_direct_bis_reconciliation(row)
    identity = str(authoritative.get("identity") or "UNKNOWN")
    defects = list(authoritative.get("defects") or ())

    parsed: dict[str, datetime] = {}
    for field in ("created_at", "protocol_frozen_at", "retrieved_at", "completed_at"):
        try:
            parsed[field] = _parse_instant(row.get(field), field=field)
        except ValueError as exc:
            defects.append(str(exc))
    if all(field in parsed for field in ("created_at", "protocol_frozen_at", "retrieved_at", "completed_at")):
        if not (
            parsed["created_at"] <= parsed["protocol_frozen_at"]
            <= parsed["retrieved_at"] <= parsed["completed_at"]
        ):
            defects.append("lifecycle chronology must be created <= frozen <= retrieved <= completed")

    latest_period: date | None = None
    try:
        latest_period = _parse_month_start(row.get("latest_period"), field="latest_period")
    except ValueError as exc:
        defects.append(str(exc))
    if latest_period is not None and "retrieved_at" in parsed and latest_period > parsed["retrieved_at"].date():
        defects.append("latest period occurs after retrieval")

    return {
        "status": "PASS" if not defects else "FAIL",
        "identity": identity,
        "defects": tuple(dict.fromkeys(defects)),
        "times": parsed,
        "latest_period": latest_period,
        "observation_receipt_fingerprint": _direct_observation_receipt(row),
    }


def validate_prospective_observation_program(program: Any) -> dict[str, Any]:
    row = _row(program)
    defects: list[str] = []
    if not str(row.get("program_id") or ""):
        defects.append("program identity is missing")
    if str(row.get("protocol_version") or "") != PROSPECTIVE_OBSERVATION_PROTOCOL_VERSION:
        defects.append("unsupported protocol version")
    if str(row.get("status") or "") != "ACTIVE":
        defects.append("program status is not ACTIVE")
    if str(row.get("cadence") or "") != "UTC_CALENDAR_MONTH":
        defects.append("cadence is not UTC_CALENDAR_MONTH")
    credit_limit = _exact_int(row.get("maximum_credited_observations_per_window"))
    if credit_limit is None:
        defects.append("monthly credit limit is not an integer")
    if credit_limit != 1:
        defects.append("monthly credit limit is not one")
    thresholds = tuple(_exact_int(row.get(field)) for field in (
        "prospective_min_distinct_snapshots",
        "prospective_min_distinct_latest_periods",
        "prospective_min_span_days",
    ))
    if any(value is None for value in thresholds):
        defects.append("prospective maturity thresholds are not integers")
    if thresholds != (12, 12, 300):
        defects.append("prospective maturity thresholds changed from 12 snapshots / 12 months / 300 days")
    if str(row.get("duplicate_content_policy") or "") != "RETAIN_OBSERVATION_EXCLUDE_FROM_DISTINCT_EVIDENCE":
        defects.append("duplicate-content policy changed")
    if str(row.get("missed_window_policy") or "") != "RETAIN_GAP_NEVER_BACKFILL":
        defects.append("missed-window policy changed")
    if str(row.get("history_semantics") or "") != DIRECT_BIS_HISTORY_SEMANTICS:
        defects.append("revised-history semantics changed")
    if str(row.get("point_in_time_status") or "") != "PROSPECTIVE_AS_OBSERVED_ONLY":
        defects.append("point-in-time boundary changed")
    if row.get("historical_backfill_permitted") is not False:
        defects.append("historical backfill is permitted")
    if row.get("historical_evidence_eligible") is not False:
        defects.append("program is overstated as historical evidence")
    if row.get("automatic_execution_authorized") is not False:
        defects.append("automatic execution is authorized")
    if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
        defects.append("research-only promotion lock is absent")
    if tuple(str(item) for item in (row.get("warnings") or ())) != PROSPECTIVE_PROGRAM_WARNINGS:
        defects.append("prospective scientific-boundary warnings changed")
    if not re.fullmatch(r"\d{4}-\d{2}-01T00:00:00\+00:00", str(row.get("first_future_window") or "")):
        defects.append("first future window is not a UTC month boundary")
    parsed: dict[str, datetime] = {}
    for field in ("created_at", "seed_retrieved_at", "protocol_frozen_at", "first_future_window"):
        try:
            parsed[field] = _parse_instant(row.get(field), field=field)
        except ValueError as exc:
            defects.append(str(exc))
    if parsed.get("created_at") != parsed.get("protocol_frozen_at"):
        defects.append("created_at and protocol_frozen_at differ")
    if parsed.get("seed_retrieved_at") and parsed.get("protocol_frozen_at") and parsed["seed_retrieved_at"] > parsed["protocol_frozen_at"]:
        defects.append("seed observation occurs after the frozen protocol")
    if parsed.get("protocol_frozen_at") and parsed.get("first_future_window") != _next_month(parsed["protocol_frozen_at"]):
        defects.append("first future window is not the month after protocol freeze")
    if any(not str(row.get(field) or "") for field in (
        "replication_id", "seed_reconciliation_id", "seed_snapshot_id", "seed_snapshot_fingerprint",
    )):
        defects.append("seed lineage identity is incomplete")
    try:
        _parse_month_start(row.get("seed_latest_period"), field="seed_latest_period")
    except ValueError as exc:
        defects.append(str(exc))
    expected = _digest(_program_payload(row))
    if str(row.get("protocol_fingerprint") or "") != expected:
        defects.append("protocol fingerprint mismatch")
    if str(row.get("program_id") or ""):
        identity_source = "|".join((
            str(row.get("replication_id") or ""),
            str(row.get("seed_reconciliation_id") or ""),
            str(row.get("protocol_frozen_at") or ""),
            expected,
        ))
        expected_identity = f"POP-{hashlib.sha256(identity_source.encode('utf-8')).hexdigest()[:16]}"
        if str(row.get("program_id")) != expected_identity:
            defects.append("program identity mismatch")
    raw_history = row.get("lifecycle_history") or ()
    history = [dict(item) for item in raw_history if isinstance(item, Mapping)]
    frozen_events = [item for item in history if str(item.get("event") or "") == "PROSPECTIVE_OBSERVATION_PROGRAM_FROZEN"]
    if not isinstance(raw_history, (list, tuple)) or len(raw_history) != 1 or len(history) != 1 or len(frozen_events) != 1:
        defects.append("exactly one program-freeze lifecycle event is required")
    else:
        event = frozen_events[0]
        expected_event = {
            "at": row.get("protocol_frozen_at"),
            "event": "PROSPECTIVE_OBSERVATION_PROGRAM_FROZEN",
            "seed_reconciliation_id": row.get("seed_reconciliation_id"),
            "first_future_window": row.get("first_future_window"),
            "historical_backfill_permitted": False,
            "automatic_execution_authorized": False,
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        }
        if event != expected_event:
            defects.append("program-freeze lifecycle differs from the exact governed event")
    return {
        "status": "PASS" if not defects else "FAIL",
        "defects": tuple(dict.fromkeys(defects)),
        "expected_protocol_fingerprint": expected,
    }


def freeze_prospective_observation_program(
    seed_reconciliation: Any,
    *,
    created_at: str | None = None,
) -> ProspectiveObservationProgram:
    """Freeze a future-only monthly observation protocol around one real seed."""
    seed = _row(seed_reconciliation)
    direct_validation = _validate_direct_observation(seed)
    if direct_validation["status"] != "PASS":
        raise ValueError(
            "The direct BIS seed is not a governed complete observation: "
            + "; ".join(direct_validation["defects"])
        )

    seed_retrieved = direct_validation["times"]["retrieved_at"]
    seed_completed = direct_validation["times"]["completed_at"]
    frozen_at = str(created_at or datetime.now(timezone.utc).isoformat())
    frozen = _parse_instant(frozen_at, field="created_at")
    if frozen < seed_completed:
        raise ValueError("The program cannot be frozen before its real seed observation is complete.")
    first_future = _next_month(frozen).isoformat()
    base = ProspectiveObservationProgram(
        program_id="",
        created_at=frozen.isoformat(),
        replication_id=str(seed.get("replication_id")),
        seed_reconciliation_id=str(seed.get("reconciliation_id")),
        seed_snapshot_id=str(seed.get("direct_snapshot_id")),
        seed_snapshot_fingerprint=str(seed.get("direct_snapshot_fingerprint")),
        seed_retrieved_at=seed_retrieved.isoformat(),
        seed_latest_period=str(seed.get("latest_period")),
        protocol_frozen_at=frozen.isoformat(),
        protocol_fingerprint="",
        first_future_window=first_future,
        prospective_min_distinct_snapshots=int(seed.get("prospective_min_distinct_snapshots") or 12),
        prospective_min_distinct_latest_periods=int(seed.get("prospective_min_distinct_latest_periods") or 12),
        prospective_min_span_days=int(seed.get("prospective_min_span_days") or 300),
        lifecycle_history=({
            "at": frozen.isoformat(),
            "event": "PROSPECTIVE_OBSERVATION_PROGRAM_FROZEN",
            "seed_reconciliation_id": str(seed.get("reconciliation_id")),
            "first_future_window": first_future,
            "historical_backfill_permitted": False,
            "automatic_execution_authorized": False,
            "automatic_promotion_authorized": False,
            "production_status": "RESEARCH_ONLY",
        },),
    )
    fingerprint = _digest(_program_payload(asdict(base)))
    identity_source = "|".join((base.replication_id, base.seed_reconciliation_id, frozen.isoformat(), fingerprint))
    identity = f"POP-{hashlib.sha256(identity_source.encode('utf-8')).hexdigest()[:16]}"
    frozen_program = replace(base, program_id=identity, protocol_fingerprint=fingerprint)
    validation = validate_prospective_observation_program(frozen_program)
    if validation["status"] != "PASS":
        raise ValueError("Prospective program cannot be frozen: " + "; ".join(validation["defects"]))
    return frozen_program


def evaluate_prospective_observation_program(
    program: Any,
    records: Sequence[Mapping[str, Any] | Any],
    *,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Derive schedule adherence and evidence maturity without mutating facts."""
    row = _row(program)
    validation = validate_prospective_observation_program(row)
    if validation["status"] != "PASS":
        raise ValueError("Invalid prospective observation program: " + "; ".join(validation["defects"]))
    now = _parse_instant(as_of or datetime.now(timezone.utc).isoformat(), field="as_of")
    frozen_at = _parse_instant(row.get("protocol_frozen_at"), field="protocol_frozen_at")
    if now < frozen_at:
        raise ValueError("as_of cannot precede the frozen program.")
    first_window = _parse_instant(row.get("first_future_window"), field="first_future_window")
    current_window = _month_start(now)
    opened_months = (current_window.year - first_window.year) * 12 + current_window.month - first_window.month + 1
    if opened_months > 2400:
        raise ValueError("Prospective calendar exceeds the bounded 200-year rendering horizon.")

    seed: dict[str, Any] | None = None
    eligible_future: list[dict[str, Any]] = []
    for value in records:
        item = _row(value)
        if str(item.get("replication_id") or "") != str(row.get("replication_id") or ""):
            continue
        if str(item.get("execution_status") or "") != "COMPLETE":
            continue
        direct_validation = _validate_direct_observation(item)
        if direct_validation["status"] != "PASS":
            raise ValueError(
                f"Completed direct observation {direct_validation['identity']} is invalid: "
                + "; ".join(direct_validation["defects"])
            )
        retrieved = direct_validation["times"]["retrieved_at"]
        completed = direct_validation["times"]["completed_at"]
        if retrieved > now or completed > now:
            raise ValueError(
                f"Completed direct observation {item.get('reconciliation_id') or 'UNKNOWN'} is dated after as_of."
            )
        candidate = {
            **item,
            "_retrieved": retrieved,
            "_completed": completed,
            "_created": direct_validation["times"]["created_at"],
            "_observation_receipt_fingerprint": direct_validation["observation_receipt_fingerprint"],
        }
        if str(item.get("reconciliation_id") or "") == str(row.get("seed_reconciliation_id") or ""):
            if seed is not None:
                raise ValueError("The prospective seed reconciliation is duplicated.")
            seed = candidate
            continue
        if retrieved >= first_window:
            eligible_future.append(candidate)

    if seed is None:
        raise ValueError("The prospective seed reconciliation is missing.")
    seed_checks = {
        "direct_snapshot_id": row.get("seed_snapshot_id"),
        "direct_snapshot_fingerprint": row.get("seed_snapshot_fingerprint"),
        "latest_period": row.get("seed_latest_period"),
    }
    if any(str(seed.get(field) or "") != str(expected or "") for field, expected in seed_checks.items()):
        raise ValueError("The prospective seed identity no longer matches the frozen program.")
    if seed["_retrieved"] != _parse_instant(row.get("seed_retrieved_at"), field="seed_retrieved_at"):
        raise ValueError("The prospective seed observation time no longer matches the frozen program.")
    if seed["_completed"] > frozen_at:
        raise ValueError("The prospective seed was not complete when the program was frozen.")
    window_records: dict[str, list[dict[str, Any]]] = {}
    for item in eligible_future:
        retrieved = item["_retrieved"]
        window_records.setdefault(_month_key(retrieved), []).append(item)

    calendar: list[dict[str, Any]] = []
    credited_evidence: list[dict[str, Any]] = [seed]
    credited_reconciliation_ids: list[str] = [str(seed.get("reconciliation_id") or "")]
    cursor = first_window
    missed = 0
    credited = 0
    duplicate_window_observations = 0
    late_window_observations = 0
    while cursor <= current_window:
        key = _month_key(cursor)
        observed = sorted(
            window_records.get(key, ()),
            key=lambda item: (item["_retrieved"], str(item.get("reconciliation_id") or "")),
        )
        count = len(observed)
        eligible_observed = [
            item for item in observed
            if item["_created"] >= frozen_at and item["_completed"] < _next_month(item["_retrieved"])
        ]
        late_count = count - len(eligible_observed)
        late_window_observations += late_count
        is_current = cursor == current_window
        credited_item = eligible_observed[0] if eligible_observed else None
        if credited_item is not None:
            status = "CAPTURED"
            credited += 1
            credited_evidence.append(credited_item)
            credited_reconciliation_ids.append(str(credited_item.get("reconciliation_id") or ""))
            duplicate_window_observations += max(0, len(eligible_observed) - 1)
        elif count and not is_current:
            status = "MISSED_RETAINED_LATE_COMPLETION"
            missed += 1
        elif is_current:
            status = "OPEN_DUE"
        else:
            status = "MISSED_RETAINED"
            missed += 1
        calendar.append({
            "window": key,
            "window_opened_at": cursor.isoformat(),
            "status": status,
            "observation_count": count,
            "eligible_same_window_completion_count": len(eligible_observed),
            "late_completion_count": late_count,
            "credited_observation_count": 1 if credited_item is not None else 0,
            "credited_reconciliation_id": str(credited_item.get("reconciliation_id") or "") if credited_item else "",
            "reconciliation_ids": [str(item.get("reconciliation_id") or "") for item in observed],
            "snapshot_ids": [str(item.get("direct_snapshot_id") or "") for item in observed],
            "latest_periods": sorted({str(item.get("latest_period") or "") for item in observed if item.get("latest_period")}),
            "backfillable": False,
        })
        cursor = _next_month(cursor)

    current = calendar[-1] if calendar and calendar[-1]["window"] == _month_key(current_window) else None
    if now < first_window:
        next_observation_at = first_window
        due = False
    elif current is not None and current["status"] == "OPEN_DUE":
        next_observation_at = current_window
        due = True
    else:
        next_observation_at = _next_month(current_window)
        due = False

    maturity = build_prospective_vintage_summary(
        credited_evidence,
        replication_id=str(row.get("replication_id") or ""),
        min_distinct_snapshots=int(row.get("prospective_min_distinct_snapshots") or 12),
        min_distinct_latest_periods=int(row.get("prospective_min_distinct_latest_periods") or 12),
        min_span_days=int(row.get("prospective_min_span_days") or 300),
    )
    if maturity["status"] == "READY_FOR_FORWARD_VINTAGE_STUDY":
        status = "MATURE_FOR_FORWARD_VINTAGE_STUDY"
    elif missed:
        status = "ACTIVE_WITH_RETAINED_GAPS"
    elif due:
        status = "OBSERVATION_DUE"
    else:
        status = "WAITING_NEXT_WINDOW"
    return {
        "program_id": row.get("program_id"),
        "program_status": status,
        "protocol_integrity_status": "PASS",
        "as_of": now.isoformat(),
        "seed_reconciliation_id": row.get("seed_reconciliation_id"),
        "seed_retrieved_at": row.get("seed_retrieved_at"),
        "first_future_window": row.get("first_future_window"),
        "next_observation_at": next_observation_at.isoformat(),
        "observation_due": due,
        "scheduled_windows_opened": len(calendar),
        "captured_windows": credited,
        "missed_windows": missed,
        "duplicate_window_observations": duplicate_window_observations,
        "late_window_observations": late_window_observations,
        "credited_reconciliation_ids": credited_reconciliation_ids,
        "calendar": calendar,
        "calendar_fingerprint": _digest(calendar),
        "maturity": maturity,
        "historical_backfill_permitted": False,
        "automatic_execution_authorized": False,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
    }


def build_research_closure_dossier(
    program: Any,
    records: Sequence[Mapping[str, Any] | Any],
    *,
    as_of: str | None = None,
    mission_status: str = "",
    core_study_status: str = "",
    mission_gate_count: int = 0,
    question_id: str = "",
    mission_snapshot_id: str = "",
    mission_gates: Sequence[Mapping[str, Any] | Any] = (),
    retained_result: Mapping[str, Any] | Any | None = None,
    triangulation_records: Sequence[Mapping[str, Any] | Any] = (),
) -> dict[str, Any]:
    """Build a machine-readable closure boundary, not a scientific approval."""
    row = _row(program)
    state = evaluate_prospective_observation_program(row, records, as_of=as_of)
    first_future_window = _parse_instant(row.get("first_future_window"), field="first_future_window")
    credited_ids = set(str(value) for value in (state.get("credited_reconciliation_ids") or ()))
    calendar_by_id = {
        str(identity): window
        for window in (state.get("calendar") or ())
        for identity in (window.get("reconciliation_ids") or ())
    }
    observation_inventory = sorted(
        (
            {
                "reconciliation_id": item.get("reconciliation_id"),
                "direct_snapshot_id": item.get("direct_snapshot_id"),
                "direct_snapshot_fingerprint": item.get("direct_snapshot_fingerprint"),
                "direct_snapshot_path": item.get("direct_snapshot_path"),
                "raw_archive_sha256": item.get("raw_archive_sha256"),
                "reconciliation_fingerprint": item.get("reconciliation_fingerprint"),
                "retrieved_at": item.get("retrieved_at"),
                "completed_at": item.get("completed_at"),
                "latest_period": item.get("latest_period"),
                "observation_receipt_fingerprint": _direct_observation_receipt(item),
                "program_role": (
                    "FROZEN_SEED"
                    if str(item.get("reconciliation_id") or "") == str(row.get("seed_reconciliation_id") or "")
                    else "PROSPECTIVE_WINDOW_OBSERVATION"
                ),
                "schedule_window": (
                    calendar_by_id.get(str(item.get("reconciliation_id") or ""), {}).get("window") or "SEED"
                ),
                "schedule_credit": str(item.get("reconciliation_id") or "") in credited_ids,
                "historical_evidence_eligible": item.get("historical_evidence_eligible"),
                "production_status": item.get("production_status"),
            }
            for item in (_row(value) for value in records)
            if str(item.get("replication_id") or "") == str(row.get("replication_id") or "")
            and str(item.get("execution_status") or "") == "COMPLETE"
            and (
                str(item.get("reconciliation_id") or "") == str(row.get("seed_reconciliation_id") or "")
                or _parse_instant(item.get("retrieved_at"), field="retrieved_at") >= first_future_window
            )
        ),
        key=lambda item: str(item.get("retrieved_at") or ""),
    )
    inventory_direct_ids = {str(item.get("reconciliation_id") or "") for item in observation_inventory}
    inventory_direct_by_id = {
        str(item.get("reconciliation_id") or ""): item for item in observation_inventory
        if str(item.get("reconciliation_id") or "")
    }

    def triangulation_is_admissible(value: Any) -> bool:
        item = _row(value)
        results = [row for row in (item.get("series_results") or ()) if isinstance(row, Mapping)]
        direct_parent = inventory_direct_by_id.get(str(item.get("direct_reconciliation_id") or ""))
        return (
            str(item.get("replication_id") or "") == str(row.get("replication_id") or "")
            and str(item.get("direct_reconciliation_id") or "") in inventory_direct_ids
            and direct_parent is not None
            and str(item.get("direct_snapshot_id") or "") == str(direct_parent.get("direct_snapshot_id") or "")
            and str(item.get("direct_snapshot_fingerprint") or "") == str(direct_parent.get("direct_snapshot_fingerprint") or "")
            and str(item.get("protocol_version") or "") == "SRB_CROSS_PROVIDER_TRIANGULATION_V1"
            and str(item.get("execution_status") or "") == "COMPLETE"
            and str(item.get("source_integrity_status") or "") == "PASS"
            and str(item.get("coverage_status") or "") == "PASS"
            and str(item.get("comparability_status") or "") == "PASS"
            and str(item.get("triangulation_outcome") or "") in {"CONCORDANT", "MEASUREMENT_DIVERGENCE"}
            and str(item.get("history_semantics") or "") == DIRECT_BIS_HISTORY_SEMANTICS
            and str(item.get("point_in_time_status") or "") == "NOT_POINT_IN_TIME"
            and item.get("historical_evidence_eligible") is False
            and item.get("automatic_promotion_authorized") is False
            and str(item.get("production_status") or "") == "RESEARCH_ONLY"
            and _exact_int(item.get("expected_series_count")) == 3
            and _exact_int(item.get("source_series_count")) == 3
            and len(results) == 3
            and {str(result.get("market") or "") for result in results} == {"GB", "JP", "US"}
            and all(
                str(result.get("status") or "") in {"CONCORDANT", "MEASUREMENT_DIVERGENCE"}
                and _is_sha256(result.get("comparison_fingerprint"))
                and result.get("historical_evidence_eligible") is False
                for result in results
            )
            and bool(re.fullmatch(r"OECDCCRE-[0-9a-f]{16}", str(item.get("oecd_snapshot_id") or "")))
            and str(item.get("oecd_snapshot_path") or "")
            == f"public_data/oecd_reer_current_history/{item.get('oecd_snapshot_id')}"
            and _is_sha256(item.get("oecd_snapshot_fingerprint"))
            and _is_sha256(item.get("raw_csv_sha256"))
            and _is_sha256(item.get("triangulation_fingerprint"))
        )

    triangulations = [
        _row(item) for item in triangulation_records if triangulation_is_admissible(item)
    ]
    latest_triangulation = max(triangulations, key=lambda item: str(item.get("retrieved_at") or ""), default={})
    cross_provider_artifact = {
        key: latest_triangulation.get(key) for key in (
            "triangulation_id",
            "direct_reconciliation_id",
            "oecd_snapshot_id",
            "oecd_snapshot_fingerprint",
            "oecd_snapshot_path",
            "raw_csv_sha256",
            "triangulation_fingerprint",
            "retrieved_at",
            "latest_period",
            "triangulation_outcome",
            "historical_evidence_eligible",
            "production_status",
        )
    }
    gate_index = [
        {
            "gate_id": item.get("gate_id"),
            "status": item.get("status"),
            "artifact_refs": list(item.get("artifact_refs") or ()),
        }
        for item in (_row(value) for value in mission_gates)
        if str(item.get("gate_id") or "")
    ]
    result_row = _row(retained_result) if retained_result is not None else {}
    historical_artifact_index = {
        key: result_row.get(key) for key in (
            "report_id",
            "protocol_id",
            "experiment_id",
            "snapshot_id",
            "snapshot_fingerprint",
            "executor_code_digest",
            "conclusion",
            "gate_status",
            "common_support_status",
            "common_split_status",
            "point_in_time_status",
            "production_status",
        )
    }
    artifact_inventory_fingerprint = _digest({
        "program_id": row.get("program_id"),
        "program_protocol_fingerprint": row.get("protocol_fingerprint"),
        "direct_observations": observation_inventory,
        "latest_cross_provider_artifact": cross_provider_artifact,
        "prospective_calendar_fingerprint": state.get("calendar_fingerprint"),
        "historical_artifact_index": historical_artifact_index,
        "mission_gate_index": gate_index,
    })
    dossier = {
        "dossier_version": "SRB_RESEARCH_CLOSURE_DOSSIER_V1",
        "generated_at": state["as_of"],
        "program_id": row.get("program_id"),
        "program_protocol_fingerprint": row.get("protocol_fingerprint"),
        "replication_id": row.get("replication_id"),
        "question_id": str(question_id or "UNKNOWN"),
        "mission_snapshot_id": str(mission_snapshot_id or "UNKNOWN"),
        "mission_status": str(mission_status or "UNKNOWN"),
        "core_study_status": str(core_study_status or "UNKNOWN"),
        "mission_status_authority": "CALLER_SUPPLIED_REQUIRES_REGISTRY_RECOMPUTATION",
        "mission_gate_count": int(mission_gate_count),
        "mission_gate_index": gate_index,
        "historical_artifact_index": historical_artifact_index,
        "current_study_review_status": (
            "CORE_DOSSIER_READY_FOR_REVIEW"
            if core_study_status == "READY_FOR_REVIEW" else "CORE_DOSSIER_NOT_READY"
        ),
        "longitudinal_program_status": state["program_status"],
        "forward_vintage_maturity": state["maturity"],
        "schedule": {
            key: state[key] for key in (
                "first_future_window",
                "next_observation_at",
                "observation_due",
                "scheduled_windows_opened",
                "captured_windows",
                "missed_windows",
                "duplicate_window_observations",
                "late_window_observations",
                "calendar_fingerprint",
            )
        },
        "prospective_calendar": state.get("calendar") or [],
        "latest_cross_provider_outcome": latest_triangulation.get("triangulation_outcome") or "NOT_AVAILABLE",
        "seed": {
            "reconciliation_id": row.get("seed_reconciliation_id"),
            "snapshot_id": row.get("seed_snapshot_id"),
            "snapshot_fingerprint": row.get("seed_snapshot_fingerprint"),
            "retrieved_at": row.get("seed_retrieved_at"),
            "latest_period": row.get("seed_latest_period"),
        },
        "prospective_observation_inventory": observation_inventory,
        "latest_cross_provider_artifact": cross_provider_artifact,
        "latest_cross_provider_artifact_verification": (
            "BASIC_PROVENANCE_CHECK_PASS_NOT_FULL_RECOMPUTATION"
            if latest_triangulation else "NOT_AVAILABLE"
        ),
        "artifact_inventory_fingerprint": artifact_inventory_fingerprint,
        "verification_scope": "INDEX_ONLY_REFERENCED_STATE_AND_CONTENT_ADDRESSED_ARTIFACTS_REQUIRED",
        "evidence_boundaries": {
            "historical_oos_result_status": "NOT_EVALUATED_BY_THIS_EXPORT",
            "prospective_observation_program_active": True,
            "prospective_vintage_study_ready": state["maturity"]["status"] == "READY_FOR_FORWARD_VINTAGE_STUDY",
            "human_independent_replication_established": False,
            "peer_review_established": False,
            "scientific_truth_established": False,
            "production_authorized": False,
        },
        "closure_interpretation": (
            "The current governed dossier may be reviewed independently of the still-maturing prospective ledger. "
            "Neither status authorizes production or scientific truth."
        ),
        "historical_backfill_permitted": False,
        "automatic_promotion_authorized": False,
        "production_status": "RESEARCH_ONLY",
        "timing_authority": (
            "UTC timestamps are asserted by the acquisition runtime and bound into derived observation receipts. "
            "They are not trusted third-party timestamp attestations; append-only state plus external SHA-256 backups are required."
        ),
    }
    return {**dossier, "dossier_fingerprint": _digest(dossier)}


__all__ = [
    "PROSPECTIVE_OBSERVATION_PROTOCOL_VERSION",
    "build_research_closure_dossier",
    "evaluate_prospective_observation_program",
    "freeze_prospective_observation_program",
    "validate_prospective_observation_program",
]
