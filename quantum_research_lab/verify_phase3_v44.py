"""Fail-closed release-chain verifier for Quantum Lab V4.4.

Identity-only mode verifies the frozen validation commitment without importing
Qiskit or rerunning scientific engines. Deep mode independently recomputes the
capacity and sealed-evidence checks; a fresh Qiskit replay remains a separate,
explicit validation operation.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v44_named_backend_routing import (
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
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SOURCE_RAW_SHA256,
    run_v44_validation,
)


FREEZE_PATH = "FREEZE_CONTRACT_V4_4.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_3.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_4_NAMED_BACKEND_ZERO_JOB_ROUTING_SPEC_V1.json"
SNAPSHOT_PATH = "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
TOOLCHAIN_PATH = "quantum_research_lab/PHASE_III_V4_4_TOOLCHAIN_MANIFEST_V1.json"
SOURCE_PATH = "quantum_research_lab/phase3_v44_named_backend_routing.py"
VALIDATION_PATH = "quantum_research_lab/phase3_v44_validation.py"
ARTIFACT_PATH = "outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json"

V44_TRANSITION_PATHS = (
    FREEZE_PATH,
    "DEPLOY_V4_4.md",
    "app_v44_offline_harness.py",
    "install_quantum_lab_v44.py",
    "build_quantum_lab_v44_release.py",
    ARTIFACT_PATH,
    SPEC_PATH,
    SNAPSHOT_PATH,
    TOOLCHAIN_PATH,
    "quantum_research_lab/QUANTUM_LAB_V4_4_ARCHITECTURE.md",
    SOURCE_PATH,
    VALIDATION_PATH,
    "quantum_research_lab/phase3_v44_ui.py",
    "quantum_research_lab/test_phase3_v44.py",
    "quantum_research_lab/test_phase3_v44_release.py",
    "quantum_research_lab/verify_freeze_contract_v44.py",
    "quantum_research_lab/verify_phase3_v44.py",
    "quantum_research_lab/verify_phase3_v44_ui.py",
    README_PATH,
    UI_PATH,
)
V44_FROZEN_TRANSITION_PATHS = tuple(path for path in V44_TRANSITION_PATHS if path != FREEZE_PATH)

EXPECTED_FROZEN_FILE_COUNT = 211
EXPECTED_V44_PATH_FINGERPRINT = "eb4fda2c2b862fa279a7f0d60f0a2694e50f9c63bf89f60de9d0af52638c0516"
EXPECTED_V43_PATH_FINGERPRINT = "3bc4c8805cf38d5e55c8cc4d1c99cfc3950f9b7faa2cb85fa891fb42987467fc"
EXPECTED_VALIDATION_SOURCE_RAW_SHA256 = "5c1b6344f447c08b6b4b4dd5313b2895d940d77f51256f372aea950f975c8a94"
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "ec43dfa6ba209c4376a79b5e57cabbeb7f1f86e1bcc1b6e4797752c4427a66dd"
EXPECTED_RELEASE_CHECK_COUNT = 34
EXPECTED_FREEZE_CHECK_COUNT = 18
EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT = 18
EXPECTED_RELEASE_HARDENING_TEST_COUNT = 28
EXPECTED_UI_CHECK_COUNT = 26


def _semantic(payload: Mapping[str, Any], *excluded: str) -> str:
    blocked = set(excluded)
    return canonical_json_sha256({key: value for key, value in payload.items() if key not in blocked})


def _fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contained_regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe release path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked release path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Release path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _provider_free_source(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_modules = {
        "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "httpx",
        "boto3", "braket", "pennylane",
    }
    forbidden_names = {"QiskitRuntimeService", "IBMProvider", "SamplerV2", "EstimatorV2", "least_busy"}
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        if any(module.split(".")[0] in forbidden_modules or module in forbidden_modules for module in modules):
            return False
        if isinstance(node, ast.Name) and node.id in forbidden_names:
            return False
    return True


def _identity_validation(freeze: Mapping[str, Any]) -> dict[str, Any]:
    identities = freeze.get("v44_identities") or {}
    exact = identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256
    return {
        "checks": {"frozen_validation_evidence_identity": exact},
        "counts": {
            "checks_passed": EXPECTED_SCIENTIFIC_CHECK_COUNT if exact else 0,
            "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT,
        },
        "errors": [] if exact else ["Frozen V4.4 validation evidence identity mismatch."],
        "failed_checks": [] if exact else ["frozen_validation_evidence_identity"],
        "fresh_toolchain_replay_performed": False,
        "passed": exact,
        "validation_evidence_sha256": identities.get("validation_evidence_sha256"),
        "validation_version": "IDENTITY_ONLY · SCIENTIFIC ENGINES NOT RUN IN THIS INVOCATION",
    }


def verify_release_chain(root: str | Path, *, deep: bool = True) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.4 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.4 frozen_files must be an object.")
    file_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen.items()):
        try:
            actual = raw_file_sha256(_contained_regular(release_root, str(relative)))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        file_rows.append({"path": relative, "actual": actual, "expected": expected, "valid": valid})
        if not valid:
            errors.append(f"Frozen file mismatch: {relative}")

    try:
        parent_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent = read_json_strict(parent_path)
        parent_raw = raw_file_sha256(parent_path)
        parent_semantic = _semantic(parent, "freeze_contract_sha256")
    except Exception as exc:
        parent = {}
        parent_raw = parent_semantic = None
        errors.append(f"V4.3 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent = {
        str(path): str(digest)
        for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    } if isinstance(parent_files, Mapping) else {}
    immutable_parent_exact = bool(
        len(immutable_parent) == 191
        and all(frozen.get(path) == digest for path, digest in immutable_parent.items())
    )

    def guarded(relative: str) -> Path:
        try:
            return _contained_regular(release_root, relative)
        except Exception as exc:
            errors.append(f"Release path unavailable ({relative}): {exc}")
            return release_root / relative

    paths = {name: guarded(relative) for name, relative in {
        "spec": SPEC_PATH,
        "snapshot": SNAPSHOT_PATH,
        "toolchain": TOOLCHAIN_PATH,
        "source": SOURCE_PATH,
        "validation": VALIDATION_PATH,
        "artifact": ARTIFACT_PATH,
        "readme": README_PATH,
    }.items()}
    try:
        spec = load_v44_spec(paths["spec"], root=release_root)
    except Exception as exc:
        spec = {}
        errors.append(f"V4.4 specification authentication failed: {exc}")
    try:
        snapshot = load_v44_snapshot(paths["snapshot"], root=release_root)
    except Exception as exc:
        snapshot = {}
        errors.append(f"V4.4 snapshot authentication failed: {exc}")
    try:
        toolchain = load_v44_toolchain(paths["toolchain"], root=release_root)
    except Exception as exc:
        toolchain = {}
        errors.append(f"V4.4 toolchain authentication failed: {exc}")
    try:
        artifact = read_json_strict(paths["artifact"])
    except Exception as exc:
        artifact = {}
        errors.append(f"V4.4 artifact unavailable: {exc}")
    if deep:
        try:
            validation = run_v44_validation(root=release_root, replay_toolchain=False)
        except Exception as exc:
            validation = {"counts": {}, "errors": [str(exc)], "failed_checks": ["exception"], "passed": False}
            errors.append(f"Deep V4.4 validation failed: {exc}")
    else:
        validation = _identity_validation(freeze)

    capacity = artifact.get("capacity_precheck") or {}
    evidence = artifact.get("canary_evidence") or {}
    bundle = evidence.get("canonical_canary_bundle") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    parent_link = artifact.get("parent") or {}
    identities = freeze.get("v44_identities") or {}
    lineage = freeze.get("lineage") or {}
    deployment = freeze.get("deployment_contract") or {}
    packaging = freeze.get("packaging_contract") or {}
    targets = freeze.get("validation_targets") or {}

    checks: dict[str, bool] = {
        "freeze_contract_version_exact": freeze.get("freeze_contract_version") == "QUANTUM LAB V4.4 FREEZE CONTRACT · V1",
        "freeze_self_hash_exact": freeze.get("freeze_contract_sha256") == _semantic(freeze, "freeze_contract_sha256"),
        "frozen_file_count_211": freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "frozen_path_fingerprint_exact": _fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V44_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in file_rows),
        "all_v44_transition_payloads_and_v43_freeze_frozen": set(V44_FROZEN_TRANSITION_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V43_FREEZE_RAW_SHA256,
        "v43_freeze_raw_identity": parent_raw == EXPECTED_V43_FREEZE_RAW_SHA256,
        "v43_freeze_semantic_identity": parent_semantic == parent.get("freeze_contract_sha256") == EXPECTED_V43_FREEZE_SHA256,
        "v43_freeze_inventory_identity": bool(isinstance(parent_files, Mapping) and len(parent_files) == 193 and _fingerprint(parent_files) == EXPECTED_V43_PATH_FINGERPRINT),
        "all_191_v43_immutable_paths_preserved": immutable_parent_exact,
        "v44_spec_raw_identity": paths["spec"].is_file() and raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256,
        "v44_spec_semantic_identity": spec.get("v44_spec_sha256") == EXPECTED_SPEC_SHA256,
        "v44_snapshot_raw_identity": paths["snapshot"].is_file() and raw_file_sha256(paths["snapshot"]) == EXPECTED_SNAPSHOT_RAW_SHA256,
        "v44_snapshot_semantic_identity": snapshot.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256,
        "v44_toolchain_raw_identity": paths["toolchain"].is_file() and raw_file_sha256(paths["toolchain"]) == EXPECTED_TOOLCHAIN_RAW_SHA256,
        "v44_toolchain_semantic_identity": toolchain.get("manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256,
        "v44_source_raw_identity": paths["source"].is_file() and raw_file_sha256(paths["source"]) == EXPECTED_SOURCE_RAW_SHA256,
        "v44_validation_source_raw_identity": paths["validation"].is_file() and raw_file_sha256(paths["validation"]) == EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
        "v44_artifact_raw_identity": paths["artifact"].is_file() and raw_file_sha256(paths["artifact"]) == EXPECTED_ARTIFACT_RAW_SHA256,
        "v44_artifact_semantic_identity": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 == _semantic(artifact, "artifact_sha256"),
        "artifact_source_spec_snapshot_toolchain_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256 and artifact.get("snapshot_raw_file_sha256") == EXPECTED_SNAPSHOT_RAW_SHA256 and artifact.get("snapshot_sha256") == EXPECTED_SNAPSHOT_SHA256 and artifact.get("toolchain_manifest_raw_file_sha256") == EXPECTED_TOOLCHAIN_RAW_SHA256 and artifact.get("toolchain_manifest_sha256") == EXPECTED_TOOLCHAIN_SHA256),
        "artifact_v43_parent_crosslinks": bool(parent_link.get("artifact_raw_file_sha256") == EXPECTED_V43_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256 and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V43_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V43_FREEZE_SHA256 and parent_link.get("immutable_file_count") == 191 and parent_link.get("immutable_files_exact") is True),
        "capacity_rejection_exact": bool(capacity.get("capacity_precheck_sha256") == EXPECTED_CAPACITY_PRECHECK_SHA256 and capacity.get("seed_count") == capacity.get("rejected_seed_count") == 8 and capacity.get("maximum_logical_qubits") == 339 and capacity.get("maximum_capacity_deficit_qubits") == -183 and capacity.get("full_workload_transpilation_attempts") == capacity.get("full_workload_routing_attempts") == 0),
        "canary_double_replay_exact": bool(bundle.get("canary_bundle_sha256") == EXPECTED_CANARY_BUNDLE_SHA256 and bundle.get("canonical_result_root_sha256") == EXPECTED_CANARY_ROOT_SHA256 and bundle.get("accepted_canary_count") == 5 and evidence.get("clean_process_replay_count") == 2 and evidence.get("replay_stable") is True),
        "bounded_decisions_exact": bool(decisions.get("overall") == "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB" and decisions.get("production_admission") == "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION" and decisions.get("next_falsifiable_gate") == "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY"),
        "provider_hardware_performance_advantage_boundary_exact": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("full_workload_transpilation") == "NOT_RUN_CAPACITY_PRECHECK_REJECTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "compiler_validation_ui_installer_provider_free": all(_provider_free_source(guarded(path)) for path in (SOURCE_PATH, VALIDATION_PATH, "quantum_research_lab/phase3_v44_ui.py", "install_quantum_lab_v44.py")),
        "scientific_validation_commitment_exact": identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256,
        "scientific_validation_passed_or_identity_verified": validation.get("passed") is True,
        "scientific_validation_has_37_checks": (validation.get("counts") or {}).get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT,
        "readme_declares_bounded_v44_decision": "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB" in paths["readme"].read_text(encoding="utf-8"),
        "deployment_contract_transactional_idempotent": bool(deployment.get("overlay_file_count") == 20 and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH),
        "packaging_contract_exact": bool(packaging.get("institutional_archive_entries") == 212 and packaging.get("overlay_archive_entries") == 20 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256"),
        "route_targets_lineage_and_identities_exact": bool(deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12 and targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("release_hardening_tests") == EXPECTED_RELEASE_HARDENING_TEST_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and lineage.get("v43_freeze_raw_file_sha256") == EXPECTED_V43_FREEZE_RAW_SHA256 and lineage.get("v43_freeze_sha256") == EXPECTED_V43_FREEZE_SHA256 and lineage.get("v43_frozen_file_count") == 193 and lineage.get("v43_immutable_file_count") == 191 and identities.get("v44_source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and identities.get("v44_validation_source_raw_file_sha256") == EXPECTED_VALIDATION_SOURCE_RAW_SHA256 and identities.get("v44_artifact_raw_file_sha256") == EXPECTED_ARTIFACT_RAW_SHA256 and identities.get("v44_artifact_sha256") == EXPECTED_ARTIFACT_SHA256),
    }
    if len(checks) != EXPECTED_RELEASE_CHECK_COUNT:
        raise AssertionError(f"V4.4 release check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    merged_errors = list(dict.fromkeys(errors + list(validation.get("errors") or [])))
    return {
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_replay": bool(deep),
        "fresh_qiskit_replay": False,
        "errors": merged_errors,
        "failed_checks": failed,
        "freeze_contract_sha256": freeze.get("freeze_contract_sha256"),
        "frozen_file_count": len(file_rows),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "verifier": "QUANTUM LAB V4.4 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--identity-only", action="store_true")
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_release_chain(root, deep=not args.identity_only)
    except Exception as exc:
        report = {
            "check_count": EXPECTED_RELEASE_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "root": str(root),
            "valid": False,
            "verifier": "QUANTUM LAB V4.4 RELEASE CHAIN · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FREEZE_CHECK_COUNT",
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_RELEASE_CHECK_COUNT",
    "EXPECTED_RELEASE_HARDENING_TEST_COUNT",
    "EXPECTED_SCIENTIFIC_CHECK_COUNT",
    "EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT",
    "EXPECTED_UI_CHECK_COUNT",
    "EXPECTED_V44_PATH_FINGERPRINT",
    "FREEZE_PATH",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V44_FROZEN_TRANSITION_PATHS",
    "V44_TRANSITION_PATHS",
    "verify_release_chain",
]
