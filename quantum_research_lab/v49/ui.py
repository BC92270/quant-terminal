"""Institutional Streamlit surface for Quantum Lab V4.9."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .engine.checker import EXPECTED_CHECK_COUNT, read_json_strict, validate_artifact
from .engine.evaluator import ARTIFACT_RELATIVE_PATH
from .engine.validation import REPORT_RELATIVE_PATH


SectionHeader = Callable[[str, str, str], None]

EXPECTED_ARTIFACT_RAW_SHA256 = "1622e2ab0260ea12ef93685ddc75ca58254437b6c9b124c7fd35f8e012457e2b"
EXPECTED_REPORT_RAW_SHA256 = "13c6265f28d766b846c964943c110981a404bc6aabad577e50867bd6484b23ad"
EXPECTED_PROTOCOL_RAW_SHA256 = "1a695b518d2352ccc5d8733ef5253fc6a381917e0611751109ca7c6cf76fbb30"
EXPECTED_CATALOG_RAW_SHA256 = "757468e1a8fca58f1cfadd65ccc6529142fdf32c68dfabcf09481be16aa42207"
EXPECTED_NORMALIZED_RAW_SHA256 = "751525edebb8ce858b3bf9fd0c127de5fc2426477df30eb83d7662056ee2ae5b"
EXPECTED_UI_AUTH_CHECK_COUNT = 10


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def default_v49_artifact_path() -> Path:
    return _root() / ARTIFACT_RELATIVE_PATH


def load_v49_ui_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v49_artifact_path()
    if not target.is_absolute():
        target = _root() / target
    errors: list[str] = []
    try:
        artifact = read_json_strict(target)
        report_path = _root() / REPORT_RELATIVE_PATH
        protocol_path = _root() / "quantum_research_lab/v49/PROTOCOL.json"
        catalog_path = _root() / "quantum_research_lab/v49/snapshots/catalog.json"
        normalized_path = _root() / "quantum_research_lab/v49/snapshots/normalized.json"
        validation = read_json_strict(report_path)
        independent = validate_artifact(
            artifact,
            root=_root(),
            artifact_raw_sha256=_raw(target),
        )
        checks = {
            "artifact_regular": target.is_file() and not target.is_symlink(),
            "artifact_raw": _raw(target) == EXPECTED_ARTIFACT_RAW_SHA256,
            "report_regular": report_path.is_file() and not report_path.is_symlink(),
            "report_raw": _raw(report_path) == EXPECTED_REPORT_RAW_SHA256,
            "protocol_raw": _raw(protocol_path) == EXPECTED_PROTOCOL_RAW_SHA256,
            "catalog_raw": _raw(catalog_path) == EXPECTED_CATALOG_RAW_SHA256,
            "normalized_raw": _raw(normalized_path) == EXPECTED_NORMALIZED_RAW_SHA256,
            "independent_checker": independent.get("valid") is True and independent.get("check_count") == EXPECTED_CHECK_COUNT,
            "validation_report": validation.get("valid") is True and validation.get("artifact_raw_sha256") == EXPECTED_ARTIFACT_RAW_SHA256,
            "boundary": _mapping(artifact.get("claim_boundary")).get("hardware_executable") is False,
        }
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_authenticated_load"],
            "valid": False,
        }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        errors.append("V4.9 UI authentication count drift")
    failed = [name for name, passed in checks.items() if passed is not True]
    integrity = {
        "check_count": len(checks),
        "checks": checks,
        "errors": errors + list(independent.get("errors") or []),
        "failed_checks": failed + list(independent.get("failed_checks") or []),
        "independent_checker": independent,
        "valid": not errors and not failed and independent.get("valid") is True,
    }
    return artifact if integrity["valid"] else None, integrity


def normalize_v49_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    integrity: bool | None,
) -> dict[str, Any]:
    if integrity is not True or not isinstance(artifact, Mapping):
        return {
            "authenticated": False,
            "decision": "MASKED_FAIL_CLOSED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
        }
    decisions = _mapping(artifact.get("decisions"))
    snapshot = _mapping(artifact.get("snapshot_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    return {
        "authenticated": True,
        "decision": decisions.get("overall"),
        "provider_discovery": decisions.get("provider_discovery"),
        "v5_entry": decisions.get("v5_hardware_protocol_entry"),
        "observed_epochs": snapshot.get("observed_distinct_authentic_epochs"),
        "required_epochs": snapshot.get("required_distinct_authentic_epochs"),
        "maximum_direct_cx": architecture.get("observed_maximum_direct_cx"),
        "required_maximum_direct_cx": architecture.get("required_maximum_direct_cx"),
        "hardware_executable": False,
        "research_classification": "RESEARCH_ONLY",
    }


def apply_v49_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(encoding or {}))
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        return projected
    decisions = _mapping(artifact.get("decisions"))
    snapshot = _mapping(artifact.get("snapshot_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    projected.update(
        {
            "encoding_status": "V4.9 TERMINAL OFFLINE ADMISSION · NOT EVALUABLE · V5 CLOSED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
            "v49_artifact_sha256": artifact.get("artifact_sha256"),
            "v49_decision": decisions.get("overall"),
            "v49_provider_discovery": decisions.get("provider_discovery"),
            "v49_v5_entry": decisions.get("v5_hardware_protocol_entry"),
            "v49_authentic_epochs": snapshot.get("observed_distinct_authentic_epochs"),
            "v49_maximum_direct_cx": architecture.get("observed_maximum_direct_cx"),
        }
    )
    return projected


def _download(path: Path, expected: str) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw if path.is_file() and not path.is_symlink() and hashlib.sha256(raw).hexdigest() == expected else None


def _seed_table(artifact: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Seed": row.get("seed"),
                "Logical Q": row.get("logical_qubits"),
                "Direct CX": row.get("direct_cx"),
                "Target max": int(row.get("strict_error_ceiling_exclusive", 0)) - 1,
                "Additional reduction required": row.get("cx_reduction_required_to_admissible_maximum"),
                "Capacity": "PASS" if row.get("capacity_pass") else "FAIL",
                "Route replay": "PASS" if row.get("route_replay_pass") else "FAIL",
                "Error screen": "PASS" if row.get("error_screen_pass") else "FAIL",
                "Duration screen": "PASS" if row.get("duration_screen_pass") else "FAIL",
            }
            for row in _rows(artifact.get("seed_admission"))
        ]
    )


def render_v49_admission_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    state = normalize_v49_artifact(artifact, integrity=integrity)
    section_header(
        "V4.9 · Terminal Offline Admission Dossier",
        "AUTHENTIC EPOCH GATE → EXACT RESOURCE GATE → PROVIDER DISCOVERY DECISION → V5 CLOSED BY DEFAULT",
        "The final offline V4 decision surface. It preserves a scientifically valid negative or not-evaluable outcome and never converts missing evidence into readiness.",
    )
    if state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        st.error("V4.9 authentication failed. Every admission result is masked fail-closed.")
        return state

    snapshot = _mapping(artifact.get("snapshot_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    decisions = _mapping(artifact.get("decisions"))
    catalog = read_json_strict(_root() / "quantum_research_lab/v49/snapshots/catalog.json")

    st.markdown(
        f'''<div class="qv49-hero">
        <div class="qv49-k">AUTHENTICATED · FINAL OFFLINE V4 PHASE · RESEARCH_ONLY · ZERO PROVIDER / ZERO JOB</div>
        <div class="qv49-t">Evidence is insufficient for multi-epoch admission, and the frozen reference architecture remains far outside the strict resource envelope.</div>
        <div class="qv49-s">Authentic epochs: <b>{snapshot.get("observed_distinct_authentic_epochs")} / {snapshot.get("required_distinct_authentic_epochs")}</b>. Frozen V4.8 direct CX: <b>{int(architecture.get("observed_minimum_direct_cx", 0)):,}–{int(architecture.get("observed_maximum_direct_cx", 0)):,}</b>. Required maximum: <b>{int(architecture.get("required_maximum_direct_cx", 0)):,}</b>. Provider discovery is denied and V5 remains closed.</div>
        <div class="qv49-strip"><span>EPOCH GATE · NOT EVALUABLE</span><span>REFERENCE ARCHITECTURE · FAIL</span><span>PROVIDER DISCOVERY · DENIED</span><span>V5 · CLOSED</span></div>
        </div>
        <style>
        .qv49-hero{{border:1px solid rgba(244,114,182,.34);border-radius:22px;padding:21px 23px;margin:8px 0 16px;background:radial-gradient(circle at 88% 8%,rgba(126,34,206,.24),transparent 38%),linear-gradient(128deg,rgba(29,8,35,.99),rgba(12,18,38,.99));box-shadow:0 0 56px rgba(168,85,247,.09)}}
        .qv49-k{{font-size:.61rem;letter-spacing:.16em;color:#f0abfc;font-weight:850}}.qv49-t{{font-size:1.2rem;line-height:1.3;color:#f8fafc;font-weight:850;margin:8px 0}}.qv49-s{{font-size:.78rem;line-height:1.6;color:#c8bdd4;max-width:1140px}}.qv49-strip{{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}}.qv49-strip span{{border:1px solid rgba(216,180,254,.22);border-radius:999px;padding:5px 9px;background:rgba(30,27,75,.58);font-size:.58rem;letter-spacing:.075em;color:#f3e8ff;font-weight:780}}
        </style>''',
        unsafe_allow_html=True,
    )
    metrics = st.columns(6)
    metrics[0].metric("Authentic epochs", "1 / 3", "2 missing")
    metrics[1].metric("Seed cells", "8 / 8", "evaluated offline")
    metrics[2].metric("Min direct CX", f"{int(architecture.get('observed_minimum_direct_cx', 0)):,}", "reference")
    metrics[3].metric("Required max", f"{int(architecture.get('required_maximum_direct_cx', 0)):,}", "strict necessary gate")
    metrics[4].metric("Provider calls", "0", "discovery denied")
    metrics[5].metric("QPU jobs", "0", "V5 closed")
    st.error(decisions.get("overall", "MASKED"))
    st.warning("This is a terminal offline admission decision, not hardware evidence. A not-evaluable result is preserved rather than repaired with synthetic epochs.")

    decision_tab, epochs_tab, gap_tab, matrix_tab, provenance_tab, governance_tab = st.tabs(
        ["DECISION", "EPOCH REGISTRY", "RESOURCE GAP", "CELL MATRIX", "PROVENANCE", "GOVERNANCE"]
    )
    with decision_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Gate": "Authentic multi-epoch cohort", "Required": "3 distinct epochs", "Observed": "1", "Status": "NOT EVALUABLE"},
                    {"Gate": "Strict direct-CX error screen", "Required": "max ≤ 963", "Observed": f"max {int(architecture.get('observed_maximum_direct_cx', 0)):,}", "Status": "FAIL"},
                    {"Gate": "Idealized duration screen", "Required": "all seeds < 613,392", "Observed": "8 / 8 fail", "Status": "FAIL"},
                    {"Gate": "Provider discovery", "Required": "both gates pass", "Observed": decisions.get("provider_discovery"), "Status": "DENIED"},
                    {"Gate": "V5 protocol entry", "Required": "V4.9 PASS", "Observed": decisions.get("v5_hardware_protocol_entry"), "Status": "CLOSED"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.code(decisions.get("next_permissible_test", "MASKED"))

    with epochs_tab:
        st.markdown("**Authenticated observations**")
        st.dataframe(pd.DataFrame(_rows(catalog.get("observed"))), width="stretch", hide_index=True)
        st.markdown("**Reserved evidence slots**")
        st.dataframe(pd.DataFrame(_rows(catalog.get("open_slots"))), width="stretch", hide_index=True)
        st.error("Copies, renamed files, metadata rewrites, bootstrap samples and synthetic jitter never count as new epochs.")

    with gap_tab:
        st.dataframe(_seed_table(artifact), width="stretch", hide_index=True)
        st.error("Every seed requires a further exact reduction of at least 795,027 CX before satisfying the current strict necessary ceiling. This is a no-go for the frozen reference architecture, not evidence against every possible architecture.")

    with matrix_tab:
        st.dataframe(pd.DataFrame(_rows(artifact.get("snapshot_seed_matrix"))), width="stretch", hide_index=True)
        st.caption("The matrix currently has one authentic snapshot × eight seeds. It cannot become a robustness matrix until two additional authentic epochs are admitted.")

    with provenance_tab:
        paths = [
            ("Sealed V4.9 artifact", _root() / ARTIFACT_RELATIVE_PATH, EXPECTED_ARTIFACT_RAW_SHA256, "SEALED_V4_9_ADMISSION_ARTIFACT.json"),
            ("Independent validation report", _root() / REPORT_RELATIVE_PATH, EXPECTED_REPORT_RAW_SHA256, "SEALED_V4_9_VALIDATION_REPORT.json"),
            ("V4.9 protocol", _root() / "quantum_research_lab/v49/PROTOCOL.json", EXPECTED_PROTOCOL_RAW_SHA256, "V4_9_PROTOCOL.json"),
            ("Authentic epoch registry", _root() / "quantum_research_lab/v49/snapshots/catalog.json", EXPECTED_CATALOG_RAW_SHA256, "V4_9_SNAPSHOT_CATALOG.json"),
            ("Normalized cohort", _root() / "quantum_research_lab/v49/snapshots/normalized.json", EXPECTED_NORMALIZED_RAW_SHA256, "V4_9_NORMALIZED_COHORT.json"),
        ]
        st.dataframe(
            pd.DataFrame([{"Evidence": label, "Raw SHA-256": expected} for label, _, expected, _ in paths]),
            width="stretch",
            hide_index=True,
        )
        columns = st.columns(2)
        for index, (label, path, expected, filename) in enumerate(paths):
            payload = _download(path, expected)
            columns[index % 2].download_button(
                f"Download {label}",
                data=payload or b"",
                file_name=filename,
                mime="application/json",
                disabled=payload is None,
                key=f"{key_prefix}_v49_download_{index}",
            )

    with governance_tab:
        for index, label in enumerate(
            (
                "Count a copied or renamed file as a new epoch",
                "Generate a synthetic replacement epoch",
                "Average away a failed snapshot × seed cell",
                "Change the ≤963 target after observing results",
                "Read provider credentials",
                "Discover a current provider backend",
                "Submit a simulator, backend or QPU job",
                "Open V5 without a sealed V4.9 PASS",
                "Claim hardware readiness, utility or quantum advantage",
            )
        ):
            st.button(label, disabled=True, key=f"{key_prefix}_v49_governance_{index}")
        st.error("RESEARCH_ONLY · hardware_executable=false · provider discovery DENIED · V5 CLOSED")
    return state


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "apply_v49_encoding_state",
    "default_v49_artifact_path",
    "load_v49_ui_artifact",
    "normalize_v49_artifact",
    "render_v49_admission_panel",
]
