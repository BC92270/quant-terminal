from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from monte_carlo.options_risk_neutral import (
    black_scholes_price,
    build_options_risk_neutral_lab,
    fetch_option_chain,
    implied_volatility,
    normalize_option_chain,
    project_arbitrage_free_call_curve,
)


def _synthetic_chain(
    spot: float = 100.0,
    volatility: float = 0.25,
    risk_free_rate: float = 0.04,
    dividend_yield: float = 0.01,
    valuation_date: str = "2026-08-05",
    expiration: str = "2026-09-04",
) -> pd.DataFrame:
    time_to_expiry = 30.0 / 365.0
    rows = []
    for strike in np.arange(60.0, 141.0, 5.0):
        for option_type in ("call", "put"):
            price = black_scholes_price(
                spot,
                strike,
                time_to_expiry,
                risk_free_rate,
                dividend_yield,
                volatility,
                option_type,
            )
            rows.append(
                {
                    "strike": strike,
                    "option_type": option_type,
                    "bid": max(0.001, price - 0.03),
                    "ask": price + 0.03,
                    "last_price": price,
                    "open_interest": 1_000,
                    "volume": 100,
                    "implied_volatility": volatility,
                    "expiration": expiration,
                    "valuation_date": valuation_date,
                }
            )
    return pd.DataFrame(rows)


def _lab(spot: float = 100.0) -> dict:
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0002, 0.018, size=(2_000, 30))
    paths = np.concatenate([np.full((2_000, 1), spot), spot * np.exp(np.cumsum(returns, axis=1))], axis=1)
    return {
        "ticker": "SYNTH",
        "base": {"current_price": spot},
        "paths_by_horizon": {30: paths},
    }


def test_black_scholes_implied_volatility_roundtrip():
    price = black_scholes_price(100.0, 105.0, 45.0 / 365.0, 0.03, 0.01, 0.31, "call")
    recovered = implied_volatility(price, 100.0, 105.0, 45.0 / 365.0, 0.03, 0.01, "call")
    assert abs(recovered - 0.31) < 1e-7


def test_option_chain_normalization_accepts_yfinance_columns():
    raw = pd.DataFrame(
        {
            "strike": [95, 100],
            "bid": [6.0, 3.5],
            "ask": [6.2, 3.7],
            "lastPrice": [6.1, 3.6],
            "openInterest": [100, 200],
            "impliedVolatility": [0.25, 0.24],
            "option_type": ["call", "call"],
            "expiration": ["2026-09-04", "2026-09-04"],
            "valuation_date": ["2026-08-05", "2026-08-05"],
        }
    )
    normalized, report = normalize_option_chain(raw)
    assert report["output_rows"] == 2
    assert {"mid", "relative_spread", "quote_weight", "open_interest", "implied_volatility"}.issubset(normalized.columns)
    assert np.allclose(normalized["mid"], [6.1, 3.6])


def test_arbitrage_projection_is_monotone_and_convex():
    strikes = np.array([80, 90, 100, 110, 120], dtype=float)
    noisy = np.array([22.0, 13.0, 7.4, 3.1, 1.8], dtype=float)
    noisy[2] += 1.0
    projected, report = project_arbitrage_free_call_curve(
        strikes,
        noisy,
        np.ones_like(strikes),
        spot=100.0,
        time_to_expiry=30.0 / 365.0,
        risk_free_rate=0.04,
        dividend_yield=0.01,
    )
    slopes = np.diff(projected) / np.diff(strikes)
    assert np.all(np.diff(projected) <= 1e-8)
    assert np.all(np.diff(slopes) >= -1e-8)
    assert report["max_monotonicity_violation"] <= 1e-8
    assert report["max_convexity_violation"] <= 1e-8


def test_risk_neutral_density_recovers_forward_and_model_free_volatility():
    result = build_options_risk_neutral_lab(
        _lab(),
        _synthetic_chain(),
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        max_relative_spread=2.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["status"] == "PASS"
    assert abs(result["forward"] - 100.0 * np.exp((0.04 - 0.01) * 30.0 / 365.0)) < 0.05
    assert abs(result["risk_neutral_metrics"]["mean_terminal_price"] - result["forward"]) < 0.10
    assert abs(result["model_free_volatility"] - 0.25) < 0.02
    assert 0.95 < result["raw_density_mass"] < 1.05
    assert result["projection_report"]["max_convexity_violation"] <= 1e-8
    assert result["measure_governance"]["prohibition"].startswith("Q probabilities")
    assert result["parity_accepted"] is True
    assert result["reliable_smile_quotes"] >= 8
    assert len(result["display_density_table"]) > len(result["density_table"])


def test_option_chain_cache_and_stale_fallback(tmp_path: Path):
    calls = {"count": 0}

    def provider(ticker: str, expiration: str) -> pd.DataFrame:
        calls["count"] += 1
        return _synthetic_chain()

    now = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
    first, first_report = fetch_option_chain(
        "SYNTH",
        "2026-09-04",
        cache_dir=tmp_path,
        provider_fetcher=provider,
        now=now,
    )
    second, second_report = fetch_option_chain(
        "SYNTH",
        "2026-09-04",
        cache_dir=tmp_path,
        provider_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("should not fetch")),
        now=now,
    )
    assert not first.empty and not second.empty
    assert first_report["status"] == "LIVE_FETCH"
    assert second_report["status"] == "CACHE_HIT"
    assert calls["count"] == 1

    stale, stale_report = fetch_option_chain(
        "SYNTH",
        "2026-09-04",
        cache_ttl_hours=1,
        force_refresh=True,
        cache_dir=tmp_path,
        provider_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("network down")),
        now=now,
    )
    assert not stale.empty
    assert stale_report["status"] == "STALE_CACHE_FALLBACK"


