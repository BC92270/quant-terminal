from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .concept_collider import _paper_profiles
from .phase3_models import GapRecord


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def detect_domain_gaps(graph: Any, target_domain: str = "Finance") -> list[GapRecord]:
    profiles = _paper_profiles(graph)
    by_mechanism: dict[str, dict[str, set[str]]] = {}
    by_entity: dict[str, dict[str, set[str]]] = {}
    for pid, p in profiles.items():
        domain = str(p.get("domain") or "Unknown")
        for mechanism in p.get("mechanisms") or {}:
            by_mechanism.setdefault(mechanism, {}).setdefault(domain, set()).add(pid)
        for entity in p.get("entities") or set():
            by_entity.setdefault(entity, {}).setdefault(domain, set()).add(pid)

    gaps: list[GapRecord] = []
    for label, domain_map in by_mechanism.items():
        target_support = len(domain_map.get(target_domain, set()))
        outside = {d: ids for d, ids in domain_map.items() if d != target_domain and ids}
        if outside and target_support == 0:
            ids = sorted(set().union(*outside.values()))
            support = len(ids)
            priority = min(100.0, 45.0 + 12.0 * support + 4.0 * len(outside))
            gaps.append(GapRecord(
                gap_id=_stable_id("GAP", "Mechanism", label, target_domain),
                created_at=_now_iso(),
                target_domain=target_domain,
                gap_kind="MECHANISM",
                label=label,
                source_domains=tuple(sorted(outside)),
                source_support_count=support,
                target_support_count=0,
                source_paper_ids=tuple(ids),
                rationale=f"Mechanism is source-grounded in {len(outside)} non-{target_domain} domain(s) but absent from stored {target_domain} papers.",
                priority_score=round(priority, 1),
            ))

    for label, domain_map in by_entity.items():
        target_support = len(domain_map.get(target_domain, set()))
        outside = {d: ids for d, ids in domain_map.items() if d != target_domain and ids}
        if outside and target_support == 0:
            ids = sorted(set().union(*outside.values()))
            support = len(ids)
            priority = min(100.0, 38.0 + 10.0 * support + 3.0 * len(outside))
            gaps.append(GapRecord(
                gap_id=_stable_id("GAP", "Entity", label, target_domain),
                created_at=_now_iso(),
                target_domain=target_domain,
                gap_kind="ONTOLOGY_ENTITY",
                label=label,
                source_domains=tuple(sorted(outside)),
                source_support_count=support,
                target_support_count=0,
                source_paper_ids=tuple(ids),
                rationale=f"Scientific entity exists in stored non-{target_domain} literature but has no source-grounded representation in stored {target_domain} literature.",
                priority_score=round(priority, 1),
            ))

    gaps.sort(key=lambda x: (-x.priority_score, x.gap_kind, x.label))
    return gaps
