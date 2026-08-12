"""Country Intelligence payload fusion and display helpers."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from .assets import country_profiles
from .config import MODULE_VERSION


def _meaningful(value: Any) -> bool:
    return value not in (None, "", [], {})


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derived_risk_channels(quant: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose model pillars as sourced country-risk channels."""

    labels = {
        "macro": "Macro / sovereign",
        "external": "Trade / external",
        "resilience": "Adaptive capacity",
        "resource": "Food / resource",
    }
    channels: list[dict[str, Any]] = []
    for pillar, label in labels.items():
        record = dict((quant.get("pillars") or {}).get(pillar) or {})
        score = _number(record.get("score"))
        if score is None:
            continue
        coverage = round(100 * float(record.get("coverage") or 0))
        factors = int(record.get("factors") or 0)
        channels.append({
            "name": label,
            "score": round(score, 1),
            "why": f"{factors} official observation(s); {coverage}% pillar coverage; structural, not live.",
        })
    return channels


def _energy_from_indicators(existing: dict[str, Any], indicators: dict[str, Any]) -> dict[str, Any]:
    """Replace generic placeholders with available official energy context."""

    energy = dict(existing or {})
    access = _number((indicators.get("EG.ELC.ACCS.ZS") or {}).get("value"))
    import_ratio = _number((indicators.get("EG.IMP.CONS.ZS") or {}).get("value"))
    if import_ratio is not None:
        energy["import"] = f"Net energy imports {round(import_ratio, 1)}% of use"
    elif str(energy.get("import") or "").casefold() in {"", "atlas profile pending", "atlas pending"}:
        energy["import"] = "Net energy-import ratio unavailable"
    if access is not None and str(energy.get("exposure") or "").casefold() in {
        "",
        "no dedicated energy profile yet.",
    }:
        energy["exposure"] = f"Electricity access {round(access, 1)}% of population (World Bank WDI)."
    return energy


def _macro_from_indicators(indicators: dict[str, Any]) -> dict[str, Any]:
    def value(code: str, digits: int = 1) -> Any:
        raw = (indicators.get(code) or {}).get("value")
        try:
            return round(float(raw), digits)
        except (TypeError, ValueError):
            return None

    years = [str(record.get("date")) for record in indicators.values() if isinstance(record, dict) and record.get("date")]
    return {
        "gdp": value("NY.GDP.MKTP.KD.ZG"),
        "gdp_usd": value("NY.GDP.MKTP.CD", 0),
        "gdp_capita": value("NY.GDP.PCAP.CD", 0),
        "cpi": value("FP.CPI.TOTL.ZG"),
        "debt": value("GC.DOD.TOTL.GD.ZS"),
        "external_debt_usd": value("DT.DOD.DECT.CD", 0),
        "unemployment": value("SL.UEM.TOTL.ZS"),
        "trade_gdp": value("NE.TRD.GNFS.ZS"),
        "imports_gdp": value("NE.IMP.GNFS.ZS"),
        "fdi_gdp": value("BX.KLT.DINV.WD.GD.ZS"),
        "source": f"World Bank WDI · latest country observations ({min(years)}–{max(years)})" if years else "World Bank WDI · unavailable",
    }


def _offline_index() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_iso: dict[str, dict[str, Any]] = {}
    by_name: dict[str, dict[str, Any]] = {}
    for profile in country_profiles():
        iso3 = str((profile.get("meta") or {}).get("iso3") or "").upper()
        name = str(profile.get("country") or "").casefold()
        if iso3:
            by_iso[iso3] = profile
        if name:
            by_name[name] = profile
    return by_iso, by_name


