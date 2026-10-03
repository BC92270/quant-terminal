from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from .mechanism_space import compare_mechanism_space
from .phase3_models import TransmutationCandidate, TransferAudit, VariableMapping
from .scientific_understanding import parse_equation_structure


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"


def parse_mapping_lines(text: str) -> tuple[VariableMapping, ...]:
    mappings: list[VariableMapping] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "->" not in line:
            continue
        head, *fields = [part.strip() for part in line.split("|")]
        source, target = [x.strip() for x in head.split("->", 1)]
        meta: dict[str, str] = {}
        for field in fields:
            if "=" in field:
                key, value = field.split("=", 1)
                meta[key.strip().lower()] = value.strip()
        mappings.append(VariableMapping(
            source_variable=source,
            target_variable=target,
            source_unit=meta.get("source_unit", ""),
            target_unit=meta.get("target_unit", ""),
            relation=meta.get("relation", "UNDECLARED").upper(),
            observable=meta.get("observable", "").lower() in {"1", "yes", "true", "y"},
            rationale=meta.get("rationale", ""),
        ))
    # Deduplicate by source variable; last declaration wins.
    index = {m.source_variable: m for m in mappings if m.source_variable and m.target_variable}
    return tuple(index.values())



def _canonical_variable(value: str) -> str:
    token = str(value or "").strip().lstrip("\\")
    token = token.replace("{", "").replace("}", "")
    if token.startswith("d") and len(token) > 2 and token[1].isupper():
        token = token[1:]
    return token


def _meaningful_variables(equation) -> tuple[str, ...]:
    raw = str(equation.normalized or "")
    commands = re.findall(r"\\([A-Za-z]+)", raw)
    ignored_commands = {
        "frac", "sum", "int", "partial", "nabla", "mathrm", "mathbf", "mathbb",
        "left", "right", "text", "operatorname", "begin", "end", "Delta", "pi",
    }
    values = list(equation.variables) + [cmd for cmd in commands if cmd not in ignored_commands]
    stochastic = {_canonical_variable(x) for x in equation.stochastic_terms}
    ignored = {"dt", "dW", "dW_t", "W", "W_t"} | stochastic
    out = []
    seen = set()
    for value in values:
        token = _canonical_variable(value)
        if not token or token in ignored or token.lower() in {"dt", "dw", "wt"}:
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return tuple(out)


def build_transmutation_candidate(
    source_equation: str,
    target_problem: str,
    mappings: Iterable[VariableMapping] = (),
    target_observables: Iterable[str] = (),
    source_context: str = "",
    source_domain: str = "Unknown",
    target_domain: str = "Finance",
    causal_hypothesis: str = "",
    falsification_test: str = "",
) -> TransmutationCandidate:
    digest = hashlib.sha256(str(source_equation or "").encode("utf-8")).hexdigest()
    equation, _ = parse_equation_structure(
        paper_id="MANUAL-TRANSMUTATION",
        raw=source_equation,
        source_kind="manual_equation",
        source_digest=digest,
        char_start=0,
        char_end=len(source_equation),
    )
    mapping_rows = tuple(mappings)
    meaningful_variables = _meaningful_variables(equation)
    mapped_sources = {_canonical_variable(m.source_variable) for m in mapping_rows}
    required = set(meaningful_variables)
    coverage = len(required & mapped_sources) / len(required) if required else 0.0
    observables = tuple(sorted({str(x).strip() for x in target_observables if str(x).strip()}))

    warnings = [
        "Phase 3 does not generate a target equation. It only constructs a pre-formalization mapping candidate.",
        "Variable names, units and observability declarations are hypotheses until independently validated.",
    ]
    if equation.dimensional_status.startswith("UNKNOWN"):
        warnings.append("Source equation dimensional semantics are unresolved by the parser.")

    return TransmutationCandidate(
        candidate_id=_stable_id("TRANSMUTE", source_equation, target_problem, source_domain, target_domain, str(mapping_rows)),
        created_at=_now_iso(),
        source_equation_id=equation.equation_id,
        source_equation_type=equation.equation_type,
        source_structural_signature=equation.structural_signature,
        source_equation=equation.normalized,
        target_problem=target_problem,
        source_domain=source_domain,
        target_domain=target_domain,
        source_variables=meaningful_variables,
        variable_mappings=mapping_rows,
        mapping_coverage=round(coverage, 4),
        preserved_operators=equation.operators,
        target_observables=observables,
        causal_hypothesis=causal_hypothesis.strip(),
        falsification_test=falsification_test.strip(),
        warnings=tuple(warnings),
    )


