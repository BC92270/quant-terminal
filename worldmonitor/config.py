"""Stable runtime configuration for WorldMonitor."""

from __future__ import annotations

import os


MODULE_VERSION = "WorldMonitor · JARVIS V8"
ASSET_SCHEMA_VERSION = 1
QUANT_MODEL_VERSION = "WM-IQ 1.0"


def env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


# Scattergeo is SVG based. A global budget keeps pan/zoom responsive while the
# full, unabridged asset remains available for registry counts and country work.
MAP_POINT_BUDGET = env_int("WORLDMONITOR_MAP_POINT_BUDGET", 1180, 350, 4000)
MAP_POINTS_PER_LAYER = env_int("WORLDMONITOR_MAP_POINTS_PER_LAYER", 170, 25, 800)
LIVE_POINTS_PER_LAYER = env_int("WORLDMONITOR_LIVE_POINTS_PER_LAYER", 220, 30, 1000)

