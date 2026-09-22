"""Fail-closed institutional evidence surface for Quantum Lab V4.4.

The panel authenticates and displays the sealed offline FakeMarrakesh result.
It never imports Qiskit, rebuilds canaries, accesses credentials, contacts a
provider, transpiles a full workload or submits a job.
"""

from __future__ import annotations

import copy
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v44_named_backend_routing import (
    EXPECTED_SEEDS,
    EXPECTED_SNAPSHOT_RAW_SHA256,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_TOOLCHAIN_RAW_SHA256,
    EXPECTED_TOOLCHAIN_SHA256,
    EXPECTED_V43_ARTIFACT_RAW_SHA256,
    EXPECTED_V43_ARTIFACT_SHA256,
    EXPECTED_V43_FREEZE_RAW_SHA256,
    EXPECTED_V43_FREEZE_SHA256,
    EXPECTED_WIDTHS,
    TARGET_BASIS,
    TARGET_QUBITS,
    authenticate_v43_parent,
    canonical_json_sha256,
    load_v44_snapshot,
    load_v44_spec,
    load_v44_toolchain,
    raw_file_sha256,
    read_json_strict,
)
from .phase3_v44_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CANARY_BUNDLE_SHA256,
    EXPECTED_CANARY_ROOT_SHA256,
    EXPECTED_CAPACITY_PRECHECK_SHA256,
    EXPECTED_SOURCE_RAW_SHA256,
)


SectionHeader = Callable[[str, str, str], None]
EXPECTED_UI_AUTH_CHECK_COUNT = 24
EXPECTED_OVERALL = "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB"
EXPECTED_PRODUCTION = "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION"
EXPECTED_NEXT_GATE = "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY"
NOT_RUN = "NOT_RUN_CAPACITY_PRECHECK_REJECTED"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _short_sha(value: Any) -> str:
    text = str(value or "")
    return f"{text[:12]}…{text[-8:]}" if len(text) == 64 else "MASKED"


def _fmt(value: Any, *, signed: bool = False) -> str:
    if value is None or isinstance(value, bool):
        return "MASKED"
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    return f"{'+' if signed and number >= 0 else ''}{number:,}"


