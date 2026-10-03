from __future__ import annotations

import hashlib
import math
import statistics
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .phase5_models import (
    AuditorFinding,
    EvidenceEvent,
    FailureRecord,
    MultipleTestingAssessment,
    SurpriseRecord,
    TheoryPopulation,
    TheoryState,
    ValidationReview,
)
from .replication_engine import REPLICATION_EVENT_TIME_SUPPORT_POLICY


COUNCIL_REVIEW_PROTOCOL_VERSION = "SRB_COUNCIL_REVIEW_V2"
COUNCIL_REVIEW_MODE = "COMPUTATIONAL_COUNCIL_DOSSIER"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _lifecycle_event(
    at: str, from_status: str, to_status: str, actor: str, reason: str, evidence_refs: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "at": str(at),
        "from": str(from_status),
        "to": str(to_status),
        "actor": str(actor),
        "reason": str(reason),
        "evidence_refs": [str(x) for x in evidence_refs if str(x).strip()],
    }


def _row(value: Any) -> dict[str, Any]:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Expected dataclass or mapping")


def _float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _rw_improvement(run: Mapping[str, Any]) -> float:
    deltas = run.get("deltas_vs_baseline") or {}
    for name, metrics in deltas.items():
        if "random walk" in str(name).lower() or "last observation" in str(name).lower():
            return _float((metrics or {}).get("RMSE_IMPROVEMENT_PCT"), 0.0)
    return 0.0


def _robustness_improvements(run: Mapping[str, Any]) -> dict[str, float]:
    robust = run.get("robustness") or {}
    out: dict[str, float] = {}
    for key, value in robust.items():
        if key == "CHRONOLOGICAL_SPLITS" and isinstance(value, Mapping):
            for split_name, split_value in value.items():
                if isinstance(split_value, Mapping):
                    out[f"CHRONOLOGICAL_{split_name}"] = _float(split_value.get("rmse_improvement_pct"), 0.0)
        elif isinstance(value, Mapping) and "rmse_improvement_pct" in value:
            out[str(key)] = _float(value.get("rmse_improvement_pct"), 0.0)
    return out


def build_multiple_testing_assessment(
    specification: Any,
    run: Any,
    all_runs: Sequence[Mapping[str, Any]] = (),
) -> MultipleTestingAssessment:
    spec = _row(specification)
    rr = _row(run)
    robustness = _robustness_improvements(rr)
    baseline_comparisons = len(rr.get("baseline_metrics") or {})
    related_runs = sum(1 for x in all_runs if str(x.get("experiment_id") or "") == str(rr.get("experiment_id") or ""))
    observed_tests = 1 + len(robustness) + baseline_comparisons + max(0, related_runs - 1)
    selection_risk = "LOW" if observed_tests <= 5 else "MODERATE" if observed_tests <= 15 else "HIGH"
    return MultipleTestingAssessment(
        assessment_id=_stable_id("MTEST", str(rr.get("run_id")), str(observed_tests)),
        created_at=_now_iso(),
        experiment_id=str(spec.get("experiment_id") or rr.get("experiment_id") or ""),
        run_id=str(rr.get("run_id") or ""),
        observed_tests=int(observed_tests),
        robustness_variants=len(robustness),
        baseline_comparisons=baseline_comparisons,
        related_runs=related_runs,
        selection_risk=selection_risk,
        notes=(
            "Phase 5 records the number of screens/variants to expose selection pressure.",
            "No p-values are stored by Phase 4, so FDR/Bonferroni significance claims are not computed or fabricated.",
            "A larger experiment search space requires stronger future confirmation and replication.",
        ),
    )


def _math_auditor(spec: Mapping[str, Any], audit: Mapping[str, Any] | None) -> AuditorFinding:
    rationale: list[str] = []
    blockers: list[str] = []
    requirements: list[str] = []
    score = 45.0
    if str(spec.get("status")) == "READY" and str(spec.get("experimental_family")) != "UNSUPPORTED_RESEARCH_FAMILY":
        score += 20
        rationale.append("Experiment uses an audited built-in scientific executor family.")
    if audit:
        if str(audit.get("mathematical_status")) == "VARIABLE_MAPPING_SUBSTANTIAL":
            score += 15
            rationale.append("Source-variable mapping is substantial.")
        dim = str(audit.get("dimensional_status") or "")
        if dim in {"UNRESOLVED", "USER_DECLARED_REQUIRES_FORMAL_VALIDATION"}:
            score = min(score, 65.0)
            requirements.append("Formal dimensional validation remains unresolved.")
        if str(audit.get("verdict")) != "PARTIAL_TRANSFER":
            blockers.append("Transfer audit is weaker than PARTIAL_TRANSFER.")
    else:
        requirements.append("Transfer audit record is unavailable to the council.")
    status = "PASS" if score >= 75 and not blockers else "CONDITIONAL" if score >= 50 and not blockers else "FAIL"
    return AuditorFinding("MATHEMATICS", status, round(score, 1), tuple(rationale), tuple(blockers), tuple(requirements))


