from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .contracts import RegimeSnapshot
from .utils import softmax


REGIMES = ("BULL_TREND", "BEAR_TREND", "RANGE", "STRESS")
REGIME_LABELS = {
    "BULL_TREND": "Bull trend",
    "BEAR_TREND": "Bear trend",
    "RANGE": "Range / mean-reverting",
    "STRESS": "Stress / high volatility",
}


def infer_regimes(frame: pd.DataFrame, stickiness: float = 0.92) -> tuple[pd.DataFrame, RegimeSnapshot]:
    """Causal sticky-state filter.

    Observation probabilities are built only from rolling features available at
    each date. A Markov transition prior stabilises the state path without
    fitting future observations or relabelling the history ex post.
    """

    transition = np.full((4, 4), (1.0 - stickiness) / 3.0)
    np.fill_diagonal(transition, stickiness)
    previous = np.full(4, 0.25)
    records: list[dict[str, float | str | pd.Timestamp]] = []

    for _, row in frame.iterrows():
        momentum = float(np.nan_to_num(row.get("momentum_composite"), nan=0.0))
        trend = float(np.nan_to_num(row.get("trend_quality"), nan=0.0))
        noise = float(np.nan_to_num(row.get("noise_score"), nan=0.6))
        vol_z = float(np.nan_to_num(row.get("vol_z_60"), nan=0.0))
        drawdown = float(np.nan_to_num(row.get("drawdown"), nan=0.0))
        shock = abs(float(np.nan_to_num(row.get("return_z_20"), nan=0.0)))
        adx = float(np.nan_to_num(row.get("adx_14"), nan=20.0)) / 50.0

        directional = 0.95 * momentum + 1.25 * trend
        logits = np.array(
            [
                directional + 0.45 * adx - 0.35 * max(vol_z, 0),
                -directional + 0.45 * adx + 0.20 * max(vol_z, 0),
                1.25 * (1 - min(abs(trend), 1)) + 0.65 * noise - 0.35 * max(vol_z, 0),
                0.95 * max(vol_z, 0) + 5.5 * max(-drawdown - 0.08, 0) + 0.35 * max(shock - 1, 0),
            ]
        )
        emission = softmax(logits)
        prior = transition.T @ previous
        filtered = emission * prior
        filtered = filtered / filtered.sum() if filtered.sum() else np.full(4, 0.25)
        previous = filtered
        state = REGIMES[int(np.argmax(filtered))]
        record: dict[str, float | str | pd.Timestamp] = {"date": row["date"], "state": state}
        record.update({regime: float(filtered[index]) for index, regime in enumerate(REGIMES)})
        records.append(record)

    history = pd.DataFrame(records)
    if history.empty:
        probabilities = {regime: 0.25 for regime in REGIMES}
        return history, RegimeSnapshot("Unknown", 0.25, 1.0, 0, 1.0, probabilities)

    latest = history.iloc[-1]
    probabilities = {regime: float(latest[regime]) for regime in REGIMES}
    confidence = max(probabilities.values())
    entropy = -sum(value * math.log(max(value, 1e-12)) for value in probabilities.values()) / math.log(len(REGIMES))
    current_state = str(latest["state"])
    persistence = 0
    for value in reversed(history["state"].tolist()):
        if value != current_state:
            break
        persistence += 1
    if len(history) >= 2:
        previous_probabilities = history.iloc[-2][list(REGIMES)].to_numpy(dtype=float)
        probability_change = 0.5 * np.abs(previous_probabilities - np.array(list(probabilities.values()))).sum()
    else:
        probability_change = 0.0
    transition_risk = float(np.clip(0.65 * (1 - confidence) + 0.35 * probability_change, 0, 1))
    snapshot = RegimeSnapshot(
        label=REGIME_LABELS[current_state],
        confidence=float(confidence),
        entropy=float(entropy),
        persistence_bars=persistence,
        transition_risk=transition_risk,
        probabilities=probabilities,
    )
    return history, snapshot

