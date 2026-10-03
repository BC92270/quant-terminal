from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class Phase65Registry:
    """Append-only lifecycle registry for cross-runtime verification records."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "verifications": self.root / "phase65_cross_runtime_verifications.json",
        }

    def list_verifications(self) -> list[dict[str, Any]]:
        return read_json_array(self.paths["verifications"], RegistryCorruptionError)

    def save_verification(self, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        identity = str(row.get("verification_id") or "").strip()
        if not identity:
            raise ValueError("verification_id is required")
        if str(row.get("protocol_version") or "") != "SRB_CROSS_RUNTIME_VERIFICATION_V1":
            raise ValueError("Unsupported cross-runtime verification protocol.")
        if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
            raise ValueError("Cross-runtime verification requires an intact research-only promotion lock.")
        path = self.paths["verifications"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("verification_id") or "") == identity), None)
            incoming_execution = str(row.get("execution_status") or "")
            if existing is None:
                if str(row.get("status") or "") != "FROZEN" or incoming_execution != "NOT_RUN":
                    raise ValueError("Cross-runtime challenge must be persisted FROZEN before execution.")
                rows.append(row)
                return row

            for immutable in (
                "challenge_fingerprint",
                "replication_id",
                "source_snapshot_fingerprint",
                "reference_execution_fingerprint",
                "engine_source_fingerprint",
            ):
                if str(existing.get(immutable) or "") != str(row.get(immutable) or ""):
                    raise ValueError(f"Cross-runtime {immutable} is immutable: {identity}")
            persisted = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            incoming = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            prior_execution = str(existing.get("execution_status") or "")
            if prior_execution == "COMPLETE":
                if persisted != incoming:
                    raise ValueError(f"Completed cross-runtime verification is append-only: {identity}")
                return dict(existing)
            if prior_execution != "NOT_RUN" or incoming_execution not in {"NOT_RUN", "COMPLETE"}:
                raise ValueError(f"Invalid cross-runtime lifecycle transition: {prior_execution} -> {incoming_execution}")
            if incoming_execution == "NOT_RUN" and persisted != incoming:
                raise ValueError(f"Frozen cross-runtime challenge cannot be edited in place: {identity}")
            if incoming_execution == "COMPLETE":
                if str(row.get("status") or "") != "COMPLETE":
                    raise ValueError("Completed cross-runtime execution must have status COMPLETE.")
                if str(row.get("parity_status") or "") not in {"PASS", "FAIL"}:
                    raise ValueError("Completed cross-runtime execution requires a PASS or FAIL parity result.")
                if not str(row.get("result_fingerprint") or "") or not str(row.get("engine_build_fingerprint") or ""):
                    raise ValueError("Completed cross-runtime execution requires result and build fingerprints.")
            for index, prior in enumerate(rows):
                if str(prior.get("verification_id") or "") == identity:
                    rows[index] = row
                    break
            return row
