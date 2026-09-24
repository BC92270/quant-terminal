"""Institutional Streamlit surface for the V5.0 hardware-evidence control plane."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .engine.checker import EXPECTED_CHECK_COUNT, validate_artifact
from .engine.evaluator import ARTIFACT, PROTOCOL
from .engine.evidence import SOURCE_CATALOG, read_json_strict
from .engine.validation import REPORT


SectionHeader = Callable[[str, str, str], None]

EXPECTED_ARTIFACT_RAW_SHA256 = "3ef7ec081ca45db61da8248d687e60e6da6c9e5eabd1d9eba58626489b865140"
EXPECTED_REPORT_RAW_SHA256 = "d7562587cc26cec7121becfe999e6ba6ed62fefb6ad0c3156e0e215736716b7b"
EXPECTED_PROTOCOL_RAW_SHA256 = "b4c17c8ebfb5532f0e1967610fd46a69ca735296ea73ca8461dff467fb081b3a"
EXPECTED_SOURCE_CATALOG_RAW_SHA256 = "300db84caf78af39fbf1266138ac4f2baa263a2db04544b5593da9575792ce1a"
EXPECTED_UI_AUTH_CHECK_COUNT = 12


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


def default_v50_artifact_path() -> Path:
    return _root() / ARTIFACT


def load_v50_ui_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v50_artifact_path()
    if not target.is_absolute():
        target = _root() / target
    errors: list[str] = []
    try:
        artifact = read_json_strict(target)
        report_path = _root() / REPORT
        protocol_path = _root() / PROTOCOL
        source_path = _root() / SOURCE_CATALOG
        report = read_json_strict(report_path)
        independent = validate_artifact(
            artifact,
            root=_root(),
            artifact_raw_sha256=_raw(target),
        )
        decisions = _mapping(artifact.get("decisions"))
        epoch_gate = _mapping(artifact.get("historical_epoch_gate"))
        architecture = _mapping(artifact.get("architecture_gate"))
        boundary = _mapping(artifact.get("claim_boundary"))
        checks = {
            "artifact_regular": target.is_file() and not target.is_symlink(),
            "artifact_raw": _raw(target) == EXPECTED_ARTIFACT_RAW_SHA256,
            "report_regular": report_path.is_file() and not report_path.is_symlink(),
            "report_raw": _raw(report_path) == EXPECTED_REPORT_RAW_SHA256,
            "protocol_raw": _raw(protocol_path) == EXPECTED_PROTOCOL_RAW_SHA256,
            "source_catalog_raw": _raw(source_path) == EXPECTED_SOURCE_CATALOG_RAW_SHA256,
            "independent_checker": independent.get("valid") is True
            and independent.get("check_count") == EXPECTED_CHECK_COUNT,
            "validation_report": report.get("valid") is True
            and report.get("artifact_raw_sha256") == EXPECTED_ARTIFACT_RAW_SHA256,
            "decision": decisions.get("overall")
            == "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO",
            "epoch_gate": epoch_gate.get("pass") is True,
            "architecture_gate": architecture.get("all_cells_pass") is False,
            "boundary": boundary.get("hardware_executable") is False
            and boundary.get("current_hardware_evidence") is False,
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
        errors.append("V5.0 UI authentication count drift")
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


def normalize_v50_artifact(
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
    epoch_gate = _mapping(artifact.get("historical_epoch_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    return {
        "authenticated": True,
        "decision": decisions.get("overall"),
        "provider_discovery": decisions.get("current_provider_discovery"),
        "v5_execution": decisions.get("v5_execution"),
        "observed_epochs": epoch_gate.get("observed_distinct_authentic_epochs"),
        "required_epochs": epoch_gate.get("required_distinct_authentic_epochs"),
        "matrix_cells": architecture.get("snapshot_seed_cell_count"),
        "required_maximum_direct_cx": architecture.get(
            "cross_snapshot_required_maximum_direct_cx"
        ),
        "hardware_executable": False,
        "research_classification": "RESEARCH_ONLY",
    }


def apply_v50_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(encoding or {}))
    if (
        str(regime).upper() != "BANDS"
        or state.get("authenticated") is not True
        or not isinstance(artifact, Mapping)
    ):
        return projected
    decisions = _mapping(artifact.get("decisions"))
    epoch_gate = _mapping(artifact.get("historical_epoch_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    projected.update(
        {
            "encoding_status": "V5.0 PRE-ADMISSION · EPOCH GATE PASS · ARCHITECTURE NO-GO · EXECUTION CLOSED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
            "v50_artifact_sha256": artifact.get("artifact_sha256"),
            "v50_decision": decisions.get("overall"),
            "v50_provider_discovery": decisions.get("current_provider_discovery"),
            "v50_execution": decisions.get("v5_execution"),
            "v50_authentic_epochs": epoch_gate.get("observed_distinct_authentic_epochs"),
            "v50_matrix_cells": architecture.get("snapshot_seed_cell_count"),
            "v50_required_maximum_direct_cx": architecture.get(
                "cross_snapshot_required_maximum_direct_cx"
            ),
        }
    )
    return projected


def _download(path: Path, expected: str) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if path.is_file() and not path.is_symlink() and hashlib.sha256(raw).hexdigest() == expected:
        return raw
    return None


def _epoch_table(artifact: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Backend": row.get("backend_name"),
                "Backend version": row.get("backend_version"),
                "Epoch": row.get("source_epoch"),
                "Wheel": _mapping(row.get("distribution")).get("version"),
                "Raw properties SHA": str(row.get("properties_raw_sha256", ""))[:16] + "…",
                "Normalized SHA": str(row.get("normalized_properties_sha256", ""))[:16] + "…",
                "Healthy component": row.get("largest_fault_excluded_component_qubits"),
                "Error ceiling <": row.get("strict_error_ceiling_exclusive"),
                "Duration ceiling <": row.get("strict_duration_ceiling_exclusive"),
                "Required max CX": row.get("required_maximum_direct_cx"),
                "Evidence class": "HISTORICAL OFFLINE",
            }
            for row in _rows(artifact.get("historical_observations"))
        ]
    )


def _matrix_table(artifact: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Backend": row.get("backend_name"),
                "Epoch": row.get("source_epoch"),
                "Seed": row.get("seed"),
                "Logical Q": row.get("logical_qubits"),
                "Capacity": row.get("fault_excluded_capacity"),
                "Direct CX": row.get("direct_cx"),
                "Target max": row.get("required_maximum_direct_cx"),
                "Reduction required": row.get("cx_reduction_required"),
                "Capacity gate": "PASS" if row.get("capacity_pass") else "FAIL",
                "Route gate": "PASS" if row.get("route_replay_pass") else "FAIL",
                "Error gate": "PASS" if row.get("error_screen_pass") else "FAIL",
                "Duration gate": "PASS" if row.get("duration_screen_pass") else "FAIL",
                "Cell": row.get("status"),
            }
            for row in _rows(artifact.get("snapshot_seed_matrix"))
        ]
    )


def render_v50_control_plane(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    state = normalize_v50_artifact(artifact, integrity=integrity)
    section_header(
        "V5.0 · Hardware-Evidence Control Plane",
        "AUTHENTICATED HISTORICAL COHORT → 32-CELL NECESSARY-SCREEN MATRIX → FAIL-CLOSED PROVIDER BOUNDARY",
        "The missing epoch evidence is now resolved with pinned official distribution bytes. The unchanged architecture is evaluated across every epoch and remains a scientific no-go; execution stays closed.",
    )
    if state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        st.error("V5.0 authentication failed. The entire control plane is masked fail-closed.")
        return state

    epoch_gate = _mapping(artifact.get("historical_epoch_gate"))
    architecture = _mapping(artifact.get("architecture_gate"))
    decisions = _mapping(artifact.get("decisions"))
    observations = _rows(artifact.get("historical_observations"))
    catalog = read_json_strict(_root() / SOURCE_CATALOG)
    required_maximum = int(architecture.get("cross_snapshot_required_maximum_direct_cx", 0))
    observed_minimum = int(architecture.get("observed_minimum_direct_cx", 0))
    observed_maximum = int(architecture.get("observed_maximum_direct_cx", 0))

    st.markdown(
        f'''<div class="qv50-hero">
        <div class="qv50-k">AUTHENTICATED · V5.0 PRE-ADMISSION · HISTORICAL OFFLINE · RESEARCH_ONLY · ZERO PROVIDER / ZERO JOB</div>
        <div class="qv50-t">The evidence gap is closed. The architecture gap is not.</div>
        <div class="qv50-s"><b>{epoch_gate.get("observed_distinct_authentic_epochs")} distinct epochs</b> pass the frozen cohort gate across two Heron rev.2 devices and two pinned official distributions. The unchanged exact architecture still requires <b>{observed_minimum:,}–{observed_maximum:,} direct CX</b> against the strict cross-snapshot maximum of <b>{required_maximum:,}</b>. This is a 32-cell architecture NO-GO, not current hardware evidence.</div>
        <div class="qv50-strip"><span>EPOCH COHORT · PASS</span><span>TOPOLOGY · 4 / 4 MATCH</span><span>CELLS · 0 / 32 PASS</span><span>PROVIDER · DENIED</span><span>V5 EXECUTION · CLOSED</span></div>
        </div>
        <style>
        .qv50-hero{{border:1px solid rgba(45,212,191,.32);border-radius:22px;padding:22px 24px;margin:8px 0 16px;background:radial-gradient(circle at 88% 5%,rgba(6,182,212,.19),transparent 38%),radial-gradient(circle at 12% 100%,rgba(168,85,247,.14),transparent 42%),linear-gradient(128deg,rgba(5,20,28,.99),rgba(12,17,38,.99));box-shadow:0 0 62px rgba(45,212,191,.08)}}
        .qv50-k{{font-size:.61rem;letter-spacing:.16em;color:#5eead4;font-weight:850}}.qv50-t{{font-size:1.3rem;line-height:1.3;color:#f8fafc;font-weight:880;margin:8px 0}}.qv50-s{{font-size:.79rem;line-height:1.65;color:#cbd5e1;max-width:1160px}}.qv50-strip{{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}}.qv50-strip span{{border:1px solid rgba(94,234,212,.22);border-radius:999px;padding:5px 9px;background:rgba(6,78,89,.25);font-size:.58rem;letter-spacing:.075em;color:#ccfbf1;font-weight:800}}
        </style>''',
        unsafe_allow_html=True,
    )
    metrics = st.columns(6)
    metrics[0].metric("Authentic epochs", "4 / 3", "gate satisfied")
    metrics[1].metric("Matrix", "32 cells", "4 epochs × 8 seeds")
    metrics[2].metric("Strict target", f"≤ {required_maximum:,} CX", "cross-snapshot")
    metrics[3].metric("Best observed", f"{observed_minimum:,} CX", f"+{observed_minimum-required_maximum:,} over")
    metrics[4].metric("Provider calls", "0", "discovery denied")
    metrics[5].metric("QPU jobs", "0", "execution closed")
    st.success("HISTORICAL EPOCH GATE · PASS · 4 distinct raw files / normalized vectors / source epochs")
    st.error(decisions.get("overall", "MASKED"))
    st.warning(
        "Historical fake-provider calibration snapshots are device-derived offline evidence. "
        "They are not a current calibration export, a hardware run, fidelity evidence, or production readiness."
    )

    control_tab, cohort_tab, matrix_tab, architecture_tab, provenance_tab, governance_tab = st.tabs(
        ["CONTROL PLANE", "EPOCH COHORT", "32-CELL MATRIX", "ARCHITECTURE", "PROVENANCE", "GOVERNANCE"]
    )
    with control_tab:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Gate": "Distinct historical epochs", "Required": "≥3", "Observed": "4", "State": "PASS"},
                    {"Gate": "Heron rev.2 topology", "Required": "same 156Q / 352 directed CZ", "Observed": "4 / 4 exact", "State": "PASS"},
                    {"Gate": "Fault-excluded capacity", "Required": "all 32 cells", "Observed": "32 / 32", "State": "PASS"},
                    {"Gate": "Exact route replay", "Required": "all 32 cells", "Observed": "32 / 32", "State": "PASS"},
                    {"Gate": "Strict error envelope", "Required": "all 32 cells", "Observed": "0 / 32", "State": "FAIL"},
                    {"Gate": "Idealized duration envelope", "Required": "all 32 cells", "Observed": "0 / 32", "State": "FAIL"},
                    {"Gate": "Current-provider discovery", "Required": "all upstream gates pass", "Observed": decisions.get("current_provider_discovery"), "State": "DENIED"},
                    {"Gate": "V5 execution", "Required": "separate controlled protocol + human approval", "Observed": decisions.get("v5_execution"), "State": "CLOSED"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.code(decisions.get("next_permissible_test", "MASKED"))

    with cohort_tab:
        st.dataframe(_epoch_table(artifact), width="stretch", hide_index=True)
        st.caption(
            "Four distinct epochs satisfy the V4.9 cohort definition. Both devices share the exact directed topology; "
            "device identity is not conflated with epoch identity."
        )
        st.error("Synthetic jitter, bootstrap resampling, copied files and metadata rewrites remain inadmissible.")

    with matrix_tab:
        st.dataframe(_matrix_table(artifact), width="stretch", hide_index=True, height=540)
        st.caption(
            "Each row is independently binding. Capacity and exact-route replay pass; every strict error and duration "
            "necessary screen fails. No mean, vote, or favorable epoch can rescue another cell."
        )

    with architecture_tab:
        per_seed: list[dict[str, Any]] = []
        matrix = _rows(artifact.get("snapshot_seed_matrix"))
        for seed in sorted({int(row["seed"]) for row in matrix}):
            seed_cells = [row for row in matrix if int(row["seed"]) == seed]
            direct_cx = int(seed_cells[0]["direct_cx"])
            per_seed.append(
                {
                    "Seed": seed,
                    "Logical Q": seed_cells[0]["logical_qubits"],
                    "Direct CX": direct_cx,
                    "Cross-snapshot target": required_maximum,
                    "Exact reduction still required": direct_cx - required_maximum,
                    "Cells passed": sum(bool(row["cell_admission_pass"]) for row in seed_cells),
                    "Cells evaluated": len(seed_cells),
                }
            )
        st.dataframe(pd.DataFrame(per_seed), width="stretch", hide_index=True)
        st.error(
            f"The best seed still needs an exact reduction of {observed_minimum-required_maximum:,} direct CX. "
            "This rejects the frozen architecture only; a formally equivalent new architecture remains a valid research target."
        )
        st.info(
            "Strict error exclusive ceiling = ceil(1 / best reported healthy CZ error). "
            "Strict duration maximum = (ceil(max T2 ticks / minimum CZ ticks) − 1) × 78; "
            "its exclusive ceiling is that maximum plus one. "
            "Both are optimistic necessary screens, never a fidelity or runtime prediction."
        )

    with provenance_tab:
        distributions = _rows(catalog.get("distributions"))
        st.markdown("**Pinned official distributions**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Package": row.get("package"),
                        "Version": row.get("version"),
                        "Uploaded": row.get("uploaded_at"),
                        "Wheel SHA-256": row.get("wheel_sha256"),
                        "PyPI metadata": row.get("pypi_metadata_url"),
                    }
                    for row in distributions
                ]
            ),
            width="stretch",
            hide_index=True,
            column_config={"PyPI metadata": st.column_config.LinkColumn("PyPI metadata")},
        )
        st.markdown("**Sealed control-plane evidence**")
        paths = [
            ("V5.0 sealed artifact", _root() / ARTIFACT, EXPECTED_ARTIFACT_RAW_SHA256, "SEALED_V5_0_PRE_ADMISSION_ARTIFACT.json"),
            ("Independent validation report", _root() / REPORT, EXPECTED_REPORT_RAW_SHA256, "SEALED_V5_0_VALIDATION_REPORT.json"),
            ("V5.0 protocol", _root() / PROTOCOL, EXPECTED_PROTOCOL_RAW_SHA256, "V5_0_PROTOCOL.json"),
            ("Pinned source catalog", _root() / SOURCE_CATALOG, EXPECTED_SOURCE_CATALOG_RAW_SHA256, "V5_0_SOURCE_CATALOG.json"),
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
                key=f"{key_prefix}_v50_download_{index}",
            )
        with st.expander("Raw snapshot identities", expanded=False):
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Snapshot": row.get("snapshot_id"),
                            "Properties raw SHA-256": row.get("properties_raw_sha256"),
                            "Configuration raw SHA-256": row.get("configuration_raw_sha256"),
                            "Normalized properties SHA-256": row.get("normalized_properties_sha256"),
                        }
                        for row in observations
                    ]
                ),
                width="stretch",
                hide_index=True,
            )

    with governance_tab:
        for index, label in enumerate(
            (
                "Treat historical snapshots as current calibration",
                "Average away a failed epoch × seed cell",
                "Change the frozen threshold after observation",
                "Read or persist provider credentials",
                "Import a provider SDK from this control plane",
                "Discover or select a live backend",
                "Start a Runtime session or primitive",
                "Submit simulator, backend or QPU work",
                "Claim hardware readiness, utility or quantum advantage",
            )
        ):
            st.button(label, disabled=True, key=f"{key_prefix}_v50_governance_{index}")
        st.error(
            "RESEARCH_ONLY · current_hardware_evidence=false · hardware_executable=false · "
            "provider discovery DENIED · V5 EXECUTION CLOSED"
        )
    return state


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "apply_v50_encoding_state",
    "default_v50_artifact_path",
    "load_v50_ui_artifact",
    "normalize_v50_artifact",
    "render_v50_control_plane",
]
