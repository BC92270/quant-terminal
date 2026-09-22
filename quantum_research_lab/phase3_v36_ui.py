"""Institutional V3.6 structural-cost and algorithmic-rewrite surface.

The renderer is artifact-driven and provider-free. It never turns a research
lane, analytical floor, or classical delta identity into compiled-circuit or
hardware evidence.
"""

from __future__ import annotations

from html import escape
import json
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st


SectionHeader = Callable[[str, str, str], None]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_int(value: Any) -> str:
    return f"{_int(value):,}"


def _fmt_ratio(value: Any, decimals: int = 6) -> str:
    return f"{_float(value):,.{decimals}f}×"


def normalize_v36_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None = None,
) -> dict[str, Any]:
    """Normalize display fields without filling missing evidence with zero claims."""

    source = _mapping(artifact)
    attribution = _mapping(source.get("structural_cost_attribution"))
    summary = _mapping(attribution.get("summary"))
    raw_rows = attribution.get("rows")
    rows = [dict(row) for row in raw_rows if isinstance(row, Mapping)] if isinstance(raw_rows, list) else []
    rewrite = _mapping(source.get("rewrite_admission"))
    raw_lanes = rewrite.get("lanes")
    lanes = _mapping(raw_lanes)
    decisions = _mapping(source.get("decisions"))
    boundary = _mapping(source.get("claim_boundary"))
    incremental = _mapping(source.get("incremental_exposure_audit"))

    budget = _int(
        summary.get("selected_model_budget_cnot")
        or summary.get("canonical_selected_model_budget_cnot")
        or rewrite.get("selected_model_budget_cnot"),
        0,
    )
    provider_limit = _int(
        summary.get("documented_provider_limit_cnot")
        or summary.get("ibm_documented_two_qubit_limit")
        or rewrite.get("documented_provider_limit_cnot"),
        0,
    )
    pair_floor = _int(
        summary.get("required_compute_uncompute_pair_cnot_floor")
        or summary.get("minimum_required_oracle_pair_cnot")
        or summary.get("nontrivial_oracle_pair_floor_cnot")
        or summary.get("oracle_pair_floor_cnot"),
        0,
    )
    max_total = _int(
        summary.get("canonical_total_cnot_max")
        or summary.get("max_total_cnot")
        or summary.get("maximum_complete_layer_cnot"),
        max((_int(row.get("total_cnot")) for row in rows), default=0),
    )
    min_oracle = _int(
        summary.get("per_oracle_cnot_min")
        or summary.get("min_per_oracle_cnot")
        or summary.get("minimum_per_oracle_cnot"),
        min((_int(row.get("per_oracle_cnot")) for row in rows), default=0),
    )
    max_oracle_share = max(
        (_float(row.get("oracle_share_of_total")) for row in rows),
        default=0.0,
    )
    if max_oracle_share <= 1.0:
        max_oracle_share *= 100.0

    qpu_jobs = _int(boundary.get("qpu_jobs_submitted"), 0)
    integrity = bool(artifact_integrity)
    decision = str(
        decisions.get("overall")
        or decisions.get("rewrite_admission")
        or rewrite.get("decision")
        or "ARCHITECTURE_REWRITE_REQUIRED"
    )
    return {
        "artifact": source,
        "artifact_integrity": integrity,
        "artifact_sha256": str(source.get("artifact_sha256") or "NOT_AUTHENTICATED"),
        "budget": budget,
        "provider_limit": provider_limit,
        "pair_floor": pair_floor,
        "max_total": max_total,
        "min_oracle": min_oracle,
        "max_oracle_share_percent": max_oracle_share,
        "rows": rows,
        "lanes": dict(lanes),
        "decisions": dict(decisions),
        "boundary": dict(boundary),
        "incremental": dict(incremental),
        "decision": decision,
        "qpu_jobs": qpu_jobs,
    }


