"""Positive-rerun Streamlit AppTest verifier for the V4.0 UI contract."""

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
    "GRAPH DEFINITION · FROZEN BEFORE CONNECTIVITY EVALUATION",
    "V3.9 ORDERED INDEX-PAIR COVERAGE IS NOT GLOBAL STATE-GRAPH CONNECTIVITY",
    "N=40 · K=10 · BANDS · 7 EXACT CONSTRAINTS · 8 FROZEN SEEDS",
    "EIGHT-SEED ALL-EVIDENCE RULE",
    "DISCONNECTED COUNTEREXAMPLE · CERTIFIED",
    "EXHAUSTIVE COVERAGE · PASS",
    "RESOURCE REDESIGN · PREREGISTERED · NOT EVALUATED",
    "V3.9 SELECTED-MODEL REJECTION · PRESERVED",
    "PRIMARY ENDPOINT · MAXIMUM CNOT ACROSS EIGHT SEEDS",
    "POST-OBSERVATION CANDIDATE SWITCHING · PROHIBITED",
    "NO EXPECTED OR PROJECTED RESOURCE CLAIM",
    "V4.0 CLAIM BOUNDARY · CONNECTIVITY EVIDENCE AND SUCCESSOR PREREGISTRATION ONLY",
    "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE",
    "BACKEND TRANSPILATION · NOT RUN",
    "HARDWARE EXECUTION · BLOCKED · ZERO JOBS",
    "QUANTUM ADVANTAGE · NOT CLAIMED",
)

CONNECTIVITY_LEDGER_COLUMNS = (
    "Seed",
    "Instance",
    "Method",
    "Certificate kind",
    "Feasible vertices",
    "State-graph edges",
    "Expected 9-core incidences",
    "Observed 9-core incidences",
    "Distinct 9-cores",
    "Union attempts",
    "Successful unions",
    "Components",
    "Largest component",
    "Smallest component",
    "Coverage complete",
    "Enumeration SHA",
    "Core-index SHA",
    "Union-forest SHA",
    "Independent replay",
    "Decision",
)

COUNTEREXAMPLE_LEDGER_COLUMNS = (
    "Seed",
    "Mask",
    "Selected indices",
    "Vertex feasible",
    "Neighbors audited",
    "Feasible neighbors",
    "All rejected",
    "First-failure ledger",
    "Neighbor ledger SHA",
    "Counterexample SHA",
)

