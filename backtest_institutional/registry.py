"""Reproducible experiment manifests and a local immutable registry."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
from typing import Any

import numpy as np
import pandas as pd

from .types import RunManifest


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.ndarray):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(v) for v in value.to_dict(orient="records")]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def stable_hash(value: Any) -> str:
    encoded = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return sha256(encoded).hexdigest()


def data_hash(frame: pd.DataFrame | pd.Series) -> str:
    obj = frame.to_frame() if isinstance(frame, pd.Series) else frame
    if obj.empty:
        return sha256(b"EMPTY").hexdigest()
    hashes = pd.util.hash_pandas_object(obj, index=True).values.tobytes()
    return sha256("|".join(map(str, obj.columns)).encode() + hashes).hexdigest()


def environment_snapshot() -> dict[str, Any]:
    packages = {}
    for name in ("numpy", "pandas", "streamlit", "plotly", "scikit-learn"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "UNAVAILABLE"
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": packages}


def build_run_manifest(
    *,
    config: dict[str, Any],
    market_data: pd.DataFrame | pd.Series,
    strategy: str,
    symbol: str,
    seed: int,
    code_path: str | Path = "backtest_lab.py",
    engine_version: str = "7.0.0",
    parent_run_id: str | None = None,
    tags: tuple[str, ...] = (),
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> RunManifest:
    code = Path(code_path)
    code_digest = sha256(code.read_bytes()).hexdigest() if code.exists() else "UNAVAILABLE"
    env = environment_snapshot()
    config_digest = stable_hash(config)
    data_digest = data_hash(market_data)
    identity = {
        "engine_version": engine_version, "strategy": strategy, "symbol": symbol,
        "seed": int(seed), "config_hash": config_digest, "data_hash": data_digest,
        "code_hash": code_digest, "environment_hash": stable_hash(env),
        "parent_run_id": parent_run_id,
    }
    run_id = "BT-" + stable_hash(identity)[:20].upper()
    return RunManifest(
        run_id=run_id,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
        engine_version=engine_version,
        strategy=strategy,
        symbol=symbol,
        seed=int(seed),
        config_hash=config_digest,
        data_hash=data_digest,
        code_hash=code_digest,
        environment_hash=stable_hash(env),
        parent_run_id=parent_run_id,
        tags=tags,
        metadata=_json_safe(metadata or {}) | {"environment": env},
    )


class ExperimentRegistry:
    def __init__(self, root: str | Path = ".quant_cache/backtest_registry") -> None:
        self.root = Path(root)
        self.runs = self.root / "runs"

    def persist(self, manifest: RunManifest, payload: dict[str, Any]) -> Path:
        self.runs.mkdir(parents=True, exist_ok=True)
        target = self.runs / f"{manifest.run_id}.json"
        document = {"manifest": _json_safe(asdict(manifest)), "payload": _json_safe(payload)}
        encoded = json.dumps(document, indent=2, sort_keys=True) + "\n"
        if target.exists():
            if target.read_text(encoding="utf-8") != encoded:
                raise RuntimeError(f"Immutable run collision for {manifest.run_id}")
            return target
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{manifest.run_id}.", dir=str(self.runs))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return target

    def get(self, run_id: str) -> dict[str, Any]:
        path = self.runs / f"{run_id}.json"
        if not path.exists():
            raise KeyError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self, limit: int = 100) -> pd.DataFrame:
        if not self.runs.exists():
            return pd.DataFrame()
        rows = []
        paths = sorted(self.runs.glob("BT-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[:limit]:
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8"))["manifest"])
            except (json.JSONDecodeError, KeyError):
                rows.append({"run_id": path.stem, "status": "CORRUPT"})
        return pd.DataFrame(rows)

    def lineage(self, run_id: str) -> list[str]:
        lineage: list[str] = []
        current: str | None = run_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            lineage.append(current)
            try:
                current = self.get(current)["manifest"].get("parent_run_id")
            except KeyError:
                break
        return lineage
