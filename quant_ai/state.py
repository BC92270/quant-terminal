from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import CommitteeRun


class AuditStore:
    def __init__(self, path: str | Path = ".quant_ai/audit.jsonl", max_records: int = 200) -> None:
        self.path = Path(path)
        self.max_records = max_records

    def append(self, run: CommitteeRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = run.to_dict()
        # Defense in depth: provider keys are never part of CommitteeRun; redact suspicious fields anyway.
        clean = self._redact(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=False) + "\n")
        self._trim()

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()[-max(1, limit) :]
        result: list[dict[str, Any]] = []
        for line in reversed(lines):
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    result.append(value)
            except json.JSONDecodeError:
                continue
        return result

    def _trim(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
            if len(lines) <= self.max_records:
                return
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-self.max_records :]) + "\n", encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "[REDACTED]" if any(token in str(key).lower() for token in ("api_key", "secret", "password", "token")) else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        return value
