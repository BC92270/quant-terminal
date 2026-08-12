"""Auditable provider catalogue: ownership, cadence, auth and implementation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


Mode = Literal["active", "snapshot", "adapter", "roadmap"]


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    name: str
    mode: Mode
    authority: str
    cadence: str
    layers: tuple[str, ...]
    credentials: tuple[str, ...] = ()
    endpoint: str = ""
    note: str = ""

    @property
    def configured(self) -> bool:
        return not self.credentials or all(
            any(bool(os.getenv(option, "").strip()) for option in requirement.split("|"))
            for requirement in self.credentials
        )


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec("world_bank_wdi", "World Bank WDI", "snapshot", "World Bank", "annual", ("ciiChoropleth", "resilienceScore", "debtStress"), endpoint="https://api.worldbank.org/v2/", note="19 official series embedded with value year and source."),
    ProviderSpec("usgs", "USGS Earthquake Hazards", "active", "USGS", "minutes", ("earthquakes",), endpoint="https://earthquake.usgs.gov/fdsnws/event/1/"),
    ProviderSpec("gdacs", "Global Disaster Alert and Coordination System", "active", "UN/European Commission", "minutes", ("natural", "weather"), endpoint="https://www.gdacs.org/xml/rss.xml"),
    ProviderSpec("nasa_eonet", "NASA EONET", "active", "NASA", "minutes", ("natural", "fires"), endpoint="https://eonet.gsfc.nasa.gov/api/v3/events"),
    ProviderSpec("nasa_firms", "NASA FIRMS", "active", "NASA", "near-real-time", ("fires",), ("NASA_FIRMS_MAP_KEY|NASA_FIRMS_API_KEY",), "https://firms.modaps.eosdis.nasa.gov/api/area/"),
    ProviderSpec("gdelt", "GDELT DOC 2.0", "active", "GDELT Project", "15 minutes", ("newsLocations", "informationOps"), endpoint="https://api.gdeltproject.org/api/v2/doc/doc"),
    ProviderSpec("google_news", "Google News publisher mesh", "active", "Publisher RSS aggregation", "minutes", ("newsLocations",), endpoint="https://news.google.com/rss/"),
    ProviderSpec("acled", "ACLED", "active", "ACLED", "near-real-time", ("protestEvents", "riotUnrest", "civilianViolence", "conflicts"), ("ACLED_EMAIL|ACLED_ACCESS_TOKEN|ACLED_KEY", "ACLED_PASSWORD|ACLED_ACCESS_TOKEN|ACLED_KEY"), "https://acleddata.com/api/acled/read"),
    ProviderSpec("opensky", "OpenSky Network", "active", "OpenSky Network", "seconds", ("flights",), ("OPENSKY_CLIENT_ID", "OPENSKY_CLIENT_SECRET"), "https://opensky-network.org/api/states/all"),
    ProviderSpec("newsapi", "NewsAPI", "active", "Publisher discovery", "minutes", ("newsLocations",), ("NEWSAPI_KEY",), "https://newsapi.org/v2/everything"),
    ProviderSpec("ucdp", "UCDP GED Candidate", "adapter", "Uppsala University", "monthly", ("ucdpEvents", "conflicts"), endpoint="https://ucdpapi.pcr.uu.se/api/gedevents/"),
    ProviderSpec("unhcr", "UNHCR Refugee Statistics", "roadmap", "UNHCR", "semiannual", ("displacement", "refugeeRoutes"), endpoint="https://api.unhcr.org/population/v1/"),
    ProviderSpec("reliefweb", "ReliefWeb API V2", "adapter", "UN OCHA", "continuous", ("displacement", "healthOutbreaks", "natural"), ("RELIEFWEB_APPNAME",), "https://api.reliefweb.int/v2/"),
    ProviderSpec("copernicus_ems", "Copernicus EMS Mapping", "roadmap", "European Commission", "event-driven", ("natural", "climate", "industrialAccidents"), endpoint="https://mapping.emergency.copernicus.eu/activations/api/activations/"),
    ProviderSpec("ofac", "OFAC Sanctions List Service", "roadmap", "US Treasury", "event-driven", ("sanctions", "secondarySanctionsRisk"), endpoint="https://sanctionslistservice.ofac.treas.gov/api/"),
    ProviderSpec("cisa_kev", "CISA Known Exploited Vulnerabilities", "roadmap", "CISA", "event-driven", ("cyberThreats",), endpoint="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"),
    ProviderSpec("noaa_swpc", "NOAA Space Weather", "roadmap", "NOAA SWPC", "1 minute", ("satellites", "gpsJamming", "orbitalSurveillance"), endpoint="https://services.swpc.noaa.gov/json/"),
    ProviderSpec("imf_sdmx", "IMF Data SDMX", "roadmap", "IMF", "monthly/quarterly", ("sovereignDebtStress", "fxStress", "bankingStress"), endpoint="https://www.imf.org/external/datamapper/api/"),
    ProviderSpec("bis_sdmx", "BIS Statistics SDMX", "roadmap", "Bank for International Settlements", "monthly/quarterly", ("bankingStress", "fxStress"), endpoint="https://stats.bis.org/api/v1/"),
    ProviderSpec("eia", "EIA Open Data V2", "adapter", "US Energy Information Administration", "daily/monthly", ("oilGasFields", "lngTerminals", "energyStorage", "fuelShortages"), ("EIA_API_KEY",), "https://api.eia.gov/v2/"),
    ProviderSpec("un_comtrade", "UN Comtrade", "roadmap", "UN Statistics Division", "monthly", ("tradeFlows", "commodityPorts", "tradeRoutes"), ("COMTRADE_API_KEY|COMTRADE_API_KEYS",), "https://comtradeapi.un.org/"),
    ProviderSpec("aisstream", "AISStream", "adapter", "AISStream", "seconds", ("ais", "liveTankers", "maritimeTraffic"), ("AISSTREAM_API_KEY",), "https://aisstream.io/"),
    ProviderSpec("fred", "FRED", "adapter", "Federal Reserve Bank of St. Louis", "daily/monthly", ("debtStress", "fxStress", "economic"), ("FRED_API_KEY",), "https://api.stlouisfed.org/fred/"),
)


def provider_summary() -> dict[str, int]:
    return {
        "catalogued": len(PROVIDERS),
        "active": sum(provider.mode == "active" for provider in PROVIDERS),
        "snapshots": sum(provider.mode == "snapshot" for provider in PROVIDERS),
        "adapters": sum(provider.mode == "adapter" for provider in PROVIDERS),
        "roadmap": sum(provider.mode == "roadmap" for provider in PROVIDERS),
        "configured_keyed": sum(bool(provider.credentials) and provider.configured for provider in PROVIDERS),
        "locked_keyed": sum(bool(provider.credentials) and not provider.configured for provider in PROVIDERS),
    }
