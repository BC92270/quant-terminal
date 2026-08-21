import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology.behavioral_memory import (
    archive_current_snapshot,
    build_behavioral_memory,
    load_snapshot_archive,
)


def _target(n=900):
    dates = pd.bdate_range(end=pd.Timestamp("2026-08-10", tz="UTC"), periods=n)
    # Repeating smooth regime cycle creates genuine spaced analogues without random coincidence.
    t = np.arange(n)
    ret = 0.00025 + 0.004 * np.sin(2 * np.pi * t / 180) + 0.0015 * np.sin(2 * np.pi * t / 45)
    close = 100 * np.exp(np.cumsum(ret))
    volume = 1e7 * (1.0 + 0.25 * np.sin(2 * np.pi * t / 180 + 0.5))
    return pd.DataFrame({"date": dates, "open": close, "high": close*1.01, "low": close*.99, "close": close, "volume": volume})


def _latent_history(target):
    dates = pd.to_datetime(target["date"], utc=True)
    t = np.arange(len(dates))
    cyc = np.sin(2*np.pi*t/180)
    return pd.DataFrame({
        "date": dates,
        "attention": 50 + 22*cyc,
        "fear": 50 - 18*cyc,
        "herding": 50 + 15*cyc,
        "extrapolation": 50 + 25*cyc,
        "reflexivity": 50 + 19*cyc,
    })


def _price_frame(dates, base=100.0, phase=0.0):
    t=np.arange(len(dates))
    close=base*np.exp(np.cumsum(0.0002+0.002*np.sin(2*np.pi*t/180+phase)))
    return pd.DataFrame({"date":dates,"close":close})


def _behavioral_data(target):
    dates = pd.to_datetime(target["date"], utc=True)
    frames = {s:_price_frame(dates,100+i*3,i*.2) for i,s in enumerate([
        "SPY","RSP","QQQ","QQEW","IWM","SPHB","SPLV","XLB","XLC","XLE","XLF","XLI","XLK","XLP","XLRE","XLU","XLV","XLY"
    ])}
    histories={}
    t=np.arange(len(dates))
    for name,base,amp in [("VIX",18,4),("VVIX",90,12),("VIX9D",17,4),("VIX3M",20,3),("SKEW",135,8)]:
        histories[name]=pd.DataFrame({"date":dates,"value":base+amp*np.sin(2*np.pi*t/180)})
    weekly=dates[::5]
    tw=np.arange(len(weekly))
    cftc=pd.DataFrame({
        "date":weekly,
        "lev_money_net_pct_oi":.15*np.sin(2*np.pi*tw/36),
        "asset_mgr_net_pct_oi":.30+.08*np.cos(2*np.pi*tw/36),
        "dealer_net_pct_oi":-.20+.07*np.sin(2*np.pi*tw/36+.3),
    })
    series={}
    for key,base in [("hy_oas",3.0),("ig_oas",1.0),("nfci_risk",0.0),("stlfsi",0.0)]:
        series[key]=pd.DataFrame({"date":weekly,"value":base+.25*np.sin(2*np.pi*tw/36)})
    return {
        "volatility_tail":{"histories":histories,"metrics":{"tail_stress_score":45}},
        "breadth":{"frames":frames,"metrics":{"breadth_score":60}},
        "funding_credit":{"series":series,"metrics":{"funding_stress_score":42}},
        "positioning":{"history":cftc,"metrics":{"positioning_crowding_score":20}},
        "options_behavior":{"metrics":{"option_tail_demand_score":45,"option_lottery_score":60,"convexity_concentration_score":20,"put_call_volume":1.0}},
        "evidence_score":82,
    }


def _news():
    return {
        "theme_concentration":0.35,
        "belief_disagreement":60,
        "belief_confidence_mean":55,
        "sentiment_mean":0.2,
        "resolved_coverage":70,
        "dominant_narrative":"Market structure / ETF flows",
    }


def _scores(latent):
    r=latent.iloc[-1]
    return {k:float(r[k]) for k in ["attention","fear","herding","extrapolation","reflexivity"]} | {"narrative":45}


def test_memory_finds_spaced_multi_domain_analogue(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    target=_target()
    latent=_latent_history(target)
    out=build_behavioral_memory("SPY",target,latent,_behavioral_data(target),_news(),_scores(latent),top_n=6,similarity_threshold=55)
    assert out["available"] is True
    assert not out["analogues"].empty
    assert 0 <= out["memory_activation_score"] <= 100
    assert out["best_similarity"] > 50
    dates=pd.to_datetime(out["analogues"]["date"],utc=True).sort_values()
    if len(dates)>1:
        diffs=np.diff(dates.values).astype("timedelta64[D]").astype(int)
        assert np.min(np.abs(diffs)) >= 30
    assert "Market state" in out["domain_coverage"]["Domain"].tolist()
    assert "Behavioral state" in out["domain_coverage"]["Domain"].tolist()


def test_archive_is_point_in_time_and_never_backfills(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    data={"options_behavior":{"metrics":{"option_tail_demand_score":50}},"evidence_score":70}
    status=archive_current_snapshot("SPY",{"attention":50,"fear":40,"herding":45,"extrapolation":70,"reflexivity":55,"narrative":40},_news(),data)
    assert status["stored"] is True
    archive=load_snapshot_archive("SPY")
    assert len(archive)==1
    assert "dominant_narrative" in archive.columns
    # Re-run the same day: upsert, not duplicate.
    archive_current_snapshot("SPY",{"attention":51,"fear":41,"herding":46,"extrapolation":71,"reflexivity":56,"narrative":41},_news(),data)
    archive2=load_snapshot_archive("SPY")
    assert len(archive2)==1


def test_no_reliable_analogue_gate_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKET_PSYCHOLOGY_MEMORY_DIR", str(tmp_path))
    target=_target(500)
    latent=_latent_history(target)
    out=build_behavioral_memory("SPY",target,latent,_behavioral_data(target),_news(),_scores(latent),similarity_threshold=99.9)
    assert out["available"] is True
    assert out["no_reliable_analogue"] is True
    assert len(out["reliable_analogues"])==0
