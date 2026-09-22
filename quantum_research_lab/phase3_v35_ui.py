"""Institutional V3.5 named-backend transpilation evidence surface.

The renderer is deliberately artifact-driven.  It does not discover providers,
refresh calibrations or submit jobs: those are separate, explicit actions
outside the sealed V3.5 auditor. A backend name is treated only as an identifier; backend
class, evidence mode and routing state are independent evidence axes.
"""

from __future__ import annotations

from html import escape
import json
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import streamlit as st


SectionHeader = Callable[[str, str, str], None]

EVIDENCE_MODES = {"NONE", "SNAPSHOT", "LIVE"}
BACKEND_CLASSES = {"HARDWARE", "FAKE", "SIMULATOR", "UNKNOWN"}
CIRCUIT_STAGES = {"PROVIDER_NEUTRAL", "TARGET_TRANSPILED", "ROUTED"}

V35_FREEZE_SUCCESSOR_POLICY = {
    "pre_seal_parent_requirement": "record a passing V3.4 6/6 freeze verification before the authorized UI transition",
    "post_transition_parent_requirement": "retain 27 immutable V3.4 files byte-exact and authenticate the UI and append-only README successors through the V3.5 freeze",
    "allowed_v34_superseded_files": [
        "quantum_research_lab/README.md",
        "quantum_research_lab/ui.py",
    ],
    "successor_transition": "record frozen V3.4 and sealed V3.5 SHA-256 identities for UI and README; reject every undeclared state",
    "lineage": "bind V3.4 freeze self-hash plus V3.4 artifact semantic and raw-file SHA-256",
    "deployment": "check-only preflight, transactional overlay, release verification, AppTest, rollback on any failure",
    "execution_boundary": "installer, verifier and UI must not discover credentials or submit QPU jobs",
    "negative_results": "retain pre-transpile provider-limit rejection independently from NOT_RUN transpilation and routing",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(mapping: Mapping[str, Any], paths: Sequence[Sequence[str]], default: Any = None) -> Any:
    for path in paths:
        value: Any = mapping
        for key in path:
            if not isinstance(value, Mapping) or key not in value:
                value = None
                break
            value = value[key]
        if value is not None:
            return value
    return default


def _upper(value: Any, default: str) -> str:
    text = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    return text or default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any, default: bool = False) -> bool:
    return value if isinstance(value, bool) else default


def _backend_class(artifact: Mapping[str, Any]) -> str:
    declared = _upper(
        _first(
            artifact,
            (
                ("backend", "class"),
                ("backend", "kind"),
                ("target", "backend_class"),
                ("backend_class",),
            ),
        ),
        "UNKNOWN",
    )
    aliases = {
        "REAL": "HARDWARE",
        "PHYSICAL": "HARDWARE",
        "QPU": "HARDWARE",
        "FAKE_BACKEND": "FAKE",
        "FAKE_PROVIDER": "FAKE",
        "AER": "SIMULATOR",
        "STATEVECTOR": "SIMULATOR",
    }
    declared = aliases.get(declared, declared)
    if declared in BACKEND_CLASSES:
        return declared
    simulator = _first(
        artifact,
        (("backend", "simulator"), ("backend", "is_simulator"), ("target", "simulator")),
    )
    return "SIMULATOR" if simulator is True else "UNKNOWN"


def _circuit_stage(artifact: Mapping[str, Any]) -> str:
    declared = _upper(
        _first(
            artifact,
            (
                ("compilation", "stage"),
                ("transpilation", "stage"),
                ("circuit", "stage"),
                ("circuit_stage",),
            ),
        ),
        "PROVIDER_NEUTRAL",
    )
    aliases = {
        "UNROUTED": "PROVIDER_NEUTRAL",
        "IR": "PROVIDER_NEUTRAL",
        "TRANSPILED": "TARGET_TRANSPILED",
        "NATIVE": "TARGET_TRANSPILED",
        "MAPPED": "ROUTED",
    }
    declared = aliases.get(declared, declared)
    if declared in CIRCUIT_STAGES:
        return declared
    routed = _first(
        artifact,
        (("compilation", "routed"), ("transpilation", "routed"), ("routing", "applied")),
    )
    if routed is True:
        return "ROUTED"
    transpiled = _first(
        artifact,
        (("compilation", "transpiled"), ("transpilation", "completed")),
    )
    return "TARGET_TRANSPILED" if transpiled is True else "PROVIDER_NEUTRAL"


