"""Positive-rerun Streamlit verifier for the Quantum Lab V4.4 surface."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd


EXPECTED_CHECK_COUNT = 26
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


def verify_streamlit_surface_v44(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v44_ui import (
            EXPECTED_OVERALL,
            NOT_RUN,
            _boundary_ledger,
            _canary_ledger,
            _capacity_ledger,
            _decision_ledger,
            _hash_ledger,
            _register_floor_ledger,
            _target_ledger,
            _toolchain_ledger,
            apply_v44_encoding_state,
            load_v44_ui_artifact,
            normalize_v44_artifact,
        )
        from .phase3_v44_named_backend_routing import (
            canonical_json_sha256,
            load_v44_snapshot,
            load_v44_toolchain,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.4 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    contract_errors: list[str] = []
    try:
        sealed, integrity = load_v44_ui_artifact()
        auth_checks = _mapping(integrity.get("checks"))
        artifact_integrity = bool(auth_checks.get("artifact_raw_identity") is True and auth_checks.get("artifact_semantic_identity") is True)
        spec_integrity = auth_checks.get("spec_raw_semantic_identity") is True
        snapshot_integrity = auth_checks.get("snapshot_raw_semantic_identity") is True
        toolchain_integrity = auth_checks.get("toolchain_raw_semantic_identity") is True
        parent_integrity = auth_checks.get("v43_parent_and_191_immutable_paths") is True
        healthy = normalize_v44_artifact(
            sealed,
            artifact_integrity=artifact_integrity,
            spec_integrity=spec_integrity,
            snapshot_integrity=snapshot_integrity,
            toolchain_integrity=toolchain_integrity,
            parent_integrity=parent_integrity,
        )
        invalid_states = {
            "missing": normalize_v44_artifact(None, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
            "implicit": normalize_v44_artifact(sealed, artifact_integrity=None, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
            "bad_spec": normalize_v44_artifact(sealed, artifact_integrity=True, spec_integrity=False, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
            "bad_snapshot": normalize_v44_artifact(sealed, artifact_integrity=True, spec_integrity=True, snapshot_integrity=False, toolchain_integrity=True, parent_integrity=True),
            "bad_toolchain": normalize_v44_artifact(sealed, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=False, parent_integrity=True),
            "bad_parent": normalize_v44_artifact(sealed, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=False),
        }
        tampered = copy.deepcopy(sealed)
        tampered["claim_boundary"]["hardware_executable"] = True
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        invalid_states["rehashed_boundary_tamper"] = normalize_v44_artifact(
            tampered,
            artifact_integrity=False,
            spec_integrity=True,
            snapshot_integrity=True,
            toolchain_integrity=True,
            parent_integrity=True,
        )
        base_encoding = {"encoding_status": "BASE ORIGINAL", "hardware_executable": True, "logical_qubits_min": 40}
        projected_base = apply_v44_encoding_state(base_encoding, regime="BASE", state=healthy, artifact=sealed)
        projected_bands = apply_v44_encoding_state(base_encoding, regime="BANDS", state=healthy, artifact=sealed)
        snapshot_payload = load_v44_snapshot()
        toolchain_payload = load_v44_toolchain()
        expected_frames = {
            "capacity": _capacity_ledger(healthy, sealed),
            "register_floor": _register_floor_ledger(healthy, sealed),
            "decision": _decision_ledger(healthy),
            "target": _target_ledger(healthy, snapshot_payload),
            "toolchain": _toolchain_ledger(healthy, toolchain_payload),
            "canary": _canary_ledger(healthy, sealed),
            "hashes": _hash_ledger(healthy, sealed),
            "boundary": _boundary_ledger(healthy, sealed),
        }
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = healthy = {}
        integrity = {"valid": False}
        artifact_integrity = spec_integrity = snapshot_integrity = toolchain_integrity = parent_integrity = False
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
        "Rebuild sealed V4.4 canaries",
        "Change the frozen FakeMarrakesh snapshot",
        "Override the 156-qubit capacity gate",
        "Treat rejected full-workload metrics as zero",
        "Run full-workload transpilation",
        "Run full-workload routing",
        "Enable scheduling or calibration extrapolation",
        "Read provider credentials · V4.4 prohibited",
        "Contact a provider service · V4.4 prohibited",
        "Submit a QPU job · V4.4 prohibited",
        "Promote to hardware executable",
        "Claim optimization performance or quantum advantage",
    )
    download_labels = (
        "Download V4.4 frozen backend snapshot",
        "Download V4.4 target topology CSV",
        "Download V4.4 pinned toolchain manifest",
        "Download V4.4 canary ledger CSV",
        "Download sealed V4.4 named-backend artifact",
        "Download V4.4 frozen protocol specification",
        "Download V4.4 capacity ledger CSV",
        "Download V4.4 boundary ledger CSV",
        "Download V4.4 hash ledger CSV",
        "Download V4.4 next-gate contract",
    )
    hooks = (
        'data-qv44-surface="named-offline-backend-zero-job"',
        'data-qv44-release="4.4"',
        'data-qv44-auth="pass"',
        'data-qv44-parent="pass"',
        'data-qv44-snapshot="pass"',
        'data-qv44-toolchain="pass"',
        'data-qv44-backend="fake_marrakesh"',
        'data-qv44-target-kind="offline-fake-snapshot"',
        'data-qv44-outcome="capacity-rejected"',
        'data-qv44-transpilation="NOT_RUN_CAPACITY_PRECHECK_REJECTED"',
        'data-qv44-routing="NOT_RUN_CAPACITY_PRECHECK_REJECTED"',
        'data-qv44-seeds="8-of-8-rejected"',
        'data-qv44-provider-sdk="false"',
        'data-qv44-credential-reads="0"',
        'data-qv44-provider-calls="0"',
        'data-qv44-network-calls="0"',
        'data-qv44-qpu-submit="disabled"',
        'data-qv44-jobs="0"',
        'data-qv44-hardware="false"',
        'data-qv44-performance="NOT_TESTED"',
        'data-qv44-advantage="NOT_CLAIMED"',
        'data-qv44-research="RESEARCH_ONLY"',
    )
    required_markers = (
        "V4.3 · SEALED ELEMENTARY CIRCUIT MANIFEST · INSTITUTIONAL EVIDENCE SURFACE",
        "V4.4 · Named Offline Backend / Zero-Job Routing Gate",
        "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB",
        "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION",
        "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
        "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY",
        "FakeMarrakesh has 156 qubits",
        "327–339",
        "160",
        "−183",
        "5 / 5 PASS",
        "2 / 2 IDENTICAL",
        "EXPECTED REJECT",
    )
    boundary_markers = (
        "RESEARCH_ONLY",
        "Current calibration",
        "NOT QUERIED",
        "Optimization performance",
        "NOT_TESTED",
        "Quantum advantage",
        "NOT_CLAIMED",
        "PROVIDER SPY CALLS · 0",
        "TRANSPILE SPY CALLS · 0",
        "SEAL SPY CALLS · 0",
        "NETWORK CALLS · 0",
        "QPU JOBS · 0",
    )
    capacity_frame = expected_frames.get("capacity", pd.DataFrame())
    canary_frame = expected_frames.get("canary", pd.DataFrame())
    checks: dict[str, bool] = {
        "sealed_artifact_and_24_way_context_authentication": bool(integrity.get("valid") is True and integrity.get("check_count") == 24 and artifact_integrity),
        "spec_snapshot_toolchain_and_191_path_parent_authentication": bool(spec_integrity and snapshot_integrity and toolchain_integrity and parent_integrity),
        "normalizer_requires_explicit_six_way_authentication": healthy.get("authenticated") is True,
        "missing_implicit_dependency_and_rehashed_tamper_states_fail_closed": bool(invalid_states) and all(state.get("authenticated") is False for state in invalid_states.values()),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_exact_and_hardware_blocked": bool(projected_bands.get("v44_decision") == EXPECTED_OVERALL and projected_bands.get("backend_qubits") == 156 and projected_bands.get("logical_qubits_min") == 339 and projected_bands.get("v44_rejected_seed_count") == 8 and projected_bands.get("backend_transpilation") == NOT_RUN and projected_bands.get("full_workload_routing") == NOT_RUN and projected_bands.get("hardware_executable") is False and projected_bands.get("provider_calls") == projected_bands.get("network_calls") == projected_bands.get("qpu_jobs_submitted") == 0),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": final_tabs[:3] + final_tabs[7:] == ("MISSION CONTROL", "REGIME / DENSITY", "QMC / RISK", "QUBO / ISING", "QUANTUM INFORMATION", "BENCHMARK PROTOCOL", "PHASE II / OOS", "PHASE III / QPU") and final_tabs[3:7] == EXPECTED_TABS[3:7],
        "v43_lineage_and_v44_markers_present_both_runs": all(marker in first_text and marker in final_text for marker in required_markers),
        "twenty_two_machine_readable_hooks_present_once": all(first_text.count(hook) == 1 and final_text.count(hook) == 1 for hook in hooks),
        "twelve_v44_metric_cards_present_once": first_text.count("qv44-metric") == 12 and final_text.count("qv44-metric") == 12,
        "all_eight_exact_v44_ledgers_both_runs": bool(expected_frames) and all(_contains_frame(first_frames, frame) and _contains_frame(final_frames, frame) for frame in expected_frames.values()),
        "eight_capacity_rows_widths_and_deficits_exact": bool(tuple(capacity_frame.get("Seed", ())) == (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807) and tuple(capacity_frame.get("Logical qubits", ())) == (330, 331, 327, 328, 329, 331, 339, 334) and tuple(capacity_frame.get("Deficit", ())) == (-174, -175, -171, -172, -173, -175, -183, -178)),
        "five_canary_rows_and_target_audits_exact": bool(tuple(canary_frame.get("Canary", ())) == ("ISA_TRANSLATION_3Q", "REVERSIBLE_ARITHMETIC_MCX_5Q", "REMOVE_COIN_RING_40Q", "DUAL_COIN_RINGS_80Q", "EXACT_CAPACITY_BOUNDARY_156Q") and set(canary_frame.get("ISA", ())) == {"PASS"} and set(canary_frame.get("Coupling", ())) == {"PASS"}),
        "target_ledger_names_snapshot_and_no_live_calibration": all(marker in final_text for marker in ("fake_marrakesh", "Pinned offline fake-backend snapshot", "Current calibration", "NOT QUERIED")),
        "toolchain_ledger_pinned_configuration_visible": all(marker in final_text for marker in ("Qiskit core", "2.5.2", "Optimization level", "trivial", "basic", "translator", "4404")),
        "provider_hardware_performance_advantage_ledger_visible": all(marker in final_text for marker in boundary_markers),
        "all_twelve_governance_controls_present_and_disabled": all(bool(items := buttons(label)) and all(item.disabled is True for item in items) for label in governance_labels),
        "ten_v44_downloads_present_exactly_once": all(len(downloads(label)) == 1 for label in download_labels),
        "legacy_provider_discovery_and_protocol_seal_controls_disabled": all(len(items := buttons(label)) == 1 and items[0].disabled is True for label in ("Discover accessible IBM QPUs", "Seal Phase-III equal-objective hardware protocol")),
        "offline_provider_transpile_seal_network_and_job_spies_zero": all(marker in first_text and marker in final_text for marker in ("PROVIDER SPY CALLS · 0", "TRANSPILE SPY CALLS · 0", "SEAL SPY CALLS · 0", "NETWORK CALLS · 0", "QPU JOBS · 0")),
        "offline_harness_load_normalize_render_apply_contract_passed": "V4.4 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in first_text and "V4.4 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in final_text,
        "capacity_canary_non_extrapolation_and_claim_boundary_visible": all(marker in final_text for marker in ("The five successful canaries do not override this rejection", "Canaries validate only the frozen translation/routing mechanics", "hardware executability is false", "quantum advantage is not claimed")),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.4 UI verifier check count drifted: {len(checks)}")
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
            "v44_canary_rows": len(canary_frame),
            "v44_capacity_rows": len(capacity_frame),
        },
        "errors": errors,
        "failed_checks": failed,
        "valid": not errors and not failed,
        "verifier": "QUANTUM LAB V4.4 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v44_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v44(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_CHECK_COUNT", "EXPECTED_TABS", "verify_streamlit_surface_v44"]
