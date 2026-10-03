from __future__ import annotations

import re
from typing import Any, Iterable

from .ontology import FINANCE_INTENT_TERMS, SCIENTIFIC_SIGNAL_TERMS


STOP_WORDS = {
    "a", "an", "the", "of", "to", "and", "or", "for", "in", "on", "with", "from", "by",
    "using", "use", "study", "analysis", "applications", "application", "approach", "model",
}


def _tokens(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) >= 2 and token not in STOP_WORDS
    }


def _field(paper: Any, name: str, default: Any = "") -> Any:
    if isinstance(paper, dict):
        return paper.get(name, default)
    return getattr(paper, name, default)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    lower = str(text or "").lower()
    return any(term in lower for term in terms)


def rank_literature_results(
    query: str,
    papers: Iterable[Any],
    quests: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rank retrieval results without deleting cross-domain candidates.

    The score answers "how directly does this paper address the current query?".
    Cross-domain papers are retained in a separate track when they contain strong
    scientific structure but weak domain overlap.
    """
    query = str(query or "").strip()
    q_tokens = _tokens(query)
    finance_intent = _contains_any(query, FINANCE_INTENT_TERMS)
    active_quests = [q for q in (quests or []) if str(q.get("status") or "OPEN") == "OPEN"]
    quest_tokens = [_tokens(f"{q.get('title','')} {q.get('question','')}") for q in active_quests]

    ranked: list[dict[str, Any]] = []
    for paper in papers:
        title = str(_field(paper, "title", "") or "")
        abstract = str(_field(paper, "abstract", "") or "")
        subjects = " ".join(str(x) for x in (_field(paper, "subjects", []) or []))
        combined = f"{title} {abstract} {subjects}".strip()
        title_tokens = _tokens(title)
        abstract_tokens = _tokens(f"{abstract} {subjects}")
        combined_tokens = title_tokens | abstract_tokens

        denom = max(1, len(q_tokens))
        title_overlap = len(q_tokens & title_tokens) / denom
        text_overlap = len(q_tokens & abstract_tokens) / denom
        exact_phrase = 1.0 if query and query.lower() in combined.lower() else 0.0

        quest_overlap = 0.0
        for qt in quest_tokens:
            if qt:
                quest_overlap = max(quest_overlap, len(qt & combined_tokens) / max(1, len(qt)))

        direct = 42 * title_overlap + 28 * text_overlap + 12 * exact_phrase + 10 * quest_overlap
        direct += 5 if _field(paper, "doi", None) else 0
        direct += 3 if abstract else 0

        finance_present = _contains_any(combined, FINANCE_INTENT_TERMS)
        if finance_intent and not finance_present:
            direct -= 18
        elif finance_intent and finance_present:
            direct += 8

        scientific_hits = sum(1 for term in SCIENTIFIC_SIGNAL_TERMS if term in combined.lower())
        scientific_signal = min(100.0, 12.0 * scientific_hits + (12.0 if abstract else 0.0))
        direct = max(0.0, min(100.0, direct))

        if finance_intent and not finance_present and scientific_signal >= 42:
            track = "CROSS_DOMAIN"
        elif direct >= 60:
            track = "DIRECT"
        elif direct >= 34:
            track = "ADJACENT"
        elif scientific_signal >= 42:
            track = "CROSS_DOMAIN"
        else:
            track = "LOW_SIGNAL"

        reasons: list[str] = []
        if title_overlap >= 0.5:
            reasons.append("strong title overlap")
        if text_overlap >= 0.35:
            reasons.append("abstract/subject overlap")
        if finance_intent and finance_present:
            reasons.append("financial-domain match")
        if finance_intent and not finance_present and scientific_signal >= 42:
            reasons.append("scientific structure outside finance")
        if quest_overlap >= 0.25:
            reasons.append("active-quest overlap")
        if not reasons:
            reasons.append("weak direct match")

        ranked.append({
            "paper": paper,
            "relevance_score": round(direct, 1),
            "scientific_signal": round(scientific_signal, 1),
            "track": track,
            "reason": "; ".join(reasons),
        })

    track_order = {"DIRECT": 0, "ADJACENT": 1, "CROSS_DOMAIN": 2, "LOW_SIGNAL": 3}
    ranked.sort(key=lambda row: (track_order.get(row["track"], 9), -row["relevance_score"], -row["scientific_signal"]))
    return ranked
