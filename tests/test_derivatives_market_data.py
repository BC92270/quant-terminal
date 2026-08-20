from datetime import datetime, timezone

import pandas as pd

from derivatives_market_data import (
    _snapshot_row,
    get_massive_api_key,
    summarize_chain_quality,
)


def test_secret_lookup_accepts_supported_names_without_enumeration():
    assert get_massive_api_key({"MASSIVE_API_KEY": "abc"}) == "abc"
    assert get_massive_api_key({"MASSIVEAPI_KEY": "legacy"}) == "legacy"
    assert get_massive_api_key({"POLYGON_API_KEY": "polygon"}) == "polygon"
    assert get_massive_api_key({}) is None


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

