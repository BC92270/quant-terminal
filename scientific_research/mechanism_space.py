from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Iterable

from .ontology import extract_mechanism_scores, mechanism_family
from .phase3_models import StructuralComparison


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def family_profile(mechanisms: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for mechanism, score in (mechanisms or {}).items():
        family = mechanism_family(mechanism)
        out[family] = out.get(family, 0.0) + float(score or 0.0)
    if not out:
        return {}
    maximum = max(out.values()) or 1.0
    return {k: round(v / maximum, 4) for k, v in sorted(out.items())}


def weighted_jaccard(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    numerator = sum(min(float(left.get(k, 0.0)), float(right.get(k, 0.0))) for k in keys)
    denominator = sum(max(float(left.get(k, 0.0)), float(right.get(k, 0.0))) for k in keys)
    return numerator / denominator if denominator else 0.0


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    keys = set(left) | set(right)
    if not keys:
        return 0.0
    dot = sum(float(left.get(k, 0.0)) * float(right.get(k, 0.0)) for k in keys)
    nl = math.sqrt(sum(float(left.get(k, 0.0)) ** 2 for k in keys))
    nr = math.sqrt(sum(float(right.get(k, 0.0)) ** 2 for k in keys))
    return dot / (nl * nr) if nl and nr else 0.0


def compare_mechanism_space(
    source_text: str,
    target_text: str,
    source_label: str = "Source",
    target_label: str = "Target",
    source_domain: str = "Unknown",
    target_domain: str = "Unknown",
) -> StructuralComparison:
    source = extract_mechanism_scores(source_text)
    target = extract_mechanism_scores(target_text)
    sf = family_profile(source)
    tf = family_profile(target)

    common = tuple(sorted(set(source) & set(target)))
    common_families = tuple(sorted(set(sf) & set(tf)))
    mech_sim = weighted_jaccard(source, target)
    family_sim = cosine_similarity(sf, tf)

    # Exact mechanisms carry most weight. Family overlap permits structurally adjacent
    # mechanisms to survive screening without pretending they are equivalent.
    common_coverage = len(common) / max(1, min(len(source), len(target))) if source and target else 0.0
    score = 100.0 * (0.62 * mech_sim + 0.28 * family_sim + 0.10 * common_coverage)
    score = max(0.0, min(100.0, score))

    if not source or not target:
        verdict = "INSUFFICIENT_MECHANISM_EVIDENCE"
    elif score >= 75:
        verdict = "STRONG_STRUCTURAL_CANDIDATE"
    elif score >= 52:
        verdict = "PARTIAL_STRUCTURAL_CANDIDATE"
    elif score >= 30:
        verdict = "WEAK_TRANSFER_SIGNAL"
    else:
        verdict = "NO_STRUCTURAL_EVIDENCE"

    return StructuralComparison(
        comparison_id=_stable_id("STRUCT", source_text, target_text, source_domain, target_domain),
        created_at=_now_iso(),
        source_label=source_label,
        target_label=target_label,
        source_domain=source_domain,
        target_domain=target_domain,
        source_mechanisms=source,
        target_mechanisms=target,
        source_families=sf,
        target_families=tf,
        common_mechanisms=common,
        common_families=common_families,
        source_only=tuple(sorted(set(source) - set(target))),
        target_only=tuple(sorted(set(target) - set(source))),
        mechanism_similarity=round(mech_sim, 4),
        family_similarity=round(family_sim, 4),
        structural_score=round(score, 1),
        verdict=verdict,
        warning=(
            "Structural similarity is a screening statistic only. It does not establish "
            "equation equivalence, dimensional consistency, causal transfer or empirical validity."
        ),
    )
