from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class Phase66Registry:
    """Append-only lifecycle registry for direct-source observations."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "reconciliations": self.root / "phase66_direct_source_reconciliations.json",
        }

    def list_reconciliations(self) -> list[dict[str, Any]]:
        return read_json_array(self.paths["reconciliations"], RegistryCorruptionError)

    def save_reconciliation(self, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        identity = str(row.get("reconciliation_id") or "").strip()
        if not identity:
            raise ValueError("reconciliation_id is required")
        if str(row.get("protocol_version") or "") != "SRB_DIRECT_BIS_RECONCILIATION_V1":
            raise ValueError("Unsupported direct-source reconciliation protocol.")
        if row.get("historical_evidence_eligible") is not False:
            raise ValueError("Revised-history reconciliation cannot become historical point-in-time evidence.")
        if str(row.get("point_in_time_status") or "") != "NOT_POINT_IN_TIME":
            raise ValueError("Direct BIS revised history must remain explicitly non-point-in-time.")
        if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
            raise ValueError("Direct-source reconciliation requires an intact research-only promotion lock.")

        path = self.paths["reconciliations"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("reconciliation_id") or "") == identity), None)
            incoming_execution = str(row.get("execution_status") or "")
            if existing is None:
                if str(row.get("status") or "") != "FROZEN" or incoming_execution != "NOT_RUN":
                    raise ValueError("Direct-source protocol must be persisted FROZEN before acquisition.")
                rows.append(row)
                return row

            for immutable in (
                "protocol_fingerprint",
                "replication_id",
                "reference_snapshot_id",
                "reference_snapshot_fingerprint",
                "source_url",
                "history_semantics",
            ):
                if str(existing.get(immutable) or "") != str(row.get(immutable) or ""):
                    raise ValueError(f"Direct-source {immutable} is immutable: {identity}")
            persisted = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            incoming = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            prior_execution = str(existing.get("execution_status") or "")
            if prior_execution == "COMPLETE":
                if persisted != incoming:
                    raise ValueError(f"Completed direct-source reconciliation is append-only: {identity}")
                return dict(existing)
            if prior_execution != "NOT_RUN" or incoming_execution not in {"NOT_RUN", "COMPLETE"}:
                raise ValueError(f"Invalid direct-source lifecycle transition: {prior_execution} -> {incoming_execution}")
            if incoming_execution == "NOT_RUN" and persisted != incoming:
                raise ValueError(f"Frozen direct-source protocol cannot be edited in place: {identity}")
            if incoming_execution == "COMPLETE":
                if str(row.get("status") or "") != "COMPLETE":
                    raise ValueError("Completed direct-source acquisition must have status COMPLETE.")
                if str(row.get("source_integrity_status") or "") != "PASS":
                    raise ValueError("Completed direct-source acquisition requires source integrity PASS.")
                if str(row.get("coverage_status") or "") != "PASS":
                    raise ValueError("Completed direct-source acquisition requires coverage PASS.")
                if str(row.get("reconciliation_status") or "") not in {"EXACT_MATCH", "RECONCILED_WITH_REVISIONS"}:
                    raise ValueError("Completed direct-source acquisition requires a governed reconciliation result.")
                for required in (
                    "direct_snapshot_id",
                    "direct_snapshot_fingerprint",
                    "raw_archive_sha256",
                    "reconciliation_fingerprint",
                ):
                    if not str(row.get(required) or ""):
                        raise ValueError(f"Completed direct-source acquisition is missing {required}.")
            for index, prior in enumerate(rows):
                if str(prior.get("reconciliation_id") or "") == identity:
                    rows[index] = row
                    break
            return row


__all__ = ["Phase66Registry"]
