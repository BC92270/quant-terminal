from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .contracts import DataQuality


ALIASES = {
    "date": ("date", "datetime", "timestamp"),
    "open": ("open",),
    "high": ("high",),
    "low": ("low",),
    "close": ("close", "adj close", "adj_close"),
    "volume": ("volume",),
}


def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = [
            "_".join(str(part) for part in column if str(part)).strip("_").lower()
            for column in data.columns
        ]
    else:
        data.columns = [str(column).strip().lower() for column in data.columns]
    return data


def normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("OHLCV data is empty.")

    data = _flatten_columns(frame)
    if not any(alias in data.columns for alias in ALIASES["date"]):
        data = data.reset_index()
        data = _flatten_columns(data)

    rename: dict[str, str] = {}
    for canonical, candidates in ALIASES.items():
        for candidate in candidates:
            exact = [column for column in data.columns if column == candidate]
            contains = [column for column in data.columns if column.startswith(f"{candidate}_")]
            if exact or contains:
                rename[(exact or contains)[0]] = canonical
                break
    data = data.rename(columns=rename)

    if "date" not in data.columns or "close" not in data.columns:
        raise ValueError("OHLCV data must contain a date/index and a close column.")

    data["date"] = pd.to_datetime(data["date"], errors="coerce", utc=True).dt.tz_convert(None)
    for column in ("open", "high", "low", "close", "volume"):
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")

    data = (
        data[["date", "open", "high", "low", "close", "volume"]]
        .dropna(subset=["date", "close"])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )
    if (data["close"] <= 0).any():
        data = data.loc[data["close"] > 0].reset_index(drop=True)
    if data.empty:
        raise ValueError("No valid positive close observations remain after normalization.")
    return data


def assess_quality(original: pd.DataFrame, clean: pd.DataFrame) -> DataQuality:
    original_rows = 0 if original is None else len(original)
    duplicates = int(clean["date"].duplicated().sum())
    missing_close = max(0, original_rows - len(clean))
    missing_volume_ratio = float(clean["volume"].isna().mean())

    inferred = pd.infer_freq(clean["date"].tail(min(50, len(clean)))) if len(clean) >= 4 else None
    if inferred and (str(inferred).upper().startswith("D") or str(inferred).upper().startswith("B")):
        stale_threshold = pd.Timedelta(days=5)
    else:
        median_delta = clean["date"].diff().median()
        stale_threshold = max(pd.Timedelta(minutes=5), median_delta * 3) if pd.notna(median_delta) else pd.Timedelta(days=5)
    staleness = pd.Timestamp.utcnow().tz_localize(None) - clean["date"].iloc[-1]
    stale_bars = int(max(0, round(staleness / stale_threshold))) if stale_threshold > pd.Timedelta(0) else 0

    score = 100.0
    notes: list[str] = []
    if missing_close:
        score -= min(25.0, 100.0 * missing_close / max(original_rows, 1))
        notes.append(f"{missing_close} lignes invalides ou sans clôture supprimées")
    if missing_volume_ratio > 0.05:
        score -= min(15.0, missing_volume_ratio * 20)
        notes.append("volume partiellement indisponible")
    if len(clean) < 200:
        score -= min(25.0, (200 - len(clean)) * 0.12)
        notes.append("historique court pour les horizons longs")
    if stale_bars > 0:
        score -= min(25.0, stale_bars * 5)
        notes.append(f"flux potentiellement ancien ({stale_bars} unité(s) de retard)")
    score = float(np.clip(score, 0, 100))
    status = "ROBUST" if score >= 85 else "USABLE" if score >= 65 else "DEGRADED"
    return DataQuality(
        rows=len(clean),
        start=clean["date"].iloc[0],
        end=clean["date"].iloc[-1],
        missing_close=missing_close,
        missing_volume_ratio=missing_volume_ratio,
        duplicate_dates=duplicates,
        stale_bars=stale_bars,
        quality_score=score,
        status=status,
        notes=tuple(notes),
    )


def align_benchmarks(
    asset: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame] | None,
) -> pd.DataFrame:
    output = asset.copy()
    if not benchmarks:
        return output

    for symbol, raw in benchmarks.items():
        try:
            benchmark = normalize_ohlcv(raw)[["date", "close"]].rename(columns={"close": "benchmark_close"})
        except (ValueError, TypeError):
            continue
        aligned = pd.merge_asof(
            output[["date"]].sort_values("date"),
            benchmark.sort_values("date"),
            on="date",
            direction="backward",
            tolerance=pd.Timedelta(days=7),
        )
        slug = "".join(character.lower() if character.isalnum() else "_" for character in str(symbol)).strip("_")
        output[f"benchmark_{slug}"] = aligned["benchmark_close"].to_numpy()
    return output

