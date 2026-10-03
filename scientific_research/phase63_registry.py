from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .registry_io import json_array_transaction, read_json_array


class RegistryCorruptionError(RuntimeError):
    """Raised when an existing registry cannot be parsed safely.

    Missing registries are valid empty state. Existing malformed registries are not:
    silently treating them as empty could destroy scientific history on the next write.
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


ATTEMPT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PLANNED": ("RUNNING", "BLOCKED", "CANCELLED"),
    "RUNNING": ("COMPLETED", "FAILED", "CANCELLED"),
    "BLOCKED": ("PLANNED", "CANCELLED"),
    "COMPLETED": (),
    "FAILED": (),
    "CANCELLED": (),
}


class Phase63Registry:
    """Strict Phase-6.3 operational registry.

    It is intentionally separate from the earlier phase files. Contracts, attempts and
    reproducibility artifacts are immutable scientific records; an invalid JSON file blocks
    mutation instead of being interpreted as an empty registry.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "contracts": self.root / "phase63_historical_data_contracts.json",
            "contract_audits": self.root / "phase63_data_contract_audits.json",
            "manifests": self.root / "phase63_dataset_manifests.json",
            "attempts": self.root / "phase63_experiment_attempts.json",
            "diagnostics": self.root / "phase63_break_diagnostics.json",
            "capsules": self.root / "phase63_reproducibility_capsules.json",
            "measurement_protocols": self.root / "phase63_measurement_robustness_protocols.json",
            "measurement_reports": self.root / "phase63_measurement_robustness_reports.json",
        }

    @staticmethod
    def _row(item: Any) -> dict[str, Any]:
        return asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)

    @staticmethod
    def _canonical(value: Any) -> str:
        """Compare persisted JSON semantics, not Python tuple/list container types."""
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        return read_json_array(path, RegistryCorruptionError)

    def _immutable_save(self, bucket: str, id_field: str, item: Any) -> dict[str, Any]:
        row = self._row(item)
        identity = str(row.get(id_field) or "").strip()
        if not identity:
            raise ValueError(f"{id_field} is required")
        path = self.paths[bucket]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            existing = next((prior for prior in rows if str(prior.get(id_field) or "") == identity), None)
            if existing is not None:
                # Stable artifact IDs intentionally exclude creation time. Rebuilding an
                # identical contract/manifest later is idempotent and returns the first
                # immutable record instead of manufacturing a revision or raising solely
                # because the wall-clock timestamp changed.
                prior_semantics = {key: value for key, value in existing.items() if key != "created_at"}
                row_semantics = {key: value for key, value in row.items() if key != "created_at"}
                if self._canonical(prior_semantics) != self._canonical(row_semantics):
                    raise ValueError(f"Immutable registry identity collision for {id_field}={identity}")
                return dict(existing)
            rows.append(row)
            return row

    def save_contract(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("contracts", "contract_id", item)

    def save_contract_audit(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("contract_audits", "audit_id", item)

    def save_manifest(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("manifests", "manifest_id", item)

    def save_diagnostic(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("diagnostics", "diagnostic_id", item)

    def save_capsule(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("capsules", "capsule_id", item)

    def save_measurement_protocol(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("measurement_protocols", "protocol_id", item)

    def save_measurement_report(self, item: Any) -> dict[str, Any]:
        return self._immutable_save("measurement_reports", "report_id", item)

    def save_attempt(self, item: Any) -> dict[str, Any]:
        row = self._row(item)
        identity = str(row.get("attempt_id") or "").strip()
        if not identity:
            raise ValueError("attempt_id is required")
        path = self.paths["attempts"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            if any(str(prior.get("attempt_id") or "") == identity for prior in rows):
                raise ValueError(f"Experiment attempt already exists: {identity}")
            rows.append(row)
            return row

    def transition_attempt(
        self,
        attempt_id: str,
        new_status: str,
        reason: str,
        *,
        run_id: str = "",
        error: BaseException | None = None,
        actor: str = "SYSTEM",
    ) -> dict[str, Any]:
        path = self.paths["attempts"]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            target = next((row for row in rows if str(row.get("attempt_id") or "") == str(attempt_id)), None)
            if target is None:
                raise KeyError(f"Unknown attempt_id: {attempt_id}")
            current = str(target.get("status") or "PLANNED").upper()
            desired = str(new_status or "").strip().upper()
            if desired not in ATTEMPT_TRANSITIONS.get(current, ()):
                raise ValueError(f"Invalid attempt transition: {current} -> {desired}")
            clean_reason = str(reason or "").strip()
            if not clean_reason:
                raise ValueError("Attempt transition requires an explicit reason.")
            at = _now_iso()
            history = list(target.get("lifecycle_history") or [])
            history.append({"at": at, "from": current, "to": desired, "actor": str(actor or "SYSTEM"), "reason": clean_reason})
            target["status"] = desired
            target["lifecycle_history"] = history
            if desired == "RUNNING":
                target["started_at"] = at
            if desired in {"COMPLETED", "FAILED", "CANCELLED"}:
                target["completed_at"] = at
            if run_id:
                target["run_id"] = str(run_id)
            if error is not None:
                target["error_type"] = type(error).__name__
                target["error_message"] = str(error)[:1000]
            return dict(target)

    def list_contracts(self) -> list[dict[str, Any]]:
        return self._read(self.paths["contracts"])

    def list_contract_audits(self) -> list[dict[str, Any]]:
        return self._read(self.paths["contract_audits"])

    def list_manifests(self) -> list[dict[str, Any]]:
        return self._read(self.paths["manifests"])

    def list_attempts(self) -> list[dict[str, Any]]:
        return self._read(self.paths["attempts"])

    def list_diagnostics(self) -> list[dict[str, Any]]:
        return self._read(self.paths["diagnostics"])

    def list_capsules(self) -> list[dict[str, Any]]:
        return self._read(self.paths["capsules"])

    def list_measurement_protocols(self) -> list[dict[str, Any]]:
        return self._read(self.paths["measurement_protocols"])

    def list_measurement_reports(self) -> list[dict[str, Any]]:
        return self._read(self.paths["measurement_reports"])

    def summary(self) -> dict[str, int]:
        attempts = self.list_attempts()
        return {
            "data_contracts": len(self.list_contracts()),
            "contract_audits": len(self.list_contract_audits()),
            "dataset_manifests": len(self.list_manifests()),
            "experiment_attempts": len(attempts),
            "completed_attempts": sum(1 for row in attempts if str(row.get("status") or "") == "COMPLETED"),
            "failed_attempts": sum(1 for row in attempts if str(row.get("status") or "") == "FAILED"),
            "break_diagnostics": len(self.list_diagnostics()),
            "reproducibility_capsules": len(self.list_capsules()),
            "measurement_protocols": len(self.list_measurement_protocols()),
            "measurement_reports": len(self.list_measurement_reports()),
        }
