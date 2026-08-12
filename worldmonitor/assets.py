"""Fast, immutable access to compiled WorldMonitor runtime assets."""

from __future__ import annotations

import gzip
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent / "data"
STATIC_PATH = DATA_DIR / "static_objects.json.gz"
COUNTRY_PATH = DATA_DIR / "country_atlas.json.gz"
LAYER_PATH = DATA_DIR / "layer_registry.json"
MANIFEST_PATH = DATA_DIR / "source_manifest.json"

STATIC_COLUMNS = [
    "object_id", "layer_id", "layer_label", "group", "title", "source_file",
    "collection", "source_class", "color", "icon", "metadata", "severity",
    "confidence", "kind", "lat", "lon", "points_json",
]


def _read_json(path: Path, compressed: bool = False) -> Any:
    opener = gzip.open if compressed else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def asset_manifest() -> dict[str, Any]:
    manifest = _read_json(MANIFEST_PATH)
    if int(manifest.get("schema_version", -1)) != 1:
        raise RuntimeError("Unsupported WorldMonitor asset schema")
    return manifest


@lru_cache(maxsize=1)
def _static_records() -> tuple[dict[str, Any], ...]:
    rows = _read_json(STATIC_PATH, compressed=True)
    if not isinstance(rows, list):
        raise RuntimeError("WorldMonitor static asset is not a record array")
    return tuple(row for row in rows if isinstance(row, dict))


def load_static_objects(_source_roots_key: str = "") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return a fresh frame from the compiled asset; never scan source archives."""

    records = _static_records()
    frame = pd.DataFrame.from_records(records, columns=STATIC_COLUMNS)
    if not frame.empty:
        frame["severity"] = pd.to_numeric(frame["severity"], errors="coerce").fillna(55).clip(0, 100)
        frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").fillna(60).clip(0, 100)
    manifest = asset_manifest()
    status = pd.DataFrame([{
        "file": STATIC_PATH.name,
        "collection": "COMPILED_WORLDMONITOR_ATLAS",
        "layer": "all",
        "status": "OK",
        "rows": len(frame),
        "detail": (
            f"schema={manifest.get('schema_version')}; build={manifest.get('built_at_utc')}; "
            "runtime_source=local-gzip; zip_scan=false"
        ),
    }])
    return frame, status


@lru_cache(maxsize=1)
def country_profiles() -> tuple[dict[str, Any], ...]:
    payload = _read_json(COUNTRY_PATH, compressed=True)
    rows = payload.get("profiles", []) if isinstance(payload, dict) else []
    return tuple(row for row in rows if isinstance(row, dict))


@lru_cache(maxsize=1)
def country_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for profile in country_profiles():
        meta = dict(profile.get("meta") or {})
        quant = dict(profile.get("quant") or {})
        score = quant.get("score")
        rows.append({
            "country": profile.get("country"),
            "iso3": meta.get("iso3"),
            "iso2": meta.get("iso2"),
            "flag": meta.get("flag", ""),
            "region": meta.get("region", ""),
            "lon": meta.get("lon"),
            "lat": meta.get("lat"),
            "bbox": meta.get("bbox"),
            "capital": meta.get("capital", ""),
            "capital_lon": meta.get("capital_lon"),
            "capital_lat": meta.get("capital_lat"),
            "score": score if score is not None else 0,
            "regime": quant.get("regime", "Insufficient data"),
            "source": "worldmonitor/country_atlas.json.gz",
        })
    return tuple(rows)


@lru_cache(maxsize=1)
def layer_registry() -> tuple[dict[str, Any], ...]:
    rows = _read_json(LAYER_PATH)
    return tuple(row for row in rows if isinstance(row, dict))


def clear_asset_caches() -> None:
    asset_manifest.cache_clear()
    _static_records.cache_clear()
    country_profiles.cache_clear()
    country_rows.cache_clear()
    layer_registry.cache_clear()

