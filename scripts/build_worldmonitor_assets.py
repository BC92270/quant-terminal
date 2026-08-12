#!/usr/bin/env python3
"""Compile reference archives and official snapshots into runtime assets.

This is the only WorldMonitor code allowed to inspect ZIP reference material.
The application itself reads only files under ``worldmonitor/data``.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "worldmonitor" / "data"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def read_gzip(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def write_gzip(path: Path, payload: Any) -> None:
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True, help="Read-only directory containing reference ZIPs")
    args = parser.parse_args()
    sources = args.sources.expanduser().resolve()
    if not sources.is_dir():
        raise SystemExit(f"source directory not found: {sources}")

    import worldmonitor_bridge_legacy_v211 as legacy
    from worldmonitor.config import ASSET_SCHEMA_VERSION, QUANT_MODEL_VERSION
    from worldmonitor.quant import score_country_profiles

    static, status = legacy.load_worldmonitor_static_objects_v211(str(sources))
    if len(static) < 1000:
        raise RuntimeError(f"compiled static atlas unexpectedly small: {len(static)}")
    static_records = json.loads(static.to_json(orient="records", force_ascii=False, double_precision=7))

    base_payload = json.loads(legacy._wmci_country_payload_v51(active_time="24h", live_enabled=False))
    profiles = [row for row in base_payload.get("profiles", []) if isinstance(row, dict)]
    if len(profiles) < 190:
        raise RuntimeError(f"country atlas unexpectedly small: {len(profiles)}")

    wdi_path = DATA / "world_bank_wdi.json.gz"
    wdi = read_gzip(wdi_path)
    indicators = wdi.get("indicators", {}) if isinstance(wdi, dict) else {}
    for profile in profiles:
        iso3 = str((profile.get("meta") or {}).get("iso3") or "").upper()
        country_indicators: dict[str, Any] = {}
        for code, series in indicators.items():
            record = (series.get("records") or {}).get(iso3) if isinstance(series, dict) else None
            if isinstance(record, dict):
                country_indicators[code] = record
        profile["indicators"] = country_indicators
        profile["data_provenance"] = {
            "structural": "World Bank World Development Indicators",
            "structural_snapshot": wdi.get("built_at_utc"),
            "historical_context": "WorldMonitor curated atlas",
            "live_events": "runtime provider mesh; never stored as structural data",
            "missing_data_policy": "no synthetic imputation",
        }
    profiles = score_country_profiles(profiles)

    live_ids = set(getattr(legacy, "_WM211_FINAL_LIVE_BACKED_LAYERS_V45", set()) or set())
    layers = []
    for spec in list(getattr(legacy, "LAYER_SPECS", []) or []):
        layers.append({
            "layer_id": str(spec.layer_id), "label": str(spec.label), "group": str(spec.group),
            "renderer": str(spec.renderer), "default": bool(spec.default), "color": str(spec.color),
            "icon": str(spec.icon), "source_class": str(spec.source_class), "note": str(spec.note),
            "live_backed": str(spec.layer_id) in live_ids,
        })

    DATA.mkdir(parents=True, exist_ok=True)
    static_path = DATA / "static_objects.json.gz"
    country_path = DATA / "country_atlas.json.gz"
    layer_path = DATA / "layer_registry.json"
    write_gzip(static_path, static_records)
    write_gzip(country_path, {"schema_version": ASSET_SCHEMA_VERSION, "profiles": profiles})
    layer_path.write_text(json.dumps(layers, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    covered = [len(profile.get("indicators") or {}) for profile in profiles]
    scored = [profile for profile in profiles if (profile.get("quant") or {}).get("score") is not None]
    source_archives = []
    for path in sorted(sources.glob("*.zip")):
        source_archives.append({"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size})
    manifest = {
        "schema_version": ASSET_SCHEMA_VERSION,
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "runtime_source": "compiled-local-assets",
        "zip_runtime_dependency": False,
        "static_objects": len(static_records),
        "static_layers_with_data": int(static["layer_id"].nunique()),
        "layers": len(layers),
        "live_backed_layers": len(live_ids),
        "layer_groups": len({row["group"] for row in layers}),
        "presets": len(getattr(legacy, "LAYER_PRESETS_V211", {}) or {}),
        "country_profiles": len(profiles),
        "country_indicator_coverage": {
            "countries_with_any": sum(value > 0 for value in covered),
            "countries_scored": len(scored),
            "median_indicators": sorted(covered)[len(covered) // 2],
            "max_indicators": max(covered),
            "official_series": len(indicators),
        },
        "quant_model": QUANT_MODEL_VERSION,
        "assets": {},
        "reference_archives": source_archives,
        "compiler_status_rows": len(status),
    }
    for path in (static_path, country_path, layer_path, wdi_path):
        manifest["assets"][path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    (DATA / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
