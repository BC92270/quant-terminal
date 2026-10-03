from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .closed_loop_engine import build_budget_ledger
from .phase61_models import BudgetEvent, BudgetLedger
from .phase63_registry import RegistryCorruptionError
from .registry_io import json_array_transaction, read_json_array


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_refs(values: Iterable[str] | None) -> list[str]:
    return list(dict.fromkeys(str(x).strip() for x in (values or ()) if str(x).strip()))


def _stable_event_id(ledger_id: str, category: str, ref_id: str, amount: float, created_at: str) -> str:
    import hashlib
    payload = f"{ledger_id}|{category}|{ref_id}|{amount:.8f}|{created_at}"
    return f"BUDGETEVT-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


class ClosedLoopRegistry:
    """Phase-6.1 persistent closed-loop state.

    This registry never mutates production state or model beliefs. It stores observable proposals,
    explicit scout promotions, grounded evidence records, and auditable budget ledgers.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.paths = {
            "observables": self.root / "phase61_observables.json",
            "promotions": self.root / "phase61_evidence_promotions.json",
            "evidence": self.root / "phase61_grounded_evidence.json",
            "budgets": self.root / "phase61_budget_ledgers.json",
            "budget_events": self.root / "phase61_budget_events.json",
        }

    @staticmethod
    def _read(path: Path) -> list[dict[str, Any]]:
        return read_json_array(path, RegistryCorruptionError)

    def _upsert(self, bucket: str, id_field: str, item: Any) -> dict[str, Any]:
        row = asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item)
        with json_array_transaction(self.paths[bucket], RegistryCorruptionError) as rows:
            ident = str(row.get(id_field) or "")
            replaced = False
            for idx, prior in enumerate(rows):
                if str(prior.get(id_field) or "") == ident:
                    if bucket == "observables" and str(prior.get("status") or "") in {"SELECTED", "SUPERSEDED"}:
                        # Regenerating deterministic candidates may refresh design scores, but it
                        # must never erase an explicit human selection lifecycle.
                        for field in (
                            "status", "selected_at", "selection_actor", "selection_reason",
                            "evidence_refs", "superseded_at",
                        ):
                            if prior.get(field) not in (None, "", [], ()):
                                row[field] = prior.get(field)
                    if bucket == "evidence":
                        history = list(prior.get("extraction_history") or [])
                        history.append({
                            "at": _now_iso(),
                            "prior": {key: value for key, value in prior.items() if key != "extraction_history"},
                        })
                        row["extraction_history"] = history
                    rows[idx] = row
                    replaced = True
                    break
            if not replaced:
                rows.append(row)
        return row

    def save_observable(self, item: Any) -> dict[str, Any]:
        return self._upsert("observables", "observable_id", item)

    def list_observables(self) -> list[dict[str, Any]]:
        return self._read(self.paths["observables"])

    def select_observable(
        self,
        observable_id: str,
        reason: str,
        evidence_refs: Iterable[str] = (),
        actor: str = "HUMAN",
    ) -> dict[str, Any]:
        reason = str(reason or "").strip()
        if not reason:
            raise ValueError("Selecting an observable requires an explicit rationale.")
        with json_array_transaction(self.paths["observables"], RegistryCorruptionError) as rows:
            target = next((x for x in rows if str(x.get("observable_id") or "") == str(observable_id)), None)
            if target is None:
                raise KeyError(f"Unknown observable_id: {observable_id}")
            qid = str(target.get("question_id") or "")
            at = _now_iso()
            for row in rows:
                if str(row.get("question_id") or "") == qid and str(row.get("observable_id") or "") != str(observable_id):
                    if str(row.get("status") or "PROPOSED") == "SELECTED":
                        row["status"] = "SUPERSEDED"
                        row["superseded_at"] = at
            target["status"] = "SELECTED"
            target["selected_at"] = at
            target["selection_actor"] = str(actor or "HUMAN")
            target["selection_reason"] = reason
            target["evidence_refs"] = _clean_refs(evidence_refs)
        return dict(target)

    def save_promotion(self, item: Any) -> dict[str, Any]:
        return self._upsert("promotions", "promotion_id", item)

    def list_promotions(self) -> list[dict[str, Any]]:
        return self._read(self.paths["promotions"])

    def update_promotion(self, promotion_id: str, **fields: Any) -> dict[str, Any]:
        with json_array_transaction(self.paths["promotions"], RegistryCorruptionError) as rows:
            target = next((x for x in rows if str(x.get("promotion_id") or "") == str(promotion_id)), None)
            if target is None:
                raise KeyError(f"Unknown promotion_id: {promotion_id}")
            for key, value in fields.items():
                target[key] = value
            target["updated_at"] = _now_iso()
        return dict(target)

    def save_evidence(self, item: Any) -> dict[str, Any]:
        return self._upsert("evidence", "evidence_id", item)

    def list_evidence(self) -> list[dict[str, Any]]:
        return self._read(self.paths["evidence"])

    def supersede_evidence(self, evidence_id: str, replacement_evidence_id: str, reason: str) -> dict[str, Any]:
        with json_array_transaction(self.paths["evidence"], RegistryCorruptionError) as rows:
            target = next((x for x in rows if str(x.get("evidence_id") or "") == str(evidence_id)), None)
            if target is None:
                raise KeyError(f"Unknown evidence_id: {evidence_id}")
            target["status"] = "SUPERSEDED_EMPTY_EXTRACTION"
            target["superseded_at"] = _now_iso()
            target["superseded_by"] = str(replacement_evidence_id or "")
            target["superseded_reason"] = str(reason or "").strip()
        return dict(target)

    def save_budget(self, item: Any) -> dict[str, Any]:
        return self._upsert("budgets", "ledger_id", item)

    def list_budgets(self) -> list[dict[str, Any]]:
        return self._read(self.paths["budgets"])

    def list_budget_events(self) -> list[dict[str, Any]]:
        return self._read(self.paths["budget_events"])

    def ledger_for_plan(self, plan_id: str) -> dict[str, Any] | None:
        return next((x for x in self.list_budgets() if str(x.get("plan_id") or "") == str(plan_id)), None)

    def reconcile_budget(
        self,
        plan: Mapping[str, Any],
        hypotheses: Iterable[Mapping[str, Any]] = (),
        scouts: Iterable[Mapping[str, Any]] = (),
        cycles: Iterable[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        """Idempotently infer minimum consumed budget from persisted Phase-6 state.

        Reconciliation never guesses token/compute use. Compute units are the sum of explicit
        scout `budget_units_used` records only; planning itself remains uncharged unless a future
        executor records a budget event.
        """
        plan_id = str(plan.get("plan_id") or "")
        qid = str(plan.get("question_id") or "")
        related_scouts = [x for x in scouts if str(x.get("question_id") or "") == qid]
        related_hyp = [x for x in hypotheses if str(x.get("question_id") or "") == qid]
        related_cycles = [x for x in cycles if str(x.get("plan_id") or "") == plan_id]
        tasks = list(plan.get("tasks") or [])
        inferred_queries = len({str(x.get("task_id") or "") for x in related_scouts if str(x.get("task_id") or "")})
        inferred_compute = sum(float(x.get("budget_units_used") or 0.0) for x in related_scouts)
        inferred_hyp = len(related_hyp)
        inferred_tasks = len(tasks)
        inferred_cycles = len(related_cycles)

        with json_array_transaction(self.paths["budgets"], RegistryCorruptionError) as rows:
            existing = next((x for x in rows if str(x.get("plan_id") or "") == plan_id), None)
            if existing:
                existing["used_literature_queries"] = max(int(existing.get("used_literature_queries") or 0), inferred_queries)
                existing["used_hypotheses"] = max(int(existing.get("used_hypotheses") or 0), inferred_hyp)
                existing["used_tasks"] = max(int(existing.get("used_tasks") or 0), inferred_tasks)
                existing["used_cycles"] = max(int(existing.get("used_cycles") or 0), inferred_cycles)
                existing["used_compute_units"] = max(float(existing.get("used_compute_units") or 0.0), inferred_compute)
                existing["reconciled_from_persisted_state"] = True
                result = dict(existing)
            else:
                ledger = build_budget_ledger(
                    plan,
                    used_literature_queries=inferred_queries,
                    used_hypotheses=inferred_hyp,
                    used_tasks=inferred_tasks,
                    used_cycles=inferred_cycles,
                    used_compute_units=inferred_compute,
                    reconciled=True,
                )
                result = asdict(ledger) if hasattr(ledger, "__dataclass_fields__") else dict(ledger)
                ledger_id = str(result.get("ledger_id") or "")
                replaced = False
                for idx, prior in enumerate(rows):
                    if str(prior.get("ledger_id") or "") == ledger_id:
                        rows[idx] = result
                        replaced = True
                        break
                if not replaced:
                    rows.append(result)
        return result

    @staticmethod
    def budget_remaining(ledger: Mapping[str, Any]) -> dict[str, float]:
        return {
            "literature_queries": max(0.0, float(ledger.get("max_literature_queries") or 0) - float(ledger.get("used_literature_queries") or 0)),
            "hypotheses": max(0.0, float(ledger.get("max_hypotheses") or 0) - float(ledger.get("used_hypotheses") or 0)),
            "tasks": max(0.0, float(ledger.get("max_tasks") or 0) - float(ledger.get("used_tasks") or 0)),
            "experiment_proposals": max(0.0, float(ledger.get("max_experiment_proposals") or 0) - float(ledger.get("used_experiment_proposals") or 0)),
            "cycles": max(0.0, float(ledger.get("max_cycles") or 0) - float(ledger.get("used_cycles") or 0)),
            "compute_units": max(0.0, float(ledger.get("max_compute_units") or 0.0) - float(ledger.get("used_compute_units") or 0.0)),
        }

    def consume_budget(
        self,
        plan_id: str,
        category: str,
        amount: float,
        reason: str,
        ref_id: str,
        actor: str = "SYSTEM",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        category = str(category or "").strip().upper()
        amount = float(amount)
        if amount <= 0:
            raise ValueError("Budget consumption amount must be positive.")
        with json_array_transaction(self.paths["budgets"], RegistryCorruptionError) as rows:
            ledger = next((x for x in rows if str(x.get("plan_id") or "") == str(plan_id)), None)
            if ledger is None:
                raise KeyError(f"No budget ledger for plan {plan_id}; reconcile the plan first.")
            mapping = {
                "LITERATURE_QUERY": ("used_literature_queries", "max_literature_queries"),
                "HYPOTHESIS": ("used_hypotheses", "max_hypotheses"),
                "TASK": ("used_tasks", "max_tasks"),
                "EXPERIMENT_PROPOSAL": ("used_experiment_proposals", "max_experiment_proposals"),
                "CYCLE": ("used_cycles", "max_cycles"),
                "COMPUTE": ("used_compute_units", "max_compute_units"),
            }
            if category not in mapping:
                raise ValueError(f"Unsupported budget category: {category}")
            used_field, max_field = mapping[category]
            used = float(ledger.get(used_field) or 0.0)
            maximum = float(ledger.get(max_field) or 0.0)
            if used + amount > maximum + 1e-12:
                raise ValueError(f"Budget exhausted for {category}: requested {amount}, remaining {max(0.0, maximum - used):.2f}.")
            ledger[used_field] = used + amount
            result = dict(ledger)
        at = _now_iso()
        event = BudgetEvent(
            event_id=_stable_event_id(str(result.get("ledger_id") or ""), category, str(ref_id or ""), amount, at),
            created_at=at,
            ledger_id=str(result.get("ledger_id") or ""),
            plan_id=str(plan_id),
            category=category,
            amount=amount,
            reason=str(reason or ""),
            ref_id=str(ref_id or ""),
            actor=str(actor or "SYSTEM"),
            metadata=dict(metadata or {}),
        )
        self._upsert("budget_events", "event_id", event)
        return result

    def summary(self) -> dict[str, int]:
        observables = self.list_observables()
        promotions = self.list_promotions()
        evidence = self.list_evidence()
        active_grounded = [
            row for row in evidence
            if str(row.get("status") or "") == "GROUNDED_REVIEWED"
            and bool((row.get("claim_ids") or []) or (row.get("mechanism_keys") or []) or (row.get("semantic_entity_ids") or []))
        ]
        return {
            "observable_candidates": len(observables),
            "selected_observables": sum(1 for x in observables if str(x.get("status") or "") == "SELECTED"),
            "promotions": len(promotions),
            "grounded_evidence": len(active_grounded),
            "evidence_records": len(evidence),
            "incomplete_evidence": len(evidence) - len(active_grounded),
            "budget_ledgers": len(self.list_budgets()),
            "budget_events": len(self.list_budget_events()),
        }
