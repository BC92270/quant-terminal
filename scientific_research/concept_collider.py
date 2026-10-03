from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from .mechanism_space import compare_mechanism_space
from .scientific_understanding import extract_semantic_entities
from .phase3_models import CollisionCandidate, GraphDiscoveryCandidate


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "into", "using", "market", "markets"}
    return {t for t in re.findall(r"[a-z][a-z0-9_-]{2,}", str(text or "").lower()) if t not in stop}


def _lexical_overlap(a: str, b: str) -> float:
    left, right = _tokens(a), _tokens(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _semantic_labels(text: str, label: str) -> tuple[str, ...]:
    records, _ = extract_semantic_entities(
        paper_id=_stable_id("TMP", label, text),
        title=label,
        text=text,
        source_kind="manual_context",
    )
    return tuple(sorted({f"{r.entity_type}:{r.canonical_label}" for r in records}))


def _paper_profiles(graph: Any) -> dict[str, dict[str, Any]]:
    nodes = {str(n.get("node_id")): n for n in graph.nodes()}
    profiles: dict[str, dict[str, Any]] = {}
    for paper in graph.nodes("Paper"):
        pid = str(paper.get("node_id"))
        profiles[pid] = {
            "paper_id": pid,
            "title": str(paper.get("label") or ""),
            "domain": "Unknown",
            "mechanisms": {},
            "families": set(),
            "entities": set(),
            "provenance": set(),
        }
    for edge in graph.edges():
        source = str(edge.get("source"))
        if source not in profiles:
            continue
        target = nodes.get(str(edge.get("target"))) or {}
        relation = str(edge.get("relation") or "")
        meta = edge.get("metadata") or {}
        if relation == "CLASSIFIED_AS":
            profiles[source]["domain"] = str(target.get("label") or "Unknown")
        elif relation == "USES_MECHANISM":
            mechanism = str(target.get("label") or "")
            if mechanism:
                profiles[source]["mechanisms"][mechanism] = float(meta.get("score") or 0.5)
                family = str((target.get("metadata") or {}).get("family") or "")
                if family:
                    profiles[source]["families"].add(family)
        elif relation in {"USES_THEORY", "USES_METHOD", "STUDIES_OBJECT", "HAS_CONCEPT", "APPLIES_TO"}:
            if target.get("label"):
                profiles[source]["entities"].add(f"{target.get('node_type')}:{target.get('label')}")
        prov = meta.get("provenance_id")
        if prov:
            profiles[source]["provenance"].add(str(prov))
        for p in meta.get("provenance_ids") or []:
            profiles[source]["provenance"].add(str(p))
    return profiles


def _bridge_papers(graph: Any, source_mechanisms: set[str], target_mechanisms: set[str], source_entities: set[str], target_entities: set[str]) -> tuple[str, ...]:
    profiles = _paper_profiles(graph)
    scored: list[tuple[int, str]] = []
    for pid, profile in profiles.items():
        mechs = set(profile["mechanisms"])
        entities = set(profile["entities"])
        source_hit = len(mechs & source_mechanisms) + len(entities & source_entities)
        target_hit = len(mechs & target_mechanisms) + len(entities & target_entities)
        if source_hit and target_hit:
            scored.append((source_hit + target_hit, pid))
    scored.sort(reverse=True)
    return tuple(pid for _, pid in scored[:12])


def collide_concepts(
    source_context: str,
    target_context: str,
    graph: Any | None = None,
    source_label: str = "Source scientific concept",
    target_label: str = "Target problem",
    source_domain: str = "Unknown",
    target_domain: str = "Finance",
) -> CollisionCandidate:
    comparison = compare_mechanism_space(
        source_context, target_context,
        source_label=source_label, target_label=target_label,
        source_domain=source_domain, target_domain=target_domain,
    )
    source_entities = set(_semantic_labels(source_context, source_label))
    target_entities = set(_semantic_labels(target_context, target_label))
    shared_entities = tuple(sorted(source_entities & target_entities))

    bridge_papers: tuple[str, ...] = ()
    if graph is not None:
        bridge_papers = _bridge_papers(
            graph,
            set(comparison.source_mechanisms),
            set(comparison.target_mechanisms),
            source_entities,
            target_entities,
        )

    lexical = _lexical_overlap(source_context, target_context)
    novelty = max(0.0, min(100.0, 100.0 * (1.0 - lexical)))
    evidence = min(100.0, 20.0 + 12.0 * len(bridge_papers) + 5.0 * len(shared_entities))
    structural = comparison.structural_score
    research_value = max(0.0, min(100.0, 0.52 * structural + 0.23 * novelty + 0.25 * evidence))

    rationale = []
    if comparison.common_mechanisms:
        rationale.append("shared controlled mechanisms: " + ", ".join(comparison.common_mechanisms))
    if comparison.common_families:
        rationale.append("shared mechanism families: " + ", ".join(comparison.common_families))
    if shared_entities:
        rationale.append("shared source-grounded ontology entities: " + ", ".join(shared_entities[:8]))
    if bridge_papers:
        rationale.append(f"{len(bridge_papers)} stored paper(s) connect source and target structures")
    if novelty >= 70 and structural >= 35:
        rationale.append("high semantic distance with non-zero structural overlap: candidate for controlled cross-domain investigation")

    if structural >= 55 and research_value >= 55:
        verdict = "RESEARCH_CANDIDATE"
    elif structural >= 30:
        verdict = "SCREEN_ONLY"
    else:
        verdict = "NO_TRANSFER_SIGNAL"

    warnings = (
        "Collision output is hypothesis generation, not scientific evidence.",
        "No equation, unit, invariant or causal transfer is accepted by the Concept Collider.",
    )
    return CollisionCandidate(
        collision_id=_stable_id("COLLISION", source_context, target_context, source_domain, target_domain),
        created_at=_now_iso(),
        source_label=source_label,
        target_label=target_label,
        source_domain=source_domain,
        target_domain=target_domain,
        structural_score=round(structural, 1),
        novelty_score=round(novelty, 1),
        evidence_score=round(evidence, 1),
        research_value=round(research_value, 1),
        verdict=verdict,
        bridge_mechanisms=comparison.common_mechanisms,
        bridge_families=comparison.common_families,
        shared_entities=shared_entities,
        source_entities=tuple(sorted(source_entities)),
        target_entities=tuple(sorted(target_entities)),
        bridge_paper_ids=bridge_papers,
        rationale=tuple(rationale),
        warnings=warnings,
        source_context=source_context,
        target_context=target_context,
    )


def discover_graph_bridges(graph: Any, min_score: float = 28.0) -> list[GraphDiscoveryCandidate]:
    profiles = _paper_profiles(graph)
    ids = sorted(profiles)
    out: list[GraphDiscoveryCandidate] = []
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1:]:
            left, right = profiles[left_id], profiles[right_id]
            if left["domain"] == right["domain"]:
                continue
            lm, rm = set(left["mechanisms"]), set(right["mechanisms"])
            lf, rf = set(left["families"]), set(right["families"])
            le, re_ = set(left["entities"]), set(right["entities"])
            shared_m = tuple(sorted(lm & rm))
            shared_f = tuple(sorted(lf & rf))
            shared_e = tuple(sorted(le & re_))
            if not shared_m and not shared_f and not shared_e:
                continue
            mech_score = 100.0 * len(shared_m) / max(1, min(len(lm), len(rm))) if lm and rm else 0.0
            fam_score = 100.0 * len(shared_f) / max(1, min(len(lf), len(rf))) if lf and rf else 0.0
            entity_score = min(100.0, 20.0 * len(shared_e))
            structural = 0.58 * mech_score + 0.27 * fam_score + 0.15 * entity_score
            if structural < min_score:
                continue
            evidence = min(100.0, 45.0 + 5.0 * len(shared_m) + 3.0 * len(shared_e))
            lexical = _lexical_overlap(left["title"], right["title"])
            novelty = 100.0 * (1.0 - lexical)
            research = 0.55 * structural + 0.25 * evidence + 0.20 * novelty
            prov = tuple(sorted(set(left["provenance"]) | set(right["provenance"])))
            out.append(GraphDiscoveryCandidate(
                discovery_id=_stable_id("DISCOVERY", left_id, right_id),
                created_at=_now_iso(),
                source_paper_id=left_id,
                target_paper_id=right_id,
                source_title=left["title"],
                target_title=right["title"],
                source_domain=left["domain"],
                target_domain=right["domain"],
                shared_mechanisms=shared_m,
                shared_families=shared_f,
                shared_entities=shared_e,
                structural_score=round(structural, 1),
                evidence_score=round(evidence, 1),
                novelty_score=round(novelty, 1),
                research_value=round(min(100.0, research), 1),
                status="SCREEN_ONLY",
                provenance_refs=prov,
            ))
    out.sort(key=lambda x: (-x.research_value, -x.structural_score, x.discovery_id))
    return out
