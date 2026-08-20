"""Ex-post decision diagnostics and point-in-time leakage controls."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


JOURNAL_COLUMNS = (
    "decision_date",
    "review_date",
    "issuer",
    "instrument",
    "decision",
    "conviction_pct",
    "entry_spread_bp",
    "exit_spread_bp",
    "status",
    "thesis",
    "invalidation_trigger",
)

PIT_COLUMNS = (
    "series",
    "observation_date",
    "available_date",
    "decision_date",
    "value",
)


def diagnose_decisions(journal: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Measure direction-adjusted spread alpha and forecast calibration."""
    work = pd.DataFrame(journal).copy()
    for column in JOURNAL_COLUMNS:
        if column not in work.columns:
            work[column] = np.nan
    work["decision_date"] = pd.to_datetime(work["decision_date"], errors="coerce", utc=True)
    work["review_date"] = pd.to_datetime(work["review_date"], errors="coerce", utc=True)
    for column in ("conviction_pct", "entry_spread_bp", "exit_spread_bp"):
        work[column] = pd.to_numeric(work[column], errors="coerce")

    substantive = (
        work["issuer"].fillna("").astype(str).str.strip().ne("")
        | work["instrument"].fillna("").astype(str).str.strip().ne("")
        | work["thesis"].fillna("").astype(str).str.strip().ne("")
        | work["entry_spread_bp"].notna()
        | work["exit_spread_bp"].notna()
    )
    work = work.loc[substantive].reset_index(drop=True)

    direction = work["decision"].astype(str).str.upper().map(
        {
            "BUY": 1.0,
            "ADD": 1.0,
            "LONG": 1.0,
            "HOLD": 0.0,
            "REDUCE": -1.0,
            "AVOID": -1.0,
            "SHORT": -1.0,
        }
    )
    work["spread_alpha_bp"] = direction * (work["entry_spread_bp"] - work["exit_spread_bp"])
    work["outcome"] = np.where(
        work["spread_alpha_bp"].notna(),
        (work["spread_alpha_bp"] > 0.0).astype(float),
        np.nan,
    )
    today = pd.Timestamp.now(tz="UTC").normalize()
    work["overdue_review"] = (
        work["review_date"].notna()
        & (work["review_date"] < today)
        & ~work["status"].astype(str).str.upper().isin(["CLOSED", "EXITED", "REJECTED"])
    )

    closed = work.loc[work["spread_alpha_bp"].notna()].copy()
    probability = closed["conviction_pct"].clip(0.0, 100.0) / 100.0
    brier_rows = pd.DataFrame({"probability": probability, "outcome": closed["outcome"]}).dropna()
    brier = (
        float(np.mean((brier_rows["probability"] - brier_rows["outcome"]) ** 2))
        if not brier_rows.empty
        else np.nan
    )
    metrics = {
        "decisions": float(len(work.dropna(subset=["decision_date"]))),
        "closed_decisions": float(len(closed)),
        "hit_rate_pct": float(100.0 * closed["outcome"].mean()) if not closed.empty else np.nan,
        "average_alpha_bp": float(closed["spread_alpha_bp"].mean()) if not closed.empty else np.nan,
        "brier_score": brier,
        "overdue_reviews": float(work["overdue_review"].sum()),
    }
    return work, metrics


def audit_point_in_time(observations: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Flag observations unavailable at the recorded decision timestamp."""
    work = pd.DataFrame(observations).copy()
    for column in PIT_COLUMNS:
        if column not in work.columns:
            work[column] = np.nan
    for column in ("observation_date", "available_date", "decision_date"):
        work[column] = pd.to_datetime(work[column], errors="coerce", utc=True)
    work["value"] = pd.to_numeric(work["value"], errors="coerce")

    substantive = work["series"].fillna("").astype(str).str.strip().ne("") | work["value"].notna()
    work = work.loc[substantive].reset_index(drop=True)
    work["missing_availability"] = work["available_date"].isna()
    work["availability_after_decision"] = work["available_date"] > work["decision_date"]
    work["observation_after_decision"] = work["observation_date"] > work["decision_date"]
    work["availability_lag_days"] = (
        work["available_date"] - work["observation_date"]
    ).dt.total_seconds() / 86_400.0
    vintage_count = work.groupby(["series", "observation_date"], dropna=False)["value"].transform("nunique")
    work["multiple_vintages"] = vintage_count > 1
    work["leakage_flag"] = (
        work["missing_availability"]
        | work["availability_after_decision"]
        | work["observation_after_decision"]
    )

    assessed = work.loc[work["decision_date"].notna()]
    metrics = {
        "rows": float(len(work)),
        "availability_coverage_pct": (
            float(100.0 * work["available_date"].notna().mean()) if len(work) else np.nan
        ),
        "leakage_rate_pct": (
            float(100.0 * assessed["leakage_flag"].mean()) if len(assessed) else np.nan
        ),
        "median_lag_days": (
            float(work["availability_lag_days"].median())
            if work["availability_lag_days"].notna().any()
            else np.nan
        ),
        "revision_rows": float(work["multiple_vintages"].sum()),
    }
    return work, metrics
