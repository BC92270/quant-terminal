from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd

# The CI/build container intentionally has no Streamlit.  Stub only the tiny
# surface data.py needs so this test can verify cached-vs-uncached routing.
if "streamlit" not in sys.modules:
    st = types.ModuleType("streamlit")
    def _cache_data(*args, **kwargs):
        def deco(fn):
            return fn
        return deco
    st.cache_data = _cache_data
    st.secrets = {}
    sys.modules["streamlit"] = st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology import data
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


def _cutoff_meta() -> dict:
    return {"cutoff_date": "2026-08-10", "validation_last_date": "2026-08-10", "policy": "TEST"}


def test_external_target_uses_uncached_data_helper_not_cached_wrapper(monkeypatch):
    calls = {"uncached": 0, "cached": 0}

    def uncached(symbol: str, period: str = "5y", interval: str = "1d"):
        calls["uncached"] += 1
        return _frame(symbol)

    def cached(symbol: str, period: str = "5y", interval: str = "1d"):
        calls["cached"] += 1
        out = pd.DataFrame()
        out.attrs["provider_attempts"] = [{"provider": "CACHED FAILURE", "status": "request_error"}]
        return out

    monkeypatch.setattr(data, "fetch_price_history_uncached", uncached)
    monkeypatch.setattr(data, "fetch_price_history", cached)
    out = ev._fetch_price_history("QQQ", "5y")
    assert not out.empty
    assert calls["uncached"] == 1
    assert calls["cached"] == 0


def test_true_uncached_second_pass_recovers_after_cached_failure_would_persist(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def true_uncached(symbol: str, period: str):
        calls["n"] += 1
        if calls["n"] == 1:
            out = pd.DataFrame()
            out.attrs["provider_attempts"] = [{"provider": "Twelve Data", "status": "request_error"}]
            return out
        return _frame(symbol)

    monkeypatch.setattr(ev, "_fetch_price_history", true_uncached)
    monkeypatch.setattr(ev.time, "sleep", lambda *_: None)
    monkeypatch.setattr(ev, "last_fully_closed_us_session_cutoff", lambda: type("C", (), {"as_dict": lambda self: _cutoff_meta()})())
    monkeypatch.setattr(ev, "trim_frame_to_closed_sessions", lambda frame: (frame.copy(), _cutoff_meta()))

    frame, meta = ev._fetch_external_target_resilient("QQQ", "5y")
    assert calls["n"] == 2
    assert not frame.empty
    assert meta["source_mode"] == "LIVE PROVIDER"
    assert meta["fetch_passes"] == 2
    controller = [r for r in meta["provider_attempts"] if r.get("provider") == "External retry controller"]
    assert controller and controller[0]["status"] == "retry_scheduled"


def test_retry_skipped_when_all_failures_are_permanent(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_EXTERNAL_CACHE_DIR", str(tmp_path))
    calls = {"n": 0}

    def permanent(symbol: str, period: str):
        calls["n"] += 1
        out = pd.DataFrame()
        out.attrs["provider_attempts"] = [
            {"provider": "Massive", "status": "insufficient_history_or_plan_limit"},
            {"provider": "Alpha Vantage", "status": "premium_full_history_required"},
        ]
        return out

    monkeypatch.setattr(ev, "_fetch_price_history", permanent)
    monkeypatch.setattr(ev.time, "sleep", lambda *_: None)
    monkeypatch.setattr(ev, "last_fully_closed_us_session_cutoff", lambda: type("C", (), {"as_dict": lambda self: _cutoff_meta()})())
    monkeypatch.setattr(ev, "trim_frame_to_closed_sessions", lambda frame: (frame.copy(), _cutoff_meta()))

    frame, meta = ev._fetch_external_target_resilient("QQQ", "5y")
    assert frame.empty
    assert calls["n"] == 1
    controller = [r for r in meta["provider_attempts"] if r.get("provider") == "External retry controller"]
    assert controller and controller[0]["status"] == "retry_skipped"


def test_baseline_requires_complete_three_asset_aligned_batch(monkeypatch):
    def fake_result(symbol: str, period: str = "5y", profile: str = "STANDARD", shared_benchmarks=None):
        return {
            "available": True,
            "symbol": symbol,
            "bundle": {
                "mechanisms": {
                    "evidence_matrix": pd.DataFrame(),
                    "development": pd.DataFrame(),
                    "hypotheses": 48,
                    "fdr_survivors": 0,
                    "robust_oos": 0,
                    "statistically_replicated": 0,
                    "directionally_confirmed": 0,
                    "failed_replication": 0,
                    "folds": [],
                },
                "manifest": {"rows": 1200, "history_end": "2026-08-10T00:00:00+00:00"},
                "external_validation": {"price_provider": "TEST", "price_source_mode": "LIVE PROVIDER"},
            },
        }

    monkeypatch.setattr(ev, "run_external_asset", fake_result)
    bundle = ev.run_external_batch(["QQQ", "IWM", "DIA"], period="5y", profile="STANDARD")
    assert bundle["batch_complete"] is True
    assert bundle["validation_end_aligned"] is True
    assert bundle["baseline_eligible"] is True
    assert bundle["baseline_reason"].startswith("ELIGIBLE")


def test_partial_batch_never_reports_baseline_eligible(monkeypatch):
    def fake_result(symbol: str, period: str = "5y", profile: str = "STANDARD", shared_benchmarks=None):
        if symbol == "QQQ":
            return {"available": False, "symbol": symbol, "reason": "provider unavailable"}
        return {
            "available": True,
            "symbol": symbol,
            "bundle": {
                "mechanisms": {
                    "evidence_matrix": pd.DataFrame(),
                    "development": pd.DataFrame(),
                    "hypotheses": 48,
                    "fdr_survivors": 0,
                    "robust_oos": 0,
                    "statistically_replicated": 0,
                    "directionally_confirmed": 0,
                    "failed_replication": 0,
                    "folds": [],
                },
                "manifest": {"rows": 1200, "history_end": "2026-08-10T00:00:00+00:00"},
                "external_validation": {"price_provider": "TEST", "price_source_mode": "LIVE PROVIDER"},
            },
        }

    monkeypatch.setattr(ev, "run_external_asset", fake_result)
    bundle = ev.run_external_batch(["QQQ", "IWM", "DIA"], period="5y", profile="STANDARD")
    assert bundle["batch_complete"] is False
    assert bundle["validation_end_aligned"] is False
    assert bundle["baseline_eligible"] is False
    assert "2/3" in bundle["baseline_reason"]