def _stats_auditor(run: Mapping[str, Any], multiple: MultipleTestingAssessment) -> AuditorFinding:
    rationale: list[str] = []
    blockers: list[str] = []
    requirements: list[str] = []
    stage = str(run.get("stage") or "")
    verdict = str(run.get("verdict") or "")
    rw = _rw_improvement(run)
    ntest = int(run.get("test_size") or 0)
    score = 25.0
    if ntest >= 100:
        score += 15
        rationale.append(f"Out-of-sample scoring uses {ntest} test observations.")
    if rw > 0:
        score += min(20.0, rw * 2.0)
        rationale.append(f"Candidate RMSE improvement versus random walk: {rw:.2f}%.")
    else:
        blockers.append("Candidate does not improve RMSE versus random-walk baseline.")
    robust = _robustness_improvements(run)
    if robust:
        positive_share = sum(1 for x in robust.values() if x > 0) / max(1, len(robust))
        score += 15.0 * positive_share
        rationale.append(f"Positive robustness screens: {positive_share:.0%}.")
    if stage == "SYNTHETIC_SANITY":
        score = min(score, 60.0)
        requirements.append("Synthetic same-family data cannot establish inferential or external validity.")
    if stage == "HISTORICAL_OOS" and verdict == "PROMISING_OOS":
        score += 10
    if multiple.selection_risk == "HIGH":
        score -= 15
        requirements.append("High screen multiplicity requires independent confirmation.")
    elif multiple.selection_risk == "MODERATE":
        score -= 5
        requirements.append("Moderate screen multiplicity should be reflected in evidence strength.")
    requirements.append("No p-values/error sequences are stored; formal forecast-comparison significance remains untested.")
    status = "PASS" if score >= 75 and not blockers else "CONDITIONAL" if score >= 45 and not blockers else "FAIL"
    return AuditorFinding("STATISTICS", status, round(max(0.0, min(100.0, score)), 1), tuple(rationale), tuple(blockers), tuple(requirements))


def _finance_auditor(spec: Mapping[str, Any], run: Mapping[str, Any], audit: Mapping[str, Any] | None) -> AuditorFinding:
    stage = str(run.get("stage") or "")
    score = 20.0
    rationale: list[str] = []
    blockers: list[str] = []
    requirements: list[str] = []
    if stage == "SYNTHETIC_SANITY":
        blockers.append("Target-domain market validity is untested; synthetic data only validate implementation.")
        requirements.append("Run a chronologically ordered historical OOS test on an economically justified observable.")
    elif stage == "HISTORICAL_OOS":
        score += 35
        rationale.append("A chronological target-domain OOS run exists.")
        if str(run.get("verdict")) == "PROMISING_OOS":
            score += 20
            rationale.append("Historical OOS run improves on the stored baseline screen.")
        else:
            blockers.append("Historical OOS run did not pass the baseline screen.")
    if audit:
        if str(audit.get("observable_status")) == "INCOMPLETE":
            score = min(score, 55.0)
            requirements.append("Observable mapping remains incomplete in the transfer audit.")
        if str(audit.get("evidence_status")) == "NO_STORED_BRIDGE_EVIDENCE":
            score = min(score, 50.0)
            requirements.append("No stored literature bridge currently supports the cross-domain mapping.")
    requirements.append("Economic meaning of the target state must be defined before any finance-domain conclusion.")
    if stage == "SYNTHETIC_SANITY":
        status = "NOT_TESTED"
    else:
        status = "PASS" if score >= 75 and not blockers else "CONDITIONAL" if score >= 45 and not blockers else "FAIL"
    return AuditorFinding("FINANCE", status, round(score, 1), tuple(rationale), tuple(blockers), tuple(requirements))


def _skeptic_auditor(run: Mapping[str, Any], audit: Mapping[str, Any] | None) -> AuditorFinding:
    rationale: list[str] = []
    blockers: list[str] = []
    requirements: list[str] = []
    score = 65.0
    robust = _robustness_improvements(run)
    structural = robust.get("STRUCTURAL_BREAK")
    non_break = [v for k, v in robust.items() if k != "STRUCTURAL_BREAK"]
    if structural is not None and non_break:
        median_other = statistics.median(non_break)
        rationale.append(f"Median non-break improvement: {median_other:.2f}%; structural-break improvement: {structural:.2f}%.")
        if structural < 1.0 and median_other >= 2.0:
            score -= 25
            blockers.append("Performance nearly disappears under structural break.")
            requirements.append("Test explicit regime changes and non-stationary alternatives before interpreting the signal as persistent.")
    if audit and str(audit.get("evidence_status")) == "NO_STORED_BRIDGE_EVIDENCE":
        score -= 10
        requirements.append("Search for confirming and refuting target-domain literature before strengthening the claim.")
    if str(run.get("stage")) == "SYNTHETIC_SANITY":
        score = min(score, 55.0)
        rationale.append("Same-family synthetic generation creates an intentionally favorable environment.")
    status = "PASS" if score >= 75 and not blockers else "WARNING" if score >= 25 else "FAIL"
    return AuditorFinding("SKEPTIC", status, round(max(0.0, score), 1), tuple(rationale), tuple(blockers), tuple(requirements))


