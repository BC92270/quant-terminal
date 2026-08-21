from __future__ import annotations

from typing import Any

import pandas as pd

from quant_ai.ui import render_quant_ai_terminal as _render


def render_quant_ai_terminal(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict[str, Any],
) -> None:
    """Stable application entrypoint for the autonomous CIO workspace."""
    _render(ticker=ticker, price_data=price_data, analysis=analysis)


__all__ = ["render_quant_ai_terminal"]
