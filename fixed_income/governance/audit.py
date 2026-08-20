"""Tamper-evident operational audit trail and model registry."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4


class AuditTrail:
    """Append JSON events linked by hashes so later edits are detectable."""

    def __init__(self, path: str | Path = ".quant_audit/fixed_income_events.jsonl") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(
        self,
        actor: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not str(actor).strip() or not str(action).strip():
            raise ValueError("actor and action are required")
        with self._lock:
            previous_hash = self._last_hash()
            event = {
                "event_id": str(uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "actor": str(actor),
                "action": str(action),
                "entity_type": str(entity_type),
                "entity_id": str(entity_id),
                "payload": dict(payload or {}),
                "previous_hash": previous_hash,
            }
            event["event_hash"] = _event_hash(event)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, separators=(",", ":"), default=str) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return event

    def verify(self) -> dict[str, Any]:
        previous_hash = ""
        count = 0
        if not self.path.exists():
            return {"ok": True, "events": 0, "error": ""}
        with self.path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    return {
                        "ok": False,
                        "events": count,
                        "error": f"invalid JSON at line {line_number}: {exc}",
                    }
                if event.get("previous_hash", "") != previous_hash:
                    return {
                        "ok": False,
                        "events": count,
                        "error": f"broken hash link at line {line_number}",
                    }
                expected = _event_hash(event)
                if event.get("event_hash") != expected:
                    return {
                        "ok": False,
                        "events": count,
                        "error": f"content hash mismatch at line {line_number}",
                    }
                previous_hash = expected
                count += 1
        return {"ok": True, "events": count, "error": "", "head_hash": previous_hash}

    def _last_hash(self) -> str:
        if not self.path.exists():
            return ""
        last = ""
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    last = line
        if not last:
            return ""
        return str(json.loads(last).get("event_hash", ""))


class ModelRegistry:
    """Versioned approvals for analytical models and parameter sets."""

    def __init__(self, path: str | Path = ".quant_audit/fixed_income_models.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def register(
        self,
        model_name: str,
        version: str,
        owner: str,
        status: str,
        evidence: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_status = str(status).upper()
        if normalized_status not in {"DEVELOPMENT", "VALIDATION", "APPROVED", "RETIRED"}:
            raise ValueError("unsupported model status")
        record = {
            "model_name": str(model_name),
            "version": str(version),
            "owner": str(owner),
            "status": normalized_status,
            "evidence": dict(evidence),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        key = f"{record['model_name']}::{record['version']}"
        with self._lock:
            registry = self._load()
            registry[key] = record
            self._atomic_write(registry)
        return record

    def get(self, model_name: str, version: str) -> dict[str, Any] | None:
        return self._load().get(f"{model_name}::{version}")

    def approved(self) -> list[dict[str, Any]]:
        return [
            record
            for record in self._load().values()
            if record.get("status") == "APPROVED"
        ]

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _atomic_write(self, registry: dict[str, dict[str, Any]]) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(registry, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _event_hash(event: dict[str, Any]) -> str:
    material = {key: value for key, value in event.items() if key != "event_hash"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
