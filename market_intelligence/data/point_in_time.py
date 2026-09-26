"""Small, deterministic point-in-time primitives."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import re
from typing import Any, Iterable, Mapping

from ..contracts import as_utc


def _natural_revision_key(value: Any) -> tuple[tuple[int, Any], ...]:
    """Return a deterministic key where numeric revision segments sort numerically."""

    parts = re.split(r"(\d+)", str(value or "").casefold())
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in parts if part)


def _stable_record_key(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=True)


def tradable_time(
    publication_time: Any,
    first_seen_time: Any,
    processing_buffer: timedelta = timedelta(0),
) -> datetime:
    if processing_buffer < timedelta(0):
        raise ValueError("processing_buffer cannot be negative")
    return max(as_utc(publication_time), as_utc(first_seen_time)) + processing_buffer


def assert_cutoff(feature_known_at: Any, prediction_time: Any, *, label: str = "feature") -> None:
    if as_utc(feature_known_at) > as_utc(prediction_time):
        raise ValueError(f"{label} is not point-in-time safe for this prediction")


def latest_known_at(
    records: Iterable[Mapping[str, Any]],
    as_of: Any,
    *,
    known_at_field: str = "available_at",
    revision_field: str = "revision_id",
) -> Mapping[str, Any] | None:
    cutoff = as_utc(as_of)
    eligible = []
    for record in records:
        if known_at_field not in record:
            raise KeyError(f"Missing point-in-time field: {known_at_field}")
        known_at = as_utc(record[known_at_field])
        if known_at <= cutoff:
            eligible.append(
                (
                    known_at,
                    _natural_revision_key(record.get(revision_field, "")),
                    _stable_record_key(record),
                    record,
                )
            )
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[0], item[1], item[2]))
    return eligible[-1][3]


def relationship_valid_at(edge: Mapping[str, Any], as_of: Any) -> bool:
    cutoff = as_utc(as_of)
    valid_from = as_utc(edge["valid_from"])
    valid_to_raw = edge.get("valid_to")
    valid_to = as_utc(valid_to_raw) if valid_to_raw else None
    return valid_from <= cutoff and (valid_to is None or cutoff < valid_to)
