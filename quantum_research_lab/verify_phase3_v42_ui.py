"""Positive-rerun Streamlit AppTest verifier for the V4.2 UI contract."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

try:
    import pandas as pd
except ImportError:  # pragma: no cover
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
    "V3.9 · SCALABLE N40 REVERSIBLE IR & SELECTED-MODEL ADMISSION",
    "V4.0 · GLOBAL FEASIBLE-GRAPH CONNECTIVITY & RESOURCE REDESIGN PREREGISTRATION",
    "V4.1 · AUGMENTED 1+2 EXCHANGE GRAPH & PROOF-CARRYING RESOURCE ADMISSION",
    "V4.2 · INDEXED COINED-WALK COMPILER · PROOF-CARRYING RESEARCH ADMISSION",
    "RESOURCE ARCHITECTURE · PASS",
    "JOINT PROMISE SUPPORT · CONNECTED",
    "SELECTOR CONTROL · 264,328 / 264,328",
    "RESEARCH GENERATOR ADMITTED ≠ EXECUTABLE CIRCUIT",
    "V4.2 CLAIM BOUNDARY · EXACT PROMISE-SUBSPACE SUPPORT + PROVIDER-NEUTRAL SELECTED-MODEL RESOURCE SCREEN ONLY",
    "NEXT FALSIFIABLE GATE · INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION",
    "CIRCUIT MATERIALIZATION · NOT RUN · BACKEND TRANSPILATION · NOT RUN",
    "HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0 · PROVIDER CALLS · 0",
    "QUANTUM ADVANTAGE · NOT CLAIMED",
)
RESOURCE_COLUMNS = (
    "Seed",
    "CNOT / complete step",
    "Budget margin",
    "Logical qubits",
    "Feasibility oracle CNOT",
    "Oracle invocations",
    "SELECT scaffold CNOT",
    "Bridge CNOT",
    "Bridges",
    "Decision",
    "Seed ledger SHA",
)
SUPPORT_COLUMNS = (
    "Seed",
    "Data vertices",
    "V4.1 one-swap edges",
    "Coin states / vertex",
    "Joint vertices",
    "Coin-ring edges",
    "Selector edges",
    "Replicated bridge edges",
    "Joint support edges",
    "Components",
    "All pair positions",
    "Support SHA",
)
MACRO_COLUMNS = (
    "Seed",
    "Widths",
    "Oracle controlled adds",
    "Oracle comparators",
    "Oracle MCX",
    "Complete direct CNOT",
    "SELECT CCX",
    "Pair labels retained",
    "Formula replay",
)
SELECTOR_COLUMNS = ("Control", "Forward", "Reverse", "Exact match")


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
        "title", "header", "subheader", "markdown", "caption", "success",
        "warning", "error", "info", "metric", "dataframe", "button",
        "download_button",
    )
    parts: list[str] = []
    for name in names:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_element_text(element) for element in elements)
    frames = [
        frame for element in app.dataframe
        if (frame := _as_frame(getattr(element, "value", None))) is not None
    ]
    return "\n".join(parts), tuple(tab.label for tab in app.tabs), frames


def _expected_resource_frame(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for row in _rows(_mapping(artifact.get("resource_evidence")).get("seed_rows")):
        rows.append({
            "Seed": row.get("seed"),
            "CNOT / complete step": _mapping(row.get("selected_model_step_resources")).get("selected_model_cnot"),
            "Budget margin": row.get("budget_margin_cnot"),
            "Logical qubits": row.get("logical_qubits_with_recycled_workspace"),
            "Feasibility oracle CNOT": _mapping(_mapping(row.get("feasibility_oracle")).get("resources")).get("selected_model_cnot"),
            "Oracle invocations": row.get("feasibility_oracle_invocations"),
            "SELECT scaffold CNOT": _mapping(_mapping(row.get("select_scaffold")).get("resources")).get("selected_model_cnot"),
            "Bridge CNOT": row.get("bridge_selected_model_cnot"),
            "Bridges": len(_rows(row.get("bridge_ir"))),
            "Decision": row.get("decision"),
            "Seed ledger SHA": row.get("seed_walk_sha256"),
        })
    return pd.DataFrame(rows, columns=RESOURCE_COLUMNS)


def _expected_support_frame(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows = [
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
        for row in _rows(_mapping(artifact.get("support_evidence")).get("seed_rows"))
    ]
    return pd.DataFrame(rows, columns=SUPPORT_COLUMNS)


def _expected_macro_frame(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows = []
    for row in _rows(_mapping(artifact.get("resource_evidence")).get("seed_rows")):
        terms = _mapping(_mapping(row.get("feasibility_oracle")).get("macro_terms"))
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
    return pd.DataFrame(rows, columns=MACRO_COLUMNS)


def _expected_selector_frame(artifact: Mapping[str, Any]) -> pd.DataFrame:
    selector = _mapping(artifact.get("selector_control"))
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
    ], columns=SELECTOR_COLUMNS)


def _frame_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left.reset_index(drop=True), right.reset_index(drop=True),
            check_dtype=False, check_like=False,
        )
    except (AssertionError, TypeError, ValueError):
        return False
    return True


def _contains_frame(frames: Sequence[pd.DataFrame], expected: pd.DataFrame) -> bool:
    return any(
        tuple(str(column) for column in frame.columns)
        == tuple(str(column) for column in expected.columns)
        and _frame_equal(frame, expected)
        for frame in frames
    )


def verify_streamlit_surface_v42(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    if pd is None:  # pragma: no cover
        return {"checks": {"pandas_available": False}, "errors": ["pandas is required."], "failed_checks": ["pandas_available"], "valid": False}
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as exc:  # pragma: no cover
        return {"checks": {"streamlit_testing_available": False}, "errors": [str(exc)], "failed_checks": ["streamlit_testing_available"], "valid": False}

    contract_errors: list[str] = []
    try:
        from .phase3_v42_coined_walk_compiler import canonical_json_sha256, load_v42_spec
        from .phase3_v42_ui import (
            EXPECTED_V42_SPEC_SHA256,
            apply_v42_encoding_state,
            load_v42_ui_artifact,
            normalize_v42_artifact,
        )
        sealed, integrity = load_v42_ui_artifact()
        spec = load_v42_spec()
        spec_integrity = spec.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA256
        parent_integrity = bool(
            _mapping(sealed.get("parent")).get("immutable_files_exact") is True
            and _mapping(sealed.get("parent")).get("immutable_file_count") == 159
        )
        healthy = normalize_v42_artifact(
            sealed,
            artifact_integrity=integrity.get("valid") is True,
            spec_integrity=spec_integrity,
            parent_integrity=parent_integrity,
        )
        invalid_states = {
            "missing": normalize_v42_artifact(None, artifact_integrity=True, spec_integrity=True, parent_integrity=True),
            "implicit": normalize_v42_artifact(sealed, artifact_integrity=None, spec_integrity=True, parent_integrity=True),
            "bad_spec": normalize_v42_artifact(sealed, artifact_integrity=True, spec_integrity=False, parent_integrity=True),
            "bad_parent": normalize_v42_artifact(sealed, artifact_integrity=True, spec_integrity=True, parent_integrity=False),
        }
        with tempfile.TemporaryDirectory(prefix="quantum-v42-ui-tamper-") as temporary:
            for name, mutate in (
                ("resource", lambda item: item["resource_evidence"]["aggregate"].__setitem__("maximum_selected_model_cnot", 1)),
                ("support", lambda item: item["support_evidence"]["aggregate"].__setitem__("all_seeds_connected", False)),
                ("boundary", lambda item: item["claim_boundary"].__setitem__("hardware_executable", True)),
            ):
                tampered = copy.deepcopy(sealed)
                mutate(tampered)
                tampered["artifact_sha256"] = canonical_json_sha256(
                    {key: value for key, value in tampered.items() if key != "artifact_sha256"}
                )
                target = Path(temporary) / f"{name}.json"
                target.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
                _, report = load_v42_ui_artifact(target)
                invalid_states[f"tamper_{name}"] = normalize_v42_artifact(
                    tampered,
                    artifact_integrity=report.get("valid") is True,
                    spec_integrity=True,
                    parent_integrity=True,
                )
        base_encoding = {"encoding_status": "BASE ORIGINAL", "hardware_executable": True, "logical_qubits_min": 40}
        projected_base = apply_v42_encoding_state(base_encoding, regime="BASE", state=healthy, artifact=sealed)
        projected_bands = apply_v42_encoding_state(base_encoding, regime="BANDS", state=healthy, artifact=sealed)
        expected_frames = {
            "resources": _expected_resource_frame(sealed),
            "support": _expected_support_frame(sealed),
            "macros": _expected_macro_frame(sealed),
            "selector": _expected_selector_frame(sealed),
        }
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = healthy = {}
        integrity = {"valid": False}
        spec_integrity = parent_integrity = False
        invalid_states = {}
        base_encoding = projected_base = projected_bands = {}
        expected_frames = {
            "resources": pd.DataFrame(columns=RESOURCE_COLUMNS),
            "support": pd.DataFrame(columns=SUPPORT_COLUMNS),
            "macros": pd.DataFrame(columns=MACRO_COLUMNS),
            "selector": pd.DataFrame(columns=SELECTOR_COLUMNS),
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
        return [element for element in app.get("download_button") if str(getattr(element.proto, "label", "")) == label]

    def widgets(collection: str, label: str) -> list[Any]:
        return [element for element in getattr(app, collection, ()) if str(getattr(element, "label", "")) == label]

    governance_labels = (
        "Recompute sealed V4.2 evidence",
        "Delete unfavorable pair positions",
        "Relax one-hot promise",
        "Override selected-model CNOT gate",
        "Claim a materialized executable circuit",
        "Select a named backend",
        "Read provider credentials",
        "Submit a QPU job",
    )
    download_labels = (
        "Download sealed V4.2 coined-walk compiler artifact",
        "Download V4.2 frozen compiler specification",
        "Download V4.2 resource ledger CSV",
        "Download V4.2 support ledger CSV",
        "Download V4.2 macro ledger CSV",
        "Download V4.2 selector-control ledger CSV",
    )
    hooks = (
        'data-qv42-surface="coined-walk-compiler"',
        'data-qv42-release="4.2"',
        'data-qv42-auth="pass"',
        'data-qv42-support="CONNECTED"',
        'data-qv42-resource="PASSED"',
        'data-qv42-production="RESEARCH_ADMITTED"',
        'data-qv42-hardware="false"',
        'data-qv42-jobs="0"',
        'data-qv42-provider-calls="0"',
        'data-qv42-circuit="NOT_RUN_NEXT_GATE"',
        'data-qv42-promise="EXACT_FEASIBLE_DATA_X_TWO_ONE_HOT_COIN_REGISTERS"',
    )
    resources = _mapping(_mapping(sealed.get("resource_evidence")).get("aggregate"))
    support = _mapping(_mapping(sealed.get("support_evidence")).get("aggregate"))
    checks = {
        "sealed_artifact_fast_identity_authentication": integrity.get("valid") is True,
        "registered_spec_identity": spec_integrity is True,
        "authenticated_159_path_parent_lineage": parent_integrity is True,
        "normalizer_requires_explicit_three_way_authentication": healthy.get("authenticated") is True,
        "missing_and_rehashed_tamper_states_fail_closed": bool(invalid_states) and all(state.get("authenticated") is False for state in invalid_states.values()),
        "invalid_states_mask_all_v42_ledgers": bool(invalid_states) and all(not state.get("artifact") and not state.get("resource_rows") and not state.get("support_rows") for state in invalid_states.values()),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_research_admitted_hardware_false": bool(
            projected_bands.get("v42_resource_architecture_decision") == "PASSED_SELECTED_MODEL_CNOT_BUDGET"
            and projected_bands.get("v42_joint_support_connected") is True
            and projected_bands.get("v42_all_pair_positions_preserved") is True
            and projected_bands.get("v42_maximum_selected_model_cnot") == 1_135_430
            and projected_bands.get("v42_minimum_budget_margin_cnot") == 1_364_570
            and projected_bands.get("logical_qubits_min") == 331
            and projected_bands.get("hardware_executable") is False
            and projected_bands.get("circuit_materialization") == "NOT_RUN_NEXT_GATE"
            and projected_bands.get("provider_calls") == 0
            and projected_bands.get("qpu_jobs_submitted") == 0
            and projected_bands.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "artifact_support_gate_exact": bool(
            support.get("all_pair_positions_preserved") is True
            and support.get("all_seeds_connected") is True
            and support.get("coin_basis_states_per_data_vertex") == 1_600
            and support.get("joint_promise_vertices") == 34_649_241_600
            and support.get("joint_support_edges") == 69_973_909_206
            and support.get("parent_selected_bridge_count") == 3
        ),
        "artifact_resource_gate_exact": bool(
            resources.get("all_eight_seeds_pass") is True
            and resources.get("maximum_selected_model_cnot") == 1_135_430
            and resources.get("minimum_budget_margin_cnot") == 1_364_570
            and resources.get("budget_cnot") == 2_500_000
            and resources.get("maximum_logical_qubits_with_recycled_workspace") == 331
        ),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": (
            final_tabs[:3] + final_tabs[7:] == (
                "MISSION CONTROL", "REGIME / DENSITY", "QMC / RISK", "QUBO / ISING",
                "QUANTUM INFORMATION", "BENCHMARK PROTOCOL", "PHASE II / OOS", "PHASE III / QPU",
            ) and final_tabs[3:7] == EXPECTED_TABS[3:7]
        ),
        "historical_v39_v40_v41_and_v42_markers_initial": all(marker in first_text for marker in REQUIRED_MARKERS),
        "historical_v39_v40_v41_and_v42_markers_rerun": all(marker in final_text for marker in REQUIRED_MARKERS),
        "v42_panel_hooks_present_exactly_once": all(first_text.count(hook) == 1 and final_text.count(hook) == 1 for hook in hooks),
        "all_four_exact_v42_ledgers_initial": all(_contains_frame(first_frames, frame) for frame in expected_frames.values()),
        "all_four_exact_v42_ledgers_rerun": all(_contains_frame(final_frames, frame) for frame in expected_frames.values()),
        "resource_support_macro_rows_follow_all_eight_seeds": all(tuple(expected_frames[name]["Seed"].tolist()) == EXPECTED_SEEDS for name in ("resources", "support", "macros")),
        "selector_ledger_has_ten_controls": len(expected_frames["selector"]) == 10,
        "all_v42_governance_controls_disabled": all(len(items := buttons(label)) == 1 and items[0].disabled is True for label in governance_labels),
        "legacy_provider_and_seal_controls_disabled": all(
            len(items := buttons(label)) == 1 and items[0].disabled is True
            for label in ("Discover accessible IBM QPUs", "Seal Phase-III equal-objective hardware protocol")
        ),
        "credential_controls_present_once_and_disabled": all(
            len(items := widgets(collection, label)) == 1 and items[0].disabled is True
            for collection, label in (
                ("text_input", "IBM Quantum API key · session only"),
                ("text_input", "IBM instance / CRN · optional"),
                ("checkbox", "Allow previously saved IBM account credentials"),
            )
        ),
        "six_v42_downloads_present_exactly_once": all(len(downloads(label)) == 1 for label in download_labels),
        "exact_resource_support_totals_visible": all(marker in final_text for marker in ("1,135,430", "1,364,570", "2,500,000", "331", "34,649,241,600", "69,973,909,206", "264,328")),
        "provider_transpile_and_seal_spies_zero_both_runs": all(marker in first_text and marker in final_text for marker in ("PROVIDER SPY CALLS · 0", "TRANSPILE SPY CALLS · 0", "SEAL SPY CALLS · 0")),
        "stale_provider_state_cleared_both_runs": "STALE PROVIDER STATE · CLEARED" in first_text and "STALE PROVIDER STATE · CLEARED" in final_text,
        "research_only_circuit_backend_hardware_boundaries_visible": all(marker in final_text for marker in ("RESEARCH_ONLY", "CIRCUIT MATERIALIZATION · NOT RUN", "BACKEND TRANSPILATION · NOT RUN", "HARDWARE EXECUTABLE · FALSE", "QPU JOBS · 0", "PROVIDER CALLS · 0", "QUANTUM ADVANTAGE · NOT CLAIMED")),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "counts": {
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "dataframes_final": len(final_frames),
            "download_buttons": len(app.get("download_button")),
            "tabs": len(final_tabs),
            "v42_resource_rows": len(expected_frames["resources"]),
            "v42_support_rows": len(expected_frames["support"]),
        },
        "errors": contract_errors + first_exceptions + final_exceptions,
        "failed_checks": failed,
        "valid": not contract_errors and not first_exceptions and not final_exceptions and not failed,
        "verifier": "QUANTUM LAB V4.2 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v42_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v42(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_TABS", "verify_streamlit_surface_v42"]
