from datetime import datetime, timedelta, timezone

import pytest

from security_master import (
    OpenFigiProvider,
    NasdaqSymbolDirectoryProvider,
    PROVIDER_CANDIDATES,
    SecCompanyTickerProvider,
    SecurityMasterStore,
    SecurityRecord,
    SyncResult,
    merge_security_records,
    normalize_us_market_symbol,
    provider_matrix,
    sync_sec_company_tickers,
    sync_nasdaq_symbol_directory,
)


class _Response:
    def __init__(self, payload=None, text=""):
        self.payload = payload
        self.text = text

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _SecSession:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def get(self, url, *, headers, timeout):
        self.request = {"url": url, "headers": headers, "timeout": timeout}
        return _Response(self.payload)


class _FigiSession:
    def __init__(self, payload):
        self.payload = payload
        self.request = None

    def post(self, url, *, headers, json, timeout):
        self.request = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return _Response(self.payload)


class _DirectorySession:
    def __init__(self, nasdaq_text: str, other_text: str):
        self.nasdaq_text = nasdaq_text
        self.other_text = other_text

    def get(self, url, *, headers, timeout):
        text = self.nasdaq_text if url.endswith("nasdaqlisted.txt") else self.other_text
        return _Response(text=text)


def _record(
    canonical_id: str,
    symbol: str,
    *,
    source: str = "curated",
    name: str = "Example",
    tags: tuple[str, ...] = (),
    exchange: str = "",
    cik: str = "",
) -> SecurityRecord:
    return SecurityRecord(
        canonical_id=canonical_id,
        symbol=symbol,
        name=name,
        universe="Equities",
        engine_asset="Equity",
        region="United States",
        source=source,
        exchange=exchange,
        cik=cik,
        tags=tags,
    )


def test_store_round_trip_replace_and_health(tmp_path) -> None:
    store = SecurityMasterStore(tmp_path / "master.sqlite3")
    assert store.upsert_records((_record("curated:aapl", "AAPL"),)) == 1
    assert store.replace_source(
        "sec_edgar",
        (_record("sec:1:aapl", "AAPL", source="sec_edgar", exchange="Nasdaq", cik="1"),),
    ) == 1

    records = store.all_records()
    assert len(records) == 2
    assert {record.source for record in records} == {"curated", "sec_edgar"}
    assert store.health() == {
        "path": str(tmp_path / "master.sqlite3"),
        "schema_version": 1,
        "raw_records": 2,
        "sources": {"curated": 1, "sec_edgar": 1},
        "integrity": "ok",
    }

    store.replace_source("sec_edgar", ())
    assert [record.source for record in store.all_records()] == ["curated"]


def test_merge_preserves_curated_metadata_and_adds_provider_identity() -> None:
    curated = _record("curated:aapl", "AAPL", name="Apple", tags=("technology", "mega cap"))
    sec = _record(
        "sec:320193:aapl",
        "AAPL",
        source="sec_edgar",
        name="APPLE INC",
        exchange="Nasdaq",
        cik="320193",
        tags=("SEC filer", "Nasdaq"),
    )

    merged = merge_security_records((sec, curated))
    assert len(merged) == 1
    assert merged[0].name == "Apple"
    assert merged[0].exchange == "Nasdaq"
    assert merged[0].cik == "320193"
    assert merged[0].source == "curated + sec_edgar"
    assert merged[0].tags == ("technology", "mega cap", "SEC filer", "Nasdaq")


