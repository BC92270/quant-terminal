"""Positive-rerun Streamlit verifier for the Quantum Lab V4.3 surface.

The verifier authenticates the sealed artifact independently, exercises the
fail-closed normalizer and encoding projection, then renders the complete
offline application twice.  Provider, transpilation, sealing and QPU activity
remain prohibited by the predecessor harness spies.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping, Sequence

import pandas as pd


EXPECTED_CHECK_COUNT = 20
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
EXPECTED_BASIS = ("X", "H", "T", "TDG", "RY", "RZ", "CX")
EXPECTED_CX = (1_106_814, 1_110_414, 1_084_798, 1_084_798, 1_084_798, 1_106_814, 1_158_046, 1_128_830)
EXPECTED_QUBITS = (330, 331, 327, 328, 329, 331, 339, 334)


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
            left.reset_index(drop=True),
            right.reset_index(drop=True),
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


def verify_streamlit_surface_v43(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v43_ui import (
            _basis_ledger,
            _correction_ledger,
            _materialization_ledger,
            _register_ledger,
            _simulator_ledger,
            apply_v43_encoding_state,
            load_v43_ui_artifact,
            normalize_v43_artifact,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.3 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    contract_errors: list[str] = []
    try:
        sealed, integrity = load_v43_ui_artifact()
        integrity_checks = _mapping(integrity.get("checks"))
        spec_integrity = integrity_checks.get("sealed_sources") is True
        parent_integrity = integrity_checks.get("parent_identity") is True
        artifact_integrity = bool(
            integrity_checks.get("artifact_raw_identity") is True
            and integrity_checks.get("artifact_semantic_identity") is True
        )
        healthy = normalize_v43_artifact(
            sealed,
            artifact_integrity=artifact_integrity,
            spec_integrity=spec_integrity,
            parent_integrity=parent_integrity,
        )
        invalid_states = {
            "missing": normalize_v43_artifact(None, artifact_integrity=True, spec_integrity=True, parent_integrity=True),
            "implicit": normalize_v43_artifact(sealed, artifact_integrity=None, spec_integrity=True, parent_integrity=True),
            "bad_spec": normalize_v43_artifact(sealed, artifact_integrity=True, spec_integrity=False, parent_integrity=True),
            "bad_parent": normalize_v43_artifact(sealed, artifact_integrity=True, spec_integrity=True, parent_integrity=False),
        }
        with tempfile.TemporaryDirectory(prefix="quantum-v43-ui-tamper-") as temporary:
            tampered = copy.deepcopy(sealed)
            tampered["claim_boundary"]["hardware_executable"] = True
            # A semantically self-consistent rewrite is still rejected because
            # the registered raw and semantic identities are immutable.
            from .phase3_v43_reversible_circuit_ir import canonical_json_sha256
            tampered["artifact_sha256"] = canonical_json_sha256(
                {key: value for key, value in tampered.items() if key != "artifact_sha256"}
            )
            target = Path(temporary) / "rehashed-boundary-tamper.json"
            target.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")
            _, tamper_report = load_v43_ui_artifact(target)
            invalid_states["rehashed_boundary_tamper"] = normalize_v43_artifact(
                tampered,
                artifact_integrity=tamper_report.get("valid") is True,
                spec_integrity=True,
                parent_integrity=True,
            )
        base_encoding = {
            "encoding_status": "BASE ORIGINAL",
            "hardware_executable": True,
            "logical_qubits_min": 40,
        }
        projected_base = apply_v43_encoding_state(
            base_encoding, regime="BASE", state=healthy, artifact=sealed
        )
        projected_bands = apply_v43_encoding_state(
            base_encoding, regime="BANDS", state=healthy, artifact=sealed
        )
        expected_frames = {
            "materialization": _materialization_ledger(healthy),
            "basis": _basis_ledger(healthy),
            "simulator": _simulator_ledger(healthy),
            "corrections": _correction_ledger(healthy),
            "registers": _register_ledger(healthy),
        }
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed = healthy = {}
        integrity = {"valid": False}
        spec_integrity = parent_integrity = artifact_integrity = False
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
        "Rebuild sealed V4.3 streams",
        "Relax the feasible-data promise",
        "Suppress the negative control",
        "Rewrite the V4.2 decision",
        "Override the 2,500,000 CX gate",
        "Select a named backend · V4.3 next gate",
        "Run transpilation or routing",
        "Read provider credentials · V4.3 prohibited",
        "Submit a QPU job · V4.3 prohibited",
        "Claim quantum advantage",
    )
    download_labels = (
        "Download sealed V4.3 reversible-circuit artifact",
        "Download V4.3 frozen materialization specification",
        "Download V4.3 materialization ledger CSV",
        "Download V4.3 elementary-basis ledger CSV",
        "Download V4.3 simulator ledger CSV",
        "Download V4.3 correction ledger CSV",
        "Download V4.3 register ledger CSV",
    )
    hooks = (
        'data-qv43-surface="reversible-circuit-materialization"',
        'data-qv43-release="4.3"',
        'data-qv43-auth="pass"',
        'data-qv43-materialization="SEALED"',
        'data-qv43-promise="EXACT_FEASIBLE_N40_X_TWO_ONE_HOT_COINS_ONLY"',
        'data-qv43-off-promise="REJECTED_WITH_WITNESS"',
        'data-qv43-backend="NOT_RUN"',
        'data-qv43-hardware="false"',
        'data-qv43-jobs="0"',
        'data-qv43-provider-calls="0"',
    )
    required_markers = (
        "V4.2 · INDEXED COINED-WALK COMPILER · PROOF-CARRYING RESEARCH ADMISSION",
        "V4.3 · SEALED ELEMENTARY CIRCUIT MANIFEST · INSTITUTIONAL EVIDENCE SURFACE",
        "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED",
        "MATERIALIZATION · PASS",
        "PROMISE-SUBSPACE REVERSIBILITY · PASS",
        "OFF-PROMISE NEGATIVE CONTROL · REJECTED WITH WITNESS",
        "NAMED BACKEND · FALSE · TRANSPILATION / ROUTING · NOT RUN",
        "HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0 · PROVIDER CALLS · 0",
        "OPTIMIZATION PERFORMANCE · NOT TESTED · QUANTUM ADVANTAGE · NOT CLAIMED",
    )
    immutable_boundary_markers = (
        "RESEARCH_ONLY",
        "21,925,902",
        "1,158,046",
        "1,341,954",
        "2,500,000",
        "339",
        "107,520",
        "64 + 64 PASS",
        "BACKEND-AGNOSTIC ELEMENTARY CIRCUIT MATERIALIZATION",
    )
    materialization = expected_frames.get("materialization", pd.DataFrame())
    basis = expected_frames.get("basis", pd.DataFrame())
    checks: dict[str, bool] = {
        "sealed_artifact_raw_semantic_and_context_authentication": integrity.get("valid") is True and artifact_integrity is True,
        "registered_spec_and_175_path_parent_lineage": spec_integrity is True and parent_integrity is True,
        "normalizer_requires_explicit_four_way_authentication": healthy.get("authenticated") is True,
        "missing_implicit_and_rehashed_tamper_states_fail_closed": bool(invalid_states) and all(state.get("authenticated") is False for state in invalid_states.values()),
        "non_bands_projection_unchanged": projected_base == base_encoding,
        "bands_projection_exact_and_hardware_blocked": bool(
            projected_bands.get("v43_total_elementary_instructions") == 21_925_902
            and projected_bands.get("v43_maximum_materialized_cnot") == 1_158_046
            and projected_bands.get("v43_minimum_budget_margin_cnot") == 1_341_954
            and projected_bands.get("logical_qubits_min") == 339
            and projected_bands.get("promise_subspace_only") is True
            and projected_bands.get("off_promise_global_cleanup") == "REJECTED_WITH_WITNESS"
            and projected_bands.get("named_backend_selected") is False
            and projected_bands.get("backend_transpilation") == "NOT_RUN"
            and projected_bands.get("hardware_executable") is False
            and projected_bands.get("provider_calls") == 0
            and projected_bands.get("qpu_jobs_submitted") == 0
            and projected_bands.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": final_tabs[:3] + final_tabs[7:] == (
            "MISSION CONTROL", "REGIME / DENSITY", "QMC / RISK", "QUBO / ISING",
            "QUANTUM INFORMATION", "BENCHMARK PROTOCOL", "PHASE II / OOS", "PHASE III / QPU",
        ) and final_tabs[3:7] == EXPECTED_TABS[3:7],
        "v42_and_v43_markers_present_both_runs": all(marker in first_text and marker in final_text for marker in required_markers),
        "v43_machine_readable_hooks_present_exactly_once": all(first_text.count(hook) == 1 and final_text.count(hook) == 1 for hook in hooks),
        "all_five_exact_v43_ledgers_both_runs": bool(expected_frames) and all(_contains_frame(first_frames, frame) and _contains_frame(final_frames, frame) for frame in expected_frames.values()),
        "eight_seed_resource_rows_and_exact_extrema": bool(
            tuple(materialization.get("Seed", ())) == EXPECTED_SEEDS
            and tuple(materialization.get("CX", ())) == EXPECTED_CX
            and tuple(materialization.get("Peak qubits", ())) == EXPECTED_QUBITS
            and tuple(basis.get("Elementary opcode", ())) == EXPECTED_BASIS
        ),
        # A few labels are deliberately inherited from prior panels.  Every
        # matching control must be disabled; V4.3-specific labels remain
        # unique while inherited controls may appear more than once.
        "all_v43_governance_labels_present_and_disabled": all(
            bool(items := buttons(label)) and all(item.disabled is True for item in items)
            for label in governance_labels
        ),
        "seven_v43_downloads_present_exactly_once": all(len(downloads(label)) == 1 for label in download_labels),
        "legacy_provider_transpile_seal_controls_and_spies_stay_blocked": all(
            marker in first_text and marker in final_text
            for marker in ("PROVIDER SPY CALLS · 0", "TRANSPILE SPY CALLS · 0", "SEAL SPY CALLS · 0")
        ) and all(
            len(items := buttons(label)) == 1 and items[0].disabled is True
            for label in ("Discover accessible IBM QPUs", "Seal Phase-III equal-objective hardware protocol")
        ),
        "offline_harness_load_normalize_render_apply_contract_passed": "V4.3 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in first_text and "V4.3 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS" in final_text,
        "promise_backend_hardware_advantage_boundaries_visible": all(marker in final_text for marker in immutable_boundary_markers),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.3 UI verifier check count drifted: {len(checks)}")
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
            "v43_materialization_rows": len(materialization),
        },
        "errors": errors,
        "failed_checks": failed,
        "valid": not errors and not failed,
        "verifier": "QUANTUM LAB V4.3 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v43_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v43(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid") is True else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["EXPECTED_CHECK_COUNT", "EXPECTED_TABS", "verify_streamlit_surface_v43"]
