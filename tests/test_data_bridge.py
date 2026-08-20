from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mc_lab
from monte_carlo.calibration_sources import resolve_calibration_data
from monte_carlo.data_bridge import fetch_long_history, normalize_provider_history


def prices(seed: int, n: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2015-01-02", periods=n)
    returns = rng.normal(0.0002, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "adj_close": close,
            "volume": 1_000_000,
        }
    )


def test_adjusted_history_removes_split_jump():
    dates = pd.bdate_range("2024-01-02", periods=4)
    raw = pd.DataFrame(
        {
            "Date": dates,
            "Open": [100, 102, 51, 52],
            "High": [101, 103, 52, 53],
            "Low": [99, 101, 50, 51],
            "Close": [100, 102, 51, 52],
            "Adj Close": [50, 51, 51, 52],
            "Stock Splits": [0, 0, 2, 0],
            "Volume": [1, 1, 1, 1],
        }
    )
    adjusted, report = normalize_provider_history(raw, price_basis="adjusted")
    assert report["price_basis_applied"] == "adjusted_ohlc_from_adj_close"
    assert report["split_event_count"] == 1
    assert adjusted["close"].pct_change().abs().max() < 0.05


def test_provider_cache_hit_and_stale_fallback(tmp_path):
    calls = {"count": 0}

    def fetcher(ticker: str, period: str) -> pd.DataFrame:
        calls["count"] += 1
        return prices(1, 900).set_index("date")

    now = datetime(2026, 8, 4, tzinfo=timezone.utc)
    frame, report = fetch_long_history(
        "TEST",
        cache_dir=tmp_path,
        provider_fetcher=fetcher,
        now=now,
        cache_ttl_hours=12,
    )
    assert frame is not None and len(frame) == 900
    assert report["status"] == "LIVE_FETCH"
    assert calls["count"] == 1

    cached, cached_report = fetch_long_history(
        "TEST",
        cache_dir=tmp_path,
        provider_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("should not run")),
        now=now + timedelta(hours=1),
        cache_ttl_hours=12,
    )
    assert cached is not None and len(cached) == 900
    assert cached_report["status"] == "CACHE_HIT"

    stale, stale_report = fetch_long_history(
        "TEST",
        cache_dir=tmp_path,
        provider_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("provider down")),
        now=now + timedelta(days=2),
        cache_ttl_hours=1,
    )
    assert stale is not None and len(stale) == 900
    assert stale_report["status"] == "STALE_CACHE_FALLBACK"
    assert "provider down" in stale_report["error"]


def test_source_priority_upload_explicit_provider_analysis_display():
    display = prices(2, 252)
    provider = prices(3, 1000)
    analysis = prices(4, 1200)
    explicit = prices(5, 800)

    selected, report = resolve_calibration_data(
        display,
        analysis={"long_history": analysis},
        explicit_calibration_data=explicit,
        provider_calibration_data=provider,
        provider_report={"provider": "test", "status": "LIVE_FETCH", "warnings": []},
        source_mode="auto",
    )
    assert len(selected) == 800
    assert report["selected_source"] == "explicit_calibration_data"

    selected_provider, report_provider = resolve_calibration_data(
        display,
        analysis={"long_history": analysis},
        provider_calibration_data=provider,
        provider_report={"provider": "test", "status": "LIVE_FETCH", "warnings": []},
        source_mode="auto",
    )
    assert len(selected_provider) == 1000
    assert report_provider["selected_source"] == "provider/test"


def test_validation_history_is_independent_from_current_calibration_window():
    display = prices(6, 252)
    provider = prices(7, 1000)
    lab = mc_lab.build_monte_carlo_lab(
        "BRIDGE",
        display,
        simulations=250,
        matrix_simulations=250,
        calibration_window=252,
        provider_calibration_data=provider,
        provider_report={"provider": "test", "status": "LIVE_FETCH", "warnings": []},
        provider_name="test",
        provider_period="10y",
        stability_check=False,
        garch_maxiter=200,
    )
    assert lab["ok"]
    assert lab["base"]["calibration_observations"] == 252
    assert lab["base"]["validation_observations"] == 999
    assert len(lab["base"]["validation_df"]) == 1000