REDESIGN_LEDGER_COLUMNS = (
    "Architecture",
    "Candidate",
    "Move family",
    "Connectivity gate",
    "Bridge rule",
    "CNOT",
    "Budget margin",
    "Status",
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


def _expected_connectivity_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    evidence = _mapping(artifact.get("connectivity_evidence"))
    rows: list[dict[str, Any]] = []
    for row in _rows(evidence.get("seed_rows")):
        rows.append(
            {
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
                "Independent replay": _mapping(row.get("replay")).get(
                    "all_stable_fields_match"
                ),
                "Decision": row.get("decision"),
            }
        )
    return pd.DataFrame(rows, columns=CONNECTIVITY_LEDGER_COLUMNS)


def _expected_counterexample_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    evidence = _mapping(artifact.get("connectivity_evidence"))
    rows: list[dict[str, Any]] = []
    for seed in _rows(evidence.get("seed_rows")):
        for item in _rows(seed.get("isolated_counterexamples")):
            rows.append(
                {
                    "Seed": seed.get("seed"),
                    "Mask": item.get("mask_hex"),
                    "Selected indices": ", ".join(
                        str(value) for value in item.get("selected_indices") or []
                    ),
                    "Vertex feasible": item.get("vertex_exactly_feasible"),
                    "Neighbors audited": item.get("neighbors_audited"),
                    "Feasible neighbors": item.get("feasible_neighbor_count"),
                    "All rejected": item.get("all_neighbors_rejected"),
                    "First-failure ledger": ", ".join(
                        f"{key}:{value}"
                        for key, value in _mapping(item.get("first_failure_counts")).items()
                    ),
                    "Neighbor ledger SHA": item.get("neighbor_ledger_sha256"),
                    "Counterexample SHA": item.get("counterexample_sha256"),
                }
            )
    return pd.DataFrame(rows, columns=COUNTEREXAMPLE_LEDGER_COLUMNS)


def _expected_redesign_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    redesign = _mapping(artifact.get("resource_redesign"))
    result_fields = _mapping(redesign.get("result_fields"))
    rows = [
        {
            "Architecture": redesign.get("architecture_id"),
            "Candidate": candidate.get("candidate_id"),
            "Move family": candidate.get("move_family"),
            "Connectivity gate": candidate.get("required_connectivity"),
            "Bridge rule": candidate.get("bridge_rule", "N/A"),
            "CNOT": result_fields.get("cnot"),
            "Budget margin": result_fields.get("budget_margin"),
            "Status": redesign.get("status"),
        }
        for candidate in _rows(redesign.get("candidate_set"))
    ]
    return pd.DataFrame(rows, columns=REDESIGN_LEDGER_COLUMNS)


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


def verify_streamlit_surface_v40(
    app_path: str | Path,
    *,
    timeout_seconds: float = 240.0,
) -> dict[str, Any]:
    if pd is None:  # pragma: no cover - depends on the invoking runtime
        return {
            "checks": {"pandas_available": False},
            "errors": ["pandas is required for V4.0 dataframe acceptance."],
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
        from .phase3_v40_global_connectivity import (
            canonical_json_sha256,
            load_v40_spec,
            validate_v40_artifact,
        )
        from .phase3_v40_ui import (
            apply_v40_encoding_state,
            load_v40_ui_artifact,
            normalize_v40_artifact,
        )

        sealed, integrity = load_v40_ui_artifact()
        spec = load_v40_spec()
        scientific_validation = validate_v40_artifact(sealed)
        healthy = normalize_v40_artifact(
            sealed,
            artifact_integrity=integrity.get("valid") is True,
            spec_integrity=True,
            parent_integrity=True,
        )
        missing = normalize_v40_artifact(
            None,
            artifact_integrity=True,
            spec_integrity=True,
            parent_integrity=True,
        )
        implicit = normalize_v40_artifact(
            sealed,
            artifact_integrity=None,
            spec_integrity=True,
            parent_integrity=True,
        )
        bad_spec = normalize_v40_artifact(
            sealed,
            artifact_integrity=True,
            spec_integrity=False,
            parent_integrity=True,
        )
        bad_parent = normalize_v40_artifact(
            sealed,
            artifact_integrity=True,
            spec_integrity=True,
            parent_integrity=False,
        )

        nested_tamper = copy.deepcopy(sealed)
        nested_tamper["connectivity_evidence"]["seed_rows"][0]["component_count"] += 1
        nested_tamper = _rehash(nested_tamper, canonical_json_sha256)

        seed_order_tamper = copy.deepcopy(sealed)
        seed_order_tamper["connectivity_evidence"]["seed_rows"].reverse()
        seed_order_tamper = _rehash(seed_order_tamper, canonical_json_sha256)

        duplicate_seed_tamper = copy.deepcopy(sealed)
        duplicate_seed_tamper["connectivity_evidence"]["seed_rows"][-1] = copy.deepcopy(
            duplicate_seed_tamper["connectivity_evidence"]["seed_rows"][0]
        )
        duplicate_seed_tamper = _rehash(duplicate_seed_tamper, canonical_json_sha256)

        redesign_result_tamper = copy.deepcopy(sealed)
        redesign_result_tamper["resource_redesign"]["result_fields"]["cnot"] = 1
        redesign_result_tamper = _rehash(redesign_result_tamper, canonical_json_sha256)

        provider_tamper = copy.deepcopy(sealed)
        provider_tamper["claim_boundary"]["provider_calls"] = 1
        provider_tamper = _rehash(provider_tamper, canonical_json_sha256)

        parent_tamper = copy.deepcopy(sealed)
        parent_tamper["parent"]["authentication"]["valid"] = False
        parent_tamper = _rehash(parent_tamper, canonical_json_sha256)

        tampered_states = {
            "nested_component": normalize_v40_artifact(
                nested_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
            "seed_order": normalize_v40_artifact(
                seed_order_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
            "duplicate_seed": normalize_v40_artifact(
                duplicate_seed_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
            "premature_redesign_result": normalize_v40_artifact(
                redesign_result_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
            "provider_boundary": normalize_v40_artifact(
                provider_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
            "parent_chain": normalize_v40_artifact(
                parent_tamper,
                artifact_integrity=True,
                spec_integrity=True,
                parent_integrity=True,
            ),
        }
        invalid_states = {
            "missing": missing,
            "implicit_integrity": implicit,
            "bad_spec": bad_spec,
            "bad_parent": bad_parent,
            **tampered_states,
        }

        base_encoding = {
            "encoding_status": "BASE ORIGINAL",
            "hardware_executable": True,
        }
        projected_base = apply_v40_encoding_state(
            base_encoding,
            regime="BASE",
            state=healthy,
            artifact=sealed,
        )
        projected_bands = apply_v40_encoding_state(
            base_encoding,
            regime="BANDS",
            state=healthy,
            artifact=sealed,
        )
        expected_connectivity = _expected_connectivity_ledger(sealed)
        expected_counterexamples = _expected_counterexample_ledger(sealed)
        expected_redesign = _expected_redesign_ledger(sealed)
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = spec = healthy = {}
        integrity = scientific_validation = {"valid": False}
        invalid_states = {}
        base_encoding = projected_base = projected_bands = {}
        expected_connectivity = pd.DataFrame(columns=CONNECTIVITY_LEDGER_COLUMNS)
        expected_counterexamples = pd.DataFrame(columns=COUNTEREXAMPLE_LEDGER_COLUMNS)
        expected_redesign = pd.DataFrame(columns=REDESIGN_LEDGER_COLUMNS)

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
        return [
            button
            for button in app.button
            if str(getattr(button, "label", "")) == label
        ]

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

    sensitive_labels = (
        "Recompute V4.0 global connectivity",
        "Override frozen graph definition",
        "Relabel inconclusive connectivity evidence",
        "Delete disconnected-component witness",
        "Override V3.9 resource rejection",
        "Switch resource-redesign candidate after observation",
        "Override 2,500,000 CNOT gate",
        "Open named-backend audit lane",
        "Discover accessible IBM QPUs",
        "Seal Phase-III equal-objective hardware protocol",
    )
    sensitive = {label: buttons(label) for label in sensitive_labels}
    credential_widgets = (
        ("text_input", "IBM Quantum API key · session only"),
        ("text_input", "IBM instance / CRN · optional"),
        ("checkbox", "Allow previously saved IBM account credentials"),
    )
    hook_values = (
        'data-qv40-surface="connectivity-redesign-control-room"',
        'data-qv40-release="4.0"',
        'data-qv40-auth="pass"',
        'data-qv40-role="overall-decision"',
        'data-qv40-connectivity="DISCONNECTED"',
        'data-qv40-certificate-kind="DISCONNECTED_COUNTEREXAMPLE"',
        'data-qv40-coverage-complete="true"',
        'data-qv40-resource="PREREGISTERED_NOT_EVALUATED"',
        'data-qv40-v39-rejection="preserved"',
        'data-qv40-production="REJECTED"',
        'data-qv40-provider-calls="0"',
        'data-qv40-hardware="false"',
    )

    expected_seed_order = tuple(expected_connectivity.get("Seed", pd.Series(dtype=int)).tolist())
    checks: dict[str, bool] = {
        "sealed_artifact_raw_semantic_and_boundary_identity": bool(
            integrity.get("valid") is True
        ),
        "full_scientific_validator_accepts_sealed_artifact": bool(
            scientific_validation.get("valid") is True
        ),
        "normalizer_accepts_only_explicit_authenticated_inputs": bool(
            healthy.get("authenticated") is True
        ),
        "missing_implicit_spec_and_parent_states_fail_closed": all(
            invalid_states.get(name, {}).get("authenticated") is False
            for name in ("missing", "implicit_integrity", "bad_spec", "bad_parent")
        ),
        "all_nested_rehashed_tampers_fail_closed": bool(tampered_states)
        and all(
            state.get("authenticated") is False
            for state in tampered_states.values()
        ),
        "invalid_states_mask_all_v40_evidence": bool(invalid_states)
        and all(
            not state.get("artifact")
            and not state.get("aggregate")
            and not state.get("seed_rows")
            and not state.get("redesign")
            and state.get("graph_definition_sha256") == "NOT AUTHENTICATED"
            and state.get("counterexample_bundle_sha256") == "NOT AUTHENTICATED"
            for state in invalid_states.values()
        ),
        "healthy_normalizer_preserves_exact_artifact_ledgers": bool(
            healthy.get("seed_rows")
            == _rows(_mapping(sealed.get("connectivity_evidence")).get("seed_rows"))
            and healthy.get("aggregate") == sealed.get("aggregate_evidence")
            and healthy.get("redesign") == sealed.get("resource_redesign")
        ),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_is_bounded_and_non_executable": bool(
            projected_bands.get("v40_global_connectivity_decision")
            == "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE"
            and projected_bands.get("v40_resource_architecture_decision")
            == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
            and projected_bands.get("v40_complete_global_connectivity")
            == "DISCONNECTED"
            and projected_bands.get("hardware_executable") is False
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
        "v34_through_v40_markers_present_initially": all(
            marker in first_text for marker in REQUIRED_MARKERS
        ),
        "v34_through_v40_markers_present_after_rerun": all(
            marker in final_text for marker in REQUIRED_MARKERS
        ),
        "v40_markdown_hooks_present_once": all(
            final_text.count(hook) == 1 for hook in hook_values
        ),
        "exact_seed_order_and_cardinality": expected_seed_order == EXPECTED_SEEDS,
        "connectivity_ledger_equals_artifact_initially": _contains_exact_frame(
            first_frames, expected_connectivity
        ),
        "connectivity_ledger_equals_artifact_after_rerun": _contains_exact_frame(
            final_frames, expected_connectivity
        ),
        "counterexample_ledger_equals_artifact_initially": _contains_exact_frame(
            first_frames, expected_counterexamples
        ),
        "counterexample_ledger_equals_artifact_after_rerun": _contains_exact_frame(
            final_frames, expected_counterexamples
        ),
        "redesign_ledger_equals_artifact_initially": _contains_exact_frame(
            first_frames, expected_redesign
        ),
        "redesign_ledger_equals_artifact_after_rerun": _contains_exact_frame(
            final_frames, expected_redesign
        ),
        "ledger_row_counts_exact": (
            len(expected_connectivity) == 8
            and len(expected_counterexamples) == 3
            and len(expected_redesign) == 2
        ),
        "all_sensitive_controls_present_once_and_disabled": all(
            len(items) == 1 and getattr(items[0], "disabled", None) is True
            for items in sensitive.values()
        ),
        "credential_controls_present_once_and_disabled": all(
            len(items := widgets(collection, label)) == 1
            and getattr(items[0], "disabled", None) is True
            for collection, label in credential_widgets
        ),
        "artifact_spec_and_ledgers_downloads_present_once": all(
            len(downloads(label)) == 1
            for label in (
                "Download sealed V4.0 connectivity artifact",
                "Download V4.0 frozen connectivity specification",
                "Download V4.0 eight-seed connectivity ledger CSV",
                "Download V4.0 isolated-counterexample ledger CSV",
            )
        ),
        "exact_connectivity_totals_visible": all(
            marker in final_text
            for marker in (
                "21,655,776",
                "337,710,603",
                "216,557,760",
                "seeds 2207 and 7703",
                "three exact feasible isolated portfolios",
            )
        ),
        "redesign_is_visibly_not_evaluated": (
            "RESOURCE REDESIGN · PREREGISTERED · NOT EVALUATED" in final_text
            and "NOT_EVALUATED" in final_text
            and "NOT_COMPUTED" in final_text
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
        "hardware_provider_and_advantage_boundaries_visible": (
            "HARDWARE EXECUTION · BLOCKED · ZERO JOBS" in final_text
            and "BACKEND TRANSPILATION · NOT RUN" in final_text
            and "QUANTUM ADVANTAGE · NOT CLAIMED" in final_text
        ),
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "failed_checks": failed,
        "first_exception_messages": first_exceptions,
        "final_exception_messages": final_exceptions,
        "contract_errors": contract_errors,
        "normalizer_invalid_cases": sorted(invalid_states),
        "tab_count": len(final_tabs),
        "tabs": list(final_tabs),
        "expected_ledger_rows": {
            "connectivity": len(expected_connectivity),
            "counterexamples": len(expected_counterexamples),
            "redesign_candidates": len(expected_redesign),
        },
        "dataframe_schemas": [
            {
                "columns": [str(column) for column in frame.columns],
                "rows": len(frame),
            }
            for frame in final_frames
        ],
        "valid": not failed and not contract_errors,
        "verifier": "QUANTUM LAB V4.0 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V4.0 UI.")
    parser.add_argument(
        "app",
        nargs="?",
        type=Path,
        default=Path("app_v40_offline_harness.py"),
    )
    parser.add_argument("--timeout", type=float, default=240.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v40(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "CONNECTIVITY_LEDGER_COLUMNS",
    "COUNTEREXAMPLE_LEDGER_COLUMNS",
    "EXPECTED_SEEDS",
    "EXPECTED_TABS",
    "REDESIGN_LEDGER_COLUMNS",
    "REQUIRED_MARKERS",
    "verify_streamlit_surface_v40",
]
