from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .phase6_models import (
    DirectorCycle,
    LiteratureScoutRecord,
    OpenResearchQuestion,
    ResearchBudget,
    ResearchDiaryEntry,
    ResearchHypothesis,
    ResearchPlan,
    ResearchTask,
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


def _target_for_experiment(experiment_id: str, theory_populations: Sequence[Mapping[str, Any]]) -> str:
    for pop in theory_populations:
        if str(pop.get("experiment_id") or "") == str(experiment_id):
            return str(pop.get("target_variable") or "market_state")
    return "market_state"


def _leading_theory(experiment_id: str, theory_populations: Sequence[Mapping[str, Any]]) -> tuple[str, float]:
    for pop in theory_populations:
        if str(pop.get("experiment_id") or "") != str(experiment_id):
            continue
        theories = list(pop.get("theories") or [])
        if theories:
            lead = max(theories, key=lambda x: float(x.get("weight") or 0.0))
            return str(lead.get("label") or ""), float(lead.get("weight") or 0.0)
    return "", 0.0


def _priority(
    uncertainty: float,
    information_gain: float,
    novelty: float,
    impact: float,
    feasibility: float,
    cost: float,
) -> float:
    score = (
        0.22 * uncertainty
        + 0.24 * information_gain
        + 0.12 * novelty
        + 0.18 * impact
        + 0.16 * feasibility
        + 0.08 * (100.0 - cost)
    )
    return round(max(0.0, min(100.0, score)), 1)


def derive_open_questions(
    failures: Sequence[Mapping[str, Any]] = (),
    surprises: Sequence[Mapping[str, Any]] = (),
    theory_populations: Sequence[Mapping[str, Any]] = (),
    gaps: Sequence[Mapping[str, Any]] = (),
    validation_reviews: Sequence[Mapping[str, Any]] = (),
) -> tuple[OpenResearchQuestion, ...]:
    """Turn unresolved scientific debt into deduplicated, falsifiable research questions.

    Phase 6 does not mark these questions answered. It only exposes unresolved scientific debt.
    """
    now = _now_iso()
    review_by_exp = {str(x.get("experiment_id") or ""): x for x in validation_reviews}
    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    for failure in failures:
        status = str(failure.get("status") or "OPEN").upper()
        if status in {"RESOLVED", "REJECTED_AS_ARTIFACT"}:
            continue
        exp = str(failure.get("experiment_id") or "")
        target = _target_for_experiment(exp, theory_populations)
        ftype = str(failure.get("failure_type") or "UNRESOLVED_FAILURE")
        key = (exp, "STRUCTURAL_BREAK" if ftype == "STRUCTURAL_BREAK_FRAGILITY" else ftype)
        bucket = grouped.setdefault(key, {"exp": exp, "target": target, "refs": [], "types": [], "signals": []})
        bucket["refs"].append(str(failure.get("failure_id") or ""))
        bucket["types"].append(ftype)
        bucket["signals"].append(str(failure.get("signal") or ""))

    for surprise in surprises:
        status = str(surprise.get("status") or "NEW").upper()
        if status == "EXPLAINED":
            continue
        exp = str(surprise.get("experiment_id") or "")
        target = _target_for_experiment(exp, theory_populations)
        stype = str(surprise.get("surprise_type") or "UNRESOLVED_SURPRISE")
        family = "STRUCTURAL_BREAK" if stype == "ROBUSTNESS_REVERSAL" else stype
        key = (exp, family)
        bucket = grouped.setdefault(key, {"exp": exp, "target": target, "refs": [], "types": [], "signals": []})
        bucket["refs"].append(str(surprise.get("surprise_id") or ""))
        bucket["types"].append(stype)
        bucket["signals"].append(str(surprise.get("implication") or surprise.get("observed") or ""))

    questions: list[OpenResearchQuestion] = []
    for (exp, family), item in grouped.items():
        target = str(item.get("target") or "market_state")
        lead_label, lead_weight = _leading_theory(exp, theory_populations)
        review = review_by_exp.get(exp) or {}
        review_reqs = tuple(str(x) for x in (review.get("requirements") or []) if str(x).strip())
        review_blockers = tuple(str(x) for x in (review.get("blockers") or []) if str(x).strip())
        refs = tuple(dict.fromkeys(x for x in item.get("refs", []) if x))

        if family == "STRUCTURAL_BREAK":
            title = f"Explain structural-break fragility in {target}"
            question = (
                f"Why does the mapped {target} mean-reverting dynamic lose predictive advantage under structural breaks, "
                "and which non-stationary alternative best explains the reversal?"
            )
            queries = (
                f"regime switching Ornstein Uhlenbeck structural breaks {target} finance",
                f"time varying mean reversion kappa stochastic process structural breaks {target}",
                f"change point Ornstein Uhlenbeck nonstationary financial markets {target}",
                "jump diffusion mean reversion regime switching finance",
            )
            uncertainty, info_gain, novelty, impact, feasibility, cost = 92.0, 94.0, 66.0, 86.0, 88.0, 36.0
            rationale = [
                "An unresolved robustness failure and expectation reversal point to non-stationarity.",
                "The highest-value next test is discriminating stable mean reversion from regime-dependent alternatives.",
            ]
            if lead_label:
                rationale.append(f"Current leading theory: {lead_label} (relative weight {lead_weight:.3f}).")
        else:
            title = f"Resolve {family.replace('_', ' ').lower()} for {target}"
            question = f"What mechanism explains the unresolved {family.replace('_', ' ').lower()} observed for {target}, and what evidence would falsify that explanation?"
            queries = (
                f"{family.replace('_', ' ')} {target} finance",
                f"{family.replace('_', ' ')} stochastic processes",
            )
            uncertainty, info_gain, novelty, impact, feasibility, cost = 85.0, 82.0, 58.0, 72.0, 74.0, 44.0
            rationale = ["Phase-5 memory contains unresolved scientific debt that should remain active until explained or rejected."]

        blockers = tuple(dict.fromkeys(
            list(review_blockers)
            + list(review_reqs)
            + (["Define an economically justified observable for the target state before target-domain inference."] if target == "market_state" else [])
        ))
        score = _priority(uncertainty, info_gain, novelty, impact, feasibility, cost)
        qid = _stable_id("QUESTION", exp, family, target)
        questions.append(OpenResearchQuestion(
            question_id=qid,
            created_at=now,
            title=title,
            question=question,
            origin_type="FAILURE_SURPRISE_SYNTHESIS" if len(refs) > 1 else "SCIENTIFIC_DEBT",
            origin_refs=refs,
            experiment_id=exp,
            target_variable=target,
            priority_score=score,
            uncertainty_score=uncertainty,
            information_gain_score=info_gain,
            novelty_score=novelty,
            impact_score=impact,
            feasibility_score=feasibility,
            cost_score=cost,
            rationale=tuple(rationale),
            blockers=blockers,
            literature_queries=queries,
            lifecycle_history=({
                "at": now,
                "from": "",
                "to": "OPEN",
                "actor": "RESEARCH_DIRECTOR",
                "reason": "Unresolved Phase-5 scientific debt converted into a falsifiable research question.",
                "evidence_refs": list(refs),
            },),
        ))

    # Stored knowledge gaps are separate questions only when they are not already covered by an experiment-debt question.
    for gap in gaps:
        gap_id = str(gap.get("gap_id") or "")
        mechanism = str(gap.get("mechanism") or gap.get("label") or "unknown mechanism")
        target_domain = str(gap.get("target_domain") or "Finance")
        qid = _stable_id("QUESTION", gap_id, mechanism, target_domain)
        questions.append(OpenResearchQuestion(
            question_id=qid,
            created_at=now,
            title=f"Verify stored-knowledge gap: {mechanism} → {target_domain}",
            question=(
                f"Does current external literature support, refute, or leave genuinely open the transfer of {mechanism} into {target_domain}?"
            ),
            origin_type="KNOWLEDGE_GAP",
            origin_refs=(gap_id,) if gap_id else (),
            target_variable="",
            priority_score=_priority(72, 78, 84, 62, 90, 22),
            uncertainty_score=72,
            information_gain_score=78,
            novelty_score=84,
            impact_score=62,
            feasibility_score=90,
            cost_score=22,
            rationale=("A stored-memory gap is not a world-literature novelty claim; external literature search is required.",),
            blockers=("World-literature novelty is unresolved until external search is performed.",),
            literature_queries=(f"{mechanism} {target_domain}", f"{mechanism} financial markets"),
            lifecycle_history=({
                "at": now, "from": "", "to": "OPEN", "actor": "RESEARCH_DIRECTOR",
                "reason": "Stored knowledge gap promoted to an explicit verification question.", "evidence_refs": [gap_id] if gap_id else [],
            },),
        ))

    # Deduplicate by stable question ID and sort by research priority.
    index = {q.question_id: q for q in questions}
    return tuple(sorted(index.values(), key=lambda q: q.priority_score, reverse=True))


def generate_hypotheses(question: Any, max_hypotheses: int = 6) -> tuple[ResearchHypothesis, ...]:
    q = _row(question)
    now = _now_iso()
    qid = str(q.get("question_id") or "")
    target = str(q.get("target_variable") or "market_state")
    title = str(q.get("title") or "").lower()

    if "structural-break" in title or "structural break" in str(q.get("question") or "").lower():
        templates = [
            (
                "Regime-switching OU",
                f"{target} follows locally mean-reverting dynamics, but kappa/sigma switch across latent regimes.",
                "REGIME_SWITCHING_STOCHASTIC",
                ("Conditioning on regimes should restore OOS improvement during stable segments.", "Estimated transition states should align with break periods more than chance."),
                ("Reject if regime conditioning does not improve chronological OOS performance over standard OU and random walk.",),
                ("Historical target observable", "Regime labels or latent-state estimation", "Chronological OOS errors"),
                91.0,
            ),
            (
                "Time-varying kappa",
                f"The restoring force for {target} is continuous but non-stationary; mean-reversion speed changes through time.",
                "TIME_VARYING_PARAMETER",
                ("Rolling estimates of kappa should vary materially around structural breaks.", "Adaptive kappa should outperform fixed-kappa OU OOS if the mechanism is real."),
                ("Reject if time-varying kappa is unstable noise or gives no incremental OOS value." ,),
                ("Historical observable", "Rolling/recursive parameter path", "Fixed-parameter baseline"),
                86.0,
            ),
            (
                "Change-point-conditioned OU",
                f"{target} is approximately OU only within stationary segments separated by discrete change points.",
                "CHANGE_POINT",
                ("Detected change points should precede or coincide with degradation of the fixed OU residual structure.",),
                ("Reject if segmentation does not improve OOS calibration/forecast loss after accounting for extra flexibility.",),
                ("Change-point method", "Penalized model selection", "OOS loss sequence"),
                84.0,
            ),
            (
                "Jump-diffusion mean reversion",
                f"Structural breaks in {target} are better represented as discontinuous jumps superimposed on a mean-reverting diffusion.",
                "JUMP_DIFFUSION",
                ("Large residual discontinuities should cluster near structural-break episodes.",),
                ("Reject if jumps do not explain break-period residuals or OOS loss relative to simpler models." ,),
                ("High-frequency or sufficiently dense historical observable", "Jump diagnostics", "OOS baseline"),
                72.0,
            ),
            (
                "Nonlinear restoring force",
                f"Mean reversion in {target} is state-dependent and nonlinear rather than proportional to displacement.",
                "NONLINEAR_DYNAMICS",
                ("Restoring strength should vary systematically with state magnitude or regime.",),
                ("Reject if nonlinear drift terms do not survive OOS and complexity penalties." ,),
                ("Historical state observable", "Nonlinear drift estimator", "Complexity-adjusted comparison"),
                68.0,
            ),
            (
                "No stable mean-reversion mechanism",
                f"The apparent mean reversion in {target} is a sample/regime artifact and no persistent target-domain OU-like mechanism exists.",
                "NULL_ALTERNATIVE",
                ("Historical OOS should fail to improve consistently once regime changes and selection pressure are respected.",),
                ("Challenge this null only with replicated OOS evidence across independent periods/markets." ,),
                ("Independent OOS periods", "Multiple-testing ledger", "Replication evidence"),
                88.0,
            ),
        ]
    else:
        templates = [
            (
                "Direct mechanism transfer",
                "The source-domain mechanism preserves enough structure to yield measurable target-domain predictions.",
                "DIRECT_TRANSFER",
                ("A mapped observable should produce falsifiable predictions beyond simple baselines.",),
                ("Reject if no measurable observable or no OOS improvement can be demonstrated." ,),
                ("Source literature", "Target observable", "Baseline comparison"),
                70.0,
            ),
            (
                "Null / analogy-only",
                "The apparent cross-domain similarity is descriptive and has no reusable target-domain mechanism.",
                "NULL_ALTERNATIVE",
                ("Transfer screens should fail once units, observability, causality and OOS evidence are enforced.",),
                ("Challenge only with independently validated mapping and target-domain evidence." ,),
                ("Transfer audit", "Target evidence"),
                82.0,
            ),
        ]

    output: list[ResearchHypothesis] = []
    for idx, (label, desc, family, predictions, falsification, evidence, score) in enumerate(templates[: max(1, int(max_hypotheses))]):
        hid = _stable_id("HYP", qid, label)
        queries = tuple(q.get("literature_queries") or ())[:2]
        output.append(ResearchHypothesis(
            hypothesis_id=hid,
            created_at=now,
            question_id=qid,
            label=label,
            description=desc,
            mechanism_family=family,
            predictions=tuple(predictions),
            falsification_conditions=tuple(falsification),
            required_evidence=tuple(evidence),
            literature_queries=queries,
            priority_score=float(score),
        ))
    return tuple(output)


def evaluate_stop_conditions(
    question: Any,
    runs: Sequence[Mapping[str, Any]] = (),
    replications: Sequence[Mapping[str, Any]] = (),
) -> tuple[str, tuple[str, ...]]:
    q = _row(question)
    exp = str(q.get("experiment_id") or "")
    related_runs = [x for x in runs if str(x.get("experiment_id") or "") == exp]
    # Multiple executions over the same predeclared dataset/holdout are attempts,
    # not independent scientific evidence.  Legacy runs predate evidence_unit_id,
    # so their run_id remains the independence key.
    failed_evidence_units = {
        str(x.get("evidence_unit_id") or x.get("run_id") or "").strip()
        for x in related_runs
        if str(x.get("stage") or "") == "HISTORICAL_OOS"
        and str(x.get("verdict") or "") == "NO_OOS_IMPROVEMENT"
        and str(x.get("evidence_unit_id") or x.get("run_id") or "").strip()
    }
    oos_failures = len(failed_evidence_units)
    repl_failures = sum(1 for x in replications if str(x.get("experiment_id") or "") == exp and str(x.get("status") or "") in {"FAILED", "NOT_REPLICATED"})
    reasons: list[str] = []
    if oos_failures >= 3:
        reasons.append("Three independent historical OOS failures reached the stop threshold.")
    if repl_failures >= 2:
        reasons.append("Two failed replication attempts reached the stop threshold.")
    if reasons:
        return "STOP_RECOMMENDED", tuple(reasons)
    if str(q.get("target_variable") or "") == "market_state":
        return "WAITING_INPUT", (
            "The economic definition of market_state is unresolved; autonomous experimentation must not invent the observable.",
        )
    return "CONTINUE_BOUNDED", ("No configured scientific stop rule has fired.",)


def build_research_plan(
    question: Any,
    hypotheses: Sequence[Any],
    budget: ResearchBudget | None = None,
    runs: Sequence[Mapping[str, Any]] = (),
    replications: Sequence[Mapping[str, Any]] = (),
) -> ResearchPlan:
    q = _row(question)
    hs = sorted((_row(x) for x in hypotheses), key=lambda x: float(x.get("priority_score") or 0.0), reverse=True)
    budget = budget or ResearchBudget()
    qid = str(q.get("question_id") or "")
    selected = str((hs[0] if hs else {}).get("hypothesis_id") or "")
    plan_id = _stable_id("PLAN", qid, selected, str(budget.max_hypotheses), str(budget.max_literature_queries))
    now = _now_iso()
    tasks: list[ResearchTask] = []

    queries = list(q.get("literature_queries") or [])[: max(0, int(budget.max_literature_queries))]
    for idx, query in enumerate(queries):
        tasks.append(ResearchTask(
            task_id=_stable_id("TASK", plan_id, "LITERATURE", query),
            created_at=now,
            plan_id=plan_id,
            question_id=qid,
            task_type="LITERATURE_SEARCH",
            description="Search confirming and refuting literature before escalating the hypothesis.",
            status="READY",
            expected_information_gain=max(55.0, 88.0 - idx * 8.0),
            estimated_cost=8.0,
            query=str(query),
            required_tools=("CROSSREF", "SCIENTIFIC_RELEVANCE_RANKER"),
        ))

    observable_blocked = str(q.get("target_variable") or "") == "market_state"
    tasks.append(ResearchTask(
        task_id=_stable_id("TASK", plan_id, "OBSERVABLE"),
        created_at=now,
        plan_id=plan_id,
        question_id=qid,
        task_type="OBSERVABLE_DEFINITION",
        description="Define the economically justified observable corresponding to the mathematical target state.",
        status="WAITING_INPUT" if observable_blocked else "READY",
        expected_information_gain=96.0,
        estimated_cost=12.0,
        blockers=("Human/domain-scientist definition required; the Research Director must not invent the target observable.",) if observable_blocked else (),
        required_tools=("DOMAIN_EXPERT", "PROVENANCE"),
    ))
    tasks.append(ResearchTask(
        task_id=_stable_id("TASK", plan_id, "HISTORICAL_DATA"),
        created_at=now,
        plan_id=plan_id,
        question_id=qid,
        task_type="HISTORICAL_DATA_CONTRACT",
        description="Acquire a chronological target-domain dataset only after the observable is defined.",
        status="WAITING_INPUT" if observable_blocked else "PLANNED",
        expected_information_gain=94.0,
        estimated_cost=18.0,
        prerequisites=("OBSERVABLE_DEFINITION",),
        blockers=("Observable mapping unresolved.",) if observable_blocked else (),
        required_tools=("DATASET", "DATA_FINGERPRINT", "LEAKAGE_GUARD"),
    ))
    tasks.append(ResearchTask(
        task_id=_stable_id("TASK", plan_id, "EXPERIMENT_DESIGN"),
        created_at=now,
        plan_id=plan_id,
        question_id=qid,
        task_type="EXPERIMENT_DESIGN",
        description="Design a discriminating experiment between the leading non-stationary hypothesis and the null.",
        status="BLOCKED" if observable_blocked else "PLANNED",
        expected_information_gain=92.0,
        estimated_cost=24.0,
        prerequisites=("LITERATURE_SEARCH", "OBSERVABLE_DEFINITION", "HISTORICAL_DATA_CONTRACT"),
        blockers=("Historical observable/data contract not ready.",) if observable_blocked else (),
        required_tools=("EXPERIMENT_FACTORY", "VALIDATION_COUNCIL"),
    ))
    tasks = tasks[: max(1, int(budget.max_tasks))]

    stop_status, stop_reasons = evaluate_stop_conditions(q, runs=runs, replications=replications)
    if stop_status == "STOP_RECOMMENDED":
        status = "STOP_RECOMMENDED"
        next_action = "Review stop evidence before spending additional research budget."
    elif observable_blocked:
        status = "WAITING_INPUT"
        next_action = "Define the target-domain observable while literature scouting proceeds within budget."
    else:
        status = "READY"
        next_action = "Run bounded literature scouting, then design the next discriminating experiment."

    stop_rules = (
        "Stop or freeze the branch after 3 independent historical OOS failures unless new evidence changes the model class.",
        "Stop or freeze after 2 failed replication attempts unless the replication contract was materially invalid.",
        "Do not experiment if no measurable target observable can be defined.",
        "Do not increase complexity solely to rescue an in-sample/backtest result.",
        "Stop the autonomous cycle when its explicit budget is exhausted.",
        "No production promotion is permitted by Phase 6.",
    )
    rationale = (
        "The plan maximizes information gain before model complexity: literature and observable definition precede new experiments.",
        *stop_reasons,
    )
    blockers = tuple(dict.fromkeys(str(x) for x in (q.get("blockers") or ()) if str(x).strip()))
    return ResearchPlan(
        plan_id=plan_id,
        created_at=now,
        question_id=qid,
        selected_hypothesis_id=selected,
        hypothesis_ids=tuple(str(x.get("hypothesis_id") or "") for x in hs if x.get("hypothesis_id")),
        tasks=tuple(tasks),
        budget=budget,
        stop_rules=stop_rules,
        status=status,
        next_action=next_action,
        rationale=rationale,
        blockers=blockers,
    )


@dataclass(frozen=True)
class BoundedCycleOutput:
    questions: tuple[OpenResearchQuestion, ...]
    hypotheses: tuple[ResearchHypothesis, ...]
    plan: ResearchPlan | None
    cycle: DirectorCycle | None
    diary: tuple[ResearchDiaryEntry, ...]


def run_bounded_research_cycle(
    failures: Sequence[Mapping[str, Any]] = (),
    surprises: Sequence[Mapping[str, Any]] = (),
    theory_populations: Sequence[Mapping[str, Any]] = (),
    gaps: Sequence[Mapping[str, Any]] = (),
    validation_reviews: Sequence[Mapping[str, Any]] = (),
    runs: Sequence[Mapping[str, Any]] = (),
    replications: Sequence[Mapping[str, Any]] = (),
    budget: ResearchBudget | None = None,
) -> BoundedCycleOutput:
    """Run exactly one bounded planning cycle.

    It may create questions/hypotheses/tasks, but executes no external search and no experiment.
    """
    budget = budget or ResearchBudget()
    questions = derive_open_questions(
        failures=failures,
        surprises=surprises,
        theory_populations=theory_populations,
        gaps=gaps,
        validation_reviews=validation_reviews,
    )
    if not questions:
        return BoundedCycleOutput((), (), None, None, ())

    selected = questions[0]
    hypotheses = generate_hypotheses(selected, max_hypotheses=budget.max_hypotheses)
    plan = build_research_plan(selected, hypotheses, budget=budget, runs=runs, replications=replications)
    now = _now_iso()
    cycle_id = _stable_id("CYCLE", selected.question_id, plan.plan_id, now)
    decisions = (
        f"Selected highest-priority unresolved question ({selected.priority_score:.1f}/100).",
        f"Generated {len(hypotheses)} bounded hypotheses including an explicit null alternative.",
        f"Plan status: {plan.status}.",
        "No external literature search was executed automatically.",
        "No experiment or production action was executed automatically.",
    )
    cycle = DirectorCycle(
        cycle_id=cycle_id,
        created_at=now,
        selected_question_id=selected.question_id,
        created_question_ids=tuple(q.question_id for q in questions),
        generated_hypothesis_ids=tuple(h.hypothesis_id for h in hypotheses),
        plan_id=plan.plan_id,
        status="BOUNDED_PLANNING_COMPLETE",
        next_action=plan.next_action,
        budget=budget,
        decisions=decisions,
        external_actions_executed=False,
        experiment_execution_allowed=False,
    )
    lead = hypotheses[0] if hypotheses else None
    diary = (
        ResearchDiaryEntry(
            diary_id=_stable_id("DIARY", cycle_id, "OBSERVATION"),
            created_at=now,
            question_id=selected.question_id,
            cycle_id=cycle_id,
            entry_type="DIRECTOR_CYCLE",
            observation=(
                "Phase-5 memory contains unresolved scientific debt. "
                + ("The current leading explanation is regime dependence." if "structural-break" in selected.title.lower() else "")
            ).strip(),
            interpretation=(
                f"The highest-value question is '{selected.title}' with priority {selected.priority_score:.1f}/100."
            ),
            action=(
                f"Prioritize '{lead.label}' as the first non-null hypothesis while retaining the null alternative. "
                f"{plan.next_action}"
                if lead else plan.next_action
            ),
            rationale="Research priority is driven by uncertainty, expected information gain, impact, feasibility and cost; not expected PnL.",
            evidence_refs=selected.origin_refs,
        ),
    )
    return BoundedCycleOutput(questions, hypotheses, plan, cycle, diary)


def build_scout_record(
    question_id: str,
    task_id: str,
    query: str,
    results: Sequence[Mapping[str, Any]] = (),
    error: str = "",
    source: str = "Crossref",
) -> LiteratureScoutRecord:
    now = _now_iso()
    compact: list[dict[str, Any]] = []
    for row in list(results)[:20]:
        compact.append({
            "paper_id": str(row.get("paper_id") or ""),
            "title": str(row.get("title") or ""),
            "doi": str(row.get("doi") or ""),
            "published": str(row.get("published") or ""),
            "access_level": str(row.get("access_level") or ""),
            "source": str(row.get("source") or source),
        })
    status = "FAILED" if error else "COMPLETE"
    return LiteratureScoutRecord(
        scout_id=_stable_id("SCOUT", question_id, task_id, query),
        created_at=now,
        question_id=question_id,
        task_id=task_id,
        query=query,
        source=source,
        status=status,
        result_count=len(compact),
        results=tuple(compact),
        error=str(error or ""),
        budget_units_used=1.0,
    )
