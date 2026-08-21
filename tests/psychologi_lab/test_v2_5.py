from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from market_psychology import external_validation as ev


def _frame(symbol: str, n: int = 720, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-02", periods=n, freq="B", tz="UTC")
    ret = rng.normal(0.0003, 0.011, n)
    close = 100 * np.exp(np.cumsum(ret))
    out = pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.001, n)),
        "high": close * 1.005,
        "low": close * 0.995,
        "close": close,
        "volume": rng.integers(1_000_000, 5_000_000, n),
        "symbol": symbol,
    })
    out.attrs["provider"] = "TEST"
    return out


def _pack(target: str = "QQQ") -> dict[str, pd.DataFrame]:
    return {
        target: _frame(target, seed=1),
        "SPY": _frame("SPY", seed=2),
        "QQQ": _frame("QQQ", seed=3),
        "IWM": _frame("IWM", seed=4),
        "HYG": _frame("HYG", seed=5),
        "TLT": _frame("TLT", seed=6),
        "GLD": _frame("GLD", seed=7),
        "^VIX": _frame("^VIX", seed=8),
    }


def test_build_frozen_external_state_core_only(monkeypatch):
    monkeypatch.setattr(ev, "_build_external_market_pack", lambda symbol, period="5y", shared_benchmarks=None: (_pack(symbol), {"source_mode": "LIVE PROVIDER", "provider": "TEST", "provider_attempts": [], "validation_cutoff": {}}))
    state = ev.build_frozen_external_state("QQQ", period="5y")
    assert state["available"] is True
    assert state["symbol"] == "QQQ"
    assert len(state["history"]) > 500
    assert state["external_validation_mode"] is True
    assert state["behavioral_data"] == {}
    for key in ["attention_latent", "fear_latent", "extrapolation_latent", "reflexivity_latent"]:
        assert key in state["history"].columns


def test_run_external_asset_uses_locked_bundle(monkeypatch):
    monkeypatch.setattr(ev, "build_frozen_external_state", lambda symbol, period="5y", shared_benchmarks=None: {
        "available": True, "symbol": symbol, "history": pd.DataFrame({"date": pd.date_range("2020-01-01", periods=500), "close": np.arange(500)+100}),
        "target_history": pd.DataFrame({"date": pd.date_range("2020-01-01", periods=500), "close": np.arange(500)+100}), "behavioral_data": {}, "price_provider": "TEST"
    })
    monkeypatch.setattr(ev, "choose_validation_config", lambda n, profile="STANDARD": object())
    monkeypatch.setattr(ev, "evaluate_mechanisms_walk_forward", lambda history, config: {"available": True, "hypotheses": 48, "fdr_survivors": 2, "robust_oos": 1, "statistically_replicated": 0, "directionally_confirmed": 3, "failed_replication": 0, "folds": []})
    monkeypatch.setattr(ev, "build_validation_manifest", lambda symbol, history, config: {"rows": len(history)})
    r = ev.run_external_asset("QQQ", period="5y", profile="DEEP")
    assert r["available"] is True
    assert r["bundle"]["external_validation"]["scope"] == "CORE FROZEN MECHANISMS ONLY"
    assert r["bundle"]["external_validation"]["profile"] == "DEEP"


def test_external_support_requires_multiple_assets():
    def result(sym: str, level: str, ic: float):
        matrix = pd.DataFrame([{"Mechanism": "Fear", "Return": "NONE", "Future vol": level, "Tail loss": "NONE", "Behavioral state shift": "NONE"}])
        dev = pd.DataFrame([{"Mechanism": "Fear", "Target": "Future vol", "OOS IC": ic}])
        return {"available": True, "symbol": sym, "bundle": {"mechanisms": {"evidence_matrix": matrix, "development": dev, "hypotheses": 48, "fdr_survivors": 1, "robust_oos": 1, "statistically_replicated": 0, "directionally_confirmed": 1, "failed_replication": 0, "folds": []}, "manifest": {"rows": 1000}, "external_validation": {"price_provider": "TEST"}}}
    s = ev.summarize_external_results([result("QQQ", "MODERATE", .3), result("IWM", "MODERATE", .2), result("DIA", "LOW", .1)])
    row = s["support"][(s["support"]["Mechanism"] == "Fear") & (s["support"]["Target"] == "Future vol")].iloc[0]
    assert row["External support"] == "CONSISTENT EXTERNAL SUPPORT"
    assert row["Moderate/High"] == 2
    assert row["Dominant OOS sign"] == "+"


def test_unavailable_asset_stays_visible():
    s = ev.summarize_external_results([{"available": False, "symbol": "IWM", "reason": "rate limited"}])
    assert len(s["asset_summary"]) == 1
    assert s["asset_summary"].iloc[0]["Status"] == "UNAVAILABLE"
