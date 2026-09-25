"""Point-in-time-safe numeric surprise calculations."""

from __future__ import annotations

import math
from typing import Any

from ..data.point_in_time import assert_cutoff


def standardized_surprise(
    actual: float,
    consensus: float,
    historical_error_std: float,
    *,
    consensus_available_at: Any,
    event_tradable_at: Any,
) -> tuple[float, float]:
    """Return raw and standardized actual-minus-consensus surprise."""

    assert_cutoff(consensus_available_at, event_tradable_at, label="consensus")
    actual_value = float(actual)
    consensus_value = float(consensus)
    scale = float(historical_error_std)
    if not all(math.isfinite(value) for value in (actual_value, consensus_value, scale)):
        raise ValueError("Surprise inputs must be finite")
    if scale <= 0.0:
        raise ValueError("historical_error_std must be positive")
    raw = actual_value - consensus_value
    return raw, raw / scale
