from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


FAILURE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("INVESTIGATING", "REJECTED_AS_ARTIFACT"),
    "INVESTIGATING": ("OPEN", "ADDRESSED", "REJECTED_AS_ARTIFACT"),
    "ADDRESSED": ("INVESTIGATING", "RESOLVED"),
    "RESOLVED": ("INVESTIGATING",),
    "REJECTED_AS_ARTIFACT": ("OPEN",),
}
SURPRISE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "NEW": ("ACKNOWLEDGED", "INVESTIGATING"),
    "ACKNOWLEDGED": ("INVESTIGATING",),
    "INVESTIGATING": ("ACKNOWLEDGED", "EXPLAINED"),
    "EXPLAINED": ("INVESTIGATING",),
}
FAILURE_CLOSED = {"RESOLVED", "REJECTED_AS_ARTIFACT"}
SURPRISE_CLOSED = {"EXPLAINED"}
FAILURE_EVIDENCE_REQUIRED = {"RESOLVED", "REJECTED_AS_ARTIFACT"}
SURPRISE_EVIDENCE_REQUIRED = {"EXPLAINED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canon_failure_status(status: str) -> str:
    value = str(status or "OPEN").strip().upper()
    return value if value in FAILURE_TRANSITIONS else "OPEN"


def _canon_surprise_status(status: str) -> str:
    value = str(status or "NEW").strip().upper()
    if value == "OPEN":  # Phase-5.0 legacy state
        return "NEW"
    return value if value in SURPRISE_TRANSITIONS else "NEW"


def _clean_refs(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(x).strip() for x in (values or ()) if str(x).strip()))


