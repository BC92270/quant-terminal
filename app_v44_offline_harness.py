"""Validation-only V4.4 AppTest harness with fail-fast provider spies.

The harness executes the complete V4.3 predecessor harness, which renders the
real current twelve-tab application under offline fixtures. It then exercises
the V4.4 loader, fail-closed normalizer, renderer and BANDS projection against
an isolated Streamlit recorder. No Qiskit replay is run by the UI harness.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import runpy
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
predecessor = runpy.run_path(str(ROOT / "app_v43_offline_harness.py"))
spy_keys = predecessor["spy_keys"]


class _FakeContext:
    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        return False


class _FakeStreamlit:
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


from quantum_research_lab import phase3_v44_ui as v44_ui  # noqa: E402


artifact, report = v44_ui.load_v44_ui_artifact()
checks = report.get("checks") or {}
artifact_integrity = bool(
    checks.get("artifact_raw_identity") is True
    and checks.get("artifact_semantic_identity") is True
)
spec_integrity = checks.get("spec_raw_semantic_identity") is True
snapshot_integrity = checks.get("snapshot_raw_semantic_identity") is True
toolchain_integrity = checks.get("toolchain_raw_semantic_identity") is True
parent_integrity = checks.get("v43_parent_and_191_immutable_paths") is True
if report.get("valid") is not True:
    raise AssertionError(f"V4.4 offline artifact authentication failed: {report}")

normalized = v44_ui.normalize_v44_artifact(
    artifact,
    artifact_integrity=artifact_integrity,
    spec_integrity=spec_integrity,
    snapshot_integrity=snapshot_integrity,
    toolchain_integrity=toolchain_integrity,
    parent_integrity=parent_integrity,
)
if normalized.get("authenticated") is not True:
    raise AssertionError("V4.4 normalization did not admit authenticated evidence")

spec = json.loads((ROOT / "quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json").read_text(encoding="utf-8"))
snapshot = json.loads((ROOT / "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json").read_text(encoding="utf-8"))
toolchain = json.loads((ROOT / "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json").read_text(encoding="utf-8"))

invalid_states = {
    "missing": v44_ui.normalize_v44_artifact(None, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
    "implicit_artifact": v44_ui.normalize_v44_artifact(artifact, artifact_integrity=None, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
    "bad_spec": v44_ui.normalize_v44_artifact(artifact, artifact_integrity=True, spec_integrity=False, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=True),
    "bad_snapshot": v44_ui.normalize_v44_artifact(artifact, artifact_integrity=True, spec_integrity=True, snapshot_integrity=False, toolchain_integrity=True, parent_integrity=True),
    "bad_toolchain": v44_ui.normalize_v44_artifact(artifact, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=False, parent_integrity=True),
    "bad_parent": v44_ui.normalize_v44_artifact(artifact, artifact_integrity=True, spec_integrity=True, snapshot_integrity=True, toolchain_integrity=True, parent_integrity=False),
}
tampered = copy.deepcopy(artifact)
tampered["claim_boundary"]["hardware_executable"] = True
tampered["artifact_sha256"] = v44_ui.canonical_json_sha256(
    {key: value for key, value in tampered.items() if key != "artifact_sha256"}
)
invalid_states["rehashed_boundary_tamper"] = v44_ui.normalize_v44_artifact(
    tampered,
    artifact_integrity=False,
    spec_integrity=True,
    snapshot_integrity=True,
    toolchain_integrity=True,
    parent_integrity=True,
)
if not all(state.get("authenticated") is False for state in invalid_states.values()):
    raise AssertionError(f"V4.4 fail-closed normalization contract failed: {invalid_states}")

fake_st = _FakeStreamlit()
section_headers: list[tuple[str, str, str]] = []


def _fake_section_header(title: str, kicker: str, copy_text: str) -> None:
    section_headers.append((title, kicker, copy_text))


real_v44_st = v44_ui.st
try:
    v44_ui.st = fake_st
    rendered = v44_ui.render_v44_named_backend_panel(
        _fake_section_header,
        artifact=artifact,
        spec=spec,
        snapshot=snapshot,
        toolchain=toolchain,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        snapshot_integrity=snapshot_integrity,
        toolchain_integrity=toolchain_integrity,
        parent_integrity=parent_integrity,
        key_prefix="v44_offline_fake",
    )
finally:
    v44_ui.st = real_v44_st

fake_markup = "\n".join(fake_st.markdown_payloads)
fake_messages = "\n".join(fake_st.messages)
render_contract = bool(
    rendered.get("authenticated") is True
    and len(section_headers) == 1
    and fake_st.calls.get("dataframe") == 8
    and fake_st.calls.get("bar_chart") == 1
    and fake_st.calls.get("expander") == 4
    and fake_st.calls.get("button") == 12
    and fake_st.calls.get("download_button") == 10
    and fake_st.calls.get("warning") == 1
    and fake_st.calls.get("error") == 1
    and fake_st.calls.get("info") == 1
    and fake_markup.count('data-qv44-auth="pass"') == 1
    and fake_markup.count("qv44-metric") == 12
    and "CAPACITY · REJECTED" in fake_messages
    and "157-qubit capacity overflow" in fake_messages
)
if not render_contract:
    raise AssertionError(
        "V4.4 isolated Streamlit render contract failed: "
        f"headers={len(section_headers)} calls={fake_st.calls}"
    )

base_encoding = {
    "encoding_status": "OFFLINE V4.3 PREDECESSOR FIXTURE",
    "hardware_executable": True,
    "logical_qubits_min": 40,
}
projected_base = v44_ui.apply_v44_encoding_state(base_encoding, regime="BASE", state=rendered, artifact=artifact)
projected_bands = v44_ui.apply_v44_encoding_state(base_encoding, regime="BANDS", state=rendered, artifact=artifact)
if projected_base != base_encoding:
    raise AssertionError("V4.4 changed a non-BANDS encoding")
if not (
    projected_bands.get("v44_decision") == v44_ui.EXPECTED_OVERALL
    and projected_bands.get("backend_qubits") == 156
    and projected_bands.get("logical_qubits_min") == 339
    and projected_bands.get("v44_rejected_seed_count") == 8
    and projected_bands.get("backend_transpilation") == v44_ui.NOT_RUN
    and projected_bands.get("full_workload_routing") == v44_ui.NOT_RUN
    and projected_bands.get("provider_calls") == 0
    and projected_bands.get("network_calls") == 0
    and projected_bands.get("qpu_jobs_submitted") == 0
    and projected_bands.get("hardware_executable") is False
    and projected_bands.get("quantum_advantage") == "NOT_CLAIMED"
):
    raise AssertionError(f"V4.4 BANDS projection failed: {projected_bands}")

spy_counts = {kind: int(st.session_state.get(key, 0)) for kind, key in spy_keys.items()}
if any(spy_counts.values()):
    raise AssertionError(f"V4.4 offline harness observed a forbidden call: {spy_counts}")

V44_HARNESS_STATUS = {
    "apply": "PASS",
    "load": "PASS",
    "normalize": "PASS",
    "provider_calls": spy_counts["provider"],
    "render": "PASS",
    "seal_calls": spy_counts["seal"],
    "transpile_calls": spy_counts["transpile"],
}

st.caption(
    "V4.4 OFFLINE APPTEST HARNESS · LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS · "
    f"PROVIDER SPY CALLS · {spy_counts['provider']} · TRANSPILE SPY CALLS · {spy_counts['transpile']} · "
    f"SEAL SPY CALLS · {spy_counts['seal']} · NETWORK CALLS · 0 · QPU JOBS · 0 · "
    "REAL SEALED V4.4 EVIDENCE · OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
