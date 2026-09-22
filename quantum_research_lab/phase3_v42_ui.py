"""Institutional V4.2 coined-walk compiler evidence surface.

The UI authenticates immutable bytes and renders already-sealed evidence only.
It never recompiles, discovers a provider, reads credentials, transpiles, or
submits work.  A resource-screen PASS is kept separate from circuit, backend,
hardware, performance and advantage claims.
"""

from __future__ import annotations

import hashlib
from html import escape
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v42_coined_walk_compiler import canonical_json_sha256, default_v42_artifact_path


SectionHeader = Callable[[str, str, str], None]

EXPECTED_V42_ARTIFACT_SHA256 = "f2f294f8f0a21804d7dd6a23d7695b161723fcc1efea48b2f9d1ce7bcbb3f5be"
EXPECTED_V42_ARTIFACT_RAW_SHA256 = "0952111064db57f6c1122e9a7b4d45ee997667e0d57137ea173be0009ba4feec"
EXPECTED_V42_SPEC_SHA256 = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_V42_SPEC_RAW_SHA256 = "11b9d7a86fc1617f7c313c2cda58c4b8874d33cb9e4fe11460a65b8920e40674"
EXPECTED_V42_ENGINE_RAW_SHA256 = "3d73cddfc7c06cf6e0e5bc22a3ad29c3ea79ac22d7c1e5a8b1ca1044789c65ab"
EXPECTED_V42_SOURCE_RAW_SHA256 = "fc4b9ce991cc866aa7a9b809172df41227e9dcd133a41d210068663ee7bd77e9"
EXPECTED_V41_ARTIFACT_SHA256 = "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e"
EXPECTED_V41_ARTIFACT_RAW_SHA256 = "42a5d7caf4e9fab18e771b2bd55fc38c9a77f7fac42f2599feb4fe789cf88c07"
EXPECTED_V41_FREEZE_RAW_SHA256 = "43d3bd4e9cdcb54e9a7c1649430f6bd10cae9ef51ac5d77319a7630639b0c34f"
V41_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})
EXPECTED_SEEDS = [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
EXPECTED_SELECTOR_COUNTS = {
    "arbitrary_supports": 2_218,
    "bridge_cases": 8_826,
    "cleanup_cases": 264_328,
    "cleanup_failures": 0,
    "full_domain_joint_cases": 28,
    "full_domain_joint_failures": 0,
    "joint_component_cases": 2_218,
    "joint_component_failures": 0,
    "selector_cases": 264_328,
    "selector_failures": 0,
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _fmt(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "NOT AUTHENTICATED"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _strict_json(raw: bytes) -> dict[str, Any]:
    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError("V4.2 evidence must be a JSON object.")
    return payload


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scientific_validation_context() -> tuple[str, list[str]]:
    """Bind UI admission to V4.2 sources and all 159 V4.1 immutable paths."""

    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    registered: dict[str, str] = {
        "quantum_research_lab/PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json": EXPECTED_V42_SPEC_RAW_SHA256,
        "quantum_research_lab/phase3_v42_selector_engine.cpp": EXPECTED_V42_ENGINE_RAW_SHA256,
        "quantum_research_lab/phase3_v42_coined_walk_compiler.py": EXPECTED_V42_SOURCE_RAW_SHA256,
        "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json": EXPECTED_V41_ARTIFACT_RAW_SHA256,
        "FREEZE_CONTRACT_V4_1.json": EXPECTED_V41_FREEZE_RAW_SHA256,
    }
    freeze_path = root / "FREEZE_CONTRACT_V4_1.json"
    try:
        if _raw_sha(freeze_path) != EXPECTED_V41_FREEZE_RAW_SHA256:
            raise ValueError("V4.1 freeze raw identity mismatch.")
        freeze = _strict_json(freeze_path.read_bytes())
        frozen = freeze.get("frozen_files")
        if not isinstance(frozen, Mapping) or len(frozen) != 161:
            raise ValueError("V4.1 freeze inventory is not the registered 161-file set.")
        immutable = {
            str(relative): str(expected)
            for relative, expected in frozen.items()
            if str(relative) not in V41_SUCCESSOR_MUTABLE
        }
        if len(immutable) != 159:
            raise ValueError("V4.1 successor must authenticate exactly 159 immutable paths.")
        registered.update(immutable)
    except Exception as exc:
        errors.append(f"Unable to bind V4.2 UI to V4.1 freeze: {exc}")

    digest = hashlib.sha256()
    for relative, expected in sorted(registered.items()):
        digest.update(relative.encode("utf-8") + b"\0")
        try:
            candidate = (root / relative).resolve(strict=True)
            candidate.relative_to(root)
            actual = _raw_sha(candidate)
        except Exception as exc:
            actual = ""
            errors.append(f"Unable to authenticate {relative}: {exc}")
        if actual != expected:
            errors.append(f"Immutable scientific dependency mismatch: {relative}")
        digest.update(actual.encode("ascii") + b"\n")
    return digest.hexdigest(), list(dict.fromkeys(errors))


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_artifact_validation(
    raw_artifact: bytes,
    context_sha256: str,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        payload = _strict_json(raw_artifact)
        semantic = canonical_json_sha256(
            {key: value for key, value in payload.items() if key != "artifact_sha256"}
        )
        boundary = _mapping(payload.get("claim_boundary"))
        parent = _mapping(payload.get("parent"))
        support = _mapping(_mapping(payload.get("support_evidence")).get("aggregate"))
        resources = _mapping(_mapping(payload.get("resource_evidence")).get("aggregate"))
        decisions = _mapping(payload.get("decisions"))
        selector = _mapping(_mapping(payload.get("selector_control")).get("forward"))
        checks = {
            "artifact_raw_identity": hashlib.sha256(raw_artifact).hexdigest() == EXPECTED_V42_ARTIFACT_RAW_SHA256,
            "artifact_semantic_identity": semantic == payload.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA256,
            "context_identity": len(context_sha256) == 64,
            "sealed_sources": bool(
                payload.get("spec_sha256") == EXPECTED_V42_SPEC_SHA256
                and payload.get("spec_raw_file_sha256") == EXPECTED_V42_SPEC_RAW_SHA256
                and payload.get("engine_source_raw_file_sha256") == EXPECTED_V42_ENGINE_RAW_SHA256
                and payload.get("source_sha256") == EXPECTED_V42_SOURCE_RAW_SHA256
            ),
            "parent_identity": bool(
                parent.get("artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA256
                and parent.get("artifact_raw_file_sha256") == EXPECTED_V41_ARTIFACT_RAW_SHA256
                and parent.get("freeze_raw_file_sha256") == EXPECTED_V41_FREEZE_RAW_SHA256
                and parent.get("immutable_file_count") == 159
                and parent.get("immutable_files_exact") is True
            ),
            "selector_control": bool(
                _mapping(payload.get("selector_control")).get("stable_replay_match") is True
                and all(selector.get(name) == value for name, value in EXPECTED_SELECTOR_COUNTS.items())
            ),
            "support_gate": bool(
                support.get("seed_count") == 8
                and support.get("all_pair_positions_preserved") is True
                and support.get("all_seeds_connected") is True
                and support.get("parent_selected_bridge_count") == 3
            ),
            "resource_gate": bool(
                resources.get("all_eight_seeds_pass") is True
                and resources.get("budget_cnot") == 2_500_000
                and resources.get("maximum_selected_model_cnot") == 1_135_430
                and resources.get("minimum_budget_margin_cnot") == 1_364_570
            ),
            "decision_gate": bool(
                decisions.get("overall") == "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED"
                and decisions.get("resource_architecture_decision") == "PASSED_SELECTED_MODEL_CNOT_BUDGET"
                and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED"
            ),
            "boundary_gate": bool(
                payload.get("research_classification") == "RESEARCH_ONLY"
                and boundary.get("provider_sdk_imported") is False
                and boundary.get("provider_credentials_read") is False
                and boundary.get("provider_calls") == 0
                and boundary.get("qpu_jobs_submitted") == 0
                and boundary.get("hardware_executable") is False
                and boundary.get("backend_transpilation") == "NOT_RUN"
                and boundary.get("circuit_materialization") == "NOT_RUN_NEXT_GATE"
                and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            ),
        }
    except Exception as exc:
        payload = {}
        errors.append(str(exc))
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "payload": payload,
        "valid": bool(checks) and not errors and not failed,
    }


def load_v42_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v42_artifact_path()
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return {}, {"valid": False, "errors": [str(exc)], "failed_checks": ["artifact_read"]}
    context_sha, context_errors = _scientific_validation_context()
    report = _cached_artifact_validation(raw, context_sha)
    errors = list(context_errors) + list(report.get("errors") or [])
    failed = list(report.get("failed_checks") or [])
    if context_errors:
        failed.append("immutable_scientific_context")
    return dict(_mapping(report.get("payload"))), {
        "checks": report.get("checks") or {},
        "context_sha256": context_sha,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": list(dict.fromkeys(failed)),
        "valid": report.get("valid") is True and not context_errors,
    }


def normalize_v42_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    source = _mapping(artifact)
    authenticated = bool(
        source
        and artifact_integrity
        and spec_integrity
        and parent_integrity
        and source.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA256
    )
    if not authenticated:
        return {
            "artifact": {},
            "artifact_sha256": "MASKED",
            "authenticated": False,
            "decisions": {},
            "next_gate": "V42_EVIDENCE_AUTHENTICATION_REQUIRED",
            "overall": "V42_EVIDENCE_UNAVAILABLE_FAIL_CLOSED",
            "resource_aggregate": {},
            "resource_rows": [],
            "selector": {},
            "support_aggregate": {},
            "support_rows": [],
        }
    decisions = _mapping(source.get("decisions"))
    resource_evidence = _mapping(source.get("resource_evidence"))
    support_evidence = _mapping(source.get("support_evidence"))
    return {
        "artifact": dict(source),
        "artifact_sha256": str(source.get("artifact_sha256", "")),
        "authenticated": True,
        "decisions": dict(decisions),
        "next_gate": str(decisions.get("next_falsifiable_gate", "")),
        "overall": str(decisions.get("overall", "")),
        "resource_aggregate": dict(_mapping(resource_evidence.get("aggregate"))),
        "resource_rows": _rows(resource_evidence.get("seed_rows")),
        "selector": dict(_mapping(source.get("selector_control"))),
        "support_aggregate": dict(_mapping(support_evidence.get("aggregate"))),
        "support_rows": _rows(support_evidence.get("seed_rows")),
    }


def _resource_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for row in state.get("resource_rows") or []:
        step = _mapping(row.get("selected_model_step_resources"))
        oracle = _mapping(_mapping(row.get("feasibility_oracle")).get("resources"))
        rows.append({
            "Seed": row.get("seed"),
            "CNOT / complete step": step.get("selected_model_cnot"),
            "Budget margin": row.get("budget_margin_cnot"),
            "Logical qubits": row.get("logical_qubits_with_recycled_workspace"),
            "Feasibility oracle CNOT": oracle.get("selected_model_cnot"),
            "Oracle invocations": row.get("feasibility_oracle_invocations"),
            "SELECT scaffold CNOT": _mapping(_mapping(row.get("select_scaffold")).get("resources")).get("selected_model_cnot"),
            "Bridge CNOT": row.get("bridge_selected_model_cnot"),
            "Bridges": len(_rows(row.get("bridge_ir"))),
            "Decision": row.get("decision"),
            "Seed ledger SHA": row.get("seed_walk_sha256"),
        })
    return pd.DataFrame(rows)


def _support_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Seed": row.get("seed"),
            "Data vertices": row.get("authenticated_feasible_data_vertices"),
            "V4.1 one-swap edges": row.get("authenticated_one_swap_edges"),
            "Coin states / vertex": row.get("coin_basis_states"),
            "Joint vertices": row.get("joint_promise_vertices"),
            "Coin-ring edges": row.get("coin_ring_support_edges"),
            "Selector edges": row.get("selector_one_swap_support_edges"),
            "Replicated bridge edges": row.get("replicated_bridge_support_edges"),
            "Joint support edges": row.get("joint_support_edges"),
            "Components": row.get("joint_component_count"),
            "All pair positions": row.get("addressed_pair_positions_preserved"),
            "Support SHA": row.get("seed_support_sha256"),
        }
        for row in state.get("support_rows") or []
    ])


def _macro_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for row in state.get("resource_rows") or []:
        oracle = _mapping(row.get("feasibility_oracle"))
        terms = _mapping(oracle.get("macro_terms"))
        complete = _mapping(_mapping(row.get("independent_cnot_formula_replay")).get("terms"))
        rows.append({
            "Seed": row.get("seed"),
            "Widths": " / ".join(str(value) for value in row.get("constraint_register_widths") or []),
            "Oracle controlled adds": sum(int(value) for value in _mapping(terms.get("controlled_add_by_width")).values()),
            "Oracle comparators": sum(int(value) for value in _mapping(terms.get("comparator_by_width")).values()),
            "Oracle MCX": sum(int(value) for value in _mapping(terms.get("mcx_by_controls")).values()),
            "Complete direct CNOT": complete.get("direct_cnot"),
            "SELECT CCX": _mapping(row.get("select_scaffold")).get("ccx_count"),
            "Pair labels retained": row.get("addressed_pair_positions_preserved"),
            "Formula replay": _mapping(row.get("independent_cnot_formula_replay")).get("match"),
        })
    return pd.DataFrame(rows)


def _selector_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    selector = _mapping(state.get("selector"))
    forward = _mapping(selector.get("forward"))
    reverse = _mapping(selector.get("reverse"))
    labels = (
        ("Arbitrary supports", "arbitrary_supports"),
        ("SELECT cases", "selector_cases"),
        ("SELECT failures", "selector_failures"),
        ("Cleanup cases", "cleanup_cases"),
        ("Cleanup failures", "cleanup_failures"),
        ("Joint-component cases", "joint_component_cases"),
        ("Joint-component failures", "joint_component_failures"),
        ("Full-domain joint cases", "full_domain_joint_cases"),
        ("Full-domain failures", "full_domain_joint_failures"),
        ("Hamming-4 bridge cases", "bridge_cases"),
    )
    return pd.DataFrame([
        {
            "Control": label,
            "Forward": forward.get(key),
            "Reverse": reverse.get(key),
            "Exact match": forward.get(key) == reverse.get(key),
        }
        for label, key in labels
    ])


def render_v42_coined_walk_compiler_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v42_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
    )
    ok = bool(state["authenticated"])
    resources = _mapping(state.get("resource_aggregate"))
    support = _mapping(state.get("support_aggregate"))
    section_header(
        "V4.2 Indexed Coined-Walk Compiler & Research Admission",
        "V4.1 CONNECTED SUPPORT → ONE-HOT ADDRESSING → SHARED EXACT ARITHMETIC → 1.135M CNOT MAX → RESEARCH GENERATOR ADMITTED",
        "V4.2 preserves every exchange position, shares one exact feasibility oracle across persistent one-hot address registers, and passes the unchanged selected-model resource gate on all eight frozen seeds. The admission ends at provider-neutral research architecture: circuit materialization, transpilation, hardware and performance remain outside the evidence boundary.",
    )
    st.markdown(
        """<style>
        .qv42-shell{position:relative;overflow:hidden;border:1px solid rgba(87,244,214,.42);border-radius:25px;padding:23px 24px;margin:10px 0 14px;background:radial-gradient(circle at 86% 5%,rgba(54,255,179,.19),transparent 30%),radial-gradient(circle at 8% 96%,rgba(80,101,255,.20),transparent 34%),linear-gradient(130deg,rgba(1,20,30,.99),rgba(10,20,49,.98) 58%,rgba(36,12,51,.97));box-shadow:0 0 62px rgba(66,238,207,.12)}
        .qv42-shell:after{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 34%,rgba(133,255,229,.045) 49%,transparent 64%);transform:translateX(-100%);animation:qv42scan 12s linear infinite;pointer-events:none}@keyframes qv42scan{to{transform:translateX(100%)}}
        .qv42-k{font-size:.61rem;letter-spacing:.19em;color:#73ffe0;font-weight:950}.qv42-title{font-size:1.23rem;color:#f7fbff;font-weight:950;margin:7px 0}.qv42-copy{font-size:.75rem;color:#adbed0;line-height:1.52}.qv42-tags{font-size:.59rem;color:#9fb4c8;letter-spacing:.105em;margin-top:11px}.qv42-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:11px 0 16px}.qv42-card{border:1px solid rgba(102,236,212,.19);background:rgba(2,17,29,.82);border-radius:15px;padding:12px}.qv42-label{font-size:.49rem;color:#859db3;letter-spacing:.115em;font-weight:900}.qv42-value{font-size:.87rem;color:#f6faff;font-weight:950;margin:5px 0;overflow-wrap:anywhere}.qv42-pass{color:#78f0ba}.qv42-warn{color:#ffd18a}.qv42-block{color:#ff9da9}.qv42-note{font-size:.60rem;color:#91a7ba;line-height:1.38}.qv42-flow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;margin:12px 0 17px}.qv42-node{border:1px solid rgba(114,237,214,.18);border-radius:12px;padding:10px;background:rgba(5,18,31,.76);font-size:.61rem;color:#aabbd0;line-height:1.35}.qv42-node b{display:block;color:#eaf8ff;margin-bottom:4px}.qv42-arrow{color:#6ff4d5}@media(max-width:1120px){.qv42-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.qv42-flow{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:600px){.qv42-grid,.qv42-flow{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div class="qv42-shell" data-qv42-surface="coined-walk-compiler" data-qv42-release="4.2" data-qv42-auth="{'pass' if ok else 'fail'}" data-qv42-support="{'CONNECTED' if ok else 'INDETERMINATE'}" data-qv42-resource="{'PASSED' if ok else 'INDETERMINATE'}" data-qv42-production="{'RESEARCH_ADMITTED' if ok else 'BLOCKED'}" data-qv42-hardware="false" data-qv42-jobs="0" data-qv42-provider-calls="0" data-qv42-circuit="NOT_RUN_NEXT_GATE" data-qv42-promise="EXACT_FEASIBLE_DATA_X_TWO_ONE_HOT_COIN_REGISTERS">
        <div class="qv42-k">V4.2 · INDEXED COINED-WALK COMPILER · PROOF-CARRYING RESEARCH ADMISSION</div>
        <div class="qv42-title">{escape(state['overall'])}</div>
        <div class="qv42-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT / UNPINNED'} · SHA {escape(state['artifact_sha256'])}<br>Support: {escape(str(_mapping(state.get('decisions')).get('generator_support_decision', 'MASKED')))}<br>Resources: {escape(str(_mapping(state.get('decisions')).get('resource_architecture_decision', 'MASKED')))} · production: {escape(str(_mapping(state.get('decisions')).get('production_admission', 'MASKED')))}</div>
        <div class="qv42-tags">RESEARCH_ONLY · PROMISE-SUBSPACE CERTIFICATE · PROVIDER FREE · CIRCUIT NOT RUN · HARDWARE FALSE · ADVANTAGE NOT CLAIMED</div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div class="qv42-grid">
        <div class="qv42-card"><div class="qv42-label">ARTIFACT AUTH</div><div class="qv42-value {'qv42-pass' if ok else 'qv42-block'}">{'PASS' if ok else 'NOT AUTHENTICATED'}</div><div class="qv42-note">raw + semantic + 159 immutable parent paths</div></div>
        <div class="qv42-card"><div class="qv42-label">PAIR POSITIONS</div><div class="qv42-value qv42-pass">{'780 / 780' if ok else 'MASKED'}</div><div class="qv42-note">no favorable label deletion</div></div>
        <div class="qv42-card"><div class="qv42-label">COIN BASIS / DATA</div><div class="qv42-value">{escape(_fmt(support.get('coin_basis_states_per_data_vertex')))}</div><div class="qv42-note">40 × 40 ordered addresses</div></div>
        <div class="qv42-card"><div class="qv42-label">JOINT CONNECTIVITY</div><div class="qv42-value qv42-pass">{'8 / 8 PASS' if ok else 'MASKED'}</div><div class="qv42-note">one component per frozen seed</div></div>
        <div class="qv42-card"><div class="qv42-label">MAX CNOT / STEP</div><div class="qv42-value qv42-pass">{escape(_fmt(resources.get('maximum_selected_model_cnot')))}</div><div class="qv42-note">maximum, never mean</div></div>
        <div class="qv42-card"><div class="qv42-label">MIN BUDGET MARGIN</div><div class="qv42-value qv42-pass">+{escape(_fmt(resources.get('minimum_budget_margin_cnot')))}</div><div class="qv42-note">vs immutable 2,500,000 gate</div></div>
        <div class="qv42-card"><div class="qv42-label">V4.1 → V4.2 REDUCTION</div><div class="qv42-value qv42-pass">{'92.75%' if ok else 'MASKED'}</div><div class="qv42-note">selected-model maximum comparison</div></div>
        <div class="qv42-card"><div class="qv42-label">LOGICAL QUBIT BOUND</div><div class="qv42-value">{escape(_fmt(resources.get('maximum_logical_qubits_with_recycled_workspace')))}</div><div class="qv42-note">recycled clean workspace model</div></div>
        <div class="qv42-card"><div class="qv42-label">SELECTOR CASES</div><div class="qv42-value">{'264,328' if ok else 'MASKED'}</div><div class="qv42-note">two C++ traversals · zero failures</div></div>
        <div class="qv42-card"><div class="qv42-label">CIRCUIT / HARDWARE</div><div class="qv42-value qv42-block">NOT RUN / FALSE</div><div class="qv42-note">provider calls 0 · QPU jobs 0</div></div></div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """<div class="qv42-flow">
        <div class="qv42-node"><b>1 · V4.1 parent</b>Connected data support + 3 exact bridges</div>
        <div class="qv42-node"><b>2 · One-hot coin</b>Two 40-qubit cyclic address rings</div>
        <div class="qv42-node"><b>3 · Shared SELECT</b>One exact target oracle for all 780 positions</div>
        <div class="qv42-node"><b>4 · Resource gate</b><span class="qv42-arrow">PASS</span> · 1.135M ≤ 2.5M</div>
        <div class="qv42-node"><b>5 · Current tier</b>Provider-neutral research generator admitted</div>
        <div class="qv42-node"><b>6 · Next gate</b>Circuit materialization + reversible simulation</div>
        </div>""",
        unsafe_allow_html=True,
    )

    if ok:
        st.success("RESOURCE ARCHITECTURE · PASS — every frozen seed remains below 2,500,000 selected-model CNOT; the worst case is seed 7703 at 1,135,430.")
        st.success("JOINT PROMISE SUPPORT · CONNECTED — all 780 pair positions are retained and the three authenticated V4.1 bridges are preserved.")
        st.info("SELECTOR CONTROL · 264,328 / 264,328 cases, two traversal orders, zero involution, cleanup or component-correspondence failures.")
        st.warning("RESEARCH GENERATOR ADMITTED ≠ EXECUTABLE CIRCUIT — materialization, reversible simulation, routing, noise, calibration, runtime and optimization performance have not been run.")
    else:
        st.error("V4.2 evidence is absent, invalid or unpinned. Support, resources, admission and downloads remain masked fail-closed.")

    resource_ledger = _resource_ledger(state)
    st.markdown("**Eight-seed exact selected-model resource ledger · complete coined-walk step**")
    st.dataframe(resource_ledger, width="stretch", hide_index=True)
    if ok and not resource_ledger.empty:
        chart = resource_ledger[["Seed", "CNOT / complete step", "Budget margin"]].set_index("Seed")
        st.markdown("**CNOT numerator and remaining immutable budget by seed**")
        st.bar_chart(chart, width="stretch")

    support_ledger = _support_ledger(state)
    st.markdown("**Joint data × coin support certificate ledger**")
    st.dataframe(support_ledger, width="stretch", hide_index=True)
    if ok:
        st.caption(
            "Aggregate joint promise support · "
            f"{_fmt(support.get('joint_promise_vertices'))} vertices · "
            f"{_fmt(support.get('joint_support_edges'))} registered support edges."
        )
    if ok and not support_ledger.empty:
        chart = support_ledger[["Seed", "Joint vertices", "Joint support edges"]].set_index("Seed")
        chart = chart.apply(lambda column: column.map(lambda value: math.log10(max(1, int(value)))))
        st.markdown("**Joint certificate scale by seed · log10 counts**")
        st.bar_chart(chart, width="stretch")

    macro_ledger = _macro_ledger(state)
    st.markdown("**Proof-carrying macro ledger · no cross-position arithmetic duplication**")
    st.dataframe(macro_ledger, width="stretch", hide_index=True)
    selector_ledger = _selector_ledger(state)
    st.markdown("**Dual-traversal independent C++ selector certificate**")
    st.dataframe(selector_ledger, width="stretch", hide_index=True)

    obligations = pd.DataFrame(
        [
            ("V4.1 immutable lineage", "Spec + engine + compiler + artifact + freeze + 159 immutable paths", "PASS" if ok else "NOT AUTHENTICATED"),
            ("No pair-position deletion", "All 780 ordered-label positions addressable", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Promise SELECT involution", "Every nonempty support through N=5; dual traversal", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Clean target symmetry", "Compute / accepted move / reverse recompute", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Joint connectivity", "Coin Cartesian support + exact V4.1 data support", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Selected-model resource gate", "Maximum across all eight seeds ≤ 2.5M CNOT", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Circuit materialization", "Backend-agnostic gate list and reversible simulation", "NEXT GATE · NOT RUN"),
            ("Backend transpilation", "Named topology, native basis and routing", "NOT RUN"),
            ("Hardware execution", "Provider credentials, calls and QPU jobs", "BLOCKED · 0 JOBS"),
            ("Optimization / advantage", "Objective quality and quantum-classical comparison", "NOT TESTED / NOT CLAIMED"),
        ],
        columns=["Evidence obligation", "Method / scope", "State"],
    )
    st.markdown("**Admission matrix · proof layers remain non-substitutable**")
    st.dataframe(obligations, width="stretch", hide_index=True)

    with st.expander("Architecture contract · one-hot indexed exact-feasibility walk", expanded=False):
        st.markdown("**EXACT_ONE_HOT_COINED_TARGET_RECOMPUTE_ARITHMETIC_WITH_DATA_ONLY_BRIDGES_V1**")
        st.markdown(
            "REMOVE_ADDRESS and ADD_ADDRESS are persistent 40-qubit one-hot registers. Their cyclic XY rings connect all 1,600 ordered address states. SELECT constructs an addressed target, evaluates one shared seven-band exact predicate, applies only accepted exchanges, and clears work through the reverse target on the certified promise subspace."
        )
        st.markdown("**PROMISE · EXACT-FEASIBLE N=40, K=10 DATA × TWO ONE-HOT COIN REGISTERS**")
        st.markdown("**SELECTED MODEL · CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1**")

    with st.expander("Scientific boundary · what V4.2 does not establish", expanded=True):
        st.markdown(
            "V4.2 establishes a structural support theorem and an exact ledger in one selected decomposition model. It does not establish off-promise cleanliness, a materialized circuit, a native backend circuit, a routing cost, a device error rate, an optimization benefit, runtime superiority, hardware execution or quantum advantage."
        )

    for label, suffix, help_text in (
        ("Recompute sealed V4.2 evidence", "recompute", "The release UI serves immutable evidence only."),
        ("Delete unfavorable pair positions", "position_delete", "All 780 positions are preregistered and preserved."),
        ("Relax one-hot promise", "promise", "Off-promise behavior is not certified."),
        ("Override selected-model CNOT gate", "budget", "The 2,500,000 maximum gate is immutable."),
        ("Claim a materialized executable circuit", "circuit", "Circuit materialization is the next falsifiable gate."),
        ("Select a named backend", "backend", "Backend work is outside this evidence tier."),
        ("Read provider credentials", "credentials", "No provider credential may be read."),
        ("Submit a QPU job", "qpu", "Hardware execution is not authorized."),
    ):
        st.button(label, disabled=True, key=f"{key_prefix}_v42_{suffix}", help=help_text)

    if ok:
        artifact_bytes = (
            json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        st.download_button(
            "Download sealed V4.2 coined-walk compiler artifact",
            data=artifact_bytes,
            file_name="SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v42_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V4.2 frozen compiler specification",
                data=(json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
                file_name="PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v42_spec_download",
            )
        for label, frame, filename, suffix in (
            ("Download V4.2 resource ledger CSV", resource_ledger, "QUANTUM_LAB_V4_2_RESOURCE_LEDGER.csv", "resource"),
            ("Download V4.2 support ledger CSV", support_ledger, "QUANTUM_LAB_V4_2_SUPPORT_LEDGER.csv", "support"),
            ("Download V4.2 macro ledger CSV", macro_ledger, "QUANTUM_LAB_V4_2_MACRO_LEDGER.csv", "macro"),
            ("Download V4.2 selector-control ledger CSV", selector_ledger, "QUANTUM_LAB_V4_2_SELECTOR_CONTROL.csv", "selector"),
        ):
            st.download_button(
                label,
                data=frame.to_csv(index=False).encode("utf-8"),
                file_name=filename,
                mime="text/csv",
                key=f"{key_prefix}_v42_{suffix}_download",
            )

    st.warning(
        "V4.2 CLAIM BOUNDARY · EXACT PROMISE-SUBSPACE SUPPORT + PROVIDER-NEUTRAL SELECTED-MODEL RESOURCE SCREEN ONLY. CIRCUIT MATERIALIZATION, BACKEND TRANSPILATION, HARDWARE EXECUTION AND OPTIMIZATION PERFORMANCE ARE NOT RUN."
    )
    st.markdown(f"**NEXT FALSIFIABLE GATE · {escape(state['next_gate'])}**")
    st.markdown("**CIRCUIT MATERIALIZATION · NOT RUN · BACKEND TRANSPILATION · NOT RUN**")
    st.markdown("**HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0 · PROVIDER CALLS · 0**")
    st.markdown("**QUANTUM ADVANTAGE · NOT CLAIMED**")
    return state


def apply_v42_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if encoding is None:
        return None
    projected = dict(encoding)
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True:
        return projected
    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    support = _mapping(_mapping(source.get("support_evidence")).get("aggregate"))
    resources = _mapping(_mapping(source.get("resource_evidence")).get("aggregate"))
    projected.update({
        "v42_artifact_sha": source.get("artifact_sha256"),
        "v42_generator_support_decision": decisions.get("generator_support_decision"),
        "v42_resource_architecture_decision": decisions.get("resource_architecture_decision"),
        "v42_production_admission": decisions.get("production_admission"),
        "v42_next_falsifiable_gate": decisions.get("next_falsifiable_gate"),
        "v42_joint_support_connected": support.get("all_seeds_connected"),
        "v42_all_pair_positions_preserved": support.get("all_pair_positions_preserved"),
        "v42_maximum_selected_model_cnot": resources.get("maximum_selected_model_cnot"),
        "v42_minimum_budget_margin_cnot": resources.get("minimum_budget_margin_cnot"),
        "v42_maximum_logical_qubits": resources.get("maximum_logical_qubits_with_recycled_workspace"),
        "logical_qubits_min": resources.get("maximum_logical_qubits_with_recycled_workspace"),
        "encoding_status": "V4.2 RESEARCH GENERATOR ADMITTED · CIRCUIT MATERIALIZATION NEXT · HARDWARE BLOCKED",
        "hardware_executable": False,
        "circuit_materialization": "NOT_RUN_NEXT_GATE",
        "backend_transpilation": "NOT_RUN",
        "provider_calls": 0,
        "qpu_jobs_submitted": 0,
        "quantum_advantage": "NOT_CLAIMED",
    })
    return projected


__all__ = [
    "EXPECTED_V42_ARTIFACT_RAW_SHA256",
    "EXPECTED_V42_ARTIFACT_SHA256",
    "EXPECTED_V42_SPEC_SHA256",
    "apply_v42_encoding_state",
    "load_v42_ui_artifact",
    "normalize_v42_artifact",
    "render_v42_coined_walk_compiler_panel",
]
