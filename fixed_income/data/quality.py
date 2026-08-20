"""Data quality gates shared by adapters and research services."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from fixed_income.contracts import ValidationReport


def inspect_frame(
    frame: pd.DataFrame,
    required_columns: Sequence[str] = (),
    unique_columns: Sequence[str] = (),
    finite_columns: Sequence[str] = (),
    observation_column: str | None = None,
    available_column: str | None = None,
    max_age_days: float | None = None,
    now: datetime | None = None,
) -> ValidationReport:
    """Run deterministic schema, uniqueness, finiteness and PIT checks."""
    report = ValidationReport()
    if not isinstance(frame, pd.DataFrame):
        report.add("TYPE", "expected a pandas DataFrame")
        return report
    if frame.empty:
        report.add("EMPTY", "dataset is empty", severity="WARNING")

    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        report.add("MISSING_COLUMNS", "missing columns: " + ", ".join(missing))
        return report

    if unique_columns:
        absent = [column for column in unique_columns if column not in frame.columns]
        if absent:
            report.add("UNIQUE_COLUMNS", "uniqueness columns are missing: " + ", ".join(absent))
        elif frame.duplicated(list(unique_columns), keep=False).any():
            count = int(frame.duplicated(list(unique_columns), keep=False).sum())
            report.add("DUPLICATES", f"{count} rows violate the uniqueness key")

    for column in finite_columns:
        if column not in frame.columns:
            report.add("FINITE_COLUMN", f"finite-value column {column} is missing")
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        invalid = ~np.isfinite(values.to_numpy(float))
        if invalid.any():
            report.add("NON_FINITE", f"{int(invalid.sum())} non-finite values", field=column)

    observation = None
    available = None
    if observation_column:
        if observation_column not in frame.columns:
            report.add("OBSERVATION_TIME", f"{observation_column} is missing")
        else:
            observation = pd.to_datetime(frame[observation_column], errors="coerce", utc=True)
            if observation.isna().any():
                report.add(
                    "OBSERVATION_PARSE",
                    f"{int(observation.isna().sum())} observation timestamps cannot be parsed",
                    field=observation_column,
                )
    if available_column:
        if available_column not in frame.columns:
            report.add("AVAILABLE_TIME", f"{available_column} is missing")
        else:
            available = pd.to_datetime(frame[available_column], errors="coerce", utc=True)
            if available.isna().any():
                report.add(
                    "AVAILABLE_PARSE",
                    f"{int(available.isna().sum())} availability timestamps cannot be parsed",
                    field=available_column,
                )
    if observation is not None and available is not None:
        impossible = available < observation
        if impossible.any():
            report.add(
                "NEGATIVE_PUBLICATION_LAG",
                f"{int(impossible.sum())} rows are available before observation",
            )

    if max_age_days is not None and available is not None and available.notna().any():
        current = pd.Timestamp(now or datetime.now(timezone.utc))
        age_days = (current - available.max()).total_seconds() / 86_400.0
        if age_days > float(max_age_days):
            report.add(
                "STALE",
                f"latest available observation is {age_days:.1f} days old",
                severity="WARNING",
            )
    return report


def quality_summary(report: ValidationReport) -> dict[str, Any]:
    counts = {"INFO": 0, "WARNING": 0, "ERROR": 0}
    for issue in report.issues:
        counts[issue.severity] += 1
    return {"ok": report.ok, "counts": counts, "issues": report.as_dicts()}