def _replication_auditor(experiment_id: str, plans: Sequence[Mapping[str, Any]]) -> AuditorFinding:
    linked = [p for p in plans if str(p.get("experiment_id") or "") == str(experiment_id)]
    if not linked:
        return AuditorFinding(
            "REPLICATION", "PENDING", 20.0,
            (), (), ("No replication plan is linked to this experiment.",)
        )
    governed_complete = []
    for plan in linked:
        dimensions = plan.get("independence_dimensions") or {}
        independent_axis = (
            any(bool(dimensions.get(key)) for key in ("market", "period", "implementation"))
            if isinstance(dimensions, Mapping) else False
        )
        if (
            str(plan.get("protocol_version") or "") == "SRB_INDEPENDENT_REPLICATION_V1"
            and str(plan.get("execution_status") or "") == "COMPLETE"
            and str(plan.get("independence_gate_status") or "") == "PASS"
            and independent_axis
            and str(plan.get("point_in_time_status") or "") == "PASS"
            and str(plan.get("event_time_support_policy") or "") == REPLICATION_EVENT_TIME_SUPPORT_POLICY
            and bool(plan.get("source_snapshot_fingerprint"))
            and bool(plan.get("execution_fingerprint"))
            and bool(plan.get("replication_outcome"))
            and str(plan.get("production_status") or "") == "RESEARCH_ONLY"
            and plan.get("automatic_promotion_authorized") is False
        ):
            governed_complete.append(plan)
    if governed_complete:
        return AuditorFinding(
            "REPLICATION", "PASS", 85.0,
            (
                f"{len(governed_complete)} governed point-in-time independent replication execution(s) are complete; "
                "the sign of the outcome is not used to award this process pass.",
            ),
            (), (),
        )
    statuses = {str(p.get("status") or "") for p in linked}
    if "REPLICATED" in statuses:
        return AuditorFinding("REPLICATION", "PASS", 85.0, ("A linked replication is marked REPLICATED.",), (), ())
    if "READY_TO_REPLICATE" in statuses:
        return AuditorFinding("REPLICATION", "PENDING", 45.0, ("Replication contract is specified but not completed.",), (), ("Execute and record the replication attempt.",))
    return AuditorFinding("REPLICATION", "PENDING", 30.0, ("A replication plan exists but required inputs remain incomplete.",), (), ("Complete data/code/metric requirements and run replication.",))


def _code_auditor(spec: Mapping[str, Any]) -> AuditorFinding:
    policy = str(spec.get("code_policy") or "")
    family = str(spec.get("experimental_family") or "")
    if policy == "BUILTIN_EXECUTORS_ONLY_NO_EVAL_NO_EXEC" and family != "UNSUPPORTED_RESEARCH_FAMILY":
        return AuditorFinding(
            "CODE", "PASS", 92.0,
            ("Execution is restricted to audited built-in families; arbitrary generated code is not executed.",), (), ()
        )
    return AuditorFinding(
        "CODE", "FAIL", 25.0, (),
        ("Execution policy/family is not eligible for guarded scientific validation.",), ()
    )


