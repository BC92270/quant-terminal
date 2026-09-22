"""Positive-rerun Streamlit AppTest verifier for the V3.7 UI contract."""

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
    "V3.7 · REVERSIBLE INCREMENTAL EXPOSURE PROTOTYPE",
    "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED",
    "N40_REWRITE_ADMISSION_BLOCKED",
    "RESEARCH_ONLY · PROTOTYPE_ONLY · PROVIDER_FREE · HARDWARE_EXECUTABLE FALSE",
    "COHERENT TWO-LEVEL UPDATE · PASS",
    "SCRATCH CLEANUP · PASS",
    "DIFFERENTIAL PREDICATE + CACHE · PASS",
    "COMPLETE ORDERED LAYER · PASS",
    "N=40 PRODUCTION COMPILER · BLOCKED",
    "SELECTED-MODEL CNOT · NOT ESTIMATED",
    "V3.7 CLAIM BOUNDARY · PROTOTYPE-ONLY REVERSIBILITY",
    "HARDWARE EXECUTION · BLOCKED · ZERO JOBS",
    "V3.6 · STRUCTURAL COST ATTRIBUTION & REWRITE GATE",
    "V3.5 · NAMED-BACKEND TRANSPILATION CONTROL ROOM",
    "V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER",
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
    collections = (
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
    for name in collections:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_element_text(element) for element in elements)
    return "\n".join(parts), tuple(element.label for element in app.tabs)


