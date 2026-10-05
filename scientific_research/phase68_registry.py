from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class Phase68Registry:
    """Append-only registry for frozen prospective observation programs."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "programs": self.root / "phase68_prospective_observation_programs.json",
        }

    def list_programs(self) -> list[dict[str, Any]]:
        return read_json_array(self.paths["programs"], RegistryCorruptionError)

    def save_program(self, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        from .prospective_observation import validate_prospective_observation_program

        validation = validate_prospective_observation_program(row)
        if validation["status"] != "PASS":
            raise ValueError(
                "Invalid prospective observation program: "
                + "; ".join(str(value) for value in validation["defects"])
            )
        identity = str(row.get("program_id") or "").strip()
        replication_id = str(row.get("replication_id") or "").strip()
        if not identity or not replication_id:
            raise ValueError("program_id and replication_id are required")
        if str(row.get("protocol_version") or "") != "SRB_PROSPECTIVE_OBSERVATION_PROGRAM_V1":
            raise ValueError("Unsupported prospective observation program protocol.")
        if str(row.get("status") or "") != "ACTIVE":
            raise ValueError("A prospective observation program must be persisted ACTIVE.")
        if row.get("historical_backfill_permitted") is not False or row.get("historical_evidence_eligible") is not False:
            raise ValueError("Prospective observation programs cannot authorize backfill or historical evidence.")
        if row.get("automatic_execution_authorized") is not False:
            raise ValueError("Prospective observation execution must remain explicit.")
        if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
            raise ValueError("Prospective observation programs require an intact research-only promotion lock.")

        path = self.paths["programs"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("program_id") or "") == identity), None)
            serialized = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            if existing is not None:
                prior = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                if prior != serialized:
                    raise ValueError(f"Prospective observation program is append-only: {identity}")
                return dict(existing)
            conflicting = next(
                (prior for prior in rows if str(prior.get("replication_id") or "") == replication_id),
                None,
            )
            if conflicting is not None:
                raise ValueError(
                    "A frozen prospective observation program already governs this replication: "
                    f"{conflicting.get('program_id')}"
                )
            rows.append(row)
            return row


__all__ = ["Phase68Registry"]
