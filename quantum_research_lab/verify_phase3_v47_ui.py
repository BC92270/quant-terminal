"""Positive-rerun Streamlit verifier for the Quantum Lab V4.7 surface."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_CHECK_COUNT = 42
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
EXPECTED_V47_TABS = (
    "PROPERTIES",
    "DURATION MODEL",
    "ERROR MASS",
    "OPTIMIZATION / PARETO",
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
        "code",
    )
    parts: list[str] = []
    for name in names:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        parts.extend(_text(element) for element in elements)
    return "\n".join(parts), tuple(tab.label for tab in app.tabs)


def _exact_raw_file(path: Path, expected_sha256: str) -> bool:
    try:
        return bool(
            len(expected_sha256) == 64
            and path.is_file()
            and not path.is_symlink()
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected_sha256
        )
    except OSError:
        return False


def verify_streamlit_surface_v47(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v47_ui import (
            EXPECTED_ARTIFACT_RAW_SHA256,
            EXPECTED_ARTIFACT_SHA256,
            EXPECTED_CHECKER_RAW_SHA256,
            EXPECTED_INDEPENDENT_CHECK_COUNT,
            EXPECTED_MODEL_RAW_SHA256,
            EXPECTED_NEXT_GATE,
            EXPECTED_OVERALL_REJECTION,
            EXPECTED_PATH_ORACLE_RAW_SHA256,
            EXPECTED_PRODUCTION,
            EXPECTED_PROPERTIES_RAW_SHA256,
            EXPECTED_RAW_PROPERTIES_SHA256,
            EXPECTED_SOURCE_RAW_SHA256,
            EXPECTED_SPEC_RAW_SHA256,
            EXPECTED_UI_AUTH_CHECK_COUNT,
            MODEL_FILENAME,
            PATH_ORACLE_FILENAME,
            PROPERTIES_FILENAME,
            RAW_PROPERTIES_FILENAME,
            SPEC_FILENAME,
            apply_v47_encoding_state,
            default_v47_ui_artifact_path,
            load_v47_ui_artifact,
            normalize_v47_artifact,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.7 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    artifact: dict[str, Any] | None
    try:
        artifact, auth = load_v47_ui_artifact()
        healthy = normalize_v47_artifact(artifact, integrity=auth.get("valid"))
        masked_missing = normalize_v47_artifact(None, integrity=True)
        masked_implicit = normalize_v47_artifact(artifact, integrity=None)
        masked_invalid = normalize_v47_artifact(artifact, integrity=False)
        base = {"encoding_status": "BASE", "hardware_executable": True}
        projected_base = apply_v47_encoding_state(
            base, regime="BASE", state=healthy, artifact=artifact
        )
        projected_bands = apply_v47_encoding_state(
            base, regime="BANDS", state=healthy, artifact=artifact
        )
    except Exception as exc:
        artifact, auth, healthy = None, {"valid": False, "checks": {}, "errors": [str(exc)]}, {}
        masked_missing = masked_implicit = masked_invalid = {}
        base = projected_base = projected_bands = {}
        errors.append(f"V4.7 UI contract load: {exc}")

    independent = _mapping(auth.get("independent_checker"))
    root = Path(__file__).resolve().parents[1]
    exact_download_sources = {
        "artifact": _exact_raw_file(default_v47_ui_artifact_path(), EXPECTED_ARTIFACT_RAW_SHA256),
        "spec": _exact_raw_file(root / "quantum_research_lab" / SPEC_FILENAME, EXPECTED_SPEC_RAW_SHA256),
        "properties": _exact_raw_file(
            root / "quantum_research_lab" / PROPERTIES_FILENAME,
            EXPECTED_PROPERTIES_RAW_SHA256,
        ),
        "model": _exact_raw_file(
            root / "quantum_research_lab" / MODEL_FILENAME,
            EXPECTED_MODEL_RAW_SHA256,
        ),
        "path_oracle": _exact_raw_file(
            root / "quantum_research_lab" / PATH_ORACLE_FILENAME,
            EXPECTED_PATH_ORACLE_RAW_SHA256,
        ),
        "raw_properties": _exact_raw_file(
            root / "quantum_research_lab" / RAW_PROPERTIES_FILENAME,
            EXPECTED_RAW_PROPERTIES_SHA256,
        ),
    }

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
        "Rebuild or mutate the sealed V4.7 artifact",
        "Replace the exact V4.6 baseline commitments",
        "Select a post-result routing candidate",
        "Impute a missing property or reverse a directed CZ tuple",
        "Interpret additive error mass as fidelity or success probability",
        "Interpret integer-dt ASAP makespan as pulse or wall-clock runtime",
        "Treat dated fake-backend properties as current calibration",
        "Read provider credentials or discover live backends",
        "Submit a simulator, backend, or QPU job",
        "Claim hardware readiness, utility, or quantum advantage",
    }
    expected_downloads = {
        "Download sealed V4.7 artifact",
        "Download V4.7 preregistration",
        "Download normalized dated properties",
        "Download duration/error model contract",
        "Download fault-excluded path oracle",
        "Download raw dated properties",
    }
    lower_text = final_text.lower()
    checks: dict[str, bool] = {
        "artifact_available": isinstance(artifact, dict),
        "ui_authentication_21_of_21": auth.get("valid") is True
        and auth.get("check_count") == EXPECTED_UI_AUTH_CHECK_COUNT == 21
        and len(_mapping(auth.get("checks"))) == 21,
        "ui_authentication_no_failures": not auth.get("failed_checks") and not auth.get("errors"),
        "independent_checker_51_of_51": independent.get("valid") is True
        and independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT == 51,
        "independent_checker_no_failures": not independent.get("failed_checks")
        and not independent.get("errors"),
        "healthy_normalization_authenticated": healthy.get("authenticated") is True,
        "healthy_decision_exact": healthy.get("decision") == EXPECTED_OVERALL_REJECTION,
        "healthy_artifact_identity_exact": isinstance(artifact, dict)
        and artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256,
        "healthy_boundary_exact": healthy.get("hardware_executable") is False
        and healthy.get("research_classification") == "RESEARCH_ONLY",
        "missing_state_masks_fail_closed": masked_missing.get("authenticated") is False
        and masked_missing.get("decision") == "MASKED_FAIL_CLOSED",
        "implicit_integrity_masks_fail_closed": masked_implicit.get("authenticated") is False
        and masked_implicit.get("hardware_executable") is False,
        "invalid_integrity_masks_fail_closed": masked_invalid.get("authenticated") is False
        and masked_invalid.get("hardware_executable") is False,
        "non_bands_projection_unchanged": projected_base == base,
        "bands_projection_hardware_false": projected_bands.get("hardware_executable") is False
        and projected_bands.get("research_classification") == "RESEARCH_ONLY",
        "bands_projection_artifact_exact": projected_bands.get("v47_artifact_sha256")
        == EXPECTED_ARTIFACT_SHA256,
        "bands_projection_decision_exact": projected_bands.get("v47_dated_properties_status")
        == EXPECTED_OVERALL_REJECTION,
        "six_download_sources_raw_exact": len(exact_download_sources) == 6
        and all(exact_download_sources.values()),
        "post_result_source_pins_are_sha256": all(
            len(value) == 64
            for value in (
                EXPECTED_ARTIFACT_RAW_SHA256,
                EXPECTED_ARTIFACT_SHA256,
                EXPECTED_SOURCE_RAW_SHA256,
                EXPECTED_CHECKER_RAW_SHA256,
            )
        ),
        "first_run_no_exception": not first_exceptions,
        "positive_rerun_no_exception": not final_exceptions,
        "twelve_outer_tabs_preserved": first_tabs[:12] == EXPECTED_OUTER_TABS
        and final_tabs[:12] == EXPECTED_OUTER_TABS,
        "six_v47_tabs_present": first_tabs[-6:] == EXPECTED_V47_TABS
        and final_tabs[-6:] == EXPECTED_V47_TABS,
        "tab_count_stable_across_rerun": len(first_tabs) == len(final_tabs) == 18,
        "v47_hero_present": "V4.7 · DATED PROPERTIES" in final_text.upper()
        and "AUTHENTICATED · RESEARCH_ONLY · HISTORICAL SNAPSHOT" in final_text,
        "historical_snapshot_visible": "2025-02-26" in final_text
        and "historical" in lower_text
        and "not current" in lower_text,
        "property_census_visible": "Native tuples" in metric_text
        and "976" in metric_text
        and "Healthy component" in metric_text
        and "153" in metric_text,
        "duration_model_boundary_visible": "integer-dt ASAP" in final_text
        and "not a pulse schedule" in lower_text,
        "error_mass_non_fidelity_visible": "NON-FIDELITY METRIC" in final_text
        and "not fidelity, success probability" in lower_text,
        "unit_error_screen_visible": "unit-error" in lower_text,
        "architecture_screen_visible": "Architecture screen" in metric_text
        and "optimistic architecture screen" in lower_text,
        "candidate_scope_visible": "Single preregistered candidate" in final_text
        and "FAULT_EXCLUDED_SHORTEST_HOP_RELIABILITY_TIEBREAK_V1" in final_text,
        "hardware_boundary_visible": "hardware_executable remains false" in final_text
        and "hardware" in lower_text
        and "blocked" in lower_text,
        "current_backend_inference_denied": "Neither result describes a current backend" in final_text
        and "current calibration" in lower_text,
        "production_rejection_visible": EXPECTED_PRODUCTION in final_text,
        "next_gate_visible": EXPECTED_NEXT_GATE in final_text,
        "authentication_counters_visible": "21/21 UI authentication gates" in final_text
        and "51/51 independent scientific checks" in final_text,
        "v47_metrics_present": len(metrics) >= 13
        and "Baseline unit-error uses" in metric_text
        and "Candidate unit-error uses" in metric_text,
        "v47_ledgers_present": len(frames) >= 8,
        "all_six_v47_downloads_present": expected_downloads.issubset(download_labels),
        "all_ten_governance_controls_disabled": governance.issubset(button_labels)
        and all(
            getattr(button, "disabled", False)
            for button in buttons
            if _label(button) in governance
        ),
        "zero_call_harness_attestation_visible": "V4.7 OFFLINE APPTEST HARNESS · 21/21 AUTH · 51/51 INDEPENDENT" in final_text
        and "PROVIDER SPY CALLS · 0" in final_text
        and "TRANSPILE SPY CALLS · 0" in final_text
        and "SEAL SPY CALLS · 0" in final_text
        and "NETWORK SPY CALLS · 0" in final_text
        and "ENV/CREDENTIAL SPY READS · 0" in final_text
        and "QPU JOBS · 0" in final_text,
        "exact_download_attestation_visible": "DOWNLOAD RAW IDENTITIES 6/6 PASS" in final_text,
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.7 UI check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(str(item) for item in auth.get("errors") or [])
    return {
        "app_path": str(target),
        "check_count": len(checks),
        "checks": checks,
        "download_source_identities": exact_download_sources,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "first_run_exceptions": first_exceptions,
        "positive_rerun_exceptions": final_exceptions,
        "tab_count": len(final_tabs),
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.7 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v47_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v47(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_OUTER_TABS",
    "EXPECTED_V47_TABS",
    "verify_streamlit_surface_v47",
]
