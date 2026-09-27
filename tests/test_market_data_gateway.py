import pandas as pd

from market_data_gateway import (
    fetch_frankfurter_history,
    fetch_price_history,
    fetch_twelve_data_history,
)
from market_intelligence.patterns import (
    PatternDiscoveryConfig,
    PatternRunState,
    discover_market_patterns,
)
from provider_config import configured_provider_keys, provider_matrix, resolve_secret


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_secret_resolution_prefers_explicit_mapping_then_environment(monkeypatch):
    monkeypatch.setenv("TWELVE_DATA_API_KEY", "environment")
    assert resolve_secret("TWELVE_DATA_API_KEY", {"TWELVE_DATA_API_KEY": "streamlit"}) == "streamlit"
    assert resolve_secret("TWELVE_DATA_API_KEY", {}) == "environment"
    assert configured_provider_keys({})["TWELVE_DATA_API_KEY"] is True


def test_provider_matrix_covers_every_major_routed_workspace():
    sections = {row["section"] for row in provider_matrix()}
    assert {
        "Momentum / Trend",
        "Options / Futures",
        "Correlation Matrix",
        "Risk / Backtest / Monte Carlo",
        "Company Intelligence",
        "Fixed Income & Credit",
        "Market Psychology",
        "WorldMonitor",
        "Security Master",
        "Quant AI",
    }.issubset(sections)


def test_twelve_data_adapter_normalizes_ohlcv_and_context():
    payload = {
        "status": "ok",
        "values": [
            {"datetime": "2026-08-19", "open": "100", "high": "103", "low": "99", "close": "102", "volume": "1000"},
            {"datetime": "2026-08-20", "open": "102", "high": "104", "low": "101", "close": "103", "volume": "1200"},
        ],
    }
    frame, context = fetch_twelve_data_history(
        "SPY", "1y", "1d", "secret", request_get=lambda *args, **kwargs: FakeResponse(payload)
    )
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "adj_close", "volume"]
    assert frame.iloc[-1]["close"] == 103
    assert context.provider == "Twelve Data"


def test_gateway_falls_back_without_exposing_key(monkeypatch):
    def failing_request(*args, **kwargs):
        raise TimeoutError("secret-token-must-not-appear")

    yahoo = pd.DataFrame(
        {
            "Open": [100, 101],
            "High": [102, 103],
            "Low": [99, 100],
            "Close": [101, 102],
            "Volume": [10, 11],
        },
        index=pd.to_datetime(["2026-08-19", "2026-08-20"]),
    )
    yahoo.index.name = "Date"
    frame, context = fetch_price_history(
        "SPY",
        secrets={"TWELVE_DATA_API_KEY": "secret-token-must-not-appear"},
        request_get=failing_request,
        yahoo_download=lambda *args, **kwargs: yahoo,
    )
    assert len(frame) == 2
    assert context.provider == "Yahoo Finance"
    assert context.fallback_used is True
    assert context.attempted == ("Twelve Data", "Yahoo Finance")
    assert "secret-token-must-not-appear" not in context.message
    assert frame.attrs["data_context"]["provider"] == "Yahoo Finance"


def test_close_only_gateway_marks_synthesized_execution_fields_and_patterns_block():
    def failing_request(*args, **kwargs):
        raise TimeoutError("unavailable")

    yahoo = pd.DataFrame(
        {"Close": [100.0, 101.0, 102.0]},
        index=pd.date_range("2026-08-18", periods=3, freq="D"),
    )
    yahoo.index.name = "Date"
    frame, _ = fetch_price_history(
        "SPY",
        secrets={"TWELVE_DATA_API_KEY": "configured"},
        request_get=failing_request,
        yahoo_download=lambda *args, **kwargs: yahoo,
    )

    provenance = frame.attrs["data_context"]["market_field_provenance"]
    assert provenance["open_complete"] is False
    assert provenance["open_synthesized"] is True
    assert provenance["adj_close_complete"] is False
    assert provenance["adj_close_synthesized"] is True
    assert frame.attrs["data_context"]["price_adjustment_policy"] == "UNVERIFIED_RAW_CLOSE"
    report = discover_market_patterns(frame, "SPY", PatternDiscoveryConfig())
    assert report.state == PatternRunState.BLOCKED_DATA_QUALITY
    assert "OPEN_PRICE_NOT_OBSERVED" in report.input_audit.quality_flags


def test_gateway_requires_complete_open_and_adjusted_close_provenance():
    def failing_request(*args, **kwargs):
        raise TimeoutError("unavailable")

    yahoo = pd.DataFrame(
        {
            "Open": [100.0, None, 102.0],
            "High": [102.0, 103.0, 104.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [101.0, 102.0, 103.0],
            "Adj Close": [100.5, None, 102.5],
            "Volume": [10, 11, 12],
        },
        index=pd.date_range("2026-08-18", periods=3, freq="D"),
    )
    yahoo.index.name = "Date"
    frame, _ = fetch_price_history(
        "SPY",
        secrets={"TWELVE_DATA_API_KEY": "configured"},
        request_get=failing_request,
        yahoo_download=lambda *args, **kwargs: yahoo,
    )

    provenance = frame.attrs["data_context"]["market_field_provenance"]
    assert provenance["open_observed_any"] is True
    assert provenance["open_complete"] is False
    assert provenance["adj_close_observed_any"] is True
    assert provenance["adj_close_complete"] is False
    assert frame.attrs["data_context"]["price_adjustment_policy"] == "UNVERIFIED_RAW_CLOSE"


def test_gateway_preserves_complete_provider_adjusted_close_contract():
    def failing_request(*args, **kwargs):
        raise TimeoutError("unavailable")

    yahoo = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Adj Close": [100.8, 101.8],
            "Volume": [10, 11],
        },
        index=pd.date_range("2026-08-19", periods=2, freq="D"),
    )
    yahoo.index.name = "Date"
    frame, _ = fetch_price_history(
        "SPY",
        secrets={"TWELVE_DATA_API_KEY": "configured"},
        request_get=failing_request,
        yahoo_download=lambda *args, **kwargs: yahoo,
    )

    provenance = frame.attrs["data_context"]["market_field_provenance"]
    assert provenance["open_complete"] is True
    assert provenance["adj_close_complete"] is True
    assert frame.attrs["data_context"]["price_adjustment_policy"] == "PROVIDER_ADJUSTED_CLOSE"


def test_frankfurter_reference_series_is_explicitly_synthetic_ohlc():
    payload = [
        {"date": "2026-08-19", "base": "EUR", "quote": "USD", "rate": 1.16},
        {"date": "2026-08-20", "base": "EUR", "quote": "USD", "rate": 1.17},
    ]
    frame, context = fetch_frankfurter_history(
        "EURUSD=X", "1mo", "1d", request_get=lambda *args, **kwargs: FakeResponse(payload)
    )
    assert frame["close"].tolist() == [1.16, 1.17]
    assert frame["open"].tolist() == frame["close"].tolist()
    assert context.status == "reference"
    assert "synthesized" in context.message
