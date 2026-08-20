"""Market Psychology package.

The UI import is deliberately lazy so the research engine can be tested independently
from Streamlit.
"""


def render_market_psychology_lab(*args, **kwargs):
    from .ui import render_market_psychology_lab as _render
    return _render(*args, **kwargs)


__all__ = ["render_market_psychology_lab"]
