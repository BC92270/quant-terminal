import numpy as np
import pandas as pd

from correlation_matrix_section.dependency_intelligence.config import DependencyConfig
from correlation_matrix_section.dependency_intelligence.data_hub import build_dependency_data_hub
from correlation_matrix_section.dependency_intelligence.engine import DependencyIntelligence
from correlation_matrix_section.dependency_intelligence.force_model import fit_force_model
from correlation_matrix_section.dependency_intelligence.inputs import collect_force_inputs, force_coverage_table
from correlation_matrix_section.dependency_intelligence.structural import extreme_move_dependency


def _returns(seed=101, n=420):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    a = pd.Series(rng.normal(0, .01, n), index=idx)
    b = pd.Series(.55 * a.to_numpy() + rng.normal(0, .008, n), index=idx)
    return pd.DataFrame({"A": a, "B": b}, index=idx)


def test_daily_extreme_move_labels_do_not_claim_jump_process():
    ch = _returns()
    ch.loc[ch.index[[50, 150, 250, 350]], "A"] += .12
    ch.loc[ch.index[[50, 150, 250, 350]], "B"] += .10
    out = extreme_move_dependency("A", "B", ch, z_threshold=3.0, min_obs=80)
    metrics = " | ".join(out["Metric"].astype(str).tolist()).lower()
    assert "co-extreme observations" in metrics
    assert "jump" not in metrics
    assert int(out.loc[out["Metric"] == "Co-extreme observations", "Value"].iloc[0]) >= 3


def test_engine_summary_separates_synchronous_from_nonzero_lag():
    rng = np.random.default_rng(12)
    n = 420
    idx = pd.bdate_range("2024-01-02", periods=n)
    a = pd.Series(rng.normal(size=n), index=idx)
    # strong synchronous relation plus a smaller true +2D association
    b = .75 * a + .30 * a.shift(2).fillna(0) + pd.Series(rng.normal(scale=.4, size=n), index=idx)
    changes = pd.DataFrame({"A": a, "B": b}, index=idx)
    analysis = {"dependency_data_hub_mode": "injected-only", "dependency_force_series": pd.DataFrame({"F": a}, index=idx),
                "dependency_force_metadata": {"F": {"mechanism": "Fundamental/Systematic", "family": "Test"}}}
    dep = DependencyIntelligence(DependencyConfig(min_pair_obs=80, max_factors=2)).analyse_pair("A", "B", changes, analysis)
    assert dep.status == "ok"
    assert dep.summary["synchronous_corr"] > .7
    assert dep.summary["best_nonzero_lag_days"] != 0
    # Positive lag means the primary is compared with a later peer return.
    assert dep.summary["best_nonzero_lag_days"] == 2


def test_data_hub_user_series_override_auto(monkeypatch):
    import correlation_matrix_section.dependency_intelligence.data_hub as hub
    ch = _returns(n=260)
    idx = ch.index
    # Mock public batch with all requested columns and enough variation.
    def fake_fred(ids, start, timeout=6.0, ttl=21600):
        x = pd.DataFrame(index=idx)
        for j, sid in enumerate(ids):
            x[sid] = 2.0 + .01 * j + np.linspace(0, .5 + .01*j, len(idx)) + .03*np.sin(np.arange(len(idx))/(7+j%4))
        return x, None
    def fake_hist(symbol, start, end, ttl=1800):
        base = 100 * np.exp(np.cumsum(np.full(len(idx), .0002) + .003*np.sin(np.arange(len(idx))/13)))
        return pd.DataFrame({"close": base, "volume": np.linspace(1e6, 1.5e6, len(idx))}, index=idx)
    def fake_meta(symbol, ttl=21600):
        return {"currency": "USD", "sector": "Test", "market_cap": 1e11, "average_volume": 1e6, "exchange": "NMS"}
    monkeypatch.setattr(hub, "_fetch_fred_batch", fake_fred)
    monkeypatch.setattr(hub, "_yahoo_history", fake_hist)
    monkeypatch.setattr(hub, "_yahoo_metadata", fake_meta)
    monkeypatch.setattr(hub, "_gpr_auto_forces", lambda changes: (pd.DataFrame(index=changes.index), {}, pd.DataFrame()))
    user = pd.Series(np.arange(len(idx), dtype=float), index=idx, name="Real yields")
    result = build_dependency_data_hub("A", "B", ch, {"dependency_data_hub_mode": "max", "dependency_force_series": user.to_frame()})
    got = result.analysis["dependency_force_series"]["Real yields"]
    assert np.array_equal(got.to_numpy(), user.to_numpy())
    assert result.summary["active"] is True
    assert result.summary["liquidity_metrics"] >= 2
    assert not result.audit.empty


