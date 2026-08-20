import sys
from pathlib import Path

import numpy as np
import pandas as pd


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from derivatives_strategy_lab import render_strategy_lab


def chain(kind: str) -> pd.DataFrame:
    strikes = np.arange(70.0, 131.0, 5.0)
    distance = np.abs(strikes / 100.0 - 1.0)
    intrinsic = np.maximum(100.0 - strikes, 0.0) if kind == "put" else np.maximum(strikes - 100.0, 0.0)
    mid = 2.0 + intrinsic * 0.25 + distance * 8.0
    return pd.DataFrame({
        "strike": strikes,
        "bid": np.maximum(mid - 0.10, 0.01),
        "ask": mid + 0.10,
        "mid": mid,
        "iv": 0.28 + distance * 0.20,
        "dte": 30,
    })


render_strategy_lab(
    ticker="TEST",
    calls=chain("call"),
    puts=chain("put"),
    spot=100.0,
    expiration="2026-09-06",
    metrics={
        "dte": 30,
        "atm_iv": 0.28,
        "rv20": 0.22,
        "iv_premium_20": 0.27,
        "expected_move_price": 8.03,
    },
    macro_summary={"tape_state": "Mixte", "tape_score": 55.0},
)