def test_american_style_chain_is_never_silent_pass():
    result = build_options_risk_neutral_lab(
        _lab(),
        _synthetic_chain(),
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="American equity/ETF approximation",
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["status"] == "WARNING"
    assert any("American-style" in warning for warning in result["warnings"])


def test_extreme_parity_carry_falls_back_to_manual_input():
    chain = _synthetic_chain(dividend_yield=0.01)
    # Artificially raise near-ATM call mids relative to puts so parity implies an
    # economically implausible negative carry.
    mask = (chain["option_type"] == "call") & chain["strike"].between(85.0, 120.0)
    chain.loc[mask, "bid"] += 1.5
    chain.loc[mask, "ask"] += 1.5
    result = build_options_risk_neutral_lab(
        _lab(),
        chain,
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["parity_accepted"] is False
    assert abs(result["dividend_yield_effective"] - 0.01) < 1e-12
    assert abs(result["forward"] - 100.0 * np.exp((0.04 - 0.01) * 30.0 / 365.0)) < 1e-10
    assert result["status"] == "WARNING"
    assert any("manual carry" in warning.lower() for warning in result["warnings"])


def test_midpoint_iv_replaces_provider_iv_and_filters_deep_itm_smile():
    chain = _synthetic_chain()
    chain["implied_volatility"] = 2.50
    result = build_options_risk_neutral_lab(
        _lab(),
        chain,
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        valuation_date="2026-08-05",
    )
    clean = result["clean_chain"]
    reliable = clean[clean["smile_eligible"]]
    assert not reliable.empty
    assert np.nanmedian(reliable["effective_iv"]) < 0.40
    assert np.nanmedian(reliable["provider_iv"]) > 2.0
    deep_itm_calls = clean[(clean["option_type"] == "call") & (clean["strike"] < 75.0)]
    assert not deep_itm_calls.empty
    assert not deep_itm_calls["smile_eligible"].any()


def test_provider_option_chain_underlying_synchronizes_midpoint_iv_inversion():
    chain = _synthetic_chain(spot=100.0)
    chain["provider_underlying_price"] = 100.0
    # Parent lab deliberately uses a stale daily close. Without synchronized
    # option-chain spot metadata, many OTM midpoint inversions fail.
    result = build_options_risk_neutral_lab(
        _lab(spot=88.0),
        chain,
        expiration="2026-09-04",
        risk_free_rate=0.04,
        dividend_yield=0.01,
        contract_style="European",
        max_relative_spread=2.0,
        valuation_date="2026-08-05",
    )
    assert result["ok"] is True
    assert result["pricing_spot_source"] == "provider_option_chain_underlying"
    assert abs(result["pricing_spot"] - 100.0) < 1e-12
    assert abs(result["lab_spot"] - 88.0) < 1e-12
    assert result["reliable_smile_quotes"] >= 8
    assert any("synchronized" in warning.lower() for warning in result["warnings"])


def test_fresh_low_quality_cache_is_auto_refreshed(tmp_path: Path):
    expiration = "2026-09-04"
    now = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)
    low = _synthetic_chain().copy()
    low["bid"] = 0.0
    low["ask"] = np.maximum(pd.to_numeric(low["last_price"], errors="coerce"), 0.01)
    low["provider_underlying_price"] = np.nan
    fetch_option_chain(
        "SYNTH", expiration, cache_dir=tmp_path, provider_fetcher=lambda *_: low, now=now
    )

    calls = {"count": 0}
    good = _synthetic_chain().copy()
    good["provider_underlying_price"] = 100.0
    def provider(*_):
        calls["count"] += 1
        return good

    frame, report = fetch_option_chain(
        "SYNTH", expiration, cache_dir=tmp_path, provider_fetcher=provider, now=now
    )
    assert not frame.empty
    assert calls["count"] == 1
    assert report["status"] == "LIVE_REFRESH_LOW_QUALITY_CACHE"
    assert report["cache_valid_midpoints"] == 0
    assert report["live_valid_midpoints"] >= 10
    assert report["live_has_provider_underlying"] is True


def test_low_quality_cache_falls_back_explicitly_when_refresh_fails(tmp_path: Path):
    expiration = "2026-09-04"
    now = datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc)
    low = _synthetic_chain().copy()
    low["bid"] = 0.0
    low["ask"] = np.maximum(pd.to_numeric(low["last_price"], errors="coerce"), 0.01)
    fetch_option_chain(
        "SYNTH", expiration, cache_dir=tmp_path, provider_fetcher=lambda *_: low, now=now
    )
    frame, report = fetch_option_chain(
        "SYNTH", expiration, cache_dir=tmp_path,
        provider_fetcher=lambda *_: (_ for _ in ()).throw(RuntimeError("network down")), now=now
    )
    assert not frame.empty
    assert report["status"] == "LOW_QUALITY_CACHE_FALLBACK"
    assert any("rejected" in warning.lower() for warning in report["warnings"])
