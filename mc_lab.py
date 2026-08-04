"""Compatibility façade for Monte Carlo Risk & Scenario Engine V2.1.2 modular parity.

Keep this file at the repository root. Existing application code can continue to use:
    from mc_lab import render_monte_carlo_advanced_lab
"""

from monte_carlo import (
    DEFAULT_HORIZONS,
    ENGINE_VERSION,
    MODELS,
    PACKAGE_VERSION,
    SCENARIOS,
    build_monte_carlo_lab,
    render_monte_carlo_advanced_lab,
)
from monte_carlo.models.dispatcher import _simulate_paths_max_horizon

__all__ = [
    "build_monte_carlo_lab",
    "render_monte_carlo_advanced_lab",
    "ENGINE_VERSION",
    "PACKAGE_VERSION",
    "DEFAULT_HORIZONS",
    "SCENARIOS",
    "MODELS",
    "_simulate_paths_max_horizon",
]
