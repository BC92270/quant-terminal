"""Persistent, provider-aware security master for the institutional router.

The router's curated catalogue remains the high-confidence navigation seed.
This module adds a normalized reference layer that can be refreshed from
authoritative sources without coupling network calls to market-data engines.
"""

from __future__ import annotations

from contextlib import contextmanager
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping, Sequence

import requests


SCHEMA_VERSION = 1
DEFAULT_DB_PATH = Path(".quant_data/security_master.sqlite3")
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
NASDAQ_OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _pairs(value: Mapping[str, Any] | Iterable[tuple[str, Any]] | None) -> tuple[tuple[str, str], ...]:
    if not value:
        return ()
    items = value.items() if isinstance(value, Mapping) else value
    return tuple(sorted((str(key), _clean(item)) for key, item in items if _clean(item)))


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    """Provider-neutral identity and routing metadata for one instrument."""

    canonical_id: str
    symbol: str
    name: str
    universe: str
    engine_asset: str
    region: str
    currency: str = ""
    exchange: str = ""
    mic: str = ""
    security_type: str = ""
    source: str = "curated"
    source_symbol: str = ""
    figi: str = ""
    cik: str = ""
    tags: tuple[str, ...] = ()
    provider_symbols: tuple[tuple[str, str], ...] = ()
    identifiers: tuple[tuple[str, str], ...] = ()
    routeable: bool = True
    active: bool = True
    last_verified_at: str = ""

    @property
    def search_text(self) -> str:
        values = (
            self.symbol,
            self.name,
            self.universe,
            self.engine_asset,
            self.region,
            self.currency,
            self.exchange,
            self.mic,
            self.security_type,
            self.source,
            self.figi,
            self.cik,
            *self.tags,
            *(value for _, value in self.identifiers),
        )
        return " ".join(value for value in values if value).casefold()


@dataclass(frozen=True, slots=True)
class SyncResult:
    provider: str
    status: str
    records: int
    started_at: str
    finished_at: str
    error: str = ""


@dataclass(frozen=True, slots=True)
class FigiMapping:
    requested_symbol: str
    figi: str
    composite_figi: str
    name: str
    ticker: str
    exchange_code: str
    market_sector: str
    security_type: str


@dataclass(frozen=True, slots=True)
class ProviderCandidate:
    provider_id: str
    name: str
    role: str
    mode: str
    auth_options: tuple[str, ...] = ()
    note: str = ""

    @property
    def configured(self) -> bool:
        return not self.auth_options or any(bool(os.getenv(name, "").strip()) for name in self.auth_options)


# Curated from the finance, currency and cryptocurrency sections of
# public-apis/public-apis, then reduced to providers that add a distinct layer.
PROVIDER_CANDIDATES: tuple[ProviderCandidate, ...] = (
    ProviderCandidate("sec_edgar", "SEC EDGAR", "issuer reference", "active", note="US listed ticker, CIK and exchange associations."),
    ProviderCandidate("nasdaq_directory", "Nasdaq Symbol Directory", "listed security reference", "active", note="Daily Nasdaq and other-exchange symbol directories."),
    ProviderCandidate("openfigi", "OpenFIGI v3", "global symbology", "adapter", ("OPENFIGI_API_KEY",), "FIGI mapping and filtered instrument discovery; lower limits work without a key."),
    ProviderCandidate("databento", "Databento", "licensed market data", "active", ("DATABENTO_API_KEY",), "Existing priority feed for mapped futures and institutional datasets."),
    ProviderCandidate("twelve_data", "Twelve Data", "cross-asset prices", "active", ("TWELVE_DATA_API_KEY",), "Existing FX, equity and ETF price adapter."),
    ProviderCandidate("yfinance", "Yahoo Finance", "public price fallback", "active", note="Best-effort historical and intraday routing fallback."),
    ProviderCandidate("frankfurter", "Frankfurter v2", "official FX reference", "adapter", note="Daily reference rates from central-bank providers; no key required."),
    ProviderCandidate("coingecko", "CoinGecko", "crypto reference and prices", "roadmap", ("COINGECKO_DEMO_API_KEY", "COINGECKO_API_KEY"), "Crypto identifiers, categories and market metadata."),
    ProviderCandidate("finnhub", "Finnhub", "events and fundamentals", "roadmap", ("FINNHUB_API_KEY",), "Company events, news and supplemental fundamentals."),
    ProviderCandidate("fmp", "Financial Modeling Prep", "fundamentals", "roadmap", ("FMP_API_KEY",), "Statements, estimates and company reference data."),
    ProviderCandidate("fred", "FRED", "macro and rates", "active", ("FRED_API_KEY",), "Existing macro-series adapter outside the security identifier layer."),
)