def _measurement_auditor(
    run: Mapping[str, Any],
    report: Mapping[str, Any] | None,
) -> AuditorFinding:
    """Audit the frozen competing-measurement evidence without scoring its sign.

    A PASS means that the measurement-dependence protocol is internally eligible for
    Council review. It never means that the tested hypothesis passed.
    """
    if str(run.get("stage") or "") != "HISTORICAL_OOS":
        return AuditorFinding(
            "MEASUREMENT", "NOT_APPLICABLE", 0.0, (), (),
            ("Competing-measurement review becomes mandatory at HISTORICAL_OOS.",),
        )
    if not report:
        return AuditorFinding(
            "MEASUREMENT", "PENDING", 20.0, (), (),
            ("No frozen measurement-robustness report is attached to this historical run.",),
        )

    rationale: list[str] = []
    blockers: list[str] = []
    requirements: list[str] = []
    score = 20.0
    required_passes = {
        "status": "COMPLETE",
        "gate_status": "PASS",
        "common_support_status": "PASS",
        "common_split_status": "PASS",
        "point_in_time_status": "PASS",
        "production_status": "RESEARCH_ONLY",
    }
    for field, expected in required_passes.items():
        observed = str(report.get(field) or "")
        if observed == expected:
            score += 10.0
        else:
            blockers.append(f"Measurement report {field} is {observed or 'MISSING'} instead of {expected}.")
    if str(report.get("experiment_id") or "") == str(run.get("experiment_id") or ""):
        score += 5.0
    else:
        blockers.append("Measurement report is not linked to the reviewed experiment.")
    variant_count = int(_float(report.get("variant_count"), 0.0))
    if variant_count >= 3:
        score += 10.0
        rationale.append(f"{variant_count} predeclared competing measurements share common support and split.")
    else:
        blockers.append("Fewer than three predeclared competing measurements were completed.")

    verdict = str(run.get("verdict") or "")
    conclusion = str(report.get("conclusion") or "")
    if verdict == "NO_OOS_IMPROVEMENT" and conclusion == "CONSISTENT_NO_OOS_IMPROVEMENT":
        score += 5.0
        rationale.append("The robustness report preserves the negative OOS result across all measurements.")
    elif verdict == "PROMISING_OOS" and conclusion in {
        "CONSISTENT_PROMISING_REQUIRES_REVIEW", "MEASUREMENT_DEPENDENT",
    }:
        rationale.append(f"The robustness report records {conclusion}; replication remains mandatory.")
    else:
        blockers.append(
            f"Run verdict {verdict or 'MISSING'} and measurement conclusion {conclusion or 'MISSING'} are inconsistent."
        )
    requirements.append("Shared-source measurement variants do not count as independent replication.")
    status = "PASS" if not blockers else "FAIL"
    return AuditorFinding(
        "MEASUREMENT", status, round(max(0.0, min(100.0, score)), 1),
        tuple(rationale), tuple(blockers), tuple(requirements),
    )


def build_validation_review(
    specification: Any,
    run: Any,
    transfer_audit: Any | None = None,
    replication_plans: Sequence[Mapping[str, Any]] = (),
    all_runs: Sequence[Mapping[str, Any]] = (),
    measurement_report: Any | None = None,
    evidence_refs: Sequence[str] = (),
) -> ValidationReview:
    spec = _row(specification)
    rr = _row(run)
    audit = _row(transfer_audit) if transfer_audit is not None else None
    measurement = _row(measurement_report) if measurement_report is not None else None
    multiple = build_multiple_testing_assessment(spec, rr, all_runs=all_runs)
    if measurement:
        variant_count = int(_float(measurement.get("variant_count"), 0.0))
        observed_tests = max(
            multiple.observed_tests,
            variant_count + multiple.baseline_comparisons + max(0, multiple.related_runs - 1),
        )
        selection_risk = "LOW" if observed_tests <= 5 else "MODERATE" if observed_tests <= 15 else "HIGH"
        multiple = replace(
            multiple,
            observed_tests=observed_tests,
            robustness_variants=max(multiple.robustness_variants, variant_count),
            selection_risk=selection_risk,
            notes=multiple.notes + (
                f"Frozen measurement report contributes {variant_count} predeclared competing measurements to the selection ledger.",
            ),
        )
    measurement_finding = _measurement_auditor(rr, measurement)
    findings = (
        _math_auditor(spec, audit),
        _stats_auditor(rr, multiple),
        _finance_auditor(spec, rr, audit),
        _skeptic_auditor(rr, audit),
        measurement_finding,
        _replication_auditor(str(spec.get("experiment_id") or rr.get("experiment_id") or ""), replication_plans),
        _code_auditor(spec),
    )
    blockers = tuple(dict.fromkeys(b for f in findings for b in f.blockers))
    requirements = tuple(dict.fromkeys(r for f in findings for r in f.requirements))
    stage = str(rr.get("stage") or "")
    verdict = str(rr.get("verdict") or "")
    if verdict in {"IMPLEMENTATION_SANITY_FAIL", "NO_OOS_IMPROVEMENT", "INVALID"}:
        decision = "REVISE_OR_REJECT"
        grade = "FAILED_SCREEN"
        tier = "NEGATIVE_EVIDENCE"
    elif stage == "SYNTHETIC_SANITY" and verdict == "IMPLEMENTATION_SANITY_PASS":
        decision = "ADVANCE_TO_HISTORICAL_OOS_WITH_BLOCKERS" if blockers else "ADVANCE_TO_HISTORICAL_OOS"
        grade = "IMPLEMENTATION_ONLY"
        tier = "SYNTHETIC_ONLY"
    elif stage == "HISTORICAL_OOS" and verdict == "PROMISING_OOS":
        decision = "ADVANCE_TO_REPLICATION_WITH_BLOCKERS" if blockers else "ADVANCE_TO_REPLICATION"
        grade = "OOS_CANDIDATE"
        tier = "PRELIMINARY_TARGET_DOMAIN"
    else:
        decision = "HOLD_RESEARCH"
        grade = "PRELIMINARY"
        tier = "INCOMPLETE"
    if any(f.auditor == "CODE" and f.status == "FAIL" for f in findings):
        decision = "REVISE_OR_REJECT"
        grade = "FAILED_SCREEN"
    if verdict in {"IMPLEMENTATION_SANITY_FAIL", "NO_OOS_IMPROVEMENT", "INVALID"}:
        disposition = "RETAIN_NEGATIVE_RESULT_AND_DO_NOT_ADVANCE_CLAIM"
    elif stage == "HISTORICAL_OOS" and verdict == "PROMISING_OOS":
        disposition = "RETAIN_PRELIMINARY_RESULT_AND_REQUIRE_INDEPENDENT_REPLICATION"
    else:
        disposition = "RETAIN_AS_WORKFLOW_EVIDENCE_ONLY"
    code_ok = any(f.auditor == "CODE" and f.status == "PASS" for f in findings)
    measurement_ok = (
        stage != "HISTORICAL_OOS"
        or measurement_finding.status == "PASS"
    )
    gate_eligibility = (
        "ELIGIBLE_COMPUTATIONAL_REVIEW"
        if code_ok and measurement_ok and str(rr.get("production_status") or "RESEARCH_ONLY") == "RESEARCH_ONLY"
        else "PENDING_EVIDENCE"
    )
    clean_refs = tuple(dict.fromkeys(
        str(value).strip()
        for value in (
            rr.get("run_id"),
            rr.get("attempt_id"),
            rr.get("dataset_manifest_id"),
            rr.get("reproducibility_capsule_id"),
            (measurement or {}).get("protocol_id"),
            (measurement or {}).get("report_id"),
            *evidence_refs,
        )
        if str(value or "").strip()
    ))
    evidence_summary = (
        f"Run stage: {stage}; run verdict: {verdict}.",
        f"Random-walk RMSE improvement: {_rw_improvement(rr):.2f}%.",
        f"Multiple-testing ledger: {multiple.observed_tests} observed screens/comparisons; selection risk {multiple.selection_risk}.",
        f"Council disposition: {disposition}.",
        "This is a transparent computational Council dossier, not a human-panel attestation.",
        "Council decisions are research workflow states, not scientific truth declarations.",
    )
    return ValidationReview(
        review_id=_stable_id(
            "REVIEW", str(rr.get("run_id")), decision, grade,
            COUNCIL_REVIEW_PROTOCOL_VERSION, str((measurement or {}).get("report_id") or ""),
        ),
        created_at=_now_iso(),
        experiment_id=str(spec.get("experiment_id") or rr.get("experiment_id") or ""),
        run_id=str(rr.get("run_id") or ""),
        stage=stage,
        run_verdict=verdict,
        transfer_verdict=str(spec.get("transfer_verdict") or (audit or {}).get("verdict") or ""),
        council_decision=decision,
        scientific_grade=grade,
        evidence_tier=tier,
        auditor_findings=findings,
        multiple_testing=multiple,
        evidence_summary=evidence_summary,
        blockers=blockers,
        requirements=requirements,
        review_protocol_version=COUNCIL_REVIEW_PROTOCOL_VERSION,
        review_mode=COUNCIL_REVIEW_MODE,
        review_authority="SYSTEM_GENERATED_RESEARCH_REVIEW",
        human_attestation_status="NOT_A_HUMAN_PANEL",
        decision_scope="RESEARCH_WORKFLOW_ONLY",
        disposition=disposition,
        measurement_report_id=str((measurement or {}).get("report_id") or ""),
        measurement_protocol_id=str((measurement or {}).get("protocol_id") or ""),
        evidence_refs=clean_refs,
        automatic_promotion_authorized=False,
        gate_eligibility=gate_eligibility,
    )