def test_sec_provider_normalizes_tickers_and_records_sync(tmp_path) -> None:
    session = _SecSession(
        {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [
                [1067983, "BERKSHIRE HATHAWAY INC", "BRK.B", "NYSE"],
                [320193, "APPLE INC", "AAPL", "Nasdaq"],
            ],
        }
    )
    store = SecurityMasterStore(tmp_path / "master.sqlite3")
    result = sync_sec_company_tickers(
        store,
        provider=SecCompanyTickerProvider(user_agent="Example example@example.com"),
        session=session,
    )

    assert result.status == "success"
    assert result.records == 2
    assert session.request["headers"]["User-Agent"] == "Example example@example.com"
    records = store.all_records()
    assert {record.symbol for record in records} == {"AAPL", "BRK-B"}
    assert all(record.currency == "USD" and record.routeable for record in records)
    assert store.latest_sync("sec_edgar") == result
    assert normalize_us_market_symbol("brk/b") == "BRK-B"


def test_nasdaq_directory_adds_listed_equities_and_etfs(tmp_path) -> None:
    session = _DirectorySession(
        "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
        "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
        "QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N\n"
        "TEST|Test Security|Q|Y|N|100|N|N\n"
        "File Creation Time: 0820202621:00|||||||\n",
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "BRK.B|Berkshire Hathaway Class B|N|BRK.B|N|100|N|BRK.B\n"
        "SPY|SPDR S&P 500 ETF Trust|P|SPY|Y|100|N|SPY\n"
        "File Creation Time: 0820202621:00|||||||\n",
    )
    store = SecurityMasterStore(tmp_path / "master.sqlite3")
    result = sync_nasdaq_symbol_directory(
        store,
        provider=NasdaqSymbolDirectoryProvider(),
        session=session,
    )

    assert result.status == "success"
    assert result.records == 4
    records = {record.symbol: record for record in store.all_records()}
    assert records["AAPL"].universe == "Equities"
    assert records["QQQ"].universe == "ETFs"
    assert records["SPY"].exchange == "NYSE Arca"
    assert records["BRK-B"].source_symbol == "BRK.B"


def test_store_refresh_policy_uses_short_failure_cooldown(tmp_path) -> None:
    store = SecurityMasterStore(tmp_path / "master.sqlite3")
    finished = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    store.record_sync(SyncResult("sec_edgar", "error", 0, finished.isoformat(), finished.isoformat(), "offline"))

    assert not store.source_needs_refresh(
        "sec_edgar",
        failure_ttl_seconds=900,
        now=finished + timedelta(minutes=10),
    )
    assert store.source_needs_refresh(
        "sec_edgar",
        failure_ttl_seconds=900,
        now=finished + timedelta(minutes=16),
    )


def test_openfigi_mapping_uses_v3_and_parses_reference_identity() -> None:
    session = _FigiSession(
        [
            {
                "data": [
                    {
                        "figi": "BBG000B9XRY4",
                        "compositeFIGI": "BBG000B9XRY4",
                        "name": "APPLE INC",
                        "ticker": "AAPL",
                        "exchCode": "US",
                        "marketSector": "Equity",
                        "securityType2": "Common Stock",
                    }
                ]
            }
        ]
    )
    mappings = OpenFigiProvider().map_tickers(("AAPL",), session=session)

    assert mappings["AAPL"].figi == "BBG000B9XRY4"
    assert mappings["AAPL"].security_type == "Common Stock"
    assert session.request["url"].endswith("/v3/mapping")
    assert session.request["json"] == [{"idType": "TICKER", "idValue": "AAPL", "exchCode": "US"}]
    with pytest.raises(ValueError, match="at most 10"):
        OpenFigiProvider().map_tickers(tuple(f"T{i}" for i in range(11)), session=session)


def test_provider_matrix_is_role_separated_and_configuration_aware() -> None:
    matrix = provider_matrix()
    assert len(matrix) == len(PROVIDER_CANDIDATES)
    assert {row["provider_id"] for row in matrix} >= {
        "sec_edgar",
        "nasdaq_directory",
        "openfigi",
        "databento",
        "twelve_data",
        "frankfurter",
        "coingecko",
    }
    assert next(row for row in matrix if row["provider_id"] == "sec_edgar")["mode"] == "active"
    assert next(row for row in matrix if row["provider_id"] == "openfigi")["role"] == "global symbology"
