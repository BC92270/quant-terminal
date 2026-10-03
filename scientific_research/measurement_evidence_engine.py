from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .phase62_models import (
    EvidenceAssessment,
    EvidenceSynthesis,
    MeasurementDecision,
    MeasurementHypothesis,
    MeasurementModel,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(x or "").strip().lower() for x in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _row(value: Any) -> dict[str, Any]:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return dict(value or {})


def _clean_refs(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(x).strip() for x in (values or ()) if str(x).strip()))


def _measurement_risks(label: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    lower = str(label or "").lower()
    if "detrended" in lower or "trend" in lower:
        return (
            ("trend specification risk", "horizon sensitivity", "structural-break contamination"),
            ("trend window", "trend estimator", "sampling frequency", "break regime"),
        )
    if "volatility" in lower:
        return (
            ("realized-volatility estimator risk", "microstructure noise", "window sensitivity"),
            ("realized-volatility estimator", "aggregation window", "sampling frequency", "volatility regime"),
        )
    if "valuation" in lower or "fundamental" in lower:
        return (
            ("fundamental-data revision risk", "publication lag", "valuation-anchor specification risk"),
            ("fundamental anchor", "reporting lag", "normalization window", "valuation regime"),
        )
    if "factor" in lower:
        return (
            ("factor selection risk", "loading-window sensitivity", "factor instability"),
            ("factor set", "loading window", "regularization", "market regime"),
        )
    if "liquidity" in lower:
        return (
            ("component selection risk", "venue/history inconsistency", "weight instability"),
            ("component set", "standardization window", "weights", "liquidity regime"),
        )
    return (
        ("measurement-model specification risk", "sampling sensitivity"),
        ("transformation", "sampling frequency", "parameterization", "regime"),
    )


def build_measurement_model(
    question: Any,
    observables: Sequence[Any],
    observable_ids: Iterable[str] | None = None,
) -> tuple[MeasurementModel, tuple[MeasurementHypothesis, ...]]:
    q = _row(question)
    requested = set(_clean_refs(observable_ids))
    rows = [_row(x) for x in observables]
    if requested:
        rows = [x for x in rows if str(x.get("observable_id") or "") in requested]
    if len(rows) < 2:
        raise ValueError("Measurement comparison requires at least two explicit observable candidates.")
    qid = str(q.get("question_id") or "")
    target = str(q.get("target_variable") or "market_state")
    exp = str(q.get("experiment_id") or "")
    ids = tuple(sorted(str(x.get("observable_id") or "") for x in rows if str(x.get("observable_id") or "")))
    mid = _stable_id("MMODEL", qid, target, *ids)
    now = _now_iso()
    hypotheses: list[MeasurementHypothesis] = []
    for row in sorted(rows, key=lambda x: str(x.get("observable_id") or "")):
        oid = str(row.get("observable_id") or "")
        label = str(row.get("label") or oid)
        risks, sensitivity = _measurement_risks(label)
        hid = _stable_id("MHYP", mid, oid)
        hypotheses.append(MeasurementHypothesis(
            measurement_hypothesis_id=hid,
            created_at=now,
            measurement_model_id=mid,
            question_id=qid,
            target_concept=target,
            observable_id=oid,
            label=label,
            mathematical_definition=str(row.get("mathematical_definition") or ""),
            unit=str(row.get("unit") or ""),
            frequency=str(row.get("frequency") or ""),
            measurement_error_risks=risks,
            sensitivity_dimensions=sensitivity,
            invariance_tests=(
                "sign/direction consistency across competing observable definitions",
                "relative model ranking consistency across measurement definitions",
                "regime stability of conclusions",
                "hyperparameter sensitivity within each observable definition",
                "data-source / revision sensitivity where applicable",
                "chronology and leakage audit",
            ),
            evidence_refs=_clean_refs(row.get("evidence_refs") or ()),
        ))
    model = MeasurementModel(
        measurement_model_id=mid,
        created_at=now,
        question_id=qid,
        experiment_id=exp,
        target_concept=target,
        observable_ids=ids,
        measurement_hypothesis_ids=tuple(x.measurement_hypothesis_id for x in hypotheses),
        comparison_principles=(
            "No observable is treated as the latent concept itself.",
            "Competing measurements remain active after a primary measurement is chosen.",
            "Target-domain conclusions should be stable across plausible measurements or explicitly reported as measurement-dependent.",
            "All transformations must be causal and preserve chronological information constraints.",
        ),
        required_tests=(
            "cross-observable result consistency",
            "within-observable hyperparameter sensitivity",
            "regime-conditional measurement stability",
            "data-source/revision sensitivity when relevant",
            "measurement-error and leakage audit",
        ),
        warnings=(
            "Measurement-model scores are operational design aids, not evidence that one observable is the true latent state.",
            "Selecting a primary observable is a workflow decision and does not eliminate measurement uncertainty.",
        ),
    )
    return model, tuple(hypotheses)


def build_measurement_decision(
    model: Any,
    selected_observable_id: str,
    rationale: str,
    evidence_refs: Iterable[str] = (),
    actor: str = "HUMAN",
) -> MeasurementDecision:
    row = _row(model)
    oid = str(selected_observable_id or "").strip()
    if oid not in set(str(x) for x in (row.get("observable_ids") or [])):
        raise ValueError("Primary observable must belong to the competing measurement model.")
    clean_reason = str(rationale or "").strip()
    if not clean_reason:
        raise ValueError("Primary measurement selection requires an explicit rationale.")
    did = _stable_id("MDECISION", str(row.get("measurement_model_id") or ""), oid)
    return MeasurementDecision(
        decision_id=did,
        created_at=_now_iso(),
        measurement_model_id=str(row.get("measurement_model_id") or ""),
        question_id=str(row.get("question_id") or ""),
        selected_observable_id=oid,
        rationale=clean_reason,
        evidence_refs=_clean_refs(evidence_refs),
        actor=str(actor or "HUMAN"),
    )


_ALLOWED_RELATIONS = {"SUPPORTS", "CHALLENGES", "CONTEXT_ONLY", "NEUTRAL", "UNRESOLVED"}
_DIRECTIONAL = {"SUPPORTS", "CHALLENGES"}


def build_evidence_assessment(
    evidence: Any,
    hypothesis: Any,
    relation: str,
    strength: float,
    rationale: str,
    claim_refs: Iterable[str] = (),
    assessor: str = "HUMAN",
) -> EvidenceAssessment:
    ev = _row(evidence)
    hyp = _row(hypothesis)
    rel = str(relation or "").strip().upper()
    if rel not in _ALLOWED_RELATIONS:
        raise ValueError(f"Unsupported evidence relation: {rel}")
    clean_reason = str(rationale or "").strip()
    if not clean_reason:
        raise ValueError("Evidence assessment requires an explicit rationale.")
    strength = float(strength)
    if not 0.0 <= strength <= 100.0:
        raise ValueError("Evidence strength must be between 0 and 100.")
    available_claims = set(str(x) for x in (ev.get("claim_ids") or []) if str(x))
    refs = _clean_refs(claim_refs)
    if rel in _DIRECTIONAL:
        if not refs:
            raise ValueError("Directional SUPPORTS/CHALLENGES assessments require at least one grounded claim reference.")
        if not set(refs).issubset(available_claims):
            raise ValueError("Assessment claim refs must belong to the grounded evidence record.")
    if "metadata" in str(ev.get("source_level") or "").lower():
        raise ValueError("Evidence assessment requires source-grounded compiled evidence; metadata-only records are not assessable.")
    if not str(ev.get("understanding_id") or "").strip():
        raise ValueError("Evidence assessment requires a persisted scientific understanding reference.")
    scientific_content = (
        tuple(ev.get("claim_ids") or ()),
        tuple(ev.get("mechanism_keys") or ()),
        tuple(ev.get("semantic_entity_ids") or ()),
    )
    if not any(scientific_content):
        raise ValueError(
            "Evidence extraction is empty. Recompile and verify source-grounded claims, mechanisms or entities before assessment."
        )
    if str(ev.get("status") or "GROUNDED_REVIEWED") != "GROUNDED_REVIEWED":
        raise ValueError("Only active GROUNDED_REVIEWED evidence may be assessed.")
    qid = str(ev.get("question_id") or "")
    if qid and str(hyp.get("question_id") or "") and qid != str(hyp.get("question_id") or ""):
        raise ValueError("Evidence and hypothesis must belong to the same research question.")
    aid = _stable_id("EASSESS", str(ev.get("evidence_id") or ""), str(hyp.get("hypothesis_id") or ""))
    return EvidenceAssessment(
        assessment_id=aid,
        created_at=_now_iso(),
        question_id=qid or str(hyp.get("question_id") or ""),
        evidence_id=str(ev.get("evidence_id") or ""),
        hypothesis_id=str(hyp.get("hypothesis_id") or ""),
        relation=rel,
        strength=round(strength, 4),
        rationale=clean_reason,
        claim_refs=refs,
        assessor=str(assessor or "HUMAN"),
    )


def build_evidence_synthesis(
    question_id: str,
    hypotheses: Sequence[Any],
    assessments: Sequence[Any],
) -> EvidenceSynthesis:
    qid = str(question_id or "").strip()
    hyps = [_row(x) for x in hypotheses if str(_row(x).get("question_id") or "") == qid]
    rows = [_row(x) for x in assessments if str(_row(x).get("question_id") or "") == qid]
    hyp_map = {str(x.get("hypothesis_id") or ""): x for x in hyps}
    summaries: list[dict[str, Any]] = []
    support_count = challenge_count = context_count = neutral_count = conflict_count = 0
    for hid, hyp in hyp_map.items():
        related = [x for x in rows if str(x.get("hypothesis_id") or "") == hid]
        supports = [x for x in related if x.get("relation") == "SUPPORTS"]
        challenges = [x for x in related if x.get("relation") == "CHALLENGES"]
        contexts = [x for x in related if x.get("relation") == "CONTEXT_ONLY"]
        neutrals = [x for x in related if x.get("relation") in {"NEUTRAL", "UNRESOLVED"}]
        support_count += len(supports)
        challenge_count += len(challenges)
        context_count += len(contexts)
        neutral_count += len(neutrals)
        if supports and challenges:
            conflict_count += 1
        support_strength = sum(float(x.get("strength") or 0.0) for x in supports)
        challenge_strength = sum(float(x.get("strength") or 0.0) for x in challenges)
        directional_total = support_strength + challenge_strength
        net_direction = 0.0 if directional_total <= 0 else (support_strength - challenge_strength) / directional_total
        summaries.append({
            "hypothesis_id": hid,
            "label": str(hyp.get("label") or hid),
            "assessments": len(related),
            "support_count": len(supports),
            "challenge_count": len(challenges),
            "context_count": len(contexts),
            "neutral_count": len(neutrals),
            "support_strength": round(support_strength, 4),
            "challenge_strength": round(challenge_strength, 4),
            "net_direction_score": round(net_direction, 6),
            "conflicted": bool(supports and challenges),
        })
    if not rows:
        conclusion = "INSUFFICIENT_EVIDENCE"
    elif conflict_count:
        conclusion = "MIXED_EVIDENCE"
    elif support_count + challenge_count == 0:
        conclusion = "NON_DIRECTIONAL_EVIDENCE"
    else:
        conclusion = "DIRECTIONAL_BUT_UNVALIDATED"
    assessed_evidence = {str(x.get("evidence_id") or "") for x in rows if str(x.get("evidence_id") or "")}
    sid = _stable_id("ESYNTH", qid, *sorted(str(x.get("assessment_id") or "") for x in rows))
    required = [
        "Validate source quality, scope and replication status before using synthesis to alter theory weights.",
        "Seek both confirming and refuting evidence for the leading and null hypotheses.",
        "Report measurement-model dependence separately from theory evidence.",
    ]
    if conflict_count:
        required.append("Resolve conflicting directional evidence through scope analysis or targeted replication.")
    if len(assessed_evidence) < 2:
        required.append("Add at least one independent grounded evidence source before strengthening a scientific claim.")
    return EvidenceSynthesis(
        synthesis_id=sid,
        created_at=_now_iso(),
        question_id=qid,
        assessment_ids=tuple(sorted(str(x.get("assessment_id") or "") for x in rows if str(x.get("assessment_id") or ""))),
        hypothesis_summaries=tuple(summaries),
        assessed_evidence_count=len(assessed_evidence),
        support_count=support_count,
        challenge_count=challenge_count,
        context_count=context_count,
        neutral_count=neutral_count,
        conflict_count=conflict_count,
        conclusion=conclusion,
        required_next_evidence=tuple(required),
        belief_update_authorized=False,
    )
