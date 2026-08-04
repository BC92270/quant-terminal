"""Monte Carlo Risk & Scenario Engine — modular parity package V2.1.2."""
from .engine import build_monte_carlo_lab
from .config import ENGINE_VERSION, PACKAGE_VERSION, DEFAULT_HORIZONS, SCENARIOS, MODELS


def render_monte_carlo_advanced_lab(*args, **kwargs):
    """Lazy UI entry point; Streamlit is imported only when rendering."""
    from .ui.app import render_monte_carlo_advanced_lab as _render
    return _render(*args, **kwargs)


__all__ = [
    "build_monte_carlo_lab", "render_monte_carlo_advanced_lab",
    "ENGINE_VERSION", "PACKAGE_VERSION", "DEFAULT_HORIZONS", "SCENARIOS", "MODELS",
]
