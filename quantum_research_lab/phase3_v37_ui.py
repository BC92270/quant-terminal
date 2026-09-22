"""Institutional V3.7 reversible-prototype evidence surface.

The renderer is deliberately artifact-driven and fail-closed.  A passing
small-instance prototype is displayed only when the supplied integrity report,
parent lineage, exhaustive checks and zero-job claim boundary agree.  The
surface never promotes the registered N=4, K=2 compiler fixture to an N=40
successor, an elementary CNOT ledger, a backend result or hardware evidence.
"""

from __future__ import annotations

from html import escape
import json
from math import comb
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v37_reversible_compiler import validate_v37_artifact


SectionHeader = Callable[[str, str, str], None]

_DIFFERENTIAL_CHECKS = (
    "all_36_exact_k_portfolio_edge_cases_present",
    "all_72_constraint_row_cases_present",
    "all_integer_deltas_equal_full_recompute",
    "all_feasibility_predicates_equal_full_recompute",
    "every_swap_preserves_exact_k",
    "compiled_guard_equals_registered_support_rule",
)

_COMPILER_CHECKS = (
    "compiled_action_matches_ideal_on_every_basis_column",
    "compiled_adjoint_restores_every_basis_column",
    "every_basis_column_preserves_norm",
    "all_non_target_basis_states_are_identity",
    "all_nonzero_target_support_has_consistent_cache",
    "complete_ordered_layer_matches_independent_reference_multi_beta",
    "complete_ordered_layer_adjoint_restores_every_basis_column",
    "complete_ordered_layer_gram_is_identity",
    "complete_ordered_layer_preserves_norm",
    "complete_ordered_layer_preserves_feasible_consistent_support",
    "feasible_fixture_graph_is_connected",
    "logical_ir_replay_is_deterministic",
    "zero_ancilla_and_zero_scratch_allocated",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, Mapping)]


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return None


def _fmt_int(value: int | None) -> str:
    return f"{value:,}" if value is not None else "NOT RECORDED"


def _fmt_scientific(value: float | None) -> str:
    return f"{value:.3e}" if value is not None else "NOT RECORDED"


