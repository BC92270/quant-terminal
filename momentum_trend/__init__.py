"""Institutional Momentum / Trend research terminal.

The public API is intentionally small so the module can be dropped into the
existing terminal without importing Streamlit from the quantitative engine.
"""

from .config import EngineConfig, Profile
from .engine import MomentumTrendEngine, run_momentum_trend
from .ui import render_momentum_trend_terminal

__all__ = [
    "EngineConfig",
    "MomentumTrendEngine",
    "Profile",
    "render_momentum_trend_terminal",
    "run_momentum_trend",
]

