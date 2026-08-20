import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from correlation_matrix_section.dependency_intelligence.config import DependencyConfig
from correlation_matrix_section.dependency_intelligence.data_hub import _fetch_fred_batch, _save_fred_disk_series
from correlation_matrix_section.dependency_intelligence.inputs import ForceInputs
from correlation_matrix_section.dependency_intelligence.spaces import dependency_spaces
from correlation_matrix_section.dependency_intelligence.structural import (
    extreme_move_dependency,
    higher_moment_dependency,
    lead_lag_table,
)


def _pair(seed=7, n=420):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    a = pd.Series(rng.normal(0, 1, n), index=idx)
    b = pd.Series(0.65 * a + rng.normal(0, 0.7, n), index=idx)
    return pd.DataFrame({"A": a, "B": b}, index=idx)


def test_same_base_currency_fx_hedge_is_not_required():
    ch = _pair(n=220)
    inputs = ForceInputs(asset_metadata={"A": {"currency": "USD"}, "B": {"currency": "USD"}}, base_currency="USD")
    out = dependency_spaces("A", "B", ch, inputs, min_obs=80)
    row = out[out["Space"] == "FX-hedged local"].iloc[0]
    assert row["Status"] == "Not required / identical"
    assert abs(float(row["Correlation"]) - float(ch["A"].corr(ch["B"]))) < 1e-12


def test_lead_lag_inference_reports_max_stat_post_selection():
    rng = np.random.default_rng(123)
    n = 480
    idx = pd.bdate_range("2023-01-02", periods=n)
    a = pd.Series(rng.normal(size=n), index=idx)
    # B_t is driven by A_{t-2}; equivalently A_t leads B_{t+2}.
    b = 0.75 * a.shift(2).fillna(0) + pd.Series(rng.normal(scale=0.55, size=n), index=idx)
    ch = pd.DataFrame({"A": a, "B": b}, index=idx)
    cfg = DependencyConfig(min_pair_obs=80, lead_lag_bootstrap_samples=199, random_seed=11)
    out = lead_lag_table("A", "B", ch, max_lag=5, min_obs=80, cfg=cfg)
    nz = out[out["Lag days"] != 0]
    sel = nz.loc[nz["Abs correlation"].idxmax()]
    assert int(sel["Lag days"]) == 2
    assert float(sel["Selection-adjusted p"]) <= 0.05
    assert sel["Evidence"] == "Supported"
    assert float(sel["CI low"]) > 0


def test_lead_lag_null_does_not_claim_supported_edge():
    rng = np.random.default_rng(321)
    n = 420
    idx = pd.bdate_range("2024-01-02", periods=n)
    a = pd.Series(rng.normal(size=n), index=idx)
    b = pd.Series(0.7 * a + rng.normal(scale=0.7, size=n), index=idx)  # synchronous only
    ch = pd.DataFrame({"A": a, "B": b}, index=idx)
    cfg = DependencyConfig(min_pair_obs=80, lead_lag_bootstrap_samples=199, random_seed=17)
    out = lead_lag_table("A", "B", ch, max_lag=5, min_obs=80, cfg=cfg)
    nz = out[out["Lag days"] != 0]
    sel = nz.loc[nz["Abs correlation"].idxmax()]
    assert sel["Evidence"] in {"Not supported", "Weak"}


def test_extreme_move_uncertainty_flags_small_coextreme_sample():
    ch = _pair(seed=44, n=420)
    dates = ch.index[[50, 100, 150, 200, 250, 300]]
    ch.loc[dates, "A"] += 8.0
    ch.loc[dates, "B"] += 7.0
    cfg = DependencyConfig(min_pair_obs=80, extreme_bootstrap_samples=199, random_seed=5)
    out = extreme_move_dependency("A", "B", ch, z_threshold=3.0, min_obs=80, cfg=cfg)
    assert {"CI low", "CI high", "N effective", "Quality"}.issubset(out.columns)
    corr = out[out["Metric"] == "Co-extreme-day correlation"].iloc[0]
    assert int(corr["N effective"]) < 10
    assert corr["Quality"] == "Fragile"
    prob = out[out["Metric"] == "P(peer extreme | primary extreme)"].iloc[0]
    assert 0 <= float(prob["CI low"]) <= float(prob["CI high"]) <= 1


def test_higher_moments_have_block_bootstrap_uncertainty():
    ch = _pair(seed=88, n=360)
    # add asymmetric common downside to make higher moments non-trivial
    ch.loc[ch.index[::40], "A"] -= 4.0
    ch.loc[ch.index[::40], "B"] -= 3.0
    cfg = DependencyConfig(min_pair_obs=80, higher_moment_bootstrap_samples=199, random_seed=9)
    out = higher_moment_dependency("A", "B", ch, min_obs=80, cfg=cfg)
    assert {"CI low", "CI high", "Sign stability", "Evidence", "Bootstrap reps"}.issubset(out.columns)
    assert (out["Bootstrap reps"] >= 150).all()
    assert out["Sign stability"].between(0, 1).all()


def test_fred_project_levels_take_priority_without_network(monkeypatch, tmp_path):
    import correlation_matrix_section.dependency_intelligence.data_hub as hub
    monkeypatch.setenv("QUANT_TERMINAL_CACHE_DIR", str(tmp_path))
    hub._CACHE.clear()
    idx = pd.bdate_range("2025-01-02", periods=100)
    levels = pd.DataFrame({"DGS10": np.linspace(4.0, 4.5, len(idx))}, index=idx)
    monkeypatch.setattr(hub, "_read_fred_url", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network should not be used")))
    frame, err = _fetch_fred_batch(["DGS10"], idx.min(), analysis={"dependency_fred_levels": levels})
    assert err is None
    assert "DGS10" in frame
    assert frame.attrs["fred_provenance"]["DGS10"]["source"] == "Quant Terminal macro/FRED cache"


def test_fred_stale_last_valid_cache_survives_provider_outage(monkeypatch, tmp_path):
    import correlation_matrix_section.dependency_intelligence.data_hub as hub
    monkeypatch.setenv("QUANT_TERMINAL_CACHE_DIR", str(tmp_path))
    hub._CACHE.clear()
    idx = pd.bdate_range("2024-01-02", periods=80)
    s = pd.Series(np.linspace(3.5, 4.0, len(idx)), index=idx, name="DGS10")
    _save_fred_disk_series("DGS10", s, "unit-test")
    csv_path, _ = hub._fred_cache_paths("DGS10")
    old = time.time() - 48 * 3600
    os.utime(csv_path, (old, old))
    monkeypatch.setattr(hub, "_read_fred_url", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("offline")))
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    frame, err = _fetch_fred_batch(["DGS10"], idx.min(), ttl=60, analysis={})
    assert "DGS10" in frame
    prov = frame.attrs["fred_provenance"]["DGS10"]
    assert prov["fallback"] is True
    assert "stale" in prov["source"].lower()
