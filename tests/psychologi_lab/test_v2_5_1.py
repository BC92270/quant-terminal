from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.market_sessions import (
    closed_session_validation_state,
    last_fully_closed_us_session_cutoff,
    trim_frame_to_closed_sessions,
)


def _daily_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-08-07", "2026-08-10", "2026-08-11"], utc=True),
        "close": [100.0, 101.0, 102.0],
    })


def test_mid_session_cutoff_excludes_current_us_day():
    # 2026-08-11 16:18 UTC = 12:18 America/New_York: US regular session still open.
    now = datetime(2026, 8, 11, 16, 18, tzinfo=timezone.utc)
    cutoff = last_fully_closed_us_session_cutoff(now)
    assert cutoff.cutoff_date.isoformat() == "2026-08-10"

    out, meta = trim_frame_to_closed_sessions(_daily_frame(), now=now)
    assert len(out) == 2
    assert str(pd.to_datetime(out["date"], utc=True).max().date()) == "2026-08-10"
    assert meta["rows_removed"] == 1
    assert meta["validation_last_date"] == "2026-08-10"


def test_after_finalization_buffer_allows_current_day():
    # 2026-08-11 20:35 UTC = 16:35 America/New_York, after the conservative buffer.
    now = datetime(2026, 8, 11, 20, 35, tzinfo=timezone.utc)
    cutoff = last_fully_closed_us_session_cutoff(now)
    assert cutoff.cutoff_date.isoformat() == "2026-08-11"
    out, meta = trim_frame_to_closed_sessions(_daily_frame(), now=now)
    assert len(out) == 3
    assert meta["rows_removed"] == 0


def test_weekend_rolls_back_to_friday():
    # Saturday 2026-08-15 -> Friday 2026-08-14.
    now = datetime(2026, 8, 15, 15, 0, tzinfo=timezone.utc)
    cutoff = last_fully_closed_us_session_cutoff(now)
    assert cutoff.cutoff_date.isoformat() == "2026-08-14"


def test_validation_state_does_not_mutate_live_state():
    now = datetime(2026, 8, 11, 16, 18, tzinfo=timezone.utc)
    live_history = _daily_frame()
    live_target = _daily_frame()
    state = {"symbol": "SPY", "history": live_history, "target_history": live_target, "regime": "LIVE"}
    closed, meta = closed_session_validation_state(state, now=now)

    assert len(state["history"]) == 3
    assert len(state["target_history"]) == 3
    assert len(closed["history"]) == 2
    assert len(closed["target_history"]) == 2
    assert closed["regime"] == "LIVE"
    assert meta["cutoff_date"] == "2026-08-10"
    assert meta["history_rows_removed"] == 1
    assert meta["target_rows_removed"] == 1
