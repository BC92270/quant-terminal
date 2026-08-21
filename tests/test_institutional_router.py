from urllib.parse import parse_qs, urlparse

import pandas as pd

from institutional_router import (
    CLIENT_PROFILES,
    Instrument,
    INSTRUMENTS,
    INSTRUMENT_BY_SYMBOL,
    UNIVERSES,
    WORKSPACE_BY_CODE,
    build_workspace_route,
    derive_market_signal,
    filter_security_master,
    normalize_workspace_codes,
    recommend_workspaces,
    search_instruments,
    workspace_context,
)


def _route_query(route: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(route).query)


def test_security_master_has_broad_institutional_coverage() -> None:
    assert len(INSTRUMENTS) >= 500
    assert len(UNIVERSES) >= 9
    assert {
        "Equities",
        "Indices",
        "ETFs",
        "FX",
        "Rates",
        "Credit",
        "Commodities",
        "Digital Assets",
        "Volatility",
    }.issubset(UNIVERSES)
    assert len({item.symbol for item in INSTRUMENTS}) == len(INSTRUMENTS)

    coverage = {universe: sum(item.universe == universe for item in INSTRUMENTS) for universe in UNIVERSES}
    assert coverage["Equities"] >= 175
    assert coverage["ETFs"] >= 85
    assert coverage["FX"] >= 45
    assert coverage["Rates"] >= 35
    assert coverage["Credit"] >= 30


def test_search_matches_symbol_name_region_and_tags() -> None:
    assert search_instruments("NVDA")[0].name == "NVIDIA"
    assert search_instruments("LVMH")[0].symbol == "MC.PA"
    assert any(item.symbol == "^N225" for item in search_instruments("Japan index"))
    assert all(item.universe == "Credit" for item in search_instruments("", universe="Credit", limit=None))


def test_security_master_combines_text_and_structured_filters() -> None:
    japan_banks = filter_security_master("banks", region="Japan", engine="Equity", limit=None)
    assert {item.symbol for item in japan_banks} >= {"MUFG", "SMFG", "8306.T"}
    assert all(item.region == "Japan" and item.engine_asset == "Equity" for item in japan_banks)

    uranium = filter_security_master("uranium", universe="Commodities", limit=None)
    assert [item.symbol for item in uranium] == ["URA"]
    assert filter_security_master("no-such-instrument", limit=None) == []


def test_provider_catalogue_can_extend_search_without_mutating_curated_seed() -> None:
    dynamic = Instrument(
        "NEWCO",
        "New Company Holdings",
        "Equities",
        "Equity",
        "United States",
        ("SEC filer",),
        "USD",
        "Nasdaq",
        "sec_edgar",
        "CIK 123456",
    )
    catalogue = (*INSTRUMENTS, dynamic)

    assert search_instruments("CIK 123456", catalogue=catalogue)[0] == dynamic
    assert filter_security_master("New Company", universe="Equities", catalogue=catalogue) == [dynamic]
    assert "NEWCO" not in INSTRUMENT_BY_SYMBOL


def test_standard_workspace_route_is_parallel_and_contextual() -> None:
    instrument = INSTRUMENT_BY_SYMBOL["EURUSD=X"]
    route = build_workspace_route("corr", instrument, period="2y", interval="1wk")
    query = _route_query(route)

    assert query == {
        "workspace": ["terminal"],
        "asset": ["FX"],
        "symbol": ["EURUSD=X"],
        "period": ["2y"],
        "interval": ["1wk"],
        "mode": ["Correlation Matrix"],
    }


def test_specialized_workspace_uses_its_required_market_context() -> None:
    equity = INSTRUMENT_BY_SYMBOL["NVDA"]
    assert workspace_context("rates", equity) == ("Rates", "^TNX")
    query = _route_query(build_workspace_route("credit", equity))
    assert query["asset"] == ["Rates"]
    assert query["symbol"] == ["LQD"]
    assert query["mode"] == ["Fixed Income & Credit Analytics"]


def test_autonomous_workspaces_have_allowlisted_routes() -> None:
    instrument = INSTRUMENT_BY_SYMBOL["SPY"]
    assert _route_query(build_workspace_route("worldmonitor", instrument)) == {"workspace": ["worldmonitor"]}
    assert _route_query(build_workspace_route("psychology", instrument)) == {"workspace": ["market-psychology"]}
    assert _route_query(build_workspace_route("quant_ai", instrument)) == {"workspace": ["quant-ai"]}


def test_client_profiles_reference_valid_bounded_workspaces() -> None:
    for profile in CLIENT_PROFILES.values():
        normalized = normalize_workspace_codes(profile.workspaces, profile.code)
        assert 1 <= len(normalized) <= 6
        assert set(normalized).issubset(WORKSPACE_BY_CODE)
        assert profile.default_symbol in INSTRUMENT_BY_SYMBOL


def test_desk_focus_combines_market_regime_with_client_profile() -> None:
    defensive = recommend_workspaces("wealth", {"bias": "DEFENSIVE"})
    assert defensive == ("risk", "portfolio", "macro")
    assert all(code in CLIENT_PROFILES["wealth"].workspaces for code in defensive)

    pro_risk = recommend_workspaces("equity", {"bias": "PRO-RISK"})
    assert pro_risk == ("momentum", "company", "options")
    assert len(recommend_workspaces("unknown", {"bias": "MIXED"})) == 3


def test_market_signal_fails_safe_and_detects_defensive_tape() -> None:
    assert derive_market_signal(pd.DataFrame())["bias"] == "DATA WAIT"

    tape = pd.DataFrame(
        [
            {"Symbol": "ES=F", "Change %": -0.012},
            {"Symbol": "NQ=F", "Change %": -0.018},
            {"Symbol": "RTY=F", "Change %": -0.020},
            {"Symbol": "^VIX", "Change %": 0.080},
            {"Symbol": "DX-Y.NYB", "Change %": 0.004},
            {"Symbol": "CL=F", "Change %": 0.015},
        ]
    )
    signal = derive_market_signal(tape)
    assert signal["bias"] == "DEFENSIVE"
    assert signal["confidence"] >= 50
