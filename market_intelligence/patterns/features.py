"""Causal OHLCV normalization and feature construction for pattern research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .contracts import (
    ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES,
    ADMISSIBLE_REVISION_POLICIES,
    PatternDiscoveryConfig,
    PatternInputAudit,
)


_MARKET_COLUMNS = ("open", "high", "low", "close", "adj_close", "volume")


@dataclass(frozen=True)
class PatternFeatureBundle:
    market: pd.DataFrame
    features: pd.DataFrame
    labels: pd.DataFrame
    forward_returns: pd.Series
    current_features: pd.DataFrame
    audit: PatternInputAudit


def _utc_datetime(value: Any) -> datetime:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    else:
        stamp = stamp.tz_convert("UTC")
    return stamp.to_pydatetime().astimezone(timezone.utc)


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if isinstance(output.columns, pd.MultiIndex):
        flattened: list[str] = []
        for column in output.columns:
            parts = [str(item).strip() for item in column if str(item).strip()]
            flattened.append("_".join(parts).lower().replace(" ", "_"))
        output.columns = flattened
    else:
        output.columns = [str(column).strip().lower().replace(" ", "_") for column in output.columns]
    return output


def _resolve_column(columns: list[str], name: str) -> str | None:
    exact = next((column for column in columns if column == name), None)
    if exact is not None:
        return exact
    if name == "date":
        return next((column for column in columns if column in {"datetime", "timestamp", "time"}), None)
    candidates = [
        column
        for column in columns
        if column.startswith(name + "_") or column.endswith("_" + name)
    ]
    return candidates[0] if candidates else None


def _source_context(price_data: Any) -> dict[str, Any]:
    attrs = getattr(price_data, "attrs", {})
    raw = attrs.get("data_context", {}) if isinstance(attrs, Mapping) else {}
    context = dict(raw) if isinstance(raw, Mapping) else {}
    provider = str(
        context.get("provider") or attrs.get("provider") or "UNIDENTIFIED_INHERITED_FRAME"
    ).strip()
    source_symbol = str(
        context.get("symbol")
        or context.get("ticker")
        or attrs.get("symbol")
        or attrs.get("ticker")
        or "UNDECLARED"
    ).upper().strip()
    status = str(context.get("status") or attrs.get("source_status") or "UNDECLARED")
    recency = str(context.get("recency") or attrs.get("recency") or "UNDECLARED")
    raw_known_at = context.get("known_at") or attrs.get("known_at")
    known_at = None
    if raw_known_at is not None:
        try:
            parsed = pd.Timestamp(raw_known_at)
            if parsed.tzinfo is not None:
                known_at = parsed.tz_convert("UTC").to_pydatetime()
        except (TypeError, ValueError):
            known_at = None
    point_in_time = context.get("point_in_time") is True or attrs.get("point_in_time") is True
    revisions = str(
        context.get("revision_policy") or attrs.get("revision_policy") or "UNDECLARED"
    ).upper().strip()
    raw_provenance = context.get("market_field_provenance") or attrs.get(
        "market_field_provenance"
    )
    field_provenance = dict(raw_provenance) if isinstance(raw_provenance, Mapping) else {}
    adjustment_policy = str(
        context.get("price_adjustment_policy")
        or attrs.get("price_adjustment_policy")
        or "UNDECLARED"
    ).upper().strip()
    return {
        "provider": provider,
        "source_symbol": source_symbol,
        "status": status,
        "recency": recency,
        "fallback_used": context.get("fallback_used") is True or attrs.get("fallback_used") is True,
        "source_identified": provider.upper()
        not in {"UNIDENTIFIED_INHERITED_FRAME", "UNKNOWN", "UNDECLARED"},
        "point_in_time_declared": point_in_time,
        "known_at": known_at,
        "revision_policy": revisions,
        "price_adjustment_policy": adjustment_policy,
        "market_field_provenance": field_provenance,
    }


def _empty_audit(
    symbol: str,
    *,
    raw_rows: int,
    source: Mapping[str, Any],
    reasons: tuple[str, ...],
    flags: tuple[str, ...] = (),
) -> PatternInputAudit:
    digest = hashlib.sha256(
        (
            f"{str(symbol).upper().strip()}|EMPTY|{raw_rows}|{source['provider']}|{source['status']}|"
            f"{source['source_symbol']}|{source['recency']}|{source['known_at']}|"
            f"{source['revision_policy']}|{source['price_adjustment_policy']}|"
            f"{source['point_in_time_declared']}|{source['fallback_used']}|"
            f"{source['market_field_provenance']}"
        ).encode("utf-8")
    ).hexdigest()
    return PatternInputAudit(
        symbol=str(symbol).upper().strip(),
        source_symbol=str(source["source_symbol"]),
        subject_match=str(source["source_symbol"]) == str(symbol).upper().strip(),
        dataset_id=digest,
        source=str(source["provider"]),
        source_status=str(source["status"]),
        recency=str(source["recency"]),
        source_known_at=source["known_at"],
        latest_row_known_at=None,
        revision_policy=str(source["revision_policy"]),
        price_adjustment_policy=str(source["price_adjustment_policy"]),
        open_price_observed=False,
        high_low_observed=False,
        adjusted_close_observed=False,
        corporate_action_safe=False,
        raw_rows=raw_rows,
        normalized_rows=0,
        first_observation=None,
        data_cutoff=None,
        chronological=False,
        unique_timestamps=False,
        source_identified=bool(source["source_identified"]),
        point_in_time_declared=bool(source["point_in_time_declared"]),
        row_lineage_complete=False,
        pit_lineage_complete=False,
        fallback_used=bool(source["fallback_used"]),
        quality_flags=flags,
        blocking_reasons=reasons,
    )


def normalize_price_history(price_data: Any, symbol: str) -> tuple[pd.DataFrame, PatternInputAudit]:
    """Normalize inherited OHLCV without making provider or recency claims."""

    source = _source_context(price_data)
    expected_symbol = str(symbol).upper().strip()
    raw_rows = int(len(price_data)) if isinstance(price_data, pd.DataFrame) else 0
    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return pd.DataFrame(), _empty_audit(
            symbol,
            raw_rows=raw_rows,
            source=source,
            reasons=("No inherited terminal OHLCV frame is available.",),
            flags=("NO_MARKET_HISTORY",),
        )

    frame = _flatten_columns(price_data)
    columns = list(frame.columns)
    declared_provenance = source["market_field_provenance"]

    def observed_field(name: str) -> bool:
        declared_complete = declared_provenance.get(f"{name}_complete")
        if type(declared_complete) is bool:
            return declared_complete
        declared = declared_provenance.get(f"{name}_observed")
        if type(declared) is bool:
            return declared
        column = _resolve_column(columns, name)
        if column is None and name == "adj_close":
            column = _resolve_column(columns, "adjusted_close")
        return bool(
            column is not None
            and pd.to_numeric(frame[column], errors="coerce").notna().all()
        )

    open_price_observed = observed_field("open")
    high_low_observed = observed_field("high") and observed_field("low")
    adjusted_close_observed = observed_field("adj_close")
    price_adjustment_policy = str(source["price_adjustment_policy"])
    if price_adjustment_policy == "UNDECLARED" and adjusted_close_observed:
        price_adjustment_policy = "DECLARED_ADJUSTED_CLOSE_SERIES"
    corporate_action_safe = bool(
        price_adjustment_policy in ADMISSIBLE_PRICE_ADJUSTMENT_POLICIES
        and (
            adjusted_close_observed
            or price_adjustment_policy == "NATIVE_NON_CORPORATE_ACTION_SERIES"
        )
    )
    date_column = _resolve_column(columns, "date")
    close_column = _resolve_column(columns, "close") or _resolve_column(columns, "price")
    if date_column is not None:
        timestamps = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
    elif isinstance(frame.index, pd.DatetimeIndex):
        timestamps = pd.Series(pd.to_datetime(frame.index, errors="coerce", utc=True), index=frame.index)
    else:
        return pd.DataFrame(), _empty_audit(
            symbol,
            raw_rows=raw_rows,
            source=source,
            reasons=("A parseable date, datetime, timestamp column or DatetimeIndex is required.",),
            flags=("MISSING_TIME_AXIS",),
        )
    if close_column is None:
        return pd.DataFrame(), _empty_audit(
            symbol,
            raw_rows=raw_rows,
            source=source,
            reasons=("A close or price column is required.",),
            flags=("MISSING_CLOSE",),
        )

    normalized = pd.DataFrame({"timestamp": timestamps.to_numpy()})
    open_source_missing = not open_price_observed
    adjusted_close_source = _resolve_column(columns, "adj_close") or _resolve_column(
        columns, "adjusted_close"
    )
    for name in _MARKET_COLUMNS:
        source_column = _resolve_column(columns, name)
        if source_column is None and name == "adj_close":
            source_column = _resolve_column(columns, "adjusted_close")
        normalized[name] = (
            pd.to_numeric(frame[source_column], errors="coerce").to_numpy()
            if source_column is not None
            else np.nan
        )
    row_known_column = _resolve_column(columns, "known_at")
    revision_column = _resolve_column(columns, "revision_id")
    normalized["known_at"] = (
        pd.to_datetime(frame[row_known_column], errors="coerce", utc=True).to_numpy()
        if row_known_column is not None
        else pd.NaT
    )
    normalized["revision_id"] = (
        frame[revision_column].astype("string").fillna("").to_numpy()
        if revision_column is not None
        else ""
    )
    open_invalid = ~np.isfinite(normalized["open"]) | normalized["open"].le(0.0)
    adjusted_close_partial = bool(
        adjusted_close_source is not None and normalized["adj_close"].isna().any()
    )
    adjusted_close_invalid = normalized["adj_close"].notna() & (
        ~np.isfinite(normalized["adj_close"]) | normalized["adj_close"].le(0.0)
    )
    normalized["adj_close"] = normalized["adj_close"].where(
        normalized["adj_close"].notna(), normalized["close"]
    )
    for name in ("open", "high", "low"):
        normalized[name] = normalized[name].where(normalized[name].notna(), normalized["close"])
    normalized = normalized.replace([np.inf, -np.inf], np.nan).dropna(subset=["timestamp", "close"])
    chronological_input = bool(normalized["timestamp"].is_monotonic_increasing)
    unique_input = bool(not normalized["timestamp"].duplicated().any())
    normalized = (
        normalized.sort_values("timestamp")
        .drop_duplicates("timestamp", keep="last")
        .reset_index(drop=True)
    )
    flags: list[str] = []
    reasons: list[str] = []
    subject_match = source["source_symbol"] == expected_symbol
    if source["source_symbol"] == "UNDECLARED":
        reasons.append("The inherited dataset does not declare its instrument symbol.")
        flags.append("DATASET_SUBJECT_UNVERIFIED")
    elif not subject_match:
        reasons.append(
            f"Dataset subject {source['source_symbol']} does not match requested subject {expected_symbol}."
        )
        flags.append("DATASET_SUBJECT_MISMATCH")
    if open_source_missing:
        reasons.append("An observed open series is required for next-bar execution-lag outcomes.")
        flags.append("OPEN_PRICE_NOT_OBSERVED")
    elif open_invalid.any():
        reasons.append("Every row requires a finite, strictly positive next-bar open price.")
        flags.append("INVALID_NEXT_BAR_ENTRY_PRICE")
    if adjusted_close_invalid.any():
        reasons.append("Adjusted-close values, when declared, must be strictly positive.")
        flags.append("INVALID_ADJUSTED_CLOSE")
    if adjusted_close_partial:
        reasons.append("A declared adjusted-close series cannot be partially missing.")
        flags.append("PARTIAL_ADJUSTED_CLOSE")
    if not corporate_action_safe:
        reasons.append(
            "Observed adjusted-close provenance or an admissible non-corporate-action price policy is required."
        )
        flags.append("CORPORATE_ACTION_ADJUSTMENT_UNVERIFIED")
    if not high_low_observed:
        flags.append("HIGH_LOW_NOT_OBSERVED")
    if not chronological_input:
        flags.append("INPUT_REORDERED_CHRONOLOGICALLY")
    if not unique_input:
        flags.append("DUPLICATE_TIMESTAMPS_DEDUPLICATED")
    invalid_close = normalized["close"].le(0.0) | normalized["close"].isna()
    if invalid_close.any():
        reasons.append("Close prices must be finite and strictly positive.")
        flags.append("INVALID_CLOSE")
        normalized = normalized.loc[~invalid_close].reset_index(drop=True)
    high_low_invalid = normalized["high"].lt(normalized["low"])
    if high_low_invalid.any():
        reasons.append("At least one high value is below its corresponding low value.")
        flags.append("INVALID_HIGH_LOW")
    if not source["source_identified"]:
        flags.append("SOURCE_UNIDENTIFIED")
    if source["fallback_used"]:
        flags.append("PROVIDER_FALLBACK")
    data_cutoff = _utc_datetime(normalized["timestamp"].iloc[-1]) if not normalized.empty else None
    row_known = pd.to_datetime(normalized["known_at"], errors="coerce", utc=True)
    revisions = normalized["revision_id"].astype(str).str.strip()
    timestamp_axis = pd.to_datetime(normalized["timestamp"], errors="coerce", utc=True)
    decision_deadlines = timestamp_axis.shift(-1)
    if len(decision_deadlines) and source["known_at"] is not None:
        decision_deadlines.iloc[-1] = pd.Timestamp(source["known_at"])
    late_known_rows = row_known.notna() & decision_deadlines.notna() & (
        row_known > decision_deadlines
    )
    early_known_rows = row_known.notna() & timestamp_axis.notna() & (
        row_known < timestamp_axis
    )
    known_before_next_open = bool(
        len(normalized)
        and decision_deadlines.notna().all()
        and row_known.notna().all()
        and (row_known <= decision_deadlines).all()
    )
    row_lineage_complete = bool(
        len(normalized)
        and row_known.notna().all()
        and revisions.ne("").all()
        and (row_known >= pd.to_datetime(normalized["timestamp"], utc=True)).all()
        and known_before_next_open
    )
    latest_row_known_at = _utc_datetime(row_known.max()) if row_known.notna().any() else None
    if not row_lineage_complete:
        flags.append("ROW_LINEAGE_INCOMPLETE")
    if late_known_rows.any():
        flags.append("ROW_KNOWN_AFTER_NEXT_OPEN")
        reasons.append(
            "At least one row was declared known only after its next observed execution open."
        )
    if early_known_rows.any():
        flags.append("ROW_KNOWN_BEFORE_OBSERVATION")
        reasons.append(
            "At least one row was declared known before its own market observation existed."
        )
    pit_lineage_complete = bool(
        source["source_identified"]
        and subject_match
        and source["point_in_time_declared"]
        and source["known_at"] is not None
        and row_lineage_complete
        and latest_row_known_at is not None
        and data_cutoff is not None
        and source["known_at"] >= data_cutoff
        and source["known_at"] >= latest_row_known_at
        and source["revision_policy"] in ADMISSIBLE_REVISION_POLICIES
    )
    if not pit_lineage_complete:
        flags.append("PIT_LINEAGE_INCOMPLETE")

    if normalized.empty:
        return pd.DataFrame(), _empty_audit(
            symbol,
            raw_rows=raw_rows,
            source=source,
            reasons=tuple(reasons or ["No usable observations remain after normalization."]),
            flags=tuple(flags),
        )

    indexed = normalized.set_index("timestamp")
    digest = hashlib.sha256()
    digest.update(b"MI_PATTERN_OHLCV_V2")
    digest.update(str(symbol).upper().strip().encode("utf-8"))
    digest.update(str(source["provider"]).encode("utf-8"))
    digest.update(str(source["source_symbol"]).encode("utf-8"))
    digest.update(str(source["status"]).encode("utf-8"))
    digest.update(str(source["recency"]).encode("utf-8"))
    digest.update(str(source["known_at"]).encode("utf-8"))
    digest.update(str(source["revision_policy"]).encode("utf-8"))
    digest.update(str(price_adjustment_policy).encode("utf-8"))
    digest.update(str(open_price_observed).encode("utf-8"))
    digest.update(str(high_low_observed).encode("utf-8"))
    digest.update(str(adjusted_close_observed).encode("utf-8"))
    digest.update(str(corporate_action_safe).encode("utf-8"))
    digest.update(str(source["point_in_time_declared"]).encode("utf-8"))
    digest.update(str(source["fallback_used"]).encode("utf-8"))
    digest.update("|".join(indexed.columns).encode("utf-8"))
    hashed = pd.util.hash_pandas_object(indexed, index=True, categorize=True)
    digest.update(np.asarray(hashed.values, dtype=np.uint64).tobytes())
    audit = PatternInputAudit(
        symbol=str(symbol).upper().strip(),
        source_symbol=str(source["source_symbol"]),
        subject_match=subject_match,
        dataset_id=digest.hexdigest(),
        source=str(source["provider"]),
        source_status=str(source["status"]),
        recency=str(source["recency"]),
        source_known_at=source["known_at"],
        latest_row_known_at=latest_row_known_at,
        revision_policy=str(source["revision_policy"]),
        price_adjustment_policy=price_adjustment_policy,
        open_price_observed=open_price_observed,
        high_low_observed=high_low_observed,
        adjusted_close_observed=adjusted_close_observed,
        corporate_action_safe=corporate_action_safe,
        raw_rows=raw_rows,
        normalized_rows=len(indexed),
        first_observation=_utc_datetime(indexed.index[0]),
        data_cutoff=_utc_datetime(indexed.index[-1]),
        chronological=True,
        unique_timestamps=True,
        source_identified=bool(source["source_identified"]),
        point_in_time_declared=bool(source["point_in_time_declared"]),
        row_lineage_complete=row_lineage_complete,
        pit_lineage_complete=pit_lineage_complete,
        fallback_used=bool(source["fallback_used"]),
        quality_flags=tuple(dict.fromkeys(flags)),
        blocking_reasons=tuple(dict.fromkeys(reasons)),
    )
    return indexed, audit


def _robust_zscore(series: pd.Series, window: int) -> pd.Series:
    median = series.rolling(window, min_periods=max(5, window // 2)).median()
    deviation = (series - median).abs().rolling(window, min_periods=max(5, window // 2)).median()
    return (series - median) / (1.4826 * deviation.replace(0.0, np.nan))


def causal_pattern_features(market: pd.DataFrame) -> pd.DataFrame:
    """Build close-of-bar features using only information available by each row."""

    raw_close = market["close"]
    close = market["adj_close"].where(market["adj_close"].notna(), raw_close)
    adjustment = (close / raw_close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    adjusted_open = market["open"] * adjustment
    adjusted_high = market["high"] * adjustment
    adjusted_low = market["low"] * adjustment
    adjusted_volume = market["volume"] / adjustment.replace(0.0, np.nan)
    returns = close.pct_change()
    features = pd.DataFrame(index=market.index)
    for lag in range(8):
        features[f"return_lag_{lag}"] = returns.shift(lag)
    for window in (3, 5, 10, 20, 60):
        features[f"momentum_{window}"] = close.pct_change(window)
    for window in (5, 10, 20, 60):
        features[f"volatility_{window}"] = returns.rolling(window, min_periods=window).std(ddof=1)
    features["downside_volatility_20"] = returns.clip(upper=0.0).rolling(20, min_periods=20).std(ddof=1)
    features["trend_distance_10"] = close / close.rolling(10, min_periods=10).mean() - 1.0
    features["trend_distance_20"] = close / close.rolling(20, min_periods=20).mean() - 1.0
    features["drawdown_60"] = close / close.rolling(60, min_periods=60).max() - 1.0
    denominator = adjusted_high - adjusted_low
    features["intrabar_range"] = denominator / close
    features["close_location"] = (close - adjusted_low) / denominator.replace(0.0, np.nan)
    features["opening_gap"] = adjusted_open / close.shift(1) - 1.0
    features["volume_robust_z_20"] = _robust_zscore(adjusted_volume, 20)
    dollar_volume = close * adjusted_volume
    features["amihud_20"] = (
        returns.abs() / dollar_volume.replace(0.0, np.nan)
    ).rolling(20, min_periods=20).mean()
    return features.replace([np.inf, -np.inf], np.nan)


def build_pattern_feature_bundle(
    price_data: Any,
    symbol: str,
    config: PatternDiscoveryConfig,
) -> PatternFeatureBundle:
    market, audit = normalize_price_history(price_data, symbol)
    if market.empty:
        empty = pd.DataFrame()
        return PatternFeatureBundle(market, empty, empty, pd.Series(dtype=float), empty, audit)
    features = causal_pattern_features(market)
    if not audit.high_low_observed:
        features = features.drop(
            columns=["intrabar_range", "close_location"],
            errors="ignore",
        )
    raw_close = market["close"]
    close = market["adj_close"].where(market["adj_close"].notna(), raw_close)
    adjustment = (close / raw_close.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(1.0)
    adjusted_open = market["open"] * adjustment
    entry = adjusted_open.shift(-config.execution_lag_bars)
    exit_offset = config.execution_lag_bars + config.horizon_bars - 1
    forward = close.shift(-exit_offset) / entry - 1.0
    label = (forward > 0.0).astype(float).where(forward.notna())
    labels = pd.DataFrame({"target": label}, index=market.index)
    current = features.tail(1).copy()
    required = (
        "return_lag_0",
        "return_lag_7",
        "momentum_60",
        "volatility_60",
        "trend_distance_20",
        "drawdown_60",
    )
    valid = features.loc[:, required].notna().all(axis=1) & labels["target"].notna() & forward.notna()
    return PatternFeatureBundle(
        market=market,
        features=features.loc[valid].copy(),
        labels=labels.loc[valid].copy(),
        forward_returns=forward.loc[valid].copy(),
        current_features=current,
        audit=audit,
    )
