"""Institutional, artifact-driven V3.8 elementary-admission surface."""

from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .phase3_v38_elementary_admission import default_v38_artifact_path


SectionHeader = Callable[[str, str, str], None]
EXPECTED_V38_ARTIFACT_SHA256 = "2d0980803e81564e455836d1fd9c52aab04adbf20a8dfd15958b6d4c3cd7b21f"
EXPECTED_V38_ARTIFACT_RAW_SHA256 = "c8062c7836f7abdf164e5cb274db9fcf2c41780714d91f71a99b81b4fd0a8195"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in value] if isinstance(value, list) and all(isinstance(row, Mapping) for row in value) else []


def _fmt_int(value: Any) -> str:
    if isinstance(value, bool):
        return "NOT AUTHENTICATED"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value) if value is not None else "NOT AUTHENTICATED"


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_v38_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fast immutable-identity check for interactive rendering.

    Full scientific recomputation remains in ``validate_v38_artifact`` and the
    release verifier.  The UI binds to their sealed semantic and raw identities
    so opening Streamlit does not repeat the 49,152-case numerical ladder.
    """

    target = Path(path) if path is not None else default_v38_artifact_path()
    errors: list[str] = []
    try:
        raw = target.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, {"valid": False, "errors": [str(exc)]}
    if not isinstance(payload, dict):
        return {}, {"valid": False, "errors": ["V3.8 artifact must be a JSON object."]}
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    try:
        semantic = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return payload, {"valid": False, "errors": [str(exc)]}
    actual_raw = hashlib.sha256(raw).hexdigest()
    if payload.get("artifact_sha256") != semantic:
        errors.append("V3.8 artifact self-hash mismatch.")
    if semantic != EXPECTED_V38_ARTIFACT_SHA256:
        errors.append("V3.8 sealed semantic identity mismatch.")
    if actual_raw != EXPECTED_V38_ARTIFACT_RAW_SHA256:
        errors.append("V3.8 sealed raw-file identity mismatch.")
    return payload, {
        "valid": not errors,
        "errors": errors,
        "semantic_sha256": semantic,
        "raw_file_sha256": actual_raw,
    }


def normalize_v38_artifact(
    artifact: Mapping[str, Any] | None, *, artifact_integrity: bool | None = None
) -> dict[str, Any]:
    source = _mapping(artifact)
    elementary = _mapping(source.get("elementary_validation"))
    template = _mapping(elementary.get("template_validation"))
    resources = _mapping(source.get("elementary_resource_ledger"))
    n40 = _mapping(source.get("n40_admission"))
    coverage = _mapping(n40.get("coverage_counts_out_of_8"))
    decisions = _mapping(source.get("decisions"))
    boundary = _mapping(source.get("claim_boundary"))
    decomposition = _mapping(source.get("decomposition_contract"))
    core = {key: value for key, value in source.items() if key != "artifact_sha256"}
    try:
        self_hash_valid = source.get("artifact_sha256") == canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError):
        self_hash_valid = False
    authenticated = bool(
        artifact_integrity is not False
        and self_hash_valid
        and source.get("artifact_sha256") == EXPECTED_V38_ARTIFACT_SHA256
        and elementary.get("passed") is True
        and resources.get("cnot_count") == 3_632
        and resources.get("one_qubit_gate_count") == 5_920
        and n40.get("admission_decision") == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
        and n40.get("maximum_selected_model_cnot") == "NOT_ESTIMATED"
        and len(_rows(n40.get("rows"))) == 8
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    )
    display = (lambda value: value if authenticated else "NOT AUTHENTICATED")
    return {
        "authenticated": authenticated,
        "artifact": dict(source),
        "artifact_sha256": str(display(source.get("artifact_sha256", "NOT AUTHENTICATED"))),
        "overall": str(display(decisions.get("overall", "NOT AUTHENTICATED"))),
        "elementary_status": str(display(decisions.get("elementary_decomposition", "NOT AUTHENTICATED"))),
        "selected_model": str(display(decomposition.get("selected_model", "NOT AUTHENTICATED"))),
        "basis": list(decomposition.get("elementary_basis") or []) if authenticated else [],
        "cnot": display(resources.get("cnot_count")),
        "one_qubit": display(resources.get("one_qubit_gate_count")),
        "serial_cnot_depth": display(resources.get("serial_cnot_depth")),
        "ancilla_peak": display(resources.get("maximum_clean_ancilla_qubits")),
        "total_qubits": display(resources.get("maximum_total_qubits")),
        "primitive_cases": display(elementary.get("primitive_basis_beta_cases_checked")),
        "action_error": display(elementary.get("maximum_action_error")),
        "norm_error": display(elementary.get("maximum_norm_error")),
        "clean_failures": display(elementary.get("clean_ancilla_failures")),
        "ccx_error": display(template.get("ccx_maximum_action_error")),
        "crx_error": display(template.get("crx_maximum_action_error")),
        "resource_rows": _rows(resources.get("rows")) if authenticated else [],
        "n40_rows": _rows(n40.get("rows")) if authenticated else [],
        "coverage": dict(coverage) if authenticated else {},
        "n40_cnot": str(display(n40.get("maximum_selected_model_cnot"))),
        "budget_gate": str(display(n40.get("budget_gate"))),
        "n40_decision": str(display(n40.get("admission_decision"))),
        "negative_result": str(display(n40.get("negative_result_preservation"))),
        "boundary": dict(boundary) if authenticated else {},
    }


def _seed_table(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("n40_rows") or []:
        gates = _mapping(row.get("gates"))
        rows.append(
            {
                "Seed": row.get("seed"),
                "7 constraints": "PASS" if gates.get("seven_constraint_parent_evidence") else "FAIL",
                "Classical delta": "PASS" if gates.get("classical_delta_equivalence") else "FAIL",
                "Reversible IR": "MISSING" if not gates.get("scalable_reversible_ir") else "PASS",
                "Elementary": "NOT RUN" if not gates.get("elementary_lowering") else "PASS",
                "Cleanup": "NOT PROVEN" if not gates.get("clean_ancilla_proof") else "PASS",
                "Connectivity": "NOT PROVEN" if not gates.get("ordered_layer_connectivity") else "PASS",
                "Selected CNOT": row.get("selected_model_cnot"),
                "2.5M gate": "NOT EVALUATED",
                "Decision": row.get("decision"),
            }
        )
    return pd.DataFrame(rows)


def render_v38_elementary_admission_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None = None,
    artifact_integrity: bool | None = None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v38_artifact(artifact, artifact_integrity=artifact_integrity)
    section_header(
        "V3.8 Elementary Decomposition & N=40 Admission",
        "FROZEN MODEL → ELEMENTARY PROOF → CLEAN ANCILLAS → EIGHT-SEED GATE",
        "The authenticated V3.7 prototype is lowered to one-qubit gates and CX. "
        "Production N=40 remains a separate, all-evidence admission decision.",
    )
    st.markdown(
        """<style>
        .qv38-shell{position:relative;overflow:hidden;border:1px solid rgba(114,166,255,.35);border-radius:20px;padding:19px 20px;margin:10px 0 15px;background:radial-gradient(circle at 92% 4%,rgba(112,77,255,.19),transparent 31%),linear-gradient(128deg,rgba(3,18,31,.99),rgba(13,18,48,.98) 59%,rgba(29,12,48,.97));box-shadow:0 0 44px rgba(83,130,255,.10)}
        .qv38-k{font-size:.61rem;letter-spacing:.17em;color:#8bb7ff;font-weight:900}.qv38-title{font-size:1.14rem;color:#fff;font-weight:900;margin:6px 0}.qv38-copy{font-size:.74rem;line-height:1.5;color:#abb8cc;max-width:1140px}.qv38-tags{margin-top:9px;font-size:.64rem;letter-spacing:.08em;color:#9aaaca}.qv38-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin:11px 0 17px}.qv38-card{border:1px solid rgba(126,164,255,.17);background:rgba(4,15,30,.78);border-radius:14px;padding:12px}.qv38-label{font-size:.52rem;letter-spacing:.115em;color:#8498b8;font-weight:850}.qv38-value{font-size:.92rem;color:#f7f9ff;font-weight:900;margin:5px 0}.qv38-note{font-size:.63rem;line-height:1.38;color:#91a2b9}.qv38-pass{color:#78edbd}.qv38-block{color:#ffaaa9}.qv38-warn{color:#ffd08a}@media(max-width:1100px){.qv38-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.qv38-grid{grid-template-columns:1fr 1fr}}@media(max-width:470px){.qv38-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    ok = bool(state["authenticated"])
    st.markdown(
        f"""<div class="qv38-shell"><div class="qv38-k">V3.8 · ELEMENTARY DECOMPOSITION & N=40 RESOURCE ADMISSION</div>
        <div class="qv38-title {'qv38-pass' if ok else 'qv38-block'}">{escape(state['overall'])}</div>
        <div class="qv38-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT'} · SHA {escape(state['artifact_sha256'][:24])}<br>Selected decomposition: {escape(state['selected_model'])}</div>
        <div class="qv38-tags">RESEARCH_ONLY · PROVIDER_FREE · HARDWARE_EXECUTABLE FALSE</div></div>
        <div class="qv38-grid">
        <div class="qv38-card"><div class="qv38-label">ELEMENTARY MODEL</div><div class="qv38-value qv38-pass">{'VALIDATED' if ok else 'NOT AUTHENTICATED'}</div><div class="qv38-note">frozen before evaluation</div></div>
        <div class="qv38-card"><div class="qv38-label">PROTOTYPE CNOT</div><div class="qv38-value">{escape(_fmt_int(state['cnot']))}</div><div class="qv38-note">exact selected-model count · N=4 only</div></div>
        <div class="qv38-card"><div class="qv38-label">PROTOTYPE 1Q</div><div class="qv38-value">{escape(_fmt_int(state['one_qubit']))}</div><div class="qv38-note">X/H/T/TDG/RY/RZ</div></div>
        <div class="qv38-card"><div class="qv38-label">CLEAN ANCILLA PEAK</div><div class="qv38-value">{escape(_fmt_int(state['ancilla_peak']))}</div><div class="qv38-note">18 total logical qubits at peak</div></div>
        <div class="qv38-card"><div class="qv38-label">FROZEN SEED COVERAGE</div><div class="qv38-value">{'8 / 8' if ok else 'NOT AUTHENTICATED'}</div><div class="qv38-note">contract authentication, not compilation</div></div>
        <div class="qv38-card"><div class="qv38-label">N40 ADMISSION</div><div class="qv38-value qv38-block">{escape(state['n40_decision'])}</div><div class="qv38-note">budget not evaluated without an IR</div></div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**SELECTED DECOMPOSITION MODEL · FROZEN BEFORE EVALUATION**")
    st.markdown("**REGISTERED PRODUCTION SCOPE · N=40 · 7 HARD CONSTRAINTS · 8 FROZEN SEEDS**")
    st.markdown("**POST-OBSERVATION CANDIDATE SWITCHING · PROHIBITED**")
    if ok:
        st.success("ELEMENTARY DECOMPOSITION · VALIDATED — 40/40 logical occurrences lowered deterministically.")
        st.success(
            "CLEAN-ANCILLA PROOF · PASS — 49,152 primitive basis/beta cases; "
            f"maximum action residual {float(state['action_error']):.3e}; zero cleanup failures."
        )
        st.info(
            "SELECTED-MODEL PROTOTYPE LEDGER · 3,632 CNOT · 5,920 one-qubit gates · "
            "serial CNOT depth 3,632 · abstract all-to-all logical connectivity."
        )
    else:
        st.error("V3.8 artifact integrity is absent or invalid. No decomposition or resource value is admissible.")

    st.markdown("**Elementary primitive ledger**")
    primitive_rows = []
    if ok:
        for kind, template_id in (("PATTERN_MCX", "SIGNED_MCX_CLEAN_AND_LADDER_V1"), ("PATTERN_MCRX", "SIGNED_MCRX_CLEAN_AND_LADDER_V1")):
            matching = [row for row in state["resource_rows"] if row.get("logical_kind") == kind]
            primitive_rows.append(
                {
                    "Primitive IR": kind,
                    "Occurrences": len(matching),
                    "Template ID": template_id,
                    "Basis": "1Q + CX",
                    "1Q": sum(int(row["one_qubit_gate_count"]) for row in matching),
                    "CNOT": sum(int(row["cnot_count"]) for row in matching),
                    "Serial CNOT depth": sum(int(row["serial_cnot_depth"]) for row in matching),
                    "Ancilla peak": max(int(row["clean_ancilla_qubits"]) for row in matching),
                    "Cleanup": "PASS",
                }
            )
    st.dataframe(pd.DataFrame(primitive_rows), width="stretch", hide_index=True)

    st.markdown("**N=40 eight-seed admission ledger**")
    st.dataframe(_seed_table(state), width="stretch", hide_index=True)
    if ok:
        st.error(
            "N40 RESOURCE ADMISSION · BLOCKED — 8/8 seed identities and seven-constraint "
            "classical delta evidence authenticate, but reversible IR, elementary lowering, "
            "coherent cleanup, connectivity and selected-model CNOT evidence are 0/8."
        )
        st.warning(
            "INTERNAL 2,500,000 CNOT GATE · NOT EVALUATED — no N=40 selected-model numerator exists. "
            "The frozen V3.4 rejection is preserved as historical, architecture-specific evidence."
        )
    else:
        st.error("N40 RESOURCE ADMISSION · BLOCKED · EVIDENCE NOT AUTHENTICATED")

    critical_path = pd.DataFrame(
        [
            {"Gate": "ELEMENTARY N=4 PROTOTYPE", "State": "PASS" if ok else "NOT AUTHENTICATED", "Authority": "V3.8 exhaustive primitive proof"},
            {"Gate": "N40 REVERSIBLE IR · 8 SEEDS", "State": "BLOCKED", "Authority": "0/8 compiled"},
            {"Gate": "2.5M SELECTED-MODEL BUDGET", "State": "NOT EVALUATED", "Authority": "No comparable N40 numerator"},
            {"Gate": "CONFIRMATORY BACKEND AUDIT", "State": "CLOSED", "Authority": "Requires prior admission"},
            {"Gate": "HARDWARE", "State": "BLOCKED · ZERO JOBS", "Authority": "Separate protocol required"},
        ]
    )
    st.markdown("**Critical path · ELEMENTARY → N40/8 SEEDS → 2.5M BUDGET → BACKEND → HARDWARE**")
    st.dataframe(critical_path, width="stretch", hide_index=True)

    st.button(
        "Recompute V3.8 elementary decomposition",
        disabled=True,
        key=f"{key_prefix}_v38_recompute",
        help="Immutable release: recomputation belongs to the offline validation ladder.",
    )
    st.button(
        "Override selected-model resource budget",
        disabled=True,
        key=f"{key_prefix}_v38_budget_override",
        help="The preregistered 2.5M budget cannot be changed after observation.",
    )
    st.button(
        "Open confirmatory backend-audit successor lane",
        disabled=True,
        key=f"{key_prefix}_v38_backend_successor",
        help="Blocked until an N40 selected-model ledger passes every preregistered gate.",
    )
    if ok:
        st.download_button(
            "Download sealed V3.8 elementary-admission artifact",
            data=json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"),
            file_name="SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v38_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V3.8 elementary-admission specification",
                data=json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"),
                file_name="PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v38_spec_download",
            )
    st.warning(
        "V3.8 CLAIM BOUNDARY · ELEMENTARY PROTOTYPE ONLY. The 3,632-CNOT result belongs only "
        "to the authenticated synthetic N=4, K=2 V3.7 operator. It is not an N=40 projection, "
        "backend transpilation, hardware result, optimization result or quantum-advantage claim."
    )
    st.markdown("**BACKEND TRANSPILATION · NOT RUN**")
    st.markdown("**HARDWARE EXECUTION · BLOCKED · ZERO JOBS**")
    st.markdown("**QUANTUM ADVANTAGE · NOT CLAIMED**")
    return state


def apply_v38_encoding_state(
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
    projected.update(
        {
            "v38_elementary_artifact_sha": source.get("artifact_sha256"),
            "v38_elementary_decision": (_mapping(source.get("decisions"))).get("elementary_decomposition"),
            "v38_n40_admission": "BLOCKED_INCOMPLETE_REVERSIBLE_IR",
            "encoding_status": "V3.8 ELEMENTARY N4 PROTOTYPE PASSED · N40 ADMISSION BLOCKED",
            "hardware_executable": False,
        }
    )
    return projected


__all__ = [
    "EXPECTED_V38_ARTIFACT_RAW_SHA256",
    "EXPECTED_V38_ARTIFACT_SHA256",
    "apply_v38_encoding_state",
    "load_v38_ui_artifact",
    "normalize_v38_artifact",
    "render_v38_elementary_admission_panel",
]
