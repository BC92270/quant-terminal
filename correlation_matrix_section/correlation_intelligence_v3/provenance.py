from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import math
from typing import Any

import numpy as np
import pandas as pd


MANIFEST_SCHEMA_NAME = "quant-terminal.correlation-research-pack"
MANIFEST_SCHEMA_VERSION = "1.0.0"
DATAFRAME_HASH_SCHEMA = "quant-terminal.dataframe-sha256.v1"


def json_safe(value: Any) -> Any:
    """Return deterministic JSON-compatible values without dataframe payloads."""
    if is_dataclass(value):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(value[k]) for k in sorted(value, key=lambda x: str(x))}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((json_safe(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(value, np.ndarray):
        return [json_safe(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, pd.Timestamp):
        return _timestamp_token(value)
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _timestamp_token(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC")
    return ts.isoformat()


def _scalar_token(value: Any) -> bytes:
    if value is None or value is pd.NaT:
        return b"N"
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        if pd.isna(value):
            return b"N"
        return b"T" + _timestamp_token(value).encode("utf-8")
    if isinstance(value, (bool, np.bool_)):
        return b"B1" if bool(value) else b"B0"
    if isinstance(value, (int, np.integer)):
        return b"I" + str(int(value)).encode("ascii")
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number):
            return b"N"
        if math.isinf(number):
            return b"F+inf" if number > 0 else b"F-inf"
        return b"F" + number.hex().encode("ascii")
    try:
        if bool(pd.isna(value)):
            return b"N"
    except (TypeError, ValueError):
        pass
    return b"S" + str(value).encode("utf-8")


def dataframe_sha256(frame: pd.DataFrame | None) -> str:
    """Hash a dataframe's ordered schema, index and exact scalar values.

    Floating-point numbers use ``float.hex`` so the digest is independent of CSV
    display precision and locale. Column and row order are intentionally material:
    they are part of the exported research artifact.
    """
    df = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    digest = sha256()
    digest.update(DATAFRAME_HASH_SCHEMA.encode("ascii"))

    def feed(value: Any) -> None:
        token = _scalar_token(value)
        digest.update(len(token).to_bytes(8, "big"))
        digest.update(token)

    feed(df.index.name)
    feed(len(df))
    feed(len(df.columns))
    for column in df.columns:
        feed(column)
        feed(str(df[column].dtype))
    for index_value, row in zip(df.index, df.itertuples(index=False, name=None)):
        if isinstance(index_value, tuple):
            feed(len(index_value))
            for part in index_value:
                feed(part)
        else:
            feed(index_value)
        for value in row:
            feed(value)
    return digest.hexdigest()


def _frame_range(frame: pd.DataFrame | None) -> tuple[str | None, str | None]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None, None
    try:
        idx = pd.to_datetime(frame.index, errors="coerce")
        idx = idx[~pd.isna(idx)]
        if len(idx):
            return _timestamp_token(idx.min()), _timestamp_token(idx.max())
    except (TypeError, ValueError):
        pass
    return str(frame.index[0]), str(frame.index[-1])


def dataframe_manifest(frame: pd.DataFrame | None) -> dict[str, Any]:
    df = frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()
    index_start, index_end = _frame_range(df)
    observed = df.loc[df.notna().any(axis=1)] if len(df.columns) else df.iloc[0:0]
    start, end = _frame_range(observed)
    return {
        "shape": [int(df.shape[0]), int(df.shape[1])],
        "columns": [str(c) for c in df.columns],
        "index_name": None if df.index.name is None else str(df.index.name),
        "range": {"start": start, "end": end},
        "index_range": {"start": index_start, "end": index_end},
        "non_null_by_column": {str(c): int(df[c].notna().sum()) for c in df.columns},
        "missing_by_column": {str(c): int(df[c].isna().sum()) for c in df.columns},
        "hash": {
            "algorithm": "sha256",
            "canonicalization": DATAFRAME_HASH_SCHEMA,
            "value": dataframe_sha256(df),
        },
    }


def _mapping_from_quality(bundle: Any, value_column: str) -> dict[str, str]:
    quality = getattr(bundle, "quality", pd.DataFrame())
    if not isinstance(quality, pd.DataFrame) or not {"Ticker", value_column}.issubset(quality.columns):
        return {}
    rows = quality[["Ticker", value_column]].dropna()
    return {str(ticker): str(value) for ticker, value in rows.itertuples(index=False, name=None)}


def _as_of(metadata: dict[str, Any], levels_manifest: dict[str, Any], returns_manifest: dict[str, Any]) -> str | None:
    supplied = metadata.get("as_of")
    if supplied is not None:
        try:
            return _timestamp_token(supplied)
        except (TypeError, ValueError):
            return str(supplied)
    ends = [
        levels_manifest.get("range", {}).get("end"),
        returns_manifest.get("range", {}).get("end"),
    ]
    return max((x for x in ends if x is not None), default=None)


def research_pack_manifest(bundle: Any, config: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    supplied_meta = dict(metadata or {})
    levels = getattr(bundle, "levels", pd.DataFrame())
    returns = getattr(bundle, "changes", pd.DataFrame())
    levels_meta = dataframe_manifest(levels)
    returns_meta = dataframe_manifest(returns)

    provider_map = getattr(bundle, "provider_map", None) or _mapping_from_quality(bundle, "Provider")
    transform_map = getattr(bundle, "transform_map", None) or _mapping_from_quality(bundle, "Transform")
    data_source = (
        getattr(bundle, "data_source", None)
        or getattr(bundle, "source", None)
        or supplied_meta.get("data_source")
        or "unknown"
    )

    artifacts = {"levels.csv": levels_meta, "changes.csv": returns_meta}
    return {
        "schema": {"name": MANIFEST_SCHEMA_NAME, "version": MANIFEST_SCHEMA_VERSION},
        "as_of": _as_of(supplied_meta, levels_meta, returns_meta),
        "as_of_basis": "metadata.as_of" if supplied_meta.get("as_of") is not None else "latest non-null dataset index",
        "data_source": str(data_source),
        "provider_map": json_safe(provider_map),
        "transforms": json_safe(transform_map),
        "config": json_safe(config),
        "request_metadata": json_safe(supplied_meta),
        "ranges": {name: value["range"] for name, value in artifacts.items()},
        "shape": {name: value["shape"] for name, value in artifacts.items()},
        "hashes": {name: value["hash"] for name, value in artifacts.items()},
        "artifacts": artifacts,
    }