def _edge_key(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    left = _int_or_none(value[0])
    right = _int_or_none(value[1])
    return (left, right) if left is not None and right is not None else None


def normalize_v37_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None = None,
) -> dict[str, Any]:
    """Normalize an artifact without converting missing evidence into claims."""

    source = _mapping(artifact)
    fixture = _mapping(source.get("fixture"))
    registers = _mapping(source.get("register_contract"))
    differential = _mapping(source.get("differential_evidence"))
    differential_checks = _mapping(differential.get("checks"))
    compiler = _mapping(source.get("compiler_evidence"))
    compiler_checks = _mapping(compiler.get("checks"))
    connectivity = _mapping(compiler.get("feasible_connectivity"))
    cleanup = _mapping(compiler.get("scratch_cleanup_proof"))
    transitions = _mapping(source.get("coherent_transition_ledger"))
    transition_rows_raw = _mapping_rows(transitions.get("rows"))
    ledger = _mapping(source.get("resource_ledger"))
    scan = _mapping(ledger.get("complete_edge_scan"))
    decisions = _mapping(source.get("decisions"))
    boundary = _mapping(source.get("claim_boundary"))
    parent = _mapping(source.get("parent"))
    parent_authentication = _mapping(parent.get("authentication"))

    n = _int_or_none(fixture.get("n"))
    k = _int_or_none(fixture.get("k"))
    exact_k_state_count = (
        comb(n, k)
        if n is not None and k is not None and 0 <= k <= n
        else None
    )
    try:
        independently_valid = validate_v37_artifact(source).get("valid") is True
    except Exception:
        independently_valid = False
    integrity = artifact_integrity is True and independently_valid
    fixture_gate = bool(
        fixture.get("fixture_id") == "V37_SYNTHETIC_EXACT_K_N4_K2_V1"
        and fixture.get("classification")
        == "SYNTHETIC_COMPILER_FIXTURE · PROTOTYPE_ONLY"
        and n == 4
        and k == 2
        and len(_mapping_rows(fixture.get("constraint_rows"))) == 2
        and len(fixture.get("edges") or []) == 6
    )
    register_gate = bool(
        registers.get("bit_order") == "LITTLE_ENDIAN_INTEGER_INDEX"
        and registers.get("data_qubits") == 10
        and registers.get("ancilla_qubits") == 0
        and registers.get("scratch_qubits") == 0
        and registers.get("full_domain_basis_states") == 1024
        and registers.get("inconsistent_cache_policy")
        == "IDENTITY_OUTSIDE_COMPILED_ENDPOINTS"
    )
    differential_gate = bool(
        differential.get("passed") is True
        and all(differential_checks.get(name) is True for name in _DIFFERENTIAL_CHECKS)
    )
    compiler_gate = bool(
        compiler.get("passed") is True
        and all(compiler_checks.get(name) is True for name in _COMPILER_CHECKS)
        and compiler.get("full_domain_basis_states") == 1024
    )
    cleanup_gate = bool(
        cleanup.get("allocated_ancilla_qubits") == 0
        and cleanup.get("allocated_scratch_qubits") == 0
        and scan.get("ancilla_qubits") == 0
        and scan.get("scratch_qubits") == 0
    )
    transition_gate = bool(
        transitions.get("transition_count") == 4
        and len(transition_rows_raw) == 4
        and all(
            row.get("reference_action_state") == "PASSED_ALL_REGISTERED_BETAS"
            and row.get("roundtrip_state")
            == "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
            and row.get("off_target_identity_state") == "PASSED"
            and row.get("clean_scratch_state")
            == "PASSED_ZERO_ANCILLA_ZERO_SCRATCH"
            and bool(row.get("pair_ir_sha256"))
            for row in transition_rows_raw
        )
    )
    logical_ledger_gate = bool(
        ledger.get("ir_basis") == ["PATTERN_MCX", "PATTERN_MCRX"]
        and ledger.get("elementary_basis_decomposition") == "NOT_IMPLEMENTED"
        and ledger.get("selected_model_cnot") == "NOT_ESTIMATED"
        and ledger.get("n40_projection") == "NOT_RUN"
        and ledger.get("selected_model_budget_gate") == "NOT_EVALUATED"
        and ledger.get("hardware_executable") is False
    )
    decision_gate = bool(
        decisions.get("overall")
        == "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
        and decisions.get("incremental_exposure_prototype")
        == "PASSED_ON_REGISTERED_N4_K2_FIXTURE"
        and decisions.get("coherent_cache_update")
        == "PASSED_EXHAUSTIVE_SMALL_INSTANCE"
        and decisions.get("scratch_cleanup")
        == "PASSED_ZERO_ANCILLA_GRAY_UNCOMPUTE"
        and decisions.get("production_n40_compiler")
        == "N40_REWRITE_ADMISSION_BLOCKED"
        and decisions.get("n40_rewrite_admission")
        == "N40_REWRITE_ADMISSION_BLOCKED"
        and decisions.get("elementary_basis_decomposition") == "BLOCKED_NOT_BUILT"
        and decisions.get("selected_model_budget") == "NOT_EVALUATED"
        and decisions.get("backend_native") == "NOT_RUN_PROVIDER_FREE_PHASE"
    )
    boundary_gate = bool(
        source.get("research_classification") == "RESEARCH_ONLY"
        and source.get("prototype_classification") == "PROTOTYPE_ONLY"
        and boundary.get("prototype_scope")
        == "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY"
        and boundary.get("v34_exact_successor_equivalence") == "NOT_CLAIMED"
        and boundary.get("production_n40_equivalence") == "NOT_CLAIMED"
        and boundary.get("selected_model_cnot") == "NOT_ESTIMATED"
        and boundary.get("provider_sdk_imported") is False
        and boundary.get("provider_credentials_read") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("backend_transpilation") == "NOT_RUN"
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("optimization_performance") == "NOT_TESTED"
        and boundary.get("global_impossibility") == "NOT_CLAIMED"
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    )
    parent_gate = parent_authentication.get("valid") is True

    gates = {
        "artifact_integrity": integrity,
        "v36_parent_lineage": parent_gate,
        "sealed_fixture_contract": fixture_gate,
        "register_contract": register_gate,
        "differential_predicate_and_cache": differential_gate,
        "coherent_two_level_action": compiler_gate,
        "coherent_transition_ledger": transition_gate,
        "scratch_cleanup": cleanup_gate,
        "logical_ir_ledger": logical_ledger_gate,
        "prototype_decision": decision_gate,
        "fail_closed_claim_boundary": boundary_gate,
    }
    prototype_pass = bool(source and all(gates.values()))

    edge_reports = {
        key: row
        for row in _mapping_rows(compiler.get("edge_reports"))
        if (key := _edge_key(row.get("edge"))) is not None
    }
    edge_rows: list[dict[str, Any]] = []
    for row in _mapping_rows(ledger.get("rows")):
        key = _edge_key(row.get("edge"))
        validation_row = edge_reports.get(key, {})
        edge_rows.append(
            {
                "Edge": f"{key[0]}↔{key[1]}" if key is not None else "NOT RECORDED",
                "Coherent pairs": _int_or_none(row.get("two_level_pair_count")),
                "Endpoint Hamming": ", ".join(
                    str(item) for item in (row.get("endpoint_hamming_distances") or [])
                )
                or "—",
                "PATTERN_MCX": _int_or_none(row.get("pattern_mcx_count")),
                "PATTERN_MCRX": _int_or_none(row.get("pattern_mcrx_count")),
                "Logical gates": _int_or_none(row.get("logical_gate_count")),
                "Basis columns": _int_or_none(validation_row.get("basis_columns_checked")),
                "Max action error": _float_or_none(validation_row.get("maximum_action_error")),
                "Max round-trip error": _float_or_none(
                    validation_row.get("maximum_roundtrip_error")
                ),
                "Off-target identity": validation_row.get(
                    "off_target_identity_exact_within_tolerance"
                )
                is True,
                "IR SHA-256": str(row.get("edge_ir_sha256") or "NOT RECORDED")[:20],
            }
        )

    coherent_rows: list[dict[str, Any]] = []
    for row in transition_rows_raw:
        key = _edge_key(row.get("edge"))
        coherent_rows.append(
            {
                "Edge": f"{key[0]}↔{key[1]}" if key is not None else "NOT RECORDED",
                "Source portfolio": "".join(
                    str(bit) for bit in (row.get("source_portfolio") or [])
                ),
                "Target portfolio": "".join(
                    str(bit) for bit in (row.get("target_portfolio") or [])
                ),
                "Source cache": str(row.get("source_caches") or []),
                "Target cache": str(row.get("target_caches") or []),
                "Cache delta": str(row.get("cache_delta") or []),
                "Basis pair": f"{row.get('source_basis', '—')} ↔ {row.get('target_basis', '—')}",
                "Hamming": _int_or_none(row.get("endpoint_hamming_distance")),
                "Logical gates": _int_or_none(row.get("logical_gate_count")),
                "Reference action": str(row.get("reference_action_state") or "NOT RECORDED"),
                "Round trip": str(row.get("roundtrip_state") or "NOT RECORDED"),
                "Off-target": str(row.get("off_target_identity_state") or "NOT RECORDED"),
                "Scratch": str(row.get("clean_scratch_state") or "NOT RECORDED"),
                "Pair IR SHA-256": str(row.get("pair_ir_sha256") or "NOT RECORDED")[:20],
            }
        )

    register_rows = []
    for row in _mapping_rows(registers.get("registers")):
        register_rows.append(
            {
                "Register": str(row.get("name") or "NOT RECORDED"),
                "Offset": _int_or_none(row.get("offset")),
                "Width": _int_or_none(row.get("width")),
                "Encoding": str(row.get("encoding") or "NOT RECORDED"),
            }
        )

    return {
        "artifact": source,
        "artifact_integrity": integrity,
        "artifact_sha256": str(source.get("artifact_sha256") or "NOT AUTHENTICATED"),
        "validation_sha256": str(
            compiler.get("compiler_validation_sha256") or "NOT AUTHENTICATED"
        ),
        "fixture_sha256": str(fixture.get("fixture_sha256") or "NOT AUTHENTICATED"),
        "fixture_id": str(fixture.get("fixture_id") or "NOT AUTHENTICATED"),
        "n": n,
        "k": k,
        "constraint_count": len(_mapping_rows(fixture.get("constraint_rows"))),
        "exact_k_state_count": exact_k_state_count,
        "feasible_state_count": _int_or_none(connectivity.get("feasible_node_count")),
        "connected": connectivity.get("connected") is True,
        "register_width": _int_or_none(compiler.get("register_width")),
        "full_domain_basis_states": _int_or_none(
            compiler.get("full_domain_basis_states")
        ),
        "basis_columns_checked": _int_or_none(compiler.get("basis_columns_checked")),
        "two_level_pair_beta_checks": _int_or_none(
            compiler.get("two_level_pair_beta_checks")
        ),
        "validation_betas": list(compiler.get("validation_betas") or []),
        "maximum_action_error": _float_or_none(compiler.get("maximum_action_error")),
        "maximum_roundtrip_error": _float_or_none(
            compiler.get("maximum_roundtrip_error")
        ),
        "maximum_norm_error": _float_or_none(compiler.get("maximum_norm_error")),
        "complete_layer_maximum_norm_error": _float_or_none(
            compiler.get("complete_layer_maximum_norm_error")
        ),
        "complete_layer_basis_columns_checked": _int_or_none(
            compiler.get("complete_layer_basis_columns_checked")
        ),
        "complete_layer_gram_entries_checked": _int_or_none(
            compiler.get("complete_layer_gram_entries_checked")
        ),
        "complete_layer_maximum_action_error": _float_or_none(
            compiler.get("complete_layer_maximum_action_error")
        ),
        "complete_layer_maximum_roundtrip_error": _float_or_none(
            compiler.get("complete_layer_maximum_roundtrip_error")
        ),
        "complete_layer_maximum_gram_error": _float_or_none(
            compiler.get("complete_layer_maximum_gram_error")
        ),
        "logical_ir_replay_sha256": str(
            compiler.get("logical_ir_replay_sha256") or "NOT AUTHENTICATED"
        ),
        "portfolio_edge_cases": _int_or_none(
            differential.get("portfolio_edge_cases")
        ),
        "constraint_row_cases": _int_or_none(differential.get("constraint_row_cases")),
        "scan": dict(scan),
        "selected_model_cnot": str(
            ledger.get("selected_model_cnot") or "NOT RECORDED"
        ),
        "elementary_basis_decomposition": str(
            ledger.get("elementary_basis_decomposition") or "NOT RECORDED"
        ),
        "ledger_boundary": str(ledger.get("ledger_boundary") or "NOT RECORDED"),
        "register_rows": register_rows,
        "edge_rows": edge_rows,
        "coherent_rows": coherent_rows,
        "differential_rows": _mapping_rows(differential.get("rows")),
        "gates": gates,
        "prototype_pass": prototype_pass,
        "prototype_status": (
            "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
            if prototype_pass
            else "INVALID / ABSENT · FAIL CLOSED"
        ),
        "n40_status": (
            "N40_REWRITE_ADMISSION_BLOCKED"
            if prototype_pass
            else "N40 STATUS · NOT AUTHENTICATED"
        ),
        "boundary": dict(boundary),
        "decisions": dict(decisions),
    }