def default_v44_ui_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs/quantum_phase3/v44_named_backend"
        / "SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json"
    )


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_validate(raw: bytes, context_sha256: str) -> dict[str, Any]:
    del context_sha256
    errors: list[str] = []
    try:
        artifact = json.loads(raw.decode("utf-8"))
        if not isinstance(artifact, dict):
            raise ValueError("Artifact is not a JSON object.")
    except Exception as exc:
        return {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "valid": False,
        }
    root = Path(__file__).resolve().parents[1]
    try:
        spec = load_v44_spec(root=root)
        snapshot = load_v44_snapshot(root=root)
        toolchain = load_v44_toolchain(root=root)
        parent = authenticate_v43_parent(root=root)
    except Exception as exc:
        spec = snapshot = toolchain = {}
        parent = {"valid": False, "errors": [str(exc)]}
        errors.append(str(exc))
    capacity = _mapping(artifact.get("capacity_precheck"))
    capacity_rows = _rows(capacity.get("capacity_rows"))
    evidence = _mapping(artifact.get("canary_evidence"))
    bundle = _mapping(evidence.get("canonical_canary_bundle"))
    canaries = _rows(bundle.get("accepted_canaries"))
    negative = _mapping(bundle.get("mandatory_negative_canary"))
    boundary = _mapping(artifact.get("claim_boundary"))
    decisions = _mapping(artifact.get("decisions"))
    parent_link = _mapping(artifact.get("parent"))

    checks: dict[str, bool] = {
        "artifact_raw_identity": hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": bool(artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and artifact.get("artifact_sha256") == canonical_json_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})),
        "source_raw_identity": raw_file_sha256(root / "quantum_research_lab/phase3_v44_named_backend_routing.py") == EXPECTED_SOURCE_RAW_SHA256,
        "spec_raw_semantic_identity": bool(spec.get("v44_spec_sha256") == EXPECTED_SPEC_SHA256 and raw_file_sha256(root / "quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json") == EXPECTED_SPEC_RAW_SHA256),
        "snapshot_raw_semantic_identity": bool(snapshot.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256 and raw_file_sha256(root / "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json") == EXPECTED_SNAPSHOT_RAW_SHA256),
        "toolchain_raw_semantic_identity": bool(toolchain.get("manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256 and raw_file_sha256(root / "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json") == EXPECTED_TOOLCHAIN_RAW_SHA256),
        "v43_parent_and_191_immutable_paths": bool(parent.get("valid") is True and parent.get("immutable_file_count") == 191 and parent.get("immutable_files_exact") is True),
        "artifact_parent_crosslinks": bool(parent_link.get("artifact_raw_file_sha256") == EXPECTED_V43_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256 and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V43_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V43_FREEZE_SHA256),
        "artifact_source_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256 and artifact.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256 and artifact.get("toolchain_manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256),
        "capacity_precheck_identity": bool(capacity.get("capacity_precheck_sha256") == EXPECTED_CAPACITY_PRECHECK_SHA256 and capacity.get("capacity_precheck_sha256") == canonical_json_sha256({key: value for key, value in capacity.items() if key != "capacity_precheck_sha256"})),
        "eight_seed_order": [row.get("seed") for row in capacity_rows] == list(EXPECTED_SEEDS),
        "eight_logical_widths": [row.get("logical_qubits") for row in capacity_rows] == list(EXPECTED_WIDTHS),
        "eight_capacity_rejections": bool(capacity.get("rejected_seed_count") == 8 and all(row.get("capacity_fit") is False for row in capacity_rows)),
        "capacity_deficits": [row.get("capacity_deficit_qubits") for row in capacity_rows] == [-174, -175, -171, -172, -173, -175, -183, -178],
        "persistent_floor_rejection": bool((_mapping(capacity.get("persistent_register_floor"))).get("persistent_register_floor_qubits") == 160 and (_mapping(capacity.get("persistent_register_floor"))).get("capacity_deficit_qubits") == -4),
        "full_workload_metrics_not_run": bool(capacity_rows and all(row.get("full_workload_transpilation") == NOT_RUN and row.get("full_workload_routing") == NOT_RUN and row.get("full_workload_native_gate_counts") == NOT_RUN and row.get("full_workload_routed_depth") == NOT_RUN for row in capacity_rows)),
        "canary_bundle_identity": bool(bundle.get("canary_bundle_sha256") == EXPECTED_CANARY_BUNDLE_SHA256 and bundle.get("canary_bundle_sha256") == canonical_json_sha256({key: value for key, value in bundle.items() if key != "canary_bundle_sha256"})),
        "double_replay_identity": bool(evidence.get("clean_process_replay_count") == 2 and evidence.get("replay_stable") is True and evidence.get("clean_process_replay_sha256") == [EXPECTED_CANARY_BUNDLE_SHA256, EXPECTED_CANARY_BUNDLE_SHA256]),
        "five_canaries_target_valid": bool(len(canaries) == 5 and bundle.get("all_accepted_canaries_isa_and_coupling_valid") is True and bundle.get("canonical_result_root_sha256") == EXPECTED_CANARY_ROOT_SHA256 and all(row.get("status") == "PASS" and row.get("isa_valid") is True and row.get("coupling_valid") is True for row in canaries)),
        "negative_157q_canary": bool(negative.get("input_logical_qubits") == 157 and negative.get("status") == "EXPECTED_REJECTION" and negative.get("exception_class") == "TranspilerError"),
        "decision_exact": decisions.get("overall") == EXPECTED_OVERALL,
        "production_and_next_gate_exact": bool(decisions.get("production_admission") == EXPECTED_PRODUCTION and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE),
        "provider_network_job_boundary": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0),
        "research_hardware_advantage_boundary": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED" and boundary.get("snapshot_is_current_hardware_evidence") is False),
    }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        raise AssertionError(f"V4.4 UI authentication check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(parent.get("errors") or [])
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": not failed and not errors,
    }


