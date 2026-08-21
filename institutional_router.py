"""Institutional multi-asset workspace navigator.

This module owns the presentation and client-adaptation layer of the terminal
router.  It deliberately stays independent from the market engines: callers
provide the launch and snapshot functions, while the pure catalogue/search/
route helpers remain straightforward to test.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import os
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from institutional_catalog import EXPANDED_INSTRUMENT_ROWS
from security_master import (
    SecurityMasterStore,
    SecurityRecord,
    merge_security_records,
    provider_matrix,
    sync_nasdaq_symbol_directory,
    sync_sec_company_tickers,
)


@dataclass(frozen=True, slots=True)
class Instrument:
    symbol: str
    name: str
    universe: str
    engine_asset: str
    region: str
    tags: tuple[str, ...] = ()
    currency: str = ""
    exchange: str = ""
    source: str = "curated"
    reference_id: str = ""
    verified_at: str = ""

    @property
    def search_text(self) -> str:
        return " ".join(
            (
                self.symbol,
                self.name,
                self.universe,
                self.engine_asset,
                self.region,
                self.currency,
                self.exchange,
                self.source,
                self.reference_id,
                *self.tags,
            )
        ).casefold()


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    code: str
    function: str
    label: str
    description: str
    mode: str | None
    default_asset: str
    default_symbol: str
    audiences: tuple[str, ...]
    special_route: str | None = None
    force_context: bool = False


@dataclass(frozen=True, slots=True)
class ClientProfile:
    code: str
    label: str
    mandate: str
    default_universe: str
    default_symbol: str
    workspaces: tuple[str, ...]
    accent: str


def _instrument(
    symbol: str,
    name: str,
    universe: str,
    engine_asset: str,
    region: str,
    *tags: str,
) -> Instrument:
    return Instrument(symbol, name, universe, engine_asset, region, tuple(tags))


_CORE_INSTRUMENTS: tuple[Instrument, ...] = (
    # Equities — Americas
    _instrument("AAPL", "Apple", "Equities", "Equity", "United States", "technology", "mega cap"),
    _instrument("MSFT", "Microsoft", "Equities", "Equity", "United States", "technology", "cloud"),
    _instrument("NVDA", "NVIDIA", "Equities", "Equity", "United States", "semiconductors", "AI"),
    _instrument("AMZN", "Amazon", "Equities", "Equity", "United States", "consumer", "cloud"),
    _instrument("META", "Meta Platforms", "Equities", "Equity", "United States", "technology", "media"),
    _instrument("GOOGL", "Alphabet", "Equities", "Equity", "United States", "technology", "advertising"),
    _instrument("TSLA", "Tesla", "Equities", "Equity", "United States", "automotive", "growth"),
    _instrument("JPM", "JPMorgan Chase", "Equities", "Equity", "United States", "banks", "financials"),
    _instrument("BAC", "Bank of America", "Equities", "Equity", "United States", "banks", "financials"),
    _instrument("GS", "Goldman Sachs", "Equities", "Equity", "United States", "capital markets"),
    _instrument("XOM", "Exxon Mobil", "Equities", "Equity", "United States", "energy"),
    _instrument("CVX", "Chevron", "Equities", "Equity", "United States", "energy"),
    _instrument("LLY", "Eli Lilly", "Equities", "Equity", "United States", "healthcare"),
    _instrument("UNH", "UnitedHealth", "Equities", "Equity", "United States", "healthcare"),
    _instrument("WMT", "Walmart", "Equities", "Equity", "United States", "consumer staples"),
    _instrument("COST", "Costco", "Equities", "Equity", "United States", "consumer staples"),
    _instrument("CAT", "Caterpillar", "Equities", "Equity", "United States", "industrials"),
    _instrument("BA", "Boeing", "Equities", "Equity", "United States", "aerospace"),
    # Equities — Europe / Asia
    _instrument("SAP.DE", "SAP", "Equities", "Equity", "Germany", "software", "Europe"),
    _instrument("ASML.AS", "ASML", "Equities", "Equity", "Netherlands", "semiconductors", "Europe"),
    _instrument("MC.PA", "LVMH", "Equities", "Equity", "France", "luxury", "Europe"),
    _instrument("AIR.PA", "Airbus", "Equities", "Equity", "France", "aerospace", "Europe"),
    _instrument("OR.PA", "L'Oreal", "Equities", "Equity", "France", "consumer", "Europe"),
    _instrument("NESN.SW", "Nestle", "Equities", "Equity", "Switzerland", "consumer staples", "Europe"),
    _instrument("NOVO-B.CO", "Novo Nordisk", "Equities", "Equity", "Denmark", "healthcare", "Europe"),
    _instrument("SHEL.L", "Shell", "Equities", "Equity", "United Kingdom", "energy", "Europe"),
    _instrument("7203.T", "Toyota Motor", "Equities", "Equity", "Japan", "automotive", "Asia"),
    _instrument("9984.T", "SoftBank Group", "Equities", "Equity", "Japan", "technology", "Asia"),
    _instrument("005930.KS", "Samsung Electronics", "Equities", "Equity", "South Korea", "technology", "Asia"),
    _instrument("0700.HK", "Tencent", "Equities", "Equity", "Hong Kong", "technology", "Asia"),
    _instrument("TSM", "TSMC ADR", "Equities", "Equity", "Taiwan", "semiconductors", "Asia"),
    _instrument("BABA", "Alibaba ADR", "Equities", "Equity", "China", "consumer", "Asia"),
    # Indices
    _instrument("^GSPC", "S&P 500", "Indices", "Equity", "United States", "large cap"),
    _instrument("^NDX", "Nasdaq 100", "Indices", "Equity", "United States", "technology"),
    _instrument("^DJI", "Dow Jones Industrial Average", "Indices", "Equity", "United States", "blue chip"),
    _instrument("^RUT", "Russell 2000", "Indices", "Equity", "United States", "small cap"),
    _instrument("^STOXX50E", "Euro Stoxx 50", "Indices", "Equity", "Eurozone", "Europe"),
    _instrument("^FTSE", "FTSE 100", "Indices", "Equity", "United Kingdom", "Europe"),
    _instrument("^GDAXI", "DAX", "Indices", "Equity", "Germany", "Europe"),
    _instrument("^FCHI", "CAC 40", "Indices", "Equity", "France", "Europe"),
    _instrument("^N225", "Nikkei 225", "Indices", "Equity", "Japan", "Asia"),
    _instrument("^HSI", "Hang Seng", "Indices", "Equity", "Hong Kong", "Asia"),
    _instrument("^AXJO", "ASX 200", "Indices", "Equity", "Australia", "Asia Pacific"),
    # ETFs / allocation proxies
    _instrument("SPY", "SPDR S&P 500 ETF", "ETFs", "Equity", "United States", "core equity"),
    _instrument("QQQ", "Invesco QQQ", "ETFs", "Equity", "United States", "growth"),
    _instrument("IWM", "iShares Russell 2000", "ETFs", "Equity", "United States", "small cap"),
    _instrument("DIA", "SPDR Dow Jones", "ETFs", "Equity", "United States", "blue chip"),
    _instrument("EFA", "iShares MSCI EAFE", "ETFs", "Equity", "Developed Markets", "international"),
    _instrument("EEM", "iShares MSCI Emerging Markets", "ETFs", "Equity", "Emerging Markets", "international"),
    _instrument("VWO", "Vanguard Emerging Markets", "ETFs", "Equity", "Emerging Markets", "international"),
    _instrument("XLK", "US Technology Sector", "ETFs", "Equity", "United States", "sector"),
    _instrument("XLF", "US Financial Sector", "ETFs", "Equity", "United States", "sector"),
    _instrument("XLE", "US Energy Sector", "ETFs", "Equity", "United States", "sector"),
    _instrument("XLV", "US Healthcare Sector", "ETFs", "Equity", "United States", "sector"),
    _instrument("XLI", "US Industrials Sector", "ETFs", "Equity", "United States", "sector"),
    _instrument("VNQ", "US Real Estate ETF", "ETFs", "Equity", "United States", "real estate"),
    _instrument("PDBC", "Diversified Commodity Strategy", "ETFs", "Commodities", "Global", "alternatives"),
    _instrument("DBMF", "Managed Futures Strategy", "ETFs", "Equity", "Global", "alternatives"),
    # FX
    _instrument("EURUSD=X", "Euro / US Dollar", "FX", "FX", "G10", "major"),
    _instrument("GBPUSD=X", "British Pound / US Dollar", "FX", "FX", "G10", "major"),
    _instrument("USDJPY=X", "US Dollar / Japanese Yen", "FX", "FX", "G10", "major"),
    _instrument("USDCHF=X", "US Dollar / Swiss Franc", "FX", "FX", "G10", "major"),
    _instrument("AUDUSD=X", "Australian Dollar / US Dollar", "FX", "FX", "G10", "major"),
    _instrument("USDCAD=X", "US Dollar / Canadian Dollar", "FX", "FX", "G10", "major"),
    _instrument("NZDUSD=X", "New Zealand Dollar / US Dollar", "FX", "FX", "G10", "major"),
    _instrument("EURJPY=X", "Euro / Japanese Yen", "FX", "FX", "G10", "cross"),
    _instrument("EURGBP=X", "Euro / British Pound", "FX", "FX", "G10", "cross"),
    _instrument("EURCHF=X", "Euro / Swiss Franc", "FX", "FX", "G10", "cross"),
    _instrument("GBPJPY=X", "British Pound / Japanese Yen", "FX", "FX", "G10", "cross"),
    _instrument("USDNOK=X", "US Dollar / Norwegian Krone", "FX", "FX", "G10", "cross"),
    _instrument("USDSEK=X", "US Dollar / Swedish Krona", "FX", "FX", "G10", "cross"),
    _instrument("USDMXN=X", "US Dollar / Mexican Peso", "FX", "FX", "Emerging Markets", "carry"),
    _instrument("USDZAR=X", "US Dollar / South African Rand", "FX", "FX", "Emerging Markets", "carry"),
    _instrument("USDTRY=X", "US Dollar / Turkish Lira", "FX", "FX", "Emerging Markets", "carry"),
    _instrument("DX-Y.NYB", "US Dollar Index", "FX", "FX", "Global", "dollar basket"),
    # Rates
    _instrument("^IRX", "US 3M Treasury Yield", "Rates", "Rates", "United States", "sovereign", "front end"),
    _instrument("^FVX", "US 5Y Treasury Yield", "Rates", "Rates", "United States", "sovereign"),
    _instrument("^TNX", "US 10Y Treasury Yield", "Rates", "Rates", "United States", "sovereign", "benchmark"),
    _instrument("^TYX", "US 30Y Treasury Yield", "Rates", "Rates", "United States", "sovereign", "long end"),
    _instrument("ZT=F", "US 2Y Treasury Future", "Rates", "Rates", "United States", "future", "front end"),
    _instrument("ZF=F", "US 5Y Treasury Future", "Rates", "Rates", "United States", "future"),
    _instrument("ZN=F", "US 10Y Treasury Future", "Rates", "Rates", "United States", "future"),
    _instrument("ZB=F", "US 30Y Treasury Future", "Rates", "Rates", "United States", "future"),
    _instrument("UB=F", "US Ultra Bond Future", "Rates", "Rates", "United States", "future", "long end"),
    _instrument("SHY", "1-3Y US Treasury ETF", "Rates", "Rates", "United States", "duration"),
    _instrument("IEF", "7-10Y US Treasury ETF", "Rates", "Rates", "United States", "duration"),
    _instrument("TLT", "20Y+ US Treasury ETF", "Rates", "Rates", "United States", "duration"),
    _instrument("TIP", "US TIPS ETF", "Rates", "Rates", "United States", "inflation"),
    # Credit
    _instrument("LQD", "Investment Grade Credit ETF", "Credit", "Rates", "United States", "IG", "spread"),
    _instrument("HYG", "High Yield Credit ETF", "Credit", "Rates", "United States", "HY", "spread"),
    _instrument("JNK", "High Yield Bond ETF", "Credit", "Rates", "United States", "HY", "spread"),
    _instrument("VCIT", "Intermediate Corporate Bond ETF", "Credit", "Rates", "United States", "IG"),
    _instrument("VCSH", "Short Corporate Bond ETF", "Credit", "Rates", "United States", "IG", "short duration"),
    _instrument("EMB", "Emerging Markets Sovereign Bond ETF", "Credit", "Rates", "Emerging Markets", "sovereign"),
    _instrument("BKLN", "Senior Loan ETF", "Credit", "Rates", "United States", "loans", "floating rate"),
    _instrument("ANGL", "Fallen Angels High Yield ETF", "Credit", "Rates", "United States", "HY"),
    _instrument("FALN", "Fallen Angels USD Bond ETF", "Credit", "Rates", "United States", "HY"),
    # Commodities
    _instrument("CL=F", "WTI Crude Oil", "Commodities", "Commodities", "Global", "energy", "future"),
    _instrument("BZ=F", "Brent Crude Oil", "Commodities", "Commodities", "Global", "energy", "future"),
    _instrument("NG=F", "Natural Gas", "Commodities", "Commodities", "United States", "energy", "future"),
    _instrument("RB=F", "RBOB Gasoline", "Commodities", "Commodities", "United States", "energy", "future"),
    _instrument("HO=F", "Heating Oil", "Commodities", "Commodities", "United States", "energy", "future"),
    _instrument("GC=F", "Gold", "Commodities", "Commodities", "Global", "precious metals", "future"),
    _instrument("SI=F", "Silver", "Commodities", "Commodities", "Global", "precious metals", "future"),
    _instrument("HG=F", "Copper", "Commodities", "Commodities", "Global", "industrial metals", "future"),
    _instrument("PL=F", "Platinum", "Commodities", "Commodities", "Global", "precious metals", "future"),
    _instrument("PA=F", "Palladium", "Commodities", "Commodities", "Global", "precious metals", "future"),
    _instrument("ZC=F", "Corn", "Commodities", "Commodities", "Global", "agriculture", "future"),
    _instrument("ZS=F", "Soybeans", "Commodities", "Commodities", "Global", "agriculture", "future"),
    _instrument("ZW=F", "Wheat", "Commodities", "Commodities", "Global", "agriculture", "future"),
    _instrument("KC=F", "Coffee", "Commodities", "Commodities", "Global", "softs", "future"),
    _instrument("CC=F", "Cocoa", "Commodities", "Commodities", "Global", "softs", "future"),
    _instrument("CT=F", "Cotton", "Commodities", "Commodities", "Global", "softs", "future"),
    _instrument("SB=F", "Sugar", "Commodities", "Commodities", "Global", "softs", "future"),
    # Digital assets and volatility proxies
    _instrument("BTC-USD", "Bitcoin", "Digital Assets", "Equity", "Global", "crypto", "store of value"),
    _instrument("ETH-USD", "Ethereum", "Digital Assets", "Equity", "Global", "crypto", "smart contracts"),
    _instrument("SOL-USD", "Solana", "Digital Assets", "Equity", "Global", "crypto", "smart contracts"),
    _instrument("BNB-USD", "BNB", "Digital Assets", "Equity", "Global", "crypto"),
    _instrument("XRP-USD", "XRP", "Digital Assets", "Equity", "Global", "crypto", "payments"),
    _instrument("ADA-USD", "Cardano", "Digital Assets", "Equity", "Global", "crypto"),
    _instrument("AVAX-USD", "Avalanche", "Digital Assets", "Equity", "Global", "crypto"),
    _instrument("LINK-USD", "Chainlink", "Digital Assets", "Equity", "Global", "crypto", "oracle"),
    _instrument("^VIX", "Cboe Volatility Index", "Volatility", "Equity", "United States", "implied volatility"),
    _instrument("^VXN", "Nasdaq 100 Volatility Index", "Volatility", "Equity", "United States", "implied volatility"),
    _instrument("VXX", "Short-Term VIX Futures ETN", "Volatility", "Equity", "United States", "volatility ETP"),
    _instrument("UVXY", "Ultra VIX Short-Term Futures ETF", "Volatility", "Equity", "United States", "leveraged volatility"),
    _instrument("SVXY", "Short VIX Short-Term Futures ETF", "Volatility", "Equity", "United States", "short volatility"),
)


INSTRUMENTS: tuple[Instrument, ...] = _CORE_INSTRUMENTS + tuple(
    _instrument(symbol, name, universe, engine, region, *tags)
    for symbol, name, universe, engine, region, tags in EXPANDED_INSTRUMENT_ROWS
)


def _security_record(instrument: Instrument) -> SecurityRecord:
    return SecurityRecord(
        canonical_id=f"curated:{instrument.engine_asset.casefold()}:{instrument.symbol.casefold()}",
        symbol=instrument.symbol,
        name=instrument.name,
        universe=instrument.universe,
        engine_asset=instrument.engine_asset,
        region=instrument.region,
        currency=instrument.currency,
        exchange=instrument.exchange,
        source="curated",
        source_symbol=instrument.symbol,
        tags=instrument.tags,
        provider_symbols=(("router", instrument.symbol),),
        routeable=True,
        active=True,
    )


CURATED_SECURITY_RECORDS: tuple[SecurityRecord, ...] = tuple(
    _security_record(instrument) for instrument in INSTRUMENTS
)


def _record_to_instrument(record: SecurityRecord) -> Instrument:
    reference_id = record.figi or (f"CIK {record.cik}" if record.cik else "")
    return Instrument(
        symbol=record.symbol,
        name=record.name,
        universe=record.universe,
        engine_asset=record.engine_asset,
        region=record.region,
        tags=record.tags,
        currency=record.currency,
        exchange=record.exchange,
        source=record.source,
        reference_id=reference_id,
        verified_at=record.last_verified_at,
    )


def _security_master_path() -> str:
    return os.getenv("SECURITY_MASTER_DB_PATH", ".quant_data/security_master.sqlite3").strip()


@st.cache_data(ttl=900, show_spinner=False)
def load_runtime_security_master() -> tuple[tuple[Instrument, ...], dict[str, Any]]:
    """Load curated and provider records, refreshing public directories when stale."""
    store = SecurityMasterStore(_security_master_path())
    store.upsert_records(CURATED_SECURITY_RECORDS)
    sync_results = []
    auto_sync = os.getenv("SECURITY_MASTER_AUTO_SYNC", "1").strip().casefold() not in {"0", "false", "off", "no"}
    if auto_sync and store.source_needs_refresh("nasdaq_directory"):
        sync_results.append(sync_nasdaq_symbol_directory(store))
    if auto_sync and os.getenv("SEC_USER_AGENT", "").strip() and store.source_needs_refresh("sec_edgar"):
        sync_results.append(sync_sec_company_tickers(store))

    records = merge_security_records(store.all_records())
    instruments = tuple(_record_to_instrument(record) for record in records if record.routeable)
    health = store.health()
    latest_sec = store.latest_sync("sec_edgar")
    latest_nasdaq = store.latest_sync("nasdaq_directory")
    health.update(
        {
            "canonical_records": len(records),
            "routeable_records": len(instruments),
            "latest_sec_sync": latest_sec,
            "latest_nasdaq_sync": latest_nasdaq,
            "sync_results": tuple(sync_results),
            "provider_matrix": provider_matrix(),
        }
    )
    return instruments or INSTRUMENTS, health


def refresh_runtime_security_master() -> tuple[Any, ...]:
    """Force auditable reference-source refreshes and invalidate the cache."""
    store = SecurityMasterStore(_security_master_path())
    results = [sync_nasdaq_symbol_directory(store)]
    if os.getenv("SEC_USER_AGENT", "").strip():
        results.append(sync_sec_company_tickers(store))
    load_runtime_security_master.clear()
    return tuple(results)


WORKSPACES: tuple[WorkspaceSpec, ...] = (
    WorkspaceSpec("corr", "CORR", "Cross-Asset Correlation", "Dependencies, regimes and diversification breaks.", "Correlation Matrix", "Equity", "SPY", ("multi_asset", "macro", "risk", "cio")),
    WorkspaceSpec("portfolio", "PORT", "Portfolio Lab", "Allocation, optimization, attribution and portfolio construction.", "Portfolio Lab", "Equity", "SPY", ("multi_asset", "risk", "cio", "wealth")),
    WorkspaceSpec("risk", "RISK", "Risk Monitor", "Volatility, drawdown, exposure and stress surveillance.", "Risk Monitor", "Equity", "SPY", ("multi_asset", "risk", "cio", "wealth")),
    WorkspaceSpec("backtest", "BT", "Backtest Lab", "Research hypotheses with controlled historical validation.", "Backtest Lab", "Equity", "SPY", ("multi_asset", "equity", "macro", "risk")),
    WorkspaceSpec("momentum", "MOM", "Momentum / Trend", "Trend state, breadth and momentum diagnostics.", "Momentum / Trend", "Equity", "SPY", ("multi_asset", "equity", "macro")),
    WorkspaceSpec("monte_carlo", "MC", "Monte Carlo Advanced", "Path simulation, scenario distributions and tail outcomes.", "Monte Carlo Advanced", "Equity", "SPY", ("multi_asset", "risk", "equity")),
    WorkspaceSpec("company", "COMP", "Company Intelligence", "Fundamentals, valuation, management and catalysts.", "Company Intelligence", "Equity", "NVDA", ("equity", "cio", "wealth"), force_context=True),
    WorkspaceSpec("options", "OMON", "Options / Futures", "Derivatives surfaces, structures and execution context.", "Options / Futures", "Equity", "SPY", ("equity", "macro", "risk")),
    WorkspaceSpec("decision", "DCSN", "Decision Engine", "Evidence synthesis and auditable decision framing.", "Decision Engine", "Equity", "SPY", ("multi_asset", "equity", "cio", "wealth")),
    WorkspaceSpec("ml", "BQLAB", "ML Research Lab", "Feature research and model diagnostics.", "ML Research Lab", "Equity", "SPY", ("multi_asset", "equity")),
    WorkspaceSpec("fx", "FXGO", "FX Dashboard", "Majors, crosses, dollar regime and relative momentum.", "FX Dashboard", "FX", "EURUSD=X", ("macro", "multi_asset"), force_context=True),
    WorkspaceSpec("commodities", "CMDTY", "Commodity Dashboard", "Energy, metals, agriculture and inflation transmission.", "Commodity Dashboard", "Commodities", "GC=F", ("macro", "multi_asset"), force_context=True),
    WorkspaceSpec("rates", "GOVT", "Rates Dashboard", "Sovereign curves, duration and policy repricing.", "Rates Dashboard", "Rates", "^TNX", ("macro", "risk", "multi_asset"), force_context=True),
    WorkspaceSpec("credit", "CRPR", "Fixed Income & Credit", "Curve, spread, DV01, CS01 and relative-value analytics.", "Fixed Income & Credit Analytics", "Rates", "LQD", ("macro", "risk", "cio", "wealth"), force_context=True),
    WorkspaceSpec("macro", "ECON", "Macro / Central Banks", "Growth, inflation, liquidity and policy regime.", "Macro / Central Banks", "Equity", "SPY", ("macro", "multi_asset", "cio"), force_context=True),
    WorkspaceSpec("psychology", "PSYC", "Market Psychology", "Narratives, positioning, reflexivity and behavioral state.", None, "Equity", "SPY", ("multi_asset", "equity", "cio"), special_route="market-psychology"),
    WorkspaceSpec("quant_ai", "ASKQ", "Quant AI · CIO", "Cross-domain research assistant and investment committee.", None, "Equity", "SPY", ("multi_asset", "equity", "macro", "risk", "cio", "wealth"), special_route="quant-ai"),
    WorkspaceSpec("worldmonitor", "WMRD", "WorldMonitor", "Geopolitical events, transmission channels and scenarios.", None, "Equity", "SPY", ("macro", "multi_asset", "cio"), special_route="worldmonitor"),
)


CLIENT_PROFILES: dict[str, ClientProfile] = {
    "multi_asset": ClientProfile(
        "multi_asset", "Multi-Asset PM", "Allocation, cross-asset signals and portfolio construction", "ETFs", "SPY",
        ("corr", "portfolio", "risk", "macro", "momentum", "quant_ai"), "#ff9f1a",
    ),
    "equity": ClientProfile(
        "equity", "Equity / Options", "Single-name research, catalysts, derivatives and execution", "Equities", "NVDA",
        ("company", "options", "momentum", "backtest", "risk", "decision"), "#39d0ff",
    ),
    "macro": ClientProfile(
        "macro", "Global Macro", "Rates, FX, commodities, policy and geopolitical transmission", "Rates", "^TNX",
        ("macro", "rates", "fx", "commodities", "worldmonitor", "corr"), "#ffd166",
    ),
    "risk": ClientProfile(
        "risk", "Risk & Allocation", "Exposure, stress, tails, liquidity and portfolio resilience", "ETFs", "SPY",
        ("risk", "portfolio", "monte_carlo", "corr", "credit", "quant_ai"), "#ff6577",
    ),
    "cio": ClientProfile(
        "cio", "CIO / Investment Committee", "Decision-ready synthesis across markets, portfolios and scenarios", "Indices", "^GSPC",
        ("quant_ai", "portfolio", "macro", "risk", "worldmonitor", "decision"), "#b98cff",
    ),
    "wealth": ClientProfile(
        "wealth", "Private Wealth / Advisory", "Client portfolios, risk framing, companies and macro context", "ETFs", "SPY",
        ("portfolio", "risk", "company", "decision", "macro", "quant_ai"), "#4ce6b3",
    ),
}


WORKSPACE_BY_CODE = {workspace.code: workspace for workspace in WORKSPACES}
INSTRUMENT_BY_SYMBOL = {instrument.symbol: instrument for instrument in INSTRUMENTS}
UNIVERSES = tuple(dict.fromkeys(instrument.universe for instrument in INSTRUMENTS))


def search_instruments(
    query: str = "",
    universe: str | None = None,
    limit: int | None = 24,
    *,
    catalogue: Sequence[Instrument] | None = None,
) -> list[Instrument]:
    """Return deterministic catalogue matches ranked by symbol then metadata."""
    source = INSTRUMENTS if catalogue is None else catalogue
    candidates = [
        instrument
        for instrument in source
        if universe in (None, "All") or instrument.universe == universe
    ]
    tokens = [token.casefold() for token in str(query or "").split() if token.strip()]
    aliases = {
        "index": ("index", "indices"),
        "indexes": ("index", "indices"),
        "stock": ("stock", "equity", "equities"),
        "stocks": ("stock", "equity", "equities"),
        "bond": ("bond", "rates", "credit", "sovereign"),
        "bonds": ("bond", "rates", "credit", "sovereign"),
        "crypto": ("crypto", "digital assets"),
    }

    def token_matches(instrument: Instrument, token: str) -> bool:
        return any(candidate in instrument.search_text for candidate in aliases.get(token, (token,)))

    if not tokens:
        matches = candidates
    else:
        matches = [instrument for instrument in candidates if all(token_matches(instrument, token) for token in tokens)]

    query_key = str(query or "").strip().casefold()
    matches.sort(
        key=lambda instrument: (
            0 if instrument.symbol.casefold() == query_key else 1,
            0 if instrument.symbol.casefold().startswith(query_key) else 1,
            instrument.universe,
            instrument.symbol,
        )
    )
    return matches if limit is None else matches[: max(int(limit), 0)]


def filter_security_master(
    query: str = "",
    *,
    universe: str = "ALL",
    region: str = "ALL",
    engine: str = "ALL",
    limit: int | None = 80,
    catalogue: Sequence[Instrument] | None = None,
) -> list[Instrument]:
    """Filter the global catalogue without coupling it to widget state."""
    matches = search_instruments(query, universe=None, limit=None, catalogue=catalogue)
    if universe != "ALL":
        matches = [item for item in matches if item.universe == universe]
    if region != "ALL":
        matches = [item for item in matches if item.region == region]
    if engine != "ALL":
        matches = [item for item in matches if item.engine_asset == engine]
    return matches if limit is None else matches[: max(int(limit), 0)]


def workspace_context(workspace_code: str, instrument: Instrument) -> tuple[str, str]:
    workspace = WORKSPACE_BY_CODE[workspace_code]
    if workspace.force_context:
        return workspace.default_asset, workspace.default_symbol
    return instrument.engine_asset, instrument.symbol


def build_workspace_route(
    workspace_code: str,
    instrument: Instrument,
    period: str = "1y",
    interval: str = "1d",
) -> str:
    """Build a non-sensitive relative route suitable for a parallel browser tab."""
    workspace = WORKSPACE_BY_CODE[workspace_code]
    if workspace.special_route:
        return "?" + urlencode({"workspace": workspace.special_route})

    asset, symbol = workspace_context(workspace_code, instrument)
    return "?" + urlencode(
        {
            "workspace": "terminal",
            "asset": asset,
            "symbol": symbol,
            "period": period,
            "interval": interval,
            "mode": workspace.mode or "Correlation Matrix",
        }
    )


def normalize_workspace_codes(
    codes: Iterable[str],
    profile_code: str = "multi_asset",
    limit: int = 6,
) -> tuple[str, ...]:
    valid: list[str] = []
    for code in codes:
        code = str(code)
        if code in WORKSPACE_BY_CODE and code not in valid:
            valid.append(code)
    if not valid:
        valid = list(CLIENT_PROFILES[profile_code].workspaces)
    return tuple(valid[: max(1, int(limit))])


def derive_market_signal(tape_df: pd.DataFrame) -> dict[str, Any]:
    """Small fail-safe cross-asset read for the navigator header."""
    if tape_df is None or not isinstance(tape_df, pd.DataFrame) or tape_df.empty:
        return {"bias": "DATA WAIT", "confidence": 0, "tone": "neutral", "detail": "Market pulse unavailable"}

    def change(symbol: str) -> float | None:
        try:
            value = tape_df.loc[tape_df["Symbol"] == symbol, "Change %"].iloc[0]
            value = float(value)
            return value if pd.notna(value) else None
        except Exception:
            return None

    equity_values = [change("ES=F"), change("NQ=F"), change("RTY=F")]
    equity_values = [value for value in equity_values if value is not None]
    equity = sum(equity_values) / len(equity_values) if equity_values else 0.0
    volatility = change("^VIX") or 0.0
    dollar = change("DX-Y.NYB") or 0.0
    oil = change("CL=F") or 0.0
    risk_score = (-equity * 42.0) + (volatility * 9.0) + (max(dollar, 0.0) * 7.0)

    if risk_score >= 0.35:
        bias, tone = "DEFENSIVE", "negative"
    elif risk_score <= -0.20:
        bias, tone = "PRO-RISK", "positive"
    else:
        bias, tone = "MIXED", "warning"

    confidence = min(95, max(38, int(45 + abs(risk_score) * 18)))
    detail = f"Equity {equity:+.2%} · VIX {volatility:+.2%} · USD {dollar:+.2%} · Oil {oil:+.2%}"
    return {"bias": bias, "confidence": confidence, "tone": tone, "detail": detail}


def recommend_workspaces(profile_code: str, market_signal: Mapping[str, Any]) -> tuple[str, ...]:
    """Prioritize three profile-relevant functions for the current tape."""
    profile = CLIENT_PROFILES.get(profile_code, CLIENT_PROFILES["multi_asset"])
    regime = str(market_signal.get("bias", "MIXED")).upper()
    priorities = {
        "DEFENSIVE": ("risk", "portfolio", "macro", "credit"),
        "PRO-RISK": ("momentum", "company", "options", "portfolio"),
        "MIXED": ("corr", "decision", "quant_ai", "risk"),
        "DATA WAIT": ("quant_ai", "worldmonitor", "corr"),
    }.get(regime, ("corr", "decision", "risk"))

    profile_matches = [code for code in priorities if code in profile.workspaces]
    candidates = (*profile_matches, *profile.workspaces, *priorities)
    return normalize_workspace_codes(candidates, profile.code, limit=3)


def _inject_router_css(accent: str) -> None:
    safe_accent = escape(accent)
    st.markdown(
        f"""
        <style>
        :root {{ --ir-accent:{safe_accent}; --ir-amber:#ff9f1a; --ir-cyan:#3bd6ff; }}
        .block-container {{ max-width:1540px; padding-top:.65rem !important; padding-bottom:3rem; }}
        [data-testid="stAppViewContainer"] {{ background:#02070b; }}
        .ir-shell {{ font-family:"IBM Plex Mono","SFMono-Regular",Consolas,monospace; color:#e7eef4; }}
        .ir-topline {{ display:flex; justify-content:space-between; gap:18px; align-items:flex-end;
            border-top:2px solid var(--ir-amber); border-bottom:1px solid #28323a; padding:10px 0 9px; margin-bottom:10px; }}
        .ir-brand {{ color:var(--ir-amber); font-size:.78rem; font-weight:900; letter-spacing:.13em; }}
        .ir-title {{ color:#f4f7f9; font-size:1.52rem; font-weight:850; letter-spacing:-.035em; margin-top:2px; }}
        .ir-clock {{ color:#8e9aa3; font-size:.68rem; text-align:right; line-height:1.5; }}
        .ir-function-rail {{ display:flex; gap:4px; flex-wrap:wrap; margin:0 0 11px; }}
        .ir-key {{ border:1px solid #333d45; background:#0a1116; padding:5px 8px; color:#b7c2ca; font-size:.63rem; }}
        .ir-key b {{ color:var(--ir-amber); margin-right:5px; }}
        .ir-context {{ border-left:3px solid var(--ir-accent); background:#071018; padding:9px 12px; margin:8px 0 10px; }}
        .ir-context-label {{ color:var(--ir-accent); font-size:.68rem; font-weight:900; letter-spacing:.12em; }}
        .ir-context-text {{ color:#c5d0d8; font-size:.72rem; margin-top:3px; }}
        .ir-section {{ margin:16px 0 7px; padding-bottom:5px; border-bottom:1px solid #263039; display:flex; justify-content:space-between; gap:12px; }}
        .ir-section-title {{ color:var(--ir-amber); font-size:.72rem; font-weight:900; letter-spacing:.13em; }}
        .ir-section-meta {{ color:#66747e; font-size:.65rem; }}
        .ir-pulse {{ display:grid; grid-template-columns:repeat(8,minmax(0,1fr)); border:1px solid #263039; background:#050b10; }}
        .ir-pulse-cell {{ padding:8px 10px; border-right:1px solid #202a31; min-height:62px; }}
        .ir-pulse-name {{ color:#7d8b95; font-size:.60rem; letter-spacing:.08em; }}
        .ir-pulse-last {{ color:#f2f5f7; font-size:.86rem; font-weight:800; margin-top:4px; }}
        .ir-up {{ color:#32df9e; }} .ir-down {{ color:#ff5d73; }} .ir-flat {{ color:#f2c14e; }}
        .ir-signal {{ display:grid; grid-template-columns:minmax(150px,.7fr) 2fr auto; border:1px solid #29343c; margin-top:6px; }}
        .ir-signal-bias {{ padding:10px 12px; background:#0a1218; color:var(--ir-accent); font-size:.82rem; font-weight:900; }}
        .ir-signal-detail {{ padding:10px 12px; color:#9dabb4; font-size:.68rem; }}
        .ir-signal-focus {{ padding:10px 12px; border-left:1px solid #27323a; color:#cbd6dd; font-size:.66rem; white-space:nowrap; }}
        .ir-signal-focus b {{ color:var(--ir-amber); margin-right:7px; }}
        .ir-grid {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; margin-top:7px; }}
        .ir-card {{ display:flex; flex-direction:column; min-height:154px; border:1px solid #2b353c; background:#060c11; padding:11px 12px; text-decoration:none !important; transition:.12s ease; }}
        .ir-card:hover {{ border-color:var(--ir-amber); background:#0b1217; transform:translateY(-1px); }}
        .ir-card-code {{ color:var(--ir-amber); font-size:.64rem; font-weight:900; letter-spacing:.12em; }}
        .ir-card-title {{ color:#edf2f5; font-size:.83rem; font-weight:800; margin-top:8px; }}
        .ir-card-copy {{ color:#96a4ad; font-size:.69rem; line-height:1.48; margin-top:5px; flex:1; }}
        .ir-card-route {{ display:flex; justify-content:space-between; gap:10px; color:#5fd6f5; font-size:.62rem; margin-top:11px; padding-top:7px; border-top:1px solid #202930; }}
        .ir-master-banner {{ display:grid; grid-template-columns:minmax(280px,1.25fr) 2fr; border:1px solid #303b43; background:linear-gradient(105deg,#0b1218 0%,#050b10 62%); margin-top:7px; }}
        .ir-master-identity {{ display:flex; align-items:center; gap:13px; padding:13px 15px; border-right:1px solid #2a343c; }}
        .ir-master-code {{ background:var(--ir-amber); color:#080a0b; padding:8px 9px; font-size:.72rem; font-weight:950; letter-spacing:.07em; white-space:nowrap; }}
        .ir-master-title {{ color:#f2f5f7; font-size:.86rem; font-weight:850; }}
        .ir-master-subtitle {{ color:#7f8d96; font-size:.64rem; margin-top:3px; }}
        .ir-master-kpis {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); }}
        .ir-master-kpi {{ padding:10px 12px; border-right:1px solid #232d34; }}
        .ir-master-kpi-label {{ color:#697983; font-size:.57rem; letter-spacing:.10em; }}
        .ir-master-kpi-value {{ color:#e7edf1; font-size:.92rem; font-weight:900; margin-top:4px; }}
        .ir-master-kpi-value.live {{ color:#36d99b; }}
        .ir-universe-grid {{ display:grid; grid-template-columns:repeat(9,minmax(0,1fr)); gap:5px; margin:6px 0 10px; }}
        .ir-universe {{ border:1px solid #273139; padding:8px 9px 9px; background:#060c11; }}
        .ir-universe-top {{ display:flex; align-items:center; justify-content:space-between; gap:5px; }}
        .ir-universe-name {{ color:#aebac2; font-size:.59rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
        .ir-universe-count {{ color:var(--ir-amber); font-size:.78rem; font-weight:900; }}
        .ir-universe-track {{ height:2px; background:#1d272e; margin-top:7px; }}
        .ir-universe-fill {{ height:100%; background:linear-gradient(90deg,var(--ir-amber),#ffd166); }}
        .ir-provider-strip {{ display:flex; flex-wrap:wrap; gap:0; margin:-4px 0 10px; border:1px solid #273139; background:#071017; }}
        .ir-provider-strip span {{ flex:1 1 260px; padding:7px 10px; border-right:1px solid #273139; color:#82919a; font-size:.59rem; }}
        .ir-provider-strip b {{ color:#52d8f5; margin-right:6px; letter-spacing:.08em; }}
        .ir-directory-status {{ display:flex; justify-content:space-between; gap:12px; align-items:center; border:1px solid #29343c; border-bottom:0; background:#0a1116; padding:7px 10px; color:#7f8d96; font-size:.62rem; }}
        .ir-directory-status b {{ color:#dbe4e9; }}
        .ir-directory-status .live {{ color:#35dc9c; font-weight:900; }}
        .ir-directory {{ max-height:620px; overflow:auto; border:1px solid #29343c; background:#050b10; scrollbar-color:#41515b #0a1116; }}
        .ir-directory-row {{ display:grid; grid-template-columns:minmax(86px,.65fr) minmax(220px,1.8fr) minmax(125px,.95fr) minmax(125px,1fr) minmax(165px,1.2fr) 78px; }}
        .ir-directory-row > span {{ min-width:0; padding:8px 10px; border-right:1px solid #222c33; border-bottom:1px solid #202a31; color:#aebbc3; font-size:.67rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
        .ir-directory-row:nth-child(even) {{ background:#071017; }}
        .ir-directory-row:hover:not(.ir-directory-head) {{ background:#0c171e; box-shadow:inset 2px 0 0 var(--ir-amber); }}
        .ir-directory-code {{ color:#f3f6f8 !important; font-weight:900; letter-spacing:.02em; }}
        .ir-directory-name {{ color:#dbe3e8 !important; font-weight:700; }}
        .ir-directory-descriptor {{ color:#71818b !important; }}
        .ir-directory-route {{ text-align:right; }}
        .ir-directory-route a {{ color:#52d8f5 !important; text-decoration:none !important; font-weight:850; }}
        .ir-directory-route a:hover {{ color:var(--ir-amber) !important; }}
        .ir-directory-head {{ position:sticky; top:0; z-index:2; background:#121a20 !important; box-shadow:0 1px 0 #33414a; }}
        .ir-directory-head > span {{ color:#ffb347; font-size:.59rem; font-weight:900; letter-spacing:.09em; }}
        .ir-directory-empty {{ padding:18px; color:#7f8c95; font-size:.72rem; }}
        .ir-footnote {{ color:#64717a; font-size:.64rem; padding:10px 0 0; }}
        div[data-testid="stForm"] {{ border:1px solid #2a343c; border-radius:0; background:#050b10; padding:10px 12px 2px; }}
        div[data-baseweb="select"] > div, .stTextInput input {{ border-radius:0 !important; background:#071017 !important; border-color:#303b43 !important; font-family:"IBM Plex Mono",monospace !important; }}
        .stButton button, .stFormSubmitButton button {{ border-radius:0 !important; font-family:"IBM Plex Mono",monospace !important; font-weight:850 !important; letter-spacing:.05em; }}
        div[data-testid="stFormSubmitButton"] button[kind="primaryFormSubmit"] {{ background:var(--ir-amber) !important; color:#090b0c !important; border-color:var(--ir-amber) !important; box-shadow:none !important; }}
        div[data-testid="stFormSubmitButton"] button[kind="secondaryFormSubmit"] {{ background:#101820 !important; color:#dbe4e9 !important; border-color:#40505b !important; box-shadow:none !important; }}
        div[data-testid="stFormSubmitButton"] button[kind="secondaryFormSubmit"]:hover {{ border-color:var(--ir-amber) !important; color:var(--ir-amber) !important; }}
        .stDownloadButton button {{ border-radius:0 !important; background:#101820 !important; color:#dbe4e9 !important; border-color:#40505b !important; font-family:"IBM Plex Mono",monospace !important; }}
        .st-key-router_directory_apply button {{ border-radius:0 !important; background:var(--ir-amber) !important; color:#090b0c !important; border-color:var(--ir-amber) !important; font-family:"IBM Plex Mono",monospace !important; font-weight:850 !important; }}
        .st-key-router_directory_reset button {{ border-radius:0 !important; background:#101820 !important; color:#96a5ae !important; border-color:#40505b !important; font-family:"IBM Plex Mono",monospace !important; }}
        .st-key-router_directory_sync button {{ border-radius:0 !important; background:#0b1b22 !important; color:#52d8f5 !important; border-color:#315567 !important; font-family:"IBM Plex Mono",monospace !important; }}
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] {{ background:#152129 !important; border:1px solid #34434d !important; color:#d6e0e6 !important; }}
        div[data-testid="stMultiSelect"] [data-baseweb="tag"] svg {{ fill:#7f929e !important; }}
        @media (min-width:1450px) {{ .ir-grid {{ grid-template-columns:repeat(6,minmax(0,1fr)); }} }}
        @media (max-width:1200px) {{ .ir-pulse {{ grid-template-columns:repeat(4,minmax(0,1fr)); }} }}
        @media (max-width:1000px) {{
            .st-key-router_profile_context [data-testid="stHorizontalBlock"],
            .st-key-router_security_filters [data-testid="stHorizontalBlock"],
            div[data-testid="stForm"] [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; }}
            .st-key-router_profile_context [data-testid="stColumn"] {{ flex:1 1 280px !important; width:auto !important; min-width:280px !important; }}
            .st-key-router_security_filters [data-testid="stColumn"] {{ flex:1 1 180px !important; width:auto !important; min-width:180px !important; }}
            div[data-testid="stForm"] [data-testid="stColumn"] {{ flex:1 1 210px !important; width:auto !important; min-width:210px !important; }}
            .ir-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
            .ir-master-banner {{ grid-template-columns:1fr; }}
            .ir-master-identity {{ border-right:0; border-bottom:1px solid #2a343c; }}
            .ir-universe-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }}
            .ir-directory-row {{ grid-template-columns:82px minmax(180px,1.5fr) minmax(100px,.9fr) minmax(94px,.8fr) minmax(100px,1fr) 82px; }}
        }}
        @media (max-width:760px) {{
            .ir-topline {{ align-items:flex-start; }} .ir-title {{ font-size:1.18rem; }}
            .ir-clock {{ display:none; }} .ir-signal {{ grid-template-columns:1fr; }}
            .ir-signal-focus {{ border-left:0; border-top:1px solid #27323a; white-space:normal; }}
            .ir-master-kpis {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
            .ir-master-kpi {{ border-bottom:1px solid #232d34; }}
            .ir-provider-strip {{ flex-direction:column; }}
            .ir-provider-strip span {{ flex-basis:auto; border-right:0; border-bottom:1px solid #273139; }}
            .ir-directory-status {{ align-items:flex-start; flex-direction:column; gap:3px; }}
            .ir-directory-row {{ grid-template-columns:74px minmax(0,1fr) 68px; }}
            .ir-directory-row > span:nth-child(3), .ir-directory-row > span:nth-child(4), .ir-directory-row > span:nth-child(5) {{ display:none; }}
            .ir-universe-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
            .ir-universe:last-child:nth-child(odd) {{ grid-column:1 / -1; }}
        }}
        @media (max-width:600px) {{
            .ir-pulse {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
            .ir-grid {{ grid-template-columns:1fr; }}
            div[data-testid="stForm"] [data-testid="stColumn"] {{ flex:1 1 100% !important; min-width:100% !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _format_instrument(instrument: Instrument) -> str:
    return f"{instrument.symbol:<12} {instrument.name} · {instrument.region}"


def _format_last(value: Any, symbol: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if symbol.endswith("=X"):
        return f"{number:,.5f}"
    if abs(number) < 10:
        return f"{number:,.4f}"
    return f"{number:,.2f}"


def _render_market_pulse(
    snapshot_loader: Callable[[tuple[str, ...]], pd.DataFrame] | None,
    profile_code: str,
) -> None:
    pulse_symbols = ("ES=F", "NQ=F", "^VIX", "DX-Y.NYB", "^TNX", "CL=F", "GC=F", "EURUSD=X")
    try:
        tape = snapshot_loader(pulse_symbols) if callable(snapshot_loader) else pd.DataFrame()
    except Exception:
        tape = pd.DataFrame()

    lookup: dict[str, Mapping[str, Any]] = {}
    if isinstance(tape, pd.DataFrame) and not tape.empty and "Symbol" in tape.columns:
        lookup = {str(row.get("Symbol")): row for _, row in tape.iterrows()}

    labels = {
        "ES=F": "S&P FUT", "NQ=F": "NASDAQ FUT", "^VIX": "VIX", "DX-Y.NYB": "DXY",
        "^TNX": "US 10Y", "CL=F": "WTI", "GC=F": "GOLD", "EURUSD=X": "EUR/USD",
    }
    cells: list[str] = []
    for symbol in pulse_symbols:
        row = lookup.get(symbol, {})
        last = _format_last(row.get("Last"), symbol)
        try:
            move = float(row.get("Change %"))
            move_class = "ir-up" if move > 0 else "ir-down" if move < 0 else "ir-flat"
            move_text = f"{move:+.2%}"
        except (TypeError, ValueError):
            move_class, move_text = "ir-flat", "WAIT"
        cells.append(
            f'<div class="ir-pulse-cell"><div class="ir-pulse-name">{labels[symbol]}</div>'
            f'<div class="ir-pulse-last">{last}</div><div class="{move_class}" style="font-size:.64rem">{move_text}</div></div>'
        )
    st.markdown('<div class="ir-pulse">' + "".join(cells) + "</div>", unsafe_allow_html=True)

    signal = derive_market_signal(tape)
    tone_class = {"positive": "ir-up", "negative": "ir-down", "warning": "ir-flat"}.get(signal["tone"], "ir-flat")
    recommended = recommend_workspaces(profile_code, signal)
    focus = " · ".join(WORKSPACE_BY_CODE[code].function for code in recommended)
    st.markdown(
        f'<div class="ir-signal"><div class="ir-signal-bias {tone_class}">{escape(signal["bias"])} · {signal["confidence"]}%</div>'
        f'<div class="ir-signal-detail">{escape(signal["detail"])}</div>'
        f'<div class="ir-signal-focus"><b>DESK FOCUS</b>{escape(focus)}</div></div>',
        unsafe_allow_html=True,
    )


def _launch_special(route: str) -> None:
    st.session_state["asset_class_selected"] = True
    st.session_state["terminal_entered"] = True
    st.session_state["worldmonitor_v211_open"] = route == "worldmonitor"
    st.session_state["market_psychology_lab_open"] = route == "market-psychology"
    st.session_state["quant_ai_open"] = route == "quant-ai"
    st.query_params.clear()
    st.query_params["workspace"] = route
    st.rerun()


def _render_workspace_grid(codes: Sequence[str], instrument: Instrument, period: str, interval: str) -> None:
    cards: list[str] = []
    for code in codes:
        workspace = WORKSPACE_BY_CODE[code]
        asset, symbol = workspace_context(code, instrument)
        route = build_workspace_route(code, instrument, period, interval)
        cards.append(
            f'<a class="ir-card" href="{escape(route, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'<div class="ir-card-code">{escape(workspace.function)} &lt;GO&gt;</div>'
            f'<div class="ir-card-title">{escape(workspace.label)}</div>'
            f'<div class="ir-card-copy">{escape(workspace.description)}</div>'
            f'<div class="ir-card-route"><span>{escape(asset)} · {escape(symbol)}</span><span>OPEN ↗</span></div></a>'
        )
    st.markdown('<div class="ir-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def _directory_frame(instruments: Sequence[Instrument]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Code": instrument.symbol,
                "Instrument": instrument.name,
                "Universe": instrument.universe,
                "Region": instrument.region,
                "Engine": instrument.engine_asset,
                "Descriptor": " | ".join(instrument.tags),
                "Currency": instrument.currency,
                "Exchange": instrument.exchange,
                "Source": instrument.source,
                "Reference ID": instrument.reference_id,
                "Verified At": instrument.verified_at,
            }
            for instrument in instruments
        ]
    )


def _render_security_directory(
    instruments: Sequence[Instrument],
    period: str,
    interval: str,
) -> None:
    if not instruments:
        st.markdown('<div class="ir-directory"><div class="ir-directory-empty">NO MATCHING SECURITY</div></div>', unsafe_allow_html=True)
        return

    rows = []
    for instrument in instruments:
        descriptor_parts = tuple(
            value
            for value in (
                instrument.exchange,
                instrument.currency,
                *instrument.tags[:2],
                instrument.source if instrument.source != "curated" else "",
            )
            if value
        )
        descriptor = " · ".join(dict.fromkeys(descriptor_parts)) or instrument.engine_asset
        route = build_workspace_route("corr", instrument, period, interval)
        cells = (
            f'<span class="ir-directory-code" title="{escape(instrument.symbol, quote=True)}">{escape(instrument.symbol)}</span>'
            f'<span class="ir-directory-name" title="{escape(instrument.name, quote=True)}">{escape(instrument.name)}</span>'
            f'<span title="{escape(instrument.universe, quote=True)}">{escape(instrument.universe)}</span>'
            f'<span title="{escape(instrument.region, quote=True)}">{escape(instrument.region)}</span>'
            f'<span class="ir-directory-descriptor" title="{escape(descriptor, quote=True)}">{escape(descriptor)}</span>'
            f'<span class="ir-directory-route"><a href="{escape(route, quote=True)}" target="_blank" rel="noopener noreferrer">OPEN ↗</a></span>'
        )
        rows.append(f'<div class="ir-directory-row" role="row">{cells}</div>')
    header = "".join(
        f'<span role="columnheader">{label}</span>'
        for label in ("CODE", "INSTRUMENT", "UNIVERSE", "REGION", "DESCRIPTOR", "ROUTE")
    )
    st.markdown(
        '<div class="ir-directory" role="table" aria-label="Security master">'
        f'<div class="ir-directory-row ir-directory-head" role="row">{header}</div>'
        + "".join(rows)
        + "</div>",
        unsafe_allow_html=True,
    )


def _reset_security_master_state() -> None:
    defaults = {
        "router_directory_filter": "",
        "router_security_universe": "ALL",
        "router_security_region": "ALL",
        "router_security_engine": "ALL",
    }
    for key, value in defaults.items():
        st.session_state[key] = value


def render_institutional_router(
    *,
    launch_workspace: Callable[[str, str, str, str, str], None],
    snapshot_loader: Callable[[tuple[str, ...]], pd.DataFrame] | None = None,
) -> None:
    """Render the adaptive launchpad used as the terminal's asset-class home."""
    profile_options = list(CLIENT_PROFILES)
    initial_profile_code = st.session_state.get("router_profile", "multi_asset")
    if initial_profile_code not in profile_options:
        initial_profile_code = "multi_asset"
    profile = CLIENT_PROFILES[initial_profile_code]
    _inject_router_css(profile.accent)
    try:
        runtime_catalogue, master_health = load_runtime_security_master()
    except Exception as exc:
        runtime_catalogue = INSTRUMENTS
        master_health = {
            "raw_records": len(INSTRUMENTS),
            "canonical_records": len(INSTRUMENTS),
            "routeable_records": len(INSTRUMENTS),
            "sources": {"curated": len(INSTRUMENTS)},
            "integrity": "fallback",
            "latest_sec_sync": None,
            "load_error": str(exc),
        }
    runtime_universes = tuple(
        dict.fromkeys((*UNIVERSES, *(item.universe for item in runtime_catalogue)))
    )
    st.markdown(
        """
        <div class="ir-shell">
          <div class="ir-topline">
            <div><div class="ir-brand">JARVIS // INSTITUTIONAL NAVIGATOR</div>
            <div class="ir-title">Multi-Asset Workspace Router</div></div>
            <div class="ir-clock">LIVE DESK · SESSION PERSISTENT<br>SEARCH · MONITOR · ANALYZE · DECIDE</div>
          </div>
          <div class="ir-function-rail">
            <span class="ir-key"><b>F1</b>MARKETS</span><span class="ir-key"><b>F2</b>EQUITIES</span>
            <span class="ir-key"><b>F3</b>RATES</span><span class="ir-key"><b>F4</b>FX</span>
            <span class="ir-key"><b>F5</b>COMMODITIES</span><span class="ir-key"><b>F6</b>CREDIT</span>
            <span class="ir-key"><b>F7</b>PORTFOLIO</span><span class="ir-key"><b>F8</b>RISK</span>
            <span class="ir-key"><b>F9</b>RESEARCH</span><span class="ir-key"><b>F10</b>AI / NEWS</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.container(key="router_profile_context"):
        profile_column, context_column = st.columns([1.05, 2.95], vertical_alignment="bottom")
        with profile_column:
            selected_profile_code = st.selectbox(
                "CLIENT / DESK PROFILE",
                profile_options,
                index=profile_options.index(initial_profile_code),
                format_func=lambda code: CLIENT_PROFILES[code].label,
                key="router_profile",
            )
    profile = CLIENT_PROFILES[selected_profile_code]
    universe_state_key = f"router_universe_{selected_profile_code}"
    primary_state_key = f"router_primary_workspace_{selected_profile_code}"
    desk_state_key = f"router_desk_workspaces_{selected_profile_code}"

    previous_profile = st.session_state.get("router_profile_applied")
    if previous_profile != selected_profile_code:
        st.session_state["router_profile_applied"] = selected_profile_code

    with context_column:
        st.markdown(
            f'<div class="ir-context"><div class="ir-context-label">{escape(profile.label.upper())} · ADAPTIVE LAYOUT</div>'
            f'<div class="ir-context-text">{escape(profile.mandate)}. The desk selection below is retained for this client session.</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="ir-section"><span class="ir-section-title">MARKET PULSE</span><span class="ir-section-meta">8 CROSS-ASSET BENCHMARKS</span></div>', unsafe_allow_html=True)
    _render_market_pulse(snapshot_loader, selected_profile_code)

    universe_default = st.session_state.get(universe_state_key, profile.default_universe)
    if universe_default not in runtime_universes:
        universe_default = profile.default_universe

    with st.form("institutional_router_command_form"):
        c1, c2, c3, c4, c5 = st.columns([1.0, 2.0, 1.55, .72, .72], vertical_alignment="bottom")
        with c1:
            universe = st.selectbox(
                "ASSET UNIVERSE",
                runtime_universes,
                index=runtime_universes.index(universe_default),
                key=universe_state_key,
            )
        universe_instruments = search_instruments(
            universe=universe,
            limit=None,
            catalogue=runtime_catalogue,
        )
        preferred_symbol = profile.default_symbol
        instrument_index = next((index for index, item in enumerate(universe_instruments) if item.symbol == preferred_symbol), 0)
        with c2:
            instrument = st.selectbox(
                "SECURITY / INSTRUMENT",
                universe_instruments,
                index=instrument_index,
                format_func=_format_instrument,
                key=f"router_instrument_{universe}",
            )
        workspace_codes = [workspace.code for workspace in WORKSPACES]
        primary_default = st.session_state.get(primary_state_key, profile.workspaces[0])
        if primary_default not in workspace_codes:
            primary_default = profile.workspaces[0]
        with c3:
            primary_workspace = st.selectbox(
                "PRIMARY FUNCTION",
                workspace_codes,
                index=workspace_codes.index(primary_default),
                format_func=lambda code: f"{WORKSPACE_BY_CODE[code].function} · {WORKSPACE_BY_CODE[code].label}",
                key=primary_state_key,
            )
        with c4:
            period = st.selectbox("HISTORY", ("3mo", "6mo", "1y", "2y", "5y", "10y"), index=2, key="router_period")
        with c5:
            interval = st.selectbox("BAR", ("1d", "1wk", "1mo"), index=0, key="router_interval")

        b1, b2, b3 = st.columns([1.05, 1.05, 3.4], vertical_alignment="center")
        with b1:
            launch_primary = st.form_submit_button("<GO> OPEN PRIMARY", type="primary", width="stretch")
        with b2:
            add_to_desk = st.form_submit_button("+ ADD TO DESK", width="stretch")
        with b3:
            context_asset, context_symbol = workspace_context(primary_workspace, instrument)
            st.caption(f"Resolved context · {context_asset} / {context_symbol} · {WORKSPACE_BY_CODE[primary_workspace].label}")

    if add_to_desk:
        selected = list(st.session_state.get(desk_state_key, profile.workspaces))
        if primary_workspace not in selected:
            selected.append(primary_workspace)
        st.session_state[desk_state_key] = list(normalize_workspace_codes(selected, selected_profile_code))
        st.rerun()

    if launch_primary:
        workspace = WORKSPACE_BY_CODE[primary_workspace]
        if workspace.special_route:
            _launch_special(workspace.special_route)
        else:
            asset, symbol = workspace_context(primary_workspace, instrument)
            launch_workspace(asset, symbol, period, interval, workspace.mode or "Correlation Matrix")

    st.markdown('<div class="ir-section"><span class="ir-section-title">ACTIVE DESK WINDOWS</span><span class="ir-section-meta">SELECT UP TO 6 · OPEN EACH IN PARALLEL</span></div>', unsafe_allow_html=True)
    selected_codes = st.multiselect(
        "DESK COMPOSITION",
        [workspace.code for workspace in WORKSPACES],
        default=list(profile.workspaces),
        format_func=lambda code: f"{WORKSPACE_BY_CODE[code].function} · {WORKSPACE_BY_CODE[code].label}",
        key=desk_state_key,
        label_visibility="collapsed",
    )
    normalized_codes = normalize_workspace_codes(selected_codes, selected_profile_code)
    if len(selected_codes) > len(normalized_codes):
        st.warning("The institutional desk is limited to six active windows to preserve focus and performance.")
    _render_workspace_grid(normalized_codes, instrument, period, interval)
    st.caption("OPEN ↗ launches an independent routed tab. Keep the navigator open and use several sections at the same time.")

    counts = {
        universe_name: sum(item.universe == universe_name for item in runtime_catalogue)
        for universe_name in runtime_universes
    }
    regions = tuple(sorted({item.region for item in runtime_catalogue}))
    engines = tuple(sorted({item.engine_asset for item in runtime_catalogue}))
    sources = master_health.get("sources", {})
    latest_sec_sync = master_health.get("latest_sec_sync")
    latest_nasdaq_sync = master_health.get("latest_nasdaq_sync")
    reference_synced = any(
        getattr(result, "status", "") == "success"
        for result in (latest_nasdaq_sync, latest_sec_sync)
    )
    catalogue_state = "SYNCED" if reference_synced else "SEED"
    sec_record_count = int(sources.get("sec_edgar", 0))
    nasdaq_record_count = int(sources.get("nasdaq_directory", 0))
    largest_universe = max(counts.values())
    universe_cards = "".join(
        f'<div class="ir-universe"><div class="ir-universe-top"><div class="ir-universe-name">{escape(name.upper())}</div>'
        f'<div class="ir-universe-count">{count}</div></div><div class="ir-universe-track">'
        f'<div class="ir-universe-fill" style="width:{(count / largest_universe) * 100:.1f}%"></div></div></div>'
        for name, count in counts.items()
    )
    st.markdown(
        f'<div class="ir-section"><span class="ir-section-title">SECURITY MASTER / XRF</span><span class="ir-section-meta">GLOBAL CROSS-ASSET DIRECTORY · ROUTE FROM ANY ROW</span></div>'
        f'<div class="ir-master-banner"><div class="ir-master-identity"><div class="ir-master-code">XRF &lt;GO&gt;</div>'
        f'<div><div class="ir-master-title">Cross-Asset Security Master</div>'
        f'<div class="ir-master-subtitle">Search, classify and launch the complete institutional instrument universe.</div></div></div>'
        f'<div class="ir-master-kpis"><div class="ir-master-kpi"><div class="ir-master-kpi-label">ROUTABLE</div><div class="ir-master-kpi-value">{len(runtime_catalogue):,}</div></div>'
        f'<div class="ir-master-kpi"><div class="ir-master-kpi-label">SOURCES</div><div class="ir-master-kpi-value">{len(sources)}</div></div>'
        f'<div class="ir-master-kpi"><div class="ir-master-kpi-label">REGIONS</div><div class="ir-master-kpi-value">{len(regions)}</div></div>'
        f'<div class="ir-master-kpi"><div class="ir-master-kpi-label">CATALOGUE</div><div class="ir-master-kpi-value live">{catalogue_state}</div></div></div></div>'
        f'<div class="ir-universe-grid">{universe_cards}</div>'
        f'<div class="ir-provider-strip"><span><b>REFERENCE</b> NASDAQ · {nasdaq_record_count:,} / SEC · {sec_record_count:,}</span>'
        f'<span><b>SYMBOLOGY</b> OPENFIGI V3 ADAPTER</span><span><b>PRICE ROUTING</b> DATABENTO · TWELVE DATA · YAHOO FALLBACK</span></div>',
        unsafe_allow_html=True,
    )
    with st.container(key="router_security_filters"):
        query_column, universe_column, region_column, engine_column = st.columns(
            [2.5, 1.15, 1.25, 1.0],
            vertical_alignment="bottom",
        )
        with query_column:
            directory_query = st.text_input(
                "SECURITY / ISSUER / THEME",
                placeholder="NVDA, Japan banks, uranium, HY spread…",
                key="router_directory_filter",
            )
        with universe_column:
            universe_filter = st.selectbox(
                "UNIVERSE SCOPE",
                ("ALL", *runtime_universes),
                format_func=lambda value: "ALL UNIVERSES" if value == "ALL" else value,
                key="router_security_universe",
            )
        with region_column:
            region_filter = st.selectbox(
                "REGION / MARKET",
                ("ALL", *regions),
                format_func=lambda value: "ALL REGIONS" if value == "ALL" else value,
                key="router_security_region",
            )
        with engine_column:
            engine_filter = st.selectbox(
                "ANALYTICS ENGINE",
                ("ALL", *engines),
                format_func=lambda value: "ALL ENGINES" if value == "ALL" else value,
                key="router_security_engine",
            )

        directory_all_matches = filter_security_master(
            directory_query,
            universe=universe_filter,
            region=region_filter,
            engine=engine_filter,
            limit=None,
            catalogue=runtime_catalogue,
        )
        directory_matches = directory_all_matches[:80]
        action_column, reset_column, sync_column, export_column, spacer_column = st.columns(
            [.85, .7, 1.05, .85, 2.9],
            vertical_alignment="center",
        )
        with action_column:
            st.button("<GO> FILTER", key="router_directory_apply", width="stretch")
        with reset_column:
            st.button(
                "RESET",
                key="router_directory_reset",
                on_click=_reset_security_master_state,
                width="stretch",
            )
        with sync_column:
            sync_requested = st.button(
                "SYNC SOURCES",
                key="router_directory_sync",
                width="stretch",
            )
        with export_column:
            directory_frame = _directory_frame(directory_all_matches)
            st.download_button(
                "EXPORT CSV",
                directory_frame.to_csv(index=False).encode("utf-8"),
                file_name="security_master.csv",
                mime="text/csv",
                width="stretch",
            )
        with spacer_column:
            st.caption("Query scope persists for this terminal session · OPEN ↗ launches an independent workspace")

    if sync_requested:
        with st.spinner("Synchronizing listed-security reference sources…"):
            sync_results = refresh_runtime_security_master()
        successful_records = sum(result.records for result in sync_results if result.status == "success")
        failures = [result for result in sync_results if result.status != "success"]
        if successful_records:
            st.toast(f"Security Master synchronized · {successful_records:,} provider records", icon="✅")
        if failures:
            st.error(" · ".join(f"{result.provider}: {result.error}" for result in failures))
        st.rerun()

    active_filter_count = sum(
        (bool(directory_query.strip()), universe_filter != "ALL", region_filter != "ALL", engine_filter != "ALL")
    )
    scope_label = "FILTERED SCOPE" if active_filter_count else "FULL CATALOGUE"
    st.markdown(
        f'<div class="ir-directory-status"><span><span class="live">● READY</span> · {scope_label} · '
        f'<b>{len(directory_all_matches)}</b> MATCHES · <b>{len(directory_matches)}</b> SHOWN</span>'
        f'<span>DOUBLE-SCOPE: PROFILE {escape(profile.label.upper())} / {escape(universe_filter)}</span></div>',
        unsafe_allow_html=True,
    )
    _render_security_directory(directory_matches, period, interval)
    st.markdown(
        '<div class="ir-footnote">NAVIGATION LAYER ONLY · Market-data availability depends on configured providers. '
        'Client profile, desk composition and instrument context remain isolated in the current Streamlit session.</div>',
        unsafe_allow_html=True,
    )