def _proof_rows(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    labels = (
        ("artifact_integrity", "V3.7 artifact integrity", "Self-hash and independent loader"),
        ("v36_parent_lineage", "V3.6 parent lineage", "Frozen semantic/raw parent commitments"),
        ("sealed_fixture_contract", "Registered synthetic fixture", "N=4 · K=2 · two integer exposures"),
        ("register_contract", "Register encoding", "10 data qubits · zero allocated ancilla/scratch"),
        ("differential_predicate_and_cache", "Differential predicate + cache", "Incremental integers versus full recompute"),
        ("coherent_two_level_action", "Coherent two-level action", "All basis columns, registered β schedule"),
        ("coherent_transition_ledger", "Four coherent transitions", "Sealed portfolio-plus-cache endpoint ledger"),
        ("scratch_cleanup", "Scratch cleanup", "Gray compute · MCRX · reverse Gray path"),
        ("logical_ir_ledger", "Logical IR ledger", "PATTERN_MCX / PATTERN_MCRX only"),
        ("prototype_decision", "Small-instance admission", "Prototype decision only"),
        ("fail_closed_claim_boundary", "Provider/hardware veto", "Provider calls 0 · QPU jobs 0"),
    )
    authenticated = bool(state.get("prototype_pass"))
    gates = _mapping(state.get("gates"))
    return [
        {
            "Evidence gate": label,
            "State": "PASS" if authenticated and gates.get(key) is True else "FAIL CLOSED",
            "Scope": scope,
        }
        for key, label, scope in labels
    ]


def _differential_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    rendered = []
    for row in rows:
        cached = row.get("cached") or []
        prospective = row.get("prospective") or []
        rendered.append(
            {
                "Portfolio": "".join(str(bit) for bit in (row.get("portfolio") or [])),
                "Edge": "↔".join(str(index) for index in (row.get("edge") or [])),
                "Cache": str(cached),
                "Prospective": str(prospective),
                "Full recompute": str(row.get("full_recompute") or []),
                "Delta exact": row.get("delta_exact") is True,
                "Predicate exact": row.get("predicate_exact") is True,
                "Exact-K": row.get("exact_k_preserved") is True,
                "Guard exact": row.get("guard_exact") is True,
            }
        )
    return pd.DataFrame(rendered)


def render_v37_reversible_prototype_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None = None,
    artifact_integrity: bool | None = None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    """Render the V3.7 prototype and return its fail-closed normalized state."""

    state = normalize_v37_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
    )
    section_header(
        "V3.7 Reversible Incremental-Exposure Prototype",
        "SEALED FIXTURE → COHERENT TWO-LEVEL UPDATE → SCRATCH CLEANUP → SCALE GATE",
        "V3.7 closes one narrow V3.6 evidence gap on a registered synthetic "
        "N=4, K=2 fixture. It validates coherent portfolio-plus-cache motion and "
        "clean Gray-path reversal, but does not compile or price the frozen N=40 problem.",
    )
    st.markdown(
        """<style>
        .qv37-shell{position:relative;overflow:hidden;border:1px solid rgba(89,230,203,.30);border-radius:20px;padding:19px 20px;margin:10px 0 16px;background:linear-gradient(128deg,rgba(4,20,31,.98),rgba(12,18,42,.97) 57%,rgba(31,14,48,.95));box-shadow:0 0 42px rgba(76,226,203,.08)}
        .qv37-shell:after{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 38%,rgba(105,247,218,.055) 49%,transparent 60%);transform:translateX(-90%);animation:qv37scan 12s linear infinite;pointer-events:none}@keyframes qv37scan{to{transform:translateX(90%)}}
        .qv37-k{font-size:.61rem;letter-spacing:.17em;color:#77efd4;font-weight:850}.qv37-title{font-size:1.16rem;color:#fff;font-weight:900;margin:6px 0}.qv37-copy{font-size:.74rem;line-height:1.5;color:#a5b6c8;max-width:1120px}.qv37-tags{margin-top:9px;font-size:.65rem;letter-spacing:.08em;color:#91a6bd}
        .qv37-grid{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px;margin:11px 0 17px}.qv37-card{border:1px solid rgba(101,230,210,.16);background:rgba(3,16,29,.77);border-radius:14px;padding:12px}.qv37-label{font-size:.53rem;letter-spacing:.12em;color:#7f94a9;font-weight:800}.qv37-value{font-size:.94rem;color:#f6f8ff;font-weight:880;margin:5px 0}.qv37-note{font-size:.64rem;line-height:1.38;color:#8fa2b8}.qv37-pass{color:#78edbd}.qv37-block{color:#ffaeae}.qv37-warn{color:#ffd28f}
        @media(max-width:1100px){.qv37-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:700px){.qv37-grid{grid-template-columns:1fr 1fr}}@media(max-width:470px){.qv37-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )

    authenticated = bool(state["prototype_pass"])
    display = (lambda value: value if authenticated else "NOT AUTHENTICATED")
    fixture_label = (
        f"N={state['n']} · K={state['k']}" if authenticated else "NOT AUTHENTICATED"
    )
    integrity_label = "AUTHENTICATED" if authenticated else "INVALID / ABSENT"
    st.markdown(
        f"""<div class="qv37-shell">
        <div class="qv37-k">V3.7 · REVERSIBLE INCREMENTAL EXPOSURE PROTOTYPE</div>
        <div class="qv37-title {'qv37-pass' if authenticated else 'qv37-block'}">{escape(state['prototype_status'])}</div>
        <div class="qv37-copy">Registered fixture {escape(fixture_label)} · ID {escape(display(state['fixture_id']))} · artifact {escape(integrity_label)} · SHA {escape(state['artifact_sha256'][:24])}<br>{escape(state['n40_status'])} · the full-width logical primitives have no elementary CNOT equivalent in this release.</div>
        <div class="qv37-tags">RESEARCH_ONLY · PROTOTYPE_ONLY · PROVIDER_FREE · HARDWARE_EXECUTABLE FALSE</div>
        </div>
        <div class="qv37-grid">
          <div class="qv37-card"><div class="qv37-label">EXACT-K STATES</div><div class="qv37-value">{escape(display(_fmt_int(state['exact_k_state_count'])))}</div><div class="qv37-note">registered combinatorial domain</div></div>
          <div class="qv37-card"><div class="qv37-label">FEASIBLE STATES</div><div class="qv37-value">{escape(display(_fmt_int(state['feasible_state_count'])))}</div><div class="qv37-note">fixture graph {'connected' if authenticated and state['connected'] else 'not authenticated'}</div></div>
          <div class="qv37-card"><div class="qv37-label">BASIS COLUMNS</div><div class="qv37-value">{escape(display(_fmt_int(state['basis_columns_checked'])))}</div><div class="qv37-note">six edges × 1,024 columns × three β</div></div>
          <div class="qv37-card"><div class="qv37-label">DIFFERENTIAL CASES</div><div class="qv37-value">{escape(display(_fmt_int(state['portfolio_edge_cases'])))}</div><div class="qv37-note">portfolio-edge cases · zero mismatches when authenticated</div></div>
          <div class="qv37-card"><div class="qv37-label">SCRATCH / ANCILLA</div><div class="qv37-value">{escape(display('0 / 0'))}</div><div class="qv37-note">allocated logical qubits</div></div>
          <div class="qv37-card"><div class="qv37-label">SELECTED-MODEL CNOT</div><div class="qv37-value qv37-warn">{escape(display(state['selected_model_cnot']))}</div><div class="qv37-note">elementary decomposition not implemented</div></div>
        </div>""",
        unsafe_allow_html=True,
    )

    if authenticated:
        st.success(
            "COHERENT TWO-LEVEL UPDATE · PASS — every registered edge operator "
            "matches the ideal portfolio-plus-cache action on every computational-basis column."
        )
        st.success(
            "SCRATCH CLEANUP · PASS — zero ancilla and zero scratch are allocated; "
            "each Gray path is reversed after the addressed MCRX operation."
        )
        st.success(
            "DIFFERENTIAL PREDICATE + CACHE · PASS — 36 portfolio-edge and 72 "
            "constraint-row cases match exact full recomputation."
        )
        st.success(
            "COMPLETE ORDERED LAYER · PASS — independent multi-beta action, adjoint "
            "round trip, full Gram identity and deterministic IR replay all pass."
        )
    else:
        st.error(
            "V3.7 artifact integrity, lineage or claim-boundary evidence is absent "
            "or invalid. No prototype PASS state may be used as release evidence."
        )

    st.markdown("**Proof-carrying admission matrix**")
    st.dataframe(pd.DataFrame(_proof_rows(state)), width="stretch", hide_index=True)

    if authenticated and state["coherent_rows"]:
        st.markdown("**Four sealed coherent portfolio/cache transitions**")
        st.dataframe(pd.DataFrame(state["coherent_rows"]), width="stretch", hide_index=True)
        st.caption(
            "Each row binds both complete register endpoints, the exact cache delta, "
            "pair IR hash, action check, round trip, off-target identity and cleanup state."
        )
        with st.expander("Six-edge logical IR summary", expanded=False):
            st.dataframe(pd.DataFrame(state["edge_rows"]), width="stretch", hide_index=True)
            st.caption(
                "Counts are exact in the declared full-width logical PATTERN_MCX / "
                "PATTERN_MCRX basis only. They are not native-gate or CNOT counts."
            )

    left, right = st.columns(2)
    with left:
        st.markdown("**Register contract**")
        if authenticated and state["register_rows"]:
            st.dataframe(pd.DataFrame(state["register_rows"]), width="stretch", hide_index=True)
            st.caption(
                f"Register width: {state['register_width']} · full domain: "
                f"{_fmt_int(state['full_domain_basis_states'])} basis states."
            )
        else:
            st.caption("Register contract not authenticated.")
    with right:
        st.markdown("**Logical resource boundary**")
        scan = _mapping(state["scan"])
        resource_rows = [
            {"Resource": "Coherent two-level pairs", "Value": _fmt_int(_int_or_none(scan.get("two_level_pair_count")))},
            {"Resource": "PATTERN_MCX", "Value": _fmt_int(_int_or_none(scan.get("pattern_mcx_count")))},
            {"Resource": "PATTERN_MCRX", "Value": _fmt_int(_int_or_none(scan.get("pattern_mcrx_count")))},
            {"Resource": "Logical gates / serial depth", "Value": _fmt_int(_int_or_none(scan.get("logical_gate_count")))},
            {"Resource": "Maximum control count", "Value": _fmt_int(_int_or_none(scan.get("maximum_control_count")))},
            {"Resource": "Selected-model CNOT", "Value": state["selected_model_cnot"]},
        ]
        if authenticated:
            st.dataframe(pd.DataFrame(resource_rows), width="stretch", hide_index=True)
            st.caption(state["ledger_boundary"])
        else:
            st.caption("Logical resource ledger not authenticated.")

    if authenticated:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Maximum action error", _fmt_scientific(state["maximum_action_error"]))
        m2.metric("Maximum round-trip error", _fmt_scientific(state["maximum_roundtrip_error"]))
        m3.metric("Maximum norm error", _fmt_scientific(state["maximum_norm_error"]))
        m4.metric("Complete-layer norm error", _fmt_scientific(state["complete_layer_maximum_norm_error"]))
        complete_layer_rows = [
            {
                "Complete-layer control": "Independent reference action · multi-beta",
                "Maximum error": _fmt_scientific(state["complete_layer_maximum_action_error"]),
                "State": "PASS",
            },
            {
                "Complete-layer control": "Adjoint round trip · every basis column",
                "Maximum error": _fmt_scientific(state["complete_layer_maximum_roundtrip_error"]),
                "State": "PASS",
            },
            {
                "Complete-layer control": "Full Gram matrix identity",
                "Maximum error": _fmt_scientific(state["complete_layer_maximum_gram_error"]),
                "State": "PASS",
            },
            {
                "Complete-layer control": "Norm preservation",
                "Maximum error": _fmt_scientific(state["complete_layer_maximum_norm_error"]),
                "State": "PASS",
            },
            {
                "Complete-layer control": "Deterministic logical IR replay",
                "Maximum error": "N/A",
                "State": "PASS",
            },
        ]
        st.markdown("**Complete ordered-layer operator controls**")
        st.dataframe(pd.DataFrame(complete_layer_rows), width="stretch", hide_index=True)
        st.caption(
            f"Basis columns: {_fmt_int(state['complete_layer_basis_columns_checked'])} · "
            f"Gram entries: {_fmt_int(state['complete_layer_gram_entries_checked'])} · "
            f"IR replay SHA-256: {state['logical_ir_replay_sha256'][:24]}"
        )
        with st.expander("36 differential portfolio-edge cases", expanded=False):
            st.dataframe(
                _differential_table(state["differential_rows"]),
                width="stretch",
                hide_index=True,
            )

    scale_rows = [
        {
            "Admission layer": "Registered N=4, K=2 fixture",
            "State": "PASS" if authenticated else "NOT AUTHENTICATED",
            "Evidence": "Exhaustive coherent action, differential cache/predicate and cleanup checks.",
        },
        {
            "Admission layer": "Frozen N=40 · seven constraints",
            "State": "BLOCKED · NOT BUILT",
            "Evidence": "No production-width reversible arithmetic or full successor-equivalence proof.",
        },
        {
            "Admission layer": "Elementary selected-model ledger",
            "State": "NOT EVALUATED",
            "Evidence": "Full-width pattern-controlled primitives are not decomposed to one-/two-qubit gates.",
        },
        {
            "Admission layer": "Internal 2.5M CNOT budget",
            "State": "NOT EVALUATED",
            "Evidence": "No comparable selected-model CNOT numerator exists for V3.7.",
        },
        {
            "Admission layer": "Named backend / routing",
            "State": "NOT RUN",
            "Evidence": "Provider-free release; backend lane remains closed.",
        },
        {
            "Admission layer": "Hardware execution",
            "State": "BLOCKED · ZERO JOBS",
            "Evidence": "Credentials, provider calls and QPU submission are outside this artifact.",
        },
    ]
    st.markdown("**Prototype-to-production critical path**")
    st.dataframe(pd.DataFrame(scale_rows), width="stretch", hide_index=True)
    st.error(
        "N=40 PRODUCTION COMPILER · BLOCKED — elementary decomposition, seven-constraint "
        "equivalence and the selected-model resource ledger have not been built."
    )
    st.info(
        "SELECTED-MODEL CNOT · NOT ESTIMATED — the exact logical-IR ledger is "
        "intentionally non-comparable with the frozen V3.6 2.5M research budget."
    )
    st.button(
        "Scale prototype to authenticated N=40 contract",
        disabled=True,
        key=f"{key_prefix}_v37_n40_scale_gate",
        help=(
            "Blocked until a production-width elementary compiler reproduces all seven "
            "frozen constraints and publishes an authenticated selected-model ledger."
        ),
    )

    if authenticated:
        artifact_payload = dict(state["artifact"])
        st.download_button(
            "Download sealed V3.7 reversible-prototype artifact",
            data=json.dumps(
                artifact_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"),
            file_name="SEALED_V3_7_REVERSIBLE_PROTOTYPE_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v37_artifact_download",
        )
    spec_payload = dict(_mapping(spec))
    if authenticated and spec_payload:
        st.download_button(
            "Download V3.7 reversible-prototype specification",
            data=json.dumps(
                spec_payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            ).encode("utf-8"),
            file_name="PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json",
            mime="application/json",
            key=f"{key_prefix}_v37_spec_download",
        )

    st.warning(
        "V3.7 CLAIM BOUNDARY · PROTOTYPE-ONLY REVERSIBILITY. The exhaustive result "
        "covers only the sealed synthetic N=4, K=2 fixture and its ten-qubit "
        "portfolio-plus-cache register. It does not establish an N=40 seven-constraint "
        "successor, an elementary or selected-model CNOT budget, named-backend viability, "
        "physical fidelity, optimization performance, QPU execution or quantum advantage."
    )
    st.markdown(
        "**HARDWARE EXECUTION · BLOCKED · ZERO JOBS** · provider calls 0 · "
        "qpu submission disabled · quantum advantage NOT CLAIMED"
    )
    return state


def apply_v37_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project the prototype status only onto its authenticated BANDS lane.

    The evidence panel is useful independently of the Phase-II selection, but
    its successor state must never contaminate BASE or PAIRWISE encodings.
    """

    if encoding is None:
        return None
    projected = dict(encoding)
    if str(regime).upper() != "BANDS" or state.get("prototype_pass") is not True:
        return projected
    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    projected.update(
        {
            "v37_reversible_prototype_artifact_sha": source.get("artifact_sha256"),
            "v37_prototype_decision": decisions.get("overall"),
            "v37_production_admission": "N40_REWRITE_ADMISSION_BLOCKED",
            "encoding_status": (
                "V3.7 SMALL-INSTANCE REVERSIBLE PROTOTYPE PASSED · "
                "N40 ADMISSION BLOCKED"
            ),
            "hardware_executable": False,
        }
    )
    return projected


__all__ = [
    "apply_v37_encoding_state",
    "normalize_v37_artifact",
    "render_v37_reversible_prototype_panel",
]
