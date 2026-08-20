"""Persistent transcript cache and provider-circuit state for Company Intelligence V3.2.

Past earnings-call transcripts are immutable research inputs.  This module persists the raw
provider payload once per symbol/fiscal-quarter so subsequent Streamlit reruns require zero
API calls.  It also persists provider circuit-breaker state so quota/entitlement failures do
not trigger request storms across reruns.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_CACHE_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).astimezone(timezone.utc).isoformat()


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _cache_root() -> Path:
    configured = os.getenv("COMPANY_INTELLIGENCE_CACHE_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([
        Path.cwd() / ".company_intelligence_cache",
        Path.home() / ".company_intelligence_cache",
    ])
    for root in candidates:
        try:
            root.mkdir(parents=True, exist_ok=True)
            test_dir = root / "transcripts"
            test_dir.mkdir(parents=True, exist_ok=True)
            return root
        except Exception:
            continue
    # Last-resort path.  Callers still handle write failures gracefully.
    return Path.cwd() / ".company_intelligence_cache"


def transcript_cache_root() -> Path:
    return _cache_root() / "transcripts"


def _symbol_dir(symbol: str) -> Path:
    safe = "".join(ch for ch in str(symbol or "").upper().strip() if ch.isalnum() or ch in "._-") or "UNKNOWN"
    path = transcript_cache_root() / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _quarter_file(symbol: str, quarter: str) -> Path:
    q = "".join(ch for ch in str(quarter or "").upper().strip() if ch.isalnum() or ch in "._-")
    return _symbol_dir(symbol) / f"{q}.json"


def _manifest_file(symbol: str) -> Path:
    return _symbol_dir(symbol) / "manifest.json"


def _circuits_file() -> Path:
    path = transcript_cache_root() / "provider_circuits.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    # pandas/numpy scalar compatibility without importing either dependency.
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _checksum(payload: Any) -> str:
    raw = json.dumps(_json_safe(payload), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return default


def _atomic_write_json(path: Path, payload: Any) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(_json_safe(payload), fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if 'tmp' in locals() and tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def _rebuild_manifest(symbol: str) -> dict[str, Any]:
    rows = []
    for path in sorted(_symbol_dir(symbol).glob("*.json")):
        if path.name in {"manifest.json", "provider_circuits.json"}:
            continue
        item = _read_json(path, {})
        if not isinstance(item, dict) or not item.get("quarter"):
            continue
        rows.append({
            "quarter": item.get("quarter"),
            "provider": item.get("provider"),
            "call_date": item.get("call_date"),
            "retrieved_at": item.get("retrieved_at"),
            "checksum": item.get("checksum"),
            "cache_version": item.get("cache_version", _CACHE_VERSION),
        })
    manifest = {
        "symbol": str(symbol or "").upper().strip(),
        "updated_at": _iso(),
        "quarters": rows,
        "cache_version": _CACHE_VERSION,
    }
    _atomic_write_json(_manifest_file(symbol), manifest)
    return manifest


def save_transcript_payload(
    symbol: str,
    quarter: str,
    provider: str,
    payload: Any,
    call_date: Any = None,
    *,
    immutable: bool = True,
) -> dict[str, Any]:
    """Persist one raw transcript payload.

    The default is intentionally immutable: an existing quarter is never overwritten by an
    automatic refresh.  This keeps historical research inputs stable and audit-friendly.
    """
    symbol = str(symbol or "").upper().strip()
    quarter = str(quarter or "").upper().strip()
    if not symbol or not quarter or payload in (None, {}, [], ""):
        return {"ok": False, "saved": False, "reason": "Invalid cache payload"}
    path = _quarter_file(symbol, quarter)
    with _LOCK:
        if immutable and path.exists():
            existing = _read_json(path, {})
            return {
                "ok": True,
                "saved": False,
                "reason": "Immutable cache entry already exists",
                "path": str(path),
                "entry": existing,
            }
        entry = {
            "cache_version": _CACHE_VERSION,
            "symbol": symbol,
            "quarter": quarter,
            "provider": str(provider or "Unknown"),
            "call_date": _json_safe(call_date),
            "retrieved_at": _iso(),
            "checksum": _checksum(payload),
            "raw_payload": _json_safe(payload),
        }
        ok = _atomic_write_json(path, entry)
        if ok:
            _rebuild_manifest(symbol)
        return {
            "ok": ok,
            "saved": ok,
            "reason": "Saved" if ok else "Cache write failed",
            "path": str(path),
            "entry": entry if ok else None,
        }


def load_transcript_payload(symbol: str, quarter: str) -> dict[str, Any] | None:
    path = _quarter_file(symbol, quarter)
    item = _read_json(path, None)
    if not isinstance(item, dict) or item.get("raw_payload") in (None, {}, [], ""):
        return None
    return item


def list_cached_transcripts(symbol: str) -> list[dict[str, Any]]:
    symbol = str(symbol or "").upper().strip()
    manifest = _read_json(_manifest_file(symbol), {})
    rows = manifest.get("quarters", []) if isinstance(manifest, dict) else []
    if not isinstance(rows, list) or not rows:
        manifest = _rebuild_manifest(symbol)
        rows = manifest.get("quarters", [])
    return [row for row in rows if isinstance(row, dict)]


def delete_transcript_payload(symbol: str, quarter: str) -> bool:
    """Explicit maintenance helper. Not called by normal runtime logic."""
    path = _quarter_file(symbol, quarter)
    with _LOCK:
        try:
            if path.exists():
                path.unlink()
            _rebuild_manifest(symbol)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Persistent provider circuit breakers
# ---------------------------------------------------------------------------

def _load_circuits() -> dict[str, Any]:
    data = _read_json(_circuits_file(), {})
    return data if isinstance(data, dict) else {}


def _save_circuits(data: dict[str, Any]) -> bool:
    return _atomic_write_json(_circuits_file(), data)


def provider_circuit(provider: str) -> dict[str, Any]:
    provider = str(provider or "").strip()
    with _LOCK:
        data = _load_circuits()
        row = data.get(provider)
        if not isinstance(row, dict):
            return {"provider": provider, "open": False}
        until = _parse_dt(row.get("open_until"))
        if until is not None and until <= _utcnow():
            data.pop(provider, None)
            _save_circuits(data)
            return {"provider": provider, "open": False, "expired": True}
        out = dict(row)
        out["provider"] = provider
        out["open"] = True
        return out


def open_provider_circuit(
    provider: str,
    reason: str,
    *,
    kind: str = "provider_failure",
    seconds: int | None = None,
    until: datetime | None = None,
    http_status: int | None = None,
) -> dict[str, Any]:
    provider = str(provider or "").strip()
    now = _utcnow()
    if until is None:
        until = now + timedelta(seconds=int(seconds or 3600))
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    row = {
        "opened_at": _iso(now),
        "open_until": _iso(until),
        "reason": str(reason or "")[:500],
        "kind": str(kind or "provider_failure"),
        "http_status": http_status,
    }
    with _LOCK:
        data = _load_circuits()
        data[provider] = row
        _save_circuits(data)
    return {"provider": provider, "open": True, **row}


def clear_provider_circuit(provider: str | None = None) -> bool:
    with _LOCK:
        data = _load_circuits()
        if provider:
            data.pop(str(provider), None)
        else:
            data = {}
        return _save_circuits(data)


def provider_circuit_table(providers: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    rows = []
    for provider in providers:
        state = provider_circuit(provider)
        rows.append({
            "Provider": provider,
            "Circuit": "OPEN" if state.get("open") else "Closed",
            "Kind": state.get("kind", ""),
            "Reason": state.get("reason", ""),
            "Next retry (UTC)": state.get("open_until", ""),
            "HTTP": state.get("http_status"),
        })
    return rows


def next_utc_day_reset(grace_minutes: int = 5) -> datetime:
    now = _utcnow()
    tomorrow = (now + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=timezone.utc) + timedelta(minutes=int(grace_minutes))
