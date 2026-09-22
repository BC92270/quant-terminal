"""Streamlit AppTest acceptance verifier for the V3.4 institutional surface."""

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


def verify_streamlit_surface(
    app_path: str | Path,
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    try:
        from streamlit.testing.v1 import AppTest
    except ImportError as exc:  # pragma: no cover - deployment dependency boundary
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
    seal_buttons = [
        element
        for element in app.button
        if element.label == "Seal Phase-III equal-objective hardware protocol"
    ]
    checks = {
        "no_uncaught_streamlit_exception": len(app.exception) == 0,
        "legacy_12_tab_contract_preserved": tabs == EXPECTED_TABS,
        "v34_hero_present": "V3.4 · OPTIMIZED ORACLE + ELEMENTARY GUARDED MIXER"
        in text_blob,
        "v34_seal_present": "SEALED · 9 / 9 EVIDENCE GATES" in text_blob,
        "v34_spec_identity_present": "A287B6BF63F5206672A8" in text_blob,
        "interval_scope_present": "610,104" in text_blob,
        "n40_swap_scope_present": "2,400" in text_blob,
        "native_matrix_scope_present": "96" in text_blob,
        "optimized_oracle_pass_present": "EQUIVALENCE · PASS" in text_blob,
        "canonical_resource_present": "668,278,258" in text_blob,
        "logical_qubit_reduction_present": "118" in text_blob,
        "ring_rejection_retained": "REJECTED · AUTHENTICATED WITNESS ISOLATION"
        in text_blob,
        "backend_unrouted_boundary_present": "NOT EVALUATED · V3.4 ELEMENTARY IR UNROUTED"
        in text_blob,
        "hardware_zero_jobs_boundary_present": "BLOCKED · ZERO JOBS" in text_blob,
        "spec_download_present": "Download V3.4 optimized/native specification"
        in text_blob,
        "artifact_download_present": "Download sealed V3.4 optimized/native artifact"
        in text_blob,
        "hardware_seal_disabled": bool(
            len(seal_buttons) == 1 and seal_buttons[0].disabled
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "app_path": str(target),
        "checks": checks,
        "exception_messages": [str(element.value) for element in app.exception],
        "failed_checks": failed,
        "tab_count": len(tabs),
        "tabs": list(tabs),
        "valid": not failed,
        "verifier": "QUANTUM LAB V3.4 STREAMLIT APPTEST ACCEPTANCE · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.4 UI.")
    parser.add_argument("app", nargs="?", type=Path, default=Path("app.py"))
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)
    report = verify_streamlit_surface(args.app, timeout_seconds=args.timeout)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_TABS", "verify_streamlit_surface"]