def load_v44_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v44_ui_artifact_path()
    try:
        raw = target.read_bytes()
        root = Path(__file__).resolve().parents[1]
        context = hashlib.sha256()
        for relative in (
            "FREEZE_CONTRACT_V4_3.json",
            "quantum_research_lab/phase3_v44_named_backend_routing.py",
            "quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json",
            "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json",
            "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json",
        ):
            candidate = root / relative
            context.update(relative.encode("utf-8") + b"\0" + candidate.read_bytes())
        report = _cached_validate(raw, context.hexdigest())
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else None, report
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["artifact_available"],
            "valid": False,
        }


def normalize_v44_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    snapshot_integrity: bool | None,
    toolchain_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    authenticated = bool(
        isinstance(artifact, Mapping)
        and artifact_integrity is True
        and spec_integrity is True
        and snapshot_integrity is True
        and toolchain_integrity is True
        and parent_integrity is True
    )
    if not authenticated:
        return {
            "authenticated": False,
            "decision": "MASKED_FAIL_CLOSED",
            "hardware_executable": False,
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "reason": "V4.4 evidence is absent, incomplete or unauthenticated.",
        }
    payload = dict(artifact or {})
    capacity = _mapping(payload.get("capacity_precheck"))
    evidence = _mapping(payload.get("canary_evidence"))
    bundle = _mapping(evidence.get("canonical_canary_bundle"))
    boundary = _mapping(payload.get("claim_boundary"))
    decisions = _mapping(payload.get("decisions"))
    return {
        "artifact_sha256": payload.get("artifact_sha256"),
        "authenticated": True,
        "backend_capacity_qubits": capacity.get("backend_capacity_qubits"),
        "backend_name": boundary.get("backend_name"),
        "canary_bundle_sha256": bundle.get("canary_bundle_sha256"),
        "canary_count": bundle.get("accepted_canary_count"),
        "canary_result_root_sha256": bundle.get("canonical_result_root_sha256"),
        "capacity_precheck_sha256": capacity.get("capacity_precheck_sha256"),
        "decision": decisions.get("overall"),
        "full_workload_routing": boundary.get("full_workload_routing"),
        "full_workload_transpilation": boundary.get("full_workload_transpilation"),
        "hardware_executable": boundary.get("hardware_executable"),
        "maximum_capacity_deficit_qubits": capacity.get("maximum_capacity_deficit_qubits"),
        "maximum_logical_qubits": capacity.get("maximum_logical_qubits"),
        "minimum_logical_qubits": capacity.get("minimum_logical_qubits"),
        "network_calls": boundary.get("network_calls"),
        "next_gate": decisions.get("next_falsifiable_gate"),
        "production_admission": decisions.get("production_admission"),
        "provider_calls": boundary.get("provider_calls"),
        "qpu_jobs_submitted": boundary.get("qpu_jobs_submitted"),
        "rejected_seed_count": capacity.get("rejected_seed_count"),
        "research_classification": payload.get("research_classification"),
        "snapshot_sha256": payload.get("snapshot_sha256"),
    }


def _capacity_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    if not state.get("authenticated"):
        return pd.DataFrame(columns=["Seed", "Logical qubits", "Target qubits", "Deficit", "Decision", "Full transpilation", "Full routing"])
    rows = _rows((_mapping(artifact.get("capacity_precheck"))).get("capacity_rows"))
    return pd.DataFrame([
        {
            "Seed": row.get("seed"),
            "Logical qubits": row.get("logical_qubits"),
            "Target qubits": row.get("backend_capacity_qubits"),
            "Deficit": row.get("capacity_deficit_qubits"),
            "Decision": "REJECTED · WIDTH",
            "Full transpilation": row.get("full_workload_transpilation"),
            "Full routing": row.get("full_workload_routing"),
        }
        for row in rows
    ])


