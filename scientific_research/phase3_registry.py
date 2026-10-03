from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class Phase3Registry:
    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "collisions": self.root / "phase3_collisions.json",
            "discoveries": self.root / "phase3_discoveries.json",
            "gaps": self.root / "phase3_gaps.json",
            "candidates": self.root / "phase3_transmutation_candidates.json",
            "audits": self.root / "phase3_transfer_audits.json",
        }

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        return read_json_array(path, RegistryCorruptionError)

    def _upsert(self, bucket: str, id_field: str, item: Any) -> None:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        path = self.paths[bucket]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            identity = str(row.get(id_field) or "")
            index = {str(x.get(id_field) or ""): dict(x) for x in rows if x.get(id_field)}
            if identity:
                index[identity] = row
            rows[:] = list(index.values())

    def save_collision(self, item: Any) -> None:
        self._upsert("collisions", "collision_id", item)

    def save_discovery(self, item: Any) -> None:
        self._upsert("discoveries", "discovery_id", item)

    def save_gap(self, item: Any) -> None:
        self._upsert("gaps", "gap_id", item)

    def save_candidate(self, item: Any) -> None:
        self._upsert("candidates", "candidate_id", item)

    def save_audit(self, item: Any) -> None:
        self._upsert("audits", "audit_id", item)

    def list_collisions(self) -> list[dict[str, Any]]:
        return self._read(self.paths["collisions"])

    def list_discoveries(self) -> list[dict[str, Any]]:
        return self._read(self.paths["discoveries"])

    def list_gaps(self) -> list[dict[str, Any]]:
        return self._read(self.paths["gaps"])

    def list_candidates(self) -> list[dict[str, Any]]:
        return self._read(self.paths["candidates"])

    def list_audits(self) -> list[dict[str, Any]]:
        return self._read(self.paths["audits"])

    def summary(self) -> dict[str, int]:
        return {
            "collisions": len(self.list_collisions()),
            "discoveries": len(self.list_discoveries()),
            "gaps": len(self.list_gaps()),
            "candidates": len(self.list_candidates()),
            "audits": len(self.list_audits()),
        }
