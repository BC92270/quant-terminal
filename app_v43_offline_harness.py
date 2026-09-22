"""Validation-only V4.3 AppTest harness with an isolated render spy.

The frozen V4.2 harness remains the authoritative full-application offline
fixture and renders the real current Quantum Lab.  This append-only successor
then authenticates the sealed V4.3 artifact and independently exercises the
V4.3 load, normalize, render and encoding-projection surfaces against an
in-memory Streamlit fake.  The second render is therefore checked without
duplicating it in the visible AppTest page.

No provider, backend, transpilation, sealing or QPU action is permitted.  A
failed assertion raises before the positive V4.3 marker is emitted.
"""

from __future__ import annotations

import json
from pathlib import Path
import runpy
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent

# AppTest reruns scripts in one interpreter.  ``run_path`` deliberately
# re-executes the complete predecessor harness on every rerun instead of using
# a cached import.  The real application, frozen fixtures and fail-fast
# provider spies are preserved exactly.
predecessor = runpy.run_path(str(ROOT / "app_v42_offline_harness.py"))
spy_keys = predecessor["spy_keys"]


class _FakeContext:
    """Minimal context manager used only by the isolated V4.3 renderer."""

    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        return False


class _FakeStreamlit:
    """Strict offline render recorder; unknown Streamlit calls fail loudly."""

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


# Import after the predecessor run so the real Streamlit integration has
# already rendered once.  Only this module's ``st`` binding is temporarily
# replaced; the application and predecessor harness keep the real AppTest API.
from quantum_research_lab import phase3_v43_ui as v43_ui  # noqa: E402


artifact, report = v43_ui.load_v43_ui_artifact()
checks = report.get("checks") or {}
artifact_integrity = bool(
    checks.get("artifact_raw_identity") is True
    and checks.get("artifact_semantic_identity") is True
)
spec_integrity = checks.get("sealed_sources") is True
parent_integrity = checks.get("parent_identity") is True

if report.get("valid") is not True:
    raise AssertionError(f"V4.3 offline artifact authentication failed: {report}")

normalized = v43_ui.normalize_v43_artifact(
    artifact,
    artifact_integrity=artifact_integrity,
    spec_integrity=spec_integrity,
    parent_integrity=parent_integrity,
)
if normalized.get("authenticated") is not True:
    raise AssertionError("V4.3 normalization did not admit authenticated evidence")

spec_path = (
    ROOT
    / "quantum_research_lab"
    / "PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json"
)
spec = json.loads(spec_path.read_text(encoding="utf-8"))
if not isinstance(spec, dict):
    raise AssertionError("V4.3 specification fixture must be a JSON object")

fake_st = _FakeStreamlit()
section_headers: list[tuple[str, str, str]] = []


def _fake_section_header(title: str, kicker: str, copy: str) -> None:
    section_headers.append((title, kicker, copy))


real_v43_st = v43_ui.st
try:
    v43_ui.st = fake_st
    rendered = v43_ui.render_v43_reversible_circuit_panel(
        _fake_section_header,
        artifact=artifact,
        spec=spec,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
        key_prefix="v43_offline_fake",
    )
finally:
    v43_ui.st = real_v43_st

projected = v43_ui.apply_v43_encoding_state(
    {
        "encoding_status": "OFFLINE V4.2 PREDECESSOR FIXTURE",
        "logical_qubits_min": 40,
    },
    regime="BANDS",
    state=rendered,
    artifact=artifact,
)

fake_markup = "\n".join(fake_st.markdown_payloads)
fake_messages = "\n".join(fake_st.messages)
render_contract = bool(
    rendered.get("authenticated") is True
    and len(section_headers) == 1
    and fake_st.calls.get("dataframe") == 6
    and fake_st.calls.get("bar_chart") == 1
    and fake_st.calls.get("expander") == 3
    and fake_st.calls.get("button") == 10
    and fake_st.calls.get("download_button") == 7
    and fake_st.calls.get("error", 0) == 0
    and 'data-qv43-auth="pass"' in fake_markup
    and "OFF-PROMISE NEGATIVE CONTROL" in fake_messages
)
if not render_contract:
    raise AssertionError(
        "V4.3 isolated Streamlit render contract failed: "
        f"headers={len(section_headers)} calls={fake_st.calls}"
    )

projection_contract = bool(
    isinstance(projected, dict)
    and projected.get("v43_total_elementary_instructions") == 21_925_902
    and projected.get("v43_maximum_materialized_cnot") == 1_158_046
    and projected.get("v43_minimum_budget_margin_cnot") == 1_341_954
    and projected.get("v43_maximum_logical_qubits") == 339
    and projected.get("promise_subspace_only") is True
    and projected.get("off_promise_global_cleanup") == "REJECTED_WITH_WITNESS"
    and projected.get("named_backend_selected") is False
    and projected.get("backend_transpilation") == "NOT_RUN"
    and projected.get("hardware_executable") is False
    and projected.get("provider_calls") == 0
    and projected.get("qpu_jobs_submitted") == 0
    and projected.get("quantum_advantage") == "NOT_CLAIMED"
)
if not projection_contract:
    raise AssertionError(f"V4.3 BANDS encoding projection failed: {projected}")

spy_counts = {
    kind: int(st.session_state.get(key, 0))
    for kind, key in spy_keys.items()
}
if any(spy_counts.values()):
    raise AssertionError(f"V4.3 offline harness observed a forbidden call: {spy_counts}")

V43_HARNESS_STATUS = {
    "apply": "PASS",
    "load": "PASS",
    "normalize": "PASS",
    "provider_calls": spy_counts["provider"],
    "render": "PASS",
    "seal_calls": spy_counts["seal"],
    "transpile_calls": spy_counts["transpile"],
}

st.caption(
    "V4.3 OFFLINE APPTEST HARNESS · "
    "LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS · "
    f"PROVIDER SPY CALLS · {spy_counts['provider']} · "
    f"TRANSPILE SPY CALLS · {spy_counts['transpile']} · "
    f"SEAL SPY CALLS · {spy_counts['seal']} · "
    "REAL SEALED V4.3 EVIDENCE · OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)

