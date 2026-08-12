"""Transparent, missingness-aware geopolitical quant primitives.

The model deliberately separates structural country vulnerability from live
event intensity. It uses cross-sectional percentile ranks, exposes coverage
and freshness, and never imputes a country value with a random or synthetic
number.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import numpy as np

from .config import QUANT_MODEL_VERSION


INDICATOR_MODEL: dict[str, dict[str, Any]] = {
    "NY.GDP.MKTP.KD.ZG": {"pillar": "macro", "weight": 0.25, "risk": "low", "label": "GDP growth"},
    "FP.CPI.TOTL.ZG": {"pillar": "macro", "weight": 0.28, "risk": "target", "target": 2.0, "label": "Inflation"},
    "SL.UEM.TOTL.ZS": {"pillar": "macro", "weight": 0.23, "risk": "high", "label": "Unemployment"},
    "GC.DOD.TOTL.GD.ZS": {"pillar": "macro", "weight": 0.24, "risk": "high", "label": "Government debt"},
    "NE.IMP.GNFS.ZS": {"pillar": "external", "weight": 0.34, "risk": "high", "label": "Import dependence"},
    "NE.TRD.GNFS.ZS": {"pillar": "external", "weight": 0.22, "risk": "high", "label": "Trade exposure"},
    "EG.IMP.CONS.ZS": {"pillar": "external", "weight": 0.44, "risk": "high", "label": "Energy import dependence"},
    "NY.GDP.PCAP.CD": {"pillar": "resilience", "weight": 0.34, "risk": "low", "label": "Income capacity"},
    "EG.ELC.ACCS.ZS": {"pillar": "resilience", "weight": 0.26, "risk": "low", "label": "Electricity access"},
    "IT.NET.USER.ZS": {"pillar": "resilience", "weight": 0.20, "risk": "low", "label": "Digital access"},
    "FI.RES.TOTL.CD": {"pillar": "resilience", "weight": 0.20, "risk": "low", "label": "Reserve buffer"},
    "NV.AGR.TOTL.ZS": {"pillar": "resource", "weight": 0.58, "risk": "high", "label": "Agriculture dependence"},
    "SP.URB.TOTL.IN.ZS": {"pillar": "resource", "weight": 0.42, "risk": "high", "label": "Urban concentration"},
}

PILLAR_WEIGHTS = {"macro": 0.30, "external": 0.27, "resilience": 0.28, "resource": 0.15}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _risk_value(value: float, spec: Mapping[str, Any]) -> float:
    if spec.get("risk") == "target":
        return abs(value - float(spec.get("target", 0.0)))
    return -value if spec.get("risk") == "low" else value


def _percentile_map(values: Mapping[str, float]) -> dict[str, float]:
    """Midrank empirical percentile on 0..100, robust to ties/outliers."""

    if not values:
        return {}
    ordered = sorted(values.items(), key=lambda item: (item[1], item[0]))
    n = len(ordered)
    result: dict[str, float] = {}
    cursor = 0
    while cursor < n:
        end = cursor + 1
        while end < n and ordered[end][1] == ordered[cursor][1]:
            end += 1
        midrank = (cursor + end - 1) / 2
        percentile = 50.0 if n == 1 else 100.0 * midrank / (n - 1)
        for index in range(cursor, end):
            result[ordered[index][0]] = percentile
        cursor = end
    return result


def score_country_profiles(profiles: list[dict[str, Any]], as_of_year: int | None = None) -> list[dict[str, Any]]:
    """Attach comparable risk scores without filling missing observations."""

    year_now = int(as_of_year or datetime.now(timezone.utc).year)
    ranks: dict[str, dict[str, float]] = {}
    for code, spec in INDICATOR_MODEL.items():
        cross_section: dict[str, float] = {}
        for profile in profiles:
            iso3 = str((profile.get("meta") or {}).get("iso3") or "")
            record = (profile.get("indicators") or {}).get(code) or {}
            value = _finite(record.get("value"))
            if len(iso3) == 3 and value is not None:
                cross_section[iso3] = _risk_value(value, spec)
        ranks[code] = _percentile_map(cross_section)

    output: list[dict[str, Any]] = []
    total_model_weight = sum(PILLAR_WEIGHTS.values())
    for profile in profiles:
        row = dict(profile)
        iso3 = str((row.get("meta") or {}).get("iso3") or "")
        by_pillar: dict[str, list[tuple[float, float, str, int | None]]] = defaultdict(list)
        observed_weight = 0.0
        total_indicator_weight = sum(float(s["weight"]) * PILLAR_WEIGHTS[str(s["pillar"])] for s in INDICATOR_MODEL.values())
        for code, spec in INDICATOR_MODEL.items():
            percentile = ranks.get(code, {}).get(iso3)
            record = (row.get("indicators") or {}).get(code) or {}
            if percentile is None:
                continue
            try:
                observed_year = int(record.get("date"))
            except (TypeError, ValueError):
                observed_year = None
            by_pillar[str(spec["pillar"])].append((percentile, float(spec["weight"]), code, observed_year))
            observed_weight += float(spec["weight"]) * PILLAR_WEIGHTS[str(spec["pillar"])]

        pillar_scores: dict[str, dict[str, Any]] = {}
        overall_num = overall_den = 0.0
        all_years: list[int] = []
        drivers: list[dict[str, Any]] = []
        for pillar, weight in PILLAR_WEIGHTS.items():
            values = by_pillar.get(pillar, [])
            if not values:
                pillar_scores[pillar] = {"score": None, "coverage": 0.0, "factors": 0}
                continue
            denominator = sum(item[1] for item in values)
            score = sum(item[0] * item[1] for item in values) / denominator
            possible = sum(float(spec["weight"]) for spec in INDICATOR_MODEL.values() if spec["pillar"] == pillar)
            coverage = denominator / possible if possible else 0.0
            years = [item[3] for item in values if item[3] is not None]
            all_years.extend(years)
            pillar_scores[pillar] = {
                "score": round(score, 1),
                "coverage": round(coverage, 3),
                "factors": len(values),
                "latest_year": max(years) if years else None,
            }
            effective_weight = weight * coverage
            overall_num += score * effective_weight
            overall_den += effective_weight
            for percentile, factor_weight, code, observed_year in values:
                drivers.append({
                    "code": code,
                    "label": INDICATOR_MODEL[code]["label"],
                    "risk_percentile": round(percentile, 1),
                    "contribution": round(percentile * factor_weight * weight, 2),
                    "year": observed_year,
                })

        coverage = observed_weight / total_indicator_weight if total_indicator_weight else 0.0
        score = overall_num / overall_den if overall_den else None
        freshness_values = [math.exp(-max(0, year_now - year) / 5.0) for year in all_years]
        freshness = float(np.mean(freshness_values)) if freshness_values else 0.0
        confidence = 100.0 * (0.68 * coverage + 0.32 * freshness)
        uncertainty = 6.0 + 24.0 * (1.0 - confidence / 100.0)
        if score is None:
            regime = "Insufficient data"
        elif score >= 75:
            regime = "Severe structural stress"
        elif score >= 60:
            regime = "High structural stress"
        elif score >= 40:
            regime = "Watch"
        else:
            regime = "Lower structural stress"
        drivers.sort(key=lambda item: item["contribution"], reverse=True)
        row["quant"] = {
            "model": QUANT_MODEL_VERSION,
            "score": round(score, 1) if score is not None else None,
            "regime": regime,
            "confidence": round(confidence, 1),
            "coverage": round(coverage, 3),
            "freshness": round(freshness, 3),
            "uncertainty_low": round(max(0.0, score - uncertainty), 1) if score is not None else None,
            "uncertainty_high": round(min(100.0, score + uncertainty), 1) if score is not None else None,
            "pillars": pillar_scores,
            "drivers": drivers[:5],
            "interpretation": "Cross-sectional structural vulnerability; live event intensity is separate.",
        }
        output.append(row)
    return output


def event_decay_weight(age_hours: float, half_life_hours: float) -> float:
    """Exponential time decay used for event intensity."""

    if half_life_hours <= 0:
        raise ValueError("half_life_hours must be positive")
    return float(math.exp(-math.log(2.0) * max(0.0, float(age_hours)) / half_life_hours))


def corroboration_score(source_tiers: Iterable[float]) -> float:
    """Probability-style corroboration from independent 0..1 source reliabilities."""

    complement = 1.0
    used = False
    for value in source_tiers:
        reliability = max(0.0, min(1.0, float(value)))
        complement *= 1.0 - reliability
        used = True
    return round(100.0 * (1.0 - complement), 2) if used else 0.0


def spatial_contagion(distance_km: float, severity: float, scale_km: float = 650.0) -> float:
    """Bounded distance-decay exposure for neighboring shocks."""

    if scale_km <= 0:
        raise ValueError("scale_km must be positive")
    return round(max(0.0, min(100.0, float(severity))) * math.exp(-max(0.0, float(distance_km)) / scale_km), 3)


def propagate_shock(
    seed: Mapping[str, float],
    edges: Iterable[Mapping[str, Any]],
    steps: int = 3,
    damping: float = 0.72,
) -> dict[str, float]:
    """Propagate a scenario through a directed trade/energy/finance graph."""

    state = {str(node): max(0.0, float(value)) for node, value in seed.items()}
    frontier = dict(state)
    edge_rows = list(edges)
    for _ in range(max(0, int(steps))):
        nxt: dict[str, float] = defaultdict(float)
        for edge in edge_rows:
            source = str(edge.get("source") or "")
            target = str(edge.get("target") or "")
            weight = max(0.0, min(1.0, float(edge.get("weight") or 0.0)))
            if source in frontier and target:
                nxt[target] += frontier[source] * weight * damping
        frontier = dict(nxt)
        for node, value in frontier.items():
            state[node] = min(100.0, state.get(node, 0.0) + value)
    return {node: round(value, 3) for node, value in sorted(state.items())}

