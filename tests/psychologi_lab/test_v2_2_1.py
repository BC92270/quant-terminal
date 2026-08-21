import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_psychology import behavioral_data as bd
from market_psychology import data as data_mod


def _price_frame(n=80, base=100.0):
    dates = pd.bdate_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n)
    close = np.linspace(base, base * 1.08, n)
    return pd.DataFrame({"date": dates, "close": close})


def test_cboe_single_value_schema_is_accepted(monkeypatch):
    class Resp:
        status_code = 200
        text = "DATE,VVIX\n2026-08-07,91.5\n2026-08-10,89.2\n"
        def raise_for_status(self):
            return None

    monkeypatch.setattr(bd.requests, "get", lambda *a, **k: Resp())
    df, meta = bd._fetch_cboe_history("VVIX", "6mo")
    assert not df.empty
    assert list(df.columns) == ["date", "value"]
    assert float(df.iloc[-1]["value"]) == 89.2
    assert meta["value_column"] == "vvix"


def test_breadth_falls_through_to_terminal_price_waterfall(monkeypatch):
    monkeypatch.setattr(bd, "YFINANCE_AVAILABLE", False)

    def fake_fetch(symbol, period):
        return _price_frame(base=100 + hash(symbol) % 7), [{"provider": "Fake waterfall", "symbol": symbol, "status": "selected"}]

    monkeypatch.setattr(bd, "_fetch_public_price", fake_fetch)
    frames, attempts = bd._fetch_breadth_prices("unit-breadth")
    assert len(frames) == len(bd.BREADTH_ETFS)
    assert "SPY" in frames and "RSP" in frames and "XLK" in frames
    out = bd.fetch_breadth_layer("unit-breadth-layer")
    # fetch_breadth_layer has its own cached call, so force the same fallback again.
    assert out["coverage"] >= 7
    assert out["core_coverage"] >= 4
    assert out["metrics"]["breadth_score"] is not None


def test_option_tenor_shares_require_audited_denominator(monkeypatch):
    now = pd.Timestamp.now(tz="UTC").date()
    expiries = [
        (pd.Timestamp(now) + pd.Timedelta(days=d)).date().isoformat()
        for d in (0, 7, 14, 45, 75)
    ]

    def chain_for(expiry):
        dte = (pd.Timestamp(expiry).date() - now).days
        vol = 1000 if dte == 0 else 500
        calls = pd.DataFrame({
            "strike": [100, 105], "volume": [vol, vol], "openInterest": [5000, 3000],
            "impliedVolatility": [0.20, 0.22],
        })
        puts = pd.DataFrame({
            "strike": [95, 100], "volume": [vol, vol], "openInterest": [4500, 3500],
            "impliedVolatility": [0.25, 0.23],
        })
        return SimpleNamespace(calls=calls, puts=puts)

    class FakeTicker:
        options = expiries
        fast_info = {"last_price": 100.0}
        def option_chain(self, expiry):
            return chain_for(expiry)
        def history(self, *a, **k):
            return pd.DataFrame({"Close": [100.0]})

    monkeypatch.setattr(data_mod, "YFINANCE_AVAILABLE", True)
    monkeypatch.setattr(data_mod, "yf", SimpleNamespace(Ticker=lambda symbol: FakeTicker()))
    out = data_mod.fetch_options_snapshot("UNITOPT", max_expiries=3)
    assert out["tenor_denominator_complete"] is True
    assert out["max_dte_loaded"] >= 45
    assert out["loaded_expiry_count"] >= 4  # first 3 + first >30D gate
    assert 0 <= out["dte_7_share"] < 1
    assert 0 <= out["zero_dte_share"] < 1
    assert out["tenor_denominator_status"].startswith("AUDITED_")


def test_behavioral_availability_is_completeness_weighted(monkeypatch):
    today = pd.Timestamp.now(tz="UTC").normalize()
    h = pd.DataFrame({"date": [today], "value": [20.0]})
    monkeypatch.setattr(bd, "fetch_volatility_tail_layer", lambda period: {
        "available": True, "coverage": 3, "coverage_total": 5,
        "histories": {"VIX": h, "VIX9D": h, "VIX3M": h, "VVIX": pd.DataFrame(), "SKEW": pd.DataFrame()},
        "metrics": {},
    })
    monkeypatch.setattr(bd, "fetch_breadth_layer", lambda period: {
        "available": False, "coverage": 0, "coverage_total": 18, "frames": {}, "metrics": {},
    })
    monkeypatch.setattr(bd, "fetch_funding_credit_layer", lambda period: {
        "available": True, "coverage": 7, "coverage_total": 7, "series": {"x": h}, "metrics": {},
    })
    ph = pd.DataFrame({"date": pd.date_range(end=today, periods=80, freq="7D", tz="UTC")})
    monkeypatch.setattr(bd, "fetch_cftc_positioning_layer", lambda symbol: {
        "available": True, "history": ph, "metrics": {"as_of": today},
    })
    monkeypatch.setattr(bd, "enrich_options_behavior", lambda options: {
        "available": True, "metrics": {"rows": 821, "tenor_denominator_complete": True},
    })
    monkeypatch.setattr(bd, "fetch_short_interest_status", lambda: {"available": False})

    out = bd.build_behavioral_data_layer("SPY", "2y", {"available": True})
    assert 45 <= out["availability_score"] <= 75
    assert out["availability_score"] < 80  # V2.2's binary 80/100 would be too generous here.
    assert 0 <= out["freshness_score"] <= 100
    assert 0 <= out["identification_score"] <= 100
    assert 0 <= out["evidence_score"] <= 100