def _lane_rows(lanes: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, payload in lanes.items():
        lane = _mapping(payload)
        rows.append(
            {
                "Lane": str(name),
                "Semantic class": str(
                    lane.get("semantic_classification") or "NOT_RECORDED"
                ),
                "Status": str(lane.get("status") or "NOT_RECORDED"),
                "Admission": str(
                    lane.get("admission_decision") or "NOT_RECORDED"
                ),
                "Selected-model CNOT": (
                    _int(lane.get("selected_model_cnot"))
                    if lane.get("selected_model_cnot") is not None
                    else None
                ),
                "Evidence boundary": str(
                    lane.get("reason")
                    or lane.get("evidence_boundary")
                    or "NOT_RECORDED"
                ),
            }
        )
    return rows


def render_v36_algorithmic_reduction_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None = None,
    artifact_integrity: bool | None = None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    """Render the sealed structural diagnosis and return normalized state."""

    state = normalize_v36_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
    )
    section_header(
        "V3.6 Structural Cost Attribution & Algorithmic Rewrite Gate",
        "ORACLE CONCENTRATION → STRUCTURAL FLOOR → SEMANTIC CLASS → REWRITE",
        "V3.6 identifies why the V3.4 representation fails before backend work. "
        "It rejects topology-only optimization as sufficient, keeps uncompiled "
        "rewrite candidates blocked and submits zero QPU jobs.",
    )
    st.markdown(
        """<style>
        .qv36-shell{position:relative;overflow:hidden;border:1px solid rgba(139,113,255,.35);border-radius:20px;padding:19px 20px;margin:10px 0 16px;background:linear-gradient(128deg,rgba(7,15,33,.97),rgba(20,12,43,.97) 56%,rgba(43,13,38,.94));box-shadow:0 0 42px rgba(105,79,255,.09)}
        .qv36-shell:after{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 38%,rgba(114,232,255,.055) 49%,transparent 60%);transform:translateX(-90%);animation:qv36scan 12s linear infinite;pointer-events:none}@keyframes qv36scan{to{transform:translateX(90%)}}
        .qv36-k{font-size:.61rem;letter-spacing:.17em;color:#79ecff;font-weight:850}.qv36-title{font-size:1.18rem;color:#fff;font-weight:900;margin:6px 0}.qv36-copy{font-size:.74rem;line-height:1.5;color:#a5b2c8;max-width:1120px}
        .qv36-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:11px 0 17px}.qv36-card{border:1px solid rgba(111,207,255,.16);background:rgba(3,13,29,.75);border-radius:14px;padding:12px}.qv36-label{font-size:.53rem;letter-spacing:.13em;color:#7e91aa;font-weight:800}.qv36-value{font-size:.98rem;color:#f6f8ff;font-weight:880;margin:5px 0}.qv36-note{font-size:.65rem;line-height:1.4;color:#8fa0b7}.qv36-reject{color:#ff98b5}.qv36-block{color:#ffd28f}.qv36-pass{color:#77edbd}
        .qv36-bar{height:10px;border-radius:999px;background:#1b2940;overflow:hidden;margin:10px 0 5px}.qv36-oracle{height:100%;width:99.99998%;background:linear-gradient(90deg,#754cff,#ff5f96)}
        @media(max-width:900px){.qv36-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.qv36-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    integrity_label = "AUTHENTICATED" if state["artifact_integrity"] else "INVALID / ABSENT"
    st.markdown(
        f"""<div class="qv36-shell">
        <div class="qv36-k">V3.6 · STRUCTURAL COST ATTRIBUTION & REWRITE GATE</div>
        <div class="qv36-title">{escape(state['decision'])}</div>
        <div class="qv36-copy">The frozen cost identity is decomposed before any backend is selected. Topology pruning cannot remove the mandatory oracle floor; incremental exposure remains a research candidate until a coherent reversible compiler and clean-ancilla proof exist.</div>
        <div class="qv36-bar"><div class="qv36-oracle"></div></div>
        <div class="qv36-copy">Oracle concentration · {state['max_oracle_share_percent']:.8f}% at the most concentrated authenticated row · artifact {escape(integrity_label)} · SHA {escape(state['artifact_sha256'][:24])}</div>
        </div>
        <div class="qv36-grid">
          <div class="qv36-card"><div class="qv36-label">CHEAPEST FROZEN ORACLE</div><div class="qv36-value">{_fmt_int(state['min_oracle'])}</div><div class="qv36-note">selected-model CNOT per call · not backend-native</div></div>
          <div class="qv36-card"><div class="qv36-label">MANDATORY ORACLE PAIR</div><div class="qv36-value qv36-reject">{_fmt_int(state['pair_floor'])}</div><div class="qv36-note">compute/uncompute floor inside the frozen architecture</div></div>
          <div class="qv36-card"><div class="qv36-label">INTERNAL REWRITE BUDGET</div><div class="qv36-value">{_fmt_int(state['budget'])}</div><div class="qv36-note">provider-neutral research gate · distinct from provider limit</div></div>
          <div class="qv36-card"><div class="qv36-label">HARDWARE EXECUTION</div><div class="qv36-value qv36-block">BLOCKED · ZERO JOBS</div><div class="qv36-note">jobs submitted: {state['qpu_jobs']} · advantage not claimed</div></div>
        </div>""",
        unsafe_allow_html=True,
    )

    if not state["artifact_integrity"]:
        st.error(
            "V3.6 artifact integrity is absent or invalid. No structural or rewrite "
            "decision below may be used as authenticated release evidence."
        )
    else:
        st.error(
            "TOPOLOGY-ONLY · REJECTED STRUCTURAL FLOOR — even the cheapest mandatory "
            "frozen oracle compute/uncompute pair exceeds the internal rewrite budget. "
            "This rejection is scoped to the frozen V3.4 architecture and cost model."
        )

    if state["rows"]:
        table_rows = []
        for row in state["rows"]:
            share = _float(row.get("oracle_share_of_total"))
            if share <= 1.0:
                share *= 100.0
            table_rows.append(
                {
                    "Seed": _int(row.get("seed")),
                    "Instance": str(row.get("instance_id") or "NOT_RECORDED"),
                    "Total selected-model CNOT": _int(row.get("total_cnot")),
                    "Oracle CNOT / call": _int(row.get("per_oracle_cnot")),
                    "Oracle calls": _int(row.get("oracle_calls")),
                    "Mixer edge CNOT": _int(row.get("edge_cnot_subtotal")),
                    "Oracle share %": share,
                    "Exact reconstruction": bool(row.get("reconstruction_exact")),
                    "Division remainder": _int(row.get("division_remainder")),
                }
            )
        st.markdown("**Authenticated eight-seed structural reconstruction**")
        st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)
        st.caption(
            "Counts reproduce the frozen selected 7T-CCX accounting identity. They "
            "are not routed native counts, timing estimates or physical lower bounds."
        )

    lane_rows = _lane_rows(state["lanes"])
    if lane_rows:
        st.markdown("**Algorithmic rewrite portfolio — independent semantic lanes**")
        st.dataframe(pd.DataFrame(lane_rows), width="stretch", hide_index=True)

    incremental = state["incremental"]
    delta_rows = _int(
        incremental.get("total_constraint_row_cases")
        or incremental.get("validated_delta_rows")
        or incremental.get("rows_checked")
        or incremental.get("classical_delta_rows"),
        0,
    )
    delta_pass = bool(
        incremental.get("passed")
        or incremental.get("all_delta_identities_pass")
        or incremental.get("classical_delta_identity_pass")
    )
    st.info(
        "INCREMENTAL EXPOSURE · BLOCKED PENDING REVERSIBLE COMPILER — classical "
        f"swap-delta identities: {delta_rows:,} rows, "
        f"{'PASS' if delta_pass else 'NOT AUTHENTICATED'}. A classical identity is "
        "not a coherent unitary update, a clean-uncompute proof or a gate ledger."
    )

    boundary_rows = [
        {
            "Evidence gate": "Exact full-operator successor",
            "State": "NOT AVAILABLE",
            "Why": "No compiled rewrite clears semantic, cleanup, connectivity and budget gates.",
        },
        {
            "Evidence gate": "Named-backend lane",
            "State": "NOT RUN",
            "Why": "V3.6 is provider-free and the numerator rewrite gate is still closed.",
        },
        {
            "Evidence gate": "Hardware execution",
            "State": "BLOCKED · ZERO JOBS",
            "Why": "Credentials, provider session and submission remain prohibited.",
        },
        {
            "Evidence gate": "Quantum advantage",
            "State": "NOT CLAIMED",
            "Why": "No accepted backend, hardware run, optimization or runtime evidence.",
        },
    ]
    st.markdown("**Critical path & claim boundary**")
    st.dataframe(pd.DataFrame(boundary_rows), width="stretch", hide_index=True)
    st.button(
        "Open named-backend transpilation lane",
        disabled=True,
        key=f"{key_prefix}_v36_backend_lane",
        help="Blocked until an exact compiled successor clears the V3.6 rewrite budget.",
    )

    artifact_payload = dict(state["artifact"])
    if artifact_payload:
        st.download_button(
            "Download sealed V3.6 structural-reduction artifact",
            data=json.dumps(
                artifact_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"),
            file_name="SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v36_artifact_download",
        )
    spec_payload = dict(_mapping(spec))
    if spec_payload:
        st.download_button(
            "Download V3.6 algorithmic-reduction specification",
            data=json.dumps(
                spec_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"),
            file_name="PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json",
            mime="application/json",
            key=f"{key_prefix}_v36_spec_download",
        )

    st.warning(
        "V3.6 CLAIM BOUNDARY · STRUCTURAL DIAGNOSIS ONLY. The result rejects "
        "topology-only optimization as sufficient inside the frozen V3.4 formula. "
        "It does not establish a compiled incremental oracle, backend viability, "
        "hardware fidelity, optimization performance or quantum advantage."
    )
    return state


__all__ = ["normalize_v36_artifact", "render_v36_algorithmic_reduction_panel"]