def derive_failure_records(review: Any, run: Any) -> tuple[FailureRecord, ...]:
    rev = _row(review)
    rr = _row(run)
    now = _now_iso()
    exp = str(rr.get("experiment_id") or rev.get("experiment_id") or "")
    run_id = str(rr.get("run_id") or rev.get("run_id") or "")
    review_id = str(rev.get("review_id") or "")
    out: list[FailureRecord] = []
    verdict = str(rr.get("verdict") or "")
    if verdict == "IMPLEMENTATION_SANITY_FAIL":
        out.append(FailureRecord(
            _stable_id("FAIL", run_id, "IMPLEMENTATION"), now, exp, run_id,
            "IMPLEMENTATION_FAILURE", "HIGH", "OPEN",
            "Built-in implementation sanity screen failed.",
            {"verdict": verdict},
            ("Inspect numerical implementation and parameter recovery before any target-domain test.",),
            status_updated_at=now,
            status_reason="Failure derived from Validation Council evidence.",
            status_evidence_refs=tuple(x for x in (review_id, run_id) if x),
            lifecycle_history=(_lifecycle_event(now, "", "OPEN", "SYSTEM", "Failure derived from Validation Council evidence.", (review_id, run_id)),),
        ))
    if verdict == "NO_OOS_IMPROVEMENT":
        out.append(FailureRecord(
            _stable_id("FAIL", run_id, "OOS"), now, exp, run_id,
            "OOS_FAILURE", "HIGH", "OPEN",
            "Historical OOS candidate failed to improve on the baseline screen.",
            {"rmse_improvement_pct": _rw_improvement(rr)},
            ("Revisit the mapping/model or record the negative result and stop this branch.",),
            status_updated_at=now,
            status_reason="Failure derived from target-domain OOS evidence.",
            status_evidence_refs=tuple(x for x in (review_id, run_id) if x),
            lifecycle_history=(_lifecycle_event(now, "", "OPEN", "SYSTEM", "Failure derived from target-domain OOS evidence.", (review_id, run_id)),),
        ))
    robust = _robustness_improvements(rr)
    structural = robust.get("STRUCTURAL_BREAK")
    non_break = [v for k, v in robust.items() if k != "STRUCTURAL_BREAK"]
    if structural is not None and non_break:
        median_other = statistics.median(non_break)
        if structural < 1.0 and median_other >= 2.0:
            out.append(FailureRecord(
                _stable_id("FAIL", run_id, "STRUCTURAL_BREAK_FRAGILITY"), now, exp, run_id,
                "STRUCTURAL_BREAK_FRAGILITY", "MEDIUM", "OPEN",
                "Performance degrades sharply under a structural-break screen.",
                {"structural_break_improvement_pct": round(structural, 4), "median_non_break_improvement_pct": round(median_other, 4)},
                (
                    "Treat apparent mean reversion as regime-dependent until disproven.",
                    "Run explicit non-stationary/regime-switching alternatives before generalization.",
                ),
                status_updated_at=now,
                status_reason="Robustness screen detected structural-break fragility.",
                status_evidence_refs=tuple(x for x in (review_id, run_id) if x),
                lifecycle_history=(_lifecycle_event(now, "", "OPEN", "SYSTEM", "Robustness screen detected structural-break fragility.", (review_id, run_id)),),
            ))
    return tuple(out)


