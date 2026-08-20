import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.behavioral_data import _cftc_availability_date
from market_psychology.behavioral_memory import _episode_tags, build_behavioral_memory
from tests.test_v2_3 import _target, _latent_history, _behavioral_data, _news, _scores


def test_cftc_report_date_is_not_daily_available_until_after_release_cycle():
    # Tuesday 4 Aug 2026 -> Monday 10 Aug 2026 under the conservative
    # first-full-session-after-Friday policy.
    out = _cftc_availability_date(pd.Timestamp("2026-08-04", tz="UTC"))
    assert out == pd.Timestamp("2026-08-10", tz="UTC")
    assert out > pd.Timestamp("2026-08-04", tz="UTC")


def test_breadth_tag_distinguishes_megacap_led_from_truly_narrow():
    row = pd.Series({
        "br_sector_positive": 82.0,
        "br_sector_ma20": 73.0,
        "br_equal_weight": 42.0,
        "br_nasdaq_equal": 49.0,
        "br_smallcap": 34.0,
        "br_highbeta": 32.0,
    })
    tags = _episode_tags(row)
    assert "MEGACAP_LED_BREADTH" in tags
    assert "NARROW_BREADTH" not in tags


def test_retrieval_uses_adaptive_classes_and_exposes_partial_domain_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    target = _target(900)
    latent = _latent_history(target)
    out = build_behavioral_memory(
        "SPY", target, latent, _behavioral_data(target), _news(), _scores(latent), top_n=8
    )
    assert out["available"] is True
    assert out["similarity_threshold"] >= out["similarity_floor"]
    assert out["activation_threshold"] >= out["activation_floor"]
    assert "Retrieval class" in out["analogues"].columns
    assert not out["analogues"]["Retrieval class"].eq("RELIABLE").any()
    assert 0 <= out["historically_usable_domains"] <= out["domain_total"] == 8
    structural = out["structural_analogues"]
    candidates = out["memory_candidates"]
    if not candidates.empty:
        assert candidates["Activation"].min() >= out["activation_threshold"] - 0.11
    if not structural.empty:
        assert structural["Coverage"].min() >= 100 * out["min_coverage"] - 0.11
