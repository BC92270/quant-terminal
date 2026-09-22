"""Positive-rerun Streamlit verifier for the Quantum Lab V4.8 surface."""

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
EXPECTED_V48_TABS = (
    "SNAPSHOT REGISTRY",
    "ROBUSTNESS",
    "ARCHITECTURE / CZ",
    "FRONTIER",
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


def verify_streamlit_surface_v48(
    app_path: str | Path,
    *,
    timeout_seconds: float = 600.0,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        from streamlit.testing.v1 import AppTest
        from .phase3_v48_ui import (
            ARCHITECTURE_ORACLE_FILENAME,
            CATALOG_FILENAME,
            EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256,
            EXPECTED_ARTIFACT_RAW_SHA256,
            EXPECTED_ARTIFACT_SHA256,
            EXPECTED_CATALOG_RAW_SHA256,
            EXPECTED_CHECKER_RAW_SHA256,
            EXPECTED_INDEPENDENT_CHECK_COUNT,
            EXPECTED_MODEL_RAW_SHA256,
            EXPECTED_MULTI_SNAPSHOT,
            EXPECTED_NEXT_GATE,
            EXPECTED_OVERALL,
            EXPECTED_PRODUCTION,
            EXPECTED_SNAPSHOTS_RAW_SHA256,
            EXPECTED_SOURCE_RAW_SHA256,
            EXPECTED_SPEC_RAW_SHA256,
            EXPECTED_UI_AUTH_CHECK_COUNT,
            MODEL_FILENAME,
            SNAPSHOTS_FILENAME,
            SPEC_FILENAME,
            apply_v48_encoding_state,
            default_v48_ui_artifact_path,
            load_v48_ui_artifact,
            normalize_v48_artifact,
        )
    except Exception as exc:
        return {
            "app_path": str(Path(app_path).resolve()),
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["dependencies_available"],
            "valid": False,
            "verifier": "QUANTUM LAB V4.8 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
        }

    artifact: dict[str, Any] | None
    try:
        artifact, auth = load_v48_ui_artifact()
        healthy = normalize_v48_artifact(artifact, integrity=auth.get("valid"))
        masked_missing = normalize_v48_artifact(None, integrity=True)
        masked_implicit = normalize_v48_artifact(artifact, integrity=None)
        masked_invalid = normalize_v48_artifact(artifact, integrity=False)
        base = {"encoding_status": "BASE", "hardware_executable": True}
        projected_base = apply_v48_encoding_state(
            base, regime="BASE", state=healthy, artifact=artifact
        )
        projected_bands = apply_v48_encoding_state(
            base, regime="BANDS", state=healthy, artifact=artifact
        )
    except Exception as exc:
        artifact, auth, healthy = None, {"valid": False, "checks": {}, "errors": [str(exc)]}, {}
        masked_missing = masked_implicit = masked_invalid = {}
        base = projected_base = projected_bands = {}
        errors.append(f"V4.8 UI contract load: {exc}")

    independent = _mapping(auth.get("independent_checker"))
    root = Path(__file__).resolve().parents[1]
    exact_download_sources = {
        "artifact": _exact_raw_file(default_v48_ui_artifact_path(), EXPECTED_ARTIFACT_RAW_SHA256),
        "spec": _exact_raw_file(root / "quantum_research_lab" / SPEC_FILENAME, EXPECTED_SPEC_RAW_SHA256),
        "catalog": _exact_raw_file(
            root / "quantum_research_lab" / CATALOG_FILENAME,
            EXPECTED_CATALOG_RAW_SHA256,
        ),
        "snapshots": _exact_raw_file(
            root / "quantum_research_lab" / SNAPSHOTS_FILENAME,
            EXPECTED_SNAPSHOTS_RAW_SHA256,
        ),
        "architecture_oracle": _exact_raw_file(
            root / "quantum_research_lab" / ARCHITECTURE_ORACLE_FILENAME,
            EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256,
        ),
        "model": _exact_raw_file(
            root / "quantum_research_lab" / MODEL_FILENAME,
            EXPECTED_MODEL_RAW_SHA256,
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
        "Rebuild or mutate the sealed V4.8 artifact",
        "Count a copied snapshot as a new calibration epoch",
        "Substitute synthetic stress data for an authentic snapshot",
        "Relabel the historical development snapshot as a holdout",
        "Change the preregistered architecture after observing results",
        "Interpret additive error mass as circuit fidelity",
        "Interpret structural or integer-dt depth as wall-clock runtime",
        "Read provider credentials or discover a live backend",
        "Submit a simulator, backend, or QPU job",
        "Claim hardware readiness, utility, or quantum advantage",
    }
    expected_downloads = {
        "Download sealed V4.8 artifact",
        "Download V4.8 protocol",
        "Download snapshot registry",
        "Download normalized snapshot cohort",
        "Download architecture candidate oracle",
        "Download robustness cost model",
    }
    lower_text = final_text.lower()
    checks: dict[str, bool] = {
        "artifact_available": isinstance(artifact, dict),
        "ui_authentication_24_of_24": auth.get("valid") is True
        and auth.get("check_count") == EXPECTED_UI_AUTH_CHECK_COUNT == 24
        and len(_mapping(auth.get("checks"))) == 24,
        "ui_authentication_no_failures": not auth.get("failed_checks") and not auth.get("errors"),
        "independent_checker_65_of_65": independent.get("valid") is True
        and independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT == 65,
        "independent_checker_no_failures": not independent.get("failed_checks")
        and not independent.get("errors"),
        "healthy_normalization_authenticated": healthy.get("authenticated") is True,
        "healthy_decision_exact": healthy.get("decision") == EXPECTED_OVERALL,
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
        "bands_projection_artifact_exact": projected_bands.get("v48_artifact_sha256")
        == EXPECTED_ARTIFACT_SHA256,
        "bands_projection_decision_exact": projected_bands.get("v48_dated_properties_status")
        == EXPECTED_OVERALL,
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
        "six_v48_tabs_present": first_tabs[-6:] == EXPECTED_V48_TABS
        and final_tabs[-6:] == EXPECTED_V48_TABS,
        "tab_count_stable_across_rerun": len(first_tabs) == len(final_tabs) == 18,
        "v47_console_replaced": not any(
            label in final_tabs
            for label in ("PROPERTIES", "DURATION MODEL", "ERROR MASS", "OPTIMIZATION / PARETO")
        ),
        "v48_hero_present": "ARCHITECTURE REDUCTION & SNAPSHOT GOVERNANCE" in final_text.upper()
        and "AUTHENTICATED · RESEARCH_ONLY · EXACT STREAMS 8/8" in final_text,
        "single_snapshot_boundary_visible": "Authentic epochs" in metric_text
        and "1 / 3" in metric_text
        and "only one distinct authentic epoch" in lower_text,
        "architecture_reduction_metrics_visible": "CX total" in metric_text
        and "6,474,096" in metric_text
        and "BasicSwap CZ" in metric_text
        and "59,565,732" in metric_text,
        "equivalence_evidence_visible": "Equivalence" in metric_text
        and "28,240" in metric_text,
        "multi_snapshot_gate_visible": EXPECTED_MULTI_SNAPSHOT in final_text
        and "synthetic substitutions" in lower_text,
        "frontier_screens_visible": "optimistic duration" in lower_text
        and "error screen" in lower_text
        and "duration screen" in lower_text,
        "routing_reduction_visible": "zero isa or coupling violations" in lower_text
        and "cx reduction" in lower_text
        and "cz reduction" in lower_text,
        "next_gate_visible": EXPECTED_NEXT_GATE in final_text,
        "production_rejection_visible": EXPECTED_PRODUCTION in final_text,
        "authentication_counters_visible": "24/24 AUTH" in final_text
        and "65/65 INDEPENDENT" in final_text,
        "v48_metrics_present": len(metrics) >= 6
        and "Exact streams" in metric_text
        and "Max depth" in metric_text,
        "v48_ledgers_present": len(frames) >= 5,
        "all_six_v48_downloads_present": expected_downloads.issubset(download_labels),
        "all_ten_governance_controls_disabled": governance.issubset(button_labels)
        and all(
            getattr(button, "disabled", False)
            for button in buttons
            if _label(button) in governance
        ),
        "zero_call_harness_attestation_visible": "V4.8 OFFLINE APPTEST HARNESS · 24/24 AUTH · 65/65 INDEPENDENT" in final_text
        and "PROVIDER SPY CALLS · 0" in final_text
        and "TRANSPILE SPY CALLS · 0" in final_text
        and "SEAL SPY CALLS · 0" in final_text
        and "NETWORK SPY CALLS · 0" in final_text
        and "ENV/CREDENTIAL SPY READS · 0" in final_text
        and "QPU JOBS · 0" in final_text,
        "exact_download_attestation_visible": "DOWNLOAD RAW IDENTITIES 6/6 PASS" in final_text,
        "current_backend_inference_denied": "not current calibration" in lower_text
        and "current-provider calls" in lower_text,
        "hardware_boundary_visible": "hardware" in lower_text
        and "blocked" in lower_text
        and "research_only" in lower_text,
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.8 UI check count drifted: {len(checks)}")
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
        "verifier": "QUANTUM LAB V4.8 STREAMLIT POSITIVE-RERUN VERIFIER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app_path", nargs="?", default="app_v48_offline_harness.py")
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v48(args.app_path, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_OUTER_TABS",
    "EXPECTED_V48_TABS",
    "verify_streamlit_surface_v48",
]
