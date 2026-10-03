from __future__ import annotations

import hashlib
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable

from .phase2_models import (
    AssumptionRecord,
    ClaimRecord,
    EquationStructure,
    KnowledgeEdge,
    KnowledgeNode,
    ProvenanceRecord,
    SemanticEntityRecord,
    UnderstandingBundle,
)
from .ontology import ONTOLOGY_VERSION, SEMANTIC_ENTITY_PATTERNS, mechanism_aliases, mechanism_family


EXTRACTOR_VERSION = "SRB_SOURCE_EXTRACTOR_V2_5_1"


MECHANISM_FAMILIES: dict[str, str] = {
    "criticality": "DYNAMICS",
    "threshold": "DYNAMICS",
    "feedback": "DYNAMICS",
    "bifurcation": "DYNAMICS",
    "attractor": "DYNAMICS",
    "synchronization": "DYNAMICS",
    "multiscale": "DYNAMICS",
    "network": "NETWORK",
    "contagion": "NETWORK",
    "diffusion": "TRANSPORT",
    "entropy": "INFORMATION",
    "geometry": "GEOMETRY",
    "optimization": "OPTIMIZATION",
    "control": "CONTROL",
    "adaptation": "ADAPTATION",
    "stochasticity": "STOCHASTIC",
}

# Explicit linguistic markers only. Phase 2.5.1 intentionally does NOT infer
# scientific claims from topic words, citations, metadata, or generic prose.
CLAIM_MARKERS: dict[str, tuple[str, ...]] = {
    "RESULT": (
        "we find", "we found", "we observe", "we observed", "we estimate", "we estimated",
        "we report", "we reported", "we document", "we documented", "we detect", "we detected",
        "we obtain", "we obtained", "our results show", "our results indicate", "results show",
        "results indicate", "the results show", "the results indicate", "data show", "data indicate",
        # Editorial/third-person abstracts are common in bibliographic sources. These markers
        # remain explicit source claims; they do not infer results from topic words.
        "the authors find", "the authors found", "the authors observe", "the authors report",
        "the authors demonstrate", "the authors show", "the article shows", "the paper shows",
        "the study shows", "the article demonstrates", "the paper demonstrates",
    ),
    "CONCLUSION": (
        "we conclude", "we concluded", "these results demonstrate", "the results demonstrate",
        "our results demonstrate", "these findings demonstrate", "our findings demonstrate",
        "these findings suggest", "our findings suggest", "this demonstrates that", "this shows that",
        "the authors conclude", "the article concludes", "the paper concludes",
    ),
    "THEORETICAL_RESULT": (
        "we prove", "we proved", "we establish", "we established", "we derive", "we derived",
        "we show that", "we demonstrate that",
    ),
    "HYPOTHESIS": (
        "we hypothesize", "we hypothesise", "we conjecture", "we propose that",
        "our hypothesis is", "we test the hypothesis",
    ),
    "METHOD": (
        "we introduce", "we develop", "we developed", "we propose a method",
        "we present a method", "we construct", "we constructed",
        "the authors build", "the authors built", "the authors develop", "the authors developed",
        "the authors describe", "the article develops", "the paper develops",
        "the article proposes", "the paper proposes", "the article solves", "the paper solves",
    ),
}


def _claim_subtype(claim_type: str, sentence: str) -> str:
    lower = sentence.lower()
    if claim_type == "RESULT":
        if any(token in lower for token in ("we estimate", "we estimated", "confidence interval", "p <", "p<", "statistically significant")):
            return "EMPIRICAL_ESTIMATE"
        if any(token in lower for token in (
            "we found", "we find", "we observe", "we observed", "results show", "results indicate",
            "data show", "data indicate", "the authors find", "the authors found", "the authors observe",
            "the authors report", "the authors demonstrate", "the authors show", "the article shows",
            "the paper shows", "the study shows",
        )):
            return "EMPIRICAL_RESULT"
        return "SOURCE_RESULT"
    if claim_type == "CONCLUSION":
        return "AUTHOR_CONCLUSION"
    if claim_type == "THEORETICAL_RESULT":
        return "THEORETICAL_RESULT"
    if claim_type == "METHOD":
        return "METHOD_CONTRIBUTION"
    if claim_type == "HYPOTHESIS":
        return "EXPLICIT_HYPOTHESIS"
    return "SOURCE_CLAIM"

ASSUMPTION_MARKERS: tuple[str, ...] = (
    "we assume", "assume that", "assuming that", "under the assumption", "suppose that",
    "subject to", "given that", "we impose", "we require",
)

