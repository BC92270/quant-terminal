import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import market_psychology.data as data


def _price(rows=1100):
    dates = pd.date_range("2022-01-03", periods=rows, freq="B", tz="UTC")
    return pd.DataFrame({
        "date": dates,
        "open": range(rows),
        "high": range(rows),
        "low": range(rows),
        "close": [100 + i * 0.01 for i in range(rows)],
        "volume": [1_000_000] * rows,
    })


def test_market_pack_stops_after_missing_target(monkeypatch):
    calls = []

    def fake_fetch(symbol, period="2y", interval="1d"):
        calls.append((symbol, period))
        out = pd.DataFrame()
        out.attrs["provider_attempts"] = [{"provider": "X", "status": "rate_limited", "http": 429}]
        return out

    monkeypatch.setattr(data, "fetch_price_history", fake_fetch)
    out = data.fetch_market_pack("SPY", period="5y", benchmarks=("QQQ", "IWM"))
    assert list(out) == ["SPY"]
    assert calls == [("SPY", "5y")]


def test_market_pack_caps_benchmark_horizon(monkeypatch):
    calls = []

    def fake_fetch(symbol, period="2y", interval="1d"):
        calls.append((symbol, period))
        return _price(1100 if symbol == "SPY" else 220)

    monkeypatch.setattr(data, "fetch_price_history", fake_fetch)
    out = data.fetch_market_pack("SPY", period="5y", benchmarks=("QQQ", "IWM"))
    assert set(out) == {"SPY", "QQQ", "IWM"}
    assert calls[0] == ("SPY", "5y")
    assert ("QQQ", "1y") in calls and ("IWM", "1y") in calls


def test_massive_uses_documented_apikey_query(monkeypatch):
    monkeypatch.setattr(data, "_get_secret", lambda *names: "secret")
    captured = {}

    def fake_request(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params", {})
        dates = pd.date_range("2022-01-03", periods=1100, freq="B", tz="UTC")
        results = [{"t": int(d.timestamp() * 1000), "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100} for d in dates]
        return {"results": results}, {"status": "ok", "http": 200}

    monkeypatch.setattr(data, "_request_json", fake_request)
    df, meta = data._fetch_massive_daily("SPY", "5y")
    assert captured["params"]["apiKey"] == "secret"
    assert meta["status"] == "ok"
    assert not df.empty


def test_fmp_stable_endpoint_accepts_list_payload(monkeypatch):
    monkeypatch.setattr(data, "_get_secret", lambda *names: "secret")
    seen = []

    def fake_request(url, **kwargs):
        seen.append(url)
        dates = pd.date_range("2022-01-03", periods=1100, freq="B", tz="UTC")
        payload = [{"date": d.date().isoformat(), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100} for d in dates]
        return payload, {"status": "ok", "http": 200}

    monkeypatch.setattr(data, "_request_json", fake_request)
    df, meta = data._fetch_fmp_daily("SPY", "5y")
    assert seen and "/stable/historical-price-eod/full" in seen[0]
    assert meta["status"] == "ok"
    assert not df.empty
