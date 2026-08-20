from __future__ import annotations

import numpy as np
import pandas as pd

from .config import EngineConfig
from .utils import max_drawdown


def _metrics(name: str, returns: pd.Series, turnover: pd.Series, annualisation: int) -> dict[str, float | str | int]:
    clean = returns.dropna()
    if clean.empty:
        return {"Series": name, "Observations": 0}
    compounded = float((1 + clean).prod())
    years = len(clean) / annualisation
    cagr = compounded ** (1 / years) - 1 if years > 0 and compounded > 0 else np.nan
    volatility = float(clean.std(ddof=0) * np.sqrt(annualisation))
    sharpe = float(clean.mean() / clean.std(ddof=0) * np.sqrt(annualisation)) if clean.std(ddof=0) > 0 else np.nan
    return {
        "Series": name,
        "Observations": len(clean),
        "CAGR": cagr,
        "Volatility": volatility,
        "Sharpe": sharpe,
        "Max drawdown": max_drawdown(clean),
        "Hit rate": float((clean > 0).mean()),
        "Avg turnover": float(turnover.reindex(clean.index).fillna(0).mean()),
    }


def build_walk_forward_diagnostic(frame: pd.DataFrame, config: EngineConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Causal diagnostic, deliberately labelled as non-production backtest."""

    direction = np.tanh(frame["momentum_composite"].fillna(0))
    regime_quality = (1 - frame["noise_score"].fillna(0.7)).clip(0, 1)
    raw_position = (direction * regime_quality).where(direction.abs() >= 0.22, 0.0)
    vol_scale = (0.15 / frame["vol_20"].replace(0, np.nan)).clip(upper=1.0).fillna(0.0)
    position = (raw_position * vol_scale).clip(-1, 1).shift(1).fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    cost = turnover * config.transaction_cost_bps / 10_000
    strategy_return = position * frame["simple_return"].fillna(0) - cost
    buy_hold = frame["simple_return"].fillna(0)

    valid_start = max(config.min_history, 120)
    strategy_return = strategy_return.iloc[valid_start:]
    buy_hold = buy_hold.iloc[valid_start:]
    turnover = turnover.iloc[valid_start:]
    curve = pd.DataFrame(
        {
            "date": frame["date"].iloc[valid_start:],
            "strategy": (1 + strategy_return).cumprod().to_numpy(),
            "buy_hold": (1 + buy_hold).cumprod().to_numpy(),
            "position": position.iloc[valid_start:].to_numpy(),
            "drawdown": ((1 + strategy_return).cumprod() / (1 + strategy_return).cumprod().cummax() - 1).to_numpy(),
        }
    )
    table = pd.DataFrame(
        [
            _metrics("Causal regime/momentum diagnostic", strategy_return, turnover, config.annualisation),
            _metrics("Buy & hold", buy_hold, pd.Series(0.0, index=buy_hold.index), config.annualisation),
        ]
    )
    return table, curve