def _canary_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    if not state.get("authenticated"):
        return pd.DataFrame(columns=["Canary", "Logical qubits", "Depth", "Instructions", "CZ", "ISA", "Coupling", "Status"])
    bundle = _mapping((_mapping(artifact.get("canary_evidence"))).get("canonical_canary_bundle"))
    return pd.DataFrame([
        {
            "Canary": row.get("canary"),
            "Logical qubits": row.get("input_logical_qubits"),
            "Depth": row.get("output_depth"),
            "Instructions": row.get("output_instruction_count"),
            "CZ": (_mapping(row.get("output_operation_counts"))).get("cz", 0),
            "ISA": "PASS" if row.get("isa_valid") else "FAIL",
            "Coupling": "PASS" if row.get("coupling_valid") else "FAIL",
            "Status": row.get("status"),
        }
        for row in _rows(bundle.get("accepted_canaries"))
    ])


def _target_ledger(state: Mapping[str, Any], snapshot: Mapping[str, Any]) -> pd.DataFrame:
    target = _mapping(snapshot.get("target")) if state.get("authenticated") else {}
    return pd.DataFrame([
        {"Field": "Target", "Value": "fake_marrakesh" if target else "MASKED", "Interpretation": "Pinned offline fake-backend snapshot"},
        {"Field": "Physical qubits", "Value": str(target.get("num_qubits", "MASKED")), "Interpretation": "Capacity gate"},
        {"Field": "Basis", "Value": " · ".join(str(item).upper() for item in target.get("basis_gates", [])) or "MASKED", "Interpretation": "Structural target ISA"},
        {"Field": "Directed edges", "Value": str(target.get("directed_coupling_edge_count", "MASKED")), "Interpretation": "Frozen coupling graph"},
        {"Field": "Maximum degree", "Value": str(target.get("maximum_degree", "MASKED")), "Interpretation": "Structural only"},
        {"Field": "Current calibration", "Value": "NOT QUERIED" if target else "MASKED", "Interpretation": "No live-hardware evidence"},
    ])


def _toolchain_ledger(state: Mapping[str, Any], toolchain: Mapping[str, Any]) -> pd.DataFrame:
    contract = _mapping(toolchain.get("canary_transpilation_contract")) if state.get("authenticated") else {}
    environment = _mapping(toolchain.get("environment")) if state.get("authenticated") else {}
    return pd.DataFrame([
        {"Control": "Qiskit core", "Frozen value": str(environment.get("qiskit", "MASKED"))},
        {"Control": "Optimization level", "Frozen value": str(contract.get("optimization_level", "MASKED"))},
        {"Control": "Layout", "Frozen value": str(contract.get("layout_method", "MASKED"))},
        {"Control": "Routing", "Frozen value": str(contract.get("routing_method", "MASKED"))},
        {"Control": "Translation", "Frozen value": str(contract.get("translation_method", "MASKED"))},
        {"Control": "Transpiler seed", "Frozen value": str(contract.get("seed_transpiler", "MASKED"))},
        {"Control": "Scheduling", "Frozen value": str(contract.get("scheduling_method", "MASKED"))},
        {"Control": "Clean process replays", "Frozen value": "2" if contract else "MASKED"},
    ])


def _register_floor_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    floor = _mapping((_mapping(artifact.get("capacity_precheck"))).get("persistent_register_floor")) if state.get("authenticated") else {}
    registers = _mapping(floor.get("persistent_registers"))
    rows = [{"Register": name, "Qubits": width, "Lifetime": "PERSISTENT"} for name, width in registers.items()]
    rows.append({"Register": "TOTAL FLOOR", "Qubits": floor.get("persistent_register_floor_qubits", "MASKED"), "Lifetime": "160 > 156 · REJECTED" if floor else "MASKED"})
    return pd.DataFrame(rows, columns=["Register", "Qubits", "Lifetime"])