def verify_streamlit_surface_v37(
    app_path: str | Path,
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Require a positive V3.7 state after a second complete Streamlit rerun."""

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
        from .phase3_v37_reversible_compiler import (
            canonical_json_sha256,
            load_v37_artifact,
            validate_v37_artifact,
        )
        from .phase3_v37_ui import apply_v37_encoding_state, normalize_v37_artifact

        sealed, sealed_integrity = load_v37_artifact()
        healthy_state = normalize_v37_artifact(
            sealed,
            artifact_integrity=sealed_integrity.get("valid") is True,
        )
        missing_state = normalize_v37_artifact(None, artifact_integrity=True)
        tampered = copy.deepcopy(sealed)
        tampered["compiler_evidence"]["basis_columns_checked"] = 1
        tampered["artifact_sha256"] = canonical_json_sha256(
            {key: value for key, value in tampered.items() if key != "artifact_sha256"}
        )
        tampered_integrity = validate_v37_artifact(tampered)
        tampered_state = normalize_v37_artifact(tampered, artifact_integrity=True)
        base_encoding = {"encoding_status": "BASE ORIGINAL", "hardware_executable": True}
        projected_base = apply_v37_encoding_state(
            base_encoding,
            regime="BASE",
            state=healthy_state,
            artifact=sealed,
        )
        projected_bands = apply_v37_encoding_state(
            base_encoding,
            regime="BANDS",
            state=healthy_state,
            artifact=sealed,
        )
    except Exception as exc:
        contract_errors.append(str(exc))
        sealed_integrity = {"valid": False}
        healthy_state = missing_state = tampered_state = {}
        tampered_integrity = {"valid": False}
        base_encoding = {}
        projected_base = projected_bands = {}

    target = Path(app_path).resolve()
    app = AppTest.from_file(str(target), default_timeout=timeout_seconds)
    app.query_params["workspace"] = "quantum-research"
    app.run(timeout=timeout_seconds)
    first_exceptions = [str(element.value) for element in app.exception]
    first_text, first_tabs = _snapshot(app)
    app.run(timeout=timeout_seconds)
    final_exceptions = [str(element.value) for element in app.exception]
    final_text, final_tabs = _snapshot(app)

    def buttons(label: str) -> list[Any]:
        return [
            button
            for button in app.button
            if str(getattr(button, "label", "")) == label
        ]

    scale_buttons = buttons("Scale prototype to authenticated N=40 contract")
    backend_buttons = buttons("Open named-backend transpilation lane")
    seal_buttons = buttons("Seal Phase-III equal-objective hardware protocol")
    downloads = [
        element
        for element in app.get("download_button")
        if str(getattr(element.proto, "label", ""))
        == "Download sealed V3.7 reversible-prototype artifact"
    ]

    checks: dict[str, bool] = {
        "normalizer_accepts_only_authenticated_sealed_artifact": bool(
            sealed_integrity.get("valid") is True
            and healthy_state.get("prototype_pass") is True
        ),
        "normalizer_missing_artifact_fails_closed": bool(
            missing_state.get("prototype_pass") is False
        ),
        "normalizer_rehashed_nested_tamper_fails_closed": bool(
            tampered_integrity.get("valid") is False
            and tampered_state.get("prototype_pass") is False
        ),
        "non_bands_encoding_is_not_contaminated": projected_base == base_encoding,
        "bands_encoding_receives_bounded_v37_state": bool(
            projected_bands.get("v37_prototype_decision")
            == "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
            and projected_bands.get("v37_production_admission")
            == "N40_REWRITE_ADMISSION_BLOCKED"
            and projected_bands.get("hardware_executable") is False
        ),
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "v37_markers_present_initially": all(
            marker in first_text for marker in REQUIRED_MARKERS
        ),
        "v37_markers_present_after_rerun": all(
            marker in final_text for marker in REQUIRED_MARKERS
        ),
        "artifact_authenticated_marker_present": "artifact AUTHENTICATED" in final_text,
        "prototype_fixture_scope_visible": (
            "V37_SYNTHETIC_EXACT_K_N4_K2_V1" in final_text
            and "REGISTERED SYNTHETIC N=4, K=2 FIXTURE" in final_text.upper()
        ),
        "logical_ledger_not_misrepresented_as_cnot": (
            "elementary decomposition not implemented" in final_text.lower()
            and "NOT ESTIMATED" in final_text
        ),
        "n40_scale_gate_present_once": len(scale_buttons) == 1,
        "n40_scale_gate_disabled": len(scale_buttons) == 1
        and getattr(scale_buttons[0], "disabled", None) is True,
        "named_backend_lane_present_once": len(backend_buttons) == 1,
        "named_backend_lane_disabled": len(backend_buttons) == 1
        and getattr(backend_buttons[0], "disabled", None) is True,
        "hardware_seal_present_once": len(seal_buttons) == 1,
        "hardware_seal_disabled": len(seal_buttons) == 1
        and getattr(seal_buttons[0], "disabled", None) is True,
        "sealed_v37_artifact_download_present_once": len(downloads) == 1,
        "offline_no_provider_invocation_boundary": (
            "V3.7 OFFLINE APPTEST HARNESS" in final_text
            and "NETWORK/PROVIDER ACTIONS NOT INVOKED" in final_text
            and "OFFLINE MARKET/PROVIDER STUBS EXCLUDED FROM SCIENTIFIC EVIDENCE"
            in final_text
        ),
        "hardware_zero_job_boundary": (
            "HARDWARE EXECUTION · BLOCKED · ZERO JOBS" in final_text
            and "provider calls 0" in final_text
            and "qpu submission disabled" in final_text
        ),
        "advantage_not_claimed": "quantum advantage" in final_text.lower()
        and "NOT CLAIMED" in final_text,
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "failed_checks": failed,
        "first_exception_messages": first_exceptions,
        "final_exception_messages": final_exceptions,
        "contract_errors": contract_errors,
        "tab_count": len(final_tabs),
        "tabs": list(final_tabs),
        "valid": not failed and not contract_errors,
        "verifier": "QUANTUM LAB V3.7 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.7 UI.")
    parser.add_argument(
        "app",
        nargs="?",
        type=Path,
        default=Path("app_v37_offline_harness.py"),
    )
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v37(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_TABS", "REQUIRED_MARKERS", "verify_streamlit_surface_v37"]
