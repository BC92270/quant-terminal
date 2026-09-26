"""Typed research model registry with fail-closed lifecycle transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping

from ..contracts import WorkspaceSnapshot, as_utc
from ..evidence import canonical_hash


class ModelRole(str, Enum):
    BASELINE = "baseline"
    CHALLENGER = "challenger"


class ModelLifecycle(str, Enum):
    REGISTERED = "registered"
    OFFLINE_VALIDATED = "offline_validated"
    ELIGIBLE_FOR_HUMAN_REVIEW = "eligible_for_human_review"
    SHADOW = "shadow"
    RETIRED = "retired"


class PromotionState(str, Enum):
    WAITING_EVIDENCE = "WAITING_EVIDENCE"
    ELIGIBLE_FOR_HUMAN_REVIEW = "ELIGIBLE_FOR_HUMAN_REVIEW"
    HUMAN_APPROVED_FOR_SHADOW = "HUMAN_APPROVED_FOR_SHADOW"
    RETIRED = "RETIRED"


def _validate_digest(value: str, name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


@dataclass(frozen=True, slots=True)
class HumanApproval:
    """Explicit, attributable approval for entry into shadow observation."""

    approval_id: str
    actor: str
    approved_at: datetime
    reason: str
    validation_run_id: str
    evidence_root: str

    def __post_init__(self) -> None:
        for name in ("approval_id", "actor", "reason", "validation_run_id"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        object.__setattr__(self, "approved_at", as_utc(self.approved_at))
        _validate_digest(self.evidence_root, "evidence_root")


@dataclass(frozen=True, slots=True)
class ModelRecord:
    model_id: str
    version: str
    role: ModelRole
    lifecycle: ModelLifecycle
    promotion_state: PromotionState
    feature_set_version: str
    data_cutoff: datetime
    artifact_hash: str
    config_hash: str
    training_data_hash: str
    validation_run_id: str | None = None
    validation_evidence_root: str | None = None
    approval_id: str | None = None
    rollback_model_id: str | None = None
    evidence_ids: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    research_boundary: str = "RESEARCH_ONLY"

    def __post_init__(self) -> None:
        for name in ("model_id", "version", "feature_set_version"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        object.__setattr__(self, "data_cutoff", as_utc(self.data_cutoff))
        for name in ("artifact_hash", "config_hash", "training_data_hash"):
            _validate_digest(str(getattr(self, name)), name)
        if self.validation_evidence_root is not None:
            _validate_digest(self.validation_evidence_root, "validation_evidence_root")
        if self.research_boundary != "RESEARCH_ONLY":
            raise ValueError("Market Intelligence V2 models must remain RESEARCH_ONLY")
        if self.lifecycle == ModelLifecycle.SHADOW and self.promotion_state != PromotionState.HUMAN_APPROVED_FOR_SHADOW:
            raise ValueError("SHADOW models require explicit human approval")
        if self.lifecycle in {
            ModelLifecycle.OFFLINE_VALIDATED,
            ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW,
            ModelLifecycle.SHADOW,
        } and (not self.validation_run_id or not self.validation_evidence_root):
            raise ValueError("Validated lifecycle states require linked validation evidence")
        if self.lifecycle == ModelLifecycle.SHADOW and not self.approval_id:
            raise ValueError("SHADOW models require a typed approval record")

    @property
    def key(self) -> tuple[str, str]:
        return self.model_id, self.version


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    records: tuple[ModelRecord, ...] = ()
    schema_version: str = "mi-model-registry-2.0.0"

    def __post_init__(self) -> None:
        keys = [record.key for record in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Model registry contains duplicate model/version keys")

    def get(self, model_id: str, version: str) -> ModelRecord:
        for record in self.records:
            if record.key == (model_id, version):
                return record
        raise KeyError(f"Unknown model: {model_id} {version}")

    def register(self, record: ModelRecord) -> "ModelRegistry":
        if any(existing.key == record.key for existing in self.records):
            raise ValueError(f"Model already registered: {record.model_id} {record.version}")
        return replace(self, records=(*self.records, record))

    def transition(
        self,
        model_id: str,
        version: str,
        target: ModelLifecycle,
        *,
        validation: Any | None = None,
        approval: HumanApproval | None = None,
    ) -> "ModelRegistry":
        current = self.get(model_id, version)
        allowed = {
            ModelLifecycle.REGISTERED: {ModelLifecycle.OFFLINE_VALIDATED, ModelLifecycle.RETIRED},
            ModelLifecycle.OFFLINE_VALIDATED: {
                ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW,
                ModelLifecycle.RETIRED,
            },
            ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW: {ModelLifecycle.SHADOW, ModelLifecycle.RETIRED},
            ModelLifecycle.SHADOW: {ModelLifecycle.RETIRED},
            ModelLifecycle.RETIRED: set(),
        }
        if target not in allowed[current.lifecycle]:
            raise ValueError(f"Illegal model transition: {current.lifecycle.value} -> {target.value}")
        if target in {ModelLifecycle.OFFLINE_VALIDATED, ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW}:
            from ..governance.contracts import ValidationRun

            if not isinstance(validation, ValidationRun):
                raise TypeError("Validated lifecycle transitions require a typed ValidationRun")
            if not validation.eligible_for_human_review:
                raise ValueError("Validated lifecycle transitions require a non-blocking validation run")
        if target == ModelLifecycle.SHADOW:
            if not isinstance(approval, HumanApproval):
                raise ValueError("SHADOW transition requires a typed human approval record")
            if approval.validation_run_id != current.validation_run_id:
                raise ValueError("Human approval does not match the linked validation run")
            if approval.evidence_root != current.validation_evidence_root:
                raise ValueError("Human approval does not match the linked evidence root")

        if target == ModelLifecycle.RETIRED:
            promotion = PromotionState.RETIRED
        elif target == ModelLifecycle.ELIGIBLE_FOR_HUMAN_REVIEW:
            promotion = PromotionState.ELIGIBLE_FOR_HUMAN_REVIEW
        elif target == ModelLifecycle.SHADOW:
            promotion = PromotionState.HUMAN_APPROVED_FOR_SHADOW
        else:
            promotion = PromotionState.WAITING_EVIDENCE
        updated = replace(
            current,
            lifecycle=target,
            promotion_state=promotion,
            validation_run_id=(
                str(getattr(validation, "run_id")) if validation is not None else current.validation_run_id
            ),
            validation_evidence_root=(
                str(getattr(validation, "evidence_root"))
                if validation is not None
                else current.validation_evidence_root
            ),
            approval_id=approval.approval_id if approval is not None else current.approval_id,
        )
        return replace(
            self,
            records=tuple(updated if record.key == current.key else record for record in self.records),
        )


def baseline_registry_from_snapshot(
    snapshot: WorkspaceSnapshot,
    *,
    evidence_ids: Iterable[str] = (),
    evidence_ids_by_model: Mapping[tuple[str, str], Iterable[str]] | None = None,
) -> ModelRegistry:
    """Materialize typed baseline records from the snapshot forecast contracts."""

    grouped: dict[tuple[str, str], list[Any]] = {}
    for forecast in snapshot.forecasts:
        grouped.setdefault((forecast.model_id, forecast.model_version), []).append(forecast)
    records: list[ModelRecord] = []
    shared_evidence = tuple(str(item) for item in evidence_ids)
    for (model_id, version), forecasts in sorted(grouped.items()):
        first = forecasts[0]
        cutoff = max(item.data_cutoff for item in forecasts)
        records.append(
            ModelRecord(
                model_id=model_id,
                version=version,
                role=ModelRole.BASELINE,
                lifecycle=ModelLifecycle.REGISTERED,
                promotion_state=PromotionState.WAITING_EVIDENCE,
                feature_set_version=first.feature_set_version,
                data_cutoff=cutoff,
                artifact_hash=canonical_hash(
                    {"model_id": model_id, "version": version, "implementation": "registered-code-baseline"}
                ),
                config_hash=canonical_hash(
                    {
                        "horizons": sorted(item.horizon for item in forecasts),
                        "regime": sorted({item.regime_state for item in forecasts}),
                    }
                ),
                training_data_hash=canonical_hash(
                    {
                        "cutoffs": sorted(item.data_cutoff.isoformat() for item in forecasts),
                        "sample_sizes": sorted(item.sample_size for item in forecasts),
                        "provider_status": sorted({item.provider_status.value for item in forecasts}),
                    }
                ),
                evidence_ids=tuple(
                    str(item)
                    for item in (
                        evidence_ids_by_model.get((model_id, version), ())
                        if evidence_ids_by_model is not None
                        else shared_evidence
                    )
                ),
                flags=("RESEARCH_ONLY", "NO_ARTIFACT_PROMOTION", "NO_SHADOW_HISTORY"),
            )
        )
    return ModelRegistry(records=tuple(records))
