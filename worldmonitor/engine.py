"""Compatibility adapter that makes the package the sole runtime authority."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from .assets import asset_manifest, country_profiles, country_rows, layer_registry, load_static_objects
from .config import MODULE_VERSION
from .country import merge_payload, quant_drawer_patch
from .performance import apply_render_budget
from .providers import provider_summary


_LAST_RENDER_BUDGET: dict[str, Any] = {}


@lru_cache(maxsize=1)
def _legacy() -> Any:
    # The mature UI is retained as a compatibility renderer while data access,
    # country intelligence and map budgeting live in this package.
    from legacy import worldmonitor_runtime_v211 as legacy

    return legacy


@lru_cache(maxsize=1)
def _install_runtime() -> Any:
    legacy = _legacy()
    legacy.load_worldmonitor_static_objects_v211 = load_static_objects

    original_registry = legacy.build_layer_registry_v211

    def institutional_registry(objects, preset: str = "Balanced institutional", *args, **kwargs):
        registry = original_registry(objects, preset=preset, *args, **kwargs)
        for layer_id in ("ciiChoropleth", "resilienceScore"):
            mask = registry["layer_id"].astype(str).eq(layer_id)
            if mask.any():
                registry.loc[mask, "count"] = len(country_profiles())
                registry.loc[mask, "disabled"] = False
        return registry

    legacy.build_layer_registry_v211 = institutional_registry

    original_figure = legacy.build_plotly_figure_v211

    def budgeted_figure(objects, registry, *args, **kwargs):
        render_objects, stats = apply_render_budget(objects)
        _LAST_RENDER_BUDGET.clear()
        _LAST_RENDER_BUDGET.update(stats)
        figure = original_figure(render_objects, registry, *args, **kwargs)
        for trace in list(getattr(figure, "data", []) or []):
            meta = getattr(trace, "meta", None)
            if isinstance(meta, dict) and meta.get("wmci_country_atlas"):
                trace.meta = {**meta, "layer_id": "ciiChoropleth", "wm_iq": True}
                trace.name = "Institutional structural risk"
                trace.hovertemplate = "<b>%{text}</b><br>Structural risk %{z}/100<br>%{customdata[3]}<extra>WM-IQ</extra>"
        resilience_rows = []
        for profile in country_profiles():
            meta = dict(profile.get("meta") or {})
            pillar = dict(((profile.get("quant") or {}).get("pillars") or {}).get("resilience") or {})
            risk = pillar.get("score")
            if len(str(meta.get("iso3") or "")) == 3 and risk is not None:
                resilience_rows.append((profile, 100.0 - float(risk)))
        if resilience_rows:
            figure.add_trace(legacy.go.Choropleth(
                locations=[str((profile.get("meta") or {}).get("iso3")) for profile, _score in resilience_rows],
                z=[round(score, 1) for _profile, score in resilience_rows],
                text=[str(profile.get("country") or "") for profile, _score in resilience_rows],
                locationmode="ISO-3",
                name="Adaptive capacity",
                colorscale=[[0.0, "#7f1d1d"], [0.5, "#f59e0b"], [1.0, "#10b981"]],
                zmin=0,
                zmax=100,
                marker={"line": {"color": "rgba(148,163,184,.38)", "width": 0.4}},
                showscale=False,
                visible="legendonly",
                hovertemplate="<b>%{text}</b><br>Adaptive capacity %{z}/100<extra>WM-IQ</extra>",
                showlegend=False,
                meta={"layer_id": "resilienceScore", "wm_v211": True, "wm_iq": True, "kind": "country"},
            ))
        return figure

    legacy.build_plotly_figure_v211 = budgeted_figure

    original_payload = legacy._wmci_country_payload_v51

    def institutional_payload(active_time: str = "24h", live_enabled: bool = True) -> str:
        try:
            base = original_payload(active_time=active_time, live_enabled=live_enabled)
        except Exception:
            base = "{}"
        return merge_payload(base, active_time=active_time)

    legacy._wmci_country_payload_v51 = institutional_payload
    legacy._wmci_countryinfo_rows_v55 = lambda: [dict(row) for row in country_rows()]
    legacy._wmci_all_country_rows_v55 = lambda: [dict(row) for row in country_rows()]

    original_drawer = legacy._wmci_drawer_injection_v51

    def institutional_drawer(active_time: str = "24h", live_enabled: bool = True) -> str:
        return quant_drawer_patch(original_drawer(active_time=active_time, live_enabled=live_enabled))

    legacy._wmci_drawer_injection_v51 = institutional_drawer
    legacy.MODULE_VERSION = MODULE_VERSION
    return legacy


def get_capabilities() -> dict[str, Any]:
    manifest = asset_manifest()
    layers = layer_registry()
    return {
        "architecture": "worldmonitor-package",
        "native_runtime": False,
        "zip_runtime_dependency": False,
        "asset_schema": manifest.get("schema_version"),
        "static_objects": manifest.get("static_objects", 0),
        "layer_count": len({str(row.get("layer_id") or "") for row in layers}),
        "live_backed_layers": int(manifest.get("live_backed_layers", sum(bool(row.get("live_backed")) for row in layers))),
        "layer_groups": len({str(row.get("group") or "") for row in layers}),
        "presets": int(manifest.get("presets", 0)),
        "country_profiles": len(country_profiles()),
        "country_indicator_coverage": manifest.get("country_indicator_coverage", {}),
        "quant_model": manifest.get("quant_model"),
        "providers": provider_summary(),
        "render_budget": dict(_LAST_RENDER_BUDGET),
    }


def render() -> None:
    legacy = _install_runtime()
    renderer = getattr(legacy, "render_worldmonitor_bridge_v211", None)
    if not callable(renderer):
        raise RuntimeError("WorldMonitor compatibility renderer is unavailable")
    renderer()
