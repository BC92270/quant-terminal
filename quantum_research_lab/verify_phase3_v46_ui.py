"""Positive-rerun Streamlit verifier for the Quantum Lab V4.6 surface."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_CHECK_COUNT = 30
EXPECTED_OUTER_TABS = (
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
EXPECTED_V46_TABS = (
    "EXECUTIVE GATES",
    "SEED ROUTING",
    "NATIVE ISA",
    "TOPOLOGY",
    "PROVENANCE",
    "GOVERNANCE",
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(element: Any) -> str:
    try:
        value = getattr(element, "value", None)
    except (AttributeError, ValueError):
        value = None
    if value is not None:
        return str(value)
    proto = getattr(element, "proto", None)
    return str(getattr(proto, "label", getattr(element, "label", "")))


def _label(element: Any) -> str:
    label = getattr(element, "label", None)
    if label is not None:
        return str(label)
    return str(getattr(getattr(element, "proto", None), "label", ""))


def _snapshot(app: Any) -> tuple[str, tuple[str, ...]]:
    names = (
        "title", "header", "subheader", "markdown", "caption", "success",
        "warning", "error", "info", "metric", "dataframe", "button",
        "download_button", "code",
    )
    parts: list[str] = []
    for name in names:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_text(element) for element in elements)
    return "\n".join(parts), tuple(tab.label for tab in app.tabs)


def verify_streamlit_surface_v46(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v46_ui import (
            EXPECTED_ARTIFACT_SHA256,
            EXPECTED_NEXT_GATE,
            EXPECTED_OVERALL,
            EXPECTED_PRODUCTION,
            apply_v46_encoding_state,
            load_v46_ui_artifact,
            normalize_v46_artifact,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.6 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    artifact: dict[str, Any] | None
    try:
        artifact, auth = load_v46_ui_artifact()
        healthy = normalize_v46_artifact(artifact, integrity=auth.get("valid"))
        masked_missing = normalize_v46_artifact(None, integrity=True)
        masked_implicit = normalize_v46_artifact(artifact, integrity=None)
        masked_invalid = normalize_v46_artifact(artifact, integrity=False)
        base = {"encoding_status": "BASE", "hardware_executable": True}
        projected_base = apply_v46_encoding_state(base, regime="BASE", state=healthy, artifact=artifact)
        projected_bands = apply_v46_encoding_state(base, regime="BANDS", state=healthy, artifact=artifact)
    except Exception as exc:
        artifact, auth, healthy = None, {"valid": False, "checks": {}, "errors": [str(exc)]}, {}
        masked_missing = masked_implicit = masked_invalid = {}
        base = projected_base = projected_bands = {}
        errors.append(f"V4.6 UI contract load: {exc}")

    target = Path(app_path).resolve()
    try:
        app = AppTest.from_file(str(target), default_timeout=timeout_seconds)
        app.query_params["workspace"] = "quantum-research"
        app.run(timeout=timeout_seconds)
        first_exceptions = [str(element.value) for element in app.exception]
        first_text, first_tabs = _snapshot(app)
        app.run(timeout=timeout_seconds)
        final_exceptions = [str(element.value) for element in app.exception]
        final_text, final_tabs = _snapshot(app)
        buttons = list(app.button)
        downloads = list(app.get("download_button"))
        metrics = list(app.metric)
        frames = list(app.dataframe)
    except Exception as exc:
        errors.append(f"AppTest: {exc}")
        first_exceptions = final_exceptions = [str(exc)]
        first_text = final_text = ""
        first_tabs = final_tabs = ()
        buttons = downloads = metrics = frames = []

    button_labels = {_label(item) for item in buttons}
    download_labels = {_label(item) for item in downloads}
    metric_text = "\n".join(f"{_label(item)} {_text(item)}" for item in metrics)
    governance = {
        "Rebuild or mutate the sealed V4.6 artifact",
        "Change the frozen V4.5 lineage",
        "Replace the ordered Qiskit path oracle",
        "Override a preregistered resource threshold",
        "Treat compact native IR as a submitted circuit",
        "Treat structural depth as calibrated duration",
        "Read provider credentials or discover live backends",
        "Submit a simulator or QPU job",
        "Claim hardware readiness, utility or quantum advantage",
    }
    expected_downloads = {
        "Download V4.6 seed routing ledger CSV",
        "Download V4.6 native ISA ledger CSV",
        "Download sealed V4.6 artifact",
        "Download V4.6 preregistration",
        "Download V4.6 native translation contract",
    }
    checks: dict[str, bool] = {
        "artifact_available": isinstance(artifact, dict),
        "ui_authentication_30_of_30": auth.get("valid") is True and auth.get("check_count") == 30 and len(_mapping(auth.get("checks"))) == 30,
        "ui_authentication_no_failures": not auth.get("failed_checks") and not auth.get("errors"),
        "healthy_normalization_authenticated": healthy.get("authenticated") is True,
        "healthy_decision_exact": healthy.get("decision") == EXPECTED_OVERALL,
        "healthy_artifact_identity_exact": isinstance(artifact, dict) and artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256,
        "missing_state_masks_fail_closed": masked_missing.get("authenticated") is False and masked_missing.get("decision") == "MASKED_FAIL_CLOSED",
        "implicit_integrity_masks_fail_closed": masked_implicit.get("authenticated") is False and masked_implicit.get("hardware_executable") is False,
        "invalid_integrity_masks_fail_closed": masked_invalid.get("authenticated") is False and masked_invalid.get("hardware_executable") is False,
        "non_bands_projection_unchanged": projected_base == base,
        "bands_projection_hardware_false": projected_bands.get("hardware_executable") is False,
        "bands_projection_exact_maxima": projected_bands.get("logical_qubits_min") == 145 and projected_bands.get("native_cz_max") == 15527797 and projected_bands.get("routed_depth_max") == 24893376,
        "first_run_no_exception": not first_exceptions,
        "positive_rerun_no_exception": not final_exceptions,
        "twelve_outer_tabs_preserved": first_tabs[:12] == EXPECTED_OUTER_TABS and final_tabs[:12] == EXPECTED_OUTER_TABS,
        "six_v46_tabs_present": first_tabs[-6:] == EXPECTED_V46_TABS and final_tabs[-6:] == EXPECTED_V46_TABS,
        "tab_count_stable_across_rerun": len(first_tabs) == len(final_tabs) == 18,
        "v46_hero_present": "V4.6 · FULL-STREAM FAKEMARRAKESH ROUTING · AUTHENTICATED RESEARCH_ONLY" in final_text,
        "full_input_total_visible": "48,647,214" in final_text or "48.65M" in final_text,
        "aggregate_swap_total_visible": "33,259,620" in final_text,
        "aggregate_native_total_visible": "476,876,458" in final_text,
        "worst_cz_and_depth_visible": "15,527,797" in final_text and "24,893,376" in final_text,
        "hardware_boundary_visible": "hardware execution remains rejected" in final_text.lower() and "hardware_executable remains false" in final_text,
        "production_rejection_visible": EXPECTED_PRODUCTION in final_text,
        "next_gate_visible": EXPECTED_NEXT_GATE in final_text,
        "five_v46_metrics_present": len(metrics) >= 5 and "Routed seeds" in metric_text and "Worst ASAP depth" in metric_text,
        "five_v46_ledgers_present": len(frames) >= 5,
        "all_v46_downloads_present": expected_downloads.issubset(download_labels),
        "all_nine_governance_controls_disabled": governance.issubset(button_labels) and all(getattr(button, "disabled", False) for button in buttons if _label(button) in governance),
        "zero_call_harness_attestation_visible": "V4.6 OFFLINE APPTEST HARNESS · 30/30 AUTH" in final_text and "PROVIDER SPY CALLS · 0" in final_text and "QPU JOBS · 0" in final_text,
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.6 UI check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(str(item) for item in auth.get("errors") or [])
    return {
        "app_path": str(target),
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "first_run_exceptions": first_exceptions,
        "positive_rerun_exceptions": final_exceptions,
        "tab_count": len(final_tabs),
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.6 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v46_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v46(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_CHECK_COUNT", "EXPECTED_OUTER_TABS", "EXPECTED_V46_TABS", "verify_streamlit_surface_v46"]
