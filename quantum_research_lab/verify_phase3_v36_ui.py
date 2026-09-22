"""Positive-rerun Streamlit AppTest verifier for the V3.6 UI contract."""

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

REQUIRED_MARKERS = (
    "V3.6 · STRUCTURAL COST ATTRIBUTION & REWRITE GATE",
    "ARCHITECTURE_REWRITE_REQUIRED",
    "TOPOLOGY-ONLY · REJECTED STRUCTURAL FLOOR",
    "INCREMENTAL EXPOSURE · BLOCKED PENDING REVERSIBLE COMPILER",
    "V3.6 CLAIM BOUNDARY · STRUCTURAL DIAGNOSIS ONLY",
    "184,191,414",
    "2,500,000",
    "43,680 rows, PASS",
    "BLOCKED · ZERO JOBS",
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


def verify_streamlit_surface_v36(
    app_path: str | Path,
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Require a positive final state after a second full Streamlit rerun."""

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
    first_exceptions = [str(element.value) for element in app.exception]
    first_text, first_tabs = _snapshot(app)
    app.run(timeout=timeout_seconds)
    final_exceptions = [str(element.value) for element in app.exception]
    final_text, final_tabs = _snapshot(app)

    backend_buttons = [
        button
        for button in app.button
        if str(getattr(button, "label", "")) == "Open named-backend transpilation lane"
    ]
    seal_buttons = [
        button
        for button in app.button
        if str(getattr(button, "label", "")) == "Seal Phase-III equal-objective hardware protocol"
    ]
    checks: dict[str, bool] = {
        "initial_run_exception_free": not first_exceptions,
        "positive_final_rerun_exception_free": not final_exceptions,
        "initial_12_tab_contract_exact": first_tabs == EXPECTED_TABS,
        "final_12_tab_contract_exact": final_tabs == EXPECTED_TABS,
        "v36_markers_present_initially": all(marker in first_text for marker in REQUIRED_MARKERS),
        "v36_markers_present_after_rerun": all(marker in final_text for marker in REQUIRED_MARKERS),
        "artifact_authenticated_marker_present": "artifact AUTHENTICATED" in final_text,
        "named_backend_lane_present_once": len(backend_buttons) == 1,
        "named_backend_lane_disabled": len(backend_buttons) == 1
        and getattr(backend_buttons[0], "disabled", None) is True,
        "hardware_seal_present_once": len(seal_buttons) == 1,
        "hardware_seal_disabled": len(seal_buttons) == 1
        and getattr(seal_buttons[0], "disabled", None) is True,
        "offline_no_provider_invocation_boundary": (
            "NETWORK/PROVIDER ACTIONS NOT INVOKED" in final_text
            and "FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE" in final_text
        ),
        "advantage_not_claimed": "quantum advantage" in final_text.lower(),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "app_path": str(target),
        "checks": checks,
        "failed_checks": failed,
        "first_exception_messages": first_exceptions,
        "final_exception_messages": final_exceptions,
        "tab_count": len(final_tabs),
        "tabs": list(final_tabs),
        "valid": not failed,
        "verifier": "QUANTUM LAB V3.6 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.6 UI.")
    parser.add_argument("app", nargs="?", type=Path, default=Path("app_v36_offline_harness.py"))
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface_v36(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_TABS", "REQUIRED_MARKERS", "verify_streamlit_surface_v36"]
