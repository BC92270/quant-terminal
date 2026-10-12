"""Data adapters for the universal kernel and Streamlit workspace."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Mapping

import numpy as np
import pandas as pd

from .security import SecurityMaster
from .types import AssetClass, Instrument, OptionRight, SettlementType


@dataclass
class UniversalDataset:
    security_master: SecurityMaster
    market_data: dict[str, pd.DataFrame]
    fx_rates: dict[str, pd.Series]
    target_weights: pd.DataFrame | None = None
    target_available_at: pd.Series | None = None
    cash_rates: dict[str, pd.Series] | None = None


def _first(group: pd.DataFrame, column: str, default: object = None) -> object:
    if column not in group:
        return default
    values = group[column].dropna()
    return values.iloc[0] if not values.empty else default


def _optional_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _optional_timestamp(value: object, timezone_name: str) -> pd.Timestamp | None:
    if value is None or (isinstance(value, float) and np.isnan(value)) or not str(value).strip():
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(timezone_name)
    return stamp.tz_convert("UTC")


def parse_long_dataset(
    frame: pd.DataFrame,
    *,
    base_currency: str,
    timezone_name: str = "UTC",
) -> UniversalDataset:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("universal dataset is empty")
    clean = frame.copy()
    clean.columns = [str(column).strip().lower().replace(" ", "_") for column in clean.columns]
    required = {
        "timestamp", "symbol", "asset_class", "quote_currency",
        "open", "high", "low", "close",
    }
    missing = sorted(required.difference(clean.columns))
    if missing:
        raise ValueError("missing universal dataset fields: " + ", ".join(missing))
    timestamps = pd.to_datetime(clean["timestamp"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("dataset contains invalid timestamps")
    if timestamps.dt.tz is None:
        timestamps = timestamps.dt.tz_localize(
            timezone_name, ambiguous="raise", nonexistent="raise"
        )
    clean["timestamp"] = timestamps.dt.tz_convert("UTC")
    clean["symbol"] = clean["symbol"].astype(str).str.strip().str.upper()
    if clean[["timestamp", "symbol"]].duplicated().any():
        raise ValueError("duplicate timestamp/symbol rows")

    instruments: list[Instrument] = []
    market_data: dict[str, pd.DataFrame] = {}
    target_rows: list[pd.DataFrame] = []
    availability_by_event: dict[pd.Timestamp, pd.Timestamp] = {}
    for symbol, group in clean.groupby("symbol", sort=True):
        asset_value = str(_first(group, "asset_class", "EQUITY")).strip().upper()
        try:
            asset_class = AssetClass(asset_value)
        except ValueError as exc:
            raise ValueError(f"{symbol}: unsupported asset_class {asset_value}") from exc
        quote = str(_first(group, "quote_currency", "")).strip().upper()
        base = _first(group, "base_currency")
        option_right_raw = str(_first(group, "option_right", "")).strip().upper()
        option_right = OptionRight(option_right_raw) if option_right_raw else None
        settlement_raw = str(_first(group, "settlement_type", "CASH")).strip().upper()
        instrument = Instrument(
            symbol=symbol,
            instrument_id=str(_first(group, "instrument_id", symbol)).strip().upper(),
            asset_class=asset_class,
            quote_currency=quote,
            base_currency=str(base).strip().upper() if base is not None and str(base).strip() else None,
            exchange=str(_first(group, "exchange", "UNKNOWN")),
            multiplier=float(_first(group, "multiplier", 1.0)),
            lot_size=float(_first(group, "lot_size", 1.0)),
            tick_size=float(_first(group, "tick_size", 0.01)),
            settlement_days=int(float(_first(group, "settlement_days", 0))),
            initial_margin_rate=_optional_float(_first(group, "initial_margin_rate")),
            maintenance_margin_rate=_optional_float(_first(group, "maintenance_margin_rate")),
            underlying_symbol=(
                str(_first(group, "underlying_symbol", "")).strip().upper() or None
            ),
            root_symbol=str(_first(group, "root_symbol", "")).strip().upper() or None,
            expiry=(
                _optional_timestamp(_first(group, "expiry"), timezone_name).to_pydatetime()
                if _optional_timestamp(_first(group, "expiry"), timezone_name) is not None
                else None
            ),
            strike=_optional_float(_first(group, "strike")),
            option_right=option_right,
            settlement_type=SettlementType(settlement_raw),
        )
        instruments.append(instrument)
        metadata_columns = {
            "timestamp", "symbol", "instrument_id", "asset_class", "quote_currency",
            "base_currency", "exchange", "multiplier", "lot_size", "tick_size",
            "settlement_days", "initial_margin_rate", "maintenance_margin_rate",
            "underlying_symbol", "root_symbol", "expiry", "strike", "option_right",
            "settlement_type", "fx_to_base", "target_weight", "target_available_at",
            "cash_rate_annual",
        }
        bars = group.drop(columns=[c for c in metadata_columns if c in group.columns]).copy()
        bars.index = pd.DatetimeIndex(group["timestamp"])
        bars = bars.drop(columns=["timestamp"], errors="ignore").sort_index()
        market_data[instrument.key] = bars

        if "target_weight" in group:
            target = pd.DataFrame(
                {instrument.key: pd.to_numeric(group["target_weight"], errors="coerce").to_numpy()},
                index=pd.DatetimeIndex(group["timestamp"]),
            )
            target_rows.append(target)
            if "target_available_at" in group:
                available_values = pd.to_datetime(
                    group["target_available_at"], errors="coerce"
                )
                if available_values.isna().any():
                    raise ValueError(f"{symbol}: invalid target_available_at")
                if available_values.dt.tz is None:
                    available_values = available_values.dt.tz_localize(timezone_name)
                for event_time, available_at in zip(
                    pd.DatetimeIndex(group["timestamp"]),
                    available_values.dt.tz_convert("UTC"),
                ):
                    prior = availability_by_event.get(event_time)
                    if prior is not None and prior != available_at:
                        raise ValueError(
                            "all targets at one event timestamp require the same available_at"
                        )
                    availability_by_event[event_time] = pd.Timestamp(available_at)

    master = SecurityMaster(instruments)
    fx_rates: dict[str, pd.Series] = {}
    for currency, group in clean.groupby("quote_currency", sort=True):
        code = str(currency).strip().upper()
        if code == str(base_currency).strip().upper():
            continue
        if "fx_to_base" not in group:
            raise ValueError(f"DATA REQUIRED: fx_to_base missing for {code}")
        rate_frame = group[["timestamp", "fx_to_base"]].drop_duplicates("timestamp")
        rates = pd.Series(
            pd.to_numeric(rate_frame["fx_to_base"], errors="coerce").to_numpy(),
            index=pd.DatetimeIndex(rate_frame["timestamp"]),
        ).dropna()
        if rates.empty:
            raise ValueError(f"DATA REQUIRED: FX history missing for {code}")
        fx_rates[f"{code}/{str(base_currency).strip().upper()}"] = rates

    targets = None
    target_available = None
    if target_rows:
        targets = pd.concat(target_rows, axis=1).sort_index()
        if availability_by_event:
            target_available = pd.Series(availability_by_event).sort_index()
            target_available = target_available.reindex(targets.index)
            defaults = pd.Series(targets.index, index=targets.index)
            target_available = target_available.where(target_available.notna(), defaults)
    cash_rates: dict[str, pd.Series] = {}
    if "cash_rate_annual" in clean:
        for currency, group in clean.groupby("quote_currency", sort=True):
            rate_frame = group[["timestamp", "cash_rate_annual"]].drop_duplicates(
                "timestamp"
            )
            rates = pd.Series(
                pd.to_numeric(rate_frame["cash_rate_annual"], errors="coerce").to_numpy(),
                index=pd.DatetimeIndex(rate_frame["timestamp"]),
            ).dropna()
            if not rates.empty:
                cash_rates[str(currency).strip().upper()] = rates
    return UniversalDataset(
        master,
        market_data,
        fx_rates,
        targets,
        target_available,
        cash_rates,
    )


def single_asset_dataset(
    symbol: str,
    bars: pd.DataFrame,
    *,
    currency: str = "USD",
    asset_class: AssetClass = AssetClass.EQUITY,
    settlement_days: int = 1,
) -> UniversalDataset:
    instrument = Instrument(
        symbol=str(symbol).upper(),
        instrument_id=str(symbol).upper(),
        asset_class=asset_class,
        quote_currency=str(currency).upper(),
        settlement_days=int(settlement_days),
        lot_size=1e-8,
    )
    return UniversalDataset(
        SecurityMaster([instrument]),
        {instrument.key: bars.copy()},
        {},
    )


def build_sma_targets(
    market_data: Mapping[str, pd.DataFrame],
    *,
    fast: int = 20,
    slow: int = 100,
    gross_weight: float = 1.0,
) -> pd.DataFrame:
    if int(fast) < 1 or int(slow) <= int(fast):
        raise ValueError("SMA windows require 1 <= fast < slow")
    if not market_data:
        raise ValueError("market_data is empty")
    weight = float(gross_weight) / len(market_data)
    columns: list[pd.Series] = []
    for key, frame in sorted(market_data.items()):
        lookup = {str(column).strip().lower(): column for column in frame.columns}
        if "close" not in lookup:
            raise ValueError(f"{key}: close is required")
        close = pd.to_numeric(frame[lookup["close"]], errors="coerce")
        fast_average = close.rolling(int(fast), min_periods=int(fast)).mean()
        slow_average = close.rolling(int(slow), min_periods=int(slow)).mean()
        target = (fast_average > slow_average).astype(float) * weight
        target[(fast_average.isna()) | (slow_average.isna())] = 0.0
        target.name = key
        columns.append(target)
    return pd.concat(columns, axis=1).sort_index()


def universal_csv_template() -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-02", periods=4, freq="B", tz=timezone.utc)
    return pd.DataFrame(
        {
            "timestamp": list(timestamps) * 2,
            "symbol": ["SPY"] * 4 + ["EWG"] * 4,
            "instrument_id": ["ARCX:SPY"] * 4 + ["XETR:EWG"] * 4,
            "asset_class": ["ETF"] * 8,
            "quote_currency": ["USD"] * 4 + ["EUR"] * 4,
            "exchange": ["ARCX"] * 4 + ["XETR"] * 4,
            "open": [500, 502, 501, 503, 32, 32.4, 32.2, 32.3],
            "high": [503, 504, 503, 505, 32.5, 32.6, 32.4, 32.5],
            "low": [498, 500, 499, 501, 31.8, 32.0, 31.9, 32.0],
            "close": [502, 501, 503, 504, 32.4, 32.2, 32.3, 32.4],
            "volume": [1_000_000] * 8,
            "fx_to_base": [1.0] * 4 + [1.08, 1.085, 1.082, 1.084],
            "target_weight": [0.45, 0.45, 0.0, np.nan, 0.45, 0.45, 0.0, np.nan],
            "target_available_at": list(timestamps) * 2,
            "cash_rate_annual": [0.04] * 4 + [0.03] * 4,
        }
    )