def test_data_hub_coverage_spans_multiple_mechanisms_with_mocked_public_data(monkeypatch):
    import correlation_matrix_section.dependency_intelligence.data_hub as hub
    ch = _returns(n=260)
    idx = ch.index
    rng = np.random.default_rng(22)
    def fake_fred(ids, start, timeout=6.0, ttl=21600):
        x = pd.DataFrame(index=idx)
        for j, sid in enumerate(ids):
            x[sid] = 2 + np.cumsum(rng.normal(0, .01 + j*.00005, len(idx)))
        return x, None
    def fake_hist(symbol, start, end, ttl=1800):
        ret = rng.normal(0, .01, len(idx))
        return pd.DataFrame({"close": 100*np.exp(np.cumsum(ret)), "volume": rng.lognormal(14, .2, len(idx))}, index=idx)
    def fake_meta(symbol, ttl=21600):
        return {"currency": "USD", "sector": "Test", "market_cap": 5e10, "average_volume": 2e6}
    monkeypatch.setattr(hub, "_fetch_fred_batch", fake_fred)
    monkeypatch.setattr(hub, "_yahoo_history", fake_hist)
    monkeypatch.setattr(hub, "_yahoo_metadata", fake_meta)
    monkeypatch.setattr(hub, "_gpr_auto_forces", lambda changes: (pd.DataFrame(index=changes.index), {}, pd.DataFrame()))
    enriched = build_dependency_data_hub("A", "B", ch, {"dependency_data_hub_mode": "max"})
    inputs = collect_force_inputs(ch, enriched.analysis)
    coverage = force_coverage_table(inputs, ch)
    connected = coverage[coverage["Status"] != "Not connected"]
    assert "Auto public series" in set(connected["Status"])
    assert "Auto market series" in set(connected["Status"])
    assert "Derived in pair engine" in set(connected["Status"])
    # public series + market + daily-derived + metadata/liquidity should span all major origins except true intraday jumps
    assert connected["Mechanism"].nunique() >= 4


def test_high_dimensional_force_selection_is_bounded_and_auditable():
    rng = np.random.default_rng(55)
    n = 520
    idx = pd.bdate_range("2023-01-02", periods=n)
    latent = rng.normal(size=(n, 5))
    factors = {}
    meta = {}
    for j in range(45):
        base = latent[:, j % 5] + rng.normal(scale=.25 + .01*(j % 7), size=n)
        name = f"F{j:02d}"
        factors[name] = base
        meta[name] = {"mechanism": ["Exogenous", "Endogenous Market", "Information/Event"][j % 3], "family": f"Family{j%9}"}
    F = pd.DataFrame(factors, index=idx)
    y1 = .5*F["F00"] - .3*F["F04"] + rng.normal(scale=.8, size=n)
    y2 = .4*F["F00"] + .35*F["F12"] + rng.normal(scale=.8, size=n)
    changes = pd.DataFrame({"A": y1, "B": y2}, index=idx)
    cfg = DependencyConfig(min_pair_obs=80, max_factors=10, max_factors_per_family=2)
    fm = fit_force_model("A", "B", changes, F, meta, cfg)
    assert fm.status == "ok"
    assert len(fm.factors_used) <= 10
    assert not fm.selection_diagnostics.empty
    assert {"Temporal stability", "Selection score", "Selection status"}.issubset(fm.selection_diagnostics.columns)
    assert (fm.selection_diagnostics["Selection status"] == "selected").sum() == len(fm.factors_used)


def test_public_gpr_csv_adapter_maps_daily_components(monkeypatch):
    import correlation_matrix_section.dependency_intelligence.data_hub as hub
    ch = _returns(n=120)
    idx = ch.index
    csv = "date,GPR_AI,Threats_GPR,Acts_GPR,Oil_GPR\n" + "\n".join(
        f"{d.date()},{100+i%7},{80+i%5},{70+i%6},{40+i%4}" for i, d in enumerate(idx)
    )
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return csv.encode("utf-8")
    monkeypatch.setattr(hub, "urlopen", lambda req, timeout=4.0: Resp())
    # isolate test from any prior module-level cache
    hub._CACHE.clear()
    frame, meta, audit = hub._gpr_auto_forces(ch, timeout=1.0, ttl=1)
    assert {"Geopolitical-risk index", "Geopolitical threats index", "Geopolitical acts index", "Geopolitical oil-disruption risk"}.issubset(frame.columns)
    assert meta["Geopolitical-risk index"]["source_kind"] == "auto_public"
    assert (audit["Status"] == "Active").sum() == 4