STATISTICAL_CUES: tuple[str, ...] = (
    "p <", "p<", "p =", "confidence interval", "statistically significant", "significant at",
    "95%", "99%", "standard error", "bootstrap", "credible interval",
)

RESERVED_VARIABLES = {
    "sin", "cos", "tan", "exp", "log", "ln", "max", "min", "argmax", "argmin",
    "sqrt", "frac", "sum", "int", "partial", "nabla", "left", "right", "mathrm",
    "mathbb", "mathbf", "text", "operatorname", "begin", "end", "where", "for", "and",
}



def _stable_id(prefix: str, *parts: str) -> str:
    payload = "|".join(str(p or "").strip().lower() for p in parts)
    return f"{prefix}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()



def _source_digest(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()



def _sentence_spans(text: str) -> list[tuple[int, int, str]]:
    """Return conservative sentence spans without silently reordering source text."""
    value = str(text or "")
    spans: list[tuple[int, int, str]] = []
    start = 0
    pattern = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\\$])")
    for match in pattern.finditer(value):
        end = match.start()
        sentence = value[start:end].strip()
        if len(sentence) >= 20:
            left_trim = len(value[start:end]) - len(value[start:end].lstrip())
            right_trim = len(value[start:end].rstrip())
            spans.append((start + left_trim, start + right_trim, sentence))
        start = match.end()
    tail = value[start:].strip()
    if len(tail) >= 20:
        left_trim = len(value[start:]) - len(value[start:].lstrip())
        right_trim = len(value[start:].rstrip())
        spans.append((start + left_trim, start + right_trim, tail))
    return spans



def _make_provenance(
    paper_id: str,
    source_kind: str,
    source_digest: str,
    sentence_index: int | None,
    char_start: int | None,
    char_end: int | None,
    excerpt: str,
) -> ProvenanceRecord:
    excerpt_clean = _normalize_space(excerpt)[:360]
    provenance_id = _stable_id(
        "PROV", paper_id, source_kind, str(sentence_index), str(char_start), str(char_end), excerpt_clean
    )
    return ProvenanceRecord(
        provenance_id=provenance_id,
        paper_id=paper_id,
        source_kind=source_kind,
        sentence_index=sentence_index,
        char_start=char_start,
        char_end=char_end,
        excerpt=excerpt_clean,
        source_digest=source_digest,
    )



def extract_claim_records(paper_id: str, text: str, source_kind: str = "full_text") -> tuple[tuple[ClaimRecord, ...], dict[str, ProvenanceRecord]]:
    digest = _source_digest(text)
    claims: list[ClaimRecord] = []
    provenance: dict[str, ProvenanceRecord] = {}

    for idx, (start, end, sentence) in enumerate(_sentence_spans(text)):
        lower = sentence.lower()
        claim_type = None
        marker_hits = 0
        for ctype, markers in CLAIM_MARKERS.items():
            hits = sum(1 for marker in markers if marker in lower)
            if hits > marker_hits:
                claim_type = ctype
                marker_hits = hits

        # Conservative fallback: explicit result/statistical language only.
        stat_cues = tuple(cue for cue in STATISTICAL_CUES if cue in lower)
        if claim_type is None and stat_cues:
            claim_type = "RESULT"
            marker_hits = 1
        elif claim_type == "THEORETICAL_RESULT" and stat_cues:
            # A sentence explicitly reporting statistical evidence is treated as an
            # empirical/source result even when it also contains "we show that".
            claim_type = "RESULT"

        if claim_type is None:
            continue

        prov = _make_provenance(paper_id, source_kind, digest, idx, start, end, sentence)
        provenance[prov.provenance_id] = prov
        extraction_confidence = min(0.98, 0.72 + 0.08 * marker_hits + 0.04 * len(stat_cues))
        claims.append(
            ClaimRecord(
                claim_id=_stable_id("CLAIM", paper_id, sentence, claim_type),
                paper_id=paper_id,
                text=_normalize_space(sentence),
                claim_type=claim_type,
                extraction_confidence=round(extraction_confidence, 3),
                support_status="SOURCE_TEXT_ONLY",
                provenance_id=prov.provenance_id,
                statistical_cues=stat_cues,
                claim_subtype=_claim_subtype(claim_type, sentence),
                explicitness="EXPLICIT_SOURCE_CLAIM",
            )
        )
        if len(claims) >= 24:
            break

    return tuple(claims), provenance