def derive_surprise_records(run: Any, all_runs: Sequence[Mapping[str, Any]] = ()) -> tuple[SurpriseRecord, ...]:
    rr = _row(run)
    now = _now_iso()
    exp = str(rr.get("experiment_id") or "")
    run_id = str(rr.get("run_id") or "")
    out: list[SurpriseRecord] = []
    robust = _robustness_improvements(rr)
    structural = robust.get("STRUCTURAL_BREAK")
    non_break = [v for k, v in robust.items() if k != "STRUCTURAL_BREAK"]
    if structural is not None and non_break:
        expected = statistics.median(non_break)
        gap = expected - structural
        if gap >= 2.0:
            score = min(100.0, max(0.0, gap * 10.0))
            out.append(SurpriseRecord(
                _stable_id("SURPRISE", run_id, "BREAK_GAP"), now, exp, run_id,
                "ROBUSTNESS_REVERSAL", "NEW",
                f"Expected robustness near the non-break median improvement ({expected:.2f}%).",
                f"Structural-break improvement falls to {structural:.2f}%.",
                round(score, 1),
                "The effect may be conditional on regime stability rather than structurally persistent.",
                {"expected_non_break_median_pct": round(expected, 4), "observed_structural_break_pct": round(structural, 4)},
                status_updated_at=now,
                status_reason="Expectation reversal detected by robustness comparison.",
                status_evidence_refs=(run_id,) if run_id else (),
                lifecycle_history=(_lifecycle_event(now, "", "NEW", "SYSTEM", "Expectation reversal detected by robustness comparison.", (run_id,)),),
            ))
    current_stage = str(rr.get("stage") or "")
    current_verdict = str(rr.get("verdict") or "")
    if current_stage == "HISTORICAL_OOS":
        prior_synthetic = [x for x in all_runs if str(x.get("experiment_id") or "") == exp and str(x.get("stage") or "") == "SYNTHETIC_SANITY"]
        if prior_synthetic:
            synthetic_pass = any(str(x.get("verdict") or "") == "IMPLEMENTATION_SANITY_PASS" for x in prior_synthetic)
            if synthetic_pass and current_verdict == "NO_OOS_IMPROVEMENT":
                out.append(SurpriseRecord(
                    _stable_id("SURPRISE", run_id, "EXTERNAL_VALIDITY"), now, exp, run_id,
                    "EXTERNAL_VALIDITY_REVERSAL", "NEW",
                    "Synthetic implementation screen suggested the model family was numerically viable.",
                    "Historical OOS failed to improve on the random-walk baseline.",
                    90.0,
                    "Implementation validity did not translate into target-domain predictive validity.",
                    {"historical_rmse_improvement_pct": _rw_improvement(rr)},
                    status_updated_at=now,
                    status_reason="Historical OOS contradicted prior synthetic viability.",
                    status_evidence_refs=(run_id,) if run_id else (),
                    lifecycle_history=(_lifecycle_event(now, "", "NEW", "SYSTEM", "Historical OOS contradicted prior synthetic viability.", (run_id,)),),
                ))
    return tuple(out)


