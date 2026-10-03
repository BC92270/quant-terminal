from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, TypeVar

try:  # POSIX is the supported runtime for local macOS and GitHub Codespaces.
    import fcntl
except ImportError:  # pragma: no cover - fail closed on unsupported platforms
    fcntl = None


class RegistryLockError(RuntimeError):
    """Base error for an unavailable or contended registry transaction lock."""


class RegistryLockTimeoutError(RegistryLockError):
    """Raised instead of risking a concurrent lost update."""


ErrorType = TypeVar("ErrorType", bound=Exception)


def _lock_path(path: Path) -> Path:
    return path.parent / ".srb-registry.lock"


@contextmanager
def registry_lock(path: Path, *, timeout: float = 10.0) -> Iterator[None]:
    """Acquire one inter-process lock shared by every registry in a state root.

    Lock acquisition is bounded and fail-closed.  The lock file is deliberately
    persistent; the kernel lock, not file deletion, owns the lifecycle.
    """

    if fcntl is None:
        raise RegistryLockError("Scientific registries require POSIX advisory file locking.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _lock_path(path)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    deadline = time.monotonic() + max(0.0, float(timeout))
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise RegistryLockTimeoutError(
                        f"Timed out waiting for scientific registry lock: {lock_path}"
                    ) from exc
                time.sleep(0.01)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def read_json_array(path: Path, corruption_error: type[ErrorType]) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise corruption_error(f"Registry is not valid JSON: {path.name}") from exc
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise corruption_error(f"Registry must contain a JSON array of objects: {path.name}")
    return [dict(row) for row in value]


def _atomic_write_json_array(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(rows, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Some filesystems do not support directory fsync. The atomic replace
            # still prevents partial JSON visibility.
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def json_array_transaction(
    path: Path,
    corruption_error: type[ErrorType],
    *,
    timeout: float = 10.0,
) -> Iterator[list[dict[str, Any]]]:
    """Serialize one complete read-modify-write cycle across processes."""

    path = Path(path)
    with registry_lock(path, timeout=timeout):
        rows = read_json_array(path, corruption_error)
        yield rows
        _atomic_write_json_array(path, rows)


def append_jsonl_object(
    path: Path,
    row: Mapping[str, Any],
    corruption_error: type[ErrorType],
    *,
    timeout: float = 10.0,
) -> None:
    """Validate and append one audit object while holding the shared root lock."""

    path = Path(path)
    with registry_lock(path, timeout=timeout):
        if path.exists():
            try:
                for line_number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), start=1
                ):
                    if not line.strip():
                        continue
                    value = json.loads(line)
                    if not isinstance(value, Mapping):
                        raise ValueError(f"line {line_number} is not an object")
            except Exception as exc:
                raise corruption_error(f"Audit registry is not valid JSONL: {path.name}") from exc
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


__all__ = [
    "RegistryLockError",
    "RegistryLockTimeoutError",
    "append_jsonl_object",
    "json_array_transaction",
    "read_json_array",
    "registry_lock",
]
