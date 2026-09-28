"""Point-in-time data contracts and fail-closed capability checks."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .types import AvailabilityState, CapabilityStatus, FieldStatus, ValidationState

CORE_FIELDS = ("open", "high", "low", "close")
OPTIONAL_FIELDS = (
    "volume",
    "adj_close",
    "dividend",
    "split",
    "delisting_return",
    "universe_membership",
    "shortable",
    "locate_available",
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
    "short_financing": ("shortable", "locate_available", "borrow_rate"),
    "capacity": ("volume",),
    "spread_calibration": ("spread_bps",),
}


@dataclass
class DataCatalogAssessment:
    symbol: str
    source: str
    as_of: str
    point_in_time: bool
    price_basis: str
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
            "price_basis": self.price_basis,
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
    aliases = {
        "adjusted_close": "adj_close",
        "dividends": "dividend",
        "stock_splits": "split",
        "is_shortable": "shortable",
        "locate": "locate_available",
    }
    for source, target in aliases.items():
        if source in result.columns and target not in result.columns:
            result = result.rename(columns={source: target})
    return result


def _field_series(frame: pd.DataFrame, name: str) -> pd.Series:
    values = frame[name]
    if name in {"shortable", "locate_available", "universe_membership"}:
        if pd.api.types.is_bool_dtype(values):
            return values.astype("boolean")
        return values.map({
            True: True, False: False, 1: True, 0: False,
            "1": True, "0": False, "true": True, "false": False,
            "TRUE": True, "FALSE": False, "yes": True, "no": False,
            "YES": True, "NO": False,
        }).astype("boolean")
    return pd.to_numeric(values, errors="coerce")


def frame_fingerprint(frame: pd.DataFrame) -> str:
    if frame.empty:
        return sha256(b"EMPTY").hexdigest()
    clean = _normalise_columns(frame)
    hashed = pd.util.hash_pandas_object(clean, index=True).values.tobytes()
    semantic_metadata = {
        key: frame.attrs.get(key)
        for key in (
            "price_basis", "periods_per_year", "interval_label",
            "corporate_actions_embedded", "data_quality_issues",
        )
        if key in frame.attrs
    }
    signature = (
        "|".join(map(str, clean.columns))
        + "|"
        + json.dumps(semantic_metadata, sort_keys=True, default=str)
    ).encode()
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
    price_basis = str(frame.attrs.get("price_basis", "unspecified")).strip().lower()
    inherited_issues = frame.attrs.get("data_quality_issues", ())
    if isinstance(inherited_issues, str):
        inherited_issues = (inherited_issues,)
    as_of_value = str(as_of or (clean.index.max() if len(clean.index) else "UNAVAILABLE"))
    fields: dict[str, FieldStatus] = {}
    issues: list[str] = [f"source quality: {issue}" for issue in inherited_issues if str(issue).strip()]

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
        series = _field_series(clean, name)
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
        elif name == "split":
            invalid = float((series.dropna() < 0).mean()) if len(series.dropna()) else 0.0
            if invalid > 0:
                state = AvailabilityState.PARTIAL
                reason = f"{invalid:.2%} invalid negative split ratios"
                issues.append(f"split: {invalid:.2%} invalid negative ratios")
            else:
                state = AvailabilityState.AVAILABLE if missing == 0 else AvailabilityState.PARTIAL
                reason = "complete; zero denotes no event" if missing == 0 else f"{missing:.2%} unknown"
        elif name == "borrow_rate":
            negative = float((series.dropna() < 0).mean()) if len(series.dropna()) else 0.0
            if negative > 0:
                state = AvailabilityState.PARTIAL
                reason = f"{negative:.2%} invalid negative rates"
                issues.append(f"borrow_rate: {negative:.2%} invalid negative observations")
            else:
                state = AvailabilityState.AVAILABLE if missing == 0 else AvailabilityState.PARTIAL
                reason = "complete" if missing == 0 else f"{missing:.2%} missing"
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
        adjusted_total_return = price_basis in {
            "adjusted", "adjusted_total_return", "total_return", "total_return_adjusted",
        }
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
        if capability == "corporate_actions" and adjusted_total_return:
            state = AvailabilityState.ESTIMATED
            reason = (
                "Corporate-action economics are embedded in total-return-adjusted prices; "
                "raw split/dividend replay is unavailable and must not be double-counted"
            )
        elif absent:
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
        elif capability in requested and state in {AvailabilityState.PARTIAL, AvailabilityState.ESTIMATED}:
            issues.append(f"{capability}: {state.value} — {reason}")

    capabilities["point_in_time"] = CapabilityStatus(
        "point_in_time",
        AvailabilityState.AVAILABLE if point_in_time else AvailabilityState.UNAVAILABLE,
        "Snapshot explicitly declared point-in-time" if point_in_time else "DATA REQUIRED: point-in-time membership/source",
        (),
    )
    if "point_in_time" in requested and not point_in_time:
        issues.append("point_in_time: DATA REQUIRED")

    core_incomplete = any(fields[name].state != AvailabilityState.AVAILABLE for name in CORE_FIELDS)
    hard_quality_issue = any(
        token in issue for issue in issues
        for token in ("invalid OHLC", "invalid negative", "non-positive", "duplicate", "missing required")
    )
    requested_unavailable = any(
        capabilities[name].state == AvailabilityState.UNAVAILABLE
        for name in requested if name in capabilities
    )
    requested_degraded = any(
        capabilities[name].state in {AvailabilityState.PARTIAL, AvailabilityState.ESTIMATED, AvailabilityState.STALE}
        for name in requested if name in capabilities
    )
    if core_incomplete or hard_quality_issue:
        verdict = ValidationState.FAIL
    elif requested_unavailable:
        verdict = ValidationState.UNAVAILABLE
    elif requested_degraded:
        verdict = ValidationState.WARN
    elif issues:
        verdict = ValidationState.WARN
    else:
        verdict = ValidationState.PASS

    return DataCatalogAssessment(
        symbol=str(symbol),
        source=str(source),
        as_of=as_of_value,
        point_in_time=bool(point_in_time),
        price_basis=price_basis,
        rows=int(len(clean)),
        fingerprint=frame_fingerprint(frame),
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
