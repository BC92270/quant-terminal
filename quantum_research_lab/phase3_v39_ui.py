"""Institutional, fail-closed V3.9 N40 reversible-IR surface."""

from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v39_scalable_reversible_ir import (
    BUDGET_CNOT,
    canonical_json_sha256,
    default_v39_artifact_path,
)


SectionHeader = Callable[[str, str, str], None]
EXPECTED_V39_ARTIFACT_SHA256 = "26856f1e26bed5dc5b9a6d6af7bb25c53ef0b25188d8c787276afbeb08027775"
EXPECTED_V39_ARTIFACT_RAW_SHA256 = "38d2d16856f1930f1f86848929a4341cab18e02edf387208debc6cd5213aed29"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in value] if isinstance(value, list) and all(isinstance(row, Mapping) for row in value) else []


def _fmt(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "NOT AUTHENTICATED"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def load_v39_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind the interactive surface to the exact offline-validated artifact."""

    target = Path(path) if path is not None else default_v39_artifact_path()
    errors: list[str] = []
    try:
        raw = target.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, {"valid": False, "errors": [str(exc)]}
    if not isinstance(payload, dict):
        return {}, {"valid": False, "errors": ["V3.9 artifact must be a JSON object."]}
    try:
        semantic = canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError) as exc:
        return payload, {"valid": False, "errors": [str(exc)]}
    raw_sha = hashlib.sha256(raw).hexdigest()
    parent = _mapping(_mapping(payload.get("parent")).get("authentication"))
    decisions = _mapping(payload.get("decisions"))
    boundary = _mapping(payload.get("claim_boundary"))
    if payload.get("artifact_sha256") != semantic:
        errors.append("V3.9 artifact self-hash mismatch.")
    if semantic != EXPECTED_V39_ARTIFACT_SHA256:
        errors.append("V3.9 semantic identity mismatch.")
    if raw_sha != EXPECTED_V39_ARTIFACT_RAW_SHA256:
        errors.append("V3.9 raw-file identity mismatch.")
    if parent.get("valid") is not True:
        errors.append("V3.9 sealed parent chain is not authenticated.")
    if decisions.get("overall") != "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED":
        errors.append("V3.9 bounded decision mismatch.")
    if not (
        boundary.get("complete_global_connectivity") == "INDETERMINATE"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
    ):
        errors.append("V3.9 claim boundary mismatch.")
    return payload, {
        "valid": not errors,
        "errors": errors,
        "semantic_sha256": semantic,
        "raw_file_sha256": raw_sha,
    }


def normalize_v39_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    screen = _mapping(source.get("resource_screen"))
    aggregate = _mapping(source.get("aggregate_evidence"))
    coverage = _mapping(source.get("coverage_counts_out_of_8"))
    boundary = _mapping(source.get("claim_boundary"))
    parent = _mapping(_mapping(source.get("parent")).get("authentication"))
    try:
        self_hash = canonical_json_sha256({key: value for key, value in source.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError):
        self_hash = ""
    authenticated = bool(
        artifact_integrity is True
        and spec_integrity is True
        and parent_integrity is True
        and parent.get("valid") is True
        and source.get("artifact_sha256") == self_hash == EXPECTED_V39_ARTIFACT_SHA256
        and decisions.get("overall") == "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED"
        and decisions.get("complete_global_connectivity") == "INDETERMINATE"
        and screen.get("decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        and len(_rows(source.get("seed_rows"))) == 8
        and aggregate.get("edge_seed_positions") == 6_240
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    )
    reveal = lambda value: value if authenticated else None
    return {
        "authenticated": authenticated,
        "artifact": dict(source) if authenticated else {},
        "artifact_sha256": str(source.get("artifact_sha256")) if authenticated else "NOT AUTHENTICATED",
        "overall": str(decisions.get("overall")) if authenticated else "NOT AUTHENTICATED",
        "reversible_ir": str(decisions.get("reversible_ir_decision")) if authenticated else "NOT AUTHENTICATED",
        "budget_decision": str(decisions.get("budget_decision")) if authenticated else "NOT AUTHENTICATED",
        "production_admission": str(decisions.get("production_admission")) if authenticated else "NOT AUTHENTICATED",
        "next_gate": str(decisions.get("next_falsifiable_gate")) if authenticated else "NOT AUTHENTICATED",
        "maximum_cnot": reveal(screen.get("maximum_selected_model_cnot")),
        "minimum_margin": reveal(screen.get("minimum_budget_margin_cnot")),
        "seed_rows": _rows(source.get("seed_rows")) if authenticated else [],
        "coverage": dict(coverage) if authenticated else {},
        "aggregate": dict(aggregate) if authenticated else {},
        "boundary": dict(boundary) if authenticated else {},
    }


def _seed_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("seed_rows") or []:
        proof = _mapping(row.get("proof_states"))
        resources = _mapping(row.get("resources"))
        widths = "/".join(str(item.get("width")) for item in _rows(row.get("constraint_registers")))
        rows.append(
            {
                "Seed": row.get("seed"),
                "Instance": row.get("instance_id"),
                "Parent": "PASS" if proof.get("authenticated_seed_contract") else "FAIL",
                "Range widths": widths,
                "Reversible IR": "PASS" if proof.get("scalable_reversible_ir") else "FAIL",
                "Dead-edge certificate": row.get("certified_identity_count"),
                "Live rotations": row.get("live_edge_count"),
                "Ordered positions": row.get("edge_count"),
                "Elementary": "PASS" if proof.get("elementary_lowering") else "FAIL",
                "Template equivalence": "PASS" if proof.get("template_equivalence") else "FAIL",
                "Clean scratch": "PASS" if proof.get("clean_scratch_proof") else "FAIL",
                "Coherent pair action": "PASS" if proof.get("feasible_support_coherent_pair_action") else "FAIL",
                "Selected CNOT": resources.get("selected_model_cnot"),
                "Budget margin": row.get("budget_margin_cnot"),
                "2.5M gate": row.get("budget_decision"),
                "Decision": row.get("decision"),
            }
        )
    return pd.DataFrame(rows)


def _register_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed in state.get("seed_rows") or []:
        for register in _rows(seed.get("constraint_registers")):
            rows.append(
                {
                    "Seed": seed.get("seed"),
                    "Register": register.get("name"),
                    "Width": register.get("width"),
                    "Signed": register.get("signed"),
                    "Role": register.get("role"),
                    "Initial state": register.get("initial_state"),
                    "Final state": register.get("final_state"),
                    "Compute": "CONDITIONAL NORMALIZE",
                    "Uncompute": "AFTER GUARD / USING NEW ORIENTATION",
                    "Reuse window": "ONE EDGE POSITION",
                    "Peak live": _mapping(seed.get("resources")).get("logical_qubits_with_clean_decomposition_ancillas"),
                }
            )
    return pd.DataFrame(rows)


def render_v39_scalable_ir_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v39_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
    )
    section_header(
        "V3.9 Scalable N40 Reversible IR & Selected-Model Admission",
        "WIDTHS → CANONICAL CACHE → SYMMETRIC GUARD → ORDERED LAYER → RESOURCE SCREEN",
        "All eight N=40 seed contracts receive a proof-carrying reversible macro IR. "
        "The selected-model resource screen is exact for that frozen architecture; connectivity remains separate.",
    )
    st.markdown(
        """<style>
        .qv39-shell{border:1px solid rgba(93,233,255,.34);border-radius:21px;padding:20px 21px;margin:10px 0 14px;background:radial-gradient(circle at 93% 5%,rgba(255,79,151,.16),transparent 29%),linear-gradient(130deg,rgba(2,21,35,.99),rgba(14,16,47,.98) 56%,rgba(42,12,43,.96));box-shadow:0 0 48px rgba(59,211,255,.09)}
        .qv39-k{font-size:.61rem;letter-spacing:.18em;color:#72edff;font-weight:950}.qv39-title{font-size:1.16rem;color:#ffb4ba;font-weight:950;margin:7px 0}.qv39-copy{font-size:.74rem;color:#a9b8cc;line-height:1.5}.qv39-tags{font-size:.62rem;color:#99acc8;letter-spacing:.10em;margin-top:10px}.qv39-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:11px 0 16px}.qv39-card{border:1px solid rgba(104,207,255,.17);background:rgba(3,15,29,.78);border-radius:14px;padding:12px}.qv39-label{font-size:.51rem;color:#8499b8;letter-spacing:.12em;font-weight:900}.qv39-value{font-size:.88rem;color:#f7f9ff;font-weight:950;margin:5px 0}.qv39-pass{color:#76edbe}.qv39-reject{color:#ffaaa9}.qv39-warn{color:#ffd18b}.qv39-note{font-size:.62rem;color:#91a4ba;line-height:1.38}@media(max-width:960px){.qv39-grid{grid-template-columns:1fr 1fr}}@media(max-width:520px){.qv39-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    ok = bool(state["authenticated"])
    st.markdown(
        f"""<div class="qv39-shell" data-qv39-surface="scalable-ir-admission" data-qv39-release="3.9" data-qv39-role="overall-decision" data-qv39-connectivity="INDETERMINATE" data-qv39-hardware="false" data-qv39-provider-calls="0">
        <div class="qv39-k">V3.9 · SCALABLE N40 REVERSIBLE IR &amp; SELECTED-MODEL ADMISSION</div>
        <div class="qv39-title">{escape(state['overall'])}</div>
        <div class="qv39-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT'} · SHA {escape(state['artifact_sha256'])}<br>Exact IR result: {escape(state['reversible_ir'])} · resource result: {escape(state['budget_decision'])}</div>
        <div class="qv39-tags">RESEARCH_ONLY · OFFLINE · PROVIDER_FREE · CONNECTIVITY_INDETERMINATE · HARDWARE_EXECUTABLE FALSE</div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**V3.9 · SCALABLE N40 REVERSIBLE IR & SELECTED-MODEL ADMISSION**")
    aggregate = _mapping(state.get("aggregate"))
    st.markdown(
        f"""<div class="qv39-grid">
        <div class="qv39-card" data-qv39-metric="artifact-auth"><div class="qv39-label">ARTIFACT AUTH</div><div class="qv39-value {'qv39-pass' if ok else 'qv39-reject'}">{'PASS' if ok else 'NOT AUTHENTICATED'}</div><div class="qv39-note">raw + semantic + parent chain</div></div>
        <div class="qv39-card" data-qv39-metric="ir-coverage"><div class="qv39-label">SCALABLE IR COVERAGE</div><div class="qv39-value qv39-pass">{'8 / 8' if ok else 'NOT AUTHENTICATED'}</div><div class="qv39-note">6,240 ordered edge-seed positions</div></div>
        <div class="qv39-card"><div class="qv39-label">LIVE / IDENTITY</div><div class="qv39-value">{escape(_fmt(aggregate.get('live_edge_positions')))} / {escape(_fmt(aggregate.get('certified_identity_positions')))}</div><div class="qv39-note">identity only with exact empty-overlap proof</div></div>
        <div class="qv39-card"><div class="qv39-label">CLEAN SCRATCH</div><div class="qv39-value qv39-pass">{'8 / 8' if ok else 'NOT AUTHENTICATED'}</div><div class="qv39-note">caches update; only scratch returns to zero</div></div>
        <div class="qv39-card" data-qv39-metric="selected-cnot"><div class="qv39-label">MAX SELECTED CNOT</div><div class="qv39-value qv39-reject">{escape(_fmt(state['maximum_cnot']))}</div><div class="qv39-note">maximum across eight complete layers</div></div>
        <div class="qv39-card" data-qv39-metric="budget-gate"><div class="qv39-label">2.5M BUDGET GATE</div><div class="qv39-value qv39-reject">{escape(state['budget_decision'])}</div><div class="qv39-note">margin {escape(_fmt(state['minimum_margin']))} CNOT</div></div>
        <div class="qv39-card"><div class="qv39-label">GLOBAL CONNECTIVITY</div><div class="qv39-value qv39-warn">INDETERMINATE</div><div class="qv39-note">ordered coverage is not ergodicity</div></div>
        <div class="qv39-card"><div class="qv39-label">HARDWARE / JOBS</div><div class="qv39-value qv39-reject">BLOCKED / ZERO</div><div class="qv39-note">no provider SDK, credentials or calls</div></div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**N=40 · K=10 · BANDS · 7 HARD CONSTRAINTS · 8 FROZEN SEEDS**")
    st.markdown("**STATIC DEAD-EDGE CERTIFICATE · 2,020 / 6,240 IDENTITY POSITIONS**")
    st.markdown("**ORDERED 780-EDGE LAYER · COMPLETE ON 8 / 8 SEEDS**")
    st.markdown("**POST-OBSERVATION MODEL SWITCHING · PROHIBITED**")
    if ok:
        st.success("N40 REVERSIBLE IR · PASS — scalable exact-integer cache normalization and clean inverse schedule on all eight frozen seeds.")
        st.error(
            "SELECTED-MODEL RESOURCE SCREEN · REJECTED — maximum 781,332,180 CNOT versus the frozen 2,500,000 limit. "
            "This rejects this architecture only; it is not a lower bound over other reversible designs."
        )
        st.warning("GLOBAL FEASIBLE-GRAPH CONNECTIVITY · INDETERMINATE — ordered 780-position coverage does not prove global reachability or ergodicity.")
    else:
        st.error("V3.9 evidence is absent or invalid. All V3.9 ledgers and numerical values remain masked.")

    ledger = _seed_ledger(state)
    st.markdown("**Eight-seed proof & resource ledger**")
    st.dataframe(ledger, width="stretch", hide_index=True)

    st.markdown("**Register contract · caller-owned exact coherent caches**")
    st.dataframe(_register_ledger(state), width="stretch", hide_index=True)

    coverage_rows = [
        {"Gate": key.replace("_", " ").upper(), "Obtained": value if ok else 0, "Required": 8, "State": "PASS" if ok and int(value) == 8 else "REJECTED" if key == "selected_model_budget_at_most_2500000" and ok else "NOT AUTHENTICATED"}
        for key, value in state.get("coverage", {}).items()
    ]
    st.markdown("**Proof coverage matrix**")
    st.dataframe(pd.DataFrame(coverage_rows), width="stretch", hide_index=True)

    if ok:
        chart = ledger[["Seed", "Selected CNOT"]].copy().set_index("Seed")
        chart["2.5M budget"] = BUDGET_CNOT
        st.markdown("**Selected-model CNOT by frozen seed**")
        st.bar_chart(chart, width="stretch")

    proof_matrix = pd.DataFrame(
        [
            ("Cache delta identity", "Exact integer algebra", "All 43,680 row-edge cases", "Exact", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Canonical pair action", "Reversible composition + small-width exhaustive", "Exact-K feasible support", "Exact / 3 beta controls", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Elementary resources", "Frozen macro expansion recount", "8 complete ordered layers", "Exact count", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Full binary operator", "Not evaluated", "Outside declared domain", "N/A", "NOT CLAIMED"),
            ("Global feasible connectivity", "No complete graph proof", "N=40 feasible graph", "N/A", "INDETERMINATE"),
        ],
        columns=["Claim", "Method", "Verified domain", "Tolerance", "Status"],
    )
    st.markdown("**Proof-scope matrix**")
    st.dataframe(proof_matrix, width="stretch", hide_index=True)
    st.markdown("**Critical path · PARENT → WIDTHS → IR → ELEMENTARY → EQUIVALENCE → CLEANUP → ORDERED LAYER → BUDGET → GLOBAL CONNECTIVITY → BACKEND → HARDWARE**")
    critical = pd.DataFrame(
        [
            ("PARENT / WIDTHS / IR / CLEANUP / ORDER", "PASS" if ok else "NOT AUTHENTICATED", "V3.9 proof chain"),
            ("2.5M SELECTED-MODEL BUDGET", "REJECTED" if ok else "NOT AUTHENTICATED", "max of eight complete ledgers"),
            ("GLOBAL CONNECTIVITY", "INDETERMINATE", "separate complete-graph proof required"),
            ("BACKEND", "NOT RUN", "resource screen rejected first"),
            ("HARDWARE", "BLOCKED · ZERO JOBS", "separate protocol required"),
        ],
        columns=["Gate", "State", "Authority"],
    )
    st.dataframe(critical, width="stretch", hide_index=True)

    for label, suffix, help_text in (
        ("Recompute V3.9 scalable reversible IR", "recompute", "Immutable release; use the offline verifier."),
        ("Override frozen arithmetic/register model", "model_override", "Post-observation model switching is prohibited."),
        ("Override 2,500,000 CNOT admission gate", "budget_override", "The preregistered maximum gate cannot be changed."),
        ("Open named-backend audit successor lane", "backend_successor", "Closed after the architecture-specific resource rejection."),
    ):
        st.button(label, disabled=True, key=f"{key_prefix}_v39_{suffix}", help=help_text)
    if ok:
        st.download_button(
            "Download sealed V3.9 scalable-IR artifact",
            data=json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"),
            file_name="SEALED_V3_9_SCALABLE_REVERSIBLE_IR_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v39_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V3.9 scalable-IR specification",
                data=json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"),
                file_name="PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v39_spec_download",
            )
        st.download_button(
            "Download V3.9 eight-seed ledger CSV",
            data=ledger.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V3_9_EIGHT_SEED_LEDGER.csv",
            mime="text/csv",
            key=f"{key_prefix}_v39_ledger_download",
        )
    st.warning(
        "V3.9 CLAIM BOUNDARY · N40 REVERSIBLE IR AND RESOURCE LEDGER ONLY. "
        "FEASIBLE_SUPPORT_COHERENT_EQUIVALENCE is proven by construction; FULL_BINARY_OPERATOR_EQUIVALENCE is not claimed."
    )
    st.markdown(f"**{escape(state['next_gate'])}**")
    st.markdown("**BACKEND TRANSPILATION · NOT RUN**")
    st.markdown("**HARDWARE EXECUTION · BLOCKED · ZERO JOBS**")
    st.markdown("**QUANTUM ADVANTAGE · NOT CLAIMED**")
    return state


def apply_v39_encoding_state(
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
    decisions = _mapping(_mapping(artifact).get("decisions"))
    screen = _mapping(_mapping(artifact).get("resource_screen"))
    projected.update(
        {
            "v39_artifact_sha": _mapping(artifact).get("artifact_sha256"),
            "v39_reversible_ir_decision": decisions.get("reversible_ir_decision"),
            "v39_budget_decision": decisions.get("budget_decision"),
            "v39_selected_model_cnot_max": screen.get("maximum_selected_model_cnot"),
            "v39_complete_global_connectivity": "INDETERMINATE",
            "encoding_status": "V3.9 N40 REVERSIBLE IR PASSED · SELECTED-MODEL RESOURCE SCREEN REJECTED",
            "hardware_executable": False,
        }
    )
    return projected


__all__ = [
    "EXPECTED_V39_ARTIFACT_RAW_SHA256",
    "EXPECTED_V39_ARTIFACT_SHA256",
    "apply_v39_encoding_state",
    "load_v39_ui_artifact",
    "normalize_v39_artifact",
    "render_v39_scalable_ir_panel",
]