def audit_transfer_candidate(
    candidate: TransmutationCandidate,
    source_context: str = "",
    bridge_paper_count: int = 0,
) -> TransferAudit:
    comparison = compare_mechanism_space(
        source_context or candidate.source_equation,
        candidate.target_problem,
        source_label="Source",
        target_label="Target",
        source_domain=candidate.source_domain,
        target_domain=candidate.target_domain,
    )
    mappings = candidate.variable_mappings
    coverage = candidate.mapping_coverage

    semantic_status = "STRUCTURAL_SUPPORT" if comparison.structural_score >= 35 else "WEAK_OR_MISSING"
    mathematical_status = "VARIABLE_MAPPING_SUBSTANTIAL" if coverage >= 0.8 else "PARTIAL_MAPPING" if coverage >= 0.5 else "INSUFFICIENT_MAPPING"

    unit_declared = bool(mappings) and all(m.source_unit and m.target_unit and m.relation != "UNDECLARED" for m in mappings)
    dimensional_status = "USER_DECLARED_REQUIRES_FORMAL_VALIDATION" if unit_declared else "UNRESOLVED"

    causal_status = "HYPOTHESIS_DECLARED_NOT_VERIFIED" if candidate.causal_hypothesis else "MISSING"
    observable_targets = {m.target_variable for m in mappings if m.observable}
    listed = set(candidate.target_observables)
    observable_status = "OBSERVABLE_MAPPING_DECLARED" if mappings and all(m.observable or m.target_variable in listed for m in mappings) else "INCOMPLETE"
    falsifiability_status = "DECLARED_NOT_TESTED" if candidate.falsification_test else "MISSING"
    evidence_status = "LITERATURE_BRIDGE_PRESENT" if bridge_paper_count > 0 else "NO_STORED_BRIDGE_EVIDENCE"

    blockers: list[str] = []
    requirements: list[str] = []
    if comparison.structural_score < 30:
        blockers.append("insufficient controlled mechanism overlap")
    if coverage < 0.5:
        blockers.append("less than 50% of parsed source variables are mapped")
    if not unit_declared:
        requirements.append("declare source/target units and mapping relation for every mapped variable")
    requirements.append("formal dimensional analysis is still required even when units are user-declared")
    if not candidate.causal_hypothesis:
        requirements.append("state the causal mechanism that could exist in the target domain")
    if observable_status != "OBSERVABLE_MAPPING_DECLARED":
        requirements.append("map target variables to measurable observables")
    if not candidate.falsification_test:
        requirements.append("state a falsification test before empirical experimentation")
    if bridge_paper_count == 0:
        requirements.append("seek literature support or explicit evidence that the structural bridge is not already refuted")

    score = (
        0.30 * comparison.structural_score
        + 0.22 * (100.0 * coverage)
        + 0.12 * (70.0 if unit_declared else 0.0)
        + 0.10 * (70.0 if candidate.causal_hypothesis else 0.0)
        + 0.10 * (75.0 if observable_status == "OBSERVABLE_MAPPING_DECLARED" else 0.0)
        + 0.10 * (75.0 if candidate.falsification_test else 0.0)
        + 0.06 * (min(100.0, 35.0 + 12.0 * bridge_paper_count) if bridge_paper_count else 0.0)
    )
    # Phase 3 explicitly cannot grant a full formal transfer because dimensional and
    # causal validation are not mechanized yet.
    score = min(79.9, max(0.0, score))

    if blockers:
        verdict = "REJECTED" if comparison.structural_score < 20 else "ANALOGY_ONLY"
    elif coverage < 0.8 or not candidate.causal_hypothesis or not candidate.falsification_test:
        verdict = "ABSTRACT_TRANSFER"
    else:
        verdict = "PARTIAL_TRANSFER"

    return TransferAudit(
        audit_id=_stable_id("TAUDIT", candidate.candidate_id, str(asdict(candidate))),
        candidate_id=candidate.candidate_id,
        created_at=_now_iso(),
        semantic_status=semantic_status,
        mathematical_status=mathematical_status,
        dimensional_status=dimensional_status,
        causal_status=causal_status,
        observable_status=observable_status,
        falsifiability_status=falsifiability_status,
        evidence_status=evidence_status,
        transfer_score=round(score, 1),
        verdict=verdict,
        blockers=tuple(blockers),
        requirements=tuple(dict.fromkeys(requirements)),
        notes=(
            "FULL_TRANSFER is impossible in Phase 3 by design.",
            "A PARTIAL_TRANSFER is only permission to build an experiment, not evidence that the source theory applies to the target domain.",
        ),
    )
