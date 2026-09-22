"""Independent fail-closed validation for Quantum Lab V4.4.

The default validation authenticates the already-sealed two-process Qiskit
canary evidence without importing Qiskit.  ``replay_toolchain=True`` performs
an additional local replay and requires an exact canonical match; it still
creates no provider, simulator or QPU job.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

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
    PERSISTENT_REGISTER_FLOOR,
    TARGET_BASIS,
    TARGET_QUBITS,
    authenticate_v43_parent,
    canonical_json_sha256,
    capacity_precheck,
    load_v44_snapshot,
    load_v44_spec,
    load_v44_toolchain,
    raw_file_sha256,
    read_json_strict,
    run_canary_bundle,
)


EXPECTED_CHECK_COUNT = 37
EXPECTED_SOURCE_RAW_SHA256 = "0be93c8b153a9a2b34a15dfd3faec0b1995f8ceaf3c3af620d5aee7178a138de"
EXPECTED_ARTIFACT_RAW_SHA256 = "3b6824965fa7b2829981d6d35eec5413a24f7340719613e7cd2e8512d6285488"
EXPECTED_ARTIFACT_SHA256 = "de1ba4194a0f7220b1cfcb0c61f8faed3f187c0e9c7712775cba53fa79ed98bb"
EXPECTED_CAPACITY_PRECHECK_SHA256 = "7d80f9b8b76aa1aaaa618b3f4b2dbfae75750c9dda376d97343b0dfc3c82be71"
EXPECTED_CANARY_BUNDLE_SHA256 = "b744a2bd1364d531c65d89e24dd7f78ef8170e12cbf13affd3e28a0a1191a0f0"
EXPECTED_CANARY_ROOT_SHA256 = "3348aedbe468e14e979dd50f943dd004c0640c1271d446d7ef8c8378c0ac8cc6"
EXPECTED_CANARY_NAMES = (
    "ISA_TRANSLATION_3Q",
    "REVERSIBLE_ARITHMETIC_MCX_5Q",
    "REMOVE_COIN_RING_40Q",
    "DUAL_COIN_RINGS_80Q",
    "EXACT_CAPACITY_BOUNDARY_156Q",
)
EXPECTED_CANARY_COUNTS = (
    {"cz": 2, "rz": 15, "sx": 7, "x": 1},
    {"cz": 144, "rz": 274, "sx": 316},
    {"cz": 530, "rz": 1200, "sx": 1380},
    {"cz": 1060, "rz": 2400, "sx": 2760},
    {"x": 156},
)


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _paths(root: str | Path | None = None) -> dict[str, Path]:
    base = _root(root)
    return {
        "artifact": base / "outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json",
        "snapshot": base / "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json",
        "source": base / "quantum_research_lab/phase3_v44_named_backend_routing.py",
        "spec": base / "quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json",
        "toolchain": base / "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json",
    }


def _self_hashed(row: Mapping[str, Any], field: str) -> bool:
    return row.get(field) == canonical_json_sha256({key: value for key, value in row.items() if key != field})


def _static_boundary(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    forbidden_modules = (
        "qiskit_ibm_runtime",
        "qiskit_ibm_provider",
        "requests",
        "httpx",
        "boto3",
        "braket",
    )
    forbidden_symbols = {
        "QiskitRuntimeService",
        "IBMProvider",
        "SamplerV2",
        "EstimatorV2",
        "least_busy",
        "save_account",
    }
    return {
        "forbidden_imports": sorted(
            module for module in imported if any(module == item or module.startswith(item + ".") for item in forbidden_modules)
        ),
        "forbidden_symbols": sorted(names & forbidden_symbols),
        "provider_free": not any(
            module for module in imported if any(module == item or module.startswith(item + ".") for item in forbidden_modules)
        ) and not (names & forbidden_symbols),
        "qiskit_core_lazy_import_present": any(module == "qiskit" or module.startswith("qiskit.") for module in imported),
    }


def validate_v44_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    replay_toolchain: bool = False,
) -> dict[str, Any]:
    paths = _paths(root)
    errors: list[str] = []
    try:
        spec = load_v44_spec(root=paths["source"].parents[1])
    except Exception as exc:
        spec = {}
        errors.append(f"V4.4 specification authentication failed: {exc}")
    try:
        snapshot = load_v44_snapshot(root=paths["source"].parents[1])
    except Exception as exc:
        snapshot = {}
        errors.append(f"V4.4 snapshot authentication failed: {exc}")
    try:
        toolchain = load_v44_toolchain(root=paths["source"].parents[1])
    except Exception as exc:
        toolchain = {}
        errors.append(f"V4.4 toolchain authentication failed: {exc}")
    try:
        parent = authenticate_v43_parent(root=paths["source"].parents[1])
    except Exception as exc:
        parent = {"valid": False, "errors": [str(exc)]}
        errors.append(f"V4.3 parent authentication failed: {exc}")
    try:
        independent_capacity = capacity_precheck(root=paths["source"].parents[1])
    except Exception as exc:
        independent_capacity = {}
        errors.append(f"Independent capacity replay failed: {exc}")

    artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    capacity = artifact.get("capacity_precheck") or {}
    rows = capacity.get("capacity_rows") or []
    canary_evidence = artifact.get("canary_evidence") or {}
    bundle = canary_evidence.get("canonical_canary_bundle") or {}
    canaries = bundle.get("accepted_canaries") or []
    negative = bundle.get("mandatory_negative_canary") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    parent_link = artifact.get("parent") or {}
    static = _static_boundary(paths["source"]) if paths["source"].is_file() else {"provider_free": False}

    fresh_replay: dict[str, Any] | None = None
    if replay_toolchain:
        try:
            fresh_replay = run_canary_bundle(root=paths["source"].parents[1])
            if fresh_replay.get("canary_bundle_sha256") != EXPECTED_CANARY_BUNDLE_SHA256:
                errors.append("Fresh Qiskit canary replay hash mismatch.")
        except Exception as exc:
            fresh_replay = {"status": "FAIL", "error": str(exc)}
            errors.append(f"Fresh Qiskit canary replay failed: {exc}")

    rejected = "NOT_RUN_CAPACITY_PRECHECK_REJECTED"
    checks: dict[str, bool] = {
        "spec_raw_and_semantic_identity": bool(spec.get("v44_spec_sha256") == EXPECTED_SPEC_SHA256 and raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256),
        "spec_was_sealed_before_result": bool((spec.get("chronology") or {}).get("result_state_at_seal") == "NOT_EVALUATED" and (spec.get("acceptance_contract") or {}).get("result_state_at_protocol_seal") == "NOT_EVALUATED"),
        "snapshot_raw_and_semantic_identity": bool(snapshot.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256 and raw_file_sha256(paths["snapshot"]) == EXPECTED_SNAPSHOT_RAW_SHA256),
        "snapshot_structural_target_exact": bool((snapshot.get("target") or {}).get("num_qubits") == TARGET_QUBITS and (snapshot.get("target") or {}).get("basis_gates") == list(TARGET_BASIS) and (snapshot.get("target") or {}).get("directed_coupling_edge_count") == 352),
        "snapshot_not_current_hardware_evidence": bool((snapshot.get("evidence_boundary") or {}).get("snapshot_is_current_hardware_evidence") is False and (snapshot.get("evidence_boundary") or {}).get("current_provider_status") == "NOT_QUERIED"),
        "toolchain_raw_and_semantic_identity": bool(toolchain.get("manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256 and raw_file_sha256(paths["toolchain"]) == EXPECTED_TOOLCHAIN_RAW_SHA256),
        "toolchain_transpiler_configuration_exact": bool((toolchain.get("environment") or {}).get("qiskit") == "2.5.2" and (toolchain.get("canary_transpilation_contract") or {}).get("seed_transpiler") == 4404 and (toolchain.get("canary_transpilation_contract") or {}).get("optimization_level") == 0),
        "v43_parent_authenticates": parent.get("valid") is True,
        "v43_parent_191_immutable_paths_exact": bool(parent.get("immutable_file_count") == 191 and parent.get("immutable_files_exact") is True),
        "artifact_raw_identity": paths["artifact"].is_file() and raw_file_sha256(paths["artifact"]) == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": bool(artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and canonical_json_sha256(artifact_core) == EXPECTED_ARTIFACT_SHA256),
        "artifact_source_spec_snapshot_toolchain_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256 and artifact.get("snapshot_raw_file_sha256") == EXPECTED_SNAPSHOT_RAW_SHA256 and artifact.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256 and artifact.get("toolchain_manifest_raw_file_sha256") == EXPECTED_TOOLCHAIN_RAW_SHA256 and artifact.get("toolchain_manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256),
        "artifact_v43_parent_crosslinks": bool(parent_link.get("artifact_raw_file_sha256") == EXPECTED_V43_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256 and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V43_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V43_FREEZE_SHA256 and parent_link.get("immutable_file_count") == 191 and parent_link.get("immutable_files_exact") is True),
        "capacity_precheck_self_hash": bool(capacity.get("capacity_precheck_sha256") == EXPECTED_CAPACITY_PRECHECK_SHA256 and _self_hashed(capacity, "capacity_precheck_sha256")),
        "capacity_precheck_independent_replay": bool(independent_capacity.get("capacity_precheck_sha256") == capacity.get("capacity_precheck_sha256") == EXPECTED_CAPACITY_PRECHECK_SHA256),
        "capacity_seed_order_exact": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "capacity_row_self_hashes": bool(rows) and all(_self_hashed(row, "capacity_row_sha256") for row in rows),
        "parent_widths_exact": [row.get("logical_qubits") for row in rows] == list(EXPECTED_WIDTHS),
        "all_eight_full_workloads_rejected": bool(capacity.get("seed_count") == capacity.get("rejected_seed_count") == 8 and capacity.get("all_eight_full_workloads_rejected_before_transpilation") is True and all(row.get("capacity_fit") is False for row in rows)),
        "capacity_deficits_exact": [row.get("capacity_deficit_qubits") for row in rows] == [-174, -175, -171, -172, -173, -175, -183, -178],
        "persistent_register_floor_exceeds_target": bool((capacity.get("persistent_register_floor") or {}).get("persistent_register_floor_qubits") == PERSISTENT_REGISTER_FLOOR and (capacity.get("persistent_register_floor") or {}).get("capacity_deficit_qubits") == -4),
        "full_workload_transpilation_attempts_zero": capacity.get("full_workload_transpilation_attempts") == 0,
        "full_workload_routing_attempts_zero": capacity.get("full_workload_routing_attempts") == 0,
        "full_workload_metrics_literal_not_run": bool(rows) and all(row.get("full_workload_transpilation") == rejected and row.get("full_workload_routing") == rejected and row.get("full_workload_native_gate_counts") == rejected and row.get("full_workload_routed_depth") == rejected for row in rows),
        "canary_evidence_self_hash": _self_hashed(canary_evidence, "canary_evidence_sha256"),
        "two_clean_process_replays_recorded": bool(canary_evidence.get("clean_process_replay_count") == 2 and len(canary_evidence.get("clean_process_replay_sha256") or []) == 2),
        "two_clean_process_replays_identical": bool(canary_evidence.get("replay_stable") is True and canary_evidence.get("clean_process_replay_sha256") == [EXPECTED_CANARY_BUNDLE_SHA256, EXPECTED_CANARY_BUNDLE_SHA256]),
        "canonical_canary_bundle_self_hash": bool(bundle.get("canary_bundle_sha256") == EXPECTED_CANARY_BUNDLE_SHA256 and _self_hashed(bundle, "canary_bundle_sha256")),
        "five_canaries_order_and_count_exact": bool(bundle.get("accepted_canary_count") == 5 and [row.get("canary") for row in canaries] == list(EXPECTED_CANARY_NAMES)),
        "canary_result_self_hashes": bool(canaries) and all(_self_hashed(row, "canary_result_sha256") for row in canaries) and _self_hashed(negative, "canary_result_sha256"),
        "canary_isa_coupling_and_counts_exact": bool(bundle.get("all_accepted_canaries_isa_and_coupling_valid") is True and bundle.get("canonical_result_root_sha256") == EXPECTED_CANARY_ROOT_SHA256 and [row.get("output_operation_counts") for row in canaries] == list(EXPECTED_CANARY_COUNTS) and all(row.get("status") == "PASS" and row.get("isa_valid") is True and row.get("coupling_valid") is True for row in canaries)),
        "capacity_157_negative_canary_exact": bool(negative.get("canary") == "CAPACITY_OVERFLOW_157Q" and negative.get("input_logical_qubits") == 157 and negative.get("exception_class") == "TranspilerError" and negative.get("status") == "EXPECTED_REJECTION"),
        "provider_credential_network_job_boundaries_zero": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and bundle.get("provider_sdk_imported") is False and bundle.get("provider_calls") == bundle.get("network_calls") == bundle.get("qpu_jobs_submitted") == 0),
        "decision_exact": decisions.get("overall") == "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB",
        "production_rejection_and_next_gate_exact": bool(decisions.get("production_admission") == "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION" and decisions.get("next_falsifiable_gate") == "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY"),
        "research_only_hardware_performance_advantage_boundary": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED" and boundary.get("snapshot_is_current_hardware_evidence") is False),
        "confirmatory_source_provider_free": bool(static.get("provider_free") is True and static.get("qiskit_core_lazy_import_present") is True),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.4 scientific check count drifted: {len(checks)}")
    if replay_toolchain and not (fresh_replay and fresh_replay.get("canary_bundle_sha256") == EXPECTED_CANARY_BUNDLE_SHA256):
        errors.append("Requested fresh toolchain replay did not reproduce the sealed bundle.")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(parent.get("errors") or [])
    evidence_core = {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {"checks_passed": sum(value is True for value in checks.values()), "checks_total": len(checks)},
        "validation_version": "QUANTUM LAB V4.4 INDEPENDENT VALIDATION · V1",
    }
    return {
        **evidence_core,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "fresh_toolchain_replay": fresh_replay,
        "fresh_toolchain_replay_performed": replay_toolchain,
        "passed": not failed and not errors,
        "root": str(paths["source"].parents[1]),
        "static_boundary": static,
        "validation_evidence_sha256": canonical_json_sha256(evidence_core),
    }


def run_v44_validation(*, root: str | Path | None = None, replay_toolchain: bool = False) -> dict[str, Any]:
    paths = _paths(root)
    artifact = read_json_strict(paths["artifact"])
    return validate_v44_artifact(artifact, root=paths["source"].parents[1], replay_toolchain=replay_toolchain)


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CANARY_BUNDLE_SHA256",
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_SOURCE_RAW_SHA256",
    "run_v44_validation",
    "validate_v44_artifact",
]
