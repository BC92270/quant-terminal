from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Phase62Registry:
    """Persistent Phase-6.2 measurement/evidence synthesis state.

    The registry never mutates Phase-5 beliefs or production state. Measurement decisions,
    evidence assessments and syntheses remain research artifacts until a later explicit validation step.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "measurement_models": self.root / "phase62_measurement_models.json",
            "measurement_hypotheses": self.root / "phase62_measurement_hypotheses.json",
            "measurement_decisions": self.root / "phase62_measurement_decisions.json",
            "evidence_assessments": self.root / "phase62_evidence_assessments.json",
            "evidence_syntheses": self.root / "phase62_evidence_syntheses.json",
        }

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        return read_json_array(path, RegistryCorruptionError)

    def _upsert(self, bucket: str, id_field: str, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        path = self.paths[bucket]
        ident = str(row.get(id_field) or "")
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            for idx, prior in enumerate(rows):
                if str(prior.get(id_field) or "") == ident:
                    if bucket == "measurement_models" and str(prior.get("primary_observable_id") or ""):
                        row["primary_observable_id"] = prior.get("primary_observable_id")
                        row["status"] = prior.get("status")
                        if prior.get("updated_at"):
                            row["updated_at"] = prior.get("updated_at")
                    rows[idx] = row
                    break
            else:
                rows.append(row)
        return row

    def save_measurement_model(self, model: Any, hypotheses: list[Any] | tuple[Any, ...] = ()) -> dict[str, Any]:
        row = self._upsert("measurement_models", "measurement_model_id", model)
        for item in hypotheses:
            self._upsert("measurement_hypotheses", "measurement_hypothesis_id", item)
        return row

    def list_measurement_models(self) -> list[dict[str, Any]]:
        return self._read(self.paths["measurement_models"])

    def list_measurement_hypotheses(self) -> list[dict[str, Any]]:
        return self._read(self.paths["measurement_hypotheses"])

    def save_measurement_decision(self, decision: Any) -> dict[str, Any]:
        row = asdict(decision) if hasattr(decision, "__dataclass_fields__") else dict(decision)
        models = self.list_measurement_models()
        target = next((x for x in models if str(x.get("measurement_model_id") or "") == str(row.get("measurement_model_id") or "")), None)
        if target is None:
            raise KeyError(f"Unknown measurement model: {row.get('measurement_model_id')}")
        selected = str(row.get("selected_observable_id") or "")
        if selected not in {str(value) for value in (target.get("observable_ids") or ())}:
            raise ValueError("Measurement decision observable is not part of the selected model.")
        if str(row.get("question_id") or "") != str(target.get("question_id") or ""):
            raise ValueError("Measurement decision question does not match the selected model.")
        # Prevalidation is complete: only now may either registry file be mutated.
        decision_path = self.paths["measurement_decisions"]
        decision_id = str(row.get("decision_id") or "")
        with json_array_transaction(decision_path, RegistryCorruptionError) as decisions:
            prior_index = next((
                idx for idx, item in enumerate(decisions)
                if str(item.get("decision_id") or "") == decision_id
            ), None)
            if prior_index is not None:
                prior_decision = decisions[prior_index]
                history = list(prior_decision.get("decision_history") or [])
                history.append({
                    "at": _now_iso(),
                    "prior": {key: value for key, value in prior_decision.items() if key != "decision_history"},
                })
                row["decision_history"] = history
                decisions[prior_index] = row
            else:
                decisions.append(row)

        with json_array_transaction(self.paths["measurement_models"], RegistryCorruptionError) as current_models:
            current_target = next((
                item for item in current_models
                if str(item.get("measurement_model_id") or "") == str(row.get("measurement_model_id") or "")
            ), None)
            if current_target is None:
                raise KeyError(f"Unknown measurement model: {row.get('measurement_model_id')}")
            current_target["primary_observable_id"] = str(row.get("selected_observable_id") or "")
            current_target["status"] = "PRIMARY_SELECTED_MEASUREMENT_UNCERTAINTY_OPEN"
            current_target["updated_at"] = _now_iso()
        return row

    def list_measurement_decisions(self) -> list[dict[str, Any]]:
        return self._read(self.paths["measurement_decisions"])

    def save_evidence_assessment(self, assessment: Any) -> dict[str, Any]:
        row = asdict(assessment) if hasattr(assessment, "__dataclass_fields__") else dict(assessment)
        path = self.paths["evidence_assessments"]
        ident = str(row.get("assessment_id") or "")
        with json_array_transaction(path, RegistryCorruptionError) as rows:
            for idx, prior in enumerate(rows):
                if str(prior.get("assessment_id") or "") == ident:
                    history = list(prior.get("assessment_history") or [])
                    snapshot = {k: v for k, v in prior.items() if k != "assessment_history"}
                    history.append({"at": _now_iso(), "prior": snapshot})
                    row["assessment_history"] = history
                    rows[idx] = row
                    break
            else:
                row["assessment_history"] = []
                rows.append(row)
        return row

    def list_evidence_assessments(self) -> list[dict[str, Any]]:
        return self._read(self.paths["evidence_assessments"])

    def save_evidence_synthesis(self, synthesis: Any) -> dict[str, Any]:
        return self._upsert("evidence_syntheses", "synthesis_id", synthesis)

    def list_evidence_syntheses(self) -> list[dict[str, Any]]:
        return self._read(self.paths["evidence_syntheses"])

    def summary(self) -> dict[str, int]:
        models = self.list_measurement_models()
        return {
            "measurement_models": len(models),
            "measurement_hypotheses": len(self.list_measurement_hypotheses()),
            "primary_measurement_decisions": len(self.list_measurement_decisions()),
            "open_measurement_uncertainty": sum(1 for x in models if "MEASUREMENT_UNCERTAINTY_OPEN" in str(x.get("status") or "")),
            "evidence_assessments": len(self.list_evidence_assessments()),
            "evidence_syntheses": len(self.list_evidence_syntheses()),
        }
