"""Central provider configuration without persisting or exposing credentials.

The terminal historically resolved provider keys independently in each large
workspace.  This module gives new adapters one deterministic lookup policy and
keeps a machine-readable map of the data dependencies of every routed section.
Existing workspaces can migrate to it incrementally without a flag day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from typing import Any, Mapping, Sequence


def resolve_secret(
    names: str | Sequence[str],
    secrets: Mapping[str, Any] | None = None,
) -> str:
    """Return the first configured value from Streamlit secrets, then env.

    Empty values are ignored.  The function deliberately returns only the
    value; callers must never put it in logs, URLs shown to users, dataframe
    attributes or exported diagnostics.
    """

    candidates = (names,) if isinstance(names, str) else tuple(names)
    for name in candidates:
        if secrets is not None:
            try:
                value = secrets.get(name, "")
            except Exception:
                try:
                    value = secrets[name]
                except Exception:
                    value = ""
            if value is not None and str(value).strip():
                return str(value).strip()
        value = os.getenv(name, "")
        if value.strip():
            return value.strip()
    return ""


@dataclass(frozen=True)
class SectionProviderBinding:
    section: str
    primary: str
    optional_keys: tuple[str, ...]
    keyless_or_local_fallback: str
    coverage: str

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["optional_keys"] = ", ".join(self.optional_keys) or "None"
        return row


SECTION_PROVIDER_BINDINGS: tuple[SectionProviderBinding, ...] = (
    SectionProviderBinding("Market shell / dashboards", "Databento / Twelve Data / Alpha Vantage", ("DATABENTO_API_KEY", "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "COINGECKO_DEMO_API_KEY", "COINGECKO_API_KEY"), "Frankfurter / CoinGecko public / Yahoo", "Cross-asset OHLCV and intraday routing"),
    SectionProviderBinding("Momentum / Trend", "Shared market-data gateway", ("TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "COINGECKO_DEMO_API_KEY", "COINGECKO_API_KEY"), "Frankfurter / CoinGecko public / Yahoo", "Causal OHLCV and volume"),
    SectionProviderBinding("Options / Futures", "ThetaData / Massive / Tradier", ("THETADATA_API_KEY", "MASSIVE_API_KEY", "TRADIER_API_TOKEN"), "Yahoo delayed public reference", "US options chains and futures curves"),
    SectionProviderBinding("Correlation Matrix", "Shared OHLCV + FRED", ("TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "COINGECKO_DEMO_API_KEY", "COINGECKO_API_KEY", "FRED_API_KEY"), "Yahoo + Frankfurter + public FRED CSV", "Prices and macro dependencies"),
    SectionProviderBinding("Portfolio Lab", "Yahoo + OpenFIGI", ("OPENFIGI_API_KEY",), "Yahoo + local symbology", "Multi-asset prices and identifiers"),
    SectionProviderBinding("Risk / Backtest / Monte Carlo", "Shared OHLCV + Tradier / Massive / ThetaData / Databento", ("TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY", "COINGECKO_DEMO_API_KEY", "COINGECKO_API_KEY", "TRADIER_API_TOKEN", "MASSIVE_API_KEY", "THETADATA_API_KEY", "DATABENTO_API_KEY", "FRED_API_KEY"), "Frankfurter / CoinGecko public / Yahoo", "Historical prices, NBBO/options enrichment, depth/factor contracts and scenarios"),
    SectionProviderBinding("Company Intelligence", "FMP / Alpha Vantage / Finnhub / SEC", ("FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY", "SEC_USER_AGENT"), "Yahoo + SEC when reachable", "Fundamentals, estimates, filings and transcripts"),
    SectionProviderBinding("Macro / Central Banks", "Official institutions / Trading Economics / FRED", ("TRADING_ECONOMICS_API_KEY", "FRED_API_KEY"), "Central-bank releases and public archives", "Policy, releases and documents"),
    SectionProviderBinding("Fixed Income & Credit", "FRED / SEC / OpenFIGI", ("FRED_API_KEY", "SEC_USER_AGENT", "OPENFIGI_API_KEY"), "Public FRED CSV + Treasury/ECB datasets", "Curves, spreads and identifiers"),
    SectionProviderBinding("Market Psychology", "Twelve Data / Massive / FMP / Finnhub / NewsAPI", ("TWELVE_DATA_API_KEY", "MASSIVE_API_KEY", "FMP_API_KEY", "ALPHA_VANTAGE_API_KEY", "FINNHUB_API_KEY", "NEWSAPI_KEY", "FRED_API_KEY", "FINRA_CLIENT_ID", "FINRA_CLIENT_SECRET"), "Yahoo + public news/event feeds", "Price, positioning, news and beliefs"),
    SectionProviderBinding("WorldMonitor", "ACLED / OpenSky / NASA FIRMS / NewsAPI", ("ACLED_ACCESS_TOKEN", "ACLED_EMAIL", "ACLED_PASSWORD", "OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET", "NASA_FIRMS_MAP_KEY", "NEWSAPI_KEY", "EIA_API_KEY", "COMTRADE_API_KEY", "AISSTREAM_API_KEY", "RELIEFWEB_APPNAME"), "GDELT, World Bank, USGS, GDACS, NASA EONET, UCDP and public official feeds", "Geopolitics and real-world events"),
    SectionProviderBinding("Security Master", "Nasdaq / SEC / OpenFIGI", ("SEC_USER_AGENT", "OPENFIGI_API_KEY"), "Curated seed + official Nasdaq directory", "Instrument identity and routing"),
    SectionProviderBinding("Quant AI", "User-selected LLM provider", (), "Deterministic analytics", "Session-only key by design"),
)


def provider_matrix() -> list[dict[str, Any]]:
    return [binding.to_dict() for binding in SECTION_PROVIDER_BINDINGS]


def configured_provider_keys(
    secrets: Mapping[str, Any] | None = None,
) -> dict[str, bool]:
    names = sorted({name for binding in SECTION_PROVIDER_BINDINGS for name in binding.optional_keys})
    return {name: bool(resolve_secret(name, secrets)) for name in names}
