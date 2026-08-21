from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology import external_validation as ev


def _frame(symbol: str = "QQQ", n: int = 1200, end: str = "2026-08-10") -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp(end), periods=n, tz="UTC")
    close = np.linspace(100, 200, n)
    df = pd.DataFrame({
        "date": dates,
        "open": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": np.full(n, 1_000_000),
    })
    df.attrs["provider"] = "TEST LIVE"
    df.attrs["provider_attempts"] = [{"provider": "TEST LIVE", "status": "ok", "rows": n}]
    df.attrs["symbol"] = symbol
    return df


def _cutoff_meta(date: str = "2026-08-10") -> dict:
    return {"cutoff_date": date, "validation_last_date": date, "policy": "TEST"}


def test_bounded_fresh_retry_recovers_second_pass(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def fake_fetch(symbol: str, period: str):
        calls["n"] += 1
        if calls["n"] == 1:
            empty = pd.DataFrame()
            empty.attrs["provider_attempts"] = [{"provider": "TEST", "status": "request_error"}]
            return empty
        return _frame(symbol)

    monkeypatch.setattr(ev, "_fetch_price_history", fake_fetch)
    monkeypatch.setattr(ev.time, "sleep", lambda *_: None)
    monkeypatch.setattr(ev, "last_fully_closed_us_session_cutoff", lambda: type("C", (), {"as_dict": lambda self: _cutoff_meta()})())
    monkeypatch.setattr(ev, "trim_frame_to_closed_sessions", lambda frame: (frame.copy(), _cutoff_meta()))

    frame, meta = ev._fetch_external_target_resilient("QQQ", "5y")
    assert calls["n"] == 2
    assert not frame.empty
    assert meta["source_mode"] == "LIVE PROVIDER"
    assert meta["provider"] == "TEST LIVE"
    assert (tmp_path / "QQQ_5Y_closed.csv").exists()


def test_validated_cache_fallback_after_provider_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    live = _frame("QQQ")
    wrote = ev._persist_external_price_cache("QQQ", "5y", live, source_provider="Twelve Data", cutoff_meta=_cutoff_meta())
    assert wrote["status"] == "cache_written"

    def fail_fetch(symbol: str, period: str):
        out = pd.DataFrame()
        out.attrs["provider_attempts"] = [{"provider": "Twelve Data", "status": "request_error"}]
        return out

    monkeypatch.setattr(ev, "_fetch_price_history", fail_fetch)
    monkeypatch.setattr(ev.time, "sleep", lambda *_: None)
    monkeypatch.setattr(ev, "last_fully_closed_us_session_cutoff", lambda: type("C", (), {"as_dict": lambda self: _cutoff_meta()})())
    monkeypatch.setattr(ev, "trim_frame_to_closed_sessions", lambda frame: (frame.copy(), _cutoff_meta()))

    frame, meta = ev._fetch_external_target_resilient("QQQ", "5y")
    assert not frame.empty
    assert meta["source_mode"] == "VALIDATED LOCAL CACHE"
    assert meta["provider"] == "Twelve Data"
    assert meta["cache"]["status"] == "cache_hit_validated"


def test_cache_rejects_future_bar(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    frame = _frame("QQQ", end="2026-08-11")
    # Write metadata manually so load-time cutoff is the part under test.
    csv_path, meta_path = ev._cache_paths("QQQ", "5y")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False)
    meta = {
        "schema_version": ev.EXTERNAL_CACHE_SCHEMA_VERSION,
        "symbol": "QQQ",
        "period": "5y",
        "source_provider": "TEST",
        "rows": len(frame),
        "first_date": str(pd.to_datetime(frame["date"], utc=True).min().date()),
        "last_date": "2026-08-11",
        "csv_sha256": ev._cache_digest(csv_path),
    }
    meta_path.write_text(json.dumps(meta))
    cached, diag = ev._load_external_price_cache("QQQ", "5y", cutoff_meta=_cutoff_meta("2026-08-10"))
    assert cached.empty
    assert diag["status"] == "cache_future_bar_rejected"


def test_cache_rejects_excessive_staleness(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    frame = _frame("QQQ", end="2026-08-03")
    wrote = ev._persist_external_price_cache("QQQ", "5y", frame, source_provider="TEST", cutoff_meta={"cutoff_date": "2026-08-03"})
    assert wrote["status"] == "cache_written"
    cached, diag = ev._load_external_price_cache("QQQ", "5y", cutoff_meta=_cutoff_meta("2026-08-10"))
    assert cached.empty
    assert diag["status"] == "cache_stale"


def test_asset_summary_exposes_cache_source_mode():
    result = {
        "available": True,
        "symbol": "QQQ",
        "bundle": {
            "mechanisms": {"hypotheses": 48, "fdr_survivors": 1, "robust_oos": 1, "statistically_replicated": 0, "directionally_confirmed": 2, "failed_replication": 0, "folds": []},
            "manifest": {"rows": 1200, "history_end": "2026-08-10T00:00:00+00:00"},
            "external_validation": {"price_provider": "Twelve Data", "price_source_mode": "VALIDATED LOCAL CACHE"},
        },
    }
    row = ev._asset_row(result)
    assert row["Provider"] == "Twelve Data"
    assert row["Source mode"] == "VALIDATED LOCAL CACHE"
    assert row["Validation end"] == "2026-08-10"
