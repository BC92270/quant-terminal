"""Point-in-time data contracts and fail-closed capability checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .types import AvailabilityState, CapabilityStatus, FieldStatus, ValidationState

CORE_FIELDS = ("open", "high", "low", "close")
OPTIONAL_FIELDS = (
    "volume",
    "dividend",
    "split",
    "delisting_return",
    "universe_membership",
    "shortable",
    "borrow_rate",
    "rebate_rate",
    "shares_outstanding",
    "spread_bps",
)
CAPABILITY_FIELDS = {
    "bar_execution": ("open", "high", "low", "close"),
    "volume_impact": ("volume",),
    "corporate_actions": ("dividend", "split"),
    "survivorship_control": ("universe_membership", "delisting_return"),
    "short_financing": ("shortable", "borrow_rate"),
    "capacity": ("volume",),
    "spread_calibration": ("spread_bps",),
}


@dataclass
class DataCatalogAssessment:
    symbol: str
    source: str
    as_of: str
    point_in_time: bool
    rows: int
    fingerprint: str
    verdict: ValidationState
    fields: dict[str, FieldStatus]
    capabilities: dict[str, CapabilityStatus]
    issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "as_of": self.as_of,
            "point_in_time": self.point_in_time,
            "rows": self.rows,
            "fingerprint": self.fingerprint,
            "verdict": self.verdict.value,
            "fields": {key: asdict(value) | {"state": value.state.value} for key, value in self.fields.items()},
            "capabilities": {
                key: asdict(value) | {"state": value.state.value}
                for key, value in self.capabilities.items()
            },
            "issues": list(self.issues),
        }


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result.columns = [str(col).strip().lower().replace(" ", "_") for col in result.columns]
    return result


def frame_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return sha256(b"EMPTY").hexdigest()
    clean = _normalise_columns(frame)
    hashed = pd.util.hash_pandas_object(clean, index=True).values.tobytes()
    signature = "|".join(map(str, clean.columns)).encode()
    return sha256(signature + hashed).hexdigest()


def assess_market_data(
    frame: pd.DataFrame,
    *,
    symbol: str,
    source: str,
    as_of: str | None = None,
    point_in_time: bool = False,
    required_capabilities: Iterable[str] = (),
) -> DataCatalogAssessment:
    clean = _normalise_columns(frame)
    as_of_value = str(as_of or (clean.index.max() if len(clean.index) else "UNAVAILABLE"))
    fields: dict[str, FieldStatus] = {}
    issues: list[str] = []

    for name in CORE_FIELDS + OPTIONAL_FIELDS:
        required = name in CORE_FIELDS
        if name not in clean.columns:
            fields[name] = FieldStatus(
                name, AvailabilityState.UNAVAILABLE, required,
                "Required field missing" if required else "Not supplied by active adapter",
            )
            if required:
                issues.append(f"missing required field: {name}")
            continue
        series = pd.to_numeric(clean[name], errors="coerce")
        missing = float(series.isna().mean()) if len(series) else 1.0
        if name == "volume":
            non_positive = float((series.fillna(0.0) <= 0.0).mean()) if len(series) else 1.0
            effective_missing = max(missing, non_positive)
            if not bool((series > 0.0).any()):
                state = AvailabilityState.UNAVAILABLE
                reason = "DATA REQUIRED: no strictly positive volume observations"
            elif effective_missing > 0:
                state = AvailabilityState.PARTIAL
                reason = f"{effective_missing:.2%} missing or non-positive"
            else:
                state = AvailabilityState.AVAILABLE
                reason = "complete and strictly positive"
            missing = effective_missing
        else:
            state = AvailabilityState.AVAILABLE if missing == 0 else AvailabilityState.PARTIAL
            reason = "complete" if missing == 0 else f"{missing:.2%} missing"
        fields[name] = FieldStatus(name, state, required, reason, missing, source)
        if required and missing > 0:
            issues.append(f"{name}: {missing:.2%} missing")

    if not clean.index.is_monotonic_increasing:
        issues.append("index is not chronological")
    if clean.index.has_duplicates:
        issues.append("duplicate timestamps")
    if all(name in clean for name in CORE_FIELDS) and len(clean):
        o, h, l, c = (pd.to_numeric(clean[name], errors="coerce") for name in CORE_FIELDS)
        invalid_ohlc = (h < pd.concat([o, c], axis=1).max(axis=1)) | (
            l > pd.concat([o, c], axis=1).min(axis=1)
        )
        non_positive = pd.concat([o, h, l, c], axis=1).le(0).any(axis=1)
        if bool(invalid_ohlc.any()):
            issues.append(f"invalid OHLC envelope: {int(invalid_ohlc.sum())} rows")
        if bool(non_positive.any()):
            issues.append(f"non-positive prices: {int(non_positive.sum())} rows")

    capabilities: dict[str, CapabilityStatus] = {}
    requested = set(required_capabilities)
    for capability, needed in CAPABILITY_FIELDS.items():
        absent = [
            name for name in needed
            if fields.get(name, FieldStatus(name, AvailabilityState.UNAVAILABLE, False)).state
            == AvailabilityState.UNAVAILABLE
        ]
        partial = [
            name for name in needed
            if fields.get(name, FieldStatus(name, AvailabilityState.UNAVAILABLE, False)).state
            == AvailabilityState.PARTIAL
        ]
        if absent:
            state = AvailabilityState.UNAVAILABLE
            reason = "DATA REQUIRED: " + ", ".join(absent)
        elif partial:
            state = AvailabilityState.PARTIAL
            reason = "Incomplete fields: " + ", ".join(partial)
        else:
            state = AvailabilityState.AVAILABLE
            reason = "All required fields available"
        capabilities[capability] = CapabilityStatus(capability, state, reason, tuple(needed))
        if capability in requested and state == AvailabilityState.UNAVAILABLE:
            issues.append(f"{capability}: {reason}")

    capabilities["point_in_time"] = CapabilityStatus(
        "point_in_time",
        AvailabilityState.AVAILABLE if point_in_time else AvailabilityState.UNAVAILABLE,
        "Snapshot explicitly declared point-in-time" if point_in_time else "DATA REQUIRED: point-in-time membership/source",
        (),
    )
    if "point_in_time" in requested and not point_in_time:
        issues.append("point_in_time: DATA REQUIRED")

    core_unavailable = any(fields[name].state == AvailabilityState.UNAVAILABLE for name in CORE_FIELDS)
    hard_quality_issue = any(
        token in issue for issue in issues
        for token in ("invalid OHLC", "non-positive", "duplicate", "missing required")
    )
    requested_unavailable = any(
        capabilities[name].state == AvailabilityState.UNAVAILABLE
        for name in requested if name in capabilities
    )
    if core_unavailable or hard_quality_issue:
        verdict = ValidationState.FAIL
    elif requested_unavailable:
        verdict = ValidationState.UNAVAILABLE
    elif issues:
        verdict = ValidationState.WARN
    else:
        verdict = ValidationState.PASS

    return DataCatalogAssessment(
        symbol=str(symbol),
        source=str(source),
        as_of=as_of_value,
        point_in_time=bool(point_in_time),
        rows=int(len(clean)),
        fingerprint=frame_fingerprint(clean),
        verdict=verdict,
        fields=fields,
        capabilities=capabilities,
        issues=issues,
    )


def capability_or_unavailable(
    assessment: DataCatalogAssessment,
    capability: str,
) -> CapabilityStatus:
    return assessment.capabilities.get(
        capability,
        CapabilityStatus(
            capability,
            AvailabilityState.UNAVAILABLE,
            "Capability is not declared by this data contract",
            (),
        ),
    )
