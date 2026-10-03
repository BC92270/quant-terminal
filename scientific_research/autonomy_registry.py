from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


QUESTION_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("PLANNED", "STOPPED"),
    "PLANNED": ("INVESTIGATING", "STOPPED"),
    "INVESTIGATING": ("PARTIALLY_ANSWERED", "ANSWERED", "STOPPED"),
    "PARTIALLY_ANSWERED": ("INVESTIGATING", "ANSWERED", "STOPPED"),
    "ANSWERED": (),
    "STOPPED": (),
}
QUESTION_EVIDENCE_REQUIRED = {"ANSWERED"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_refs(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(x).strip() for x in (values or ()) if str(x).strip()))


class AutonomyRegistry:
    """Persistent Phase-6 research-director state with atomic, ID-based writes."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "questions": self.root / "phase6_open_questions.json",
            "hypotheses": self.root / "phase6_hypotheses.json",
            "plans": self.root / "phase6_research_plans.json",
            "cycles": self.root / "phase6_director_cycles.json",
            "diary": self.root / "phase6_scientific_diary.json",
            "scouts": self.root / "phase6_literature_scouts.json",
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
                if bucket == "questions" and prior:
                    for field in ("status", "lifecycle_history", "plan_id", "hypothesis_ids", "selected_observable_id", "grounded_evidence_refs"):
                        if prior.get(field) not in (None, "", [], ()):
                            row[field] = prior.get(field)
                index[identity] = row
            rows[:] = list(index.values())

    def save_question(self, item: Any) -> None:
        self._upsert("questions", "question_id", item)

    def save_hypothesis(self, item: Any) -> None:
        self._upsert("hypotheses", "hypothesis_id", item)

    def save_plan(self, item: Any) -> None:
        self._upsert("plans", "plan_id", item)

    def save_cycle(self, item: Any) -> None:
        self._upsert("cycles", "cycle_id", item)

    def save_diary(self, item: Any) -> None:
        self._upsert("diary", "diary_id", item)

    def save_scout(self, item: Any) -> None:
        self._upsert("scouts", "scout_id", item)

    def list_questions(self) -> list[dict[str, Any]]:
        return self._read(self.paths["questions"])

    def list_hypotheses(self) -> list[dict[str, Any]]:
        return self._read(self.paths["hypotheses"])

    def list_plans(self) -> list[dict[str, Any]]:
        return self._read(self.paths["plans"])

    def list_cycles(self) -> list[dict[str, Any]]:
        return self._read(self.paths["cycles"])

    def list_diary(self) -> list[dict[str, Any]]:
        return self._read(self.paths["diary"])

    def list_scouts(self) -> list[dict[str, Any]]:
        return self._read(self.paths["scouts"])

    @staticmethod
    def question_next_statuses(status: str) -> tuple[str, ...]:
        return QUESTION_TRANSITIONS.get(str(status or "OPEN").strip().upper(), ())

    def transition_question(
        self,
        question_id: str,
        new_status: str,
        reason: str,
        evidence_refs: Iterable[str] = (),
        actor: str = "HUMAN",
    ) -> dict[str, Any]:
        with json_array_transaction(self.paths["questions"], RegistryCorruptionError) as rows:
            target = next((x for x in rows if str(x.get("question_id") or "") == str(question_id)), None)
            if target is None:
                raise KeyError(f"Unknown question_id: {question_id}")
            current = str(target.get("status") or "OPEN").strip().upper()
            desired = str(new_status or "").strip().upper()
            allowed = QUESTION_TRANSITIONS.get(current, ())
            if desired not in allowed:
                raise ValueError(f"Invalid question transition: {current} -> {desired}. Allowed: {', '.join(allowed) or 'none'}")
            clean_reason = str(reason or "").strip()
            if not clean_reason:
                raise ValueError("A question lifecycle transition requires an explicit reason.")
            refs = _clean_refs(evidence_refs)
            if desired in QUESTION_EVIDENCE_REQUIRED and not refs:
                raise ValueError(f"Transition to {desired} requires at least one evidence reference.")
            at = _now_iso()
            history = list(target.get("lifecycle_history") or [])
            if not history:
                history.append({
                    "at": str(target.get("created_at") or at),
                    "from": "",
                    "to": current,
                    "actor": "LEGACY_IMPORT",
                    "reason": "Question imported into guarded Phase-6 lifecycle.",
                    "evidence_refs": list(target.get("origin_refs") or []),
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
            target["lifecycle_history"] = history
        return dict(target)

    def attach_plan(self, question_id: str, plan_id: str, hypothesis_ids: Iterable[str]) -> bool:
        changed = False
        with json_array_transaction(self.paths["questions"], RegistryCorruptionError) as rows:
            for row in rows:
                if str(row.get("question_id") or "") == str(question_id):
                    row["plan_id"] = str(plan_id or "")
                    row["hypothesis_ids"] = list(_clean_refs(hypothesis_ids))
                    if str(row.get("status") or "OPEN") == "OPEN":
                        row["status"] = "PLANNED"
                        history = list(row.get("lifecycle_history") or [])
                        history.append({
                            "at": _now_iso(), "from": "OPEN", "to": "PLANNED", "actor": "RESEARCH_DIRECTOR",
                            "reason": "Bounded director cycle created a guarded research plan.", "evidence_refs": [str(plan_id)],
                        })
                        row["lifecycle_history"] = history
                    changed = True
                    break
        return changed

    def reopen_question(
        self,
        question_id: str,
        reason: str,
        evidence_refs: Iterable[str] = (),
        actor: str = "HUMAN",
    ) -> dict[str, Any]:
        with json_array_transaction(self.paths["questions"], RegistryCorruptionError) as rows:
            target = next((x for x in rows if str(x.get("question_id") or "") == str(question_id)), None)
            if target is None:
                raise KeyError(f"Unknown question_id: {question_id}")
            current = str(target.get("status") or "OPEN").strip().upper()
            if current not in {"ANSWERED", "STOPPED"}:
                raise ValueError(f"Explicit reopen is available only from ANSWERED or STOPPED, not {current}.")
            clean_reason = str(reason or "").strip()
            if not clean_reason:
                raise ValueError("Reopening a question requires an explicit reason.")
            refs = _clean_refs(evidence_refs)
            at = _now_iso()
            history = list(target.get("lifecycle_history") or [])
            history.append({
                "at": at,
                "from": current,
                "to": "OPEN",
                "actor": str(actor or "HUMAN"),
                "reason": clean_reason,
                "evidence_refs": list(refs),
                "transition_type": "EXPLICIT_REOPEN",
            })
            target["status"] = "OPEN"
            target["lifecycle_history"] = history
        return dict(target)

    def attach_observable(self, question_id: str, observable_id: str) -> bool:
        changed = False
        with json_array_transaction(self.paths["questions"], RegistryCorruptionError) as rows:
            for row in rows:
                if str(row.get("question_id") or "") == str(question_id):
                    row["selected_observable_id"] = str(observable_id or "")
                    changed = True
                    break
        return changed

    def attach_grounded_evidence(self, question_id: str, evidence_id: str) -> bool:
        changed = False
        with json_array_transaction(self.paths["questions"], RegistryCorruptionError) as rows:
            for row in rows:
                if str(row.get("question_id") or "") == str(question_id):
                    refs = list(row.get("grounded_evidence_refs") or [])
                    if str(evidence_id or "") and str(evidence_id) not in refs:
                        refs.append(str(evidence_id))
                    row["grounded_evidence_refs"] = refs
                    changed = True
                    break
        return changed

    def update_plan_task(
        self,
        plan_id: str,
        task_id: str,
        status: str | None = None,
        result_ref: str | None = None,
        clear_blockers: bool = False,
    ) -> dict[str, Any]:
        with json_array_transaction(self.paths["plans"], RegistryCorruptionError) as rows:
            plan = next((x for x in rows if str(x.get("plan_id") or "") == str(plan_id)), None)
            if plan is None:
                raise KeyError(f"Unknown plan_id: {plan_id}")
            found = None
            for task in plan.get("tasks") or []:
                if str(task.get("task_id") or "") != str(task_id):
                    continue
                if status is not None:
                    task["status"] = str(status)
                if result_ref:
                    refs = list(task.get("result_refs") or [])
                    if str(result_ref) not in refs:
                        refs.append(str(result_ref))
                    task["result_refs"] = refs
                if clear_blockers:
                    task["blockers"] = []
                found = task
                break
            if found is None:
                raise KeyError(f"Unknown task_id: {task_id}")
        return dict(found)

    def refresh_plan_after_observable(self, plan_id: str, observable_id: str) -> dict[str, Any]:
        with json_array_transaction(self.paths["plans"], RegistryCorruptionError) as rows:
            plan = next((x for x in rows if str(x.get("plan_id") or "") == str(plan_id)), None)
            if plan is None:
                raise KeyError(f"Unknown plan_id: {plan_id}")
            for task in plan.get("tasks") or []:
                ttype = str(task.get("task_type") or "")
                if ttype == "OBSERVABLE_DEFINITION":
                    task["status"] = "COMPLETE"
                    task["result_refs"] = list(dict.fromkeys(list(task.get("result_refs") or []) + [str(observable_id)]))
                    task["blockers"] = []
                elif ttype == "HISTORICAL_DATA_CONTRACT" and str(task.get("status") or "") == "WAITING_INPUT":
                    # Observable definition removes only one prerequisite. A dataset is still required.
                    task["status"] = "WAITING_INPUT"
                    task["blockers"] = ["A chronological target-domain dataset is still required for the selected observable."]
                elif ttype == "EXPERIMENT_DESIGN":
                    task["status"] = "BLOCKED"
                    task["blockers"] = ["Historical data contract and grounded evidence review remain required before experiment design."]
            plan["status"] = "WAITING_INPUT"
            plan["next_action"] = "Provide a chronological dataset for the selected observable while grounded literature review continues."
        return dict(plan)

    def summary(self) -> dict[str, int]:
        questions = self.list_questions()
        plans = self.list_plans()
        cycles = self.list_cycles()
        scouts = self.list_scouts()
        return {
            "questions": len(questions),
            "open_questions": sum(1 for x in questions if str(x.get("status") or "OPEN") not in {"ANSWERED", "STOPPED"}),
            "hypotheses": len(self.list_hypotheses()),
            "plans": len(plans),
            "active_plans": sum(1 for x in plans if str(x.get("status") or "") not in {"COMPLETED", "STOPPED"}),
            "cycles": len(cycles),
            "diary_entries": len(self.list_diary()),
            "literature_scouts": len(scouts),
        }
