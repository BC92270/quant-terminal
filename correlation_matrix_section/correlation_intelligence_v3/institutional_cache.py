from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import gzip
import json
import os
from pathlib import Path
import pickle
import sqlite3
import tempfile
import time
from typing import Any

import pandas as pd


CACHE_SCHEMA_VERSION = "quant-terminal.correlation-cache.v1"
DEFAULT_TTL_SECONDS = 6 * 60 * 60


try:  # Optional institutional catalog backend.
    import duckdb  # type: ignore
except Exception:  # pragma: no cover - exercised through the SQLite fallback.
    duckdb = None

try:  # Arrow remains optional for small/offline installations.
    import pyarrow as pa  # type: ignore
    import pyarrow.ipc as pa_ipc  # type: ignore
except Exception:  # pragma: no cover
    pa = None
    pa_ipc = None

try:  # Redis is activated only when CORRELATION_REDIS_URL is configured.
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None


@dataclass
class CacheRead:
    value: Any = None
    hit: bool = False
    age_seconds: float | None = None
    backend: str = "none"
    reason: str | None = None


class InstitutionalCache:
    """Persistent two-tier cache for governed correlation research artifacts.

    The local tier uses a DuckDB catalog when the optional package is present and
    falls back to SQLite otherwise. DataFrames are stored as Arrow IPC whenever
    PyArrow is available. Python analysis bundles use a checksummed gzip/pickle
    payload in an app-owned cache directory and are never accepted from uploads or
    any other untrusted path. A configured Redis instance acts as a bounded hot tier.
    """

    def __init__(
        self,
        root: str | Path | None = None,
        *,
        default_ttl: int = DEFAULT_TTL_SECONDS,
        max_entries: int = 48,
    ) -> None:
        default_root = Path.cwd() / ".quant_terminal_cache" / "correlation_v5"
        self.root = Path(root or os.getenv("QUANT_TERMINAL_CORRELATION_CACHE_DIR", default_root)).expanduser().resolve()
        self.payload_dir = self.root / "payloads"
        self.default_ttl = max(60, int(default_ttl))
        self.max_entries = max(4, int(max_entries))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.payload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            os.chmod(self.root, 0o700)
            os.chmod(self.payload_dir, 0o700)
        except OSError:
            pass
        self.catalog_backend = "duckdb" if duckdb is not None else "sqlite"
        self.catalog_path = self.root / ("catalog.duckdb" if duckdb is not None else "catalog.sqlite3")
        self._redis = self._build_redis_client()
        self._initialize_catalog()

    def _build_redis_client(self):
        url = str(os.getenv("CORRELATION_REDIS_URL", "")).strip()
        if not url or redis is None:
            return None
        try:
            return redis.Redis.from_url(
                url,
                socket_connect_timeout=0.25,
                socket_timeout=0.35,
                decode_responses=False,
            )
        except Exception:
            return None

    def _connect(self):
        if self.catalog_backend == "duckdb":
            return duckdb.connect(str(self.catalog_path))
        conn = sqlite3.connect(str(self.catalog_path), timeout=5.0)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize_catalog(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_id VARCHAR PRIMARY KEY,
                    namespace VARCHAR NOT NULL,
                    user_key VARCHAR NOT NULL,
                    format VARCHAR NOT NULL,
                    relative_path VARCHAR NOT NULL,
                    checksum VARCHAR NOT NULL,
                    created_at DOUBLE NOT NULL,
                    accessed_at DOUBLE NOT NULL,
                    expires_at DOUBLE NOT NULL,
                    size_bytes BIGINT NOT NULL,
                    metadata_json VARCHAR NOT NULL
                )
                """
            )
            if self.catalog_backend == "sqlite":
                conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _cache_id(namespace: str, key: str) -> str:
        token = json.dumps(
            {"schema": CACHE_SCHEMA_VERSION, "namespace": str(namespace), "key": str(key)},
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(token.encode("utf-8")).hexdigest()

    def _redis_key(self, cache_id: str) -> str:
        return f"qt:corr:v5:{cache_id}"

    def _safe_payload_path(self, relative_path: str) -> Path | None:
        try:
            resolved = (self.root / relative_path).resolve()
            resolved.relative_to(self.payload_dir)
            return resolved
        except (OSError, ValueError):
            return None

    def _row(self, cache_id: str):
        conn = self._connect()
        try:
            return conn.execute(
                "SELECT cache_id, namespace, user_key, format, relative_path, checksum, created_at, accessed_at, expires_at, size_bytes, metadata_json FROM cache_entries WHERE cache_id = ?",
                [cache_id],
            ).fetchone()
        finally:
            conn.close()

    def _touch(self, cache_id: str, now: float) -> None:
        conn = self._connect()
        try:
            conn.execute("UPDATE cache_entries SET accessed_at = ? WHERE cache_id = ?", [now, cache_id])
            if self.catalog_backend == "sqlite":
                conn.commit()
        finally:
            conn.close()

    def _delete_entry(self, cache_id: str, relative_path: str | None = None) -> None:
        conn = self._connect()
        try:
            if relative_path is None:
                row = conn.execute("SELECT relative_path FROM cache_entries WHERE cache_id = ?", [cache_id]).fetchone()
                relative_path = row[0] if row else None
            conn.execute("DELETE FROM cache_entries WHERE cache_id = ?", [cache_id])
            if self.catalog_backend == "sqlite":
                conn.commit()
        finally:
            conn.close()
        if relative_path:
            path = self._safe_payload_path(str(relative_path))
            if path is not None and path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
        if self._redis is not None:
            try:
                self._redis.delete(self._redis_key(cache_id))
            except Exception:
                pass

    def _write_payload(self, cache_id: str, suffix: str, payload: bytes) -> tuple[str, str]:
        checksum = sha256(payload).hexdigest()
        final_path = self.payload_dir / f"{cache_id}.{suffix}"
        with tempfile.NamedTemporaryFile(dir=self.payload_dir, prefix=f".{cache_id}.", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(final_path)
        return str(final_path.relative_to(self.root)), checksum

    def _upsert(
        self,
        cache_id: str,
        namespace: str,
        key: str,
        fmt: str,
        relative_path: str,
        checksum: str,
        size_bytes: int,
        ttl: int,
        metadata: dict[str, Any] | None,
    ) -> None:
        now = time.time()
        values = [
            cache_id,
            str(namespace),
            str(key),
            fmt,
            relative_path,
            checksum,
            now,
            now,
            now + max(60, int(ttl)),
            int(size_bytes),
            json.dumps(metadata or {}, sort_keys=True, default=str),
        ]
        conn = self._connect()
        try:
            conn.execute("DELETE FROM cache_entries WHERE cache_id = ?", [cache_id])
            conn.execute(
                "INSERT INTO cache_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            )
            if self.catalog_backend == "sqlite":
                conn.commit()
        finally:
            conn.close()
        self.prune()

    def get_object(self, namespace: str, key: str) -> CacheRead:
        cache_id = self._cache_id(namespace, key)
        row = self._row(cache_id)
        if not row:
            return CacheRead(reason="miss")
        now = time.time()
        if float(row[8]) <= now:
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="expired")
        payload: bytes | None = None
        backend = self.catalog_backend
        if self._redis is not None:
            try:
                payload = self._redis.get(self._redis_key(cache_id))
                if payload:
                    backend = "redis"
            except Exception:
                payload = None
        if payload is None:
            path = self._safe_payload_path(str(row[4]))
            if path is None or not path.is_file():
                self._delete_entry(cache_id, str(row[4]))
                return CacheRead(reason="payload_missing")
            try:
                payload = path.read_bytes()
            except OSError:
                return CacheRead(reason="payload_unreadable")
        if sha256(payload).hexdigest() != str(row[5]):
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="checksum_mismatch")
        try:
            value = pickle.loads(gzip.decompress(payload))
        except Exception:
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="decode_error")
        self._touch(cache_id, now)
        return CacheRead(value=value, hit=True, age_seconds=max(0.0, now - float(row[6])), backend=backend)

    def put_object(
        self,
        namespace: str,
        key: str,
        value: Any,
        *,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        cache_id = self._cache_id(namespace, key)
        try:
            payload = gzip.compress(pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL), compresslevel=5)
            relative_path, checksum = self._write_payload(cache_id, "pkl.gz", payload)
        except Exception:
            return False
        ttl_value = int(ttl or self.default_ttl)
        self._upsert(cache_id, namespace, key, "pickle_gzip", relative_path, checksum, len(payload), ttl_value, metadata)
        if self._redis is not None and len(payload) <= 48 * 1024 * 1024:
            try:
                self._redis.setex(self._redis_key(cache_id), ttl_value, payload)
            except Exception:
                pass
        return True

    def get_frame(self, namespace: str, key: str) -> CacheRead:
        cache_id = self._cache_id(namespace, key)
        row = self._row(cache_id)
        if not row:
            return CacheRead(reason="miss")
        now = time.time()
        if float(row[8]) <= now:
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="expired")
        path = self._safe_payload_path(str(row[4]))
        if path is None or not path.is_file():
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="payload_missing")
        try:
            payload = path.read_bytes()
            if sha256(payload).hexdigest() != str(row[5]):
                raise ValueError("checksum mismatch")
            if str(row[3]) == "arrow_ipc" and pa_ipc is not None:
                with pa_ipc.open_file(path) as reader:
                    frame = reader.read_all().to_pandas()
            else:
                frame = pickle.loads(gzip.decompress(payload))
            if not isinstance(frame, pd.DataFrame):
                raise TypeError("cached payload is not a dataframe")
        except Exception:
            self._delete_entry(cache_id, str(row[4]))
            return CacheRead(reason="decode_error")
        self._touch(cache_id, now)
        return CacheRead(value=frame, hit=True, age_seconds=max(0.0, now - float(row[6])), backend=f"{self.catalog_backend}+{row[3]}")

    def put_frame(
        self,
        namespace: str,
        key: str,
        frame: pd.DataFrame,
        *,
        ttl: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if not isinstance(frame, pd.DataFrame):
            return False
        cache_id = self._cache_id(namespace, key)
        try:
            if pa is not None and pa_ipc is not None:
                final_path = self.payload_dir / f"{cache_id}.arrow"
                with tempfile.NamedTemporaryFile(dir=self.payload_dir, prefix=f".{cache_id}.", delete=False) as handle:
                    temp_path = Path(handle.name)
                table = pa.Table.from_pandas(frame, preserve_index=True)
                with pa.OSFile(str(temp_path), "wb") as sink:
                    with pa_ipc.new_file(sink, table.schema) as writer:
                        writer.write_table(table)
                payload = temp_path.read_bytes()
                checksum = sha256(payload).hexdigest()
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass
                temp_path.replace(final_path)
                relative_path = str(final_path.relative_to(self.root))
                fmt = "arrow_ipc"
            else:
                payload = gzip.compress(pickle.dumps(frame, protocol=pickle.HIGHEST_PROTOCOL), compresslevel=5)
                relative_path, checksum = self._write_payload(cache_id, "frame.pkl.gz", payload)
                fmt = "pickle_gzip"
        except Exception:
            return False
        self._upsert(
            cache_id,
            namespace,
            key,
            fmt,
            relative_path,
            checksum,
            len(payload),
            int(ttl or self.default_ttl),
            metadata,
        )
        return True

    def prune(self) -> None:
        now = time.time()
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT cache_id, relative_path, expires_at, accessed_at FROM cache_entries ORDER BY accessed_at DESC"
            ).fetchall()
        finally:
            conn.close()
        stale = [(str(r[0]), str(r[1])) for r in rows if float(r[2]) <= now]
        live = [r for r in rows if float(r[2]) > now]
        stale.extend((str(r[0]), str(r[1])) for r in live[self.max_entries :])
        for cache_id, relative_path in stale:
            self._delete_entry(cache_id, relative_path)

    def status(self) -> dict[str, Any]:
        conn = self._connect()
        try:
            count_row = conn.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM cache_entries").fetchone()
        finally:
            conn.close()
        redis_state = "not_configured"
        if str(os.getenv("CORRELATION_REDIS_URL", "")).strip():
            redis_state = "client_missing" if redis is None else "unreachable"
            if self._redis is not None:
                try:
                    redis_state = "ready" if bool(self._redis.ping()) else "unreachable"
                except Exception:
                    redis_state = "unreachable"
        return {
            "schema": CACHE_SCHEMA_VERSION,
            "catalog_backend": self.catalog_backend,
            "arrow_backend": "ready" if pa is not None and pa_ipc is not None else "fallback_pickle",
            "redis_backend": redis_state,
            "entries": int(count_row[0] if count_row else 0),
            "size_bytes": int(count_row[1] if count_row else 0),
            "root": str(self.root),
            "ttl_seconds": self.default_ttl,
        }


_CACHE_SINGLETON: InstitutionalCache | None = None


def get_correlation_cache() -> InstitutionalCache:
    global _CACHE_SINGLETON
    if _CACHE_SINGLETON is None:
        _CACHE_SINGLETON = InstitutionalCache()
    return _CACHE_SINGLETON