def provider_matrix() -> list[dict[str, Any]]:
    return [
        {
            "provider_id": provider.provider_id,
            "name": provider.name,
            "role": provider.role,
            "mode": provider.mode,
            "configured": provider.configured,
            "note": provider.note,
        }
        for provider in PROVIDER_CANDIDATES
    ]


class SecurityMasterStore:
    """SQLite cache with isolated provider records and auditable sync runs."""

    def __init__(self, path: str | Path = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS securities (
                    canonical_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    universe TEXT NOT NULL,
                    engine_asset TEXT NOT NULL,
                    region TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    mic TEXT NOT NULL,
                    security_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    source_symbol TEXT NOT NULL,
                    figi TEXT NOT NULL,
                    cik TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    provider_symbols_json TEXT NOT NULL,
                    identifiers_json TEXT NOT NULL,
                    routeable INTEGER NOT NULL,
                    active INTEGER NOT NULL,
                    last_verified_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_security_symbol ON securities(symbol);
                CREATE INDEX IF NOT EXISTS idx_security_source ON securities(source);
                CREATE INDEX IF NOT EXISTS idx_security_scope ON securities(universe, region, engine_asset);

                CREATE TABLE IF NOT EXISTS security_master_sync_runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record_count INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    error TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS security_master_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            connection.execute(
                """
                INSERT INTO security_master_metadata(key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _upsert(self, connection: sqlite3.Connection, records: Sequence[SecurityRecord]) -> int:
        if not records:
            return 0
        now = _utc_now()
        rows = [
            (
                record.canonical_id,
                record.symbol,
                record.name,
                record.universe,
                record.engine_asset,
                record.region,
                record.currency,
                record.exchange,
                record.mic,
                record.security_type,
                record.source,
                record.source_symbol,
                record.figi,
                record.cik,
                json.dumps(record.tags, ensure_ascii=False),
                json.dumps(dict(record.provider_symbols), ensure_ascii=False, sort_keys=True),
                json.dumps(dict(record.identifiers), ensure_ascii=False, sort_keys=True),
                int(record.routeable),
                int(record.active),
                record.last_verified_at,
                now,
            )
            for record in records
        ]
        before = connection.total_changes
        connection.executemany(
            """
            INSERT INTO securities(
                canonical_id, symbol, name, universe, engine_asset, region,
                currency, exchange, mic, security_type, source, source_symbol,
                figi, cik, tags_json, provider_symbols_json, identifiers_json,
                routeable, active, last_verified_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_id) DO UPDATE SET
                symbol=excluded.symbol,
                name=excluded.name,
                universe=excluded.universe,
                engine_asset=excluded.engine_asset,
                region=excluded.region,
                currency=excluded.currency,
                exchange=excluded.exchange,
                mic=excluded.mic,
                security_type=excluded.security_type,
                source=excluded.source,
                source_symbol=excluded.source_symbol,
                figi=excluded.figi,
                cik=excluded.cik,
                tags_json=excluded.tags_json,
                provider_symbols_json=excluded.provider_symbols_json,
                identifiers_json=excluded.identifiers_json,
                routeable=excluded.routeable,
                active=excluded.active,
                last_verified_at=excluded.last_verified_at,
                updated_at=excluded.updated_at
            """,
            rows,
        )
        return int(connection.total_changes - before)

    def upsert_records(self, records: Iterable[SecurityRecord]) -> int:
        materialized = tuple(records)
        with self.connection() as connection:
            return self._upsert(connection, materialized)

    def replace_source(self, source: str, records: Iterable[SecurityRecord]) -> int:
        materialized = tuple(records)
        if any(record.source != source for record in materialized):
            raise ValueError("replace_source received a record owned by another provider")
        with self.connection() as connection:
            connection.execute("DELETE FROM securities WHERE source = ?", (source,))
            self._upsert(connection, materialized)
        return len(materialized)

    def record_sync(self, result: SyncResult) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO security_master_sync_runs(
                    provider, status, record_count, started_at, finished_at, error
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    result.provider,
                    result.status,
                    result.records,
                    result.started_at,
                    result.finished_at,
                    result.error,
                ),
            )

    def all_records(self, *, active_only: bool = True) -> list[SecurityRecord]:
        where = "WHERE active = 1" if active_only else ""
        with self.connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM securities {where} ORDER BY universe, symbol, source"  # noqa: S608
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def latest_sync(self, provider: str, *, successful_only: bool = False) -> SyncResult | None:
        status_filter = "AND status = 'success'" if successful_only else ""
        with self.connection() as connection:
            row = connection.execute(
                f"""
                SELECT provider, status, record_count, started_at, finished_at, error
                FROM security_master_sync_runs
                WHERE provider = ? {status_filter}
                ORDER BY run_id DESC
                LIMIT 1
                """,  # noqa: S608
                (provider,),
            ).fetchone()
        return SyncResult(*row) if row is not None else None

    def source_needs_refresh(
        self,
        provider: str,
        *,
        success_ttl_seconds: int = 86_400,
        failure_ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> bool:
        latest = self.latest_sync(provider)
        if latest is None:
            return True
        timestamp = datetime.fromisoformat(latest.finished_at)
        current = now or datetime.now(timezone.utc)
        age = max((current - timestamp).total_seconds(), 0.0)
        ttl = success_ttl_seconds if latest.status == "success" else failure_ttl_seconds
        return age >= ttl

    def health(self) -> dict[str, Any]:
        with self.connection() as connection:
            raw_records = int(connection.execute("SELECT COUNT(*) FROM securities WHERE active = 1").fetchone()[0])
            sources = {
                str(row[0]): int(row[1])
                for row in connection.execute(
                    "SELECT source, COUNT(*) FROM securities WHERE active = 1 GROUP BY source ORDER BY source"
                ).fetchall()
            }
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        return {
            "path": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "raw_records": raw_records,
            "sources": sources,
            "integrity": integrity,
        }


def _row_to_record(row: sqlite3.Row) -> SecurityRecord:
    return SecurityRecord(
        canonical_id=row["canonical_id"],
        symbol=row["symbol"],
        name=row["name"],
        universe=row["universe"],
        engine_asset=row["engine_asset"],
        region=row["region"],
        currency=row["currency"],
        exchange=row["exchange"],
        mic=row["mic"],
        security_type=row["security_type"],
        source=row["source"],
        source_symbol=row["source_symbol"],
        figi=row["figi"],
        cik=row["cik"],
        tags=tuple(json.loads(row["tags_json"])),
        provider_symbols=_pairs(json.loads(row["provider_symbols_json"])),
        identifiers=_pairs(json.loads(row["identifiers_json"])),
        routeable=bool(row["routeable"]),
        active=bool(row["active"]),
        last_verified_at=row["last_verified_at"],
    )


def normalize_us_market_symbol(symbol: str) -> str:
    """Translate common SEC share-class punctuation to the Yahoo route format."""
    return _clean(symbol).upper().replace(".", "-").replace("/", "-").replace(" ", "-")


class SecCompanyTickerProvider:
    provider_id = "sec_edgar"

    def __init__(self, user_agent: str | None = None, timeout: float = 15.0) -> None:
        self.user_agent = _clean(user_agent or os.getenv("SEC_USER_AGENT")) or "QuantTerminal/1.0 security-master"
        self.timeout = float(timeout)

    def fetch(self, session: Any | None = None) -> list[SecurityRecord]:
        client = session or requests
        response = client.get(
            SEC_TICKERS_URL,
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        fields = [str(field) for field in payload.get("fields", ())]
        index = {field: position for position, field in enumerate(fields)}
        required = {"cik", "name", "ticker", "exchange"}
        if not required.issubset(index):
            raise ValueError("SEC ticker payload is missing required fields")

        verified_at = _utc_now()
        records: list[SecurityRecord] = []
        for row in payload.get("data", ()):
            ticker = _clean(row[index["ticker"]]).upper()
            name = _clean(row[index["name"]])
            exchange = _clean(row[index["exchange"]])
            cik = _clean(row[index["cik"]])
            if not ticker or not name:
                continue
            symbol = normalize_us_market_symbol(ticker)
            records.append(
                SecurityRecord(
                    canonical_id=f"sec_edgar:{cik}:{ticker}",
                    symbol=symbol,
                    name=name,
                    universe="Equities",
                    engine_asset="Equity",
                    region="United States",
                    currency="USD",
                    exchange=exchange,
                    security_type="SEC registrant",
                    source=self.provider_id,
                    source_symbol=ticker,
                    cik=cik,
                    tags=tuple(value for value in ("SEC filer", exchange) if value),
                    provider_symbols=_pairs({"sec": ticker, "yfinance": symbol}),
                    identifiers=_pairs({"CIK": cik}),
                    routeable=True,
                    active=True,
                    last_verified_at=verified_at,
                )
            )
        return records


class NasdaqSymbolDirectoryProvider:
    """Daily US listed-symbol reference feed published by Nasdaq Trader."""

    provider_id = "nasdaq_directory"
    exchange_names = {
        "A": "NYSE American",
        "N": "NYSE",
        "P": "NYSE Arca",
        "Z": "Cboe BZX",
        "V": "IEX",
    }

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = float(timeout)

    def _download(self, url: str, session: Any | None = None) -> str:
        client = session or requests
        response = client.get(
            url,
            headers={"User-Agent": "QuantTerminal/1.0", "Accept": "text/plain"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return str(response.text)

    def fetch(self, session: Any | None = None) -> list[SecurityRecord]:
        verified_at = _utc_now()
        nasdaq_rows = csv.DictReader(StringIO(self._download(NASDAQ_LISTED_URL, session)), delimiter="|")
        other_rows = csv.DictReader(StringIO(self._download(NASDAQ_OTHER_LISTED_URL, session)), delimiter="|")
        records: list[SecurityRecord] = []

        for row in nasdaq_rows:
            symbol = _clean(row.get("Symbol")).upper()
            name = _clean(row.get("Security Name"))
            if not symbol or symbol.startswith("FILE CREATION TIME") or _clean(row.get("Test Issue")).upper() == "Y":
                continue
            is_etf = _clean(row.get("ETF")).upper() == "Y"
            records.append(
                self._record(
                    symbol=symbol,
                    name=name,
                    exchange="Nasdaq",
                    source_symbol=symbol,
                    is_etf=is_etf,
                    verified_at=verified_at,
                )
            )

        for row in other_rows:
            source_symbol = _clean(row.get("ACT Symbol") or row.get("CQS Symbol")).upper()
            route_symbol = _clean(row.get("NASDAQ Symbol") or source_symbol).upper()
            name = _clean(row.get("Security Name"))
            if not route_symbol or route_symbol.startswith("FILE CREATION TIME") or _clean(row.get("Test Issue")).upper() == "Y":
                continue
            exchange_code = _clean(row.get("Exchange")).upper()
            records.append(
                self._record(
                    symbol=route_symbol,
                    name=name,
                    exchange=self.exchange_names.get(exchange_code, exchange_code),
                    source_symbol=source_symbol or route_symbol,
                    is_etf=_clean(row.get("ETF")).upper() == "Y",
                    verified_at=verified_at,
                )
            )

        return records

    def _record(
        self,
        *,
        symbol: str,
        name: str,
        exchange: str,
        source_symbol: str,
        is_etf: bool,
        verified_at: str,
    ) -> SecurityRecord:
        route_symbol = normalize_us_market_symbol(symbol)
        universe = "ETFs" if is_etf else "Equities"
        return SecurityRecord(
            canonical_id=f"nasdaq_directory:{source_symbol}",
            symbol=route_symbol,
            name=name or source_symbol,
            universe=universe,
            engine_asset="Equity",
            region="United States",
            currency="USD",
            exchange=exchange,
            security_type="ETF" if is_etf else "Listed Security",
            source=self.provider_id,
            source_symbol=source_symbol,
            tags=("listed", exchange, "ETF" if is_etf else "security"),
            provider_symbols=_pairs({"nasdaq": source_symbol, "yfinance": route_symbol}),
            routeable=True,
            active=True,
            last_verified_at=verified_at,
        )


class OpenFigiProvider:
    provider_id = "openfigi"

    def __init__(self, api_key: str | None = None, timeout: float = 15.0) -> None:
        self.api_key = _clean(api_key or os.getenv("OPENFIGI_API_KEY"))
        self.timeout = float(timeout)

    def map_tickers(
        self,
        tickers: Sequence[str],
        *,
        exchange_code: str = "US",
        session: Any | None = None,
    ) -> dict[str, FigiMapping]:
        requested = tuple(dict.fromkeys(_clean(ticker).upper() for ticker in tickers if _clean(ticker)))
        max_jobs = 100 if self.api_key else 10
        if len(requested) > max_jobs:
            raise ValueError(f"OpenFIGI accepts at most {max_jobs} mapping jobs for this credential mode")
        if not requested:
            return {}

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        jobs = [{"idType": "TICKER", "idValue": ticker, "exchCode": exchange_code} for ticker in requested]
        client = session or requests
        response = client.post(OPENFIGI_MAPPING_URL, headers=headers, json=jobs, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()

        mappings: dict[str, FigiMapping] = {}
        for requested_symbol, result in zip(requested, payload, strict=False):
            candidates = result.get("data", ()) if isinstance(result, Mapping) else ()
            if not candidates:
                continue
            item = candidates[0]
            mappings[requested_symbol] = FigiMapping(
                requested_symbol=requested_symbol,
                figi=_clean(item.get("figi")),
                composite_figi=_clean(item.get("compositeFIGI")),
                name=_clean(item.get("name")),
                ticker=_clean(item.get("ticker")),
                exchange_code=_clean(item.get("exchCode")),
                market_sector=_clean(item.get("marketSector")),
                security_type=_clean(item.get("securityType2") or item.get("securityType")),
            )
        return mappings


def sync_sec_company_tickers(
    store: SecurityMasterStore,
    *,
    provider: SecCompanyTickerProvider | None = None,
    session: Any | None = None,
) -> SyncResult:
    started_at = _utc_now()
    try:
        records = (provider or SecCompanyTickerProvider()).fetch(session=session)
        store.replace_source("sec_edgar", records)
        result = SyncResult("sec_edgar", "success", len(records), started_at, _utc_now())
    except Exception as exc:
        result = SyncResult("sec_edgar", "error", 0, started_at, _utc_now(), str(exc)[:500])
    store.record_sync(result)
    return result


def sync_nasdaq_symbol_directory(
    store: SecurityMasterStore,
    *,
    provider: NasdaqSymbolDirectoryProvider | None = None,
    session: Any | None = None,
) -> SyncResult:
    started_at = _utc_now()
    try:
        records = (provider or NasdaqSymbolDirectoryProvider()).fetch(session=session)
        store.replace_source("nasdaq_directory", records)
        result = SyncResult("nasdaq_directory", "success", len(records), started_at, _utc_now())
    except Exception as exc:
        result = SyncResult("nasdaq_directory", "error", 0, started_at, _utc_now(), str(exc)[:500])
    store.record_sync(result)
    return result


def merge_security_records(records: Iterable[SecurityRecord]) -> list[SecurityRecord]:
    """Merge provider identities into one routeable record per engine symbol."""
    priority = {
        "curated": 100,
        "openfigi": 90,
        "sec_edgar": 85,
        "nasdaq_directory": 80,
        "coingecko": 70,
    }
    groups: dict[tuple[str, str], list[SecurityRecord]] = {}
    for record in records:
        if not record.active or not record.symbol:
            continue
        groups.setdefault((record.engine_asset.casefold(), record.symbol.casefold()), []).append(record)

    merged: list[SecurityRecord] = []
    for candidates in groups.values():
        ordered = sorted(candidates, key=lambda item: (-priority.get(item.source, 0), item.source, item.canonical_id))
        base = ordered[0]

        def first(field: str) -> str:
            return next((_clean(getattr(item, field)) for item in ordered if _clean(getattr(item, field))), "")

        tags = tuple(dict.fromkeys(tag for item in ordered for tag in item.tags if tag))
        provider_symbols = _pairs(
            (key, value) for item in ordered for key, value in item.provider_symbols
        )
        identifiers = _pairs((key, value) for item in ordered for key, value in item.identifiers)
        sources = tuple(dict.fromkeys(item.source for item in ordered))
        verified = max((item.last_verified_at for item in ordered if item.last_verified_at), default="")
        merged.append(
            SecurityRecord(
                canonical_id=base.canonical_id,
                symbol=base.symbol,
                name=base.name,
                universe=base.universe,
                engine_asset=base.engine_asset,
                region=base.region,
                currency=first("currency"),
                exchange=first("exchange"),
                mic=first("mic"),
                security_type=first("security_type"),
                source=" + ".join(sources),
                source_symbol=first("source_symbol"),
                figi=first("figi"),
                cik=first("cik"),
                tags=tags,
                provider_symbols=provider_symbols,
                identifiers=identifiers,
                routeable=any(item.routeable for item in ordered),
                active=True,
                last_verified_at=verified,
            )
        )
    return sorted(merged, key=lambda item: (item.universe, item.symbol, item.name))
