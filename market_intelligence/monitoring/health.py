"""Deterministic integrity audit used by tests and the validation panel."""

from __future__ import annotations

from typing import Any

import pandas as pd

from ..contracts import WorkspaceSnapshot


def run_fixture_integrity_audit(snapshot: WorkspaceSnapshot) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(gate: str, passed: bool, evidence: str, *, blocking: bool = True) -> None:
        rows.append(
            {
                "Gate": gate,
                "Result": "PASS" if passed else "FAIL",
                "Blocking": blocking,
                "Evidence": evidence,
            }
        )

    timestamp_safe = all(
        event.first_seen_time <= event.ingested_at <= event.tradable_at <= event.feature_computed_at
        and event.publication_time <= event.tradable_at
        for event in snapshot.events
    )
    add("Point-in-time event chain", timestamp_safe, f"{len(snapshot.events)} fixture events checked")
    forecasts = list(snapshot.forecasts)
    cutoff_safe = all(item.data_cutoff <= item.as_of for item in forecasts)
    add("Forecast data cutoff", cutoff_safe, f"{len(forecasts)} forecast records checked")
    quantile_safe = all(
        item.q05 is None or item.q05 <= item.q25 <= item.q50 <= item.q75 <= item.q95
        for item in forecasts
    )
    add("Monotone quantiles", quantile_safe, "Q05 ≤ Q25 ≤ Q50 ≤ Q75 ≤ Q95")
    add(
        "Explicit simulation status",
        snapshot.catalyst_status == "SIMULATED" and "SIMULATED" in snapshot.microstructure_level,
        f"catalyst={snapshot.catalyst_status}; micro={snapshot.microstructure_level}",
    )
    add(
        "Canonical high collision",
        snapshot.interaction.collision_score >= 0.70,
        f"collision={snapshot.interaction.collision_score:.3f}",
    )
    add(
        "Canonical absorption state",
        snapshot.interaction.state == "negative_catalyst_absorption",
        snapshot.interaction.state,
    )
    short = next((item for item in forecasts if item.horizon == "10m"), None)
    medium = next((item for item in forecasts if item.horizon == "30m"), None)
    horizon_safe = bool(
        short is not None
        and medium is not None
        and short.p_up is not None
        and medium.p_up is not None
        and short.p_up <= medium.p_up
    )
    add(
        "Short horizon no stronger than medium",
        horizon_safe,
        f"10m={getattr(short, 'p_up', None)}; 30m={getattr(medium, 'p_up', None)}",
        blocking=False,
    )
    gap = snapshot.audit["information_gap"]
    add(
        "Known catalysts explain fixture move",
        float(gap["unexplained_residual"]) < 0.70,
        f"residual={gap['unexplained_residual']:.3f}",
    )
    add(
        "Production promotion remains closed",
        all("RESEARCH_ONLY" in item.uncertainty_flags for item in forecasts),
        "All fixture forecasts remain research-only and uncalibrated",
    )
    return pd.DataFrame(rows)
