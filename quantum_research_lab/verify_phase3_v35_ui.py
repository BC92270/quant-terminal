"""Streamlit AppTest verifier for the V3.5 institutional evidence contract."""

from __future__ import annotations

import argparse
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


def verify_streamlit_surface_v35(
    app_path: str | Path,
    *,
    timeout_seconds: float = 120.0,
    expected_evidence_mode: str | None = None,
    expected_backend_class: str | None = None,
    expected_circuit_stage: str | None = None,
) -> dict[str, Any]:
    """Verify wording and non-regression; optional expectations bind a run."""

    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as exc:  # pragma: no cover
        return {
            "checks": {"streamlit_testing_available": False},
            "errors": [str(exc)],
            "failed_checks": ["streamlit_testing_available"],
            "valid": False,
        }

    target = Path(app_path).resolve()
    app = AppTest.from_file(str(target), default_timeout=timeout_seconds)
    app.query_params["workspace"] = "quantum-research"
    app.run(timeout=timeout_seconds)
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
    text_parts: list[str] = []
    for name in collections:
        elements = app.get(name) if name == "download_button" else getattr(app, name, ())
        text_parts.extend(_element_text(element) for element in elements)
    text_blob = "\n".join(text_parts)
    tabs = tuple(element.label for element in app.tabs)

    checks = {
        "no_uncaught_streamlit_exception": len(app.exception) == 0,
        "legacy_12_tab_contract_preserved": tabs == EXPECTED_TABS,
        "v35_control_room_present": "V3.5 · NAMED-BACKEND TRANSPILATION CONTROL ROOM" in text_blob,
        "snapshot_live_axis_present": "SNAPSHOT / LIVE" in text_blob and "EVIDENCE MODE ·" in text_blob,
        "named_fake_axis_present": "NAMED / FAKE" in text_blob and "BACKEND CLASS ·" in text_blob,
        "provider_neutral_target_ledger_present": "Provider-neutral vs target-transpiled/routed gate ledger" in text_blob,
        "pre_transpile_provider_limit_gate_present": "PRE-TRANSPILE PROVIDER LIMIT ·" in text_blob
        and "independent of backend-native transpilation" in text_blob,
        "circuit_stage_present": "CIRCUIT STAGE ·" in text_blob,
        "admission_veto_present": "ADMISSION VETO ·" in text_blob,
        "hardware_veto_active": "HARDWARE CLAIM VETO · ACTIVE" in text_blob,
        "zero_jobs_boundary_present": "ZERO JOBS" in text_blob,
        "submission_wording_present": "Submission enabled:" in text_blob,
        "name_not_hardware_boundary_present": "Backend name is an identifier, not evidence of physical hardware." in text_blob,
        "backend_admission_boundary_present": "V3.5 CLAIM BOUNDARY · BACKEND-ADMISSION EVIDENCE ONLY" in text_blob,
        "advantage_not_claimed": "quantum advantage" in text_blob.lower(),
        "v34_surface_preserved": "V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER" in text_blob,
    }
    optional = {
        "expected_evidence_mode": expected_evidence_mode,
        "expected_backend_class": expected_backend_class,
        "expected_circuit_stage": expected_circuit_stage,
    }
    expected_markers = {
        "expected_evidence_mode": "EVIDENCE MODE ·",
        "expected_backend_class": "BACKEND CLASS ·",
        "expected_circuit_stage": "CIRCUIT STAGE ·",
    }
    for name, expected in optional.items():
        if expected is not None:
            checks[name] = f"{expected_markers[name]} {expected.strip().upper()}" in text_blob

    failed = [name for name, passed in checks.items() if not passed]
    return {
        "app_path": str(target),
        "checks": checks,
        "exception_messages": [str(element.value) for element in app.exception],
        "failed_checks": failed,
        "tab_count": len(tabs),
        "tabs": list(tabs),
        "valid": not failed,
        "verifier": "QUANTUM LAB V3.5 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.5 UI.")
    parser.add_argument("app", nargs="?", type=Path, default=Path("app.py"))
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--evidence-mode", choices=("NONE", "SNAPSHOT", "LIVE"))
    parser.add_argument("--backend-class", choices=("HARDWARE", "FAKE", "SIMULATOR", "UNKNOWN"))
    parser.add_argument("--circuit-stage", choices=("PROVIDER_NEUTRAL", "TARGET_TRANSPILED", "ROUTED"))
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v35(
        args.app,
        timeout_seconds=args.timeout,
        expected_evidence_mode=args.evidence_mode,
        expected_backend_class=args.backend_class,
        expected_circuit_stage=args.circuit_stage,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_TABS", "verify_streamlit_surface_v35"]