def _event(exp: str, run_id: str, event_type: str, direction: str, strength: float, rationale: str) -> EvidenceEvent:
    return EvidenceEvent(
        event_id=_stable_id("EVID", exp, run_id, event_type, direction),
        created_at=_now_iso(), experiment_id=exp, run_id=run_id,
        event_type=event_type, direction=direction, strength=round(float(strength), 4), rationale=rationale,
    )


def build_theory_population(
    specification: Any,
    runs: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]] = (),
    surprises: Sequence[Mapping[str, Any]] = (),
) -> TheoryPopulation:
    spec = _row(specification)
    exp = str(spec.get("experiment_id") or "")
    target = str(spec.get("target_variable") or "mapped_state")
    weights = {
        "GENERALIZES": 0.33,
        "REGIME_DEPENDENT": 0.34,
        "NO_PERSISTENT_EDGE": 0.33,
    }
    support = {k: 0.0 for k in weights}
    challenge = {k: 0.0 for k in weights}
    events: list[EvidenceEvent] = []
    seen_evidence_units: set[str] = set()
    for run in runs:
        if str(run.get("experiment_id") or "") != exp:
            continue
        run_id = str(run.get("run_id") or "")
        stage = str(run.get("stage") or "")
        verdict = str(run.get("verdict") or "")
        contributes_run_evidence = (
            (stage == "SYNTHETIC_SANITY" and verdict == "IMPLEMENTATION_SANITY_PASS")
            or (stage == "HISTORICAL_OOS" and verdict in {"PROMISING_OOS", "NO_OOS_IMPROVEMENT"})
        )
        if not contributes_run_evidence:
            continue
        # Reruns sharing an evidence unit are retained as attempts elsewhere, but
        # must not multiply their epistemic contribution here.  A legacy run has
        # no evidence_unit_id, so run_id preserves the previous one-run-one-unit
        # behavior. Malformed rows without either identifier carry no auditable
        # evidence and are ignored.
        evidence_unit_id = str(run.get("evidence_unit_id") or run_id).strip()
        if not evidence_unit_id or evidence_unit_id in seen_evidence_units:
            continue
        seen_evidence_units.add(evidence_unit_id)
        if stage == "SYNTHETIC_SANITY" and verdict == "IMPLEMENTATION_SANITY_PASS":
            weights["GENERALIZES"] += 0.03; support["GENERALIZES"] += 0.03
            weights["REGIME_DEPENDENT"] += 0.04; support["REGIME_DEPENDENT"] += 0.04
            weights["NO_PERSISTENT_EDGE"] -= 0.02; challenge["NO_PERSISTENT_EDGE"] += 0.02
            events.append(_event(exp, run_id, "SYNTHETIC_PASS", "WEAK_SUPPORT", 0.05, "Implementation works on same-family synthetic data; external evidence remains weak."))
        if stage == "HISTORICAL_OOS" and verdict == "PROMISING_OOS":
            weights["GENERALIZES"] += 0.20; support["GENERALIZES"] += 0.20
            weights["REGIME_DEPENDENT"] += 0.08; support["REGIME_DEPENDENT"] += 0.08
            weights["NO_PERSISTENT_EDGE"] -= 0.15; challenge["NO_PERSISTENT_EDGE"] += 0.15
            events.append(_event(exp, run_id, "HISTORICAL_OOS_PASS", "SUPPORT", 0.25, "Chronological historical OOS improves on the random-walk screen."))
        if stage == "HISTORICAL_OOS" and verdict == "NO_OOS_IMPROVEMENT":
            weights["GENERALIZES"] -= 0.18; challenge["GENERALIZES"] += 0.18
            weights["REGIME_DEPENDENT"] += 0.06; support["REGIME_DEPENDENT"] += 0.06
            weights["NO_PERSISTENT_EDGE"] += 0.20; support["NO_PERSISTENT_EDGE"] += 0.20
            events.append(_event(exp, run_id, "HISTORICAL_OOS_FAIL", "CHALLENGE", 0.30, "Historical OOS does not improve on the random-walk baseline."))
    for row in failures:
        if str(row.get("experiment_id") or "") != exp:
            continue
        if str(row.get("status") or "").upper() == "REJECTED_AS_ARTIFACT":
            continue
        if str(row.get("failure_type")) == "STRUCTURAL_BREAK_FRAGILITY":
            weights["GENERALIZES"] -= 0.08; challenge["GENERALIZES"] += 0.08
            weights["REGIME_DEPENDENT"] += 0.18; support["REGIME_DEPENDENT"] += 0.18
            weights["NO_PERSISTENT_EDGE"] += 0.03; support["NO_PERSISTENT_EDGE"] += 0.03
            events.append(_event(exp, str(row.get("run_id") or ""), "STRUCTURAL_BREAK_FRAGILITY", "SUPPORT_REGIME_DEPENDENCE", 0.22, "Performance nearly disappears under structural break."))
    for row in surprises:
        if str(row.get("experiment_id") or "") != exp:
            continue
        if str(row.get("surprise_type")) == "EXTERNAL_VALIDITY_REVERSAL":
            weights["GENERALIZES"] -= 0.10; challenge["GENERALIZES"] += 0.10
            weights["NO_PERSISTENT_EDGE"] += 0.10; support["NO_PERSISTENT_EDGE"] += 0.10
    clipped = {k: max(0.01, v) for k, v in weights.items()}
    total = sum(clipped.values())
    norm = {k: clipped[k] / total for k in clipped}
    labels = {
        "GENERALIZES": (f"Mapped {target} dynamics generalize out of sample", "The mapped dynamics retain useful target-domain behavior across regimes and samples."),
        "REGIME_DEPENDENT": (f"Mapped {target} dynamics are regime-dependent", "The effect exists only under some structural regimes and degrades under shifts."),
        "NO_PERSISTENT_EDGE": (f"No persistent target-domain improvement for {target}", "Any apparent advantage is implementation/sampling specific or not stable versus simple baselines."),
    }
    theories = []
    event_ids = tuple(e.event_id for e in events)
    for key in ("GENERALIZES", "REGIME_DEPENDENT", "NO_PERSISTENT_EDGE"):
        label, desc = labels[key]
        theories.append(TheoryState(
            theory_id=_stable_id("THEORY", exp, key), label=label, description=desc,
            weight=round(norm[key], 6), support_score=round(support[key], 4), challenge_score=round(challenge[key], 4),
            evidence_event_ids=event_ids,
        ))
    return TheoryPopulation(
        population_id=_stable_id("THEORYPOP", exp), created_at=_now_iso(), experiment_id=exp,
        target_variable=target, theories=tuple(theories), evidence_events=tuple(events),
    )