def _assumption_category(sentence: str) -> str:
    lower = sentence.lower()
    if any(x in lower for x in ("normal distribution", "gaussian", "iid", "independent", "stationary", "ergodic")):
        return "STATISTICAL"
    if any(x in lower for x in ("boundary", "initial condition", "terminal condition", "constraint")):
        return "BOUNDARY_CONDITION"
    if any(x in lower for x in ("market", "friction", "liquidity", "transaction cost", "arbitrage")):
        return "DOMAIN"
    if any(x in lower for x in ("parameter", "constant", "homogeneous", "linear", "continuous", "differentiable")):
        return "MODEL"
    return "GENERAL"



def extract_assumption_records(paper_id: str, text: str, source_kind: str = "full_text") -> tuple[tuple[AssumptionRecord, ...], dict[str, ProvenanceRecord]]:
    digest = _source_digest(text)
    records: list[AssumptionRecord] = []
    provenance: dict[str, ProvenanceRecord] = {}

    for idx, (start, end, sentence) in enumerate(_sentence_spans(text)):
        lower = sentence.lower()
        hits = sum(1 for marker in ASSUMPTION_MARKERS if marker in lower)
        if not hits:
            continue
        prov = _make_provenance(paper_id, source_kind, digest, idx, start, end, sentence)
        provenance[prov.provenance_id] = prov
        records.append(
            AssumptionRecord(
                assumption_id=_stable_id("ASSUMP", paper_id, sentence),
                paper_id=paper_id,
                text=_normalize_space(sentence),
                category=_assumption_category(sentence),
                explicitness="EXPLICIT",
                extraction_confidence=round(min(0.98, 0.84 + 0.04 * hits), 3),
                provenance_id=prov.provenance_id,
            )
        )
        if len(records) >= 24:
            break
    return tuple(records), provenance



def _find_alias_span(text: str, alias: str) -> tuple[int | None, int | None, str]:
    value = str(text or "")
    alias = str(alias or "").strip()
    if not value or not alias:
        return None, None, ""
    if len(alias) <= 3 and alias.isalpha():
        match = re.search(rf"\b{re.escape(alias)}\b", value, flags=re.IGNORECASE)
    else:
        match = re.search(re.escape(alias), value, flags=re.IGNORECASE)
    if not match:
        return None, None, ""
    return match.start(), match.end(), value[match.start():match.end()]


def _sentence_for_position(text: str, position: int | None) -> tuple[int | None, int | None, int | None, str]:
    if position is None:
        return None, None, None, ""
    for idx, (start, end, sentence) in enumerate(_sentence_spans(text)):
        if start <= position <= end:
            return idx, start, end, sentence
    return None, position, position, ""


def extract_semantic_entities(
    paper_id: str,
    title: str,
    text: str,
    source_kind: str = "full_text",
) -> tuple[tuple[SemanticEntityRecord, ...], dict[str, ProvenanceRecord]]:
    """Extract lexically grounded theories/methods/objects/concepts/applications.

    Specific matches dominate nested generic matches inside the same entity type
    (e.g. "Random Singular Value Decomposition" suppresses the nested generic SVD
    record for that same occurrence). Cross-type views are retained because a phrase
    can legitimately identify both a theory and a mathematical object.
    """
    provenance: dict[str, ProvenanceRecord] = {}
    sources = (("title", str(title or "")), (source_kind, str(text or "")))
    candidates: list[dict[str, object]] = []

    for entity_type, entities in SEMANTIC_ENTITY_PATTERNS.items():
        for canonical, aliases in entities.items():
            best = None
            for skind, source in sources:
                for alias in aliases:
                    start, end, matched = _find_alias_span(source, alias)
                    if start is not None:
                        best = {
                            "entity_type": entity_type,
                            "canonical": canonical,
                            "alias": alias,
                            "skind": skind,
                            "source": source,
                            "start": start,
                            "end": end,
                            "matched": matched,
                        }
                        break
                if best:
                    break
            if best:
                candidates.append(best)

    # Longer exact source matches win over nested generic matches of the same type/source.
    candidates.sort(key=lambda c: (str(c["entity_type"]), -(int(c["end"]) - int(c["start"])), str(c["canonical"])))
    accepted: list[dict[str, object]] = []
    seen_canonical: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (str(candidate["entity_type"]), str(candidate["canonical"]).lower())
        if key in seen_canonical:
            continue
        nested = False
        for existing in accepted:
            if existing["entity_type"] != candidate["entity_type"] or existing["skind"] != candidate["skind"]:
                continue
            if int(existing["start"]) <= int(candidate["start"]) and int(candidate["end"]) <= int(existing["end"]):
                nested = True
                break
        if nested:
            continue
        seen_canonical.add(key)
        accepted.append(candidate)

    records: list[SemanticEntityRecord] = []
    for item in accepted:
        entity_type = str(item["entity_type"])
        canonical = str(item["canonical"])
        alias = str(item["alias"])
        skind = str(item["skind"])
        source = str(item["source"])
        start = int(item["start"])
        end = int(item["end"])
        matched = str(item["matched"])
        digest = _source_digest(source)
        sentence_idx, sent_start, sent_end, sentence = _sentence_for_position(source, start)
        excerpt = sentence or matched
        prov = _make_provenance(
            paper_id, skind, digest, sentence_idx,
            sent_start if sentence else start,
            sent_end if sentence else end,
            excerpt,
        )
        provenance[prov.provenance_id] = prov
        confidence = 0.96 if alias.lower() == canonical.lower() else 0.91
        records.append(
            SemanticEntityRecord(
                entity_id=_stable_id("ENTITY", paper_id, entity_type, canonical),
                paper_id=paper_id,
                entity_type=entity_type,
                canonical_label=canonical,
                matched_text=matched,
                extraction_confidence=confidence,
                provenance_id=prov.provenance_id,
            )
        )

    records.sort(key=lambda r: (r.entity_type, r.canonical_label))
    return tuple(records), provenance

