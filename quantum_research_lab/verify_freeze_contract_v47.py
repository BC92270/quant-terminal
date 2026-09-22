"""Independent immutable-freeze verifier for Quantum Lab V4.7."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from install_quantum_lab_v47 import (
    EXPECTED_V47_FROZEN_FILE_COUNT,
    EXPECTED_V47_FROZEN_PATHS_FINGERPRINT,
    EXPECTED_V47_OVERLAY_ORDER_SHA256,
    FAULT_PHASES,
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    README_PATH,
    UI_PATH,
    V47_FREEZE_PATH,
    V47_TRANSITION_FILES,
    _canonical_json_sha256,
    _read_json_strict,
)


EXPECTED_FREEZE_CHECK_COUNT = 24
ARTIFACT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
)
VALIDATION_REPORT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_VALIDATION_REPORT.json"
)

RAW_IDENTITY_PATHS = {
    "artifact_raw_file_sha256": ARTIFACT_PATH,
    "validation_report_raw_file_sha256": VALIDATION_REPORT_PATH,
    "spec_raw_file_sha256": "quantum_research_lab/PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json",
    "raw_properties_raw_file_sha256": "quantum_research_lab/PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json",
    "normalized_properties_raw_file_sha256": "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json",
    "path_oracle_raw_file_sha256": "quantum_research_lab/PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json",
    "duration_error_model_raw_file_sha256": "quantum_research_lab/PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json",
    "reference_builder_raw_file_sha256": "quantum_research_lab/phase3_v47_reference_builder.py",
    "optimizer_raw_file_sha256": "quantum_research_lab/phase3_v47_dated_properties_optimizer.py",
    "checker_raw_file_sha256": "quantum_research_lab/phase3_v47_independent_checker.py",
    "validation_source_raw_file_sha256": "quantum_research_lab/phase3_v47_validation.py",
    "ui_module_raw_file_sha256": "quantum_research_lab/phase3_v47_ui.py",
}
SEMANTIC_IDENTITY_PATHS = {
    "artifact_sha256": (ARTIFACT_PATH, "artifact_sha256"),
    "validation_report_sha256": (VALIDATION_REPORT_PATH, "sealed_validation_evidence_sha256"),
    "spec_sha256": (
        "quantum_research_lab/PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json",
        "v47_spec_sha256",
    ),
    "normalized_properties_sha256": (
        "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json",
        "properties_snapshot_sha256",
    ),
    "path_oracle_sha256": (
        "quantum_research_lab/PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json",
        "path_oracle_sha256",
    ),
    "duration_error_model_sha256": (
        "quantum_research_lab/PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json",
        "model_contract_sha256",
    ),
}


def _semantic(payload: Mapping[str, Any], field: str = "freeze_contract_sha256") -> str:
    return _canonical_json_sha256({key: value for key, value in payload.items() if key != field})


def _safe_regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError("unsafe relative path")
    cursor = root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError("symlink rejected")
    cursor.resolve(strict=True).relative_to(root)
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError("not a regular file")
    return cursor


def _semantic_identity(payload: Mapping[str, Any], field: str) -> bool:
    excluded = {field}
    if field == "v47_spec_sha256":
        excluded.add("v47_spec_sha")
    actual = _canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in excluded}
    )
    return isinstance(payload.get(field), str) and payload.get(field) == actual


def verify_freeze_contract(
    root: str | Path,
    contract_path: str | Path | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    target = Path(contract_path) if contract_path else release_root / V47_FREEZE_PATH
    if not target.is_absolute():
        target = release_root / target
    errors: list[str] = []
    try:
        contract = _read_json_strict(target)
    except Exception as exc:
        contract = {}
        errors.append(f"V4.7 freeze unavailable: {exc}")
    frozen = contract.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("frozen_files must be an object")
    fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    file_results: dict[str, bool] = {}
    for relative, expected in sorted(frozen.items()):
        try:
            path = _safe_regular(release_root, str(relative))
            file_results[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest() == expected
        except Exception as exc:
            file_results[str(relative)] = False
            errors.append(f"{relative}: {exc}")

    try:
        parent_path = _safe_regular(release_root, PARENT_FREEZE_PATH)
        parent = _read_json_strict(parent_path)
        parent_frozen = parent.get("frozen_files") or {}
        parent_semantic = _semantic(parent)
        parent_raw = hashlib.sha256(parent_path.read_bytes()).hexdigest()
    except Exception as exc:
        parent, parent_frozen, parent_semantic, parent_raw = {}, {}, None, None
        errors.append(f"V4.6 parent unavailable: {exc}")
    parent_immutable = {
        str(path): str(digest)
        for path, digest in parent_frozen.items()
        if str(path) not in {README_PATH, UI_PATH}
    } if isinstance(parent_frozen, dict) else {}
    expected_paths = set(parent_immutable) | {PARENT_FREEZE_PATH} | (
        set(V47_TRANSITION_FILES) - {V47_FREEZE_PATH}
    )

    identities = contract.get("v47_identities") or {}
    raw_identity_results = {
        key: identities.get(key) == frozen.get(relative)
        for key, relative in RAW_IDENTITY_PATHS.items()
    }
    semantic_identity_results: dict[str, bool] = {}
    for identity_key, (relative, field) in SEMANTIC_IDENTITY_PATHS.items():
        try:
            payload = _read_json_strict(_safe_regular(release_root, relative))
            semantic_identity_results[identity_key] = (
                identities.get(identity_key) == payload.get(field)
                and _semantic_identity(payload, field)
            )
        except Exception as exc:
            semantic_identity_results[identity_key] = False
            errors.append(f"Semantic identity {relative}: {exc}")

    try:
        report = _read_json_strict(_safe_regular(release_root, VALIDATION_REPORT_PATH))
    except Exception as exc:
        report = {}
        errors.append(f"V4.7 validation report unavailable: {exc}")
    report_scientific = report.get("scientific_validation") or {}
    report_replay = report.get("clean_process_replay") or {}
    report_boundary = report.get("claim_boundary") or {}

    lineage = contract.get("lineage") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    validation_evidence = contract.get("validation_evidence") or {}
    report_field = "sealed_validation_evidence_sha256"
    exact_zero_calls = all(
        boundary.get(key) == 0
        for key in (
            "credential_reads",
            "provider_calls",
            "network_calls",
            "backend_run_calls",
            "local_simulator_jobs_submitted",
            "qpu_jobs_submitted",
        )
    )
    checks: dict[str, bool] = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.7 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _semantic(contract),
        "frozen_file_count_272": contract.get("frozen_file_count") == len(frozen) == EXPECTED_V47_FROZEN_FILE_COUNT,
        "path_fingerprint_exact": fingerprint == contract.get("frozen_paths_fingerprint_sha256") == EXPECTED_V47_FROZEN_PATHS_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_V47_FROZEN_FILE_COUNT and all(file_results.values()),
        "append_only_path_set_exact": set(frozen) == expected_paths,
        "v46_parent_freeze_identity_exact": parent_raw == PARENT_FREEZE_RAW_SHA256 and parent_semantic == parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256 and len(parent_frozen) == parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT and hashlib.sha256(json.dumps(sorted(parent_frozen), separators=(",", ":")).encode()).hexdigest() == PARENT_FROZEN_PATHS_FINGERPRINT,
        "v46_immutable_hashes_preserved": len(parent_immutable) == PARENT_IMMUTABLE_FILE_COUNT and all(frozen.get(path) == digest for path, digest in parent_immutable.items()) and frozen.get(PARENT_FREEZE_PATH) == PARENT_FREEZE_RAW_SHA256,
        "release_paths_exact": contract.get("release_paths") == list(V47_TRANSITION_FILES),
        "deployment_order_exact": deployment.get("ordered_transition_paths") == list(V47_TRANSITION_FILES) and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V47_OVERLAY_ORDER_SHA256 and deployment.get("overlay_file_count") == len(V47_TRANSITION_FILES),
        "transactional_fault_contract_exact": deployment.get("commit_fault_positions_tested") == len(V47_TRANSITION_FILES) and set(deployment.get("commit_fault_phases_tested") or []) == set(FAULT_PHASES) and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("candidate_static_offline_boundary") == "REQUIRED_BEFORE_EXECUTION" and deployment.get("candidate_subprocess_environment") == "SCRUBBED_ALLOWLIST_ONLY" and deployment.get("predecessor_reauthenticated_under_lock_before_commit") is True and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("source_tree_raw_external_pin_required") is True and deployment.get("source_tree_raw_pin_scope") == "ORDERED_25_TRANSITION_PATHS_INCLUDING_RAW_FREEZE_BYTES" and deployment.get("exact_v47_freeze_raw_bytes_required") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("lock_release_requires_owned_token") is True,
        "successor_surfaces_committed_last": deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and tuple(V47_TRANSITION_FILES[-2:]) == (README_PATH, UI_PATH),
        "successor_policy_exact": successor.get("accepted_target_states") == ["V4.6", "V4.7"] and successor.get("allowed_v46_superseded_files") == [README_PATH, UI_PATH] and successor.get("immutable_v46_frozen_file_count") == PARENT_IMMUTABLE_FILE_COUNT and successor.get("mixed_or_third_state") == "REJECT",
        "successor_surface_hashes_exact": successor.get("v47_successor_readme_sha256") == frozen.get(README_PATH) and successor.get("v47_successor_ui_sha256") == frozen.get(UI_PATH),
        "lineage_exact": lineage.get("append_only") is True and lineage.get("v46_freeze_raw_file_sha256") == PARENT_FREEZE_RAW_SHA256 and lineage.get("v46_freeze_sha256") == PARENT_FREEZE_SEMANTIC_SHA256 and lineage.get("v46_frozen_file_count") == PARENT_FROZEN_FILE_COUNT and lineage.get("v46_immutable_file_count") == PARENT_IMMUTABLE_FILE_COUNT and lineage.get("allowed_v46_superseded_files") == [README_PATH, UI_PATH],
        "research_only_zero_operation_boundary": boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and exact_zero_calls and boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "dated_snapshot_boundary_exact": boundary.get("snapshot_is_current_hardware_evidence") is False and boundary.get("dated_properties_are_historical_offline_evidence_only") is True and boundary.get("current_calibration_claimed") is False and boundary.get("hardware_fidelity_claimed") is False,
        "primary_raw_identities_exact": raw_identity_results.get("artifact_raw_file_sha256") is True and raw_identity_results.get("validation_report_raw_file_sha256") is True,
        "supporting_raw_identities_exact": all(raw_identity_results.values()),
        "semantic_json_identities_exact": all(semantic_identity_results.values()),
        "sealed_validation_report_exact": bool(
            report.get(report_field) == identities.get("validation_report_sha256")
            and _semantic_identity(report, report_field)
            and report.get("validation_evidence_version")
            == "QUANTUM LAB V4.7 VALIDATION EVIDENCE · V1"
            and report.get("artifact_raw_file_sha256")
            == identities.get("artifact_raw_file_sha256")
            and report.get("artifact_sha256") == identities.get("artifact_sha256")
            and report_scientific.get("passed") is True
            and report_scientific.get("checks_passed")
            == report_scientific.get("checks_total")
            == 96
            and report_scientific.get("independent_checker_check_count") == 51
            and report_scientific.get("validation_evidence_sha256")
            == validation_evidence.get("scientific_validation_sha256")
            and report_scientific.get("errors") in ([], None)
            and report_scientific.get("failed_checks") in ([], None)
            and report_replay.get("performed") is True
            and report_replay.get("byte_for_byte_equal_to_sealed_artifact") is True
            and report_replay.get("semantic_self_hash_valid") is True
            and report_replay.get("artifact_raw_file_sha256")
            == identities.get("artifact_raw_file_sha256")
            and report_replay.get("artifact_sha256") == identities.get("artifact_sha256")
            and report_boundary.get("research_classification") == "RESEARCH_ONLY"
            and report_boundary.get("hardware_executable") is False
            and report_boundary.get("snapshot_is_current_hardware_evidence") is False
            and report_boundary.get("quantum_advantage") == "NOT_CLAIMED"
            and all(
                report_boundary.get(key) == 0
                for key in (
                    "provider_calls",
                    "network_calls",
                    "backend_run_calls",
                    "local_simulator_jobs_submitted",
                    "qpu_jobs_submitted",
                )
            )
        ),
        "packaging_contract_exact": packaging.get("institutional_archive_entries") == EXPECTED_V47_FROZEN_FILE_COUNT + 1 and packaging.get("overlay_archive_entries") == len(V47_TRANSITION_FILES) and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_symlink_entries") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256" and packaging.get("source_tree_raw_sha256_emitted_out_of_band") is True,
        "validation_targets_coherent": targets.get("frozen_file_count")
        == EXPECTED_V47_FROZEN_FILE_COUNT
        and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT
        and targets.get("independent_scientific_checks") == 51
        and targets.get("scientific_unit_tests") == 26
        and targets.get("release_hardening_tests") == 29
        and targets.get("scientific_validation_checks") == 96
        and targets.get("streamlit_ui_checks") == 42
        and targets.get("release_chain_checks") == 20,
        "no_freeze_errors": not errors,
    }
    if len(checks) != EXPECTED_FREEZE_CHECK_COUNT:
        raise AssertionError(
            f"V4.7 freeze verifier check count drifted: {len(checks)} != {EXPECTED_FREEZE_CHECK_COUNT}"
        )
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "contract": str(target),
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "frozen_file_count": len(file_results),
        "root": str(release_root),
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.7 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_freeze_contract(root, args.contract)
    except Exception as exc:
        report = {
            "check_count": EXPECTED_FREEZE_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "root": str(root),
            "valid": False,
            "verifier": "QUANTUM LAB V4.7 FREEZE CONTRACT · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_FREEZE_CHECK_COUNT", "verify_freeze_contract"]
