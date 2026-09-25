"""Compact abnormal-return event-study baseline."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def event_study(
    asset_returns: Any,
    benchmark_returns: Any,
    *,
    event_position: int,
    estimation_window: tuple[int, int] = (-60, -10),
    event_window: tuple[int, int] = (-2, 5),
) -> pd.DataFrame:
    """Estimate a market model pre-event and return AR/CAR around the event."""

    asset = pd.Series(asset_returns, dtype=float).reset_index(drop=True)
    benchmark = pd.Series(benchmark_returns, dtype=float).reset_index(drop=True)
    if len(asset) != len(benchmark):
        raise ValueError("Asset and benchmark return histories must align")
    est_start = event_position + estimation_window[0]
    est_end = event_position + estimation_window[1]
    win_start = event_position + event_window[0]
    win_end = event_position + event_window[1]
    if est_start < 0 or win_start < 0 or est_end >= len(asset) or win_end >= len(asset):
        raise ValueError("Requested event-study windows are outside the available history")
    x = benchmark.iloc[est_start : est_end + 1].to_numpy(dtype=float)
    y = asset.iloc[est_start : est_end + 1].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    event_asset = asset.iloc[win_start : win_end + 1].to_numpy(dtype=float)
    event_benchmark = benchmark.iloc[win_start : win_end + 1].to_numpy(dtype=float)
    abnormal = event_asset - (alpha + beta * event_benchmark)
    offsets = np.arange(event_window[0], event_window[1] + 1)
    return pd.DataFrame(
        {
            "event_offset": offsets,
            "asset_return": event_asset,
            "benchmark_return": event_benchmark,
            "abnormal_return": abnormal,
            "cumulative_abnormal_return": np.cumsum(abnormal),
            "alpha": alpha,
            "beta": beta,
        }
    )