def extract_problem_provenance(
    paper_id: str,
    problem: str,
    source_text: str,
    source_kind: str,
) -> tuple[str, dict[str, ProvenanceRecord]]:
    fragment = str(problem or "").strip()
    source = str(source_text or "")
    if not fragment or not source:
        return "", {}
    start = source.find(fragment)
    if start < 0:
        # Only accept an exact normalized sentence match; do not attach provenance to an LLM paraphrase.
        norm_problem = _normalize_space(fragment).lower()
        for idx, (s, e, sentence) in enumerate(_sentence_spans(source)):
            if _normalize_space(sentence).lower() == norm_problem:
                prov = _make_provenance(paper_id, source_kind, _source_digest(source), idx, s, e, sentence)
                return prov.provenance_id, {prov.provenance_id: prov}
        return "", {}
    idx, sent_start, sent_end, sentence = _sentence_for_position(source, start)
    prov = _make_provenance(
        paper_id, source_kind, _source_digest(source), idx,
        sent_start if sentence else start,
        sent_end if sentence else start + len(fragment),
        sentence or fragment,
    )
    return prov.provenance_id, {prov.provenance_id: prov}


def extract_mechanism_provenance(
    paper_id: str,
    title: str,
    source_text: str,
    source_kind: str,
    mechanisms: dict[str, float],
) -> tuple[dict[str, tuple[str, ...]], dict[str, ProvenanceRecord]]:
    mapping: dict[str, tuple[str, ...]] = {}
    provenance: dict[str, ProvenanceRecord] = {}
    for mechanism in mechanisms:
        ids: list[str] = []
        for skind, source in ((source_kind, str(source_text or "")), ("title", str(title or ""))):
            for alias in mechanism_aliases(mechanism):
                start, end, matched = _find_alias_span(source, alias)
                if start is None:
                    continue
                idx, sent_start, sent_end, sentence = _sentence_for_position(source, start)
                prov = _make_provenance(
                    paper_id, skind, _source_digest(source), idx,
                    sent_start if sentence else start,
                    sent_end if sentence else end,
                    sentence or matched,
                )
                provenance[prov.provenance_id] = prov
                ids.append(prov.provenance_id)
                break
            if ids:
                break
        if ids:
            mapping[mechanism] = tuple(dict.fromkeys(ids))
    return mapping, provenance


def _equation_candidates(text: str) -> list[tuple[str, int | None, int | None]]:
    value = str(text or "")
    candidates: list[tuple[str, int | None, int | None]] = []

    patterns = [
        re.compile(r"\$\$([^$]{3,1200})\$\$", re.DOTALL),
        re.compile(r"(?<!\$)\$([^$]{3,500})\$(?!\$)", re.DOTALL),
        re.compile(r"\\\[([\s\S]{3,1200}?)\\\]"),
        re.compile(r"\\begin\{equation\*?\}([\s\S]{3,1600}?)\\end\{equation\*?\}"),
    ]
    for pattern in patterns:
        for match in pattern.finditer(value):
            raw = match.group(1).strip()
            if any(token in raw for token in ("=", "\\frac", "\\sum", "\\int", "\\partial", "\\nabla", "\\min", "\\max")):
                candidates.append((raw, match.start(1), match.end(1)))

    # Plain-text equation lines, useful for pasted notes/PDF text extraction.
    cursor = 0
    for line in value.splitlines(True):
        clean = line.strip()
        if 3 <= len(clean) <= 600 and "=" in clean and re.search(r"[A-Za-z\\]", clean):
            # If the line already contains an inline/display LaTeX delimiter, the dedicated
            # extractor above owns that equation. Treating the whole prose line as an equation
            # would duplicate it and contaminate variable extraction with ordinary words.
            if "$" in clean or "\\[" in clean or "\\begin{equation" in clean:
                cursor += len(line)
                continue
            if not clean.startswith(("http://", "https://")):
                pos = value.find(clean, cursor)
                candidates.append((clean, pos if pos >= 0 else None, pos + len(clean) if pos >= 0 else None))
        cursor += len(line)

    out: list[tuple[str, int | None, int | None]] = []
    seen: set[str] = set()
    for raw, start, end in candidates:
        normalized = _normalize_space(raw)
        if normalized not in seen:
            seen.add(normalized)
            out.append((raw, start, end))
        if len(out) >= 32:
            break
    return out