def normalize_v35_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    live_probe: Mapping[str, Any] | None = None,
    parent_v34_artifact: Mapping[str, Any] | None = None,
    parent_v34_integrity: bool | None = None,
    artifact_integrity: bool | None = None,
) -> dict[str, Any]:
    """Normalize a V3.5-like artifact without trusting names as evidence.

    Missing or ambiguous fields remain explicit and fail closed. ``live_probe``
    can report runtime reachability, but it never silently upgrades a sealed
    snapshot to LIVE evidence.
    """

    source = _mapping(artifact)
    probe = _mapping(live_probe)
    backend_name = str(
        _first(
            source,
            (
                ("backend", "name"),
                ("backend", "backend_name"),
                ("target", "backend_name"),
                ("backend_name",),
            ),
            "",
        )
        or ""
    ).strip()
    backend_identity = "NAMED" if backend_name else "UNNAMED"
    backend_class = _backend_class(source)
    evidence_mode = _upper(
        _first(
            source,
            (("evidence", "mode"), ("snapshot", "mode"), ("evidence_mode",)),
            "NONE",
        ),
        "NONE",
    )
    if evidence_mode not in EVIDENCE_MODES:
        evidence_mode = "UNKNOWN"
    circuit_stage = _circuit_stage(source)

    capture_utc = str(
        _first(
            source,
            (
                ("evidence", "captured_at_utc"),
                ("calibration", "captured_at_utc"),
                ("snapshot", "captured_at_utc"),
                ("created_utc",),
            ),
            "NOT_RECORDED",
        )
    )
    calibration_id = str(
        _first(
            source,
            (
                ("calibration", "snapshot_id"),
                ("calibration", "calibration_id"),
                ("backend", "calibration_id"),
            ),
            "NOT_RECORDED",
        )
    )
    basis_gates = _first(
        source,
        (("compilation", "basis_gates"), ("backend", "basis_gates"), ("target", "basis_gates")),
        [],
    )
    if not isinstance(basis_gates, (list, tuple)):
        basis_gates = []
    coupling_edges = _int(
        _first(
            source,
            (
                ("compilation", "coupling_map_edges"),
                ("routing", "coupling_map_edges"),
                ("backend", "coupling_map_edges"),
            ),
            0,
        )
    )
    seed_transpiler = _first(
        source,
        (("compilation", "seed_transpiler"), ("transpilation", "seed_transpiler")),
        "NOT_RECORDED",
    )
    optimization_level = _first(
        source,
        (("compilation", "optimization_level"), ("transpilation", "optimization_level")),
        "NOT_RECORDED",
    )

    provider_limit_name = str(
        _first(
            source,
            (
                ("provider_limits", "limit_name"),
                ("pre_transpile_provider_limit", "limit_name"),
                ("provider_limit", "name"),
            ),
            "NOT_RECORDED",
        )
    )
    provider_limit_value = _int(
        _first(
            source,
            (
                ("provider_limits", "max_two_qubit_instructions_per_circuit"),
                ("provider_limits", "max_two_qubit_gates_per_circuit"),
                ("pre_transpile_provider_limit", "max_two_qubit_instructions"),
                ("provider_limit", "maximum"),
            ),
            0,
        )
    )
    pre_transpile_two_qubit = _int(
        _first(
            source,
            (
                ("pre_transpile_provider_limit", "selected_model_two_qubit_instructions"),
                ("pre_transpile_provider_limit", "selected_ccx_model_cnot_count"),
                ("resources", "pre_transpile_two_qubit_instructions"),
                ("resource_reference", "cnot_after_selected_ccx_model_max"),
                ("compilation", "input_two_qubit_gates"),
            ),
            0,
        )
    )
    provider_limit_source = str(
        _first(
            source,
            (
                ("provider_limits", "source_url"),
                ("pre_transpile_provider_limit", "source_url"),
                ("provider_limit", "source"),
            ),
            "NOT_RECORDED",
        )
    )
    provider_limit_observed_utc = str(
        _first(
            source,
            (
                ("provider_limits", "observed_at_utc"),
                ("pre_transpile_provider_limit", "observed_at_utc"),
                ("provider_limit", "observed_at_utc"),
            ),
            "NOT_RECORDED",
        )
    )
    declared_provider_decision = _upper(
        _first(
            source,
            (
                ("decisions", "pre_transpile_provider_limit"),
                ("pre_transpile_provider_limit", "decision"),
                ("provider_limit", "decision"),
            ),
            "NOT_RUN",
        ),
        "NOT_RUN",
    )
    if provider_limit_value > 0 and pre_transpile_two_qubit > 0:
        provider_limit_decision = (
            "REJECTED"
            if pre_transpile_two_qubit > provider_limit_value
            else "WITHIN_LIMIT"
        )
    elif "REJECT" in declared_provider_decision:
        provider_limit_decision = "REJECTED"
    elif declared_provider_decision in {"PASS", "WITHIN_LIMIT"}:
        provider_limit_decision = "WITHIN_LIMIT"
    else:
        provider_limit_decision = "NOT_RUN"
    provider_limit_ratio = (
        float(pre_transpile_two_qubit) / float(provider_limit_value)
        if provider_limit_value > 0 and pre_transpile_two_qubit > 0
        else None
    )

    jobs = _int(
        _first(
            source,
            (
                ("claim_boundary", "qpu_jobs_submitted"),
                ("execution", "qpu_jobs_submitted"),
                ("qpu_jobs_submitted",),
            ),
            0,
        )
    )
    submission_enabled = _bool(
        _first(
            source,
            (
                ("claim_boundary", "qpu_submission_enabled"),
                ("execution", "qpu_submission_enabled"),
            ),
            False,
        )
    )
    checks = _mapping(_first(source, (("validation", "checks"),), {}))
    gate_states = _mapping(
        _first(source, (("validation", "gate_states"),), {})
    )
    if not gate_states:
        raw_gates = _mapping(source.get("gates"))
        gate_states = {
            str(name): str(_mapping(gate).get("state", "NOT_RUN"))
            for name, gate in raw_gates.items()
        }
    validation_overall = _first(source, (("validation", "overall_pass"),), None)
    if validation_overall is None and checks:
        validation_overall = all(bool(value) for value in checks.values())
    validation_pass = validation_overall is True

    declared_parent = str(
        _first(
            source,
            (("parents", "v34_artifact_sha256"), ("lineage", "v34_artifact_sha256")),
            "",
        )
        or ""
    )
    supplied_parent = str(_mapping(parent_v34_artifact).get("artifact_sha256", "") or "")
    if not declared_parent:
        parent_state = "NOT_DECLARED"
    elif not supplied_parent:
        parent_state = "NOT_CHECKED"
    elif declared_parent == supplied_parent and parent_v34_integrity is True:
        parent_state = "PASS"
    else:
        parent_state = "MISMATCH"

    live_reachable = _bool(
        _first(probe, (("reachable",), ("backend_reachable",), ("connected",)), False)
    )
    live_probe_backend = str(
        _first(probe, (("backend_name",), ("backend", "name")), "") or ""
    )
    live_probe_match = bool(
        live_reachable and backend_name and live_probe_backend == backend_name
    )

    declared_veto = _mapping(_first(source, (("veto",), ("governance", "veto")), {}))
    declared_reasons = declared_veto.get("reasons", [])
    if isinstance(declared_reasons, str):
        declared_reasons = [declared_reasons]
    if not isinstance(declared_reasons, (list, tuple)):
        declared_reasons = []
    reasons = [str(item) for item in declared_reasons if str(item).strip()]
    if not source:
        reasons.append("V3.5 artifact is missing")
    if artifact_integrity is not True:
        reasons.append(
            "artifact integrity failed"
            if artifact_integrity is False
            else "artifact integrity is NOT_CHECKED"
        )
    if declared_veto.get("active") is True and not reasons:
        reasons.append("artifact-declared governance veto is active")
    if backend_identity != "NAMED":
        reasons.append("backend identity is unnamed")
    if backend_class == "UNKNOWN":
        reasons.append("backend class is unknown")
    if evidence_mode == "UNKNOWN":
        reasons.append("evidence mode is not NONE, SNAPSHOT or LIVE")
    if circuit_stage != "ROUTED":
        reasons.append("circuit is not routed to the target coupling map")
    if circuit_stage == "ROUTED" and coupling_edges <= 0:
        reasons.append("routed label lacks coupling-map evidence")
    if not basis_gates:
        reasons.append("target basis gates are not recorded")
    if calibration_id == "NOT_RECORDED":
        reasons.append("calibration snapshot identity is missing")
    if capture_utc == "NOT_RECORDED":
        reasons.append("evidence capture timestamp is missing")
    if parent_state != "PASS":
        reasons.append(f"V3.4 parent chain is {parent_state}")
    if not validation_pass:
        reasons.append("validation gates are incomplete")
    if submission_enabled:
        reasons.append("QPU submission must remain disabled in V3.5")
    if jobs != 0:
        reasons.append(f"QPU job count is {jobs}, expected zero")
    if provider_limit_decision == "REJECTED":
        reasons.append("pre-transpile provider-limit gate is REJECTED")
    reasons = list(dict.fromkeys(reasons))

    compilation_gate = "PASS" if not reasons else "FAIL_CLOSED"
    hardware_reasons = []
    if backend_class != "HARDWARE":
        hardware_reasons.append(f"backend class is {backend_class}")
    if evidence_mode != "LIVE":
        hardware_reasons.append(f"evidence mode is {evidence_mode}")
    if not live_probe_match:
        hardware_reasons.append("no matching live provider probe")
    hardware_reasons.append(
        "no QPU execution evidence; job count is zero"
        if jobs == 0
        else f"QPU job count policy breach: {jobs}"
    )

    metrics = {
        "input_depth": _int(_first(source, (("resources", "input_depth"), ("compilation", "input_depth")), 0)),
        "output_depth": _int(_first(source, (("resources", "output_depth"), ("compilation", "output_depth")), 0)),
        "input_two_qubit": _int(_first(source, (("resources", "input_two_qubit_gates"), ("compilation", "input_two_qubit_gates")), 0)),
        "output_two_qubit": _int(_first(source, (("resources", "output_two_qubit_gates"), ("compilation", "output_two_qubit_gates")), 0)),
        "output_total_gates": _int(_first(source, (("resources", "output_total_gates"), ("compilation", "output_total_gates")), 0)),
        "swap_count": _int(_first(source, (("resources", "swap_count"), ("routing", "swap_count")), 0)),
    }
    return {
        "artifact_present": bool(source),
        "artifact_sha256": str(source.get("artifact_sha256", "NOT_RECORDED")),
        "backend_name": backend_name or "NOT_RECORDED",
        "backend_identity": backend_identity,
        "backend_class": backend_class,
        "evidence_mode": evidence_mode,
        "capture_utc": capture_utc,
        "calibration_id": calibration_id,
        "circuit_stage": circuit_stage,
        "basis_gates": [str(item) for item in basis_gates],
        "coupling_map_edges": coupling_edges,
        "seed_transpiler": seed_transpiler,
        "optimization_level": optimization_level,
        "provider_limit_name": provider_limit_name,
        "provider_limit_value": provider_limit_value,
        "pre_transpile_two_qubit": pre_transpile_two_qubit,
        "provider_limit_ratio": provider_limit_ratio,
        "provider_limit_decision": provider_limit_decision,
        "provider_limit_source": provider_limit_source,
        "provider_limit_observed_utc": provider_limit_observed_utc,
        "qpu_jobs_submitted": jobs,
        "qpu_submission_enabled": submission_enabled,
        "validation_checks": dict(checks),
        "validation_gate_states": dict(gate_states),
        "validation_pass": validation_pass,
        "parent_state": parent_state,
        "live_probe_reachable": live_reachable,
        "live_probe_match": live_probe_match,
        "compilation_gate": compilation_gate,
        "release_veto_active": bool(reasons),
        "release_veto_reasons": reasons,
        "hardware_claim_veto_active": True,
        "hardware_claim_veto_reasons": hardware_reasons,
        "metrics": metrics,
    }


