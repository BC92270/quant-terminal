import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.walk_forward import (
    _bh_qvalues,
    build_walk_forward_folds,
    build_walk_forward_validation_bundle,
    choose_validation_config,
    evaluate_mechanisms_walk_forward,
    evaluate_memory_walk_forward,
)
from tests.test_v2_3 import _target, _latent_history, _behavioral_data


def _history(n=1250):
    target = _target(n)
    latent = _latent_history(target).copy()
    latent["close"] = target["close"].to_numpy()
    # Raw/normalized columns allow the stale-proxy guard to run without
    # classifying the synthetic cyclical history as constant.
    for key in ["attention", "fear", "herding", "extrapolation", "reflexivity"]:
        latent[f"{key}_raw"] = latent[key]
        latent[f"{key}_normalized"] = latent[key]
        latent[f"{key}_latent"] = latent[key]
        latent[f"{key}_severity"] = np.where(latent[key] >= 82, 3, np.where(latent[key] >= 70, 2, 0))
    return target, latent


def test_walk_forward_splits_reserve_final_holdout_and_are_chronological():
    cfg = choose_validation_config(1250, "STANDARD")
    assert cfg is not None
    folds = build_walk_forward_folds(1250, cfg)
    assert folds[-1].partition == "HOLDOUT"
    assert folds[-1].test_end == 1250
    wf = [f for f in folds if f.partition == "WALK_FORWARD"]
    assert len(wf) >= 3
    assert all(a.test_end <= b.test_start for a, b in zip(wf, wf[1:]))
    assert wf[-1].test_end <= folds[-1].test_start


def test_bh_qvalues_are_valid_and_order_preserving():
    p = np.array([0.001, 0.01, 0.03, 0.20, np.nan])
    q = _bh_qvalues(p)
    assert np.nanmin(q) >= 0 and np.nanmax(q) <= 1
    assert q[0] <= q[1] <= q[2] <= q[3]
    assert np.isnan(q[4])


def test_mechanism_walk_forward_builds_development_and_holdout_tables():
    _, history = _history(1250)
    cfg = choose_validation_config(len(history), "STANDARD")
    out = evaluate_mechanisms_walk_forward(history, cfg)
    assert out["available"] is True
    assert not out["development"].empty
    assert not out["holdout"].empty
    assert "FDR q" in out["development"].columns
    assert "Development evidence" in out["development"].columns
    assert not out["confirmation"].empty
    assert set(out["development"]["Target"].unique()) == {"Return", "Future vol", "Tail loss", "Behavioral state shift"}


def test_memory_walk_forward_uses_historical_analogues_without_current_backfill(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    target, history = _history(1100)
    cfg = choose_validation_config(len(history), "STANDARD")
    out = evaluate_memory_walk_forward("SPY", target, history, _behavioral_data(target), cfg, horizons=(20,))
    assert out["available"] is True
    assert not out["summary"].empty
    assert (out["detail"]["Candidates"] >= 3).all()
    assert set(out["detail"]["Partition"].unique()).issubset({"WALK_FORWARD", "HOLDOUT"})


def test_full_v24_bundle_has_manifest_and_no_production_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    target, history = _history(1100)
    state = {
        "symbol": "SPY",
        "history": history,
        "target_history": target,
        "behavioral_data": _behavioral_data(target),
    }
    out = build_walk_forward_validation_bundle(state, profile="STANDARD")
    assert out["available"] is True
    assert out["version"] == "V2.4.1"
    assert "no production promotion" in out["status"].lower()
    assert out["manifest"]["rows"] == len(history)
    assert out["manifest"]["holdout_rows"] > 0
    assert "walk_forward.py" in out["manifest"]["code_hashes"]