def _normalize_equation(raw: str) -> str:
    value = str(raw or "").strip()
    value = value.replace("\\,", " ").replace("\\!", "")

    # Phase 4.0.1: accept common human-entered mathematical Unicode and
    # compact stochastic-calculus notation without changing the scientific
    # meaning of the expression. This is normalization only, not inference.
    unicode_ops = {
        "−": "-", "–": "-", "—": "-",
        "×": "*", "·": "*",
        "ₜ": "_t",
    }
    for src, dst in unicode_ops.items():
        value = value.replace(src, dst)

    greek = {
        "κ": "kappa", "σ": "sigma", "μ": "mu", "λ": "lambda",
        "ρ": "rho", "θ": "theta", "β": "beta", "α": "alpha",
        "γ": "gamma", "δ": "delta", "ν": "nu", "τ": "tau",
        "φ": "phi", "ψ": "psi", "ω": "omega",
        "Λ": "Lambda", "Σ": "Sigma", "Φ": "Phi", "Ψ": "Psi", "Ω": "Omega",
    }
    for src, dst in greek.items():
        value = value.replace(src, f" {dst} ")

    # Normalize the most common compact Itô notation used in manual input:
    # dXt -> dX_t, dWt -> dW_t, Xtdt -> X_t dt.
    value = re.sub(r"\bd([A-Za-z])t\b", r"d\1_t", value)
    value = re.sub(r"\b([A-Za-z])tdt\b", r"\1_t dt", value)
    value = re.sub(r"\b([A-Za-z])_tdt\b", r"\1_t dt", value)

    # Compact products frequently have no whitespace around named parameters.
    # Adding whitespace here only helps tokenization; it does not add terms.
    value = re.sub(r"\b(kappa|sigma|mu|lambda|rho|theta|beta|alpha|gamma|delta|nu|tau|phi|psi|omega)(?=[A-Za-z])", r"\1 ", value)

    value = re.sub(r"\s+", " ", value)
    return value.strip()



def _equation_variables(normalized: str) -> tuple[str, ...]:
    value = normalized
    tokens: list[str] = []

    # LaTeX commands with semantic variable meaning are retained selectively.
    greek = re.findall(r"\\(alpha|beta|gamma|delta|epsilon|eta|theta|lambda|mu|nu|rho|sigma|tau|phi|psi|omega|Lambda|Sigma|Phi|Psi|Omega)\b", value)
    tokens.extend(f"\\{g}" for g in greek)

    # Standard identifiers, including subscripts.
    for token in re.findall(r"(?<!\\)\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9{}]+)?\b", value):
        if token.lower() in RESERVED_VARIABLES:
            continue
        if len(token) > 24:
            continue
        tokens.append(token)

    # Indexed LaTeX symbols such as X_t or g_{\mu\nu}.
    tokens.extend(re.findall(r"(?:[A-Za-z]|\\[A-Za-z]+)_(?:\{[^{}]{1,30}\}|[A-Za-z0-9])", value))

    clean: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            clean.append(token)
    return tuple(clean[:32])



def _equation_operators(value: str) -> tuple[str, ...]:
    checks = {
        "EQUALITY": "=" in value,
        "SUM": "\\sum" in value or "Σ" in value,
        "INTEGRAL": "\\int" in value or "∫" in value,
        "PARTIAL_DERIVATIVE": "\\partial" in value or "∂" in value,
        "GRADIENT": "\\nabla" in value or "∇" in value,
        "LAPLACIAN": "\\Delta" in value or "\\nabla^2" in value or "Δ" in value,
        "EXPECTATION": "\\mathbb{E}" in value or "E[" in value or "\\mathbf{E}" in value,
        "MINIMIZATION": "\\min" in value or "min " in value,
        "MAXIMIZATION": "\\max" in value or "max " in value,
        "MATRIX_TENSOR": any(x in value for x in ("_{ij}", "_{\\mu", "\\otimes", "\\mathbf", "\\mathbb")),
    }
    return tuple(name for name, present in checks.items() if present)



