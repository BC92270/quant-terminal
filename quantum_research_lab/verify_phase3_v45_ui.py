"""Positive-rerun Streamlit verifier for the Quantum Lab V4.5 surface."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


EXPECTED_CHECK_COUNT = 28
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


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
        "download_button", "code",
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


def _frame_equal(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    try:
        pd.testing.assert_frame_equal(
            left.reset_index(drop=True).fillna("").astype(str),
            right.reset_index(drop=True).fillna("").astype(str),
            check_dtype=False,
            check_like=False,
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


def verify_streamlit_surface_v45(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v45_proof_carrying_width_reduction import canonical_json_sha256
        from .phase3_v45_ui import (
            EXPECTED_NEXT_GATE,
            EXPECTED_OVERALL,
            EXPECTED_PRODUCTION,
            NOT_RUN,
            _boundary_ledger,
            _cnot_ledger,
            _hash_ledger,
            _liveness_ledger,
            _register_ledger,
            _semantic_ledger,
            _width_ledger,
            apply_v45_encoding_state,
            load_v45_ui_artifact,
            load_v45_ui_supporting_evidence,
            normalize_v45_artifact,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.5 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    contract_errors: list[str] = []
    try:
        sealed, integrity = load_v45_ui_artifact()
        auth_checks = _mapping(integrity.get("checks"))
        artifact_integrity = bool(
            auth_checks.get("artifact_raw_identity") is True
            and auth_checks.get("artifact_semantic_identity") is True
        )
        spec_integrity = auth_checks.get("spec_raw_semantic_identity") is True
        liveness_integrity = bool(
            auth_checks.get("liveness_raw_identity") is True
            and auth_checks.get("liveness_semantic_identity") is True
        )
        parent_integrity = bool(
            auth_checks.get("v44_parent_and_209_immutable_paths") is True
            and auth_checks.get("artifact_parent_crosslinks") is True
        )
        source_integrity = auth_checks.get("source_raw_identity") is True
        checker_integrity = auth_checks.get("checker_raw_identity") is True
        spec_payload, liveness_payload = load_v45_ui_supporting_evidence()
        if not isinstance(sealed, dict) or not isinstance(spec_payload, dict) or not isinstance(liveness_payload, dict):
            raise AssertionError("V4.5 sealed or supporting evidence is unavailable")
        healthy = normalize_v45_artifact(
            sealed,
            artifact_integrity=artifact_integrity,
            spec_integrity=spec_integrity,
            liveness_integrity=liveness_integrity,
            parent_integrity=parent_integrity,
            source_integrity=source_integrity,
            checker_integrity=checker_integrity,
        )
        invalid_states = {
            "missing": normalize_v45_artifact(None, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
            "implicit": normalize_v45_artifact(sealed, artifact_integrity=None, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
            "bad_spec": normalize_v45_artifact(sealed, artifact_integrity=True, spec_integrity=False, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
            "bad_liveness": normalize_v45_artifact(sealed, artifact_integrity=True, spec_integrity=True, liveness_integrity=False, parent_integrity=True, source_integrity=True, checker_integrity=True),
            "bad_parent": normalize_v45_artifact(sealed, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=False, source_integrity=True, checker_integrity=True),
            "bad_source": normalize_v45_artifact(sealed, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=False, checker_integrity=True),
            "bad_checker": normalize_v45_artifact(sealed, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=False),
        }
        tampered = copy.deepcopy(sealed)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        invalid_states["rehashed_boundary_tamper"] = normalize_v45_artifact(
            tampered,
            artifact_integrity=False,
            spec_integrity=True,
            liveness_integrity=True,
            parent_integrity=True,
            source_integrity=True,
            checker_integrity=True,
        )
        base_encoding = {
            "encoding_status": "BASE ORIGINAL",
            "hardware_executable": True,
            "logical_qubits_min": 339,
        }
        projected_base = apply_v45_encoding_state(
            base_encoding, regime="BASE", state=healthy, artifact=sealed
        )
        projected_bands = apply_v45_encoding_state(
            base_encoding, regime="BANDS", state=healthy, artifact=sealed
        )
        expected_frames = {
            "width": _width_ledger(healthy, sealed),
            "cnot": _cnot_ledger(healthy, sealed),
            "register": _register_ledger(healthy, liveness_payload),
            "liveness": _liveness_ledger(healthy, liveness_payload),
            "semantic": _semantic_ledger(healthy, sealed),
            "boundary": _boundary_ledger(healthy, sealed),
            "hashes": _hash_ledger(healthy, sealed, liveness_payload),
        }
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = healthy = {}
        integrity = {"valid": False}
        artifact_integrity = spec_integrity = liveness_integrity = False
        parent_integrity = source_integrity = checker_integrity = False
        invalid_states = {}
        base_encoding = projected_base = projected_bands = {}
        expected_frames = {}

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
            element for element in app.get("download_button")
            if str(getattr(element.proto, "label", "")) == label
        ]

    governance_labels = (
        "Rebuild or mutate the sealed V4.5 artifact",
        "Change the frozen V4.4 parent lineage",
        "Override the 156-qubit logical-capacity gate",
        "Expand the exact claim beyond valid addresses 0–39",
        "Discard garbage instead of reversible uncompute",
        "Reset or measure borrowed workspace",
        "Treat logical width as routed hardware fit",
        "Run full-workload transpilation inside V4.5",
        "Run full-workload routing inside V4.5",
        "Read credentials or contact a provider",
        "Submit a simulator or QPU job",
        "Claim hardware execution, performance or quantum advantage",
    )
    download_labels = (
        "Download V4.5 register/liveness certificate",
        "Download V4.5 register ledger CSV",
        "Download V4.5 liveness events CSV",
        "Download V4.5 semantic trace ledger CSV",
        "Download sealed V4.5 artifact",
        "Download frozen V4.5 protocol",
        "Download V4.5 width ledger CSV",
        "Download V4.5 CNOT budget ledger CSV",
        "Download V4.5 boundary ledger CSV",
        "Download V4.5 hash ledger CSV",
    )
    hooks = (
        'data-qv45-surface="proof-carrying-width-reduction"',
        'data-qv45-release="4.5"',
        'data-qv45-auth="pass"',
        'data-qv45-parent="pass"',
        'data-qv45-max-width="145"',
        'data-qv45-min-margin="11"',
        'data-qv45-cnot-budget="2500000"',
        'data-qv45-provider-sdk="false"',
        'data-qv45-credential-reads="0"',
        'data-qv45-provider-calls="0"',
        'data-qv45-network-calls="0"',
        'data-qv45-jobs="0"',
        'data-qv45-qpu-submit="disabled"',
        'data-qv45-hardware="false"',
        'data-qv45-transpilation="NOT_RUN_IN_V4_5"',
        'data-qv45-routing="NOT_RUN_IN_V4_5"',
        'data-qv45-performance="NOT_TESTED"',
        'data-qv45-advantage="NOT_CLAIMED"',
        'data-qv45-research="RESEARCH_ONLY"',
    )
    required_markers = (
        "V4.4 · Named Offline Backend / Zero-Job Routing Gate",
        "V4.5 · Proof-Carrying Width Reduction",
        EXPECTED_OVERALL,
        EXPECTED_PRODUCTION,
        EXPECTED_NEXT_GATE,
        "133–145",
        "327–339",
        "67 + 2W",
        "2,499,790",
        "+210",
        "1,600",
        "WIDTH + PROMISE PARITY · PASSED",
    )
    boundary_markers = (
        "RESEARCH_ONLY",
        "NOT_RUN_IN_V4_5",
        "Optimization performance",
        "NOT_TESTED",
        "Quantum advantage",
        "NOT_CLAIMED",
        "hardware executability is false",
        "PROVIDER SPY CALLS · 0",
        "TRANSPILE SPY CALLS · 0",
        "SEAL SPY CALLS · 0",
        "CREDENTIAL READS · 0",
        "NETWORK CALLS · 0",
        "QPU JOBS · 0",
    )

    width_frame = expected_frames.get("width", pd.DataFrame())
    cnot_frame = expected_frames.get("cnot", pd.DataFrame())
    register_frame = expected_frames.get("register", pd.DataFrame())
    liveness_frame = expected_frames.get("liveness", pd.DataFrame())
    semantic_frame = expected_frames.get("semantic", pd.DataFrame())
    boundary_frame = expected_frames.get("boundary", pd.DataFrame())
    hash_frame = expected_frames.get("hashes", pd.DataFrame())
    cnot_values = tuple(int(value) for value in cnot_frame.get("Materialized CX", ()))
    cnot_margins = tuple(int(value) for value in cnot_frame.get("Margin", ()))

    checks: dict[str, bool] = {
        "sealed_artifact_and_28_way_authentication": bool(integrity.get("valid") is True and integrity.get("check_count") == 28 and artifact_integrity),
        "spec_liveness_source_checker_and_v44_parent_authentication": bool(spec_integrity and liveness_integrity and source_integrity and checker_integrity and parent_integrity),
        "normalizer_requires_explicit_seven_way_authentication": healthy.get("authenticated") is True,
        "missing_implicit_dependency_and_rehashed_tamper_states_fail_closed": bool(invalid_states) and all(
            state.get("authenticated") is False
            and state.get("decision") == "MASKED_FAIL_CLOSED"
            and "maximum_logical_qubits" not in state
            and "maximum_materialized_cnot" not in state
            for state in invalid_states.values()
        ),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_width_pass_but_hardware_blocked": bool(projected_bands.get("v45_decision") == EXPECTED_OVERALL and projected_bands.get("backend_capacity_ok") is True and projected_bands.get("backend_qubits") == 156 and projected_bands.get("logical_qubits_max") == 145 and projected_bands.get("v45_minimum_capacity_margin_qubits") == 11 and projected_bands.get("v45_cnot_budget_pass_count") == 8 and projected_bands.get("backend_transpilation") == NOT_RUN and projected_bands.get("full_workload_routing") == NOT_RUN and projected_bands.get("hardware_executable") is False and projected_bands.get("provider_calls") == projected_bands.get("network_calls") == projected_bands.get("qpu_jobs_submitted") == 0),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": final_tabs[:3] + final_tabs[7:] == ("MISSION CONTROL", "REGIME / DENSITY", "QMC / RISK", "QUBO / ISING", "QUANTUM INFORMATION", "BENCHMARK PROTOCOL", "PHASE II / OOS", "PHASE III / QPU") and final_tabs[3:7] == EXPECTED_TABS[3:7],
        "v44_lineage_and_v45_markers_present_both_runs": all(marker in first_text and marker in final_text for marker in required_markers),
        "nineteen_machine_readable_hooks_present_once": all(first_text.count(hook) == 1 and final_text.count(hook) == 1 for hook in hooks),
        "twelve_v45_metric_cards_present_once": first_text.count("qv45-metric") == 12 and final_text.count("qv45-metric") == 12,
        "all_seven_exact_v45_ledgers_both_runs": bool(expected_frames) and all(_contains_frame(first_frames, frame) and _contains_frame(final_frames, frame) for frame in expected_frames.values()),
        "eight_width_rows_old_new_margins_and_capacity_exact": bool(tuple(width_frame.get("Seed", ())) == (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807) and tuple(width_frame.get("V4.3 width", ())) == (330, 331, 327, 328, 329, 331, 339, 334) and tuple(width_frame.get("V4.5 width", ())) == (135, 137, 133, 135, 137, 137, 145, 139) and tuple(width_frame.get("156Q margin", ())) == (21, 19, 23, 21, 19, 19, 11, 17) and set(width_frame.get("Capacity", ())) == {"PASS"}),
        "eight_cnot_rows_budget_worst_and_margin_exact": bool(len(cnot_values) == 8 and max(cnot_values, default=-1) == 2_499_790 and all(0 <= value <= 2_500_000 for value in cnot_values) and min(cnot_margins, default=-1) == 210),
        "register_and_phase_liveness_ledgers_complete": bool(len(register_frame) == 72 and len(liveness_frame) == 32 and set(register_frame.get("Register", ())) == {"DATA", "REMOVE_ADDR", "ADD_ADDR", "SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"}),
        "semantic_trace_ledger_covers_all_eight_seeds": bool(len(semantic_frame) == 8 and set(semantic_frame.get("Address pairs / representative", ())) == {1600} and set(semantic_frame.get("Relation", ())) == {"EXACT_SELECT_TRACE_PARITY_FOR_ALL_1600_ADDRESS_PAIRS_OF_EACH_AUTHENTICATED_COMPONENT_REPRESENTATIVE"}),
        "provider_hardware_routing_and_advantage_boundary_exact": bool(len(boundary_frame) == 12 and all(marker in first_text and marker in final_text for marker in boundary_markers)),
        "nine_hash_identities_visible_both_runs": bool(len(hash_frame) == 9 and _contains_frame(first_frames, hash_frame) and _contains_frame(final_frames, hash_frame)),
        "all_twelve_v45_governance_controls_present_and_disabled": all(bool(items := buttons(label)) and all(item.disabled is True for item in items) for label in governance_labels),
        "ten_v45_downloads_present_exactly_once": all(len(downloads(label)) == 1 for label in download_labels),
        "legacy_provider_discovery_and_protocol_seal_controls_disabled": all(len(items := buttons(label)) == 1 and items[0].disabled is True for label in ("Discover accessible IBM QPUs", "Seal Phase-III equal-objective hardware protocol")),
        "offline_provider_transpile_seal_network_and_job_spies_zero": all(marker in first_text and marker in final_text for marker in ("PROVIDER SPY CALLS · 0", "TRANSPILE SPY CALLS · 0", "SEAL SPY CALLS · 0", "NETWORK CALLS · 0", "QPU JOBS · 0")),
        "offline_harness_load_normalize_render_apply_contract_passed": "V4.5 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in first_text and "V4.5 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in final_text,
        "next_gate_and_non_extrapolation_boundary_visible": all(marker in final_text for marker in ("Full backend reconstruction, transpilation and routing remain the next gate and were not run in V4.5", "Logical width is a wire count, not a hardware claim", "no current calibration, fidelity, runtime, utility or advantage conclusion is authorized")),
        "v44_historical_evidence_surface_preserved": all(marker in first_text and marker in final_text for marker in ("V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB", "NOT_RUN_CAPACITY_PRECHECK_REJECTED", "5 / 5 PASS", "2 / 2 IDENTICAL")),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.5 UI verifier check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors = list(dict.fromkeys(contract_errors + first_exceptions + final_exceptions))
    return {
        "app_path": str(target),
        "check_count": len(checks),
        "checks": checks,
        "counts": {
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "dataframes_final": len(final_frames),
            "download_buttons": len(app.get("download_button")),
            "tabs": len(final_tabs),
            "v45_cnot_rows": len(cnot_frame),
            "v45_liveness_rows": len(liveness_frame),
            "v45_register_rows": len(register_frame),
            "v45_semantic_rows": len(semantic_frame),
            "v45_width_rows": len(width_frame),
        },
        "errors": errors,
        "failed_checks": failed,
        "valid": not errors and not failed,
        "verifier": "QUANTUM LAB V4.5 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v45_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v45(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_CHECK_COUNT", "EXPECTED_TABS", "verify_streamlit_surface_v45"]
