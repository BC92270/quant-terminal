"""Time-safe cosine novelty baseline."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..contracts import as_utc


def _unit(vector: Sequence[float]) -> np.ndarray:
    values = np.asarray(vector, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("Embedding must be a finite one-dimensional vector")
    norm = float(np.linalg.norm(values))
    if norm <= 0.0:
        raise ValueError("Embedding norm must be positive")
    return values / norm


def novelty_score(
    current_embedding: Sequence[float],
    prior_items: Iterable[Mapping[str, Any]],
    *,
    as_of: Any,
    entity: str | None = None,
    topic: str | None = None,
) -> float:
    """Return 1 - maximum cosine similarity against prior eligible items."""

    current = _unit(current_embedding)
    cutoff = as_utc(as_of)
    similarities: list[float] = []
    for item in prior_items:
        if as_utc(item["known_at"]) > cutoff:
            continue
        if entity is not None and item.get("entity") != entity:
            continue
        if topic is not None and item.get("topic") != topic:
            continue
        prior = _unit(item["embedding"])
        if prior.shape != current.shape:
            raise ValueError("Embedding dimensions must match")
        similarities.append(float(np.clip(np.dot(current, prior), -1.0, 1.0)))
    if not similarities:
        return 1.0
    return float(np.clip(1.0 - max(similarities), 0.0, 1.0))
