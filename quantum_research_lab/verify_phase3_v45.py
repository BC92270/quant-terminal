"""Fail-closed release-chain verifier for Quantum Lab V4.5.

Identity-only mode authenticates the frozen scientific-validation commitment
without reconstructing the eight circuit streams.  Deep mode independently
validates the sealed proof-carrying artifact; ``--rebuild`` additionally
reconstructs it deterministically.  Every mode remains provider-free and
submits no simulator or QPU job.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v45_proof_carrying_width_reduction import (
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_V44_ARTIFACT_RAW_SHA256,
    EXPECTED_V44_ARTIFACT_SHA256,
    EXPECTED_V44_FREEZE_RAW_SHA256,
    EXPECTED_V44_FREEZE_SHA256,
    EXPECTED_V44_PATH_FINGERPRINT,
    canonical_json_sha256,
    load_v45_spec,
    raw_file_sha256,
    read_json_strict,
)
from .phase3_v45_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CERTIFICATE_RAW_SHA256,
    EXPECTED_CERTIFICATE_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SOURCE_RAW_SHA256,
    run_v45_validation,
)


FREEZE_PATH = "FREEZE_CONTRACT_V4_5.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_4.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json"
CERTIFICATE_PATH = "quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json"
SOURCE_PATH = "quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py"
CHECKER_PATH = "quantum_research_lab/phase3_v45_width_proof_checker.py"
VALIDATION_PATH = "quantum_research_lab/phase3_v45_validation.py"
ARTIFACT_PATH = "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"

V45_TRANSITION_PATHS = (
    FREEZE_PATH,
    "DEPLOY_V4_5.md",
    "app_v45_offline_harness.py",
    "install_quantum_lab_v45.py",
    "build_quantum_lab_v45_release.py",
    ARTIFACT_PATH,
    SPEC_PATH,
    CERTIFICATE_PATH,
    "quantum_research_lab/QUANTUM_LAB_V4_5_ARCHITECTURE.md",
    SOURCE_PATH,
    CHECKER_PATH,
    VALIDATION_PATH,
    "quantum_research_lab/phase3_v45_ui.py",
    "quantum_research_lab/test_phase3_v45.py",
    "quantum_research_lab/test_phase3_v45_release.py",
    "quantum_research_lab/verify_freeze_contract_v45.py",
    "quantum_research_lab/verify_phase3_v45.py",
    "quantum_research_lab/verify_phase3_v45_ui.py",
    README_PATH,
    UI_PATH,
)
V45_FROZEN_TRANSITION_PATHS = tuple(path for path in V45_TRANSITION_PATHS if path != FREEZE_PATH)

EXPECTED_FROZEN_FILE_COUNT = 229
EXPECTED_V45_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_VALIDATION_SOURCE_RAW_SHA256 = "4bda439619d660d4044d34948a664281e85639f3dc97ed7c254b73fb769748fb"
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "c6eaa30664e80c62c63441536dc4900ce138fb7f5ecbd4521d856d5bc3808eda"
EXPECTED_RELEASE_CHECK_COUNT = 36
EXPECTED_FREEZE_CHECK_COUNT = 18
EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT = 20
EXPECTED_RELEASE_HARDENING_TEST_COUNT = 28
EXPECTED_UI_CHECK_COUNT = 28

EXPECTED_SEEDS = [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
EXPECTED_WIDTHS = [135, 137, 133, 135, 137, 137, 145, 139]
EXPECTED_NEXT_GATE = "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS"
EXPECTED_PRODUCTION_ADMISSION = "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED"


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
        "urllib", "socket", "boto3", "braket", "pennylane",
    }
    forbidden_names = {
        "QiskitRuntimeService", "IBMProvider", "SamplerV2", "EstimatorV2",
        "least_busy", "save_account",
    }
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
        if isinstance(node, ast.Attribute) and node.attr in forbidden_names:
            return False
    return True


def _identity_validation(freeze: Mapping[str, Any]) -> dict[str, Any]:
    identities = freeze.get("v45_identities") or {}
    exact = identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256
    return {
        "checks": {"frozen_validation_evidence_identity": exact},
        "counts": {
            "checks_passed": EXPECTED_SCIENTIFIC_CHECK_COUNT if exact else 0,
            "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT,
        },
        "deterministic_rebuild_performed": False,
        "errors": [] if exact else ["Frozen V4.5 validation evidence identity mismatch."],
        "failed_checks": [] if exact else ["frozen_validation_evidence_identity"],
        "passed": exact,
        "validation_evidence_sha256": identities.get("validation_evidence_sha256"),
        "validation_version": "IDENTITY_ONLY · SCIENTIFIC ENGINES NOT RUN IN THIS INVOCATION",
    }


def verify_release_chain(
    root: str | Path,
    *,
    deep: bool = True,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Authenticate the complete V4.5 release and its exact V4.4 lineage."""

    if rebuild and not deep:
        raise ValueError("Deterministic rebuild requires deep validation.")
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.5 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.5 frozen_files must be an object.")

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
        errors.append(f"V4.4 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent = {
        str(path): str(digest)
        for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    } if isinstance(parent_files, Mapping) else {}
    immutable_parent_exact = bool(
        len(immutable_parent) == 209
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
        "certificate": CERTIFICATE_PATH,
        "source": SOURCE_PATH,
        "checker": CHECKER_PATH,
        "validation": VALIDATION_PATH,
        "artifact": ARTIFACT_PATH,
        "readme": README_PATH,
    }.items()}
    try:
        spec = load_v45_spec(paths["spec"], root=release_root)
    except Exception as exc:
        spec = {}
        errors.append(f"V4.5 specification authentication failed: {exc}")
    try:
        certificate = read_json_strict(paths["certificate"])
    except Exception as exc:
        certificate = {}
        errors.append(f"V4.5 liveness certificate unavailable: {exc}")
    try:
        artifact = read_json_strict(paths["artifact"])
    except Exception as exc:
        artifact = {}
        errors.append(f"V4.5 artifact unavailable: {exc}")
    if deep:
        try:
            validation = run_v45_validation(root=release_root, rebuild=rebuild)
        except Exception as exc:
            validation = {
                "counts": {}, "errors": [str(exc)], "failed_checks": ["exception"], "passed": False,
            }
            errors.append(f"Deep V4.5 validation failed: {exc}")
    else:
        validation = _identity_validation(freeze)

    aggregate = artifact.get("aggregate") or {}
    rows = list(artifact.get("seed_materializations") or [])
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    parent_link = artifact.get("parent") or {}
    certificate_link = artifact.get("standalone_liveness_certificate") or {}
    identities = freeze.get("v45_identities") or {}
    lineage = freeze.get("lineage") or {}
    deployment = freeze.get("deployment_contract") or {}
    packaging = freeze.get("packaging_contract") or {}
    targets = freeze.get("validation_targets") or {}
    evidence = freeze.get("validation_evidence") or {}

    seeds = [row.get("seed") for row in rows]
    widths = [((row.get("register_layout") or {}).get("total_qubits")) for row in rows]
    cnot_counts = [
        int((((row.get("stream_manifest") or {}).get("elementary_counts") or {}).get("CX", -1)))
        for row in rows
    ]
    certificate_rows = list(certificate.get("seed_rows") or [])
    certificate_widths = [((row.get("register_layout") or {}).get("total_qubits")) for row in certificate_rows]
    off_promise = artifact.get("mandatory_off_promise_control") or {}
    readme_text = paths["readme"].read_text(encoding="utf-8") if paths["readme"].is_file() else ""

    checks: dict[str, bool] = {
        "freeze_contract_version_exact": freeze.get("freeze_contract_version") == "QUANTUM LAB V4.5 FREEZE CONTRACT · V1",
        "freeze_self_hash_exact": freeze.get("freeze_contract_sha256") == _semantic(freeze, "freeze_contract_sha256"),
        "frozen_file_count_229": freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "frozen_path_fingerprint_exact": _fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V45_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in file_rows),
        "all_v45_transition_payloads_and_v44_freeze_frozen": set(V45_FROZEN_TRANSITION_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V44_FREEZE_RAW_SHA256,
        "v44_freeze_raw_identity": parent_raw == EXPECTED_V44_FREEZE_RAW_SHA256,
        "v44_freeze_semantic_identity": parent_semantic == parent.get("freeze_contract_sha256") == EXPECTED_V44_FREEZE_SHA256,
        "v44_freeze_inventory_identity": bool(isinstance(parent_files, Mapping) and len(parent_files) == 211 and _fingerprint(parent_files) == EXPECTED_V44_PATH_FINGERPRINT),
        "all_209_v44_immutable_paths_preserved": immutable_parent_exact,
        "v45_spec_raw_identity": paths["spec"].is_file() and raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256,
        "v45_spec_semantic_and_preregistration_identity": bool(spec.get("v45_spec_sha256") == EXPECTED_SPEC_SHA256 and (spec.get("chronology") or {}).get("result_state_at_seal") == "NOT_EVALUATED"),
        "v45_source_raw_identity": paths["source"].is_file() and raw_file_sha256(paths["source"]) == EXPECTED_SOURCE_RAW_SHA256,
        "v45_checker_raw_identity": paths["checker"].is_file() and raw_file_sha256(paths["checker"]) == EXPECTED_CHECKER_RAW_SHA256,
        "v45_validation_source_raw_identity": paths["validation"].is_file() and raw_file_sha256(paths["validation"]) == EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
        "v45_certificate_raw_identity": paths["certificate"].is_file() and raw_file_sha256(paths["certificate"]) == EXPECTED_CERTIFICATE_RAW_SHA256,
        "v45_certificate_semantic_identity": certificate.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256,
        "v45_certificate_self_hash_and_widths": bool(certificate.get("certificate_sha256") == _semantic(certificate, "certificate_sha256") and [row.get("seed") for row in certificate_rows] == EXPECTED_SEEDS and certificate_widths == EXPECTED_WIDTHS),
        "v45_artifact_raw_identity": paths["artifact"].is_file() and raw_file_sha256(paths["artifact"]) == EXPECTED_ARTIFACT_RAW_SHA256,
        "v45_artifact_semantic_identity": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 == _semantic(artifact, "artifact_sha256"),
        "artifact_source_spec_checker_certificate_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("width_proof_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256 and artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256 and certificate_link.get("certificate_raw_file_sha256") == EXPECTED_CERTIFICATE_RAW_SHA256 and certificate_link.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256),
        "artifact_v44_parent_crosslinks": bool(parent_link.get("artifact_raw_file_sha256") == EXPECTED_V44_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V44_ARTIFACT_SHA256 and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V44_FREEZE_SHA256 and parent_link.get("immutable_file_count") == 209 and parent_link.get("immutable_files_exact") is True),
        "all_eight_seed_widths_exact": seeds == EXPECTED_SEEDS and widths == EXPECTED_WIDTHS,
        "width_allocation_capacity_and_margin_exact": bool(len(rows) == 8 and all((row.get("register_layout") or {}).get("total_qubits") == 67 + 2 * int((row.get("register_layout") or {}).get("arithmetic_width", -1000)) for row in rows) and aggregate.get("all_eight_widths_fit_156") is True and aggregate.get("maximum_logical_qubits") == 145 and aggregate.get("minimum_capacity_margin_qubits") == 11),
        "materialized_cnot_budget_exact": bool(len(cnot_counts) == 8 and all(0 <= count <= 2_500_000 for count in cnot_counts) and max(cnot_counts, default=-1) == aggregate.get("maximum_materialized_cnot") == 2_499_790 and aggregate.get("cnot_budget_pass_count") == 8 and aggregate.get("all_eight_materialized_cnot_counts_at_or_below_2500000") is True and evidence.get("clean_process_replay_count") == 2 and evidence.get("replay_artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and evidence.get("replay_stable") is True),
        "aggregate_self_hash_exact": aggregate.get("aggregate_sha256") == _semantic(aggregate, "aggregate_sha256"),
        "liveness_certificate_exact_clean_exit": bool(len(certificate_rows) == 8 and certificate.get("maximum_logical_qubits") == 145 and certificate.get("minimum_capacity_margin_qubits") == 11 and all((row.get("liveness") or {}).get("reset_instruction_count") == 0 and (row.get("liveness") or {}).get("clean_exit_registers") == ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"] for row in certificate_rows)),
        "off_promise_negative_witness_retained": off_promise.get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" and off_promise.get("witness_detected") is True,
        "bounded_decisions_exact": bool(decisions.get("overall") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY" and decisions.get("materialized_cnot_budget") == "PASSED_AT_OR_BELOW_2500000_ALL_EIGHT_SEEDS" and decisions.get("production_admission") == EXPECTED_PRODUCTION_ADMISSION and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE),
        "provider_hardware_performance_advantage_boundary_exact": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == boundary.get("provider_calls") == boundary.get("network_calls") == boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("full_workload_transpilation") == "NOT_RUN_IN_V4_5" and boundary.get("full_workload_routing") == "NOT_RUN_IN_V4_5" and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED" and boundary.get("snapshot_is_current_hardware_evidence") is False),
        "compiler_checker_validation_ui_installer_provider_free": all(_provider_free_source(guarded(path)) for path in (SOURCE_PATH, CHECKER_PATH, VALIDATION_PATH, "quantum_research_lab/phase3_v45_ui.py", "install_quantum_lab_v45.py")),
        "scientific_validation_commitment_exact": identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256,
        "scientific_validation_passed_with_51_checks": validation.get("passed") is True and (validation.get("counts") or {}).get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT,
        "readme_declares_bounded_v45_decision": "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY" in readme_text and EXPECTED_NEXT_GATE in readme_text and "RESEARCH_ONLY" in readme_text,
        "deployment_contract_transactional_idempotent": bool(deployment.get("overlay_file_count") == 20 and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH),
        "packaging_route_targets_lineage_and_identities_exact": bool(packaging.get("institutional_archive_entries") == 230 and packaging.get("overlay_archive_entries") == 20 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_symlink_entries") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256" and deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12 and targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("release_hardening_tests") == EXPECTED_RELEASE_HARDENING_TEST_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and lineage.get("v44_freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256 and lineage.get("v44_freeze_sha256") == EXPECTED_V44_FREEZE_SHA256 and lineage.get("v44_frozen_file_count") == 211 and lineage.get("v44_immutable_file_count") == 209 and identities.get("v45_source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and identities.get("v45_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256 and identities.get("liveness_certificate_raw_file_sha256") == EXPECTED_CERTIFICATE_RAW_SHA256 and identities.get("liveness_certificate_sha256") == EXPECTED_CERTIFICATE_SHA256 and identities.get("v45_validation_source_raw_file_sha256") == EXPECTED_VALIDATION_SOURCE_RAW_SHA256 and identities.get("v45_artifact_raw_file_sha256") == EXPECTED_ARTIFACT_RAW_SHA256 and identities.get("v45_artifact_sha256") == EXPECTED_ARTIFACT_SHA256),
    }
    if len(checks) != EXPECTED_RELEASE_CHECK_COUNT:
        raise AssertionError(f"V4.5 release check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    merged_errors = list(dict.fromkeys(errors + list(validation.get("errors") or [])))
    return {
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_replay": bool(deep),
        "deterministic_rebuild_performed": bool(deep and rebuild),
        "fresh_qiskit_replay": False,
        "errors": merged_errors,
        "failed_checks": failed,
        "freeze_contract_sha256": freeze.get("freeze_contract_sha256"),
        "frozen_file_count": len(file_rows),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "verifier": "QUANTUM LAB V4.5 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--identity-only", action="store_true")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="deterministically rebuild all eight streams during deep validation",
    )
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    if args.identity_only and args.rebuild:
        parser.error("--identity-only and --rebuild are mutually exclusive.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_release_chain(root, deep=not args.identity_only, rebuild=args.rebuild)
    except Exception as exc:
        report = {
            "check_count": EXPECTED_RELEASE_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "root": str(root),
            "valid": False,
            "verifier": "QUANTUM LAB V4.5 RELEASE CHAIN · V1",
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
    "EXPECTED_V45_PATH_FINGERPRINT",
    "EXPECTED_VALIDATION_EVIDENCE_SHA256",
    "EXPECTED_VALIDATION_SOURCE_RAW_SHA256",
    "FREEZE_PATH",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V45_FROZEN_TRANSITION_PATHS",
    "V45_TRANSITION_PATHS",
    "verify_release_chain",
]
