from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .phase61_models import (
    BudgetLedger,
    EvidencePromotion,
    GroundedEvidenceRecord,
    ObservableCandidate,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(x or "").strip().lower() for x in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def _row(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return dict(value)


def _score(observability: float, interpretability: float, leakage_risk: float, feasibility: float) -> float:
    # Leakage risk is a penalty: higher means worse.
    total = 0.30 * observability + 0.30 * interpretability + 0.20 * feasibility + 0.20 * (100.0 - leakage_risk)
    return round(max(0.0, min(100.0, total)), 1)


def generate_observable_candidates(question: Any, experiment_id: str = "") -> tuple[ObservableCandidate, ...]:
    """Generate explicit *candidate* observables; never silently selects one.

    The library is deterministic and intentionally conservative. Mathematical definitions are
    specifications, not executable code, and all candidates remain RESEARCH_ONLY until a human
    or later audited agent explicitly selects one.
    """
    q = _row(question)
    qid = str(q.get("question_id") or "")
    target = str(q.get("target_variable") or "market_state").strip() or "market_state"
    exp = str(experiment_id or q.get("experiment_id") or "")
    now = _now_iso()

    if target == "market_state":
        specs = [
            {
                "label": "Causal detrended log-price residual",
                "economic": "Deviation of log price from a one-sided, causally estimated local trend; interpretable as a temporary displacement from a slowly moving price state.",
                "definition": "x_t = log(P_t) - trend_t, with trend_t estimated using information available at or before t only",
                "unit": "log-price residual (dimensionless)",
                "frequency": "daily_or_weekly",
                "columns": ("price",),
                "steps": ("sort chronologically", "take log price", "estimate one-sided/expanding or rolling causal trend", "subtract causal trend"),
                "rationale": ("Directly operationalizes a mean-reverting deviation without using future observations.", "Requires only price data and has an explicit leakage guard."),
                "limitations": ("Results depend on trend specification and horizon.", "A price residual is not automatically a fundamental mispricing measure."),
                "obs": 96.0, "interp": 78.0, "leak": 24.0, "feas": 98.0,
            },
            {
                "label": "Price-to-fundamental log residual",
                "economic": "Deviation of market price from an explicitly chosen fundamental anchor such as earnings, book value, cash flow or another economically justified slow-moving reference.",
                "definition": "x_t = log(P_t) - log(F_t), where F_t is a declared fundamental anchor aligned without look-ahead",
                "unit": "log valuation residual (dimensionless)",
                "frequency": "daily_to_monthly",
                "columns": ("price", "fundamental_anchor"),
                "steps": ("align release dates causally", "forward-fill only after public release", "take log ratio/residual"),
                "rationale": ("Offers a clearer economic equilibrium interpretation than price detrending.",),
                "limitations": ("Fundamental anchors are model choices and may be non-stationary.", "Publication lags and revisions must be timestamped to prevent leakage."),
                "obs": 72.0, "interp": 94.0, "leak": 48.0, "feas": 68.0,
            },
            {
                "label": "Causal valuation z-score",
                "economic": "Standardized deviation of a declared valuation metric from its own expanding or rolling historical distribution.",
                "definition": "x_t = (V_t - mean_{<=t-1}(V)) / std_{<=t-1}(V), using a causal window",
                "unit": "z-score (dimensionless)",
                "frequency": "daily_to_monthly",
                "columns": ("valuation_metric",),
                "steps": ("timestamp valuation metric", "compute causal expanding/rolling mean and volatility", "standardize"),
                "rationale": ("Dimensionless state facilitates cross-period comparison while retaining an economic valuation interpretation.",),
                "limitations": ("Sensitive to the selected valuation metric and window.", "Structural shifts in valuation regimes can invalidate a stationary z-score."),
                "obs": 82.0, "interp": 90.0, "leak": 32.0, "feas": 78.0,
            },
            {
                "label": "Liquidity stress composite",
                "economic": "Composite state summarizing market illiquidity using causally standardized bid-ask, price-impact, turnover or spread measures.",
                "definition": "x_t = weighted causal z-scores of declared liquidity measures; weights fixed ex ante or estimated on training data only",
                "unit": "composite stress score (dimensionless)",
                "frequency": "daily",
                "columns": ("liquidity_measure_1", "liquidity_measure_2"),
                "steps": ("define components", "causally standardize each component", "combine using fixed/train-only weights"),
                "rationale": ("Directly targets a state that can change around market breaks and may explain regime-dependent mean reversion.",),
                "limitations": ("Composite construction introduces specification risk.", "Microstructure fields can differ across venues and history."),
                "obs": 70.0, "interp": 88.0, "leak": 38.0, "feas": 62.0,
            },
            {
                "label": "Realized-volatility deviation",
                "economic": "Deviation of realized volatility from a causal slow-moving baseline, representing volatility-state displacement rather than price displacement.",
                "definition": "x_t = log(RV_t) - causal_baseline_t(log(RV))",
                "unit": "log-volatility residual",
                "frequency": "daily_or_weekly",
                "columns": ("realized_volatility",),
                "steps": ("construct realized volatility from available data", "take log", "subtract causal baseline"),
                "rationale": ("Observable is naturally linked to regime changes and stochastic state dynamics.",),
                "limitations": ("Changes the economic target from price/valuation state to volatility state.", "Realized-volatility estimator choice matters."),
                "obs": 92.0, "interp": 76.0, "leak": 24.0, "feas": 90.0,
            },
            {
                "label": "Train-only factor residual state",
                "economic": "Residual state after removing exposures to explicitly declared systematic factors estimated on training information only.",
                "definition": "x_t = y_t - beta_t' f_t, with beta estimated causally/train-only",
                "unit": "depends on y_t (typically return/residual units)",
                "frequency": "daily_or_weekly",
                "columns": ("target_series", "factor_1"),
                "steps": ("declare factors", "estimate loadings using train/causal window only", "compute residual"),
                "rationale": ("Tests whether mean reversion exists after removing broad systematic variation.",),
                "limitations": ("Factor selection changes the meaning of the state.", "Return residuals are not equivalent to a level-state unless explicitly accumulated/defined."),
                "obs": 88.0, "interp": 72.0, "leak": 34.0, "feas": 84.0,
            },
        ]
    else:
        specs = [{
            "label": f"Causal standardized deviation of {target}",
            "economic": f"Deviation of the declared {target} observable from a causal historical reference state.",
            "definition": f"x_t = ({target}_t - causal_mean_t) / causal_scale_t",
            "unit": "standardized units",
            "frequency": "user_declared",
            "columns": (target,),
            "steps": ("declare the raw observable", "preserve chronology", "estimate reference state using past information only", "standardize"),
            "rationale": ("Provides a generic, falsifiable state definition while preserving the user's declared economic variable.",),
            "limitations": ("Economic validity depends entirely on the declared raw observable.",),
            "obs": 75.0, "interp": 70.0, "leak": 30.0, "feas": 75.0,
        }]

    out: list[ObservableCandidate] = []
    for spec in specs:
        total = _score(spec["obs"], spec["interp"], spec["leak"], spec["feas"])
        oid = _stable_id("OBS", qid, target, spec["label"], spec["definition"])
        out.append(ObservableCandidate(
            observable_id=oid,
            created_at=now,
            question_id=qid,
            experiment_id=exp,
            target_concept=target,
            label=spec["label"],
            economic_interpretation=spec["economic"],
            mathematical_definition=spec["definition"],
            unit=spec["unit"],
            frequency=spec["frequency"],
            required_columns=tuple(spec["columns"]),
            transformation_steps=tuple(spec["steps"]),
            rationale=tuple(spec["rationale"]),
            limitations=tuple(spec["limitations"]),
            observability_score=float(spec["obs"]),
            economic_interpretability_score=float(spec["interp"]),
            leakage_risk_score=float(spec["leak"]),
            data_feasibility_score=float(spec["feas"]),
            total_score=total,
        ))
    return tuple(sorted(out, key=lambda x: x.total_score, reverse=True))


def build_evidence_promotion(
    scout: Any,
    result: Mapping[str, Any],
    review_reason: str,
) -> EvidencePromotion:
    scout_row = _row(scout)
    title = str(result.get("title") or "").strip()
    paper_id = str(result.get("paper_id") or "").strip()
    if not paper_id or not title:
        raise ValueError("Scout result must contain a paper_id and title before promotion.")
    reason = str(review_reason or "").strip()
    if not reason:
        raise ValueError("Promotion requires an explicit review reason.")
    access = str(result.get("access_level") or "metadata_only")
    status = "PROMOTED_FOR_REVIEW" if str(result.get("abstract") or "").strip() else "NEEDS_SOURCE_TEXT"
    pid = _stable_id("PROMO", str(scout_row.get("scout_id") or ""), paper_id)
    warnings = [
        "Promotion is a routing decision, not scientific support for the hypothesis.",
        "The promoted paper cannot update beliefs until source-grounded compilation and explicit evidence assessment occur.",
    ]
    if status == "NEEDS_SOURCE_TEXT":
        warnings.append("Only metadata is available; claims/equations must not be inferred until source text is supplied.")
    return EvidencePromotion(
        promotion_id=pid,
        created_at=_now_iso(),
        scout_id=str(scout_row.get("scout_id") or ""),
        task_id=str(scout_row.get("task_id") or ""),
        question_id=str(scout_row.get("question_id") or ""),
        paper_id=paper_id,
        title=title,
        doi=str(result.get("doi") or ""),
        access_level=access,
        status=status,
        review_reason=reason,
        warnings=tuple(warnings),
    )


def build_grounded_evidence_record(
    promotion: Any,
    understanding: Any,
    source_level: str,
) -> GroundedEvidenceRecord:
    promo = _row(promotion)
    bundle = _row(understanding)
    if not str(bundle.get("understanding_id") or ""):
        raise ValueError("Grounded evidence requires a persisted scientific understanding bundle.")
    claims = tuple(
        str(x.get("claim_id") or "")
        for x in (bundle.get("claims") or [])
        if isinstance(x, Mapping) and str(x.get("claim_id") or "")
    )
    entities = tuple(
        str(x.get("entity_id") or "")
        for x in (bundle.get("semantic_entities") or [])
        if isinstance(x, Mapping) and str(x.get("entity_id") or "")
    )
    mechanism_map = bundle.get("mechanisms") or {}
    if mechanism_map:
        mechanisms = tuple(sorted(str(k) for k in mechanism_map.keys() if str(k).strip()))
    else:
        # Legacy fallback for bundles created before explicit mechanism maps were persisted.
        mechanisms = tuple(sorted(str(k) for k in (bundle.get("mechanism_families") or {}).keys() if str(k).strip()))
    eid = _stable_id("EVIDENCE", str(promo.get("question_id") or ""), str(promo.get("paper_id") or ""), str(bundle.get("understanding_id") or ""))
    extraction_has_content = bool(claims or mechanisms or entities)
    notes = [
        "Grounded evidence is relevant but its support/refutation direction is intentionally unassessed in Phase 6.1.",
        "Belief weights are not updated automatically by evidence promotion.",
    ]
    if not extraction_has_content:
        notes.append("Source compilation produced no grounded scientific structure; this record cannot satisfy an evidence gate or be assessed.")
    return GroundedEvidenceRecord(
        evidence_id=eid,
        created_at=_now_iso(),
        question_id=str(promo.get("question_id") or ""),
        scout_id=str(promo.get("scout_id") or ""),
        task_id=str(promo.get("task_id") or ""),
        promotion_id=str(promo.get("promotion_id") or ""),
        paper_id=str(promo.get("paper_id") or ""),
        understanding_id=str(bundle.get("understanding_id") or ""),
        title=str(promo.get("title") or ""),
        doi=str(promo.get("doi") or ""),
        source_level=str(source_level or "UNKNOWN"),
        claim_ids=claims,
        mechanism_keys=mechanisms,
        semantic_entity_ids=entities,
        status="GROUNDED_REVIEWED" if extraction_has_content else "INCOMPLETE_EXTRACTION",
        notes=tuple(notes),
    )


def build_budget_ledger(
    plan: Any,
    used_literature_queries: int = 0,
    used_hypotheses: int = 0,
    used_tasks: int = 0,
    used_experiment_proposals: int = 0,
    used_cycles: int = 0,
    used_compute_units: float = 0.0,
    reconciled: bool = False,
) -> BudgetLedger:
    row = _row(plan)
    budget = dict(row.get("budget") or {})
    plan_id = str(row.get("plan_id") or "")
    ledger_id = _stable_id("BUDGET", plan_id)
    return BudgetLedger(
        ledger_id=ledger_id,
        created_at=_now_iso(),
        plan_id=plan_id,
        question_id=str(row.get("question_id") or ""),
        max_literature_queries=int(budget.get("max_literature_queries") or 0),
        used_literature_queries=max(0, int(used_literature_queries)),
        max_hypotheses=int(budget.get("max_hypotheses") or 0),
        used_hypotheses=max(0, int(used_hypotheses)),
        max_tasks=int(budget.get("max_tasks") or 0),
        used_tasks=max(0, int(used_tasks)),
        max_experiment_proposals=int(budget.get("max_experiment_proposals") or 0),
        used_experiment_proposals=max(0, int(used_experiment_proposals)),
        max_cycles=int(budget.get("max_cycles") or 0),
        used_cycles=max(0, int(used_cycles)),
        max_compute_units=float(budget.get("max_compute_units") or 0.0),
        used_compute_units=max(0.0, float(used_compute_units)),
        reconciled_from_persisted_state=bool(reconciled),
    )
