from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class ExperimentRegistry:
    """Persistent Phase-4 registry with atomic writes and ID-based upserts."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "specifications": self.root / "phase4_experiment_specifications.json",
            "runs": self.root / "phase4_experiment_runs.json",
            "replications": self.root / "phase4_replication_plans.json",
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

    def save_specification(self, item: Any) -> None:
        self._upsert("specifications", "experiment_id", item)

    def save_run(self, item: Any) -> dict[str, Any]:
        """Persist a completed attempt without ever overwriting a distinct run.

        Phase 6.3 run IDs are unique per execution while run_signature groups equivalent
        protocols. An exact re-save is idempotent; an identity collision fails closed.
        """
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        identity = str(row.get("run_id") or "").strip()
        if not identity:
            raise ValueError("run_id is required")
        path = self.paths["runs"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("run_id") or "") == identity), None)
            if existing is not None:
                persisted_semantics = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                incoming_semantics = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
                if persisted_semantics != incoming_semantics:
                    raise ValueError(f"Run identity collision; prior attempt retained: {identity}")
                return dict(existing)
            rows.append(row)
            return row

    def save_replication(self, item: Any) -> None:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        if str(row.get("protocol_version") or "") != "SRB_INDEPENDENT_REPLICATION_V1":
            self._upsert("replications", "replication_id", row)
            return

        identity = str(row.get("replication_id") or "").strip()
        if not identity:
            raise ValueError("replication_id is required")
        path = self.paths["replications"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("replication_id") or "") == identity), None)
            incoming_execution = str(row.get("execution_status") or "")
            if existing is None:
                if str(row.get("status") or "") != "FROZEN" or incoming_execution != "NOT_RUN":
                    raise ValueError("Independent replication must be persisted FROZEN before execution.")
                rows.append(row)
                return

            if str(existing.get("protocol_fingerprint") or "") != str(row.get("protocol_fingerprint") or ""):
                raise ValueError(f"Replication protocol fingerprint is immutable: {identity}")
            prior_execution = str(existing.get("execution_status") or "")
            persisted_semantics = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            incoming_semantics = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            if prior_execution == "COMPLETE":
                if persisted_semantics != incoming_semantics:
                    raise ValueError(f"Completed replication is append-only and cannot be overwritten: {identity}")
                return
            if prior_execution != "NOT_RUN" or incoming_execution not in {"NOT_RUN", "COMPLETE"}:
                raise ValueError(f"Invalid replication lifecycle transition: {prior_execution} -> {incoming_execution}")
            if incoming_execution == "NOT_RUN" and persisted_semantics != incoming_semantics:
                raise ValueError(f"Frozen replication protocol cannot be edited in place: {identity}")
            if incoming_execution == "COMPLETE":
                if str(row.get("status") or "") != "COMPLETE":
                    raise ValueError("Completed replication execution must have status COMPLETE.")
                if not str(row.get("source_snapshot_fingerprint") or "") or not str(row.get("execution_fingerprint") or ""):
                    raise ValueError("Completed replication requires source and execution fingerprints.")
            for index, prior in enumerate(rows):
                if str(prior.get("replication_id") or "") == identity:
                    rows[index] = row
                    break

    def list_specifications(self) -> list[dict[str, Any]]:
        return self._read(self.paths["specifications"])

    def list_runs(self) -> list[dict[str, Any]]:
        return self._read(self.paths["runs"])

    def list_replications(self) -> list[dict[str, Any]]:
        return self._read(self.paths["replications"])

    def summary(self) -> dict[str, int]:
        runs = self.list_runs()
        return {
            "experiments": len(self.list_specifications()),
            "runs": len(runs),
            "passed": sum(1 for r in runs if str(r.get("verdict")) in {"IMPLEMENTATION_SANITY_PASS", "PROMISING_OOS"}),
            "failed": sum(1 for r in runs if str(r.get("verdict")) in {"IMPLEMENTATION_SANITY_FAIL", "NO_OOS_IMPROVEMENT", "INVALID"}),
            "replications": len(self.list_replications()),
        }
