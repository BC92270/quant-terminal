"""Redacted append-only audit storage for section-assistant turns."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contracts import SectionAuditRecord


_SECRET_PARTS = ("api_key", "apikey", "secret", "password", "token", "credential")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(part in str(key).casefold() for part in _SECRET_PARTS)
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    return value


class SectionAuditStore:
    """Persist metadata only; prompts, answers and provider keys are omitted."""

    def __init__(
        self,
        path: str | Path = ".quant_ai/section_assistant_audit.jsonl",
        *,
        max_records: int = 1_000,
    ) -> None:
        self.path = Path(path)
        self.max_records = max(1, int(max_records))

    def append(self, record: SectionAuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = _redact(record.to_dict())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        self._trim()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        result: list[dict[str, Any]] = []
        for line in reversed(self.path.read_text(encoding="utf-8").splitlines()[-max(1, limit) :]):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                result.append(value)
        return result

    def _trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= self.max_records:
                return
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(
                "\n".join(lines[-self.max_records :]) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        except OSError:
            # Audit storage must not make the application unavailable.
            return
