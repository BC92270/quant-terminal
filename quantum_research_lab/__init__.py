"""Quantum Research Lab package.

The public renderer stays import-compatible while loading Streamlit lazily.
This keeps proof/validation CLIs free from UI side effects and scientific
runtime imports.
"""

from typing import Any


def render_quantum_research_lab(*args: Any, **kwargs: Any) -> Any:
    from .ui import render_quantum_research_lab as _render

    return _render(*args, **kwargs)

__all__ = ["render_quantum_research_lab"]