def validate_and_learn(
    specification: Any,
    run: Any,
    transfer_audit: Any | None = None,
    replication_plans: Sequence[Mapping[str, Any]] = (),
    all_runs: Sequence[Mapping[str, Any]] = (),
    existing_failures: Sequence[Mapping[str, Any]] = (),
    existing_surprises: Sequence[Mapping[str, Any]] = (),
    measurement_report: Any | None = None,
    evidence_refs: Sequence[str] = (),
) -> tuple[ValidationReview, tuple[FailureRecord, ...], tuple[SurpriseRecord, ...], TheoryPopulation]:
    review = build_validation_review(
        specification, run, transfer_audit=transfer_audit,
        replication_plans=replication_plans, all_runs=all_runs,
        measurement_report=measurement_report, evidence_refs=evidence_refs,
    )
    failures = derive_failure_records(review, run)
    surprises = derive_surprise_records(run, all_runs=all_runs)

    existing_failure_by_id = {str(x.get("failure_id") or ""): dict(x) for x in existing_failures if x.get("failure_id")}
    preserved_failures = []
    for item in failures:
        prior = existing_failure_by_id.get(item.failure_id)
        if prior:
            item = replace(
                item,
                status=str(prior.get("status") or item.status),
                status_updated_at=str(prior.get("status_updated_at") or item.status_updated_at),
                status_reason=str(prior.get("status_reason") or item.status_reason),
                status_evidence_refs=tuple(str(x) for x in (prior.get("status_evidence_refs") or item.status_evidence_refs)),
                lifecycle_history=tuple(dict(x) for x in (prior.get("lifecycle_history") or item.lifecycle_history) if isinstance(x, Mapping)),
            )
        preserved_failures.append(item)
    failures = tuple(preserved_failures)

    existing_surprise_by_id = {str(x.get("surprise_id") or ""): dict(x) for x in existing_surprises if x.get("surprise_id")}
    preserved_surprises = []
    for item in surprises:
        prior = existing_surprise_by_id.get(item.surprise_id)
        if prior:
            prior_status = str(prior.get("status") or item.status)
            if prior_status == "OPEN":  # Phase-5.0 legacy surprise state
                prior_status = "NEW"
            item = replace(
                item,
                status=prior_status,
                status_updated_at=str(prior.get("status_updated_at") or item.status_updated_at),
                status_reason=str(prior.get("status_reason") or item.status_reason),
                status_evidence_refs=tuple(str(x) for x in (prior.get("status_evidence_refs") or item.status_evidence_refs)),
                lifecycle_history=tuple(dict(x) for x in (prior.get("lifecycle_history") or item.lifecycle_history) if isinstance(x, Mapping)),
            )
        preserved_surprises.append(item)
    surprises = tuple(preserved_surprises)

    failure_map = dict(existing_failure_by_id)
    for item in failures:
        failure_map[item.failure_id] = asdict(item)
    surprise_map = dict(existing_surprise_by_id)
    for item in surprises:
        surprise_map[item.surprise_id] = asdict(item)
    population = build_theory_population(
        specification, all_runs, failures=list(failure_map.values()), surprises=list(surprise_map.values())
    )
    return review, failures, surprises, population