class ValidationRegistry:
    """Persistent Phase-5 validation/learning registry with guarded memory lifecycles."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "reviews": self.root / "phase5_validation_reviews.json",
            "failures": self.root / "phase5_failure_memory.json",
            "surprises": self.root / "phase5_surprise_memory.json",
            "theories": self.root / "phase5_theory_populations.json",
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
                prior = index.get(identity) or {}
                # Validation reruns must not erase an explicit lifecycle transition/history.
                if bucket in {"failures", "surprises"} and prior:
                    for field in ("status", "status_updated_at", "status_reason", "status_evidence_refs", "lifecycle_history"):
                        if prior.get(field) not in (None, "", [], ()):
                            row[field] = prior.get(field)
                index[identity] = row
            rows[:] = list(index.values())

    def save_review(self, item: Any) -> None:
        self._upsert("reviews", "review_id", item)

    def save_failure(self, item: Any) -> None:
        self._upsert("failures", "failure_id", item)

    def save_surprise(self, item: Any) -> None:
        self._upsert("surprises", "surprise_id", item)

    def save_theory_population(self, item: Any) -> None:
        self._upsert("theories", "population_id", item)

    def list_reviews(self) -> list[dict[str, Any]]:
        return self._read(self.paths["reviews"])

    def list_failures(self) -> list[dict[str, Any]]:
        return self._read(self.paths["failures"])

    def list_surprises(self) -> list[dict[str, Any]]:
        return self._read(self.paths["surprises"])

    def list_theory_populations(self) -> list[dict[str, Any]]:
        return self._read(self.paths["theories"])

    @staticmethod
    def failure_next_statuses(status: str) -> tuple[str, ...]:
        return FAILURE_TRANSITIONS.get(_canon_failure_status(status), ())

    @staticmethod
    def surprise_next_statuses(status: str) -> tuple[str, ...]:
        return SURPRISE_TRANSITIONS.get(_canon_surprise_status(status), ())

    def _transition(
        self,
        bucket: str,
        id_field: str,
        identity: str,
        new_status: str,
        reason: str,
        evidence_refs: Iterable[str] = (),
        actor: str = "HUMAN",
    ) -> dict[str, Any]:
        path = self.paths[bucket]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            target = next((row for row in rows if str(row.get(id_field) or "") == str(identity)), None)
            if target is None:
                raise KeyError(f"Unknown {id_field}: {identity}")

            is_failure = bucket == "failures"
            current = _canon_failure_status(target.get("status")) if is_failure else _canon_surprise_status(target.get("status"))
            desired = str(new_status or "").strip().upper()
            allowed = FAILURE_TRANSITIONS.get(current, ()) if is_failure else SURPRISE_TRANSITIONS.get(current, ())
            if desired not in allowed:
                raise ValueError(f"Invalid lifecycle transition: {current} -> {desired}. Allowed: {', '.join(allowed) or 'none'}")
            clean_reason = str(reason or "").strip()
            if not clean_reason:
                raise ValueError("A lifecycle transition requires an explicit reason.")
            refs = _clean_refs(evidence_refs)
            evidence_required = FAILURE_EVIDENCE_REQUIRED if is_failure else SURPRISE_EVIDENCE_REQUIRED
            if desired in evidence_required and not refs:
                raise ValueError(f"Transition to {desired} requires at least one evidence reference.")

            at = _now_iso()
            history = list(target.get("lifecycle_history") or [])
            if not history:
                history.append({
                    "at": str(target.get("created_at") or at),
                    "from": "",
                    "to": current,
                    "actor": "LEGACY_IMPORT" if target.get("status") else "SYSTEM",
                    "reason": str(target.get("status_reason") or "Existing memory state imported into guarded lifecycle."),
                    "evidence_refs": list(target.get("status_evidence_refs") or []),
                })
            history.append({
                "at": at,
                "from": current,
                "to": desired,
                "actor": str(actor or "HUMAN"),
                "reason": clean_reason,
                "evidence_refs": list(refs),
            })
            target["status"] = desired
            target["status_updated_at"] = at
            target["status_reason"] = clean_reason
            target["status_evidence_refs"] = list(refs)
            target["lifecycle_history"] = history
            return dict(target)

    def transition_failure(
        self, failure_id: str, new_status: str, reason: str, evidence_refs: Iterable[str] = (), actor: str = "HUMAN"
    ) -> dict[str, Any]:
        return self._transition("failures", "failure_id", failure_id, new_status, reason, evidence_refs, actor)

    def transition_surprise(
        self, surprise_id: str, new_status: str, reason: str, evidence_refs: Iterable[str] = (), actor: str = "HUMAN"
    ) -> dict[str, Any]:
        return self._transition("surprises", "surprise_id", surprise_id, new_status, reason, evidence_refs, actor)

    def _reconcile_legacy_history(
        self,
        bucket: str,
        id_field: str,
        identity: str,
        reason: str,
        actor: str,
    ) -> dict[str, Any]:
        """Align legacy history with its stored status without asserting an unknown transition.

        This is deliberately separate from the guarded lifecycle transition API. It never
        changes the current status, never closes an item, and explicitly records that the
        original transition time, actor and evidence are unknown.
        """
        path = self.paths[bucket]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            target = next((row for row in rows if str(row.get(id_field) or "") == str(identity)), None)
            if target is None:
                raise KeyError(f"Unknown {id_field}: {identity}")
            clean_reason = str(reason or "").strip()
            if not clean_reason:
                raise ValueError("Legacy lifecycle alignment requires an explicit migration rationale.")
            current = str(target.get("status") or ("OPEN" if bucket == "failures" else "NEW")).strip().upper()
            allowed_statuses = FAILURE_TRANSITIONS if bucket == "failures" else SURPRISE_TRANSITIONS
            if current not in allowed_statuses:
                raise ValueError(f"Unsupported stored lifecycle status: {current}")
            history = list(target.get("lifecycle_history") or ())
            last_status = str((history[-1] if history else {}).get("to") or "").strip().upper()
            if last_status == current:
                return dict(target)
            at = _now_iso()
            history.append({
                "at": at,
                "from": last_status,
                "to": current,
                "actor": str(actor or "MIGRATION"),
                "reason": clean_reason,
                "evidence_refs": list(target.get("status_evidence_refs") or ()),
                "transition_kind": "LEGACY_STATE_ALIGNMENT",
                "historical_transition_asserted": False,
                "original_transition_time": "UNKNOWN",
                "original_transition_actor": "UNKNOWN",
            })
            target["lifecycle_history"] = history
            target["lifecycle_reconciled_at"] = at
            target["lifecycle_reconciliation_actor"] = str(actor or "MIGRATION")
            target["lifecycle_reconciliation_reason"] = clean_reason
            return dict(target)

    def reconcile_failure_history(
        self, failure_id: str, reason: str, actor: str = "MIGRATION"
    ) -> dict[str, Any]:
        return self._reconcile_legacy_history(
            "failures", "failure_id", failure_id, reason, actor,
        )

    def reconcile_surprise_history(
        self, surprise_id: str, reason: str, actor: str = "MIGRATION"
    ) -> dict[str, Any]:
        return self._reconcile_legacy_history(
            "surprises", "surprise_id", surprise_id, reason, actor,
        )

    # Backward-compatible low-level methods. New UI and agents must use guarded transition_* methods.
    def _legacy_update_status(self, bucket: str, id_field: str, identity: str, status: str) -> bool:
        path = self.paths[bucket]
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            changed = False
            for row in rows:
                if str(row.get(id_field) or "") == str(identity):
                    row["status"] = str(status).strip().upper()
                    row["status_updated_at"] = _now_iso()
                    row["status_reason"] = "Legacy direct status update; use guarded lifecycle transitions for new workflows."
                    changed = True
                    break
            return changed

    def update_failure_status(self, failure_id: str, status: str) -> bool:
        return self._legacy_update_status("failures", "failure_id", failure_id, status)

    def update_surprise_status(self, surprise_id: str, status: str) -> bool:
        return self._legacy_update_status("surprises", "surprise_id", surprise_id, status)

    def summary(self) -> dict[str, int]:
        failures = self.list_failures()
        surprises = self.list_surprises()
        unresolved_failures = sum(
            1 for x in failures if _canon_failure_status(x.get("status")) not in FAILURE_CLOSED
        )
        unresolved_surprises = sum(
            1 for x in surprises if _canon_surprise_status(x.get("status")) not in SURPRISE_CLOSED
        )
        return {
            "reviews": len(self.list_reviews()),
            # Legacy keys retained, but now count unresolved lifecycle states rather than literal OPEN only.
            "open_failures": unresolved_failures,
            "open_surprises": unresolved_surprises,
            "unresolved_failures": unresolved_failures,
            "unresolved_surprises": unresolved_surprises,
            "theory_populations": len(self.list_theory_populations()),
        }