def _boundary_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    boundary = _mapping(artifact.get("claim_boundary")) if state.get("authenticated") else {}
    fields = (
        ("Research classification", artifact.get("research_classification")),
        ("Provider SDK imported", boundary.get("provider_sdk_imported")),
        ("Credentials read", boundary.get("provider_credentials_read")),
        ("Provider calls", boundary.get("provider_calls")),
        ("Network calls", boundary.get("network_calls")),
        ("QPU jobs", boundary.get("qpu_jobs_submitted")),
        ("Hardware executable", boundary.get("hardware_executable")),
        ("Calibration-aware fidelity", boundary.get("calibration_aware_fidelity")),
        ("Optimization performance", boundary.get("optimization_performance")),
        ("Quantum advantage", boundary.get("quantum_advantage")),
    ) if boundary else (("Evidence", "MASKED"),)
    return pd.DataFrame(
        [{"Boundary": name, "Value": str(value)} for name, value in fields]
    )


def _hash_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    if not state.get("authenticated"):
        return pd.DataFrame([{"Evidence": "MASKED", "SHA-256": "MASKED"}])
    return pd.DataFrame([
        {"Evidence": "V4.4 artifact", "SHA-256": artifact.get("artifact_sha256")},
        {"Evidence": "Capacity precheck", "SHA-256": state.get("capacity_precheck_sha256")},
        {"Evidence": "Offline target snapshot", "SHA-256": state.get("snapshot_sha256")},
        {"Evidence": "Canary bundle", "SHA-256": state.get("canary_bundle_sha256")},
        {"Evidence": "Canary result root", "SHA-256": state.get("canary_result_root_sha256")},
        {"Evidence": "V4.3 parent artifact", "SHA-256": EXPECTED_V43_ARTIFACT_SHA256},
        {"Evidence": "V4.3 parent freeze", "SHA-256": EXPECTED_V43_FREEZE_SHA256},
    ])


def _negative_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    negative = _mapping((_mapping((_mapping(artifact.get("canary_evidence"))).get("canonical_canary_bundle"))).get("mandatory_negative_canary")) if state.get("authenticated") else {}
    return pd.DataFrame([
        {"Control": "157-qubit capacity overflow", "Expected": "REJECT", "Observed": negative.get("status", "MASKED"), "Exception": negative.get("exception_class", "MASKED")},
        {"Control": "Full V4.3 workload", "Expected": "PRECHECK BEFORE ROUTING", "Observed": "8 / 8 REJECTED" if state.get("authenticated") else "MASKED", "Exception": "NONE · CONTROLLED DECISION" if state.get("authenticated") else "MASKED"},
    ])


def _decision_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Gate": "Target capacity", "State": "REJECTED" if state.get("authenticated") else "MASKED", "Evidence": "327–339 logical vs 156 physical" if state.get("authenticated") else "MASKED"},
        {"Gate": "Canary translation/routing", "State": "PASS" if state.get("authenticated") else "MASKED", "Evidence": "5 canaries · 2 identical clean-process replays" if state.get("authenticated") else "MASKED"},
        {"Gate": "Full-workload transpilation", "State": "NOT RUN" if state.get("authenticated") else "MASKED", "Evidence": NOT_RUN if state.get("authenticated") else "MASKED"},
        {"Gate": "Production / hardware", "State": "BLOCKED" if state.get("authenticated") else "MASKED", "Evidence": state.get("production_admission", "MASKED")},
        {"Gate": "Next falsifiable gate", "State": "REGISTERED" if state.get("authenticated") else "MASKED", "Evidence": state.get("next_gate", "MASKED")},
    ])


