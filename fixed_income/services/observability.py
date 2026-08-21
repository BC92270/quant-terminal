"""Structured logging and composable health probes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
from time import perf_counter
from typing import Any, Callable


@dataclass(frozen=True)
class HealthResult:
    name: str
    ok: bool
    latency_ms: float
    detail: str = ""
    checked_at: str = ""


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("run_id", "model_version", "actor", "entity_id"):
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, sort_keys=True, default=str)


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger("fixed_income")
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger


class HealthMonitor:
    def __init__(self) -> None:
        self._probes: dict[str, Callable[[], Any]] = {}

    def register(self, name: str, probe: Callable[[], Any]) -> None:
        if not str(name).strip():
            raise ValueError("probe name is required")
        if name in self._probes:
            raise ValueError(f"probe already registered: {name}")
        self._probes[name] = probe

    def check(self) -> dict[str, Any]:
        results: list[HealthResult] = []
        for name, probe in self._probes.items():
            started = perf_counter()
            try:
                detail = probe()
                ok = True
                text = str(detail)
            except Exception as exc:
                ok = False
                text = f"{type(exc).__name__}: {exc}"
            latency_ms = (perf_counter() - started) * 1000.0
            results.append(
                HealthResult(
                    name=name,
                    ok=ok,
                    latency_ms=latency_ms,
                    detail=text,
                    checked_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        return {
            "ok": all(result.ok for result in results),
            "checks": [asdict(result) for result in results],
        }
