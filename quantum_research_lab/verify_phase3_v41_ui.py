"""Positive-rerun Streamlit AppTest verifier for the V4.1 UI contract."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import pandas as pd
except ImportError:  # pragma: no cover - reported as an explicit verifier gate
    pd = None  # type: ignore[assignment]


EXPECTED_TABS = (
    "MISSION CONTROL",
    "REGIME / DENSITY",
    "QMC / RISK",
    "PRICING & CONVERGENCE",
    "TAIL RISK / EXPOSURE",
    "QAE RESOURCE INTELLIGENCE",
    "ADVANTAGE FRONTIER",
    "QUBO / ISING",
    "QUANTUM INFORMATION",
    "BENCHMARK PROTOCOL",
    "PHASE II / OOS",
    "PHASE III / QPU",
)
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)

REQUIRED_MARKERS = (
    "V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER",
    "V3.5 · NAMED-BACKEND TRANSPILATION CONTROL ROOM",
    "V3.6 · STRUCTURAL COST ATTRIBUTION & REWRITE GATE",
    "V3.7 · REVERSIBLE INCREMENTAL EXPOSURE PROTOTYPE",
    "V3.8 · ELEMENTARY DECOMPOSITION & N=40 RESOURCE ADMISSION",
    "V3.9 · SCALABLE N40 REVERSIBLE IR & SELECTED-MODEL ADMISSION",
    "V4.0 · GLOBAL FEASIBLE-GRAPH CONNECTIVITY & RESOURCE REDESIGN PREREGISTRATION",
    "V4.1 · AUGMENTED 1+2 EXCHANGE GRAPH & PROOF-CARRYING RESOURCE ADMISSION",
    "CONNECTED BY CERTIFIED SUBGRAPH · PASS",
    "58,725 / 58,725 INCIDENT TWO-SWAP CANDIDATES AUDITED",
    "RESOURCE ADMISSION · REJECTED",
    "FULL AUGMENTED EDGE COUNT · NOT ENUMERATED · NOT REQUIRED FOR THE CONNECTIVITY CERTIFICATE",
    "CACHE PREPARATION · REPORTED SEPARATELY · EXCLUDED FROM NUMERATOR",
    "R1_LINEAR_SLACK_ALL_ONE_SWAP · REJECTED",
    "R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES · REJECTED_SELECTED_MODEL_CNOT_BUDGET",
    "PRIMARY ENDPOINT · MAXIMUM R2 CNOT ACROSS ALL EIGHT FROZEN SEEDS",
    "POST-OBSERVATION CANDIDATE SWITCHING · PROHIBITED",
    "V4.1 CLAIM BOUNDARY · EXACT CONNECTIVITY AND PROVIDER-NEUTRAL RESOURCE EVIDENCE ONLY",
    "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION",
    "BACKEND TRANSPILATION · NOT RUN",
    "HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0",
    "QUANTUM ADVANTAGE · NOT CLAIMED",
)

BRIDGE_AUDIT_COLUMNS = (
    "Seed",
    "Isolated source",
    "Candidates audited",
    "Feasible two-swaps",
    "Triple replay",
    "Independent methods",
    "First feasible target",
    "First removed",
    "First added",
    "Classification ledger SHA",
    "Feasible-record SHA",
    "Audit SHA",
)
SELECTED_BRIDGE_COLUMNS = (
    "Seed",
    "Selection rank",
    "Source",
    "Target",
    "Source component",
    "Target component",
    "Removed",
    "Added",
    "Hamming distance",
    "Exact seven values",
    "Bridge SHA",
)
CONNECTIVITY_COLUMNS = (
    "Seed",
    "V4 feasible vertices",
    "V4 exact one-swap edges",
    "Components before",
    "Singletons",
    "Candidate bridges",
    "Selected bridges",
    "Certified-subgraph edges",
    "Components after",
    "Connected",
    "All incident candidates audited",
    "Certificate SHA",
)
RESOURCE_COLUMNS = (
    "Seed",
    "Ordered one-swap positions",
    "Live positions",
    "Certified identities",
    "R1 connected",
    "R1 CNOT",
    "R1 margin",
    "R1 decision",
    "R2 connected",
    "Bridge CNOT",
    "R2 CNOT",
    "R2 margin",
    "R2 decision",
    "Cache prep CNOT (excluded)",
    "Cache controlled adds",
    "Cache qubits",
    "R1 logical qubits + clean ancillas",
    "R2 logical qubits + clean ancillas",
    "Seed ledger SHA",
)
COMPRESSION_COLUMNS = (
    "Seed",
    "Factor",
    "Complete domain",
    "Shift",
    "Scale",
    "Original lower",
    "Original upper",
    "Compressed lower",
    "Compressed upper",
    "Exact min threshold distance",
    "Exact error bound",
    "Predicate parity",
    "Certificate SHA",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _element_text(element: Any) -> str:
    if getattr(element, "type", None) == "download_button":
        return str(getattr(element.proto, "label", ""))
    try:
        value = getattr(element, "value", None)
    except (AttributeError, ValueError):
        value = None
    if value is not None:
        if hasattr(value, "to_string"):
            try:
                return value.to_string(index=False)
            except TypeError:
                return value.to_string()
        return str(value)
    return str(getattr(element, "label", ""))


def _as_frame(value: Any) -> pd.DataFrame | None:
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if hasattr(value, "to_pandas"):
        try:
            converted = value.to_pandas()
            return converted if isinstance(converted, pd.DataFrame) else None
        except Exception:
            return None
    return None


def _snapshot(app: Any) -> tuple[str, tuple[str, ...], list[pd.DataFrame]]:
    names = (
        "title",
        "header",
        "subheader",
        "markdown",
        "caption",
        "success",
        "warning",
        "error",
        "info",
        "metric",
        "dataframe",
        "button",
        "download_button",
    )
    parts: list[str] = []
    for name in names:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_element_text(element) for element in elements)
    frames = [
        frame
        for element in app.dataframe
        if (frame := _as_frame(getattr(element, "value", None))) is not None
    ]
    return "\n".join(parts), tuple(element.label for element in app.tabs), frames


def _expected_bridge_audits(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in _rows(_mapping(artifact.get("bridge_audits")).get("rows")):
        records = _rows(row.get("feasible_records"))
        first = _mapping(records[0] if records else {})
        rows.append({
            "Seed": row.get("seed"),
            "Isolated source": row.get("source_mask_hex"),
            "Candidates audited": row.get("candidates_audited"),
            "Feasible two-swaps": row.get("feasible_neighbor_count"),
            "Triple replay": row.get("triple_replay_match"),
            "Independent methods": " · ".join(str(value) for value in row.get("independent_methods") or []),
            "First feasible target": first.get("target_mask_hex"),
            "First removed": ", ".join(str(value) for value in first.get("removed") or []),
            "First added": ", ".join(str(value) for value in first.get("added") or []),
            "Classification ledger SHA": row.get("classification_ledger_sha256"),
            "Feasible-record SHA": row.get("feasible_record_sha256"),
            "Audit SHA": row.get("isolate_audit_sha256"),
        })
    return pd.DataFrame(rows, columns=BRIDGE_AUDIT_COLUMNS)


def _expected_selected_bridges(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    connectivity = _mapping(artifact.get("connectivity_evidence"))
    for seed_row in _rows(connectivity.get("seed_rows")):
        for bridge in _rows(seed_row.get("selected_bridges")):
            rows.append({
                "Seed": seed_row.get("seed"),
                "Selection rank": bridge.get("selection_rank"),
                "Source": bridge.get("source_mask_hex"),
                "Target": bridge.get("target_mask_hex"),
                "Source component": bridge.get("source_component_representative"),
                "Target component": bridge.get("target_component_representative"),
                "Removed": ", ".join(str(value) for value in bridge.get("removed") or []),
                "Added": ", ".join(str(value) for value in bridge.get("added") or []),
                "Hamming distance": bridge.get("hamming_distance"),
                "Exact seven values": ", ".join(str(value) for value in bridge.get("exact_values") or []),
                "Bridge SHA": bridge.get("bridge_sha256"),
            })
    return pd.DataFrame(rows, columns=SELECTED_BRIDGE_COLUMNS)


def _expected_connectivity(artifact: Mapping[str, Any]) -> pd.DataFrame:
    connectivity = _mapping(artifact.get("connectivity_evidence"))
    rows = [
        {
            "Seed": row.get("seed"),
            "V4 feasible vertices": row.get("authenticated_v40_feasible_vertices"),
            "V4 exact one-swap edges": row.get("authenticated_v40_exact_one_swap_edges"),
            "Components before": row.get("authenticated_v40_component_count"),
            "Singletons": row.get("singleton_component_count"),
            "Candidate bridges": row.get("candidate_bridge_count"),
            "Selected bridges": row.get("selected_bridge_count"),
            "Certified-subgraph edges": row.get("selected_spanning_subgraph_edges"),
            "Components after": row.get("final_component_count"),
            "Connected": row.get("connected_by_certified_subgraph"),
            "All incident candidates audited": row.get("all_incident_candidates_audited"),
            "Certificate SHA": row.get("seed_connectivity_sha256"),
        }
        for row in _rows(connectivity.get("seed_rows"))
    ]
    return pd.DataFrame(rows, columns=CONNECTIVITY_COLUMNS)


def _expected_resources(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    resource = _mapping(artifact.get("resource_evidence"))
    for row in _rows(resource.get("seed_rows")):
        r1 = _mapping(row.get("r1"))
        r2 = _mapping(row.get("r2"))
        r1_resources = _mapping(r1.get("selected_model_layer_resources"))
        r2_resources = _mapping(r2.get("selected_model_layer_resources"))
        bridge_resources = _mapping(r2.get("bridge_resources"))
        one_swap = _mapping(row.get("one_swap_layer"))
        cache = _mapping(row.get("cache_preparation_outside_numerator"))
        cache_resources = _mapping(cache.get("resources"))
        cache_macros = _mapping(cache.get("macros"))
        rows.append({
            "Seed": row.get("seed"),
            "Ordered one-swap positions": one_swap.get("ordered_positions"),
            "Live positions": one_swap.get("live_positions"),
            "Certified identities": one_swap.get("certified_identity_positions"),
            "R1 connected": r1.get("connectivity_pass"),
            "R1 CNOT": r1_resources.get("selected_model_cnot"),
            "R1 margin": r1.get("budget_margin_cnot"),
            "R1 decision": r1.get("decision"),
            "R2 connected": r2.get("connectivity_pass"),
            "Bridge CNOT": bridge_resources.get("selected_model_cnot"),
            "R2 CNOT": r2_resources.get("selected_model_cnot"),
            "R2 margin": r2.get("budget_margin_cnot"),
            "R2 decision": r2.get("decision"),
            "Cache prep CNOT (excluded)": cache_resources.get("selected_model_cnot"),
            "Cache controlled adds": cache_macros.get("controlled_add_macros"),
            "Cache qubits": one_swap.get("cache_qubits"),
            "R1 logical qubits + clean ancillas": r1.get("logical_qubits_with_clean_decomposition_ancillas"),
            "R2 logical qubits + clean ancillas": r2.get("logical_qubits_with_clean_decomposition_ancillas"),
            "Seed ledger SHA": row.get("seed_resource_sha256"),
        })
    return pd.DataFrame(rows, columns=RESOURCE_COLUMNS)


def _expected_compressions(artifact: Mapping[str, Any]) -> pd.DataFrame:
    exact_decimal = lambda value: str(value) if type(value) is int else value
    rows: list[dict[str, Any]] = []
    compression = _mapping(artifact.get("compression_evidence"))
    for seed_row in _rows(compression.get("seed_rows")):
        for factor in _rows(seed_row.get("factor_rows")):
            rows.append({
                "Seed": seed_row.get("seed"),
                "Factor": factor.get("factor"),
                "Complete domain": factor.get("classification_domain_count"),
                "Shift": factor.get("selected_shift"),
                "Scale": factor.get("scale"),
                "Original lower": exact_decimal(factor.get("original_lower_int")),
                "Original upper": exact_decimal(factor.get("original_upper_int")),
                "Compressed lower": exact_decimal(factor.get("compressed_lower_int")),
                "Compressed upper": exact_decimal(factor.get("compressed_upper_int")),
                "Exact min threshold distance": exact_decimal(factor.get("exact_minimum_threshold_distance")),
                "Exact error bound": exact_decimal(factor.get("exact_error_bound")),
                "Predicate parity": factor.get("identity_or_strict_margin_parity_proof"),
                "Certificate SHA": factor.get("compression_certificate_sha256"),
            })
    return pd.DataFrame(rows, columns=COMPRESSION_COLUMNS)


def _frame_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left.reset_index(drop=True),
            right.reset_index(drop=True),
            check_dtype=False,
            check_like=False,
        )
    except (AssertionError, TypeError, ValueError):
        return False
    return True


def _contains_exact_frame(frames: Sequence[pd.DataFrame], expected: pd.DataFrame) -> bool:
    return any(
        tuple(str(column) for column in frame.columns)
        == tuple(str(column) for column in expected.columns)
        and _frame_equal(frame, expected)
        for frame in frames
    )


def _rehash(payload: dict[str, Any], canonical_json_sha256: Any) -> dict[str, Any]:
    payload["artifact_sha256"] = canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "artifact_sha256"}
    )
    return payload


def verify_streamlit_surface_v41(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    if pd is None:  # pragma: no cover
        return {
            "checks": {"pandas_available": False},
            "errors": ["pandas is required for V4.1 dataframe acceptance."],
            "failed_checks": ["pandas_available"],
            "valid": False,
        }
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as exc:  # pragma: no cover
        return {
            "checks": {"streamlit_testing_available": False},
            "errors": [str(exc)],
            "failed_checks": ["streamlit_testing_available"],
            "valid": False,
        }

    contract_errors: list[str] = []
    try:
        from .phase3_v41_certified_bridge_compiler import (
            canonical_json_sha256,
            load_v41_spec,
        )
        from .phase3_v41_ui import (
            EXPECTED_V41_SPEC_SHA256,
            apply_v41_encoding_state,
            load_v41_ui_artifact,
            normalize_v41_artifact,
            v41_release_identity_pins_resolved,
        )

        sealed, integrity = load_v41_ui_artifact()
        spec = load_v41_spec()
        spec_integrity = spec.get("v41_spec_sha256") == EXPECTED_V41_SPEC_SHA256
        startup_validation = {
            "valid": integrity.get("valid") is True,
            "checks": dict(_mapping(integrity.get("scientific_checks"))),
        }
        parent_integrity = bool(_mapping(_mapping(sealed.get("parent")).get("authentication")).get("valid"))
        healthy = normalize_v41_artifact(
            sealed,
            artifact_integrity=integrity.get("valid") is True,
            spec_integrity=spec_integrity,
            parent_integrity=parent_integrity,
        )
        invalid_states = {
            "missing": normalize_v41_artifact(None, artifact_integrity=True, spec_integrity=True, parent_integrity=True),
            "implicit_integrity": normalize_v41_artifact(sealed, artifact_integrity=None, spec_integrity=True, parent_integrity=True),
            "bad_spec": normalize_v41_artifact(sealed, artifact_integrity=True, spec_integrity=False, parent_integrity=True),
            "bad_parent": normalize_v41_artifact(sealed, artifact_integrity=True, spec_integrity=True, parent_integrity=False),
        }

        bridge_tamper = copy.deepcopy(sealed)
        bridge_tamper["bridge_audits"]["rows"][0]["feasible_neighbor_count"] += 1
        resource_tamper = copy.deepcopy(sealed)
        resource_tamper["resource_evidence"]["aggregate"]["r2_maximum_selected_model_cnot"] -= 1
        compression_tamper = copy.deepcopy(sealed)
        compression_tamper["compression_evidence"]["all_factor_predicates_exact"] = False
        boundary_tamper = copy.deepcopy(sealed)
        boundary_tamper["claim_boundary"]["hardware_executable"] = True
        parent_tamper = copy.deepcopy(sealed)
        parent_tamper["parent"]["authentication"]["valid"] = False
        for name, tamper in (
            ("bridge", bridge_tamper),
            ("resource", resource_tamper),
            ("compression", compression_tamper),
            ("boundary", boundary_tamper),
            ("parent_chain", parent_tamper),
        ):
            _rehash(tamper, canonical_json_sha256)
            invalid_states[f"tamper_{name}"] = normalize_v41_artifact(
                tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            )

        base_encoding = {"encoding_status": "BASE ORIGINAL", "hardware_executable": True}
        projected_base = apply_v41_encoding_state(base_encoding, regime="BASE", state=healthy, artifact=sealed)
        projected_bands = apply_v41_encoding_state(base_encoding, regime="BANDS", state=healthy, artifact=sealed)
        expected_frames = {
            "bridge_audits": _expected_bridge_audits(sealed),
            "selected_bridges": _expected_selected_bridges(sealed),
            "connectivity": _expected_connectivity(sealed),
            "resources": _expected_resources(sealed),
            "compressions": _expected_compressions(sealed),
        }
        pins_resolved = v41_release_identity_pins_resolved()
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = spec = healthy = {}
        integrity = startup_validation = {"valid": False}
        spec_integrity = parent_integrity = pins_resolved = False
        invalid_states = {}
        base_encoding = projected_base = projected_bands = {}
        expected_frames = {
            "bridge_audits": pd.DataFrame(columns=BRIDGE_AUDIT_COLUMNS),
            "selected_bridges": pd.DataFrame(columns=SELECTED_BRIDGE_COLUMNS),
            "connectivity": pd.DataFrame(columns=CONNECTIVITY_COLUMNS),
            "resources": pd.DataFrame(columns=RESOURCE_COLUMNS),
            "compressions": pd.DataFrame(columns=COMPRESSION_COLUMNS),
        }

    target = Path(app_path).resolve()
    app = AppTest.from_file(str(target), default_timeout=timeout_seconds)
    app.query_params["workspace"] = "quantum-research"
    app.run(timeout=timeout_seconds)
    first_exceptions = [str(element.value) for element in app.exception]
    first_text, first_tabs, first_frames = _snapshot(app)
    app.run(timeout=timeout_seconds)
    final_exceptions = [str(element.value) for element in app.exception]
    final_text, final_tabs, final_frames = _snapshot(app)

    def buttons(label: str) -> list[Any]:
        return [button for button in app.button if str(getattr(button, "label", "")) == label]

    def downloads(label: str) -> list[Any]:
        return [
            element
            for element in app.get("download_button")
            if str(getattr(element.proto, "label", "")) == label
        ]

    def widgets(collection: str, label: str) -> list[Any]:
        return [
            element
            for element in getattr(app, collection, ())
            if str(getattr(element, "label", "")) == label
        ]

    governance_counts = {
        "Recompute sealed V4.1 evidence": 1,
        "Override deterministic bridge selection": 1,
        "Relabel incomplete bridge coverage": 1,
        "Claim the full augmented edge count": 1,
        "Include cache preparation selectively": 1,
        "Switch R1/R2 after observation": 1,
        "Override 2,500,000 CNOT gate": 2,  # V4.0 and V4.1 controls are both preserved
        "Open named-backend or QPU lane": 1,
        "Discover accessible IBM QPUs": 1,
        "Seal Phase-III equal-objective hardware protocol": 1,
    }
    credential_widgets = (
        ("text_input", "IBM Quantum API key · session only"),
        ("text_input", "IBM instance / CRN · optional"),
        ("checkbox", "Allow previously saved IBM account credentials"),
    )
    hook_values = (
        'data-qv41-surface="certified-bridge-compiler"',
        'data-qv41-release="4.1"',
        'data-qv41-auth="pass"',
        'data-qv41-connectivity="CONNECTED_BY_CERTIFIED_SUBGRAPH"',
        'data-qv41-bridge-count="3"',
        'data-qv41-resource="REJECTED"',
        'data-qv41-cache-prep="EXCLUDED_FROM_NUMERATOR"',
        'data-qv41-production="REJECTED"',
        'data-qv41-hardware="false"',
        'data-qv41-jobs="0"',
    )
    aggregate_connectivity = _mapping(_mapping(sealed.get("connectivity_evidence")).get("aggregate"))
    aggregate_resources = _mapping(_mapping(sealed.get("resource_evidence")).get("aggregate"))
    expected_row_counts = {
        "bridge_audits": 3,
        "selected_bridges": 3,
        "connectivity": 8,
        "resources": 8,
        "compressions": 24,
    }

    checks: dict[str, bool] = {
        "release_identity_pins_resolved": pins_resolved,
        "sealed_artifact_raw_semantic_and_boundary_identity": integrity.get("valid") is True,
        "registered_spec_identity": spec_integrity is True,
        "authenticated_v40_parent_lineage": parent_integrity is True,
        "fast_byte_pinned_startup_validator_accepts_sealed_artifact": startup_validation.get("valid") is True,
        "normalizer_accepts_only_explicit_authenticated_inputs": healthy.get("authenticated") is True,
        "all_missing_and_rehashed_tamper_states_fail_closed": bool(invalid_states)
        and all(state.get("authenticated") is False for state in invalid_states.values()),
        "invalid_states_mask_every_v41_ledger": bool(invalid_states)
        and all(
            not state.get("artifact")
            and not state.get("audit_rows")
            and not state.get("connectivity_rows")
            and not state.get("compression_rows")
            and not state.get("resource_seed_rows")
            and not state.get("connectivity_aggregate")
            and not state.get("resource_aggregate")
            for state in invalid_states.values()
        ),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_connectivity_pass_resource_rejected_hardware_false": bool(
            projected_bands.get("v41_augmented_connectivity_decision")
            == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
            and projected_bands.get("v41_resource_architecture_decision")
            == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            and projected_bands.get("v41_augmented_connectivity") == "CONNECTED_BY_CERTIFIED_SUBGRAPH"
            and projected_bands.get("v41_selected_bridge_count") == 3
            and projected_bands.get("v41_r1_maximum_selected_model_cnot") == 15_256_056
            and projected_bands.get("v41_r2_maximum_selected_model_cnot") == 15_663_936
            and projected_bands.get("hardware_executable") is False
            and projected_bands.get("qpu_jobs_submitted") == 0
            and projected_bands.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "artifact_connectivity_pass_exact": bool(
            aggregate_connectivity.get("all_eight_seeds_connected_by_certified_subgraph") is True
            and aggregate_connectivity.get("audited_incident_two_swap_candidates") == 58_725
            and aggregate_connectivity.get("feasible_incident_two_swap_candidates") == 787
            and aggregate_connectivity.get("selected_bridge_count") == 3
            and aggregate_connectivity.get("final_components_across_seeds") == 8
        ),
        "artifact_r1_r2_resource_rejection_exact": bool(
            aggregate_resources.get("r1_all_seeds_pass") is False
            and aggregate_resources.get("r2_all_seeds_pass") is False
            and aggregate_resources.get("r1_maximum_selected_model_cnot") == 15_256_056
            and aggregate_resources.get("r2_maximum_selected_model_cnot") == 15_663_936
            and aggregate_resources.get("budget_cnot") == 2_500_000
            and aggregate_resources.get("r2_minimum_budget_margin_cnot") == -13_163_936
            and aggregate_resources.get("cache_preparation_excluded_from_numerator") is True
        ),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": (
            final_tabs[:3] + final_tabs[7:]
            == (
                "MISSION CONTROL",
                "REGIME / DENSITY",
                "QMC / RISK",
                "QUBO / ISING",
                "QUANTUM INFORMATION",
                "BENCHMARK PROTOCOL",
                "PHASE II / OOS",
                "PHASE III / QPU",
            )
            and final_tabs[3:7] == EXPECTED_TABS[3:7]
        ),
        "historical_v34_through_v40_and_v41_markers_present_initially": all(
            marker in first_text for marker in REQUIRED_MARKERS
        ),
        "historical_v34_through_v40_and_v41_markers_present_after_rerun": all(
            marker in final_text for marker in REQUIRED_MARKERS
        ),
        "v41_panel_and_hooks_present_exactly_once": all(
            first_text.count(hook) == 1 and final_text.count(hook) == 1 for hook in hook_values
        ),
        "all_five_exact_ledgers_present_initially": all(
            _contains_exact_frame(first_frames, frame) for frame in expected_frames.values()
        ),
        "all_five_exact_ledgers_present_after_rerun": all(
            _contains_exact_frame(final_frames, frame) for frame in expected_frames.values()
        ),
        "exact_ledger_row_counts_3_3_8_8_24": all(
            len(expected_frames[name]) == count for name, count in expected_row_counts.items()
        ),
        "connectivity_and_resource_seed_order_exact": bool(
            tuple(expected_frames["connectivity"]["Seed"].tolist()) == EXPECTED_SEEDS
            and tuple(expected_frames["resources"]["Seed"].tolist()) == EXPECTED_SEEDS
        ),
        "all_governance_provider_and_seal_controls_disabled": all(
            len(items := buttons(label)) == expected_count
            and all(getattr(item, "disabled", None) is True for item in items)
            for label, expected_count in governance_counts.items()
        ),
        "credential_controls_present_once_and_disabled": all(
            len(items := widgets(collection, label)) == 1
            and getattr(items[0], "disabled", None) is True
            for collection, label in credential_widgets
        ),
        "five_v41_downloads_present_exactly_once": all(
            len(downloads(label)) == 1
            for label in (
                "Download sealed V4.1 certified-bridge compiler artifact",
                "Download V4.1 frozen compiler specification",
                "Download V4.1 bridge-audit ledger CSV",
                "Download V4.1 selected-bridge ledger CSV",
                "Download V4.1 resource ledger CSV",
            )
        ),
        "exact_connectivity_and_resource_totals_visible": all(
            marker in final_text
            for marker in (
                "58,725",
                "787",
                "337,710,606",
                "15,256,056",
                "15,663,936",
                "2,500,000",
                "-13,163,936",
            )
        ),
        "provider_transpile_and_seal_spies_zero_both_runs": all(
            marker in first_text and marker in final_text
            for marker in (
                "PROVIDER SPY CALLS · 0",
                "TRANSPILE SPY CALLS · 0",
                "SEAL SPY CALLS · 0",
            )
        ),
        "stale_provider_state_cleared_both_runs": (
            "STALE PROVIDER STATE · CLEARED" in first_text
            and "STALE PROVIDER STATE · CLEARED" in final_text
        ),
        "provider_transpile_hardware_and_advantage_boundaries_visible": all(
            marker in final_text
            for marker in (
                "PROVIDER CALLS · 0 · CREDENTIALS READ · FALSE · SDK IMPORTED · FALSE",
                "BACKEND TRANSPILATION · NOT RUN",
                "HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0",
                "QUANTUM ADVANTAGE · NOT CLAIMED",
            )
        ),
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "contract_errors": contract_errors,
        "dataframe_schemas": [
            {"columns": [str(column) for column in frame.columns], "rows": len(frame)}
            for frame in final_frames
        ],
        "expected_ledger_rows": expected_row_counts,
        "failed_checks": failed,
        "final_exception_messages": final_exceptions,
        "first_exception_messages": first_exceptions,
        "missing_required_markers_final": [
            marker for marker in REQUIRED_MARKERS if marker not in final_text
        ],
        "missing_required_markers_initial": [
            marker for marker in REQUIRED_MARKERS if marker not in first_text
        ],
        "normalizer_invalid_cases": sorted(invalid_states),
        "tab_count": len(final_tabs),
        "tabs": list(final_tabs),
        "valid": not failed and not contract_errors,
        "verifier": "QUANTUM LAB V4.1 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V4.1 UI.")
    parser.add_argument("app", nargs="?", type=Path, default=Path("app_v41_offline_harness.py"))
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v41(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BRIDGE_AUDIT_COLUMNS",
    "COMPRESSION_COLUMNS",
    "CONNECTIVITY_COLUMNS",
    "EXPECTED_SEEDS",
    "EXPECTED_TABS",
    "REQUIRED_MARKERS",
    "RESOURCE_COLUMNS",
    "SELECTED_BRIDGE_COLUMNS",
    "verify_streamlit_surface_v41",
]
