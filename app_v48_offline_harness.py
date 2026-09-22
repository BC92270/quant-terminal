"""Offline AppTest harness for the authenticated Quantum Lab V4.8 surface.

The frozen V4.7 harness supplies the complete twelve-tab application and its
provider/transpile/seal spies.  This successor authenticates the real V4.8
artifact, independently checks its 65-check scientific report, and renders the
six-tab V4.8 panel into a strict recorder.  Network access, provider SDK import
and provider-credential environment reads fail immediately.  No compiler
replay, backend discovery, simulator submission or QPU job occurs here.
"""

from __future__ import annotations

import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket
from typing import Any, Callable
from unittest import mock

import streamlit as st


ROOT = Path(__file__).resolve().parent
predecessor = runpy.run_path(str(ROOT / "app_v47_offline_harness.py"))
spy_keys = dict(predecessor["spy_keys"])
spy_keys.update(
    {
        "network": "v48_network_spy_calls",
        "environment": "v48_environment_spy_reads",
    }
)


def _forbidden_call(kind: str) -> Callable[..., None]:
    def fail(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        key = spy_keys[kind]
        st.session_state[key] = int(st.session_state.get(key, 0)) + 1
        raise RuntimeError(f"V4.8 forbidden {kind} spy was invoked")

    return fail


for spy_key in spy_keys.values():
    st.session_state.setdefault(spy_key, 0)


_real_import = builtins.__import__
_real_getenv = os.getenv
_real_environ_getitem = type(os.environ).__getitem__


def _guarded_import(
    name: str,
    globals: dict[str, Any] | None = None,
    locals: dict[str, Any] | None = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if name == "qiskit" or name.startswith("qiskit.") or name.startswith("qiskit_ibm_runtime"):
        _forbidden_call("provider")()
    return _real_import(name, globals, locals, fromlist, level)


def _is_provider_environment_key(key: Any) -> bool:
    normalized = str(key).upper()
    return bool(
        normalized.startswith(("IBM_QUANTUM", "QISKIT_IBM", "QISKIT_TOKEN"))
        or normalized in {"IBM_TOKEN", "IBM_CLOUD_API_KEY"}
        or ("QUANTUM" in normalized and any(term in normalized for term in ("TOKEN", "CREDENTIAL", "API_KEY")))
    )


def _guarded_getenv(key: str, default: str | None = None) -> str | None:
    if _is_provider_environment_key(key):
        _forbidden_call("environment")()
    return _real_getenv(key, default)


def _guarded_environ_getitem(environment: Any, key: str) -> str:
    if _is_provider_environment_key(key):
        _forbidden_call("environment")()
    return _real_environ_getitem(environment, key)


class _StrictOfflineBoundary:
    def __enter__(self) -> "_StrictOfflineBoundary":
        # Explicit patch lifecycle keeps this harness compatible with every
        # supported Python minor.
        self._patches = [
            mock.patch.object(socket.socket, "connect", new=_forbidden_call("network")),
            mock.patch("socket.create_connection", new=_forbidden_call("network")),
            mock.patch.object(builtins, "__import__", new=_guarded_import),
            mock.patch.object(os, "getenv", new=_guarded_getenv),
            mock.patch.object(type(os.environ), "__getitem__", new=_guarded_environ_getitem),
        ]
        for patcher in self._patches:
            patcher.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        for patcher in reversed(self._patches):
            patcher.stop()
        return False


class _FakeContext:
    def __init__(self, recorder: "_FakeStreamlit") -> None:
        self.recorder = recorder

    def __enter__(self) -> "_FakeContext":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        del exc_type, exc, traceback
        return False

    def metric(self, label: Any, value: Any, delta: Any = None, **kwargs: Any) -> None:
        del kwargs
        self.recorder._record("metric")
        self.recorder.metrics.append((str(label), str(value), str(delta)))

    def download_button(self, label: Any, **kwargs: Any) -> bool:
        return self.recorder.download_button(label, **kwargs)


class _FakeStreamlit:
    """Strict recorder: an unimplemented Streamlit primitive fails the run."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.markdown_payloads: list[str] = []
        self.messages: list[str] = []
        self.metrics: list[tuple[str, str, str]] = []
        self.tab_labels: list[str] = []
        self.buttons: list[dict[str, Any]] = []
        self.downloads: list[dict[str, Any]] = []

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

    def code(self, body: Any, **kwargs: Any) -> None:
        self._message("code", body, **kwargs)

    def dataframe(self, data: Any, **kwargs: Any) -> None:
        del data, kwargs
        self._record("dataframe")

    def button(self, label: Any, **kwargs: Any) -> bool:
        self._record("button")
        self.buttons.append({"label": str(label), **kwargs})
        return False

    def download_button(self, label: Any, **kwargs: Any) -> bool:
        self._record("download_button")
        self.downloads.append({"label": str(label), **kwargs})
        return False

    def columns(self, count: int, **kwargs: Any) -> list[_FakeContext]:
        del kwargs
        self._record("columns")
        return [_FakeContext(self) for _ in range(count)]

    def tabs(self, labels: list[str], **kwargs: Any) -> list[_FakeContext]:
        del kwargs
        self._record("tabs")
        self.tab_labels = list(labels)
        return [_FakeContext(self) for _ in labels]


with _StrictOfflineBoundary():
    from quantum_research_lab import phase3_v48_ui as v48_ui

    artifact, report = v48_ui.load_v48_ui_artifact()

if not (
    isinstance(artifact, dict)
    and report.get("valid") is True
    and report.get("check_count") == v48_ui.EXPECTED_UI_AUTH_CHECK_COUNT == 24
    and len(report.get("checks") or {}) == 24
    and not report.get("failed_checks")
    and not report.get("errors")
):
    raise AssertionError(f"V4.8 offline artifact authentication failed: {report}")
independent = report.get("independent_checker") or {}
if not (
    independent.get("valid") is True
    and independent.get("check_count") == v48_ui.EXPECTED_INDEPENDENT_CHECK_COUNT == 65
    and not independent.get("failed_checks")
    and not independent.get("errors")
):
    raise AssertionError(f"V4.8 independent checker failed: {independent}")

healthy = v48_ui.normalize_v48_artifact(artifact, integrity=True)
if not (
    healthy.get("authenticated") is True
    and healthy.get("hardware_executable") is False
    and healthy.get("research_classification") == "RESEARCH_ONLY"
):
    raise AssertionError(f"V4.8 normalization did not admit authenticated evidence: {healthy}")

tampered = copy.deepcopy(artifact)
tampered["claim_boundary"]["hardware_executable"] = True
tampered["artifact_sha256"] = v48_ui.canonical_json_sha256(
    {key: value for key, value in tampered.items() if key != "artifact_sha256"}
)
tampered_raw = (
    json.dumps(tampered, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
).encode("utf-8")
tampered_report = v48_ui._validate_v48_ui_artifact(
    tampered_raw,
    v48_ui.default_v48_ui_artifact_path(),
)
if tampered_report.get("valid") is not False:
    raise AssertionError(f"V4.8 rehashed boundary tamper was admitted: {tampered_report}")
invalid_states = {
    "missing": v48_ui.normalize_v48_artifact(None, integrity=True),
    "implicit": v48_ui.normalize_v48_artifact(artifact, integrity=None),
    "invalid": v48_ui.normalize_v48_artifact(artifact, integrity=False),
    "rehashed_boundary_tamper": v48_ui.normalize_v48_artifact(
        tampered, integrity=tampered_report.get("valid")
    ),
}
if not all(
    state.get("authenticated") is False
    and state.get("decision") == "MASKED_FAIL_CLOSED"
    and state.get("hardware_executable") is False
    for state in invalid_states.values()
):
    raise AssertionError(f"V4.8 fail-closed normalization contract failed: {invalid_states}")

fake_st = _FakeStreamlit()
section_headers: list[tuple[str, str, str]] = []


def _fake_section_header(title: str, kicker: str, description: str) -> None:
    section_headers.append((title, kicker, description))


real_v48_st = v48_ui.st
try:
    v48_ui.st = fake_st
    with _StrictOfflineBoundary():
        rendered = v48_ui.render_v48_multi_snapshot_architecture_panel(
            _fake_section_header,
            artifact=artifact,
            integrity=True,
            key_prefix="v48_offline_fake",
        )
finally:
    v48_ui.st = real_v48_st

expected_tabs = [
    "SNAPSHOT REGISTRY",
    "ROBUSTNESS",
    "ARCHITECTURE / CZ",
    "FRONTIER",
    "PROVENANCE",
    "GOVERNANCE",
]
governance_labels = {
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
button_labels = {button["label"] for button in fake_st.buttons}
if not (
    fake_st.calls.get("tabs") == 1
    and fake_st.tab_labels == expected_tabs
    and fake_st.calls.get("dataframe") == 5
    and fake_st.calls.get("columns") == 2
    and fake_st.calls.get("metric") == 6
    and fake_st.calls.get("button") == 10
    and governance_labels == button_labels
    and all(button.get("disabled") is True for button in fake_st.buttons)
):
    raise AssertionError(f"V4.8 isolated render structure failed: {fake_st.calls}")

expected_download_hashes = {
    "Download sealed V4.8 artifact": v48_ui.EXPECTED_ARTIFACT_RAW_SHA256,
    "Download V4.8 protocol": v48_ui.EXPECTED_SPEC_RAW_SHA256,
    "Download snapshot registry": v48_ui.EXPECTED_CATALOG_RAW_SHA256,
    "Download normalized snapshot cohort": v48_ui.EXPECTED_SNAPSHOTS_RAW_SHA256,
    "Download architecture candidate oracle": v48_ui.EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256,
    "Download robustness cost model": v48_ui.EXPECTED_MODEL_RAW_SHA256,
}
download_hashes = {
    item["label"]: hashlib.sha256(bytes(item.get("data") or b"")).hexdigest()
    for item in fake_st.downloads
}
if not (
    fake_st.calls.get("download_button") == 6
    and download_hashes == expected_download_hashes
):
    raise AssertionError(f"V4.8 exact download contract failed: {download_hashes}")

markup = "\n".join(fake_st.markdown_payloads)
messages = "\n".join(fake_st.messages)
if not (
    rendered.get("authenticated") is True
    and rendered.get("hardware_executable") is False
    and len(section_headers) == 1
    and "AUTHENTICATED · RESEARCH_ONLY · EXACT STREAMS 8/8 · ZERO PROVIDER / ZERO JOB" in markup
    and "not fidelity or runtime" in messages
    and v48_ui.EXPECTED_MULTI_SNAPSHOT in messages
    and v48_ui.EXPECTED_PRODUCTION in messages
    and v48_ui.EXPECTED_NEXT_GATE in messages
):
    raise AssertionError("V4.8 isolated render evidence boundary failed")

base_encoding = {"encoding_status": "OFFLINE V4.7 PREDECESSOR", "hardware_executable": True}
projected_base = v48_ui.apply_v48_encoding_state(
    base_encoding, regime="BASE", state=rendered, artifact=artifact
)
projected_bands = v48_ui.apply_v48_encoding_state(
    base_encoding, regime="BANDS", state=rendered, artifact=artifact
)
if projected_base != base_encoding:
    raise AssertionError("V4.8 changed a non-BANDS encoding")
if not (
    projected_bands.get("encoding_status")
    == "V4.8 EXACT ARCHITECTURE REDUCTION · MULTI-SNAPSHOT BLOCKED · HARDWARE BLOCKED"
    and projected_bands.get("hardware_executable") is False
    and projected_bands.get("research_classification") == "RESEARCH_ONLY"
    and projected_bands.get("v48_artifact_sha256") == v48_ui.EXPECTED_ARTIFACT_SHA256
    and projected_bands.get("v48_dated_properties_status") == v48_ui.EXPECTED_OVERALL
):
    raise AssertionError(f"V4.8 BANDS projection failed: {projected_bands}")

spy_counts = {kind: int(st.session_state.get(key, 0)) for kind, key in spy_keys.items()}
if any(spy_counts.values()):
    raise AssertionError(f"V4.8 offline harness observed a forbidden call: {spy_counts}")

V48_HARNESS_STATUS = {
    "apply": "PASS",
    "authentication_checks": 24,
    "download_raw_identities": "6/6 PASS",
    "environment_reads": spy_counts["environment"],
    "independent_checks": 65,
    "load": "PASS",
    "network_calls": spy_counts["network"],
    "normalize": "PASS",
    "provider_calls": spy_counts["provider"],
    "render": "PASS",
    "seal_calls": spy_counts["seal"],
    "transpile_calls": spy_counts["transpile"],
}

st.caption(
    "V4.8 OFFLINE APPTEST HARNESS · 24/24 AUTH · 65/65 INDEPENDENT · POSITIVE SURFACE READY · "
    "LOAD PASS · NORMALIZE PASS · FAKE RENDER PASS · APPLY PASS · DOWNLOAD RAW IDENTITIES 6/6 PASS · "
    f"PROVIDER SPY CALLS · {spy_counts['provider']} · TRANSPILE SPY CALLS · {spy_counts['transpile']} · "
    f"SEAL SPY CALLS · {spy_counts['seal']} · NETWORK SPY CALLS · {spy_counts['network']} · "
    f"ENV/CREDENTIAL SPY READS · {spy_counts['environment']} · BACKEND RUNS · 0 · SIMULATOR JOBS · 0 · "
    "QPU JOBS · 0 · HARDWARE EXECUTABLE · FALSE · REAL SEALED V4.8 EVIDENCE · "
    "OFFLINE MARKET FIXTURES EXCLUDED FROM SCIENTIFIC EVIDENCE"
)
