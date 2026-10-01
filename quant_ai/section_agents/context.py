"""Allowlisted context extraction for Streamlit and backend callers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import is_dataclass, asdict
from datetime import date, datetime
from enum import Enum
import hashlib
import json
import math
import re
from typing import Any
from uuid import uuid4

from .contracts import DataSourceRef, GovernanceMode, SectionContextEnvelope
from .registry import SectionAgentRegistry, build_default_section_registry


COMMON_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "route",
        "current_route",
        "workspace",
        "active_view",
        "view",
        "mode",
        "security",
        "active_security",
        "symbol",
        "ticker",
        "selected_symbol",
        "symbols",
        "primary_function",
        "asset",
        "asset_type",
        "period",
        "interval",
        "start_date",
        "end_date",
        "date_range",
        "filters",
        "widget_values",
        "widgets",
        "section_state",
        "data_sources",
        "sources",
        "data_as_of",
        "as_of",
        "permissions",
    }
)

_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "password",
    "passwd",
    "secret",
    "credential",
    "access_token",
    "refresh_token",
    "private_key",
)
_DROP = object()

GENERIC_SECTION_STATE_KEYS: frozenset[str] = frozenset(
    {
        "analysis_available",
        "price_observations",
        "analysis_summary",
        "data_quality",
        "evidence_state",
        "freshness",
    }
)


def _key(value: object) -> str:
    return str(value or "").strip().casefold()


def _sensitive_key(value: object) -> bool:
    normalized = re.sub(r"[^a-z0-9_]+", "_", _key(value))
    return any(part in normalized for part in _SENSITIVE_PARTS)


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    """Return bounded JSON data, omitting unsupported or sensitive objects."""

    if depth > 4:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return round(value, 10) if math.isfinite(value) else None
    if isinstance(value, str):
        return value[:2_000]
    if isinstance(value, Enum):
        return _sanitize(value.value, depth=depth + 1)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return _sanitize(asdict(value), depth=depth + 1)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:64]:
            key_text = str(raw_key)[:160]
            if _sensitive_key(key_text):
                continue
            item = _sanitize(raw_value, depth=depth + 1)
            if item is not _DROP:
                result[key_text] = item
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items: list[Any] = []
        for raw_item in list(value)[:48]:
            item = _sanitize(raw_item, depth=depth + 1)
            if item is not _DROP:
                items.append(item)
        return items
    # DataFrames and similar table objects are represented by schema only.
    shape = getattr(value, "shape", None)
    columns = getattr(value, "columns", None)
    if isinstance(shape, tuple) and columns is not None:
        return {
            "rows": int(shape[0]) if shape else 0,
            "columns": [str(column)[:120] for column in list(columns)[:32]],
            "values_omitted": True,
        }
    return _DROP


def _first_text(values: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text[:500]
    return ""


def _string_tuple(value: Any, *, limit: int = 32) -> tuple[str, ...]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, Sequence):
        candidates = list(value)[:limit]
    else:
        candidates = []
    result: list[str] = []
    for item in candidates:
        text = str(item).strip()[:240]
        if text and not _sensitive_key(text) and text not in result:
            result.append(text)
    return tuple(result)


def _source_refs(value: Any) -> tuple[DataSourceRef, ...]:
    if isinstance(value, (str, Mapping)):
        candidates = [value]
    elif isinstance(value, Sequence):
        candidates = list(value)[:32]
    else:
        candidates = []
    refs: list[DataSourceRef] = []
    for item in candidates:
        if isinstance(item, str):
            source_id = item.strip()[:240]
            if source_id:
                refs.append(DataSourceRef(source_id=source_id, title=source_id))
            continue
        if not isinstance(item, Mapping):
            continue
        safe = _sanitize(item)
        if not isinstance(safe, Mapping):
            continue
        source_id = _first_text(safe, "source_id", "id", "source", "name")
        if not source_id:
            continue
        refs.append(
            DataSourceRef(
                source_id=source_id,
                title=_first_text(safe, "title", "label", "name"),
                as_of=_first_text(safe, "as_of", "data_as_of", "updated_at"),
                vintage=_first_text(safe, "vintage", "release"),
                freshness=_first_text(safe, "freshness", "status"),
            )
        )
    return tuple(refs)


class SectionContextBuilder:
    def __init__(self, registry: SectionAgentRegistry | None = None) -> None:
        self.registry = registry or build_default_section_registry()

    def build(
        self,
        section_id: str,
        raw_context: Mapping[str, Any] | None,
        *,
        conversation_id: str = "",
        user_id: str = "",
        tenant_id: str = "",
        request_id: str = "",
    ) -> SectionContextEnvelope:
        manifest = self.registry.require(section_id)
        if raw_context is None:
            raw_context = {}
        if not isinstance(raw_context, Mapping):
            raise TypeError("raw_context must be a mapping.")

        allowed = COMMON_CONTEXT_KEYS.union(manifest.allowed_context_keys)
        values: dict[str, Any] = {}
        for raw_key, raw_value in raw_context.items():
            normalized = _key(raw_key)
            if normalized not in allowed or _sensitive_key(normalized):
                continue
            sanitized = _sanitize(raw_value)
            if sanitized is not _DROP:
                values[normalized] = sanitized

        security = _first_text(values, "active_security", "security", "selected_symbol", "symbol", "ticker")
        symbols = _string_tuple(values.get("symbols"))
        if security and security not in symbols:
            symbols = (security, *symbols)

        date_range = values.get("date_range") if isinstance(values.get("date_range"), Mapping) else {}
        if not date_range:
            date_range = {
                key: values[key]
                for key in ("period", "interval", "start_date", "end_date")
                if key in values
            }

        filters = values.get("filters") if isinstance(values.get("filters"), Mapping) else {}
        widgets = values.get("widget_values", values.get("widgets", {}))
        widget_values = widgets if isinstance(widgets, Mapping) else {}
        explicit_state = values.get("section_state")
        explicit_state = explicit_state if isinstance(explicit_state, Mapping) else {}
        allowed_state_keys = set(manifest.allowed_context_keys).union(GENERIC_SECTION_STATE_KEYS)
        section_state = {
            key: values[key]
            for key in manifest.allowed_context_keys
            if key in values
        }
        section_state.update(
            {
                str(key): value
                for key, value in explicit_state.items()
                if _key(key) in allowed_state_keys and not _sensitive_key(key)
            }
        )
        sources = _source_refs(values.get("data_sources", values.get("sources", ())))
        permissions = _string_tuple(values.get("permissions"), limit=24)

        hash_payload = {
            "section_id": manifest.section_id,
            "route": _first_text(values, "route", "current_route", "workspace"),
            "active_view": _first_text(values, "active_view", "view", "mode"),
            "security": security,
            "primary_function": _first_text(values, "primary_function"),
            "asset_type": _first_text(values, "asset_type", "asset"),
            "symbols": symbols,
            "date_range": date_range,
            "filters": filters,
            "widget_values": widget_values,
            "section_state": section_state,
            "data_sources": [source.to_dict() for source in sources],
            "permissions": permissions,
            "data_as_of": _first_text(values, "data_as_of", "as_of"),
            "governance_mode": GovernanceMode.RESEARCH_ONLY.value,
        }
        encoded = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        context_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()

        return SectionContextEnvelope(
            section_id=manifest.section_id,
            request_id=request_id or uuid4().hex,
            conversation_id=str(conversation_id)[:240],
            user_id=str(user_id)[:240],
            tenant_id=str(tenant_id)[:240],
            route=hash_payload["route"],
            active_view=hash_payload["active_view"],
            security=security,
            primary_function=hash_payload["primary_function"],
            asset_type=hash_payload["asset_type"],
            symbols=symbols,
            date_range=date_range,
            filters=filters,
            widget_values=widget_values,
            section_state=section_state,
            data_sources=sources,
            permissions=permissions,
            data_as_of=hash_payload["data_as_of"],
            context_hash=context_hash,
        )
