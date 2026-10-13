"""Data adapters for the universal kernel and Streamlit workspace."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Mapping

import numpy as np
import pandas as pd

from .security import SecurityMaster
from .margin import MarginMethod, MarginParameterSet
from .types import (
    AssetClass,
    Instrument,
    OptionCalendarContract,
    OptionExerciseStyle,
    OptionRight,
    SettlementType,
)


@dataclass
class UniversalDataset:
    security_master: SecurityMaster
    market_data: dict[str, pd.DataFrame]
    fx_rates: dict[str, pd.Series]
    target_weights: pd.DataFrame | None = None
    target_available_at: pd.Series | None = None
    cash_rates: dict[str, pd.Series] | None = None
    option_calendars: dict[str, OptionCalendarContract] = field(default_factory=dict)


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


def _required_timestamp(value: object, timezone_name: str, field_name: str) -> datetime:
    stamp = _optional_timestamp(value, timezone_name)
    if stamp is None:
        raise ValueError(f"{field_name} is required")
    return stamp.to_pydatetime()


def _date_tuple(value: object) -> tuple[date, ...]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ()
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [item for item in str(value).split(",") if item.strip()]
    return tuple(sorted({pd.Timestamp(item).date() for item in raw_items}))


def parse_margin_parameter_set(
    payload: Mapping[str, object],
    *,
    timezone_name: str = "UTC",
) -> MarginParameterSet:
    """Normalize a future provider payload into the versioned margin contract."""

    if not isinstance(payload, Mapping):
        raise TypeError("margin parameter payload must be a mapping")
    try:
        method = MarginMethod(str(payload["method"]).strip().upper())
        parameters = payload["parameters"]
    except KeyError as exc:
        raise ValueError(f"missing margin parameter field: {exc.args[0]}") from exc
    if not isinstance(parameters, Mapping):
        raise ValueError("margin parameters must be a mapping")
    return MarginParameterSet(
        method=method,
        version=str(payload.get("version", "")),
        effective_from=_required_timestamp(
            payload.get("effective_from"), timezone_name, "effective_from"
        ),
        available_at=_required_timestamp(
            payload.get("available_at"), timezone_name, "available_at"
        ),
        source=str(payload.get("source", "")),
        source_sha256=str(payload.get("source_sha256", "")),
        official=bool(payload.get("official", False)),
        parameters=dict(parameters),
    )


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
    if (clean["symbol"] == "").any():
        raise ValueError("dataset contains an empty symbol")
    if "instrument_id" in clean:
        raw_identity = clean["instrument_id"].fillna("").astype(str).str.strip().str.upper()
        # Missing identifiers remain backward compatible with the historical
        # symbol-keyed CSV contract.  Explicit identifiers, however, are the
        # authority for contracts that share a display symbol (options,
        # futures and multi-venue listings).
        clean["_instrument_identity"] = raw_identity.where(
            raw_identity.ne(""), clean["symbol"]
        )
    else:
        clean["_instrument_identity"] = clean["symbol"]
    if clean[["timestamp", "_instrument_identity"]].duplicated().any():
        raise ValueError("duplicate timestamp/instrument_id rows")

    instruments: list[Instrument] = []
    option_calendars: dict[str, OptionCalendarContract] = {}
    market_data: dict[str, pd.DataFrame] = {}
    target_rows: list[pd.DataFrame] = []
    availability_by_event: dict[pd.Timestamp, pd.Timestamp] = {}
    for identity, group in clean.groupby("_instrument_identity", sort=True):
        symbols = tuple(sorted(set(group["symbol"].astype(str))))
        if len(symbols) != 1:
            raise ValueError(
                f"{identity}: one instrument_id maps to multiple symbols"
            )
        symbol = symbols[0]
        invariant_columns = (
            "asset_class",
            "quote_currency",
            "base_currency",
            "exchange",
            "multiplier",
            "lot_size",
            "tick_size",
            "settlement_days",
            "underlying_symbol",
            "root_symbol",
            "expiry",
            "strike",
            "option_right",
            "settlement_type",
            "option_exercise_style",
            "option_calendar_id",
            "automatic_exercise_threshold",
            "deliverable_quantity",
            "option_calendar_timezone",
            "exercise_cutoff_at",
            "settlement_at",
            "calendar_source",
            "calendar_source_version",
            "calendar_available_at",
            "early_exercise_dates",
        )
        for column in invariant_columns:
            if column not in group:
                continue
            values = {
                str(value).strip().upper()
                for value in group[column].dropna()
                if str(value).strip()
            }
            if len(values) > 1:
                raise ValueError(
                    f"{identity}: inconsistent instrument metadata for {column}"
                )
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
        exercise_style_raw = str(
            _first(group, "option_exercise_style", "")
        ).strip().upper()
        exercise_style = (
            OptionExerciseStyle(exercise_style_raw) if exercise_style_raw else None
        )
        calendar_id = str(_first(group, "option_calendar_id", "")).strip() or None
        expiry_stamp = _optional_timestamp(_first(group, "expiry"), timezone_name)
        instrument = Instrument(
            symbol=symbol,
            instrument_id=str(identity),
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
            expiry=expiry_stamp.to_pydatetime() if expiry_stamp is not None else None,
            strike=_optional_float(_first(group, "strike")),
            option_right=option_right,
            settlement_type=SettlementType(settlement_raw),
            option_exercise_style=exercise_style,
            option_calendar_id=calendar_id,
            automatic_exercise_threshold=float(
                _first(group, "automatic_exercise_threshold", 0.0)
            ),
            deliverable_quantity=_optional_float(_first(group, "deliverable_quantity")),
        )
        instruments.append(instrument)
        if calendar_id:
            if instrument.asset_class != AssetClass.OPTION:
                raise ValueError(f"{identity}: option_calendar_id requires an option")
            if instrument.expiry is None or exercise_style is None:
                raise ValueError(
                    f"{identity}: option calendar requires expiry and option_exercise_style"
                )
            calendar = OptionCalendarContract(
                calendar_id=calendar_id,
                timezone_name=str(
                    _first(group, "option_calendar_timezone", "")
                ).strip(),
                expiration_at=instrument.expiry,
                exercise_cutoff_at=_required_timestamp(
                    _first(group, "exercise_cutoff_at"),
                    timezone_name,
                    "exercise_cutoff_at",
                ),
                settlement_at=_required_timestamp(
                    _first(group, "settlement_at"), timezone_name, "settlement_at"
                ),
                exercise_style=exercise_style,
                source=str(_first(group, "calendar_source", "")),
                source_version=str(_first(group, "calendar_source_version", "")),
                available_at=_required_timestamp(
                    _first(group, "calendar_available_at"),
                    timezone_name,
                    "calendar_available_at",
                ),
                early_exercise_dates=_date_tuple(
                    _first(group, "early_exercise_dates")
                ),
            )
            prior_calendar = option_calendars.get(calendar_id)
            if prior_calendar is not None and prior_calendar != calendar:
                raise ValueError(f"{identity}: conflicting option calendar contract")
            option_calendars[calendar_id] = calendar
        metadata_columns = {
            "timestamp", "symbol", "instrument_id", "asset_class", "quote_currency",
            "base_currency", "exchange", "multiplier", "lot_size", "tick_size",
            "settlement_days", "initial_margin_rate", "maintenance_margin_rate",
            "underlying_symbol", "root_symbol", "expiry", "strike", "option_right",
            "settlement_type", "fx_to_base", "target_weight", "target_available_at",
            "option_exercise_style", "option_calendar_id",
            "automatic_exercise_threshold", "deliverable_quantity",
            "option_calendar_timezone", "exercise_cutoff_at", "settlement_at",
            "calendar_source", "calendar_source_version", "calendar_available_at",
            "early_exercise_dates", "cash_rate_annual", "_instrument_identity",
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
        option_calendars,
    )


def single_asset_dataset(
    symbol: str,
    bars: pd.DataFrame,
    *,
    currency: str = "USD",
    asset_class: AssetClass = AssetClass.EQUITY,
    settlement_days: int = 1,
    instrument_id: str | None = None,
    exchange: str = "UNKNOWN",
    multiplier: float = 1.0,
    lot_size: float | None = None,
    tick_size: float = 0.01,
    base_currency: str | None = None,
    underlying_symbol: str | None = None,
    root_symbol: str | None = None,
    expiry: datetime | None = None,
    strike: float | None = None,
    option_right: OptionRight | None = None,
    settlement_type: SettlementType = SettlementType.CASH,
    option_exercise_style: OptionExerciseStyle | None = None,
    option_calendar: OptionCalendarContract | None = None,
    automatic_exercise_threshold: float = 0.0,
    deliverable_quantity: float | None = None,
    initial_margin_rate: float | None = None,
    maintenance_margin_rate: float | None = None,
) -> UniversalDataset:
    derivative_lot = asset_class in {AssetClass.FUTURE, AssetClass.OPTION}
    instrument = Instrument(
        symbol=str(symbol).upper(),
        instrument_id=str(instrument_id or symbol).upper(),
        asset_class=asset_class,
        quote_currency=str(currency).upper(),
        base_currency=(str(base_currency).upper() if base_currency else None),
        exchange=str(exchange),
        multiplier=float(multiplier),
        settlement_days=int(settlement_days),
        lot_size=float(lot_size if lot_size is not None else (1.0 if derivative_lot else 1e-8)),
        tick_size=float(tick_size),
        underlying_symbol=underlying_symbol,
        root_symbol=root_symbol,
        expiry=expiry,
        strike=strike,
        option_right=option_right,
        settlement_type=settlement_type,
        option_exercise_style=(
            option_calendar.exercise_style if option_calendar else option_exercise_style
        ),
        option_calendar_id=option_calendar.calendar_id if option_calendar else None,
        automatic_exercise_threshold=automatic_exercise_threshold,
        deliverable_quantity=deliverable_quantity,
        initial_margin_rate=initial_margin_rate,
        maintenance_margin_rate=maintenance_margin_rate,
    )
    return UniversalDataset(
        SecurityMaster([instrument]),
        {instrument.key: bars.copy()},
        {},
        option_calendars=(
            {option_calendar.calendar_id: option_calendar} if option_calendar else {}
        ),
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
