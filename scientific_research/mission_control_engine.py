from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .phase63_models import MissionSnapshot, RegistryFileHealth, ResearchGate
from .registry_io import registry_lock
from .replication_engine import REPLICATION_EVENT_TIME_SUPPORT_POLICY
from .direct_bis_reconciliation import (
    DIRECT_BIS_HISTORY_SEMANTICS,
    DIRECT_BIS_PROTOCOL_VERSION,
    build_prospective_vintage_summary,
    validate_completed_direct_bis_reconciliation,
)
from .cross_provider_triangulation import (
    CROSS_PROVIDER_PROTOCOL_VERSION,
    OECD_HISTORY_SEMANTICS,
)
from .prospective_observation import (
    PROSPECTIVE_OBSERVATION_PROTOCOL_VERSION,
    evaluate_prospective_observation_program,
    validate_prospective_observation_program,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(part or "").strip().lower() for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _exact_int(value: Any, *, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _utc_instant(value: Any) -> datetime:
    parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed.astimezone(timezone.utc)


def _observation_order(row: Mapping[str, Any]) -> tuple[datetime, str]:
    try:
        instant = _utc_instant(row.get("retrieved_at"))
    except (TypeError, ValueError):
        instant = datetime.min.replace(tzinfo=timezone.utc)
    return instant, _text(row.get("reconciliation_id"))


def _as_rows(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (value or ()) if isinstance(row, Mapping)]


def inspect_registry_file(registry: str, path: Path, *, jsonl: bool = False) -> RegistryFileHealth:
    if not path.exists():
        return RegistryFileHealth(registry, str(path), "MISSING", 0, "No records have been persisted yet.")
    try:
        if jsonl:
            rows = []
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise ValueError(f"line {line_number} is not an object")
                rows.append(value)
        else:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
                raise ValueError("top level must be an array of objects")
            rows = value
        return RegistryFileHealth(registry, str(path), "OK", len(rows), "")
    except Exception as exc:
        return RegistryFileHealth(registry, str(path), "INVALID", 0, f"{type(exc).__name__}: {str(exc)[:240]}")


def _safe_capture(
    key: str,
    loader: Callable[[], Any],
    path: Path,
    health: list[RegistryFileHealth],
    *,
    jsonl: bool = False,
) -> list[dict[str, Any]]:
    state = inspect_registry_file(key, path, jsonl=jsonl)
    health.append(state)
    if state.status == "INVALID":
        return []
    try:
        return _as_rows(loader())
    except Exception as exc:
        health[-1] = RegistryFileHealth(key, str(path), "INVALID", 0, f"{type(exc).__name__}: {str(exc)[:240]}")
        return []


def _audit_tail_unlocked(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines()[-max(1, int(limit)):]:
        if line.strip():
            rows.append(dict(json.loads(line)))
    return rows


def capture_registry_snapshot(memory: Any, audit_limit: int = 250) -> dict[str, Any]:
    """Capture every registry once under the shared state-root transaction lock."""
    health: list[RegistryFileHealth] = []
    snapshot: dict[str, Any] = {}
    specs = (
        ("papers", memory.list_papers, memory.paths["papers"]),
        ("compilations", memory.list_compilations, memory.paths["compilations"]),
        ("quests", memory.list_quests, memory.paths["quests"]),
        ("understanding", memory.list_understanding, memory.paths["understanding"]),
        ("provenance", memory.list_provenance, memory.paths["provenance"]),
        ("transfer_candidates", memory.phase3.list_candidates, memory.phase3.paths["candidates"]),
        ("transfer_audits", memory.phase3.list_audits, memory.phase3.paths["audits"]),
        ("experiment_specs", memory.phase4.list_specifications, memory.phase4.paths["specifications"]),
        ("runs", memory.phase4.list_runs, memory.phase4.paths["runs"]),
        ("replications", memory.phase4.list_replications, memory.phase4.paths["replications"]),
        ("reviews", memory.phase5.list_reviews, memory.phase5.paths["reviews"]),
        ("failures", memory.phase5.list_failures, memory.phase5.paths["failures"]),
        ("surprises", memory.phase5.list_surprises, memory.phase5.paths["surprises"]),
        ("theory_populations", memory.phase5.list_theory_populations, memory.phase5.paths["theories"]),
        ("questions", memory.phase6.list_questions, memory.phase6.paths["questions"]),
        ("hypotheses", memory.phase6.list_hypotheses, memory.phase6.paths["hypotheses"]),
        ("plans", memory.phase6.list_plans, memory.phase6.paths["plans"]),
        ("cycles", memory.phase6.list_cycles, memory.phase6.paths["cycles"]),
        ("diary", memory.phase6.list_diary, memory.phase6.paths["diary"]),
        ("scouts", memory.phase6.list_scouts, memory.phase6.paths["scouts"]),
        ("observables", memory.phase61.list_observables, memory.phase61.paths["observables"]),
        ("promotions", memory.phase61.list_promotions, memory.phase61.paths["promotions"]),
        ("evidence", memory.phase61.list_evidence, memory.phase61.paths["evidence"]),
        ("budgets", memory.phase61.list_budgets, memory.phase61.paths["budgets"]),
        ("budget_events", memory.phase61.list_budget_events, memory.phase61.paths["budget_events"]),
        ("measurement_models", memory.phase62.list_measurement_models, memory.phase62.paths["measurement_models"]),
        ("measurement_hypotheses", memory.phase62.list_measurement_hypotheses, memory.phase62.paths["measurement_hypotheses"]),
        ("measurement_decisions", memory.phase62.list_measurement_decisions, memory.phase62.paths["measurement_decisions"]),
        ("evidence_assessments", memory.phase62.list_evidence_assessments, memory.phase62.paths["evidence_assessments"]),
        ("evidence_syntheses", memory.phase62.list_evidence_syntheses, memory.phase62.paths["evidence_syntheses"]),
        ("data_contracts", memory.phase63.list_contracts, memory.phase63.paths["contracts"]),
        ("contract_audits", memory.phase63.list_contract_audits, memory.phase63.paths["contract_audits"]),
        ("dataset_manifests", memory.phase63.list_manifests, memory.phase63.paths["manifests"]),
        ("attempts", memory.phase63.list_attempts, memory.phase63.paths["attempts"]),
        ("break_diagnostics", memory.phase63.list_diagnostics, memory.phase63.paths["diagnostics"]),
        ("capsules", memory.phase63.list_capsules, memory.phase63.paths["capsules"]),
        ("measurement_protocols", memory.phase63.list_measurement_protocols, memory.phase63.paths["measurement_protocols"]),
        ("measurement_reports", memory.phase63.list_measurement_reports, memory.phase63.paths["measurement_reports"]),
        ("cross_runtime_verifications", memory.phase65.list_verifications, memory.phase65.paths["verifications"]),
        ("direct_source_reconciliations", memory.phase66.list_reconciliations, memory.phase66.paths["reconciliations"]),
        ("cross_provider_triangulations", memory.phase67.list_triangulations, memory.phase67.paths["triangulations"]),
        ("prospective_observation_programs", memory.phase68.list_programs, memory.phase68.paths["programs"]),
    )
    # Every mutable registry uses the same root-level lock. Holding it for the
    # complete read prevents Mission Control from mixing pre- and post-write
    # states across files. The audit reader is deliberately lock-free here to
    # avoid recursively acquiring the same OS lock.
    with registry_lock(Path(memory.paths["papers"])):
        for key, loader, path in specs:
            snapshot[key] = _safe_capture(key, loader, Path(path), health)
        snapshot["audit"] = _safe_capture(
            "audit",
            lambda: _audit_tail_unlocked(Path(memory.paths["audit"]), audit_limit),
            memory.paths["audit"],
            health,
            jsonl=True,
        )
    snapshot["registry_health"] = [asdict(item) for item in health]
    snapshot["captured_at"] = _now_iso()
    return snapshot


def _find(rows: Iterable[Mapping[str, Any]], field: str, identity: str) -> dict[str, Any]:
    return next((dict(row) for row in rows if _text(row.get(field)) == _text(identity)), {})


def build_mission_lineage_index(snapshot: Mapping[str, Any], question_id: str) -> dict[str, set[str]]:
    """Resolve only explicit or identity-linked descendants of one question.

    The index intentionally has no global "first experiment" fallback. A row with no
    question_id is visible only when one of its governed foreign keys already belongs
    to this mission's lineage.
    """
    qid = _text(question_id)
    question = _find(snapshot.get("questions") or (), "question_id", qid)
    index: dict[str, set[str]] = {
        "question_id": {qid} if qid else set(),
        "plan_id": set(),
        "hypothesis_id": set(),
        "observable_id": set(),
        "evidence_id": set(),
        "contract_id": set(),
        "manifest_id": set(),
        "experiment_id": set(),
        "attempt_id": set(),
        "run_id": set(),
        "review_id": set(),
        "capsule_id": set(),
        "diagnostic_id": set(),
        "replication_id": set(),
        "verification_id": set(),
        "reconciliation_id": set(),
        "triangulation_id": set(),
        "program_id": set(),
    }

    def add(field: str, value: Any) -> None:
        identity = _text(value)
        if identity:
            index[field].add(identity)

    add("plan_id", question.get("plan_id"))
    add("observable_id", question.get("selected_observable_id"))
    add("experiment_id", question.get("experiment_id"))
    for registry, identity_field in (
        ("plans", "plan_id"),
        ("hypotheses", "hypothesis_id"),
        ("observables", "observable_id"),
        ("evidence", "evidence_id"),
        ("data_contracts", "contract_id"),
    ):
        for row in snapshot.get(registry) or ():
            if isinstance(row, Mapping) and _text(row.get("question_id")) == qid:
                add(identity_field, row.get(identity_field))
                add("experiment_id", row.get("experiment_id"))
                add("observable_id", row.get("observable_id"))
                add("plan_id", row.get("plan_id"))
    for registry in ("measurement_protocols", "measurement_reports"):
        for row in snapshot.get(registry) or ():
            if isinstance(row, Mapping) and _text(row.get("question_id")) == qid:
                add("experiment_id", row.get("experiment_id"))

    for row in snapshot.get("dataset_manifests") or ():
        if isinstance(row, Mapping) and _text(row.get("contract_id")) in index["contract_id"]:
            add("manifest_id", row.get("manifest_id"))
    for row in snapshot.get("attempts") or ():
        if isinstance(row, Mapping) and _text(row.get("experiment_id")) in index["experiment_id"]:
            add("attempt_id", row.get("attempt_id"))
    for row in snapshot.get("runs") or ():
        if not isinstance(row, Mapping):
            continue
        row_question = _text(row.get("question_id"))
        row_experiment = _text(row.get("experiment_id"))
        linked = (
            row_question == qid
            and (not row_experiment or row_experiment in index["experiment_id"])
            if row_question
            else row_experiment in index["experiment_id"]
        )
        if linked:
            add("run_id", row.get("run_id"))
            add("attempt_id", row.get("attempt_id"))
            add("manifest_id", row.get("dataset_manifest_id"))
    for registry, identity_field in (
        ("reviews", "review_id"),
        ("capsules", "capsule_id"),
        ("break_diagnostics", "diagnostic_id"),
        ("failures", "failure_id"),
        ("surprises", "surprise_id"),
    ):
        for row in snapshot.get(registry) or ():
            if isinstance(row, Mapping) and _text(row.get("run_id")) in index["run_id"]:
                if identity_field in index:
                    add(identity_field, row.get(identity_field))
    for row in snapshot.get("replications") or ():
        if not isinstance(row, Mapping):
            continue
        row_question = _text(row.get("question_id"))
        row_experiment = _text(row.get("experiment_id"))
        reference_run = _text(row.get("reference_run_id"))
        foreign_link = (
            (not row_experiment or row_experiment in index["experiment_id"])
            and (not reference_run or reference_run in index["run_id"])
            and bool(row_experiment or reference_run)
        )
        if foreign_link and (not row_question or row_question == qid):
            add("replication_id", row.get("replication_id"))
    for row in snapshot.get("cross_runtime_verifications") or ():
        if isinstance(row, Mapping) and _text(row.get("replication_id")) in index["replication_id"]:
            add("verification_id", row.get("verification_id"))
    for row in snapshot.get("direct_source_reconciliations") or ():
        if isinstance(row, Mapping) and _text(row.get("replication_id")) in index["replication_id"]:
            add("reconciliation_id", row.get("reconciliation_id"))
    direct_replication = {
        _text(row.get("reconciliation_id")): _text(row.get("replication_id"))
        for row in (snapshot.get("direct_source_reconciliations") or ())
        if isinstance(row, Mapping) and _text(row.get("reconciliation_id"))
    }
    for row in snapshot.get("cross_provider_triangulations") or ():
        if not isinstance(row, Mapping):
            continue
        replication_id = _text(row.get("replication_id"))
        reconciliation_id = _text(row.get("direct_reconciliation_id"))
        linked = (
            (not replication_id or replication_id in index["replication_id"])
            and (not reconciliation_id or reconciliation_id in index["reconciliation_id"])
            and (not reconciliation_id or direct_replication.get(reconciliation_id) == replication_id)
            and bool(replication_id or reconciliation_id)
        )
        if linked:
            add("triangulation_id", row.get("triangulation_id"))
    for row in snapshot.get("prospective_observation_programs") or ():
        if not isinstance(row, Mapping):
            continue
        replication_id = _text(row.get("replication_id"))
        reconciliation_id = _text(row.get("seed_reconciliation_id"))
        linked = (
            (not replication_id or replication_id in index["replication_id"])
            and (not reconciliation_id or reconciliation_id in index["reconciliation_id"])
            and (not reconciliation_id or direct_replication.get(reconciliation_id) == replication_id)
            and bool(replication_id or reconciliation_id)
        )
        if linked:
            add("program_id", row.get("program_id"))
    return index


def _gate(
    gate_id: str,
    label: str,
    status: str,
    summary: str,
    refs: Iterable[str] = (),
    blockers: Iterable[str] = (),
    next_action: str = "",
) -> ResearchGate:
    return ResearchGate(
        gate_id=gate_id,
        label=label,
        status=status,
        summary=summary,
        artifact_refs=tuple(dict.fromkeys(_text(ref) for ref in refs if _text(ref))),
        blockers=tuple(dict.fromkeys(_text(item) for item in blockers if _text(item))),
        next_action=_text(next_action),
    )


def _active_question(snapshot: Mapping[str, Any], question_id: str = "") -> dict[str, Any]:
    questions = _as_rows(snapshot.get("questions"))
    if question_id:
        return _find(questions, "question_id", question_id)
    active = [row for row in questions if _text(row.get("status")).upper() not in {"ANSWERED", "STOPPED"}]
    return max(active or questions, key=lambda row: (float(row.get("priority_score") or 0.0), _text(row.get("created_at"))), default={})


def build_mission_snapshot(snapshot: Mapping[str, Any], question_id: str = "") -> MissionSnapshot:
    question = _active_question(snapshot, question_id)
    qid = _text(question.get("question_id"))
    lineage = build_mission_lineage_index(snapshot, qid)
    plan = _find(snapshot.get("plans") or (), "plan_id", _text(question.get("plan_id")))
    if not plan:
        plan = next((dict(row) for row in (snapshot.get("plans") or ()) if _text(row.get("question_id")) == qid), {})
    experiment_id = _text(question.get("experiment_id"))
    if not experiment_id and len(lineage["experiment_id"]) == 1:
        experiment_id = next(iter(lineage["experiment_id"]))
    specs = [dict(row) for row in (snapshot.get("experiment_specs") or ()) if _text(row.get("experiment_id")) == experiment_id]
    ready_spec = next((row for row in specs if _text(row.get("status")) == "READY"), specs[-1] if specs else {})
    hypotheses = [dict(row) for row in (snapshot.get("hypotheses") or ()) if _text(row.get("question_id")) == qid]
    leading = _find(hypotheses, "hypothesis_id", _text(plan.get("selected_hypothesis_id")))
    if not leading and hypotheses:
        leading = max(hypotheses, key=lambda row: float(row.get("priority_score") or 0.0))
    null_hypothesis = next((row for row in hypotheses if "no stable" in f"{row.get('label', '')} {row.get('description', '')}".lower() or "null" in _text(row.get("label")).lower()), {})

    models = [dict(row) for row in (snapshot.get("measurement_models") or ()) if _text(row.get("question_id")) == qid]
    model = models[-1] if models else {}
    decisions = [dict(row) for row in (snapshot.get("measurement_decisions") or ()) if _text(row.get("question_id")) == qid]
    decision = max(decisions, key=lambda row: _text(row.get("created_at")), default={})
    decision_observable_id = _text(decision.get("selected_observable_id"))
    primary_id = decision_observable_id or _text(model.get("primary_observable_id")) or _text(question.get("selected_observable_id"))
    observables = [dict(row) for row in (snapshot.get("observables") or ()) if _text(row.get("question_id")) == qid]
    primary_observable = _find(observables, "observable_id", primary_id)

    evidence_rows = [dict(row) for row in (snapshot.get("evidence") or ()) if _text(row.get("question_id")) == qid]
    active_evidence = [
        row for row in evidence_rows
        if _text(row.get("status")) == "GROUNDED_REVIEWED"
        and bool((row.get("claim_ids") or ()) or (row.get("mechanism_keys") or ()) or (row.get("semantic_entity_ids") or ()))
    ]
    empty_reviewed = [
        row for row in evidence_rows
        if _text(row.get("status")) == "GROUNDED_REVIEWED"
        and not ((row.get("claim_ids") or ()) or (row.get("mechanism_keys") or ()) or (row.get("semantic_entity_ids") or ()))
    ]
    active_evidence_ids = {_text(row.get("evidence_id")) for row in active_evidence}
    assessments = [
        dict(row) for row in (snapshot.get("evidence_assessments") or ())
        if _text(row.get("question_id")) == qid and _text(row.get("evidence_id")) in active_evidence_ids
    ]
    syntheses = [dict(row) for row in (snapshot.get("evidence_syntheses") or ()) if _text(row.get("question_id")) == qid]

    contracts = [
        dict(row) for row in (snapshot.get("data_contracts") or ())
        if _text(row.get("question_id")) == qid and (not primary_id or _text(row.get("observable_id")) == primary_id)
    ]
    contract = max(contracts, key=lambda row: _text(row.get("created_at")), default={})
    contract_audits = [dict(row) for row in (snapshot.get("contract_audits") or ()) if _text(row.get("contract_id")) == _text(contract.get("contract_id"))]
    contract_audit = max(contract_audits, key=lambda row: _text(row.get("created_at")), default={})
    manifests = [dict(row) for row in (snapshot.get("dataset_manifests") or ()) if _text(row.get("contract_id")) == _text(contract.get("contract_id"))]
    manifest = max(manifests, key=lambda row: _text(row.get("created_at")), default={})
    attempts = [
        dict(row) for row in (snapshot.get("attempts") or ())
        if _text(row.get("attempt_id")) in lineage["attempt_id"]
    ]
    runs = [
        dict(row) for row in (snapshot.get("runs") or ())
        if (
            (
                _text(row.get("question_id")) == qid
                and (not _text(row.get("experiment_id")) or _text(row.get("experiment_id")) == experiment_id)
            )
            if _text(row.get("question_id"))
            else _text(row.get("experiment_id")) == experiment_id
        )
    ]
    historical_runs = [row for row in runs if _text(row.get("stage")) == "HISTORICAL_OOS"]
    attributed_historical = [
        row for row in historical_runs
        if _text(row.get("observable_id")) == primary_id
        and (not manifest or _text(row.get("dataset_manifest_id")) == _text(manifest.get("manifest_id")))
    ]
    latest_historical = max(attributed_historical, key=lambda row: _text(row.get("created_at")), default={})
    reviews = [dict(row) for row in (snapshot.get("reviews") or ()) if _text(row.get("run_id")) == _text(latest_historical.get("run_id"))]
    replications = [
        dict(row) for row in (snapshot.get("replications") or ())
        if (not _text(row.get("question_id")) or _text(row.get("question_id")) == qid)
        and (
            _text(row.get("experiment_id")) == experiment_id
            or _text(row.get("reference_run_id")) in lineage["run_id"]
        )
    ]
    capsules = [dict(row) for row in (snapshot.get("capsules") or ()) if _text(row.get("run_id")) == _text(latest_historical.get("run_id"))]
    measurement_protocols = [
        dict(row) for row in (snapshot.get("measurement_protocols") or ())
        if _text(row.get("question_id")) == qid and _text(row.get("experiment_id")) == experiment_id
    ]
    measurement_reports = [
        dict(row) for row in (snapshot.get("measurement_reports") or ())
        if _text(row.get("question_id")) == qid and _text(row.get("experiment_id")) == experiment_id
    ]

    inconsistencies: list[str] = []
    if not experiment_id and len(lineage["experiment_id"]) > 1:
        inconsistencies.append(
            "Mission lineage is ambiguous: more than one explicitly linked experiment exists and the question selects none."
        )
    invalid_health = [row for row in (snapshot.get("registry_health") or ()) if _text(row.get("status")) == "INVALID"]
    if invalid_health:
        inconsistencies.extend(f"Registry {row.get('registry')} is invalid: {row.get('detail')}" for row in invalid_health)
    primary_views = {
        "question": _text(question.get("selected_observable_id")),
        "measurement_model": _text(model.get("primary_observable_id")),
        "measurement_decision": decision_observable_id,
    }
    nonempty_primary = {value for value in primary_views.values() if value}
    if len(nonempty_primary) > 1:
        inconsistencies.append(f"Primary observable conflicts across registries: {primary_views}.")
    if primary_id and _text(primary_observable.get("status")) != "SELECTED":
        inconsistencies.append(f"Primary observable {primary_id} is {_text(primary_observable.get('status')) or 'MISSING'} in Phase 6.1 instead of SELECTED.")
    if empty_reviewed:
        inconsistencies.extend(f"Evidence {_text(row.get('evidence_id'))} is labelled GROUNDED_REVIEWED but contains no claims, mechanisms or entities." for row in empty_reviewed)
    for row in list(snapshot.get("failures") or ()) + list(snapshot.get("surprises") or ()):
        if _text(row.get("run_id")) not in lineage["run_id"]:
            continue
        history = list(row.get("lifecycle_history") or ())
        if history and _text(history[-1].get("to")) != _text(row.get("status")):
            identity = _text(row.get("failure_id")) or _text(row.get("surprise_id"))
            inconsistencies.append(f"Lifecycle history for {identity} ends at {_text(history[-1].get('to'))}, but current status is {_text(row.get('status'))}.")
    for ref in decision.get("evidence_refs") or ():
        if _text(ref).startswith('"') or _text(ref).endswith('"'):
            inconsistencies.append(f"Measurement decision contains a non-canonical quoted reference: {ref}")
    for run in runs:
        if _text(run.get("stage")) == "HISTORICAL_OOS" and not run.get("forecast_timestamps"):
            inconsistencies.append(f"Historical run {_text(run.get('run_id'))} has no timestamped forecast trace.")

    gates: list[ResearchGate] = []
    gates.append(_gate(
        "REGISTRY_INTEGRITY", "Registry integrity", "BLOCKED" if invalid_health else "SATISFIED",
        "Malformed registry detected; mutations are blocked." if invalid_health else "All existing registries are parseable.",
        blockers=[row.get("registry") for row in invalid_health],
        next_action="Restore or repair the malformed registry from backup before any write." if invalid_health else "",
    ))
    transfer_ok = bool(ready_spec) and _text(ready_spec.get("transfer_verdict")) == "PARTIAL_TRANSFER"
    gates.append(_gate(
        "PARTIAL_TRANSFER_ELIGIBLE", "Transfer eligibility", "SATISFIED" if transfer_ok else "BLOCKED",
        "PARTIAL_TRANSFER with a READY built-in specification." if transfer_ok else "No READY PARTIAL_TRANSFER specification is linked.",
        refs=(_text(ready_spec.get("experiment_id")), _text(ready_spec.get("transfer_audit_id"))),
        next_action="Complete the guarded transfer audit and specification." if not transfer_ok else "",
    ))
    evidence_status = "SATISFIED" if active_evidence else "BLOCKED" if empty_reviewed else "NOT_EVALUATED"
    gates.append(_gate(
        "SOURCE_GROUNDED_EVIDENCE", "Source-grounded evidence", evidence_status,
        f"{len(active_evidence)} active non-empty evidence record(s)." if active_evidence else "A reviewed evidence record is empty." if empty_reviewed else "No active source-grounded evidence record.",
        refs=[row.get("evidence_id") for row in active_evidence or empty_reviewed],
        blockers=("Empty extraction cannot satisfy the evidence gate.",) if empty_reviewed else (),
        next_action="Recompile the verified source text and inspect exact provenance before assessment." if not active_evidence else "",
    ))
    decision_ok = bool(decision) and bool(primary_id)
    gates.append(_gate(
        "MEASUREMENT_DECISION_RECORDED", "Measurement decision", "SATISFIED" if decision_ok else "NOT_EVALUATED",
        _text(primary_observable.get("label")) or "No primary measurement decision.",
        refs=(_text(decision.get("decision_id")), primary_id),
        next_action="Record one explicit primary measurement while retaining all competitors." if not decision_ok else "",
    ))
    measurement_consistent = decision_ok and len(nonempty_primary) == 1 and _text(primary_observable.get("status")) == "SELECTED"
    gates.append(_gate(
        "MEASUREMENT_STATE_CONSISTENT", "Measurement state consistency", "SATISFIED" if measurement_consistent else "CONFLICT" if decision_ok else "NOT_EVALUATED",
        "Question, model, decision and observable lifecycle agree." if measurement_consistent else "Primary selection is not aligned across registries.",
        refs=tuple(nonempty_primary),
        blockers=("Reconcile the explicit decision into the observable lifecycle without changing the chosen measurement.",) if decision_ok and not measurement_consistent else (),
        next_action="Apply an audited registry reconciliation for the existing MeasurementDecision." if decision_ok and not measurement_consistent else "",
    ))
    contract_ok = bool(contract) and _text(contract.get("status")) == "VALIDATED" and _text(contract_audit.get("overall_status")) in {"VALIDATED", "VALIDATED_WITH_WARNINGS"}
    gates.append(_gate(
        "DATA_CONTRACT_VALIDATED", "Historical data contract", "SATISFIED" if contract_ok else "NOT_EVALUATED",
        f"{_text(contract.get('market'))} · {_text(contract.get('anchor_family'))}" if contract else "No formal historical data contract.",
        refs=(_text(contract.get("contract_id")), _text(contract_audit.get("audit_id"))),
        blockers=contract.get("blockers") or (),
        next_action="Declare market, single anchor family, sources, release timestamps, revision policy and chronological split." if not contract_ok else "",
    ))
    point_status = _text(contract_audit.get("point_in_time_status"))
    gates.append(_gate(
        "POINT_IN_TIME_AUDITED", "Point-in-time audit",
        "SATISFIED" if point_status == "PASS" else "WARNING" if point_status == "WARNING" else "NOT_EVALUATED",
        "Point-in-time vintages/non-revision policy verified." if point_status == "PASS" else "Revision risk is explicit." if point_status == "WARNING" else "Point-in-time status has not been audited.",
        refs=(_text(contract_audit.get("audit_id")),),
        next_action="Provide availability/vintage fields or explicitly retain revision risk." if not point_status else "",
    ))
    manifest_ok = bool(manifest) and _text(manifest.get("status")).startswith("VALIDATED") and int(manifest.get("valid_row_count") or 0) >= 40
    manifest_point_in_time = (
        manifest_ok
        and _text(manifest.get("point_in_time_status")).upper() == "PASS"
        and _text(manifest.get("revision_risk_status")).upper()
        not in {"PRESENT", "REVISION_RISK_PRESENT"}
    )
    gates.append(_gate(
        "MATERIALIZED_DATA_FINGERPRINTED", "Causal dataset materialized", "SATISFIED" if manifest_ok else "NOT_EVALUATED",
        f"{manifest.get('valid_row_count')} rows · {str(manifest.get('materialized_fingerprint') or '')[:12]}" if manifest else "No fingerprinted materialized dataset.",
        refs=(_text(manifest.get("manifest_id")), _text(manifest.get("materialized_fingerprint"))),
        next_action="Upload contract-compliant rows and materialize the log residual causally." if not manifest_ok else "",
    ))
    executor_ok = bool(ready_spec) and _text(ready_spec.get("experimental_family")) == "OU_MEAN_REVERTING_SDE" and "NO_EVAL_NO_EXEC" in _text(ready_spec.get("code_policy"))
    gates.append(_gate(
        "BUILTIN_EXECUTOR_AUDITED", "Built-in executor", "SATISFIED" if executor_ok else "BLOCKED",
        _text(ready_spec.get("experimental_family")) or "No audited executor.",
        refs=(_text(ready_spec.get("experiment_id")),),
        next_action="Use an audited built-in family; arbitrary generated code remains forbidden." if not executor_ok else "",
    ))
    gates.append(_gate(
        "ATTEMPT_REGISTERED", "Attempt registered", "SATISFIED" if attempts else "NOT_EVALUATED",
        f"{len(attempts)} append-only attempt(s)." if attempts else "No Phase-6.3 attempt registered before execution.",
        refs=[row.get("attempt_id") for row in attempts],
        next_action="Register the predeclared attempt before running the historical executor." if not attempts else "",
    ))
    historical_status = (
        "SATISFIED"
        if latest_historical and manifest_point_in_time
        else "WARNING"
        if latest_historical
        else "NOT_EVALUATED"
    )
    historical_summary = (
        f"{_text(latest_historical.get('verdict'))} · run {_text(latest_historical.get('run_id'))}"
        if historical_status == "SATISFIED"
        else (
            "Historical OOS exists, but it is a revised diagnostic, not point-in-time; "
            f"run {_text(latest_historical.get('run_id'))}."
        )
        if historical_status == "WARNING"
        else "No contract-attributed real historical OOS run."
    )
    gates.append(_gate(
        "HISTORICAL_OOS_COMPLETE", "Standard OU historical OOS", historical_status,
        historical_summary,
        refs=(
            _text(latest_historical.get("run_id")),
            _text(manifest.get("manifest_id")),
        ),
        next_action=(
            "Acquire first-release or vintage-aware data and rerun the frozen historical OOS protocol."
            if historical_status == "WARNING"
            else "Run the standard OU baseline first on the validated materialized dataset."
            if historical_status == "NOT_EVALUATED"
            else ""
        ),
    ))
    trace_lengths = {
        len(latest_historical.get("forecast_timestamps") or ()),
        len(latest_historical.get("actual_values") or ()),
        len(latest_historical.get("candidate_errors") or ()),
    }
    trace_ok = bool(latest_historical) and len(trace_lengths) == 1 and next(iter(trace_lengths), 0) > 0 and bool(latest_historical.get("forecast_trace_fingerprint"))
    gates.append(_gate(
        "FORECAST_TRACE_AVAILABLE", "Timestamped forecast trace", "SATISFIED" if trace_ok else "NOT_EVALUATED",
        f"{len(latest_historical.get('forecast_timestamps') or ())} aligned errors." if trace_ok else "Formal forecast comparison is unavailable without aligned timestamps and errors.",
        refs=(_text(latest_historical.get("forecast_trace_fingerprint")),),
        next_action="Persist forecast origins, target timestamps, predictions and errors." if not trace_ok else "",
    ))
    selection_context = latest_historical.get("selection_context") or {}
    selection_ok = bool(selection_context) and int(selection_context.get("total_attempts") or 0) >= 1
    gates.append(_gate(
        "SELECTION_PRESSURE_RECORDED", "Selection pressure", "SATISFIED" if selection_ok else "NOT_EVALUATED",
        (
            f"{int(selection_context.get('total_attempts') or 0)} attempt(s) · "
            f"{int(selection_context.get('observed_screens') or 0)} observed screen(s) · "
            f"{_text(selection_context.get('selection_risk')) or 'UNKNOWN'} risk."
        ) if selection_ok else "No attempt-complete multiplicity snapshot is attached to the historical run.",
        refs=(_text(selection_context.get("snapshot_id")),),
        next_action="Count every attempt, baseline and robustness screen before interpreting OOS results." if not selection_ok else "",
    ))
    capsule_ok = bool(capsules) and any(
        _text(row.get("status")) == "COMPLETE" and _text(row.get("replay_grade")) in {"EXACT", "CONDITIONAL"}
        for row in capsules
    )
    gates.append(_gate(
        "REPRODUCIBILITY_CAPSULE", "Reproducibility capsule", "SATISFIED" if capsule_ok else "NOT_EVALUATED",
        (
            f"{len(capsules)} capsule(s) · latest replay grade {_text(capsules[-1].get('replay_grade'))}."
            if capsules else "No complete capsule links code, contract, data, attempt and forecast trace."
        ),
        refs=[row.get("capsule_id") for row in capsules],
        next_action="Persist an identity-aligned capsule with executor code and data fingerprints." if not capsule_ok else "",
    ))
    distinct_measurements = {_text(row.get("observable_id")) for row in historical_runs if _text(row.get("observable_id"))}
    latest_measurement_report = max(
        measurement_reports,
        key=lambda row: _text(row.get("created_at")),
        default={},
    )
    report_protocol = _find(
        measurement_protocols,
        "protocol_id",
        _text(latest_measurement_report.get("protocol_id")),
    )
    variant_results = _as_rows(latest_measurement_report.get("variant_results"))
    protocol_variants = _as_rows(report_protocol.get("variants"))
    result_variant_ids = {_text(row.get("variant_id")) for row in variant_results if _text(row.get("variant_id"))}
    protocol_variant_ids = {_text(row.get("variant_id")) for row in protocol_variants if _text(row.get("variant_id"))}
    measurement_report_ok = (
        bool(latest_measurement_report)
        and _text(latest_measurement_report.get("status")) == "COMPLETE"
        and _text(latest_measurement_report.get("gate_status")) == "PASS"
        and _text(latest_measurement_report.get("common_support_status")) == "PASS"
        and _text(latest_measurement_report.get("common_split_status")) == "PASS"
        and _text(latest_measurement_report.get("point_in_time_status")) == "PASS"
        and int(latest_measurement_report.get("variant_count") or 0) >= 3
        and len(result_variant_ids) >= 3
        and _text(report_protocol.get("status")) == "FROZEN"
        and len(protocol_variant_ids) >= 3
        and result_variant_ids == protocol_variant_ids
        and all(bool(row.get("counts_as_distinct_measurement")) for row in protocol_variants)
        and _text(latest_measurement_report.get("snapshot_id")) == _text(report_protocol.get("snapshot_id"))
        and _text(latest_measurement_report.get("snapshot_fingerprint")) == _text(report_protocol.get("snapshot_fingerprint"))
        and _text(latest_measurement_report.get("executor_code_digest")) == _text(report_protocol.get("executor_code_digest"))
        and _text(latest_measurement_report.get("production_status")) == "RESEARCH_ONLY"
        and _text(report_protocol.get("production_status")) == "RESEARCH_ONLY"
    )
    measurement_gate_status = (
        "SATISFIED"
        if measurement_report_ok
        else "WARNING"
        if latest_measurement_report or len(distinct_measurements) >= 2
        else "NOT_EVALUATED"
    )
    measurement_summary = (
        f"{len(result_variant_ids)} predeclared measurements · {_text(latest_measurement_report.get('conclusion'))}."
        if measurement_report_ok
        else (
            "A robustness artifact exists but does not satisfy every frozen support, split, vintage and lineage check."
            if latest_measurement_report
            else f"{len(distinct_measurements)} ordinary historical run measurement(s); no complete predeclared robustness report."
        )
    )
    gates.append(_gate(
        "MEASUREMENT_ROBUSTNESS", "Measurement dependence", measurement_gate_status,
        measurement_summary,
        refs=(
            _text(report_protocol.get("protocol_id")),
            _text(latest_measurement_report.get("report_id")),
            *sorted(result_variant_ids or distinct_measurements),
        ),
        blockers=(
            "A report cannot close this gate unless at least three predeclared distinct measurements share point-in-time support and the identical chronological split.",
        ) if latest_measurement_report and not measurement_report_ok else (),
        next_action=(
            "Repeat the frozen protocol across plausible competing measurements before generalization."
            if not measurement_report_ok else ""
        ),
    ))
    expected_negative_review = _text(latest_historical.get("verdict")) in {
        "NO_OOS_IMPROVEMENT", "IMPLEMENTATION_SANITY_FAIL", "INVALID",
    }
    eligible_reviews: list[dict[str, Any]] = []
    review_defects: list[str] = []
    for row in reviews:
        refs = {_text(value) for value in (row.get("evidence_refs") or ()) if _text(value)}
        defects = []
        if _text(row.get("review_protocol_version")) != "SRB_COUNCIL_REVIEW_V2":
            defects.append("unrecognised or legacy review protocol")
        if _text(row.get("review_mode")) != "COMPUTATIONAL_COUNCIL_DOSSIER":
            defects.append("review mode is not a transparent computational dossier")
        if _text(row.get("human_attestation_status")) != "NOT_A_HUMAN_PANEL":
            defects.append("human-attestation boundary is not explicit")
        if _text(row.get("decision_scope")) != "RESEARCH_WORKFLOW_ONLY":
            defects.append("decision scope is not research-only")
        if _text(row.get("gate_eligibility")) != "ELIGIBLE_COMPUTATIONAL_REVIEW":
            defects.append("Council dossier is not evidence-eligible")
        if row.get("automatic_promotion_authorized") is not False:
            defects.append("automatic promotion lock is absent")
        if _text(row.get("production_status")) != "RESEARCH_ONLY":
            defects.append("production status is not RESEARCH_ONLY")
        if _text(latest_historical.get("run_id")) not in refs:
            defects.append("latest historical run is missing from evidence references")
        if latest_measurement_report and _text(row.get("measurement_report_id")) != _text(latest_measurement_report.get("report_id")):
            defects.append("latest measurement-robustness report is not attached")
        if expected_negative_review:
            if _text(row.get("council_decision")) != "REVISE_OR_REJECT":
                defects.append("negative run was not dispositioned as REVISE_OR_REJECT")
            if _text(row.get("scientific_grade")) != "FAILED_SCREEN":
                defects.append("negative run was not graded FAILED_SCREEN")
            if _text(row.get("evidence_tier")) != "NEGATIVE_EVIDENCE":
                defects.append("negative evidence tier is not preserved")
            if _text(row.get("disposition")) != "RETAIN_NEGATIVE_RESULT_AND_DO_NOT_ADVANCE_CLAIM":
                defects.append("negative-result retention policy is missing")
        if defects:
            review_defects.append(f"{_text(row.get('review_id')) or 'review'}: {', '.join(defects)}.")
        else:
            eligible_reviews.append(row)
    council_status = "SATISFIED" if eligible_reviews else "WARNING" if reviews else "NOT_EVALUATED"
    council_summary = (
        f"{len(eligible_reviews)} eligible computational Council dossier(s) for the latest historical run; "
        "this is not a human-panel attestation."
        if eligible_reviews else
        f"{len(reviews)} review artifact(s) exist, but none satisfies the fail-closed Council contract."
        if reviews else
        "No Council dossier is tied to the latest historical run."
    )
    gates.append(_gate(
        "VALIDATION_COUNCIL_REVIEWED", "Validation Council", council_status,
        council_summary,
        refs=[row.get("review_id") for row in reviews],
        blockers=review_defects,
        next_action=(
            "Run the explicit computational Validation Council dossier after the historical result and measurement report are persisted."
            if not eligible_reviews else ""
        ),
    ))

    eligible_replications: list[dict[str, Any]] = []
    replication_defects: list[str] = []
    replication_lineage_conflicts: list[str] = []
    for row in replications:
        dimensions = row.get("independence_dimensions") or {}
        independent_axis = any(
            bool(dimensions.get(key))
            for key in ("market", "period", "implementation")
        ) if isinstance(dimensions, Mapping) else False
        defects = []
        if _text(row.get("experiment_id")) != experiment_id:
            defects.append("replication experiment conflicts with the mission lineage")
            replication_lineage_conflicts.append(
                f"{_text(row.get('replication_id')) or 'replication'}: experiment foreign key conflicts with the reference-run lineage."
            )
        if _text(row.get("reference_run_id")) and _text(row.get("reference_run_id")) not in lineage["run_id"]:
            replication_lineage_conflicts.append(
                f"{_text(row.get('replication_id')) or 'replication'}: reference run belongs to another mission lineage."
            )
        if _text(row.get("protocol_version")) != "SRB_INDEPENDENT_REPLICATION_V1":
            defects.append("missing governed replication protocol")
        if _text(row.get("reference_run_id")) != _text(latest_historical.get("run_id")):
            defects.append("replication is not tied to the latest historical run")
        if _text(row.get("execution_status")) != "COMPLETE":
            defects.append("execution is incomplete")
        if _text(row.get("independence_gate_status")) != "PASS" or not independent_axis:
            defects.append("no admissible independent market, period or implementation axis")
        if _text(row.get("point_in_time_status")) != "PASS":
            defects.append("point-in-time evidence is not PASS")
        if _text(row.get("event_time_support_policy")) != REPLICATION_EVENT_TIME_SUPPORT_POLICY:
            defects.append("causal co-release/backfill event-time policy is absent")
        if not _text(row.get("source_snapshot_fingerprint")) or not _text(row.get("execution_fingerprint")):
            defects.append("snapshot or execution fingerprint is missing")
        if not _text(row.get("replication_outcome")):
            defects.append("replication outcome is missing")
        if _text(row.get("production_status")) != "RESEARCH_ONLY":
            defects.append("production status is not RESEARCH_ONLY")
        if row.get("automatic_promotion_authorized") is not False:
            defects.append("automatic promotion lock is absent")
        if defects:
            replication_defects.append(f"{_text(row.get('replication_id')) or 'replication'}: {', '.join(defects)}.")
        else:
            eligible_replications.append(row)
    replication_ok = bool(eligible_replications)
    replication_status = (
        "CONFLICT" if replication_lineage_conflicts else "SATISFIED" if replication_ok else "NOT_EVALUATED"
    )
    gates.append(_gate(
        "INDEPENDENT_REPLICATION", "Independent replication", replication_status,
        (
            "A replication contains contradictory governed foreign keys and cannot enter this mission lineage."
            if replication_lineage_conflicts else
            f"{len(eligible_replications)} governed independent replication execution(s) recorded; outcome sign does not affect gate completion."
            if replication_ok else "No governed point-in-time independent replication execution is complete."
        ),
        refs=[row.get("replication_id") for row in replications],
        blockers=replication_lineage_conflicts or (replication_defects if not replication_ok else ()),
        next_action=(
            "Retain the conflicting replication and restore consistent experiment/reference-run foreign keys."
            if replication_lineage_conflicts else
            "Execute a declared replication on an independent period, market or implementation."
            if not replication_ok else ""
        ),
    ))

    eligible_replication_ids = {_text(row.get("replication_id")) for row in eligible_replications}
    eligible_replication_by_id = {
        _text(row.get("replication_id")): row for row in eligible_replications
        if _text(row.get("replication_id"))
    }
    cross_runtime_rows = [
        dict(row) for row in (snapshot.get("cross_runtime_verifications") or ())
        if _text(row.get("replication_id")) in eligible_replication_ids
    ]
    eligible_cross_runtime: list[dict[str, Any]] = []
    cross_runtime_defects: list[str] = []
    completed_cross_runtime = False
    for row in cross_runtime_rows:
        defects = []
        dimensions = row.get("independence_dimensions") or {}
        if _text(row.get("protocol_version")) != "SRB_CROSS_RUNTIME_VERIFICATION_V1":
            defects.append("missing governed cross-runtime protocol")
        if _text(row.get("execution_status")) != "COMPLETE":
            defects.append("TypeScript execution is incomplete")
        else:
            completed_cross_runtime = True
        if _text(row.get("parity_status")) != "PASS" or _text(row.get("implementation_gate_status")) != "PASS":
            defects.append("cross-runtime parity did not pass")
        if not isinstance(dimensions, Mapping) or dimensions.get("implementation") is not True:
            defects.append("independent implementation axis is not declared")
        if isinstance(dimensions, Mapping) and dimensions.get("investigator") is not False:
            defects.append("investigator independence is overstated")
        if not _text(row.get("challenge_fingerprint")) or not _text(row.get("engine_source_fingerprint")):
            defects.append("challenge or source fingerprint is missing")
        if not _text(row.get("engine_build_fingerprint")) or not _text(row.get("result_fingerprint")):
            defects.append("build or result fingerprint is missing")
        if int(row.get("result_count") or 0) < 1 or int(row.get("matched_result_count") or 0) != int(row.get("result_count") or 0):
            defects.append("not every declared result matched")
        if int(row.get("discrepancy_count") or 0) != 0 or row.get("discrepancies"):
            defects.append("numerical or structural discrepancies remain")
        if _text(row.get("production_status")) != "RESEARCH_ONLY" or row.get("automatic_promotion_authorized") is not False:
            defects.append("research-only promotion lock is absent")
        if defects:
            cross_runtime_defects.append(f"{_text(row.get('verification_id')) or 'verification'}: {', '.join(defects)}.")
        else:
            eligible_cross_runtime.append(row)
    cross_runtime_ok = bool(eligible_cross_runtime)
    cross_runtime_status = "SATISFIED" if cross_runtime_ok else "CONFLICT" if completed_cross_runtime else "NOT_EVALUATED"
    gates.append(_gate(
        "CROSS_RUNTIME_REPRODUCIBILITY",
        "Cross-runtime reproducibility",
        cross_runtime_status,
        (
            f"{len(eligible_cross_runtime)} sealed TypeScript/Node reproduction(s) match every persisted Python result."
            if cross_runtime_ok else
            "A completed independent code-path reproduction disagrees with the persisted Python execution."
            if completed_cross_runtime else
            "No completed independent TypeScript/Node reproduction is tied to the governed replication."
        ),
        refs=[row.get("verification_id") for row in cross_runtime_rows],
        blockers=cross_runtime_defects,
        next_action=(
            "Inspect and retain every cross-runtime discrepancy before changing either implementation."
            if completed_cross_runtime else
            "Freeze and execute the independent TypeScript/Node challenge against the sealed ALFRED snapshot."
        ) if not cross_runtime_ok else "",
    ))

    direct_rows = [
        dict(row) for row in (snapshot.get("direct_source_reconciliations") or ())
        if _text(row.get("replication_id")) in eligible_replication_ids
    ]
    eligible_direct: list[dict[str, Any]] = []
    direct_defects: list[str] = []
    for row in direct_rows:
        if _text(row.get("execution_status")) != "COMPLETE":
            continue
        defects: list[str] = []
        dimensions = row.get("independence_dimensions") or {}
        series_results = [dict(item) for item in (row.get("series_results") or ()) if isinstance(item, Mapping)]
        authoritative_validation = validate_completed_direct_bis_reconciliation(
            row,
            reference_replication=eligible_replication_by_id.get(_text(row.get("replication_id"))),
        )
        defects.extend(str(item) for item in authoritative_validation.get("defects") or ())
        if _text(row.get("protocol_version")) != DIRECT_BIS_PROTOCOL_VERSION:
            defects.append("missing governed direct-source protocol")
        if _text(row.get("source_integrity_status")) != "PASS":
            defects.append("direct source integrity is not PASS")
        if _text(row.get("coverage_status")) != "PASS":
            defects.append("declared direct series coverage is not PASS")
        if _text(row.get("reconciliation_status")) not in {"EXACT_MATCH", "RECONCILED_WITH_REVISIONS"}:
            defects.append("revision reconciliation is incomplete")
        expected_count = _exact_int(row.get("expected_series_count"))
        series_count = _exact_int(row.get("series_count"))
        if expected_count < 1 or series_count != expected_count or len(series_results) != expected_count:
            defects.append("not every frozen series has a reconciliation result")
        if not _text(row.get("direct_snapshot_id")) or not _text(row.get("direct_snapshot_fingerprint")):
            defects.append("direct snapshot identity or fingerprint is missing")
        if not _text(row.get("raw_archive_sha256")) or not _text(row.get("reconciliation_fingerprint")):
            defects.append("raw archive or reconciliation fingerprint is missing")
        if _text(row.get("history_semantics")) != DIRECT_BIS_HISTORY_SEMANTICS:
            defects.append("current revised-history semantics are not explicit")
        if _text(row.get("point_in_time_status")) != "NOT_POINT_IN_TIME":
            defects.append("direct revised history is being overstated as point-in-time")
        if row.get("historical_evidence_eligible") is not False:
            defects.append("direct revised history is incorrectly eligible as historical evidence")
        if not isinstance(dimensions, Mapping):
            defects.append("independence dimensions are missing")
        else:
            if dimensions.get("distribution_channel") is not True or dimensions.get("source_host") is not True:
                defects.append("independent direct distribution route is not declared")
            if dimensions.get("underlying_data_lineage") is not False or dimensions.get("point_in_time") is not False:
                defects.append("shared lineage or non-point-in-time boundary is overstated")
            if dimensions.get("investigator") is not False:
                defects.append("investigator independence is overstated")
        minimum_overlap = _exact_int(row.get("min_overlap_rows"))
        if any(
            _exact_int(item.get("overlap_row_count"), default=-1) < minimum_overlap
            or not _text(item.get("comparison_fingerprint"))
            or item.get("historical_evidence_eligible") is not False
            for item in series_results
        ):
            defects.append("a series comparison lacks governed overlap, fingerprint or evidence boundary")
        if _text(row.get("production_status")) != "RESEARCH_ONLY" or row.get("automatic_promotion_authorized") is not False:
            defects.append("research-only promotion lock is absent")
        if defects:
            direct_defects.append(f"{_text(row.get('reconciliation_id')) or 'reconciliation'}: {', '.join(defects)}.")
        else:
            eligible_direct.append(row)

    direct_conflict = bool(direct_defects)
    direct_ok = bool(eligible_direct) and not direct_conflict
    direct_status = "CONFLICT" if direct_conflict else "SATISFIED" if direct_ok else "NOT_EVALUATED"
    prospective = {}
    if eligible_direct:
        latest_direct = max(eligible_direct, key=_observation_order)
        prospective = build_prospective_vintage_summary(
            direct_rows,
            replication_id=_text(latest_direct.get("replication_id")),
            min_distinct_snapshots=int(latest_direct.get("prospective_min_distinct_snapshots") or 12),
            min_distinct_latest_periods=int(latest_direct.get("prospective_min_distinct_latest_periods") or 12),
            min_span_days=int(latest_direct.get("prospective_min_span_days") or 300),
        )
    gates.append(_gate(
        "DIRECT_SOURCE_RECONCILIATION",
        "Direct-source reconciliation",
        direct_status,
        (
            f"{len(eligible_direct)} direct BIS revised-history observation(s) reconcile all declared series; "
            f"the legacy raw-content inventory is {prospective.get('status', 'WARMING_UP')} "
            f"({prospective.get('distinct_snapshots', 0)}/"
            f"{prospective.get('required_distinct_snapshots', 12)} content-distinct snapshots). "
            "Phase 6.8 is authoritative for monthly schedule credit and maturity. This gate validates provenance and "
            "revision accounting, not point-in-time historical evidence."
            if direct_ok else
            "A completed direct-source record violates its provenance, coverage or non-point-in-time boundary."
            if direct_conflict else
            "No complete direct BIS revised-history reconciliation is tied to the governed replication."
        ),
        refs=[row.get("reconciliation_id") for row in direct_rows],
        blockers=direct_defects,
        next_action=(
            "Inspect and retain the direct-source conflict; never promote revised history into point-in-time evidence."
            if direct_conflict else
            "Freeze one explicit direct BIS observation, then acquire and reconcile the six declared series."
        ) if not direct_ok else "",
    ))

    eligible_direct_ids = {
        _text(row.get("reconciliation_id")) for row in eligible_direct
        if _text(row.get("reconciliation_id"))
    }
    eligible_direct_by_id = {
        _text(row.get("reconciliation_id")): row for row in eligible_direct
        if _text(row.get("reconciliation_id"))
    }
    triangulation_rows = [
        dict(row) for row in (snapshot.get("cross_provider_triangulations") or ())
        if (
            _text(row.get("replication_id")) in eligible_replication_ids
            or _text(row.get("direct_reconciliation_id")) in eligible_direct_ids
        )
    ]
    eligible_triangulations: list[dict[str, Any]] = []
    non_comparable_triangulations: list[dict[str, Any]] = []
    triangulation_defects: list[str] = []
    for row in triangulation_rows:
        if _text(row.get("execution_status")) != "COMPLETE":
            continue
        defects: list[str] = []
        dimensions = row.get("independence_dimensions") or {}
        results = [dict(item) for item in (row.get("series_results") or ()) if isinstance(item, Mapping)]
        direct_parent = eligible_direct_by_id.get(_text(row.get("direct_reconciliation_id")))
        if not direct_parent or _text(direct_parent.get("replication_id")) != _text(row.get("replication_id")):
            defects.append("direct reconciliation does not belong to the declared replication")
        elif (
            _text(row.get("direct_snapshot_id")) != _text(direct_parent.get("direct_snapshot_id"))
            or _text(row.get("direct_snapshot_fingerprint"))
            != _text(direct_parent.get("direct_snapshot_fingerprint"))
        ):
            defects.append("direct snapshot identity differs from the declared reconciliation")
        if _text(row.get("protocol_version")) != CROSS_PROVIDER_PROTOCOL_VERSION:
            defects.append("missing governed cross-provider protocol")
        if _text(row.get("source_integrity_status")) != "PASS":
            defects.append("OECD source integrity is not PASS")
        if _text(row.get("coverage_status")) != "PASS":
            defects.append("declared OECD series coverage is not PASS")
        outcome = _text(row.get("triangulation_outcome"))
        if outcome not in {"CONCORDANT", "MEASUREMENT_DIVERGENCE", "NOT_COMPARABLE"}:
            defects.append("triangulation outcome is missing or unsupported")
        expected_count = _exact_int(row.get("expected_series_count"))
        source_count = _exact_int(row.get("source_series_count"))
        if expected_count != 3 or source_count != expected_count or len(results) != expected_count:
            defects.append("the frozen GB/JP/US comparison matrix is incomplete")
        if not _text(row.get("oecd_snapshot_id")) or not _text(row.get("oecd_snapshot_fingerprint")):
            defects.append("OECD snapshot identity or fingerprint is missing")
        if not _text(row.get("raw_csv_sha256")) or not _text(row.get("triangulation_fingerprint")):
            defects.append("raw OECD CSV or triangulation fingerprint is missing")
        if _text(row.get("history_semantics")) != OECD_HISTORY_SEMANTICS:
            defects.append("current revised-history semantics are not explicit")
        if _text(row.get("point_in_time_status")) != "NOT_POINT_IN_TIME":
            defects.append("cross-provider revised history is being overstated as point-in-time")
        if row.get("historical_evidence_eligible") is not False:
            defects.append("cross-provider revised history is incorrectly eligible as historical evidence")
        if not isinstance(dimensions, Mapping):
            defects.append("cross-provider independence dimensions are missing")
        else:
            if (
                dimensions.get("distribution_channel") is not True
                or dimensions.get("source_host") is not True
                or dimensions.get("provider_organization") is not True
            ):
                defects.append("distinct provider/distribution axes are not declared")
            if dimensions.get("underlying_data_lineage") is not False or dimensions.get("methodology") is not False:
                defects.append("unresolved underlying lineage or methodology is overstated as independent")
            if dimensions.get("point_in_time") is not False or dimensions.get("investigator") is not False:
                defects.append("point-in-time or investigator independence is overstated")
        minimum_overlap = _exact_int(row.get("min_overlap_rows"))
        for result in results:
            result_status = _text(result.get("status"))
            if result_status not in {"CONCORDANT", "MEASUREMENT_DIVERGENCE", "NOT_COMPARABLE"}:
                defects.append("a country result has no governed status")
                continue
            if not _text(result.get("comparison_fingerprint")):
                defects.append("a country comparison fingerprint is missing")
            if result.get("historical_evidence_eligible") is not False:
                defects.append("a country comparison is incorrectly eligible as historical evidence")
            if result_status != "NOT_COMPARABLE":
                checks = result.get("threshold_checks")
                if _exact_int(result.get("overlap_row_count"), default=-1) < minimum_overlap:
                    defects.append("a comparable country result lacks governed overlap")
                if not isinstance(checks, Mapping) or set(checks) != {
                    "change_correlation", "sign_agreement", "mean_absolute_change_gap"
                }:
                    defects.append("a comparable country result lacks the frozen threshold audit")
        if _text(row.get("production_status")) != "RESEARCH_ONLY" or row.get("automatic_promotion_authorized") is not False:
            defects.append("research-only promotion lock is absent")
        if defects:
            triangulation_defects.append(
                f"{_text(row.get('triangulation_id')) or 'triangulation'}: {', '.join(dict.fromkeys(defects))}."
            )
        elif outcome == "NOT_COMPARABLE" or _text(row.get("comparability_status")) != "PASS":
            non_comparable_triangulations.append(row)
        else:
            eligible_triangulations.append(row)

    triangulation_conflict = bool(triangulation_defects)
    triangulation_ok = bool(eligible_triangulations) and not triangulation_conflict
    triangulation_warning = bool(non_comparable_triangulations) and not triangulation_conflict and not triangulation_ok
    triangulation_status = (
        "CONFLICT" if triangulation_conflict else
        "SATISFIED" if triangulation_ok else
        "WARNING" if triangulation_warning else
        "NOT_EVALUATED"
    )
    latest_triangulation = max(
        eligible_triangulations or non_comparable_triangulations,
        key=lambda item: _text(item.get("retrieved_at")),
        default={},
    )
    latest_outcome = _text(latest_triangulation.get("triangulation_outcome")) or "NOT_RUN"
    gates.append(_gate(
        "CROSS_PROVIDER_MEASUREMENT_TRIANGULATION",
        "Cross-provider measurement triangulation",
        triangulation_status,
        (
            f"OECD/BIS monthly-change triangulation is complete across GB, JP and US: {latest_outcome}. "
            "The outcome is retained as a measurement diagnostic; neither source is ground truth and underlying-lineage independence remains unresolved."
            if triangulation_ok else
            "A completed OECD/BIS triangulation violates its frozen provenance, comparability or inference boundary."
            if triangulation_conflict else
            "The OECD/BIS protocol executed, but at least one country is not structurally comparable under the frozen contract."
            if triangulation_warning else
            "No complete OECD/BIS cross-provider triangulation is tied to the governed direct-source snapshot."
        ),
        refs=[row.get("triangulation_id") for row in triangulation_rows],
        blockers=triangulation_defects + [
            f"{_text(row.get('triangulation_id'))}: retained NOT_COMPARABLE outcome."
            for row in non_comparable_triangulations
        ],
        next_action=(
            "Inspect and retain the cross-provider conflict; do not select a preferred provider after seeing the result."
            if triangulation_conflict else
            "Audit the comparability failure and freeze a new protocol only if the source definition changes."
            if triangulation_warning else
            "Freeze the OECD/BIS thresholds before network access, then acquire the three monthly CPI-based REER series."
        ) if not triangulation_ok else "",
    ))

    all_program_rows = [
        dict(row) for row in (snapshot.get("prospective_observation_programs") or ())
        if _text(row.get("replication_id")) in eligible_replication_ids
    ]
    active_direct = max(eligible_direct, key=_observation_order, default={})
    active_replication_id = _text(active_direct.get("replication_id"))
    program_rows = [
        row for row in all_program_rows
        if _text(row.get("replication_id")) == active_replication_id
    ]
    valid_programs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    program_defects: list[str] = []
    if len(program_rows) > 1:
        identities = ", ".join(_text(row.get("program_id")) or "MISSING_ID" for row in program_rows)
        program_defects.append(
            f"Active replication {active_replication_id} has {len(program_rows)} prospective program rows ({identities}); exactly one is allowed."
        )
    for row in program_rows:
        identity = _text(row.get("program_id")) or "program"
        defects: list[str] = []
        validation = validate_prospective_observation_program(row)
        defects.extend(str(item) for item in validation.get("defects") or ())
        if _text(row.get("protocol_version")) != PROSPECTIVE_OBSERVATION_PROTOCOL_VERSION:
            defects.append("missing governed prospective observation protocol")
        replication_direct = [
            direct for direct in eligible_direct
            if _text(direct.get("replication_id")) == _text(row.get("replication_id"))
        ]
        replication_direct_ids = {
            _text(direct.get("reconciliation_id")) for direct in replication_direct
            if _text(direct.get("reconciliation_id"))
        }
        if _text(row.get("seed_reconciliation_id")) not in replication_direct_ids:
            defects.append("seed direct reconciliation is absent or ineligible")
        try:
            frozen_at = _utc_instant(row.get("protocol_frozen_at"))
            available_at_freeze: list[tuple[datetime, dict[str, Any]]] = []
            for direct in replication_direct:
                retrieved_at = _utc_instant(direct.get("retrieved_at"))
                completed_at = _utc_instant(direct.get("completed_at"))
                if retrieved_at <= frozen_at and completed_at <= frozen_at:
                    available_at_freeze.append((retrieved_at, direct))
            expected_seed = max(
                available_at_freeze,
                key=lambda item: (item[0], _text(item[1].get("reconciliation_id"))),
            )[1] if available_at_freeze else {}
            if _text(expected_seed.get("reconciliation_id")) != _text(row.get("seed_reconciliation_id")):
                defects.append("seed is not the latest eligible direct observation available at protocol freeze")
        except (TypeError, ValueError):
            defects.append("seed recency cannot be verified from governed UTC timestamps")
        if len(program_rows) != 1:
            defects.append("more than one prospective program governs the replication")
        if defects:
            program_defects.append(f"{identity}: {', '.join(dict.fromkeys(defects))}.")
            continue
        try:
            state = evaluate_prospective_observation_program(
                row,
                [
                    direct for direct in direct_rows
                    if _text(direct.get("replication_id")) == _text(row.get("replication_id"))
                ],
                as_of=_text(snapshot.get("captured_at")) or None,
            )
        except Exception as exc:
            program_defects.append(f"{identity}: {type(exc).__name__}: {str(exc)}.")
            continue
        valid_programs.append((row, state))

    program_conflict = bool(program_defects)
    program_ok = len(valid_programs) == 1 and not program_conflict
    program_status = "CONFLICT" if program_conflict else "SATISFIED" if program_ok else "NOT_EVALUATED"
    program_state = valid_programs[0][1] if program_ok else {}
    maturity = program_state.get("maturity") or {}
    gates.append(_gate(
        "PROSPECTIVE_OBSERVATION_PROTOCOL",
        "Prospective observation protocol",
        program_status,
        (
            f"Future-only UTC monthly program is {program_state.get('program_status')}; "
            f"maturity is {maturity.get('status', 'WARMING_UP')} with "
            f"{maturity.get('distinct_snapshots', 0)}/{maturity.get('required_distinct_snapshots', 12)} "
            f"content-distinct snapshots, {maturity.get('distinct_latest_periods', 0)}/"
            f"{maturity.get('required_distinct_latest_periods', 12)} latest months and "
            f"{maturity.get('span_days', 0)}/{maturity.get('required_span_days', 300)} observed days. "
            "This gate validates the frozen operating protocol, not longitudinal scientific maturity."
            if program_ok else
            "A prospective program violates its frozen cadence, seed, no-backfill boundary or research-only lock."
            if program_conflict else
            f"No future-only observation program is frozen around the active replication {active_replication_id or 'UNKNOWN'} direct-BIS seed."
        ),
        refs=[row.get("program_id") for row in program_rows],
        blockers=program_defects,
        next_action=(
            "Retain the conflict and restore the exact frozen program; never relabel a missed window as observed."
            if program_conflict else
            "Freeze the monthly prospective observation program around the latest governed direct-BIS seed."
        ) if not program_ok else "",
    ))

    unauthorized_belief = any(bool(row.get("belief_update_authorized")) for row in syntheses)
    bad_production = []
    for key, rows in snapshot.items():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, Mapping) and row.get("production_status") not in (None, "", "RESEARCH_ONLY"):
                bad_production.append(f"{key}:{_text(row.get('run_id')) or _text(row.get('question_id')) or 'record'}")
    production_safe = not unauthorized_belief and not bad_production
    gates.append(_gate(
        "PRODUCTION_PROMOTION_LOCK", "Production & belief lock", "SATISFIED" if production_safe else "BLOCKED",
        "Workspace-wide RESEARCH_ONLY kill-switch enforced; synthesis cannot update beliefs automatically."
        if production_safe else "Workspace-wide unauthorized production/belief state detected.",
        blockers=bad_production + (["A synthesis authorizes automatic belief update."] if unauthorized_belief else []),
        next_action="Restore RESEARCH_ONLY and revoke automatic belief update before continuing." if not production_safe else "",
    ))

    blocking_statuses = {"BLOCKED", "CONFLICT"}
    evidence_pending_statuses = {"NOT_EVALUATED", "WARNING"}
    def derived_status(selected: Sequence[ResearchGate]) -> str:
        return (
            "BLOCKED" if any(gate.status in blocking_statuses for gate in selected)
            else "WAITING_EVIDENCE" if any(gate.status in evidence_pending_statuses for gate in selected)
            else "READY_FOR_REVIEW"
        )

    overall = derived_status(gates)
    core_gates = [gate for gate in gates if gate.gate_id != "PROSPECTIVE_OBSERVATION_PROTOCOL"]
    core_study_status = derived_status(core_gates)
    prospective_operations_status = program_status
    next_gate = (
        next((gate for gate in gates if gate.status in blocking_statuses), None)
        or next((gate for gate in gates if gate.status == "NOT_EVALUATED"), None)
        or next((gate for gate in gates if gate.status == "WARNING"), None)
    )
    # A persisted plan action describes how to reach a reviewable state. Once
    # every gate is satisfied it is historical context, not the current action;
    # surfacing it here would contradict READY_FOR_REVIEW in Mission Control.
    next_action = next_gate.next_action if next_gate else "Review the completed mission with the Validation Council."
    ledger = next((dict(row) for row in (snapshot.get("budgets") or ()) if _text(row.get("plan_id")) == _text(plan.get("plan_id"))), {})
    budget_remaining = {
        "literature_queries": max(0.0, float(ledger.get("max_literature_queries") or 0) - float(ledger.get("used_literature_queries") or 0)),
        "hypotheses": max(0.0, float(ledger.get("max_hypotheses") or 0) - float(ledger.get("used_hypotheses") or 0)),
        "tasks": max(0.0, float(ledger.get("max_tasks") or 0) - float(ledger.get("used_tasks") or 0)),
        "experiment_proposals": max(0.0, float(ledger.get("max_experiment_proposals") or 0) - float(ledger.get("used_experiment_proposals") or 0)),
        "cycles": max(0.0, float(ledger.get("max_cycles") or 0) - float(ledger.get("used_cycles") or 0)),
        "compute_units": max(0.0, float(ledger.get("max_compute_units") or 0) - float(ledger.get("used_compute_units") or 0)),
    }
    # Persisted plan blockers describe historical planning debt. Active mission
    # blockers come only from the current derived gates; otherwise a fully
    # satisfied READY mission can contradict itself in the UI.
    all_blockers: list[str] = []
    for gate in gates:
        all_blockers.extend(gate.blockers)
    counts = {
        "hypotheses": len(hypotheses), "observables": len(observables), "grounded_evidence": len(active_evidence),
        "assessments": len(assessments), "syntheses": len(syntheses), "contracts": len(contracts),
        "manifests": len(manifests), "attempts": len(attempts), "runs": len(runs),
        "historical_runs": len(historical_runs), "reviews": len(reviews), "replications": len(replications),
        "capsules": len(capsules),
        "measurement_protocols": len(measurement_protocols),
        "measurement_reports": len(measurement_reports),
        "cross_runtime_verifications": len(cross_runtime_rows),
        "direct_source_reconciliations": len(direct_rows),
        "cross_provider_triangulations": len(triangulation_rows),
        "prospective_observation_programs": len(all_program_rows),
        "diagnostics": len([row for row in (snapshot.get("break_diagnostics") or ()) if _text(row.get("run_id")) == _text(latest_historical.get("run_id"))]),
        "inconsistencies": len(inconsistencies),
    }
    snapshot_id = _stable_id("MISSION", qid, snapshot.get("captured_at", ""), *(gate.status for gate in gates))
    return MissionSnapshot(
        snapshot_id=snapshot_id,
        created_at=_text(snapshot.get("captured_at")) or _now_iso(),
        question_id=qid,
        question_title=_text(question.get("title")),
        question_status=_text(question.get("status")) or "MISSING",
        plan_id=_text(plan.get("plan_id")),
        plan_status=_text(plan.get("status")) or "MISSING",
        leading_hypothesis_id=_text(leading.get("hypothesis_id")),
        leading_hypothesis_label=_text(leading.get("label")),
        null_hypothesis_id=_text(null_hypothesis.get("hypothesis_id")),
        null_hypothesis_label=_text(null_hypothesis.get("label")),
        primary_observable_id=primary_id,
        primary_observable_label=_text(primary_observable.get("label")),
        next_action=next_action,
        overall_status=overall,
        gates=tuple(gates),
        inconsistencies=tuple(dict.fromkeys(inconsistencies)),
        blockers=tuple(dict.fromkeys(_text(item) for item in all_blockers if _text(item))),
        budget_remaining=budget_remaining,
        counts=counts,
        core_study_status=core_study_status,
        prospective_operations_status=prospective_operations_status,
    )


def build_measurement_arena(snapshot: Mapping[str, Any], question_id: str) -> list[dict[str, Any]]:
    qid = _text(question_id)
    question = _find(snapshot.get("questions") or (), "question_id", qid)
    model = max((dict(row) for row in (snapshot.get("measurement_models") or ()) if _text(row.get("question_id")) == qid), key=lambda row: _text(row.get("created_at")), default={})
    decision = max((dict(row) for row in (snapshot.get("measurement_decisions") or ()) if _text(row.get("question_id")) == qid), key=lambda row: _text(row.get("created_at")), default={})
    hypotheses = {str(row.get("observable_id") or ""): dict(row) for row in (snapshot.get("measurement_hypotheses") or ()) if _text(row.get("question_id")) == qid}
    runs = [dict(row) for row in (snapshot.get("runs") or ()) if _text(row.get("stage")) == "HISTORICAL_OOS"]
    rows: list[dict[str, Any]] = []
    for observable in (snapshot.get("observables") or ()):
        if _text(observable.get("question_id")) != qid:
            continue
        oid = _text(observable.get("observable_id"))
        measurement = hypotheses.get(oid, {})
        attributed_runs = [run for run in runs if _text(run.get("observable_id")) == oid]
        rows.append({
            "observable_id": oid,
            "label": observable.get("label"),
            "observable_status": observable.get("status"),
            "decision_primary": oid == _text(decision.get("selected_observable_id")),
            "model_primary": oid == _text(model.get("primary_observable_id")),
            "question_primary": oid == _text(question.get("selected_observable_id")),
            "definition": observable.get("mathematical_definition"),
            "unit": observable.get("unit"),
            "frequency": observable.get("frequency"),
            "required_columns": list(observable.get("required_columns") or ()),
            "design_score": observable.get("total_score"),
            "measurement_error_risks": list(measurement.get("measurement_error_risks") or ()),
            "sensitivity_dimensions": list(measurement.get("sensitivity_dimensions") or ()),
            "historical_runs": len(attributed_runs),
            "invariance_status": "NOT_RECORDED" if not attributed_runs else "PARTIAL_NOT_SYNTHESIZED",
        })
    return sorted(rows, key=lambda row: float(row.get("design_score") or 0.0), reverse=True)


def build_evidence_inspector(snapshot: Mapping[str, Any], question_id: str) -> list[dict[str, Any]]:
    qid = _text(question_id)
    understandings = {_text(row.get("understanding_id")): dict(row) for row in (snapshot.get("understanding") or ())}
    papers = {_text(row.get("paper_id")): dict(row) for row in (snapshot.get("papers") or ())}
    provenance = {_text(row.get("provenance_id")): dict(row) for row in (snapshot.get("provenance") or ())}
    assessments = _as_rows(snapshot.get("evidence_assessments"))
    output: list[dict[str, Any]] = []
    for evidence in (snapshot.get("evidence") or ()):
        if _text(evidence.get("question_id")) != qid:
            continue
        understanding = understandings.get(_text(evidence.get("understanding_id")), {})
        claim_rows = []
        for claim in understanding.get("claims") or ():
            if not isinstance(claim, Mapping):
                continue
            prov = provenance.get(_text(claim.get("provenance_id")), {})
            claim_rows.append({
                "claim_id": claim.get("claim_id"), "text": claim.get("text"),
                "claim_type": claim.get("claim_type"), "claim_subtype": claim.get("claim_subtype"),
                "explicit": claim.get("explicit"), "provenance_id": claim.get("provenance_id"),
                "excerpt": prov.get("excerpt"), "source_digest": prov.get("source_digest"),
            })
        output.append({
            "evidence": dict(evidence),
            "understanding": understanding,
            "paper": papers.get(_text(evidence.get("paper_id")), {}),
            "claims": claim_rows,
            "assessments": [row for row in assessments if _text(row.get("evidence_id")) == _text(evidence.get("evidence_id"))],
            "content_ready": bool(claim_rows or evidence.get("mechanism_keys") or evidence.get("semantic_entity_ids")),
        })
    return output


def build_run_room(snapshot: Mapping[str, Any], question_id: str) -> dict[str, Any]:
    mission = build_mission_snapshot(snapshot, question_id)
    question = _find(snapshot.get("questions") or (), "question_id", mission.question_id)
    lineage = build_mission_lineage_index(snapshot, mission.question_id)
    experiment_id = _text(question.get("experiment_id"))
    if not experiment_id and len(lineage["experiment_id"]) == 1:
        experiment_id = next(iter(lineage["experiment_id"]))
    spec = _find(snapshot.get("experiment_specs") or (), "experiment_id", experiment_id)
    runs = [
        dict(row) for row in (snapshot.get("runs") or ())
        if _text(row.get("run_id")) in lineage["run_id"]
    ]
    run = max(runs, key=lambda row: _text(row.get("created_at")), default={})
    run_id = _text(run.get("run_id"))
    return {
        "mission": asdict(mission),
        "specification": spec,
        "run": run,
        "reviews": [dict(row) for row in (snapshot.get("reviews") or ()) if _text(row.get("run_id")) == run_id],
        "failures": [dict(row) for row in (snapshot.get("failures") or ()) if _text(row.get("run_id")) == run_id],
        "surprises": [dict(row) for row in (snapshot.get("surprises") or ()) if _text(row.get("run_id")) == run_id],
        "attempt": _find(snapshot.get("attempts") or (), "attempt_id", _text(run.get("attempt_id"))),
        "manifest": _find(snapshot.get("dataset_manifests") or (), "manifest_id", _text(run.get("dataset_manifest_id"))),
        "capsules": [dict(row) for row in (snapshot.get("capsules") or ()) if _text(row.get("run_id")) == run_id],
        "diagnostics": [dict(row) for row in (snapshot.get("break_diagnostics") or ()) if _text(row.get("run_id")) == run_id],
        "replications": [
            dict(row) for row in (snapshot.get("replications") or ())
            if _text(row.get("replication_id")) in lineage["replication_id"]
        ],
    }


def build_epistemic_timeline(snapshot: Mapping[str, Any], question_id: str, limit: int = 120) -> list[dict[str, Any]]:
    qid = _text(question_id)
    lineage = build_mission_lineage_index(snapshot, qid)
    timeline: list[dict[str, Any]] = []
    identity_fields = (
        "question_id", "hypothesis_id", "plan_id", "observable_id", "measurement_model_id",
        "decision_id", "evidence_id", "assessment_id", "synthesis_id", "contract_id",
        "manifest_id", "attempt_id", "run_id", "review_id", "failure_id", "surprise_id",
        "capsule_id", "diagnostic_id", "replication_id", "verification_id",
        "reconciliation_id", "triangulation_id", "program_id",
    )
    for registry, rows in snapshot.items():
        if not isinstance(rows, list) or registry in {"registry_health", "audit"}:
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            row_qid = _text(row.get("question_id"))
            linked = row_qid == qid if row_qid else any(
                _text(row.get(field)) in identities
                for field, identities in lineage.items()
                if identities and field in row
            )
            if qid and not linked:
                continue
            ref_id = next((_text(row.get(field)) for field in identity_fields if _text(row.get(field))), "")
            created_at = _text(row.get("created_at"))
            if created_at:
                timeline.append({"timestamp": created_at, "source_registry": registry, "event_type": "RECORD_CREATED", "ref_id": ref_id, "detail": _text(row.get("status")) or _text(row.get("verdict"))})
            for event in row.get("lifecycle_history") or ():
                if isinstance(event, Mapping) and _text(event.get("at")):
                    timeline.append({
                        "timestamp": _text(event.get("at")), "source_registry": registry,
                        "event_type": f"LIFECYCLE {_text(event.get('from'))}->{_text(event.get('to'))}",
                        "ref_id": ref_id, "detail": _text(event.get("reason")),
                    })
    for event in snapshot.get("audit") or ():
        payload = event.get("payload") or {}
        payload_qid = _text(payload.get("question_id"))
        linked = payload_qid == qid if payload_qid else any(
            _text(payload.get(field)) in identities
            for field, identities in lineage.items()
            if identities and field in payload
        )
        if qid and not linked:
            continue
        ref_id = next((_text(payload.get(field)) for field in identity_fields if _text(payload.get(field))), "")
        timeline.append({
            "timestamp": _text(event.get("timestamp")), "source_registry": "audit",
            "event_type": _text(event.get("event")), "ref_id": ref_id,
            "detail": json.dumps(payload, ensure_ascii=False, default=str)[:500],
        })
    return sorted((row for row in timeline if row.get("timestamp")), key=lambda row: row["timestamp"], reverse=True)[: max(1, int(limit))]
