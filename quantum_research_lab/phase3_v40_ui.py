"""Institutional, fail-closed V4.0 connectivity and redesign surface."""

from __future__ import annotations

import hashlib
from html import escape
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v40_global_connectivity import (
    canonical_json_sha256,
    default_v40_artifact_path,
    validate_v40_artifact,
)


SectionHeader = Callable[[str, str, str], None]
EXPECTED_V40_ARTIFACT_SHA256 = "0fbbddcdf73dde6708814521cc3df741acb53c079e25b6c8829965de56778f01"
EXPECTED_V40_ARTIFACT_RAW_SHA256 = "3e2918c31ff01d0545125fb641c850af6429a1f8db11709f419c38a2d9f619f2"
EXPECTED_V40_SPEC_SHA256 = "3ab75513efc7014157ef74633ef5c4d9bd4f23b22390f341dbfd033cb8a9694e"


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


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def load_v40_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load only the exact offline-confirmed V4.0 artifact."""

    target = Path(path) if path is not None else default_v40_artifact_path()
    errors: list[str] = []
    try:
        raw = target.read_bytes()
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, {"valid": False, "errors": [str(exc)]}
    if not isinstance(payload, dict):
        return {}, {"valid": False, "errors": ["V4.0 artifact must be a JSON object."]}
    try:
        semantic = canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError) as exc:
        return payload, {"valid": False, "errors": [str(exc)]}
    raw_sha = hashlib.sha256(raw).hexdigest()
    parent = _mapping(_mapping(payload.get("parent")).get("authentication"))
    decisions = _mapping(payload.get("decisions"))
    aggregate = _mapping(payload.get("aggregate_evidence"))
    boundary = _mapping(payload.get("claim_boundary"))
    redesign = _mapping(payload.get("resource_redesign"))
    evidence = _mapping(payload.get("connectivity_evidence"))
    seed_rows = _rows(evidence.get("seed_rows"))
    if payload.get("artifact_sha256") != semantic or semantic != EXPECTED_V40_ARTIFACT_SHA256:
        errors.append("V4.0 artifact semantic identity mismatch.")
    if raw_sha != EXPECTED_V40_ARTIFACT_RAW_SHA256:
        errors.append("V4.0 artifact raw-file identity mismatch.")
    if parent.get("valid") is not True:
        errors.append("V4.0 sealed V3.9 parent chain is not authenticated.")
    if decisions.get("global_connectivity_decision") != "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE":
        errors.append("V4.0 global connectivity decision mismatch.")
    if not (
        len(seed_rows) == 8
        and [row.get("seed") for row in seed_rows] == [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
        and aggregate.get("all_eight_seeds_complete") is True
        and aggregate.get("total_feasible_vertices") == 21_655_776
        and aggregate.get("isolated_component_count") == 3
    ):
        errors.append("V4.0 complete eight-seed evidence contract mismatch.")
    if not (
        redesign.get("status") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and _mapping(redesign.get("result_fields")).get("cnot") == "NOT_EVALUATED"
    ):
        errors.append("V4.0 resource-redesign boundary mismatch.")
    if not (
        boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("V4.0 provider/hardware claim boundary mismatch.")
    try:
        scientific_report = validate_v40_artifact(payload)
    except Exception as exc:
        scientific_report = {"valid": False, "errors": [str(exc)], "checks": {}}
    if scientific_report.get("valid") is not True:
        errors.extend(
            f"Scientific artifact validation: {item}"
            for item in scientific_report.get("errors") or scientific_report.get("failed_checks") or ["unknown failure"]
        )
    return payload, {
        "valid": not errors,
        "errors": errors,
        "semantic_sha256": semantic,
        "raw_file_sha256": raw_sha,
        "scientific_checks": scientific_report.get("checks") or {},
    }


def normalize_v40_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    aggregate = _mapping(source.get("aggregate_evidence"))
    evidence = _mapping(source.get("connectivity_evidence"))
    boundary = _mapping(source.get("claim_boundary"))
    redesign = _mapping(source.get("resource_redesign"))
    parent = _mapping(_mapping(source.get("parent")).get("authentication"))
    seed_rows = _rows(evidence.get("seed_rows"))
    try:
        semantic = canonical_json_sha256({key: value for key, value in source.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError):
        semantic = ""
    authenticated = bool(
        artifact_integrity is True
        and spec_integrity is True
        and parent_integrity is True
        and parent.get("valid") is True
        and source.get("artifact_sha256") == semantic == EXPECTED_V40_ARTIFACT_SHA256
        and source.get("spec_sha256") == EXPECTED_V40_SPEC_SHA256
        and decisions.get("global_connectivity_decision") == "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE"
        and decisions.get("resource_architecture_decision") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and aggregate.get("all_eight_seeds_complete") is True
        and aggregate.get("total_feasible_vertices") == 21_655_776
        and aggregate.get("total_nine_core_incidences") == 216_557_760
        and [row.get("seed") for row in seed_rows] == [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
        and redesign.get("status") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and _mapping(redesign.get("result_fields")).get("cnot") == "NOT_EVALUATED"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    )
    return {
        "authenticated": authenticated,
        "artifact": dict(source) if authenticated else {},
        "artifact_sha256": str(source.get("artifact_sha256")) if authenticated else "NOT AUTHENTICATED",
        "overall": str(decisions.get("overall")) if authenticated else "NOT AUTHENTICATED",
        "connectivity_decision": str(decisions.get("global_connectivity_decision")) if authenticated else "NOT AUTHENTICATED",
        "production_admission": str(decisions.get("production_admission")) if authenticated else "NOT AUTHENTICATED",
        "next_gate": str(decisions.get("next_falsifiable_gate")) if authenticated else "NOT AUTHENTICATED",
        "aggregate": dict(aggregate) if authenticated else {},
        "seed_rows": seed_rows if authenticated else [],
        "redesign": dict(redesign) if authenticated else {},
        "v39_rejection": dict(_mapping(source.get("v39_resource_rejection"))) if authenticated else {},
        "boundary": dict(boundary) if authenticated else {},
        "graph_definition_sha256": str(evidence.get("graph_definition_sha256")) if authenticated else "NOT AUTHENTICATED",
        "counterexample_bundle_sha256": str(evidence.get("counterexample_bundle_sha256")) if authenticated else "NOT AUTHENTICATED",
    }


def _connectivity_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("seed_rows") or []:
        rows.append({
            "Seed": row.get("seed"),
            "Instance": row.get("instance_id"),
            "Method": row.get("method"),
            "Certificate kind": row.get("certificate_kind"),
            "Feasible vertices": row.get("feasible_vertex_count"),
            "State-graph edges": row.get("exact_state_graph_edge_count"),
            "Expected 9-core incidences": row.get("expected_nine_core_incidences"),
            "Observed 9-core incidences": row.get("observed_nine_core_incidences"),
            "Distinct 9-cores": row.get("distinct_nine_cores"),
            "Union attempts": row.get("union_attempts"),
            "Successful unions": row.get("successful_unions"),
            "Components": row.get("component_count"),
            "Largest component": row.get("largest_component_size"),
            "Smallest component": row.get("smallest_component_size"),
            "Coverage complete": row.get("coverage_complete"),
            "Enumeration SHA": row.get("enumeration_sha256"),
            "Core-index SHA": row.get("core_index_sha256"),
            "Union-forest SHA": row.get("forest_sha256"),
            "Independent replay": _mapping(row.get("replay")).get("all_stable_fields_match"),
            "Decision": row.get("decision"),
        })
    return pd.DataFrame(rows)


def _counterexample_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed in state.get("seed_rows") or []:
        for item in seed.get("isolated_counterexamples") or []:
            rows.append({
                "Seed": seed.get("seed"),
                "Mask": item.get("mask_hex"),
                "Selected indices": ", ".join(str(value) for value in item.get("selected_indices") or []),
                "Vertex feasible": item.get("vertex_exactly_feasible"),
                "Neighbors audited": item.get("neighbors_audited"),
                "Feasible neighbors": item.get("feasible_neighbor_count"),
                "All rejected": item.get("all_neighbors_rejected"),
                "First-failure ledger": ", ".join(f"{key}:{value}" for key, value in _mapping(item.get("first_failure_counts")).items()),
                "Neighbor ledger SHA": item.get("neighbor_ledger_sha256"),
                "Counterexample SHA": item.get("counterexample_sha256"),
            })
    return pd.DataFrame(rows)


def _redesign_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    redesign = _mapping(state.get("redesign"))
    rows: list[dict[str, Any]] = []
    for candidate in _rows(redesign.get("candidate_set")):
        rows.append({
            "Architecture": redesign.get("architecture_id"),
            "Candidate": candidate.get("candidate_id"),
            "Move family": candidate.get("move_family"),
            "Connectivity gate": candidate.get("required_connectivity"),
            "Bridge rule": candidate.get("bridge_rule", "N/A"),
            "CNOT": _mapping(redesign.get("result_fields")).get("cnot"),
            "Budget margin": _mapping(redesign.get("result_fields")).get("budget_margin"),
            "Status": redesign.get("status"),
        })
    return pd.DataFrame(rows)


def render_v40_connectivity_redesign_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v40_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
    )
    section_header(
        "V4.0 Global Feasible-Graph Connectivity & Resource Redesign",
        "EXACT VERTICES → 9-CORES → DSU COMPONENTS → COUNTEREXAMPLE → V4.1 PREREGISTRATION",
        "The complete feasible state graph is adjudicated independently from the future resource architecture. "
        "A connectivity result never repairs the V3.9 CNOT rejection, and a preregistration is not a resource result.",
    )
    st.markdown(
        """<style>
        .qv40-shell{border:1px solid rgba(117,235,255,.34);border-radius:22px;padding:21px 22px;margin:10px 0 14px;background:radial-gradient(circle at 91% 7%,rgba(255,71,122,.20),transparent 30%),radial-gradient(circle at 8% 100%,rgba(87,85,255,.15),transparent 30%),linear-gradient(132deg,rgba(2,18,31,.99),rgba(17,16,48,.98) 58%,rgba(48,11,37,.97));box-shadow:0 0 52px rgba(57,212,255,.10)}
        .qv40-k{font-size:.61rem;letter-spacing:.18em;color:#77efff;font-weight:950}.qv40-title{font-size:1.16rem;color:#ffb0bd;font-weight:950;margin:7px 0}.qv40-copy{font-size:.74rem;color:#b0bfd1;line-height:1.5}.qv40-tags{font-size:.61rem;color:#9bb0ca;letter-spacing:.10em;margin-top:10px}.qv40-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:11px 0 16px}.qv40-card{border:1px solid rgba(107,213,255,.17);background:rgba(3,15,29,.79);border-radius:14px;padding:12px}.qv40-label{font-size:.49rem;color:#849ab9;letter-spacing:.11em;font-weight:900}.qv40-value{font-size:.86rem;color:#f7f9ff;font-weight:950;margin:5px 0;overflow-wrap:anywhere}.qv40-pass{color:#75edbd}.qv40-reject{color:#ffaaa9}.qv40-warn{color:#ffd08a}.qv40-note{font-size:.60rem;color:#91a5ba;line-height:1.38}@media(max-width:1100px){.qv40-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.qv40-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    ok = bool(state["authenticated"])
    aggregate = _mapping(state.get("aggregate"))
    redesign = _mapping(state.get("redesign"))
    st.markdown(
        f"""<div class="qv40-shell" data-qv40-surface="connectivity-redesign-control-room" data-qv40-release="4.0" data-qv40-auth="{'pass' if ok else 'fail'}" data-qv40-role="overall-decision" data-qv40-connectivity="{'DISCONNECTED' if ok else 'INDETERMINATE'}" data-qv40-certificate-kind="{'DISCONNECTED_COUNTEREXAMPLE' if ok else 'BOUNDED_SEARCH_INCONCLUSIVE'}" data-qv40-coverage-complete="{'true' if ok else 'false'}" data-qv40-resource="PREREGISTERED_NOT_EVALUATED" data-qv40-v39-rejection="preserved" data-qv40-production="REJECTED" data-qv40-provider-calls="0" data-qv40-hardware="false">
        <div class="qv40-k">V4.0 · GLOBAL FEASIBLE-GRAPH CONNECTIVITY &amp; RESOURCE REDESIGN PREREGISTRATION</div>
        <div class="qv40-title">{escape(state['overall'])}</div>
        <div class="qv40-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT'} · SHA {escape(state['artifact_sha256'])}<br>Connectivity: {escape(state['connectivity_decision'])} · production: {escape(state['production_admission'])}</div>
        <div class="qv40-tags">RESEARCH_ONLY · EXACT_GRAPH · DUAL_REPLAY · PROVIDER_FREE · HARDWARE_EXECUTABLE FALSE</div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**V4.0 · GLOBAL FEASIBLE-GRAPH CONNECTIVITY & RESOURCE REDESIGN PREREGISTRATION**")
    st.markdown(
        f"""<div class="qv40-grid">
        <div class="qv40-card"><div class="qv40-label">ARTIFACT AUTH</div><div class="qv40-value {'qv40-pass' if ok else 'qv40-reject'}">{'PASS' if ok else 'NOT AUTHENTICATED'}</div><div class="qv40-note">raw + semantic + V3.9 lineage</div></div>
        <div class="qv40-card"><div class="qv40-label">EXACT VERTICES</div><div class="qv40-value">{escape(_fmt(aggregate.get('total_feasible_vertices')))}</div><div class="qv40-note">complete feasible universe, eight seeds</div></div>
        <div class="qv40-card"><div class="qv40-label">STATE-GRAPH EDGES</div><div class="qv40-value">{escape(_fmt(aggregate.get('total_exact_state_graph_edges')))}</div><div class="qv40-note">unique feasible one-swap adjacencies</div></div>
        <div class="qv40-card"><div class="qv40-label">9-CORE INCIDENCES</div><div class="qv40-value">{escape(_fmt(aggregate.get('total_nine_core_incidences')))}</div><div class="qv40-note">must equal 10 × vertices</div></div>
        <div class="qv40-card"><div class="qv40-label">SEEDS ADJUDICATED</div><div class="qv40-value qv40-pass">{'8 / 8' if ok else 'NOT AUTHENTICATED'}</div><div class="qv40-note">two registered enumeration splits</div></div>
        <div class="qv40-card"><div class="qv40-label">DISCONNECTED SEEDS</div><div class="qv40-value qv40-reject">{escape(_fmt(aggregate.get('disconnected_seed_count')))}</div><div class="qv40-note">{escape(str(aggregate.get('disconnected_seeds')) if ok else 'masked')}</div></div>
        <div class="qv40-card"><div class="qv40-label">ISOLATED COMPONENTS</div><div class="qv40-value qv40-reject">{escape(_fmt(aggregate.get('isolated_component_count')))}</div><div class="qv40-note">900 direct neighbor checks</div></div>
        <div class="qv40-card"><div class="qv40-label">GLOBAL CONNECTIVITY</div><div class="qv40-value qv40-reject">{'DISCONNECTED' if ok else 'NOT AUTHENTICATED'}</div><div class="qv40-note">complete graph counterexample</div></div>
        <div class="qv40-card"><div class="qv40-label">RESOURCE REDESIGN</div><div class="qv40-value qv40-warn">{'PREREGISTERED' if ok else 'NOT AUTHENTICATED'}</div><div class="qv40-note">CNOT not evaluated; no projection</div></div>
        <div class="qv40-card"><div class="qv40-label">HARDWARE / JOBS</div><div class="qv40-value qv40-reject">BLOCKED / ZERO</div><div class="qv40-note">no backend, credentials or provider calls</div></div></div>""",
        unsafe_allow_html=True,
    )

    for marker in (
        "GRAPH DEFINITION · FROZEN BEFORE CONNECTIVITY EVALUATION",
        "V3.9 ORDERED INDEX-PAIR COVERAGE IS NOT GLOBAL STATE-GRAPH CONNECTIVITY",
        "N=40 · K=10 · BANDS · 7 EXACT CONSTRAINTS · 8 FROZEN SEEDS",
        "EIGHT-SEED ALL-EVIDENCE RULE",
    ):
        st.markdown(f"**{marker}**")
    if ok:
        st.error(
            "DISCONNECTED COUNTEREXAMPLE · CERTIFIED — seeds 2207 and 7703 contain three exact feasible isolated portfolios. "
            "The complete one-out/one-in mixer is not globally ergodic, so no one-swap subtopology can repair it."
        )
        st.success(
            f"EXHAUSTIVE COVERAGE · PASS — {_fmt(aggregate.get('total_feasible_vertices'))} feasible vertices, "
            f"{_fmt(aggregate.get('total_exact_state_graph_edges'))} state edges and {_fmt(aggregate.get('total_nine_core_incidences'))} nine-core incidences, dual-replayed."
        )
    else:
        st.error("V4.0 evidence is absent or invalid. Exact counts, ledgers, counterexamples and downloads remain masked.")

    ledger = _connectivity_ledger(state)
    st.markdown("**Exact connectivity certificate ledger · eight frozen seeds**")
    st.dataframe(ledger, width="stretch", hide_index=True)

    counterexamples = _counterexample_ledger(state)
    st.markdown("**Closed-frontier counterexamples · exact isolated feasible portfolios**")
    st.dataframe(counterexamples, width="stretch", hide_index=True)

    if ok and not ledger.empty:
        chart = ledger[["Seed", "Feasible vertices", "State-graph edges"]].copy().set_index("Seed")
        chart = chart.apply(
            lambda column: column.map(lambda value: math.log10(max(1, int(value))))
        )
        st.markdown("**Exact universe scale by seed · log10 counts**")
        st.bar_chart(chart, width="stretch")
        component_chart = ledger[["Seed", "Components"]].copy().set_index("Seed")
        st.markdown("**Exact component count by seed**")
        st.bar_chart(component_chart, width="stretch")

    obligations = pd.DataFrame(
        [
            ("Complete feasible enumeration", "Group-product MITM + exact dyadic filter", "All exact-K group-valid states", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Enumeration replay", "Two group splits / two primary factor filters", "All eight seeds", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Adjacency identity", "Unique shared 9-core iff Hamming distance 2", "Complete state graph", "PASS" if ok else "NOT AUTHENTICATED"),
            ("DSU component forest", "10 incidences per vertex", "All feasible vertices", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Isolated frontier", "300 exact swaps per isolated vertex", "Three counterexamples", "PASS" if ok else "NOT AUTHENTICATED"),
            ("V3.9 resource architecture", "Frozen selected-model ledger", "Eight ordered layers", "REJECTED" if ok else "NOT AUTHENTICATED"),
            ("V4.1 resource redesign", "Preregistered only", "No resource ledger", "NOT EVALUATED"),
            ("Backend / hardware", "Not run", "Outside V4.0", "BLOCKED"),
        ],
        columns=["Obligation", "Method", "Declared universe", "State"],
    )
    st.markdown("**Evidence obligations · connectivity and resources remain independent**")
    st.dataframe(obligations, width="stretch", hide_index=True)

    st.markdown("**RESOURCE REDESIGN · PREREGISTERED · NOT EVALUATED**")
    st.warning(
        "V3.9 SELECTED-MODEL REJECTION · PRESERVED — the future architecture may change arithmetic and add certified two-out/two-in bridges, "
        "but it has no CNOT result, margin, backend result or hardware status in V4.0."
    )
    st.dataframe(_redesign_ledger(state), width="stretch", hide_index=True)
    if ok:
        st.caption(f"Architecture lock: {escape(str(redesign.get('architecture_id')))}")
        st.caption(f"Primary endpoint: {escape(str(redesign.get('primary_endpoint')))}")
        with st.expander("V4.1 correctness gates and immutable redesign rules", expanded=False):
            st.dataframe(
                pd.DataFrame({"Required future gate": list(redesign.get("correctness_gates") or [])}),
                width="stretch",
                hide_index=True,
            )
            st.code(str(redesign.get("edge_universe_policy")))
            st.code(str(redesign.get("multiple_candidate_policy")))

    st.markdown("**PRIMARY ENDPOINT · MAXIMUM CNOT ACROSS EIGHT SEEDS**")
    st.markdown("**POST-OBSERVATION CANDIDATE SWITCHING · PROHIBITED**")
    st.markdown("**NO EXPECTED OR PROJECTED RESOURCE CLAIM**")
    st.markdown("**Critical path · V3.9 REJECTION → EXACT STATE GRAPH → COUNTEREXAMPLE → AUGMENTED 1+2 EXCHANGE → LINEAR RESOURCE LEDGER → BACKEND → HARDWARE**")

    for label, suffix, help_text in (
        ("Recompute V4.0 global connectivity", "recompute", "The sealed release exposes immutable evidence only."),
        ("Override frozen graph definition", "graph_override", "Vertices and adjacency were frozen before confirmatory replay."),
        ("Relabel inconclusive connectivity evidence", "relabel", "No manual scientific relabeling is permitted."),
        ("Delete disconnected-component witness", "delete_witness", "Counterexamples are append-only evidence."),
        ("Override V3.9 resource rejection", "v39_override", "The V3.9 selected-model rejection remains binding."),
        ("Switch resource-redesign candidate after observation", "candidate_switch", "Both registered candidates must be published."),
        ("Override 2,500,000 CNOT gate", "budget_override", "The family maximum endpoint is fixed."),
        ("Open named-backend audit lane", "backend", "Connectivity and resource gates reject production admission."),
    ):
        st.button(label, disabled=True, key=f"{key_prefix}_v40_{suffix}", help=help_text)

    if ok:
        artifact_bytes = (json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        st.download_button(
            "Download sealed V4.0 connectivity artifact",
            data=artifact_bytes,
            file_name="SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v40_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V4.0 frozen connectivity specification",
                data=(json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
                file_name="PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v40_spec_download",
            )
        st.download_button(
            "Download V4.0 eight-seed connectivity ledger CSV",
            data=ledger.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V4_0_CONNECTIVITY_LEDGER.csv",
            mime="text/csv",
            key=f"{key_prefix}_v40_ledger_download",
        )
        st.download_button(
            "Download V4.0 isolated-counterexample ledger CSV",
            data=counterexamples.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V4_0_COUNTEREXAMPLES.csv",
            mime="text/csv",
            key=f"{key_prefix}_v40_counterexample_download",
        )

    st.warning(
        "V4.0 CLAIM BOUNDARY · CONNECTIVITY EVIDENCE AND SUCCESSOR PREREGISTRATION ONLY. "
        "The one-swap state graph is disconnected for this frozen family; no claim is made about augmented mixers, optimization performance or quantum advantage."
    )
    st.markdown(f"**{escape(state['next_gate'])}**")
    st.markdown("**BACKEND TRANSPILATION · NOT RUN**")
    st.markdown("**HARDWARE EXECUTION · BLOCKED · ZERO JOBS**")
    st.markdown("**QUANTUM ADVANTAGE · NOT CLAIMED**")
    return state


def apply_v40_encoding_state(
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
    projected.update({
        "v40_artifact_sha": _mapping(artifact).get("artifact_sha256"),
        "v40_global_connectivity_decision": decisions.get("global_connectivity_decision"),
        "v40_resource_architecture_decision": decisions.get("resource_architecture_decision"),
        "v40_next_falsifiable_gate": decisions.get("next_falsifiable_gate"),
        "v40_complete_global_connectivity": "DISCONNECTED",
        "encoding_status": "V4.0 ONE-SWAP MIXER REJECTED · GLOBAL CONNECTIVITY COUNTEREXAMPLE",
        "hardware_executable": False,
    })
    return projected


__all__ = [
    "EXPECTED_V40_ARTIFACT_RAW_SHA256",
    "EXPECTED_V40_ARTIFACT_SHA256",
    "EXPECTED_V40_SPEC_SHA256",
    "apply_v40_encoding_state",
    "load_v40_ui_artifact",
    "normalize_v40_artifact",
    "render_v40_connectivity_redesign_panel",
]
