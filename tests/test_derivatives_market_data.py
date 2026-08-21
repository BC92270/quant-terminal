from datetime import datetime, timezone

import pandas as pd

from derivatives_market_data import (
    _snapshot_row,
    fetch_tradier_option_chain,
    fetch_tradier_option_expirations,
    get_massive_api_key,
    get_thetadata_api_key,
    get_tradier_api_token,
    summarize_chain_quality,
)


def test_secret_lookup_accepts_supported_names_without_enumeration():
    assert get_massive_api_key({"MASSIVE_API_KEY": "abc"}) == "abc"
    assert get_massive_api_key({"MASSIVEAPI_KEY": "legacy"}) == "legacy"
    assert get_massive_api_key({"POLYGON_API_KEY": "polygon"}) == "polygon"
    assert get_massive_api_key({}) is None


def test_derivatives_secrets_fall_back_to_environment(monkeypatch):
    monkeypatch.setenv("THETADATA_API_KEY", "theta-env")
    monkeypatch.setenv("TRADIER_ACCESS_TOKEN", "tradier-env")
    assert get_thetadata_api_key({}) == "theta-env"
    assert get_tradier_api_token({}) == "tradier-env"


def test_tradier_expirations_normalize_single_and_multiple_dates(monkeypatch):
    monkeypatch.setattr(
        "derivatives_market_data.tradier_get_json",
        lambda *args, **kwargs: {"expirations": {"date": ["2026-09-18", "2026-12-18"]}},
    )
    expirations, context = fetch_tradier_option_expirations("spy", "token")
    assert expirations == ["2026-09-18", "2026-12-18"]
    assert context.provider == "Tradier"
    assert context.rows == 2


def test_tradier_chain_preserves_quotes_oi_iv_and_vendor_greeks(monkeypatch):
    payload = {
        "options": {
            "option": [
                {
                    "symbol": "SPY260918C00600000",
                    "type": "option",
                    "option_type": "call",
                    "strike": 600,
                    "last": 12.4,
                    "bid": 12.3,
                    "ask": 12.5,
                    "volume": 320,
                    "open_interest": 1800,
                    "expiration_date": "2026-09-18",
                    "contract_size": 100,
                    "trade_date": 1786104000000,
                    "greeks": {
                        "mid_iv": 0.215,
                        "delta": 0.53,
                        "gamma": 0.02,
                        "theta": -0.08,
                        "vega": 0.17,
                        "rho": 0.11,
                    },
                },
                {
                    "symbol": "SPY260918P00600000",
                    "option_type": "put",
                    "strike": 600,
                    "bid": 11.8,
                    "ask": 12.0,
                    "open_interest": 1600,
                    "expiration_date": "2026-09-18",
                    "greeks": {"smv_vol": 0.22, "delta": -0.47, "gamma": 0.02},
                },
            ]
        }
    }
    monkeypatch.setattr("derivatives_market_data.tradier_get_json", lambda *args, **kwargs: payload)
    calls, puts, context = fetch_tradier_option_chain("SPY", "2026-09-18", "token")
    assert len(calls) == 1 and len(puts) == 1
    assert calls.iloc[0]["openInterest"] == 1800
    assert calls.iloc[0]["impliedVolatility"] == 0.215
    assert calls.iloc[0]["delta_vendor"] == 0.53
    assert puts.iloc[0]["impliedVolatility"] == 0.22
    assert context.provider == "Tradier / OPRA"
    assert context.quality["two_sided_coverage"] == 1.0


def test_snapshot_row_preserves_nbbo_vendor_greeks_and_recency():
    row = _snapshot_row(
        {
            "details": {
                "ticker": "O:XYZ260821C00100000",
                "contract_type": "call",
                "expiration_date": "2026-08-21",
                "strike_price": 100,
                "exercise_style": "american",
                "shares_per_contract": 100,
            },
            "last_quote": {
                "bid": 4.9,
                "ask": 5.1,
                "bid_size": 10,
                "ask_size": 12,
                "last_updated": 1786104000000000000,
                "timeframe": "REAL-TIME",
            },
            "last_trade": {"price": 5.0, "size": 2, "sip_timestamp": 1786103999000000000},
            "day": {"volume": 420},
            "open_interest": 900,
            "implied_volatility": 0.42,
            "greeks": {"delta": 0.54, "gamma": 0.03, "theta": -0.08, "vega": 0.11},
            "underlying_asset": {"price": 101.5, "timeframe": "REAL-TIME"},
        }
    )
    assert row["bid"] == 4.9
    assert row["ask"] == 5.1
    assert row["delta_vendor"] == 0.54
    assert row["quoteTimeframe"] == "REAL-TIME"
    assert row["provider"] == "Massive / OPRA"


def test_chain_quality_reports_coverage_spread_and_age():
    frame = pd.DataFrame(
        {
            "bid": [1.0, 0.0],
            "ask": [1.2, 0.5],
            "impliedVolatility": [0.3, None],
            "openInterest": [100, 0],
            "delta_vendor": [0.5, None],
            "gamma_vendor": [0.02, None],
            "quoteTimestamp": ["2026-08-07T12:00:00+00:00", None],
        }
    )
    quality = summarize_chain_quality(frame, now=datetime(2026, 8, 7, 12, 1, tzinfo=timezone.utc))
    assert quality["quote_coverage"] == 1.0
    assert quality["two_sided_coverage"] == 0.5
    assert quality["iv_coverage"] == 0.5
    assert quality["greeks_coverage"] == 0.5
    assert abs(quality["median_spread_pct"] - (0.2 / 1.1)) < 1e-9
    assert quality["median_quote_age_seconds"] == 60.0
