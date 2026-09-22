"""Validation-only V4.5 AppTest harness with fail-fast provider spies.

The harness executes the complete V4.4 predecessor harness, which renders the
real twelve-tab application under offline fixtures.  It then authenticates and
exercises the V4.5 loader, fail-closed normalizer, renderer and BANDS projection
against an isolated Streamlit recorder.  No circuit build, provider SDK,
credential read, network access, transpilation, routing or job is permitted.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
predecessor = runpy.run_path(str(ROOT / "app_v44_offline_harness.py"))
spy_keys = predecessor["spy_keys"]


class _FakeContext:
    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        return False


class _FakeStreamlit:
    """Strict recorder: an unimplemented Streamlit call fails immediately."""

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

    def success(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("success")
        self.messages.append(str(body))

    def warning(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("warning")
        self.messages.append(str(body))

    def error(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("error")
        self.messages.append(str(body))

    def info(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("info")
        self.messages.append(str(body))

    def dataframe(self, data: Any, **kwargs: Any) -> None:
        del data, kwargs
        self._record("dataframe")

    def bar_chart(self, data: Any, **kwargs: Any) -> None:
        del data, kwargs
        self._record("bar_chart")

    def caption(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("caption")
        self.messages.append(str(body))

    def code(self, body: Any, **kwargs: Any) -> None:
        del kwargs
        self._record("code")
        self.messages.append(str(body))

    def button(self, label: Any, **kwargs: Any) -> bool:
        del label, kwargs
        self._record("button")
        return False

    def download_button(self, label: Any, **kwargs: Any) -> bool:
        del label, kwargs
        self._record("download_button")
        return False

    def expander(self, label: Any, **kwargs: Any) -> _FakeContext:
        del label, kwargs
        self._record("expander")
        return _FakeContext()


from quantum_research_lab import phase3_v45_ui as v45_ui  # noqa: E402


artifact, report = v45_ui.load_v45_ui_artifact()
checks = report.get("checks") or {}
artifact_integrity = bool(
    checks.get("artifact_raw_identity") is True
    and checks.get("artifact_semantic_identity") is True
)
spec_integrity = checks.get("spec_raw_semantic_identity") is True
liveness_integrity = bool(
    checks.get("liveness_raw_identity") is True
    and checks.get("liveness_semantic_identity") is True
)
parent_integrity = bool(
    checks.get("v44_parent_and_209_immutable_paths") is True
    and checks.get("artifact_parent_crosslinks") is True
)
source_integrity = checks.get("source_raw_identity") is True
checker_integrity = checks.get("checker_raw_identity") is True
if report.get("valid") is not True or report.get("check_count") != 28:
    raise AssertionError(f"V4.5 offline artifact authentication failed: {report}")

healthy = v45_ui.normalize_v45_artifact(
    artifact,
    artifact_integrity=artifact_integrity,
    spec_integrity=spec_integrity,
    liveness_integrity=liveness_integrity,
    parent_integrity=parent_integrity,
    source_integrity=source_integrity,
    checker_integrity=checker_integrity,
)
if healthy.get("authenticated") is not True:
    raise AssertionError("V4.5 normalization did not admit authenticated evidence")

spec, liveness = v45_ui.load_v45_ui_supporting_evidence()
if not isinstance(spec, dict) or not isinstance(liveness, dict):
    raise AssertionError("V4.5 supporting specification or liveness evidence is unavailable")

invalid_states = {
    "missing": v45_ui.normalize_v45_artifact(None, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
    "implicit_artifact": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=None, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
    "bad_spec": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=True, spec_integrity=False, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=True),
    "bad_liveness": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=True, spec_integrity=True, liveness_integrity=False, parent_integrity=True, source_integrity=True, checker_integrity=True),
    "bad_parent": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=False, source_integrity=True, checker_integrity=True),
    "bad_source": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=False, checker_integrity=True),
    "bad_checker": v45_ui.normalize_v45_artifact(artifact, artifact_integrity=True, spec_integrity=True, liveness_integrity=True, parent_integrity=True, source_integrity=True, checker_integrity=False),
}
tampered = copy.deepcopy(artifact)
tampered["claim_boundary"]["hardware_executable"] = True
tampered["artifact_sha256"] = v45_ui.canonical_json_sha256(
    {key: value for key, value in tampered.items() if key != "artifact_sha256"}
)
invalid_states["rehashed_boundary_tamper"] = v45_ui.normalize_v45_artifact(
    tampered,
    artifact_integrity=False,
    spec_integrity=True,
    liveness_integrity=True,
    parent_integrity=True,
    source_integrity=True,
    checker_integrity=True,
)
if not all(state.get("authenticated") is False for state in invalid_states.values()):
    raise AssertionError(f"V4.5 fail-closed normalization contract failed: {invalid_states}")

fake_st = _FakeStreamlit()
section_headers: list[tuple[str, str, str]] = []


def _fake_section_header(title: str, kicker: str, copy_text: str) -> None:
    section_headers.append((title, kicker, copy_text))


real_v45_st = v45_ui.st
try:
    v45_ui.st = fake_st
    rendered = v45_ui.render_v45_width_reduction_panel(
        _fake_section_header,
        artifact=artifact,
        spec=spec,
        liveness=liveness,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        liveness_integrity=liveness_integrity,
        parent_integrity=parent_integrity,
        source_integrity=source_integrity,
        checker_integrity=checker_integrity,
        key_prefix="v45_offline_fake",
    )
finally:
    v45_ui.st = real_v45_st

fake_markup = "\n".join(fake_st.markdown_payloads)
fake_messages = "\n".join(fake_st.messages)
render_contract = bool(
    rendered.get("authenticated") is True
    and len(section_headers) == 1
    and fake_st.calls.get("dataframe") == 7
    and fake_st.calls.get("bar_chart") == 1
    and fake_st.calls.get("expander") == 4
    and fake_st.calls.get("button") == 12
    and fake_st.calls.get("download_button") == 10
    and fake_st.calls.get("success") == 1
    and fake_st.calls.get("warning") == 1
    and fake_st.calls.get("info") == 1
    and fake_st.calls.get("error", 0) == 0
    and fake_markup.count('data-qv45-auth="pass"') == 1
    and fake_markup.count("qv45-metric") == 12
    and "WIDTH + PROMISE PARITY · PASSED" in fake_messages
    and v45_ui.EXPECTED_NEXT_GATE in fake_messages
)
if not render_contract:
    raise AssertionError(
        "V4.5 isolated Streamlit render contract failed: "
        f"headers={len(section_headers)} calls={fake_st.calls}"
    )

base_encoding = {
    "encoding_status": "OFFLINE V4.4 PREDECESSOR FIXTURE",
    "hardware_executable": True,
    "logical_qubits_min": 339,
}
projected_base = v45_ui.apply_v45_encoding_state(
    base_encoding, regime="BASE", state=rendered, artifact=artifact
)
projected_bands = v45_ui.apply_v45_encoding_state(
    base_encoding, regime="BANDS", state=rendered, artifact=artifact
)
if projected_base != base_encoding:
    raise AssertionError("V4.5 changed a non-BANDS encoding")
if not (
    projected_bands.get("v45_decision") == v45_ui.EXPECTED_OVERALL
    and projected_bands.get("backend_capacity_ok") is True
    and projected_bands.get("backend_qubits") == 156
    and projected_bands.get("logical_qubits_max") == 145
    and projected_bands.get("v45_minimum_capacity_margin_qubits") == 11
    and projected_bands.get("v45_cnot_budget_pass_count") == 8
    and projected_bands.get("backend_transpilation") == v45_ui.NOT_RUN
    and projected_bands.get("full_workload_routing") == v45_ui.NOT_RUN
    and projected_bands.get("provider_calls") == 0
    and projected_bands.get("network_calls") == 0
    and projected_bands.get("qpu_jobs_submitted") == 0
    and projected_bands.get("hardware_executable") is False
    and projected_bands.get("quantum_advantage") == "NOT_CLAIMED"
):
    raise AssertionError(f"V4.5 BANDS projection failed: {projected_bands}")

spy_counts = {kind: int(st.session_state.get(key, 0)) for kind, key in spy_keys.items()}
if any(spy_counts.values()):
    raise AssertionError(f"V4.5 offline harness observed a forbidden call: {spy_counts}")

V45_HARNESS_STATUS = {
    "apply": "PASS",
    "load": "PASS",
    "normalize": "PASS",
    "provider_calls": spy_counts["provider"],
    "render": "PASS",
    "seal_calls": spy_counts["seal"],
    "transpile_calls": spy_counts["transpile"],
}

st.caption(
    "V4.5 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS · "
    f"PROVIDER SPY CALLS · {spy_counts['provider']} · TRANSPILE SPY CALLS · {spy_counts['transpile']} · "
    f"SEAL SPY CALLS · {spy_counts['seal']} · CREDENTIAL READS · 0 · NETWORK CALLS · 0 · QPU JOBS · 0 · "
    "FULL RECONSTRUCTION / TRANSPILATION / ROUTING · NOT_RUN_IN_V4_5 · "
    "REAL SEALED V4.5 EVIDENCE · OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