def _equation_type(value: str, operators: Iterable[str]) -> str:
    ops = set(operators)
    lower = value.lower()
    stochastic = bool(re.search(r"\bdW(?:_[A-Za-z0-9{}]+)?\b|\\mathrm\{d\}W|brownian|ito", value, re.IGNORECASE))
    if stochastic and ("PARTIAL_DERIVATIVE" in ops or re.search(r"\bd[A-Za-z].*=", value)):
        return "SDE"
    if "PARTIAL_DERIVATIVE" in ops:
        return "PDE"
    if re.search(r"\bd[A-Za-z](?:_[A-Za-z0-9{}]+)?\s*/\s*dt|\\frac\{d", value):
        return "ODE"
    if "INTEGRAL" in ops and "EQUALITY" in ops:
        return "INTEGRAL_EQUATION"
    if "MINIMIZATION" in ops or "MAXIMIZATION" in ops or "argmin" in lower or "argmax" in lower:
        return "OPTIMIZATION"
    if "MATRIX_TENSOR" in ops or any(x in value for x in ("g_{", "R_{", "G_{", "T_{")):
        return "TENSOR_GEOMETRIC"
    if "EXPECTATION" in ops:
        return "PROBABILISTIC"
    return "ALGEBRAIC"



def _derivative_order(value: str) -> int:
    if re.search(r"\\partial\^\{?2\}?|d\^2|\\nabla\^2|∂²", value):
        return 2
    if "\\partial" in value or "∂" in value or re.search(r"\bd[A-Za-z].*/\s*dt", value):
        return 1
    return 0



def parse_equation_structure(
    paper_id: str,
    raw: str,
    source_kind: str,
    source_digest: str,
    char_start: int | None = None,
    char_end: int | None = None,
) -> tuple[EquationStructure, ProvenanceRecord]:
    normalized = _normalize_equation(raw)
    variables = _equation_variables(normalized)
    operators = _equation_operators(normalized)
    equation_type = _equation_type(normalized, operators)

    stochastic_terms = tuple(sorted(set(re.findall(r"(?:dW(?:_[A-Za-z0-9{}]+)?|\\mathrm\{d\}W(?:_[A-Za-z0-9{}]+)?)", normalized))))
    geometry_terms = tuple(term for term in ("curvature", "metric", "geodesic", "Ricci", "tensor") if term.lower() in normalized.lower())
    integral_terms = tuple(x for x in ("INTEGRAL", "SUM", "EXPECTATION") if x in operators)
    constraints = tuple(
        x for x in ("nonnegative", "positive", "normalized", "martingale", "boundary", "initial condition")
        if x in normalized.lower()
    )

    # Parameters are deliberately heuristic: Greek symbols and short lowercase identifiers not indexed by time.
    params = [v for v in variables if v.startswith("\\") or (len(v) <= 3 and not re.search(r"_[tTnN]", v))]
    signature_payload = "|".join([
        equation_type,
        ",".join(sorted(operators)),
        str(_derivative_order(normalized)),
        ",".join(sorted(stochastic_terms)),
        ",".join(sorted(geometry_terms)),
    ])
    structural_signature = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()[:20]

    prov = _make_provenance(
        paper_id, source_kind, source_digest, None, char_start, char_end, normalized
    )
    equation = EquationStructure(
        equation_id=_stable_id("EQ", paper_id, normalized),
        paper_id=paper_id,
        raw=raw.strip(),
        normalized=normalized,
        equation_type=equation_type,
        variables=variables,
        parameters=tuple(dict.fromkeys(params))[:24],
        operators=operators,
        derivative_order=_derivative_order(normalized),
        stochastic_terms=stochastic_terms,
        geometry_terms=geometry_terms,
        integral_terms=integral_terms,
        constraints=constraints,
        dimensional_status="UNKNOWN_REQUIRES_MAPPING",
        structural_signature=structural_signature,
        provenance_id=prov.provenance_id,
    )
    return equation, prov



def extract_equation_structures(paper_id: str, text: str, source_kind: str = "full_text") -> tuple[tuple[EquationStructure, ...], dict[str, ProvenanceRecord]]:
    digest = _source_digest(text)
    records: list[EquationStructure] = []
    provenance: dict[str, ProvenanceRecord] = {}
    for raw, start, end in _equation_candidates(text):
        equation, prov = parse_equation_structure(paper_id, raw, source_kind, digest, start, end)
        records.append(equation)
        provenance[prov.provenance_id] = prov
    return tuple(records), provenance