def apply_v44_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if encoding is None:
        return None
    result = copy.deepcopy(dict(encoding))
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        return result
    result.update(
        {
            "backend_capacity_ok": False,
            "backend_qubits": 156,
            "backend_transpilation": NOT_RUN,
            "canary_pipeline": "PASS · FIVE CANARIES · TWO IDENTICAL CLEAN-PROCESS REPLAYS",
            "encoding_status": "V4.4 REJECTED · FAKEMARRAKESH 156Q CAPACITY PRECHECK",
            "full_workload_routing": NOT_RUN,
            "hardware_executable": False,
            "logical_qubits_min": 339,
            "named_backend": "fake_marrakesh · PINNED OFFLINE SNAPSHOT",
            "network_calls": 0,
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "v44_capacity_deficit_worst": -183,
            "v44_decision": EXPECTED_OVERALL,
            "v44_minimum_logical_qubits": 327,
            "v44_next_gate": EXPECTED_NEXT_GATE,
            "v44_persistent_floor_qubits": 160,
            "v44_rejected_seed_count": 8,
        }
    )
    return result


def render_v44_named_backend_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
    toolchain: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    snapshot_integrity: bool | None,
    toolchain_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v44_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        snapshot_integrity=snapshot_integrity,
        toolchain_integrity=toolchain_integrity,
        parent_integrity=parent_integrity,
    )
    payload = dict(artifact or {})
    spec_payload = dict(spec or {})
    snapshot_payload = dict(snapshot or {})
    toolchain_payload = dict(toolchain or {})
    authenticated = state.get("authenticated") is True

    section_header(
        "V4.4 · Named Offline Backend / Zero-Job Routing Gate",
        "FAKEMARRAKESH 156Q · CAPACITY FALSIFICATION · CANARY TOOLCHAIN",
        "The frozen full workload is wider than the named offline target. Capacity therefore rejects all eight seeds before full transpilation; bounded canaries validate only the pinned compilation mechanics.",
    )

    auth_value = "pass" if authenticated else "fail"
    hooks = (
        f'<span data-qv44-surface="named-offline-backend-zero-job" data-qv44-release="4.4" data-qv44-auth="{auth_value}" '
        f'data-qv44-parent="{("pass" if parent_integrity is True else "fail")}" data-qv44-snapshot="{("pass" if snapshot_integrity is True else "fail")}" '
        f'data-qv44-toolchain="{("pass" if toolchain_integrity is True else "fail")}" data-qv44-backend="fake_marrakesh" '
        f'data-qv44-target-kind="offline-fake-snapshot" data-qv44-outcome="capacity-rejected" '
        f'data-qv44-transpilation="NOT_RUN_CAPACITY_PRECHECK_REJECTED" data-qv44-routing="NOT_RUN_CAPACITY_PRECHECK_REJECTED" '
        f'data-qv44-seeds="8-of-8-rejected" data-qv44-provider-sdk="false" data-qv44-credential-reads="0" '
        f'data-qv44-provider-calls="0" data-qv44-network-calls="0" data-qv44-qpu-submit="disabled" data-qv44-jobs="0" '
        f'data-qv44-hardware="false" data-qv44-performance="NOT_TESTED" data-qv44-advantage="NOT_CLAIMED" '
        f'data-qv44-research="RESEARCH_ONLY" style="display:none"></span>'
    )
    st.markdown(hooks, unsafe_allow_html=True)

    if authenticated:
        st.warning(
            "Authenticated V4.4 scientific rejection: FakeMarrakesh has 156 qubits, while every frozen V4.3 workload requires 327–339. Full transpilation and routing were intentionally not run after the capacity gate."
        )
    else:
        st.error("V4.4 evidence authentication failed. All scientific outcomes are masked fail-closed.")

    values = [
        ("TARGET", "FAKEMARRAKESH", "PINNED OFFLINE SNAPSHOT"),
        ("PHYSICAL QUBITS", "156", "STRUCTURAL CAPACITY"),
        ("FULL SEEDS", "8 / 8 REJECTED", "BEFORE TRANSPILATION"),
        ("LOGICAL WIDTH", "327–339", "V4.3 FROZEN RANGE"),
        ("WORST DEFICIT", "−183", "CAPACITY − LOGICAL"),
        ("PERSISTENT FLOOR", "160", "4 OVER BEFORE SCRATCH"),
        ("CANARIES", "5 / 5 PASS", "ISA + COUPLING"),
        ("CLEAN REPLAYS", "2 / 2 IDENTICAL", _short_sha(state.get("canary_bundle_sha256"))),
        ("157Q CONTROL", "EXPECTED REJECT", "TRANSPILER ERROR"),
        ("FULL ROUTING", "NOT RUN", "CAPACITY PRECHECK"),
        ("PROVIDER / NETWORK", "0 / 0", "NO CREDENTIAL READ"),
        ("QPU / HARDWARE", "0 / FALSE", "RESEARCH_ONLY"),
    ] if authenticated else [(label, "MASKED", "AUTHENTICATION REQUIRED") for label in (
        "TARGET", "PHYSICAL QUBITS", "FULL SEEDS", "LOGICAL WIDTH", "WORST DEFICIT", "PERSISTENT FLOOR", "CANARIES", "CLEAN REPLAYS", "157Q CONTROL", "FULL ROUTING", "PROVIDER / NETWORK", "QPU / HARDWARE"
    )]
    cards = "".join(
        f'<div class="qp3-card qv44-metric"><div class="qp3-ck">{escape(label)}</div><div class="qp3-cv">{escape(value)}</div><div class="qp3-cn">{escape(note)}</div></div>'
        for label, value, note in values
    )
    st.markdown(f'<div class="qp3-grid">{cards}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="qp3-panel"><div class="qp3-pk">SEALED V4.4 DECISION</div><div class="qp3-pt qp3-block">{escape(str(state.get("decision", "MASKED_FAIL_CLOSED")))}</div><div class="qp3-note">Production · {escape(str(state.get("production_admission", "MASKED")))}<br>Full workload · {escape(str(state.get("full_workload_transpilation", "MASKED")))}<br>Next gate · {escape(str(state.get("next_gate", "MASKED")))}</div></div>',
        unsafe_allow_html=True,
    )

    capacity_frame = _capacity_ledger(state, payload)
    st.dataframe(capacity_frame, width="stretch", hide_index=True)
    if authenticated and not capacity_frame.empty:
        chart = capacity_frame[["Seed", "Deficit"]].copy().set_index("Seed")
        st.bar_chart(chart, color="#F59E0B")
    st.caption(
        "Negative deficits are intentional: target capacity minus logical width. Rejected routed metrics remain NOT_RUN, never synthetic zeroes."
    )

    st.dataframe(_register_floor_ledger(state, payload), width="stretch", hide_index=True)
    st.dataframe(_decision_ledger(state), width="stretch", hide_index=True)

    with st.expander("Pinned offline target · identity and topology", expanded=False):
        st.dataframe(_target_ledger(state, snapshot_payload), width="stretch", hide_index=True)
        st.code(str((_mapping(snapshot_payload.get("target"))).get("directed_coupling_edges_compact", "MASKED")))
        st.download_button(
            "Download V4.4 frozen backend snapshot",
            data=json.dumps(snapshot_payload, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json",
            mime="application/json",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_snapshot",
        )
        st.download_button(
            "Download V4.4 target topology CSV",
            data=_target_ledger(state, snapshot_payload).to_csv(index=False),
            file_name="QUANTUM_LAB_V4_4_TARGET_TOPOLOGY.csv",
            mime="text/csv",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_target",
        )

    with st.expander("Pinned Qiskit canary toolchain · deterministic replay", expanded=True):
        st.dataframe(_toolchain_ledger(state, toolchain_payload), width="stretch", hide_index=True)
        st.dataframe(_canary_ledger(state, payload), width="stretch", hide_index=True)
        st.caption(
            "Canaries validate only the frozen translation/routing mechanics. They do not establish that any 327–339-qubit workload can be compiled."
        )
        st.download_button(
            "Download V4.4 pinned toolchain manifest",
            data=json.dumps(toolchain_payload, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json",
            mime="application/json",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_toolchain",
        )
        st.download_button(
            "Download V4.4 canary ledger CSV",
            data=_canary_ledger(state, payload).to_csv(index=False),
            file_name="QUANTUM_LAB_V4_4_CANARY_LEDGER.csv",
            mime="text/csv",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_canaries",
        )

    with st.expander("Integrity, evidence boundary and decision register", expanded=False):
        st.dataframe(_hash_ledger(state, payload), width="stretch", hide_index=True)
        st.dataframe(_boundary_ledger(state, payload), width="stretch", hide_index=True)
        negative = _negative_ledger(state, payload).iloc[0].to_dict()
        st.caption(
            f"Mandatory negative control · {negative.get('Control')} · {negative.get('Observed')} · {negative.get('Exception')}"
        )
        st.download_button(
            "Download sealed V4.4 named-backend artifact",
            data=json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json",
            mime="application/json",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_artifact",
        )
        st.download_button(
            "Download V4.4 frozen protocol specification",
            data=json.dumps(spec_payload, indent=2, sort_keys=True, ensure_ascii=False),
            file_name="PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json",
            mime="application/json",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_spec",
        )
        st.download_button(
            "Download V4.4 capacity ledger CSV",
            data=capacity_frame.to_csv(index=False),
            file_name="QUANTUM_LAB_V4_4_CAPACITY_LEDGER.csv",
            mime="text/csv",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_capacity",
        )
        st.download_button(
            "Download V4.4 boundary ledger CSV",
            data=_boundary_ledger(state, payload).to_csv(index=False),
            file_name="QUANTUM_LAB_V4_4_BOUNDARY_LEDGER.csv",
            mime="text/csv",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_boundary",
        )
        st.download_button(
            "Download V4.4 hash ledger CSV",
            data=_hash_ledger(state, payload).to_csv(index=False),
            file_name="QUANTUM_LAB_V4_4_HASH_LEDGER.csv",
            mime="text/csv",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_hashes",
        )
        st.download_button(
            "Download V4.4 next-gate contract",
            data=str(state.get("next_gate", "MASKED")) + "\n",
            file_name="QUANTUM_LAB_V4_4_NEXT_GATE.txt",
            mime="text/plain",
            disabled=not authenticated,
            key=f"{key_prefix}_v44_download_next_gate",
        )

    with st.expander("Governance controls · all disabled by the sealed boundary", expanded=False):
        labels = (
            "Rebuild sealed V4.4 canaries",
            "Change the frozen FakeMarrakesh snapshot",
            "Override the 156-qubit capacity gate",
            "Treat rejected full-workload metrics as zero",
            "Run full-workload transpilation",
            "Run full-workload routing",
            "Enable scheduling or calibration extrapolation",
            "Read provider credentials · V4.4 prohibited",
            "Contact a provider service · V4.4 prohibited",
            "Submit a QPU job · V4.4 prohibited",
            "Promote to hardware executable",
            "Claim optimization performance or quantum advantage",
        )
        for index, label in enumerate(labels):
            st.button(label, disabled=True, key=f"{key_prefix}_v44_governance_{index}")

    if authenticated:
        st.error(
            "FULL-WORKLOAD CAPACITY · REJECTED. The current architecture cannot fit FakeMarrakesh: even DATA + REMOVE_COIN + ADD_COIN + TARGET requires 160 qubits. The five successful canaries do not override this rejection."
        )
        st.info(
            f"Next falsifiable gate: {state.get('next_gate')}. A successor must reach 156 qubits or fewer and prove exact promise-subspace parity; provider and QPU execution remain unauthorized."
        )
    return state


__all__ = [
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "NOT_RUN",
    "_boundary_ledger",
    "_canary_ledger",
    "_capacity_ledger",
    "_decision_ledger",
    "_hash_ledger",
    "_negative_ledger",
    "_register_floor_ledger",
    "_target_ledger",
    "_toolchain_ledger",
    "apply_v44_encoding_state",
    "default_v44_ui_artifact_path",
    "load_v44_ui_artifact",
    "normalize_v44_artifact",
    "render_v44_named_backend_panel",
]
