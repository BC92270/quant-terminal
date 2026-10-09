"""Append-only governed scenario ledger for Company Intelligence M&A.

The ledger is deliberately local and research-only.  Every JSONL record links
to the prior record through SHA-256 so silent rewrites are detected.  There is
no update or delete API: a changed case is a new revision.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping
from uuid import uuid4

try:  # POSIX runtime used by macOS development and Linux Codespaces.
    import fcntl
except ImportError:  # pragma: no cover - explicit fail-closed branch.
    fcntl = None


SCHEMA_VERSION = "qntm.mna.scenario.v1"
POLICY = "RESEARCH_ONLY · HUMAN REVIEW REQUIRED"
GENESIS_HASH = "0" * 64
_SAFE_TICKER = re.compile(r"[^A-Z0-9._-]+")


class ScenarioLedgerError(RuntimeError):
    """Base exception for scenario-ledger failures."""


class ScenarioLedgerIntegrityError(ScenarioLedgerError):
    """Raised when the append-only hash chain cannot be verified."""


def _root(root: str | os.PathLike[str] | None = None) -> Path:
    configured = root or os.environ.get("COMPANY_INTELLIGENCE_MNA_DIR")
    return Path(configured).expanduser() if configured else Path.cwd() / ".company_intelligence_mna"


def _safe_ticker(ticker: str) -> str:
    normalized = _SAFE_TICKER.sub("_", str(ticker or "UNKNOWN").upper().strip()).strip("._-")
    return normalized[:40] or "UNKNOWN"


def _ledger_path(ticker: str, root: str | os.PathLike[str] | None = None) -> Path:
    return _root(root) / f"{_safe_ticker(ticker)}.jsonl"


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    return str(value)


def _canonical(record: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "record_hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _hash(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


@contextmanager
def _locked(lock_path: Path) -> Iterator[None]:
    if fcntl is None:
        raise ScenarioLedgerError("POSIX file locking is unavailable; governed append is blocked.")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ScenarioLedgerIntegrityError(f"Invalid JSON at ledger line {line_number}.") from exc
            if not isinstance(parsed, dict):
                raise ScenarioLedgerIntegrityError(f"Ledger line {line_number} is not an object.")
            records.append(parsed)
    return records


def verify_records(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Verify a record sequence without touching the filesystem."""
    prior = GENESIS_HASH
    for index, record in enumerate(records, start=1):
        if record.get("schema_version") != SCHEMA_VERSION:
            return {"valid": False, "count": len(records), "failed_at": index, "reason": "schema_version"}
        if record.get("sequence") != index:
            return {"valid": False, "count": len(records), "failed_at": index, "reason": "sequence"}
        if record.get("prior_hash") != prior:
            return {"valid": False, "count": len(records), "failed_at": index, "reason": "prior_hash"}
        expected = _hash(record)
        if record.get("record_hash") != expected:
            return {"valid": False, "count": len(records), "failed_at": index, "reason": "record_hash"}
        prior = expected
    return {"valid": True, "count": len(records), "failed_at": None, "reason": None, "head_hash": prior}


def load_scenarios(
    ticker: str,
    *,
    root: str | os.PathLike[str] | None = None,
    verify: bool = True,
) -> list[dict[str, Any]]:
    """Load scenarios in append order and optionally fail closed on tampering."""
    records = _read_records(_ledger_path(ticker, root))
    if verify:
        status = verify_records(records)
        if not status["valid"]:
            raise ScenarioLedgerIntegrityError(
                f"Scenario ledger integrity failure at record {status['failed_at']}: {status['reason']}."
            )
    return records


def verify_ledger(ticker: str, *, root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Return the current chain status; malformed JSON is reported as invalid."""
    try:
        return verify_records(_read_records(_ledger_path(ticker, root)))
    except ScenarioLedgerIntegrityError as exc:
        return {"valid": False, "count": 0, "failed_at": None, "reason": str(exc), "head_hash": None}


def append_scenario(
    ticker: str,
    label: str,
    payload: Mapping[str, Any],
    *,
    context: Mapping[str, Any] | None = None,
    root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Append one immutable scenario revision after verifying the current chain."""
    normalized_ticker = _safe_ticker(ticker)
    normalized_label = str(label or "Untitled scenario").strip()[:160] or "Untitled scenario"
    path = _ledger_path(normalized_ticker, root)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _locked(lock_path):
        records = _read_records(path)
        status = verify_records(records)
        if not status["valid"]:
            raise ScenarioLedgerIntegrityError(
                f"Refusing append: integrity failure at record {status['failed_at']} ({status['reason']})."
            )
        safe_context = _json_safe(dict(context or {}))
        safe_payload = _json_safe(dict(payload or {}))
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "MNA_SCENARIO_SNAPSHOT",
            "scenario_id": str(uuid4()),
            "sequence": len(records) + 1,
            "ticker": normalized_ticker,
            "label": normalized_label,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "policy": POLICY,
            "review_status": safe_context.get("review_status", "DRAFT") if isinstance(safe_context, dict) else "DRAFT",
            "owner": safe_context.get("owner", "Unassigned") if isinstance(safe_context, dict) else "Unassigned",
            "reviewer": safe_context.get("reviewer", "Unassigned") if isinstance(safe_context, dict) else "Unassigned",
            "context": safe_context,
            "payload": safe_payload,
            "prior_hash": status.get("head_hash") or GENESIS_HASH,
        }
        record["record_hash"] = _hash(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record


__all__ = [
    "GENESIS_HASH",
    "POLICY",
    "SCHEMA_VERSION",
    "ScenarioLedgerError",
    "ScenarioLedgerIntegrityError",
    "append_scenario",
    "load_scenarios",
    "verify_ledger",
    "verify_records",
]