def _mechanism_family_map(mechanisms: dict[str, float]) -> dict[str, tuple[str, ...]]:
    buckets: dict[str, list[str]] = {}
    for mechanism in mechanisms:
        family = mechanism_family(mechanism)
        buckets.setdefault(family, []).append(mechanism)
    return {family: tuple(sorted(values)) for family, values in sorted(buckets.items())}



def _node(node_type: str, label: str, identity: str, **metadata) -> KnowledgeNode:
    return KnowledgeNode(node_id=_stable_id(node_type.upper(), identity), node_type=node_type, label=label, metadata=metadata)



def _edge(source: str, target: str, relation: str, **metadata) -> KnowledgeEdge:
    return KnowledgeEdge(
        edge_id=_stable_id("EDGE", source, target, relation),
        source=source,
        target=target,
        relation=relation,
        metadata=metadata,
    )



def _build_graph(
    paper_id: str,
    paper_title: str,
    domain: str,
    problem: str,
    claims: tuple[ClaimRecord, ...],
    assumptions: tuple[AssumptionRecord, ...],
    equations: tuple[EquationStructure, ...],
    mechanisms: dict[str, float],
    semantic_entities: tuple[SemanticEntityRecord, ...] = (),
    problem_provenance_id: str = "",
    mechanism_provenance_ids: dict[str, tuple[str, ...]] | None = None,
) -> tuple[tuple[KnowledgeNode, ...], tuple[KnowledgeEdge, ...]]:
    nodes: dict[str, KnowledgeNode] = {}
    edges: dict[str, KnowledgeEdge] = {}
    mechanism_provenance_ids = mechanism_provenance_ids or {}

    paper_node = KnowledgeNode(paper_id, "Paper", paper_title, {})
    nodes[paper_node.node_id] = paper_node

    domain_node = _node("Domain", domain, domain)
    nodes[domain_node.node_id] = domain_node
    edge = _edge(paper_id, domain_node.node_id, "CLASSIFIED_AS")
    edges[edge.edge_id] = edge

    if problem:
        problem_node = _node("Problem", problem[:160], f"{paper_id}|{problem}", provenance_id=problem_provenance_id)
        nodes[problem_node.node_id] = problem_node
        edge = _edge(paper_id, problem_node.node_id, "ADDRESSES", provenance_id=problem_provenance_id)
        edges[edge.edge_id] = edge

    for claim in claims:
        node = KnowledgeNode(
            claim.claim_id,
            "Claim",
            claim.text[:180],
            {
                "claim_type": claim.claim_type,
                "claim_subtype": getattr(claim, "claim_subtype", ""),
                "explicitness": getattr(claim, "explicitness", "EXPLICIT_SOURCE_CLAIM"),
                "support_status": claim.support_status,
                "extraction_confidence": claim.extraction_confidence,
                "provenance_id": claim.provenance_id,
            },
        )
        nodes[node.node_id] = node
        edge = _edge(paper_id, node.node_id, "MAKES_CLAIM", provenance_id=claim.provenance_id)
        edges[edge.edge_id] = edge

    for assumption in assumptions:
        node = KnowledgeNode(
            assumption.assumption_id,
            "Assumption",
            assumption.text[:180],
            {"category": assumption.category, "provenance_id": assumption.provenance_id},
        )
        nodes[node.node_id] = node
        edge = _edge(paper_id, node.node_id, "ASSUMES", provenance_id=assumption.provenance_id)
        edges[edge.edge_id] = edge

    for mechanism, score in mechanisms.items():
        family = mechanism_family(mechanism)
        prov_ids = tuple(mechanism_provenance_ids.get(mechanism, ()))
        node = _node("Mechanism", mechanism, mechanism, family=family)
        nodes[node.node_id] = node
        edge = _edge(paper_id, node.node_id, "USES_MECHANISM", score=score, provenance_ids=list(prov_ids))
        edges[edge.edge_id] = edge

    relation_by_entity_type = {
        "Theory": "USES_THEORY",
        "Method": "USES_METHOD",
        "MathematicalObject": "STUDIES_OBJECT",
        "Concept": "HAS_CONCEPT",
        "Application": "APPLIES_TO",
    }
    for entity in semantic_entities:
        # Semantic nodes are global across papers; provenance belongs to the paper->concept edge.
        node = _node(entity.entity_type, entity.canonical_label, f"{entity.entity_type}|{entity.canonical_label}")
        nodes[node.node_id] = node
        relation = relation_by_entity_type.get(entity.entity_type, "MENTIONS")
        edge = _edge(
            paper_id, node.node_id, relation,
            provenance_id=entity.provenance_id,
            extraction_confidence=entity.extraction_confidence,
            matched_text=entity.matched_text,
        )
        edges[edge.edge_id] = edge

    for equation in equations:
        node = KnowledgeNode(
            equation.equation_id,
            "Equation",
            equation.normalized[:180],
            {
                "equation_type": equation.equation_type,
                "signature": equation.structural_signature,
                "provenance_id": equation.provenance_id,
                "dimensional_status": equation.dimensional_status,
            },
        )
        nodes[node.node_id] = node
        edge = _edge(paper_id, node.node_id, "CONTAINS_EQUATION", provenance_id=equation.provenance_id)
        edges[edge.edge_id] = edge
        for variable in equation.variables:
            variable_node = _node("Variable", variable, variable)
            nodes[variable_node.node_id] = variable_node
            edge = _edge(node.node_id, variable_node.node_id, "USES_VARIABLE")
            edges[edge.edge_id] = edge

    return tuple(nodes.values()), tuple(edges.values())


