from __future__ import annotations

"""Conservative US daily-session cutoff for research validation.

V2.5.1 separates the live monitoring clock from the research-validation clock.
The live Market Psychology state may use an in-progress US session, but any
walk-forward, holdout, Behavioral Memory validation or frozen external
replication must stop at the last *fully closed* daily session.

The policy intentionally has no exchange-calendar dependency.  For regular US
cash-equity sessions it treats a same-day daily bar as validation-eligible only
after 16:30 America/New_York (30 minutes after the normal 16:00 close).  Before
that time the cutoff is the previous weekday.  Weekends are rolled back.  On
exchange holidays, providers normally have no bar for the holiday; the date
filter therefore naturally retains the most recent actual trading bar.  On
early-close days this policy is deliberately conservative and waits until
16:30 ET before admitting that day's bar.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

US_EASTERN = ZoneInfo("America/New_York")
VALIDATION_REGULAR_CLOSE = time(16, 0)
VALIDATION_FINALIZATION_BUFFER_MINUTES = 30
VALIDATION_ELIGIBLE_TIME = time(16, 30)
VALIDATION_CUTOFF_POLICY = "US_CASH_DAILY_LAST_FULLY_CLOSED_SESSION_16_30_ET"


@dataclass(frozen=True)
class ClosedSessionCutoff:
    cutoff_date: date
    asof_utc: datetime
    asof_new_york: datetime
    policy: str = VALIDATION_CUTOFF_POLICY
    regular_close_et: str = "16:00"
    eligible_after_et: str = "16:30"

    def as_dict(self) -> dict[str, Any]:
        return {
            "cutoff_date": self.cutoff_date.isoformat(),
            "asof_utc": self.asof_utc.isoformat(),
            "asof_new_york": self.asof_new_york.isoformat(),
            "policy": self.policy,
            "regular_close_et": self.regular_close_et,
            "eligible_after_et": self.eligible_after_et,
        }


def _coerce_now(now: datetime | pd.Timestamp | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, pd.Timestamp):
        now = now.to_pydatetime()
    if not isinstance(now, datetime):
        raise TypeError("now must be datetime, pandas Timestamp, or None")
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _previous_weekday(d: date) -> date:
    out = d
    while out.weekday() >= 5:
        out -= timedelta(days=1)
    return out


def last_fully_closed_us_session_cutoff(
    now: datetime | pd.Timestamp | None = None,
) -> ClosedSessionCutoff:
    """Return the conservative last fully closed US cash-equity session date.

    Normal-session bars dated today are admitted only at/after 16:30 ET.  Before
    then, validation ends on the previous weekday.  The additional 30-minute
    buffer protects against providers publishing a still-forming or not-yet-final
    daily candle immediately at 16:00 ET.
    """
    now_utc = _coerce_now(now)
    now_ny = now_utc.astimezone(US_EASTERN)
    today = now_ny.date()

    if today.weekday() < 5 and now_ny.time().replace(tzinfo=None) >= VALIDATION_ELIGIBLE_TIME:
        candidate = today
    else:
        candidate = today - timedelta(days=1)

    candidate = _previous_weekday(candidate)
    return ClosedSessionCutoff(
        cutoff_date=candidate,
        asof_utc=now_utc,
        asof_new_york=now_ny,
    )


def trim_frame_to_closed_sessions(
    frame: pd.DataFrame | None,
    *,
    now: datetime | pd.Timestamp | None = None,
    date_col: str = "date",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Filter a dated frame to the validation cutoff without mutating the input."""
    cutoff = last_fully_closed_us_session_cutoff(now)
    meta = cutoff.as_dict()
    meta.update({"rows_before": 0, "rows_after": 0, "rows_removed": 0, "source_last_date": None, "validation_last_date": None})

    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame() if frame is None else frame.copy(), meta
    if date_col not in frame.columns:
        out = frame.copy()
        out.attrs = dict(getattr(frame, "attrs", {}))
        meta.update({"rows_before": int(len(frame)), "rows_after": int(len(out))})
        return out, meta

    out = frame.copy()
    out.attrs = dict(getattr(frame, "attrs", {}))
    dates = pd.to_datetime(out[date_col], errors="coerce", utc=True)
    valid_dates = dates.dropna()
    if not valid_dates.empty:
        meta["source_last_date"] = valid_dates.max().date().isoformat()

    mask = dates.notna() & (dates.dt.date <= cutoff.cutoff_date)
    out = out.loc[mask].copy().reset_index(drop=True)
    out.attrs = dict(getattr(frame, "attrs", {}))

    after_dates = pd.to_datetime(out[date_col], errors="coerce", utc=True).dropna() if not out.empty else pd.Series(dtype="datetime64[ns, UTC]")
    if not after_dates.empty:
        meta["validation_last_date"] = after_dates.max().date().isoformat()
    meta.update({
        "rows_before": int(len(frame)),
        "rows_after": int(len(out)),
        "rows_removed": int(len(frame) - len(out)),
    })
    return out, meta


def closed_session_validation_state(
    state: dict[str, Any],
    *,
    now: datetime | pd.Timestamp | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a shallow validation copy with history/target history cut to closed bars.

    Live state dictionaries remain untouched.  This deliberately keeps the live
    State Map capable of using current-session observations while the research
    validation stack receives only fully closed daily bars.
    """
    if not isinstance(state, dict):
        return {}, last_fully_closed_us_session_cutoff(now).as_dict()

    out = dict(state)
    history, hmeta = trim_frame_to_closed_sessions(state.get("history"), now=now)
    target, tmeta = trim_frame_to_closed_sessions(state.get("target_history"), now=now)
    out["history"] = history
    if isinstance(state.get("target_history"), pd.DataFrame):
        out["target_history"] = target

    meta = last_fully_closed_us_session_cutoff(now).as_dict()
    meta.update({
        "history_rows_before": hmeta.get("rows_before", 0),
        "history_rows_after": hmeta.get("rows_after", 0),
        "history_rows_removed": hmeta.get("rows_removed", 0),
        "history_source_last_date": hmeta.get("source_last_date"),
        "history_validation_last_date": hmeta.get("validation_last_date"),
        "target_rows_before": tmeta.get("rows_before", 0),
        "target_rows_after": tmeta.get("rows_after", 0),
        "target_rows_removed": tmeta.get("rows_removed", 0),
        "target_source_last_date": tmeta.get("source_last_date"),
        "target_validation_last_date": tmeta.get("validation_last_date"),
    })
    out["validation_cutoff"] = meta
    return out, meta
