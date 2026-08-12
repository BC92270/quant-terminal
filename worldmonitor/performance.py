"""Deterministic geometry budgets for a responsive institutional map."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .config import LIVE_POINTS_PER_LAYER, MAP_POINT_BUDGET, MAP_POINTS_PER_LAYER


def _spatially_diverse(points: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Keep the strongest observation per adaptive geographic cell.

    Selection is deterministic and preserves global coverage. If cells do not
    fill the budget, remaining high-quality observations are appended.
    """

    if len(points) <= limit:
        return points
    work = points.copy()
    work["_lat"] = pd.to_numeric(work.get("lat"), errors="coerce")
    work["_lon"] = pd.to_numeric(work.get("lon"), errors="coerce")
    work["_severity"] = pd.to_numeric(work.get("severity"), errors="coerce").fillna(0)
    work["_confidence"] = pd.to_numeric(work.get("confidence"), errors="coerce").fillna(0)
    work["_quality"] = work["_severity"] * 0.62 + work["_confidence"] * 0.38
    # The cell expands only as much as needed for this layer density.
    cell = max(0.35, min(6.0, math.sqrt(len(work) / max(1, limit)) * 1.15))
    work["_cell"] = list(zip((work["_lat"] / cell).round(), (work["_lon"] / cell).round()))
    ranked = work.sort_values(["_quality", "object_id"], ascending=[False, True])
    chosen = ranked.drop_duplicates("_cell", keep="first").head(limit)
    if len(chosen) < limit:
        remainder = ranked.loc[~ranked.index.isin(chosen.index)].head(limit - len(chosen))
        chosen = pd.concat([chosen, remainder], axis=0)
    return chosen.drop(columns=[c for c in chosen.columns if c.startswith("_")], errors="ignore")


def apply_render_budget(
    objects: pd.DataFrame,
    point_budget: int = MAP_POINT_BUDGET,
    per_layer: int = MAP_POINTS_PER_LAYER,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Return a rendering view while keeping the underlying atlas untouched."""

    if objects is None or objects.empty or "kind" not in objects.columns:
        return objects, {"input": 0, "rendered": 0, "reduced": 0}
    non_points = objects.loc[~objects["kind"].astype(str).eq("point")].copy()
    points = objects.loc[objects["kind"].astype(str).eq("point")].copy()
    selections: list[pd.DataFrame] = []
    for _layer, group in points.groupby("layer_id", sort=False):
        live = group.get("source_class", pd.Series(index=group.index, dtype=str)).astype(str).eq("live").any()
        cap = LIVE_POINTS_PER_LAYER if live else per_layer
        selections.append(_spatially_diverse(group, cap))
    selected = pd.concat(selections, ignore_index=False) if selections else points.iloc[0:0]
    if len(selected) > point_budget:
        # Guarantee representation before distributing the remaining budget by
        # quality across all layers.
        first = selected.sort_values(["layer_id", "severity", "confidence"], ascending=[True, False, False]).groupby("layer_id", sort=False).head(3)
        remaining_budget = max(0, point_budget - len(first))
        rest = selected.loc[~selected.index.isin(first.index)].copy()
        rest["_q"] = pd.to_numeric(rest.get("severity"), errors="coerce").fillna(0) * 0.62 + pd.to_numeric(rest.get("confidence"), errors="coerce").fillna(0) * 0.38
        rest = rest.sort_values(["_q", "object_id"], ascending=[False, True]).head(remaining_budget).drop(columns="_q", errors="ignore")
        selected = pd.concat([first, rest], ignore_index=False)
    rendered = pd.concat([selected, non_points], ignore_index=True, sort=False)
    stats = {
        "input": int(len(objects)),
        "input_points": int(len(points)),
        "rendered": int(len(rendered)),
        "rendered_points": int(len(selected)),
        "geometry_rows": int(len(non_points)),
        "reduced": int(len(objects) - len(rendered)),
        "point_budget": int(point_budget),
        "per_layer": int(per_layer),
    }
    return rendered, stats