def build_understanding_bundle(
    *,
    paper_id: str,
    paper_title: str,
    source_text: str,
    source_kind: str,
    domain: str,
    problem: str,
    mechanisms: dict[str, float],
) -> tuple[UnderstandingBundle, dict[str, ProvenanceRecord]]:
    text = str(source_text or "").strip()
    if not text:
        raise ValueError("Scientific understanding requires abstract or full scientific text.")

    digest = _source_digest(text)
    claims, p_claims = extract_claim_records(paper_id, text, source_kind)
    assumptions, p_assumptions = extract_assumption_records(paper_id, text, source_kind)
    equations, p_equations = extract_equation_structures(paper_id, text, source_kind)
    semantic_entities, p_entities = extract_semantic_entities(paper_id, paper_title, text, source_kind)
    problem_provenance_id, p_problem = extract_problem_provenance(paper_id, problem, text, source_kind)
    mechanism_provenance_ids, p_mechanisms = extract_mechanism_provenance(
        paper_id, paper_title, text, source_kind, mechanisms
    )

    provenance = {
        **p_claims,
        **p_assumptions,
        **p_equations,
        **p_entities,
        **p_problem,
        **p_mechanisms,
    }
    variables = tuple(dict.fromkeys(v for eq in equations for v in eq.variables))[:128]
    mechanism_families = _mechanism_family_map(mechanisms)
    nodes, edges = _build_graph(
        paper_id=paper_id,
        paper_title=paper_title,
        domain=domain,
        problem=problem,
        claims=claims,
        assumptions=assumptions,
        equations=equations,
        mechanisms=mechanisms,
        semantic_entities=semantic_entities,
        problem_provenance_id=problem_provenance_id,
        mechanism_provenance_ids=mechanism_provenance_ids,
    )

    warnings: list[str] = [
        "Extraction confidence measures parser confidence, not scientific truth.",
        "Equation dimensional compatibility is UNKNOWN until a target-domain mapping defines units and observables.",
        "Claims remain SOURCE_TEXT_ONLY until replication or independent evidence is attached.",
        "Semantic entities are source-grounded lexical normalizations; ontology membership is not evidence of causal transfer.",
    ]
    if not equations:
        warnings.append("No equation structure was detected in the supplied text; no equation should be inferred from metadata or prose.")

    compiler_signature = f"{EXTRACTOR_VERSION}|ontology:{ONTOLOGY_VERSION}"
    understanding_id = _stable_id("UNDERSTAND", paper_id, digest, compiler_signature)
    bundle = UnderstandingBundle(
        understanding_id=understanding_id,
        paper_id=paper_id,
        created_at=_now_iso(),
        source_digest=digest,
        source_kind=source_kind,
        domain=domain,
        problem=problem,
        claims=claims,
        assumptions=assumptions,
        equations=equations,
        mechanisms=mechanisms,
        mechanism_families=mechanism_families,
        variables=variables,
        knowledge_nodes=nodes,
        knowledge_edges=edges,
        warnings=tuple(warnings),
        semantic_entities=semantic_entities,
        problem_provenance_id=problem_provenance_id,
        mechanism_provenance_ids=mechanism_provenance_ids,
        ontology_version=ONTOLOGY_VERSION,
        extractor_version=EXTRACTOR_VERSION,
        compiler_signature=compiler_signature,
        revision_id=_stable_id("UREV", understanding_id, compiler_signature),
    )
    return bundle, provenance


def bundle_to_dict(bundle: UnderstandingBundle) -> dict:
    return asdict(bundle)