def _merge_profile(live: dict[str, Any] | None, offline: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(offline)
    if isinstance(live, dict):
        # Keep current events and curated strategic context, but never let an
        # old placeholder overwrite sourced offline observations.
        for key in ("live", "history", "themes", "risk_channels", "watchlist", "scenario", "infra"):
            if _meaningful(live.get(key)):
                merged[key] = deepcopy(live[key])
        for key in ("energy",):
            current = dict(merged.get(key) or {})
            current.update({k: v for k, v in dict(live.get(key) or {}).items() if _meaningful(v)})
            merged[key] = current
        meta = dict(merged.get("meta") or {})
        meta.update({k: v for k, v in dict(live.get("meta") or {}).items() if _meaningful(v)})
        merged["meta"] = meta
    indicators = dict(merged.get("indicators") or {})
    merged["macro"] = _macro_from_indicators(indicators)
    merged["energy"] = _energy_from_indicators(dict(merged.get("energy") or {}), indicators)
    merged["indicator_snapshot"] = [
        [code, record.get("value"), record.get("date")]
        for code, record in sorted(indicators.items())
        if isinstance(record, dict) and record.get("value") is not None
    ]
    # Full provenance remains in the compressed country asset. The iframe gets
    # only compact value/year tuples to avoid duplicating source strings 3,000x.
    merged.pop("indicators", None)
    merged.pop("data_provenance", None)
    quant = dict(merged.get("quant") or {})
    confidence = quant.get("confidence")
    score = quant.get("score")
    merged["source_quality"] = confidence if confidence is not None else 0
    if score is not None:
        merged["operational"] = (
            f"Structural risk {score}/100 ({quant.get('regime')}); confidence {confidence}/100, "
            f"coverage {round(100 * float(quant.get('coverage') or 0))}%. Live intensity is modelled separately."
        )
        if not merged.get("risk_channels"):
            merged["risk_channels"] = _derived_risk_channels(quant)
        old_instability = dict((live or {}).get("instability") or {})
        old_score = _number(old_instability.get("score"))
        if old_score is None or old_score <= 0:
            color = "#ff4d5c" if score >= 75 else "#f59e0b" if score >= 50 else "#33ff88"
            merged["instability"] = {"score": score, "regime": "Structural", "color": color}
    return merged


def merge_payload(base_json: str | None, active_time: str = "24h") -> str:
    """Fuse cached institutional profiles with the current live event payload."""

    try:
        base = json.loads(str(base_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        base = {}
    live_profiles = base.get("profiles", []) if isinstance(base, dict) else []
    live_by_iso: dict[str, dict[str, Any]] = {}
    live_by_name: dict[str, dict[str, Any]] = {}
    for profile in live_profiles if isinstance(live_profiles, list) else []:
        if not isinstance(profile, dict):
            continue
        iso3 = str((profile.get("meta") or {}).get("iso3") or "").upper()
        name = str(profile.get("country") or "").casefold()
        if iso3:
            live_by_iso[iso3] = profile
        if name:
            live_by_name[name] = profile
    merged: list[dict[str, Any]] = []
    indicator_labels: dict[str, str] = {}
    for offline in country_profiles():
        iso3 = str((offline.get("meta") or {}).get("iso3") or "").upper()
        name = str(offline.get("country") or "").casefold()
        for code, record in dict(offline.get("indicators") or {}).items():
            if isinstance(record, dict) and record.get("indicator"):
                indicator_labels.setdefault(str(code), str(record["indicator"]))
        merged.append(_merge_profile(live_by_iso.get(iso3) or live_by_name.get(name), offline))
    return json.dumps(
        {
            "version": MODULE_VERSION,
            "active_time": str(active_time or "24h"),
            "indicator_labels": indicator_labels,
            "profiles": merged,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def quant_drawer_patch(html_payload: str) -> str:
    """Add transparent quant factors and uncertainty to the legacy drawer."""

    helper = r"""
 function quantPanel(p){
   const q=(p&&p.quant)||{}, pillars=q.pillars||{}, drivers=Array.isArray(q.drivers)?q.drivers:[];
   if(q.score===undefined || q.score===null) return '<div class="wmci-muted">Insufficient sourced observations for a comparable structural score.</div>';
   const rows=Object.entries(pillars).map(([k,v])=>{ const s=v&&v.score; return `<div class="wmci-row"><span>${esc(k)}</span><div class="wmci-bar"><i style="width:${Math.max(2,Math.min(100,num(s,0)))}%"></i></div><b>${s===null?'N/A':esc(s)}</b></div>`; }).join('');
   const ds=drivers.slice(0,5).map(d=>`<p><b>${esc(d.label)}</b> · risk percentile ${esc(d.risk_percentile)} · ${esc(d.year||'n/a')}</p>`).join('');
   const observations=Array.isArray(p.indicator_snapshot)?p.indicator_snapshot:[];
   const labels=(PAYLOAD&&PAYLOAD.indicator_labels)||{};
   const tape=observations.map(r=>`<span class="wmci-pill" title="${esc(r[0])}">${esc(labels[r[0]]||r[0])}: ${esc(r[1])} · ${esc(r[2]||'')}</span>`).join('');
   return `<div class="wmci-kgrid" style="padding:0 0 9px"><div class="wmci-k"><small>Structural risk</small><strong>${esc(q.score)}/100</strong><span class="wmci-pill">${esc(q.regime||'')}</span></div><div class="wmci-k"><small>Confidence</small><strong>${esc(q.confidence)}/100</strong><span class="wmci-pill">coverage ${esc(Math.round(num(q.coverage,0)*100))}%</span></div><div class="wmci-k"><small>Uncertainty</small><strong>${esc(q.uncertainty_low)}–${esc(q.uncertainty_high)}</strong><span class="wmci-pill">${esc(q.model||'')}</span></div></div>${rows}<h3 style="margin-top:14px">Primary drivers</h3>${ds}<h3 style="margin-top:14px">Official indicator tape</h3><div>${tape||'<span class="wmci-muted">No current observation</span>'}</div><p class="wmci-muted">${esc(q.interpretation||'')}</p>`;
 }
"""
    if "function quantPanel(p)" not in html_payload:
        html_payload = html_payload.replace(" function render(p){", helper + "\n function render(p){")
    old = '<div class="wmci-sec"><h3>Macro / sovereign</h3>${macroLine(macro)}</div>'
    new = old + '<div class="wmci-sec"><h3>Institutional quant model</h3>${quantPanel(p)}</div>'
    html_payload = html_payload.replace(old, new)
    return html_payload.replace(
        "watchlist:p.watchlist||[], exported_at",
        "watchlist:p.watchlist||[], quant:p.quant||{}, indicators:p.indicator_snapshot||[], exported_at",
    )
