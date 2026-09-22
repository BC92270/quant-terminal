"""Institutional Streamlit evidence panel for the sealed V3.4 successor."""

from __future__ import annotations

from html import escape
import json
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_algorithmic_contract import PROFILE_DUAL_GUARD, TOPOLOGY_COMPLETE, TOPOLOGY_RING
from .phase3_native_mixer import elementary_schedule_sha256
from .phase3_optimized_oracle import load_v34_spec
from .phase3_v34_validation import (
    DEFAULT_SEAL_NAME,
    default_optimized_native_root,
    load_optimized_native_artifact,
)


SectionHeader = Callable[[str, str, str], None]


def _angle_text(gate: Mapping[str, Any]) -> str:
    angle = gate.get("angle") or {}
    if "beta_coefficient" in angle:
        coefficient = float(angle["beta_coefficient"])
        return f"{coefficient:+g}β"
    if "pi_multiple" in angle:
        coefficient = float(angle["pi_multiple"])
        return f"{coefficient:+g}π"
    return "—"


def render_v34_evidence_panel(
    section_header: SectionHeader,
    *,
    parent_v33_artifact: Mapping[str, Any] | None,
    parent_v33_integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    """Render V3.4 evidence and return its fail-closed runtime state."""

    section_header(
        "V3.4 Optimized Oracle + Elementary Guarded Mixer",
        "DISJOINT-VIOLATION FLAG → 2-QUBIT REDUCTION → EXACT C2-XY SCHEDULE → RESOURCE DELTA",
        "V3.4 removes two live comparator flags without changing the frozen predicate, then lowers each doubly-guarded XY edge to a clean 12-gate provider-neutral schedule. Exact matrix identity is sealed; backend-native synthesis, routing, calibration, optimization performance and QPU execution remain separate blocked gates.",
    )
    spec = load_v34_spec()
    seal_path = default_optimized_native_root() / DEFAULT_SEAL_NAME
    artifact: dict[str, Any] | None = None
    integrity_report: dict[str, Any] = {"valid": False, "errors": []}
    if seal_path.exists():
        try:
            artifact, integrity_report = load_optimized_native_artifact(seal_path)
        except Exception as exc:
            integrity_report = {"valid": False, "errors": [str(exc)]}

    validation = artifact.get("validation", {}) if artifact else {}
    decisions = artifact.get("decisions", {}) if artifact else {}
    parents = artifact.get("parents", {}) if artifact else {}
    resources = artifact.get("resource_envelopes", {}) if artifact else {}
    chain_checks = {
        "artifact_internal_and_live_sources": bool(integrity_report.get("valid")),
        "v33_parent_integrity": bool(
            artifact
            and parent_v33_artifact
            and parent_v33_integrity
            and parents.get("v33_artifact_sha256")
            == parent_v33_artifact.get("artifact_sha256")
        ),
        "v34_spec_identity": bool(
            artifact
            and artifact.get("optimizer", {}).get("spec_sha256")
            == spec.get("v34_spec_sha256")
        ),
        "validation_9_of_9": bool(
            validation.get("overall_pass") is True
            and len(validation.get("checks") or {}) == 9
            and all(bool(value) for value in (validation.get("checks") or {}).values())
        ),
        "schedule_identity": bool(
            artifact
            and artifact.get("native_lowering", {}).get("schedule_sha256")
            == elementary_schedule_sha256()
        ),
        "hardware_fail_closed": bool(
            artifact
            and artifact.get("claim_boundary", {}).get("hardware_executable") is False
            and artifact.get("claim_boundary", {}).get("qpu_submission_enabled") is False
            and artifact.get("claim_boundary", {}).get("qpu_jobs_submitted") == 0
            and decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }
    integral = bool(artifact and all(chain_checks.values()))
    state = (
        "SEALED · 9 / 9 EVIDENCE GATES"
        if integral
        else ("INVALID · FAIL CLOSED" if artifact else "WAITING · CANONICAL SEAL NOT FOUND")
    )
    state_class = "qp3-ok" if integral else ("qp3-block" if artifact else "qp3-warn")
    st.markdown(
        f'''<div class="qp3-panel"><div class="qp3-pk">V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER</div><div class="qp3-pt {state_class}">{escape(state)}</div><div class="qp3-note"><b>Spec:</b> <span class="qp3-sha">{escape(str(spec.get("v34_spec_sha", "—")))}</span> · <b>artifact:</b> <span class="qp3-sha">{escape(str((artifact or {}).get("artifact_sha256", "—"))[:24])}</span><br><b>Validation:</b> <span class="qp3-sha">{escape(str(validation.get("validation_manifest_sha256", "—"))[:24])}</span> · <b>resources:</b> <span class="qp3-sha">{escape(str(resources.get("resource_manifest_sha256", "—"))[:24])}</span><br><b>Exact interval identity:</b> 1[L≤v≤U] = 1 ⊕ 1[v≤L−1] ⊕ 1[v≥U+1] · <b>native wording:</b> provider-neutral elementary lowering, not backend-native.</div></div>''',
        unsafe_allow_html=True,
    )

    if not integral or not artifact:
        st.warning(
            "The V3.4 seal is missing or its live source/spec/parent chain is invalid. "
            "The optimized oracle and elementary mixer remain fail-closed in this runtime."
        )
        if integrity_report.get("errors"):
            with st.expander("V3.4 integrity errors", expanded=False):
                st.code("\n".join(str(item) for item in integrity_report["errors"]))
        return {
            "artifact": artifact,
            "chain_checks": chain_checks,
            "integrity": False,
            "seal_path": seal_path,
        }

    interval = validation.get("interval_identity", {})
    n40 = validation.get("n40_optimized_oracle", {})
    native = validation.get("native_c2xy", {})
    complete = resources.get("ledgers", {}).get(
        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
    )
    ring = resources.get("ledgers", {}).get(
        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_RING}", {}
    )
    complete_max = complete.get("maxima", {})
    ring_max = ring.get("maxima", {})

    q1, q2, q3, q4, q5 = st.columns(5)
    q1.metric("V3.4 evidence gates", "9 / 9")
    q2.metric("Interval basis cases", f"{int(interval.get('total_basis_cases', 0)):,}")
    q3.metric("N=40 witness swaps", f"{int(n40.get('total_nontrivial_witness_swaps', 0)):,}")
    q4.metric("C2-XY matrix cases", int(native.get("total_basis_angle_cases", 0)))
    q5.metric(
        "Matrix max |Δamp|",
        f"{float(native.get('maximum_amplitude_error', 0.0)):.2e}",
    )
    st.markdown(
        '''<div class="qp3-grid">
          <div class="qp3-card"><div class="qp3-ck">OPTIMIZED ORACLE</div><div class="qp3-cv qp3-ok">EQUIVALENCE · PASS</div><div class="qp3-cn">56 → 28 comparator networks · two logical qubits removed on every seed</div></div>
          <div class="qp3-card"><div class="qp3-ck">C2-XY ELEMENTARY</div><div class="qp3-cv qp3-ok">MATRIX + CLEANUP · PASS</div><div class="qp3-cn">12-gate exact schedule · 96/96 cases · dirty scratch probability 0</div></div>
          <div class="qp3-card"><div class="qp3-ck">BACKEND-NATIVE</div><div class="qp3-cv qp3-warn">NOT RUN</div><div class="qp3-cn">continuous RY synthesis, target ISA and routing remain unmeasured</div></div>
          <div class="qp3-card"><div class="qp3-ck">HARDWARE / ADVANTAGE</div><div class="qp3-cv qp3-block">BLOCKED · ZERO JOBS</div><div class="qp3-cn">no calibration, noise acceptance, optimization or execution evidence</div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    comparison = {
        int(row["seed"]): row for row in resources.get("comparison_vs_v33", [])
    }
    resource_rows = []
    for row in complete.get("per_seed", []):
        delta = comparison.get(int(row["seed"]), {})
        resource_rows.append(
            {
                "Seed": row.get("seed"),
                "Logical qubits · reuse": row.get("logical_qubits_sequential_reuse"),
                "IR gates · complete layer": row.get("provider_neutral_gate_count"),
                "Serial depth upper": row.get("serial_depth_upper_bound"),
                "CX · selected CCX model": row.get("cnot_after_selected_ccx_model"),
                "T subtotal · rotations excluded": row.get(
                    "t_count_oracle_and_ccx_subtotal"
                ),
                "Continuous RY": row.get("continuous_ry_rotations"),
                "Gate reduction vs V3.3": delta.get(
                    "provider_neutral_gate_reduction_after_12_gate_c2xy_lowering"
                ),
            }
        )
    st.markdown("**Canonical complete-swap resource ledger — exact IR + selected CCX model**")
    st.dataframe(pd.DataFrame(resource_rows), width="stretch", hide_index=True)

    topology_rows = [
        {
            "Topology": "RING · rejected control",
            "Edges": ring.get("edge_count"),
            "Oracle calls": ring.get("oracle_calls"),
            "Logical qubits · max": ring_max.get("logical_qubits_sequential_reuse"),
            "IR gates · max": ring_max.get("provider_neutral_gate_count"),
            "Serial depth · max": ring_max.get("serial_depth_upper_bound"),
            "Backend": "NOT RUN",
        },
        {
            "Topology": "COMPLETE · canonical accounting",
            "Edges": complete.get("edge_count"),
            "Oracle calls": complete.get("oracle_calls"),
            "Logical qubits · max": complete_max.get(
                "logical_qubits_sequential_reuse"
            ),
            "IR gates · max": complete_max.get("provider_neutral_gate_count"),
            "Serial depth · max": complete_max.get("serial_depth_upper_bound"),
            "Backend": "NOT RUN",
        },
    ]
    st.dataframe(pd.DataFrame(topology_rows), width="stretch", hide_index=True)
    st.error(
        "RESOURCE DECISION · STILL NOT NISQ-PRACTICAL. The optimization is real and "
        "strictly reduces all eight complete-layer ledgers even after inserting the "
        "12-gate C2-XY schedule, but the canonical construction still requires "
        f"{int(complete_max.get('provider_neutral_gate_count', 0)):,} provider-neutral "
        "operations at the worst seed before routing. This is an engineering rejection "
        "of the reference construction, not an impossibility result for future encodings."
    )

    schedule = artifact.get("construction", {}).get(
        "controlled_xy_elementary_schedule", []
    )
    schedule_rows = [
        {
            "#": index,
            "Stage": gate.get("stage"),
            "Gate": gate.get("gate"),
            "Controls": ", ".join(gate.get("controls", [])) or "—",
            "Target": gate.get("target"),
            "Angle": _angle_text(gate),
        }
        for index, gate in enumerate(schedule, start=1)
    ]
    with st.expander("Exact 12-gate C2-XY lowering and proof boundary", expanded=False):
        st.dataframe(pd.DataFrame(schedule_rows), width="stretch", hide_index=True)
        st.caption(
            "Four CCX + four CX + two continuous RY + two Clifford RZ(±π/2). "
            "The two clean scratch bits are borrowed from the uncomputed oracle work "
            "register and return to |00>. Discrete fault-tolerant rotation synthesis is NOT ESTIMATED."
        )

    decision_rows = [
        {
            "Claim": "Optimized oracle = frozen V3.2 predicate",
            "Decision": decisions.get("optimized_oracle_equivalence"),
            "Scope": "8 seeds · 2,400 swaps · 48 full gate-stream cases",
        },
        {
            "Claim": "Elementary controlled-XY identity",
            "Decision": decisions.get("controlled_xy_elementary_synthesis"),
            "Scope": "16 clean basis inputs × 6 angles",
        },
        {
            "Claim": "Complete feasible-graph connectivity",
            "Decision": decisions.get("complete_global_connectivity"),
            "Scope": "Not exhaustively enumerated",
        },
        {
            "Claim": "Backend-native lowering / routing",
            "Decision": decisions.get("backend_native_lowering"),
            "Scope": "No named target or coupling map",
        },
        {
            "Claim": "Quantum advantage",
            "Decision": decisions.get("quantum_advantage"),
            "Scope": "No hardware or runtime acceptance evidence",
        },
    ]
    st.markdown("**V3.4 independent claim ledger**")
    st.dataframe(pd.DataFrame(decision_rows), width="stretch", hide_index=True)

    left, right = st.columns(2)
    with left:
        st.download_button(
            "Download V3.4 optimized/native specification",
            data=json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
            mime="application/json",
            key=f"{key_prefix}_v34_spec_download",
        )
    with right:
        st.download_button(
            "Download sealed V3.4 optimized/native artifact",
            data=json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False),
            file_name=DEFAULT_SEAL_NAME,
            mime="application/json",
            key=f"{key_prefix}_v34_artifact_download",
        )
    with st.expander("V3.4 validation ladder, source chain and limitations", expanded=False):
        st.dataframe(
            pd.DataFrame(
                [
                    {"Gate": name, "Pass": bool(passed)}
                    for name, passed in (validation.get("checks") or {}).items()
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown("**Live chain checks**")
        st.dataframe(
            pd.DataFrame(
                [{"Check": name, "Pass": passed} for name, passed in chain_checks.items()]
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown("\n".join(f"- {item}" for item in artifact.get("limitations", [])))

    return {
        "artifact": artifact,
        "chain_checks": chain_checks,
        "integrity": True,
        "seal_path": seal_path,
    }


__all__ = ["render_v34_evidence_panel"]