def render_v35_backend_evidence_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    live_probe: Mapping[str, Any] | None = None,
    parent_v34_artifact: Mapping[str, Any] | None = None,
    parent_v34_integrity: bool | None = None,
    artifact_integrity: bool | None = None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    """Render V3.5 evidence without performing provider or QPU operations."""

    state = normalize_v35_artifact(
        artifact,
        live_probe=live_probe,
        parent_v34_artifact=parent_v34_artifact,
        parent_v34_integrity=parent_v34_integrity,
        artifact_integrity=artifact_integrity,
    )
    section_header(
        "V3.5 Named-Backend Transpilation Control Room",
        "PREREGISTERED TARGET → CALIBRATION IDENTITY → TRANSPILE → ROUTE → RESOURCE DELTA → VETO",
        "V3.5 separates sealed snapshot evidence from live provider state, backend identity from backend class, and provider-neutral resources from target-transpiled and routed counts. It performs no QPU submission and makes no hardware-advantage claim.",
    )

    status_class = "qp3-ok" if not state["release_veto_active"] else "qp3-block"
    release_text = "CLEAR · OFFLINE EVIDENCE" if not state["release_veto_active"] else "ACTIVE · FAIL CLOSED"
    execution_text = "ZERO JOBS" if state["qpu_jobs_submitted"] == 0 else f"{state['qpu_jobs_submitted']} JOBS · POLICY BREACH"
    execution_class = "qp3-block"
    st.markdown(
        f'''<div class="qp3-panel"><div class="qp3-pk">V3.5 · NAMED-BACKEND TRANSPILATION CONTROL ROOM</div><div class="qp3-pt {status_class}">ADMISSION VETO · {release_text}</div><div class="qp3-note"><b>EVIDENCE MODE · {escape(state['evidence_mode'])}</b> · <b>BACKEND IDENTITY · {escape(state['backend_identity'])}</b> · <b>BACKEND CLASS · {escape(state['backend_class'])}</b> · <b>CIRCUIT STAGE · {escape(state['circuit_stage'])}</b><br><b>Backend:</b> {escape(state['backend_name'])} · <b>Calibration:</b> <span class="qp3-sha">{escape(state['calibration_id'])}</span> · <b>Captured:</b> {escape(state['capture_utc'])}<br><b>Artifact:</b> <span class="qp3-sha">{escape(state['artifact_sha256'][:24])}</span> · <b>V3.4 parent:</b> {escape(state['parent_state'])}</div></div>''',
        unsafe_allow_html=True,
    )

    st.caption(
        "Backend name is an identifier, not evidence of physical hardware. "
        "FAKE and SIMULATOR targets may validate transpilation mechanics but cannot clear the hardware-claim veto."
    )
    limit_ratio = state["provider_limit_ratio"]
    limit_summary = (
            f"{state['pre_transpile_two_qubit']:,} selected-model CNOT gates vs "
        f"{state['provider_limit_value']:,} provider cap · {limit_ratio:,.2f}× cap"
        if limit_ratio is not None
        else "provider limit or pre-transpile 2Q estimate is not recorded"
    )
    if state["provider_limit_decision"] == "REJECTED":
        st.error(
            f"PRE-TRANSPILE PROVIDER LIMIT · REJECTED — {limit_summary}. "
            "This gate is independent of backend-native transpilation and routed gate counts."
        )
    elif state["provider_limit_decision"] == "WITHIN_LIMIT":
        st.success(
            f"PRE-TRANSPILE PROVIDER LIMIT · WITHIN LIMIT — {limit_summary}. "
            "This does not prove that transpilation or routing will succeed."
        )
    else:
        st.warning(
            "PRE-TRANSPILE PROVIDER LIMIT · NOT RUN. Candidate discovery, Qiskit transpilation "
            "and backend-native routed counts may also remain NOT RUN."
        )
    st.caption(
        f"Limit identity: {state['provider_limit_name']} · observed: {state['provider_limit_observed_utc']} · "
        f"source: {state['provider_limit_source']}. The provider limit and the V3.4 selected-CCX estimate must be frozen with provenance."
    )
    a, b, c, d, e = st.columns(5)
    a.metric("Evidence", state["evidence_mode"])
    b.metric("Backend identity", state["backend_identity"])
    c.metric("Backend class", state["backend_class"])
    d.metric("Circuit stage", state["circuit_stage"])
    e.metric("QPU execution", "ZERO JOBS" if state["qpu_jobs_submitted"] == 0 else f"{state['qpu_jobs_submitted']} JOBS")

    st.markdown(
        f'''<div class="qp3-grid">
          <div class="qp3-card"><div class="qp3-ck">SNAPSHOT / LIVE</div><div class="qp3-cv">EVIDENCE MODE · {escape(state['evidence_mode'])}</div><div class="qp3-cn">Live probe reachable: {str(state['live_probe_reachable']).upper()} · identity match: {str(state['live_probe_match']).upper()}</div></div>
          <div class="qp3-card"><div class="qp3-ck">NAMED / FAKE</div><div class="qp3-cv">BACKEND IDENTITY · {escape(state['backend_identity'])}</div><div class="qp3-cn">BACKEND CLASS · {escape(state['backend_class'])} · classifications remain independent</div></div>
          <div class="qp3-card"><div class="qp3-ck">COMPILATION BOUNDARY</div><div class="qp3-cv">CIRCUIT STAGE · {escape(state['circuit_stage'])}</div><div class="qp3-cn">Basis gates: {escape(', '.join(state['basis_gates']) or 'NOT RECORDED')} · coupling edges: {state['coupling_map_edges']}</div></div>
          <div class="qp3-card"><div class="qp3-ck">PROVIDER LIMIT</div><div class="qp3-cv">PRE-TRANSPILE · {escape(state['provider_limit_decision'])}</div><div class="qp3-cn">independent of transpiled/routed native counts</div></div>
          <div class="qp3-card"><div class="qp3-ck">QPU EXECUTION</div><div class="qp3-cv {execution_class}">QPU EXECUTION · {escape(execution_text)}</div><div class="qp3-cn">Submission enabled: {str(state['qpu_submission_enabled']).upper()} · hardware advantage NOT CLAIMED</div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    metrics = state["metrics"]
    resource_rows = [
        {"Resource": "Circuit depth", "Provider-neutral input": f"{metrics['input_depth']:,}", "Target output": f"{metrics['output_depth']:,}"},
        {"Resource": "Two-qubit gates", "Provider-neutral input": f"{metrics['input_two_qubit']:,}", "Target output": f"{metrics['output_two_qubit']:,}"},
        {"Resource": "Total gates", "Provider-neutral input": "NOT COMPARABLE", "Target output": f"{metrics['output_total_gates']:,}"},
        {"Resource": "Routing SWAP", "Provider-neutral input": "N/A", "Target output": f"{metrics['swap_count']:,}"},
    ]
    st.markdown("**Provider-neutral vs target-transpiled/routed gate ledger**")
    st.dataframe(pd.DataFrame(resource_rows), width="stretch", hide_index=True)
    st.caption(
        f"Transpiler seed: {state['seed_transpiler']} · optimization level: {state['optimization_level']} · "
        f"target coupling-map edges: {state['coupling_map_edges']}. Zero values mean NOT RECORDED unless the artifact explicitly establishes otherwise."
    )

    left, right = st.columns(2)
    with left:
        if state["release_veto_active"]:
            st.error("ADMISSION VETO · ACTIVE. The V3.5 backend-admission artifact remains fail-closed.")
        else:
            st.success("ADMISSION VETO · CLEAR for offline backend evidence only.")
        st.dataframe(
            pd.DataFrame(
                [{"Admission veto reason": item} for item in state["release_veto_reasons"]]
                or [{"Admission veto reason": "NONE"}]
            ),
            width="stretch",
            hide_index=True,
        )
    with right:
        st.error("HARDWARE CLAIM VETO · ACTIVE · ZERO-JOB BOUNDARY")
        st.dataframe(
            pd.DataFrame(
                [{"Hardware veto reason": item} for item in state["hardware_claim_veto_reasons"]]
            ),
            width="stretch",
            hide_index=True,
        )

    st.markdown("**V3.5 validation gates**")
    gate_rows = [
        {
            "Gate": name,
            "State": gate_state,
            "Pass": gate_state == "PASS",
        }
        for name, gate_state in state["validation_gate_states"].items()
    ]
    if not gate_rows:
        gate_rows = [
            {"Gate": name, "State": "PASS" if passed else "NOT_PASS", "Pass": bool(passed)}
            for name, passed in state["validation_checks"].items()
        ]
    st.dataframe(
        pd.DataFrame(gate_rows or [{"Gate": "NO VALIDATION MANIFEST", "State": "NOT_RUN", "Pass": False}]),
        width="stretch",
        hide_index=True,
    )
    st.warning(
        "V3.5 CLAIM BOUNDARY · BACKEND-ADMISSION EVIDENCE ONLY. Routed gate counts are target- and snapshot-specific. "
        "They do not establish execution fidelity, runtime advantage, queue behavior, noise acceptance or quantum advantage."
    )
    if artifact:
        st.download_button(
            "Download sealed V3.5 named-backend artifact",
            data=json.dumps(dict(artifact), indent=2, sort_keys=True, ensure_ascii=False),
            file_name="SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
            mime="application/json",
            key=f"{key_prefix}_v35_artifact_download",
        )
    return state


__all__ = [
    "BACKEND_CLASSES",
    "CIRCUIT_STAGES",
    "EVIDENCE_MODES",
    "V35_FREEZE_SUCCESSOR_POLICY",
    "normalize_v35_artifact",
    "render_v35_backend_evidence_panel",
]
