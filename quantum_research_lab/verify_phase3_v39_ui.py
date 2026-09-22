"""Positive-rerun Streamlit AppTest verifier for the V3.9 UI contract."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Sequence


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

REQUIRED_MARKERS = (
    "V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER",
    "V3.5 · NAMED-BACKEND TRANSPILATION CONTROL ROOM",
    "V3.6 · STRUCTURAL COST ATTRIBUTION & REWRITE GATE",
    "V3.7 · REVERSIBLE INCREMENTAL EXPOSURE PROTOTYPE",
    "V3.8 · ELEMENTARY DECOMPOSITION & N=40 RESOURCE ADMISSION",
    "V3.9 · SCALABLE N40 REVERSIBLE IR & SELECTED-MODEL ADMISSION",
    "N=40 · K=10 · BANDS · 7 HARD CONSTRAINTS · 8 FROZEN SEEDS",
    "STATIC DEAD-EDGE CERTIFICATE",
    "ORDERED 780-EDGE LAYER",
    "POST-OBSERVATION MODEL SWITCHING · PROHIBITED",
    "N40 REVERSIBLE IR · PASS",
    "SELECTED-MODEL RESOURCE SCREEN · REJECTED",
    "GLOBAL FEASIBLE-GRAPH CONNECTIVITY · INDETERMINATE",
    "GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE",
    "V3.9 CLAIM BOUNDARY · N40 REVERSIBLE IR AND RESOURCE LEDGER ONLY",
    "BACKEND TRANSPILATION · NOT RUN",
    "HARDWARE EXECUTION · BLOCKED · ZERO JOBS",
    "QUANTUM ADVANTAGE · NOT CLAIMED",
)

SEED_LEDGER_COLUMNS = (
    "Seed",
    "Instance",
    "Parent",
    "Range widths",
    "Reversible IR",
    "Dead-edge certificate",
    "Live rotations",
    "Ordered positions",
    "Elementary",
    "Template equivalence",
    "Clean scratch",
    "Coherent pair action",
    "Selected CNOT",
    "Budget margin",
    "2.5M gate",
    "Decision",
)


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


def _snapshot(app: Any) -> tuple[str, tuple[str, ...]]:
    names = (
        "title", "header", "subheader", "markdown", "caption", "success",
        "warning", "error", "info", "metric", "dataframe", "button",
        "download_button",
    )
    parts: list[str] = []
    for name in names:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_element_text(element) for element in elements)
    return "\n".join(parts), tuple(element.label for element in app.tabs)


def _dataframe_schemas(app: Any) -> list[tuple[tuple[str, ...], int]]:
    schemas: list[tuple[tuple[str, ...], int]] = []
    for element in app.dataframe:
        try:
            value = element.value
            schemas.append((tuple(str(column) for column in value.columns), len(value)))
        except Exception:
            continue
    return schemas


def verify_streamlit_surface_v39(app_path: str | Path, *, timeout_seconds: float = 180.0) -> dict[str, Any]:
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as exc:  # pragma: no cover
        return {"checks": {"streamlit_testing_available": False}, "errors": [str(exc)], "failed_checks": ["streamlit_testing_available"], "valid": False}

    contract_errors: list[str] = []
    try:
        from .phase3_v39_scalable_reversible_ir import canonical_json_sha256, load_v39_spec
        from .phase3_v39_ui import apply_v39_encoding_state, load_v39_ui_artifact, normalize_v39_artifact

        sealed, integrity = load_v39_ui_artifact()
        spec = load_v39_spec()
        healthy = normalize_v39_artifact(
            sealed,
            artifact_integrity=integrity.get("valid") is True,
            spec_integrity=True,
            parent_integrity=True,
        )
        missing = normalize_v39_artifact(None, artifact_integrity=True, spec_integrity=True, parent_integrity=True)
        implicit = normalize_v39_artifact(sealed, artifact_integrity=None, spec_integrity=True, parent_integrity=True)
        bad_spec = normalize_v39_artifact(sealed, artifact_integrity=True, spec_integrity=False, parent_integrity=True)
        bad_parent = normalize_v39_artifact(sealed, artifact_integrity=True, spec_integrity=True, parent_integrity=False)
        tampered = copy.deepcopy(sealed)
        tampered["seed_rows"][0]["resources"]["selected_model_cnot"] -= 1
        tampered["artifact_sha256"] = canonical_json_sha256({key: value for key, value in tampered.items() if key != "artifact_sha256"})
        tampered_state = normalize_v39_artifact(tampered, artifact_integrity=True, spec_integrity=True, parent_integrity=True)
        base = {"encoding_status": "BASE ORIGINAL", "hardware_executable": True}
        projected_base = apply_v39_encoding_state(base, regime="BASE", state=healthy, artifact=sealed)
        projected_bands = apply_v39_encoding_state(base, regime="BANDS", state=healthy, artifact=sealed)
    except Exception as exc:
        contract_errors.append(str(exc))
        integrity = {"valid": False}
        healthy = missing = implicit = bad_spec = bad_parent = tampered_state = {}
        base = projected_base = projected_bands = {}
        spec = {}

    target = Path(app_path).resolve()
    app = AppTest.from_file(str(target), default_timeout=timeout_seconds)
    app.query_params["workspace"] = "quantum-research"
    app.run(timeout=timeout_seconds)
    first_exceptions = [str(element.value) for element in app.exception]
    first_text, first_tabs = _snapshot(app)
    app.run(timeout=timeout_seconds)
    final_exceptions = [str(element.value) for element in app.exception]
    final_text, final_tabs = _snapshot(app)
    schemas = _dataframe_schemas(app)

    def buttons(label: str) -> list[Any]:
        return [button for button in app.button if str(getattr(button, "label", "")) == label]

    def downloads(label: str) -> list[Any]:
        return [element for element in app.get("download_button") if str(getattr(element.proto, "label", "")) == label]

    sensitive_labels = (
        "Recompute V3.9 scalable reversible IR",
        "Override frozen arithmetic/register model",
        "Override 2,500,000 CNOT admission gate",
        "Open named-backend audit successor lane",
        "Discover accessible IBM QPUs",
        "Seal Phase-III equal-objective hardware protocol",
    )
    sensitive = {label: buttons(label) for label in sensitive_labels}
    hook_values = (
        'data-qv39-surface="scalable-ir-admission"',
        'data-qv39-release="3.9"',
        'data-qv39-role="overall-decision"',
        'data-qv39-metric="artifact-auth"',
        'data-qv39-metric="ir-coverage"',
        'data-qv39-metric="selected-cnot"',
        'data-qv39-metric="budget-gate"',
        'data-qv39-connectivity="INDETERMINATE"',
        'data-qv39-hardware="false"',
        'data-qv39-provider-calls="0"',
    )
    checks: dict[str, bool] = {
        "normalizer_accepts_only_explicitly_authenticated_seal": bool(integrity.get("valid") is True and healthy.get("authenticated") is True),
        "missing_none_and_implicit_integrity_fail_closed": all(state.get("authenticated") is False for state in (missing, implicit, bad_spec, bad_parent)),
        "nested_rehashed_tamper_fails_closed": tampered_state.get("authenticated") is False,
        "invalid_states_mask_all_numeric_ledgers": all(not state.get("seed_rows") and state.get("maximum_cnot") is None for state in (missing, implicit, tampered_state)),
        "non_bands_projection_unchanged": projected_base == base,
        "bands_projection_bounded_and_non_executable": bool(
            projected_bands.get("v39_reversible_ir_decision") == "N40_REVERSIBLE_IR_PASSED"
            and projected_bands.get("v39_budget_decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            and projected_bands.get("v39_complete_global_connectivity") == "INDETERMINATE"
            and projected_bands.get("hardware_executable") is False
        ),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "outer_8_plus_inner_4_tab_hierarchy_exact": final_tabs[:3] + final_tabs[7:] == (
            "MISSION CONTROL", "REGIME / DENSITY", "QMC / RISK", "QUBO / ISING", "QUANTUM INFORMATION", "BENCHMARK PROTOCOL", "PHASE II / OOS", "PHASE III / QPU"
        ) and final_tabs[3:7] == EXPECTED_TABS[3:7],
        "v39_and_predecessor_markers_present_initially": all(marker in first_text for marker in REQUIRED_MARKERS),
        "v39_and_predecessor_markers_present_after_rerun": all(marker in final_text for marker in REQUIRED_MARKERS),
        "stable_dom_hooks_unique": all(final_text.count(hook) == 1 for hook in hook_values),
        "artifact_authenticated_with_exact_decision": "Artifact AUTHENTICATED" in final_text and "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED" in final_text,
        "seed_ledger_schema_and_row_count_exact": (SEED_LEDGER_COLUMNS, 8) in schemas,
        "register_ledger_schema_and_row_count_exact": any(schema[1] == 56 and schema[0][:4] == ("Seed", "Register", "Width", "Signed") for schema in schemas),
        "all_sensitive_controls_present_once_and_disabled": all(len(items) == 1 and getattr(items[0], "disabled", None) is True for items in sensitive.values()),
        "artifact_spec_and_csv_downloads_present_once": all(
            len(downloads(label)) == 1
            for label in (
                "Download sealed V3.9 scalable-IR artifact",
                "Download V3.9 scalable-IR specification",
                "Download V3.9 eight-seed ledger CSV",
            )
        ),
        "all_eight_frozen_seeds_visible": all(str(seed) in final_text for seed in (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)),
        "exact_resource_rejection_visible": "781,332,180" in final_text and "-778,832,180" in final_text and "2,500,000" in final_text,
        "provider_spy_proves_zero_calls_on_both_reruns": "V3.9 OFFLINE APPTEST HARNESS · PROVIDER SPY CALLS · 0" in first_text and "V3.9 OFFLINE APPTEST HARNESS · PROVIDER SPY CALLS · 0" in final_text,
        "hardware_and_advantage_boundaries_visible": "HARDWARE EXECUTION · BLOCKED · ZERO JOBS" in final_text and "QUANTUM ADVANTAGE · NOT CLAIMED" in final_text,
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "failed_checks": failed,
        "first_exception_messages": first_exceptions,
        "final_exception_messages": final_exceptions,
        "contract_errors": contract_errors,
        "tab_count": len(final_tabs),
        "tabs": list(final_tabs),
        "dataframe_schemas": [{"columns": list(columns), "rows": rows} for columns, rows in schemas],
        "valid": not failed and not contract_errors,
        "verifier": "QUANTUM LAB V3.9 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.9 UI.")
    parser.add_argument("app", nargs="?", type=Path, default=Path("app_v39_offline_harness.py"))
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v39(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_TABS", "REQUIRED_MARKERS", "SEED_LEDGER_COLUMNS", "verify_streamlit_surface_v39"]
