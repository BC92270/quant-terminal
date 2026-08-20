import io
import zipfile

import pandas as pd

from derivatives_workspaces import (
    build_export_package,
    delta_skew_snapshot,
    gamma_exposure_by_strike,
    positioning_by_strike,
)


def sample_chain():
    calls = pd.DataFrame(
        {
            "contractSymbol": ["C95", "C100", "C105"],
            "strike": [95, 100, 105],
            "bid": [7.0, 4.5, 2.2],
            "ask": [7.2, 4.7, 2.4],
            "volume": [10, 30, 100],
            "openInterest": [100, 300, 500],
            "iv": [.30, .29, .31],
            "delta_vendor": [.72, .51, .25],
            "gamma_vendor": [.02, .035, .025],
        }
    )
    puts = pd.DataFrame(
        {
            "contractSymbol": ["P95", "P100", "P105"],
            "strike": [95, 100, 105],
            "bid": [2.0, 4.2, 7.0],
            "ask": [2.2, 4.4, 7.2],
            "volume": [80, 25, 5],
            "openInterest": [600, 250, 50],
            "iv": [.36, .30, .32],
            "delta_vendor": [-.25, -.49, -.72],
            "gamma_vendor": [.026, .034, .021],
        }
    )
    return calls, puts


def test_positioning_keeps_oi_and_intraday_volume_distinct():
    calls, puts = sample_chain()
    result = positioning_by_strike(calls, puts, 100)
    at_95 = result[result["strike"] == 95].iloc[0]
    assert at_95["call_oi"] == 100
    assert at_95["put_oi"] == 600
    assert at_95["total_volume"] == 90
    assert abs(result["oi_share"].sum() - 1) < 1e-12


def test_delta_skew_defines_rr_and_butterfly_explicitly():
    calls, puts = sample_chain()
    result = delta_skew_snapshot(calls, puts, 100)
    assert abs(result["rr25"] - .05) < 1e-12
    assert result["bf25"] > 0


def test_gamma_default_is_unsigned_concentration():
    calls, puts = sample_chain()
    concentration = gamma_exposure_by_strike(calls, puts, 100, "concentration")
    signed = gamma_exposure_by_strike(calls, puts, 100, "calls_plus_puts_minus")
    assert (concentration["exposure"] >= 0).all()
    assert signed["exposure"].abs().sum() < concentration["exposure"].sum()


def test_export_package_contains_manifest_hashes_and_raw_artifacts():
    calls, puts = sample_chain()
    payload, manifest = build_export_package(
        "XYZ", "2026-08-21", {"atm_iv": .30}, calls, puts, pd.DataFrame(),
        pd.DataFrame(), pd.DataFrame(), {"provider": "fixture"}, {},
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
        names = set(bundle.namelist())
        assert "manifest.json" in names
        assert "options_calls.csv" in names
        assert "options_puts.csv" in names
        assert "analytics_summary.json" in names
    assert manifest["models"]["dealer_gamma"].startswith("not asserted")
    assert len(manifest["files"]["options_calls.csv"]["sha256"]) == 64

