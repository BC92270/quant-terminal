from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


class Phase67Registry:
    """Append-only lifecycle registry for governed cross-provider diagnostics."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "triangulations": self.root / "phase67_cross_provider_triangulations.json",
        }

    def list_triangulations(self) -> list[dict[str, Any]]:
        return read_json_array(self.paths["triangulations"], RegistryCorruptionError)

    def save_triangulation(self, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        identity = str(row.get("triangulation_id") or "").strip()
        if not identity:
            raise ValueError("triangulation_id is required")
        if str(row.get("protocol_version") or "") != "SRB_CROSS_PROVIDER_TRIANGULATION_V1":
            raise ValueError("Unsupported cross-provider triangulation protocol.")
        if row.get("historical_evidence_eligible") is not False:
            raise ValueError("Revised-history triangulation cannot become historical point-in-time evidence.")
        if str(row.get("point_in_time_status") or "") != "NOT_POINT_IN_TIME":
            raise ValueError("Cross-provider revised histories must remain explicitly non-point-in-time.")
        if row.get("automatic_promotion_authorized") is not False or str(row.get("production_status") or "") != "RESEARCH_ONLY":
            raise ValueError("Cross-provider triangulation requires an intact research-only promotion lock.")

        path = self.paths["triangulations"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get("triangulation_id") or "") == identity), None)
            incoming_execution = str(row.get("execution_status") or "")
            if existing is None:
                if str(row.get("status") or "") != "FROZEN" or incoming_execution != "NOT_RUN":
                    raise ValueError("Cross-provider protocol must be persisted FROZEN before acquisition.")
                rows.append(row)
                return row

            for immutable in (
                "protocol_fingerprint",
                "replication_id",
                "direct_reconciliation_id",
                "direct_snapshot_id",
                "direct_snapshot_fingerprint",
                "source_url",
                "comparison_matrix",
                "direct_series_matrix",
                "history_semantics",
            ):
                if existing.get(immutable) != row.get(immutable):
                    raise ValueError(f"Cross-provider {immutable} is immutable: {identity}")
            persisted = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            incoming = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
            prior_execution = str(existing.get("execution_status") or "")
            if prior_execution == "COMPLETE":
                if persisted != incoming:
                    raise ValueError(f"Completed cross-provider triangulation is append-only: {identity}")
                return dict(existing)
            if prior_execution != "NOT_RUN" or incoming_execution not in {"NOT_RUN", "COMPLETE"}:
                raise ValueError(f"Invalid cross-provider lifecycle transition: {prior_execution} -> {incoming_execution}")
            if incoming_execution == "NOT_RUN" and persisted != incoming:
                raise ValueError(f"Frozen cross-provider protocol cannot be edited in place: {identity}")
            if incoming_execution == "COMPLETE":
                if str(row.get("status") or "") != "COMPLETE":
                    raise ValueError("Completed cross-provider acquisition must have status COMPLETE.")
                if str(row.get("source_integrity_status") or "") != "PASS":
                    raise ValueError("Completed cross-provider acquisition requires source integrity PASS.")
                if str(row.get("coverage_status") or "") != "PASS":
                    raise ValueError("Completed cross-provider acquisition requires coverage PASS.")
                if str(row.get("comparability_status") or "") not in {"PASS", "FAIL"}:
                    raise ValueError("Completed cross-provider acquisition requires an explicit comparability result.")
                if str(row.get("triangulation_outcome") or "") not in {
                    "CONCORDANT",
                    "MEASUREMENT_DIVERGENCE",
                    "NOT_COMPARABLE",
                }:
                    raise ValueError("Completed cross-provider acquisition requires a governed outcome.")
                for required in (
                    "oecd_snapshot_id",
                    "oecd_snapshot_fingerprint",
                    "raw_csv_sha256",
                    "triangulation_fingerprint",
                ):
                    if not str(row.get(required) or ""):
                        raise ValueError(f"Completed cross-provider triangulation is missing {required}.")
            for index, prior in enumerate(rows):
                if str(prior.get("triangulation_id") or "") == identity:
                    rows[index] = row
                    break
            return row


__all__ = ["Phase67Registry"]
