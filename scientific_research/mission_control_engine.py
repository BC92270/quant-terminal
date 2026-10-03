from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .phase63_models import MissionSnapshot, RegistryFileHealth, ResearchGate
from .registry_io import registry_lock
from .replication_engine import REPLICATION_EVENT_TIME_SUPPORT_POLICY


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(part or "").strip().lower() for part in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _text(value: Any) -> str:
    return str(value or "").strip()


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
    plan = _find(snapshot.get("plans") or (), "plan_id", _text(question.get("plan_id")))
    if not plan:
        plan = next((dict(row) for row in (snapshot.get("plans") or ()) if _text(row.get("question_id")) == qid), {})
    experiment_id = _text(question.get("experiment_id"))
    if not experiment_id:
        experiment_id = _text(next((row.get("experiment_id") for row in (snapshot.get("experiment_specs") or ()) if _text(row.get("experiment_id"))), ""))
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
    attempts = [dict(row) for row in (snapshot.get("attempts") or ()) if _text(row.get("experiment_id")) == experiment_id]
    runs = [dict(row) for row in (snapshot.get("runs") or ()) if _text(row.get("experiment_id")) == experiment_id]
    historical_runs = [row for row in runs if _text(row.get("stage")) == "HISTORICAL_OOS"]
    attributed_historical = [
        row for row in historical_runs
        if _text(row.get("observable_id")) == primary_id
        and (not manifest or _text(row.get("dataset_manifest_id")) == _text(manifest.get("manifest_id")))
    ]
    latest_historical = max(attributed_historical, key=lambda row: _text(row.get("created_at")), default={})
    reviews = [dict(row) for row in (snapshot.get("reviews") or ()) if _text(row.get("run_id")) == _text(latest_historical.get("run_id"))]
    replications = [dict(row) for row in (snapshot.get("replications") or ()) if _text(row.get("experiment_id")) == experiment_id]
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
    for row in replications:
        dimensions = row.get("independence_dimensions") or {}
        independent_axis = any(
            bool(dimensions.get(key))
            for key in ("market", "period", "implementation")
        ) if isinstance(dimensions, Mapping) else False
        defects = []
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
    gates.append(_gate(
        "INDEPENDENT_REPLICATION", "Independent replication", "SATISFIED" if replication_ok else "NOT_EVALUATED",
        (
            f"{len(eligible_replications)} governed independent replication execution(s) recorded; outcome sign does not affect gate completion."
            if replication_ok else "No governed point-in-time independent replication execution is complete."
        ),
        refs=[row.get("replication_id") for row in replications],
        blockers=replication_defects if not replication_ok else (),
        next_action="Execute a declared replication on an independent period, market or implementation." if not replication_ok else "",
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
        "RESEARCH_ONLY enforced; synthesis cannot update beliefs automatically." if production_safe else "Unauthorized production/belief state detected.",
        blockers=bad_production + (["A synthesis authorizes automatic belief update."] if unauthorized_belief else []),
        next_action="Restore RESEARCH_ONLY and revoke automatic belief update before continuing." if not production_safe else "",
    ))

    blocking_statuses = {"BLOCKED", "CONFLICT"}
    evidence_pending_statuses = {"NOT_EVALUATED", "WARNING"}
    overall = "BLOCKED" if any(gate.status in blocking_statuses for gate in gates) else "WAITING_EVIDENCE" if any(gate.status in evidence_pending_statuses for gate in gates) else "READY_FOR_REVIEW"
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
    all_blockers = list(plan.get("blockers") or ())
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
    experiment_id = _text(question.get("experiment_id"))
    if not experiment_id:
        experiment_id = _text(next((row.get("experiment_id") for row in (snapshot.get("experiment_specs") or ()) if row.get("experiment_id")), ""))
    spec = _find(snapshot.get("experiment_specs") or (), "experiment_id", experiment_id)
    runs = [dict(row) for row in (snapshot.get("runs") or ()) if _text(row.get("experiment_id")) == experiment_id]
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
        "replications": [dict(row) for row in (snapshot.get("replications") or ()) if _text(row.get("experiment_id")) == experiment_id],
    }


def build_epistemic_timeline(snapshot: Mapping[str, Any], question_id: str, limit: int = 120) -> list[dict[str, Any]]:
    qid = _text(question_id)
    timeline: list[dict[str, Any]] = []
    identity_fields = (
        "question_id", "hypothesis_id", "plan_id", "observable_id", "measurement_model_id",
        "decision_id", "evidence_id", "assessment_id", "synthesis_id", "contract_id",
        "manifest_id", "attempt_id", "run_id", "review_id", "failure_id", "surprise_id",
        "capsule_id", "diagnostic_id",
    )
    for registry, rows in snapshot.items():
        if not isinstance(rows, list) or registry in {"registry_health", "audit"}:
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            row_qid = _text(row.get("question_id"))
            if row_qid and qid and row_qid != qid:
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
        if qid and _text(payload.get("question_id")) not in {"", qid} and qid not in json.dumps(payload, default=str):
            continue
        ref_id = next((_text(payload.get(field)) for field in identity_fields if _text(payload.get(field))), "")
        timeline.append({
            "timestamp": _text(event.get("timestamp")), "source_registry": "audit",
            "event_type": _text(event.get("event")), "ref_id": ref_id,
            "detail": json.dumps(payload, ensure_ascii=False, default=str)[:500],
        })
    return sorted((row for row in timeline if row.get("timestamp")), key=lambda row: row["timestamp"], reverse=True)[: max(1, int(limit))]
