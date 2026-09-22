"""Offline AppTest harness for the authenticated Quantum Lab V4.6 surface.

The V4.5 predecessor harness preserves the complete twelve-tab application and
its fail-fast provider spies. V4.6 then exercises its real loader, normalizer,
renderer and BANDS projection against a strict recorder. No compiler replay,
provider discovery, credential read, network request, simulator or QPU job is
performed by this harness.
"""

from __future__ import annotations

import copy
from pathlib import Path
import runpy
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
predecessor = runpy.run_path(str(ROOT / "app_v45_offline_harness.py"))
spy_keys = predecessor["spy_keys"]


class _FakeContext:
    def __init__(self, recorder: "_FakeStreamlit") -> None:
        self.recorder = recorder

    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        return False

    def metric(self, label: Any, value: Any, delta: Any = None, **kwargs: Any) -> None:
        del label, value, delta, kwargs
        self.recorder._record("metric")


class _FakeStreamlit:
    """Strict recorder: any missing Streamlit primitive fails the harness."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.markdown_payloads: list[str] = []
        self.messages: list[str] = []

    def _record(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1

    def markdown(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("markdown")
        self.markdown_payloads.append(str(body))

    def _message(self, name: str, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record(name)
        self.messages.append(str(body))

    def success(self, body: Any, **kwargs: Any) -> None:
        self._message("success", body, **kwargs)

    def warning(self, body: Any, **kwargs: Any) -> None:
        self._message("warning", body, **kwargs)

    def error(self, body: Any, **kwargs: Any) -> None:
        self._message("error", body, **kwargs)

    def info(self, body: Any, **kwargs: Any) -> None:
        self._message("info", body, **kwargs)

    def caption(self, body: Any, **kwargs: Any) -> None:
        self._message("caption", body, **kwargs)

    def write(self, body: Any, **kwargs: Any) -> None:
        self._message("write", body, **kwargs)

    def dataframe(self, data: Any, **kwargs: Any) -> None:
        del data, kwargs
        self._record("dataframe")

    def button(self, label: Any, **kwargs: Any) -> bool:
        del label, kwargs
        self._record("button")
        return False

    def download_button(self, label: Any, **kwargs: Any) -> bool:
        del label, kwargs
        self._record("download_button")
        return False

    def columns(self, count: int, **kwargs: Any) -> list[_FakeContext]:
        del kwargs
        self._record("columns")
        return [_FakeContext(self) for _ in range(count)]

    def tabs(self, labels: list[str], **kwargs: Any) -> list[_FakeContext]:
        del kwargs
        self._record("tabs")
        return [_FakeContext(self) for _ in labels]


from quantum_research_lab import phase3_v46_ui as v46_ui  # noqa: E402


artifact, report = v46_ui.load_v46_ui_artifact()
if not isinstance(artifact, dict) or report.get("valid") is not True or report.get("check_count") != 30:
    raise AssertionError(f"V4.6 offline artifact authentication failed: {report}")
healthy = v46_ui.normalize_v46_artifact(artifact, integrity=True)
if healthy.get("authenticated") is not True:
    raise AssertionError("V4.6 normalization did not admit authenticated evidence")

tampered = copy.deepcopy(artifact)
tampered["claim_boundary"]["hardware_executable"] = True
tampered["artifact_sha256"] = v46_ui.canonical_json_sha256(
    {key: value for key, value in tampered.items() if key != "artifact_sha256"}
)
invalid_states = {
    "missing": v46_ui.normalize_v46_artifact(None, integrity=True),
    "implicit": v46_ui.normalize_v46_artifact(artifact, integrity=None),
    "invalid": v46_ui.normalize_v46_artifact(artifact, integrity=False),
    "rehashed_boundary_tamper": v46_ui.normalize_v46_artifact(tampered, integrity=False),
}
if not all(state.get("authenticated") is False and state.get("hardware_executable") is False for state in invalid_states.values()):
    raise AssertionError(f"V4.6 fail-closed normalization contract failed: {invalid_states}")

fake_st = _FakeStreamlit()
section_headers: list[tuple[str, str, str]] = []


def _fake_section_header(title: str, kicker: str, description: str) -> None:
    section_headers.append((title, kicker, description))


real_v46_st = v46_ui.st
try:
    v46_ui.st = fake_st
    rendered = v46_ui.render_v46_full_stream_routing_panel(
        _fake_section_header,
        artifact=artifact,
        integrity=True,
        key_prefix="v46_offline_fake",
    )
finally:
    v46_ui.st = real_v46_st

messages = "\n".join(fake_st.messages)
markup = "\n".join(fake_st.markdown_payloads)
expected_calls = {
    "button": 9,
    "columns": 1,
    "dataframe": 5,
    "download_button": 5,
    "error": 1,
    "info": 1,
    "metric": 5,
    "success": 1,
    "tabs": 1,
    "warning": 1,
}
if not (
    rendered.get("authenticated") is True
    and rendered.get("hardware_executable") is False
    and len(section_headers) == 1
    and all(fake_st.calls.get(name, 0) == count for name, count in expected_calls.items())
    and "AUTHENTICATED · RESEARCH_ONLY · ZERO PROVIDER / ZERO JOB" in markup
    and "Structural PASS is not hardware readiness" in messages
    and v46_ui.EXPECTED_NEXT_GATE in messages
):
    raise AssertionError(
        "V4.6 isolated Streamlit render contract failed: "
        f"headers={len(section_headers)} calls={fake_st.calls}"
    )

base_encoding = {
    "encoding_status": "OFFLINE V4.5 PREDECESSOR FIXTURE",
    "hardware_executable": True,
    "logical_qubits_min": 339,
}
projected_base = v46_ui.apply_v46_encoding_state(base_encoding, regime="BASE", state=rendered, artifact=artifact)
projected_bands = v46_ui.apply_v46_encoding_state(base_encoding, regime="BANDS", state=rendered, artifact=artifact)
if projected_base != base_encoding:
    raise AssertionError("V4.6 changed a non-BANDS encoding")
if not (
    projected_bands.get("encoding_status") == "V4.6 FULL-STREAM ROUTING PASS · HARDWARE BLOCKED"
    and projected_bands.get("hardware_executable") is False
    and projected_bands.get("logical_qubits_min") == 145
    and projected_bands.get("native_cz_max") == 15527797
    and projected_bands.get("routed_depth_max") == 24893376
    and projected_bands.get("routing_status") == "8/8 STRUCTURAL + PREREGISTERED RESOURCE PASS"
    and projected_bands.get("research_classification") == "RESEARCH_ONLY"
):
    raise AssertionError(f"V4.6 BANDS projection failed: {projected_bands}")

spy_counts = {kind: int(st.session_state.get(key, 0)) for kind, key in spy_keys.items()}
if any(spy_counts.values()):
    raise AssertionError(f"V4.6 offline harness observed a forbidden call: {spy_counts}")

V46_HARNESS_STATUS = {
    "apply": "PASS",
    "authentication_checks": 30,
    "load": "PASS",
    "normalize": "PASS",
    "provider_calls": spy_counts["provider"],
    "render": "PASS",
    "seal_calls": spy_counts["seal"],
    "transpile_calls": spy_counts["transpile"],
}

st.caption(
    "V4.6 OFFLINE APPTEST HARNESS · 30/30 AUTH · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS · "
    f"PROVIDER SPY CALLS · {spy_counts['provider']} · TRANSPILE SPY CALLS · {spy_counts['transpile']} · "
    f"SEAL SPY CALLS · {spy_counts['seal']} · CREDENTIAL READS · 0 · NETWORK CALLS · 0 · "
    "BACKEND RUNS · 0 · SIMULATOR JOBS · 0 · QPU JOBS · 0 · HARDWARE EXECUTABLE · FALSE · "
    "REAL SEALED V4.6 EVIDENCE · OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
