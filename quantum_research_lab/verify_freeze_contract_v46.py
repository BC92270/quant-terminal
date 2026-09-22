"""Independent immutable-freeze verifier for Quantum Lab V4.6."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v46_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_NEXT_GATE,
    EXPECTED_OVERALL,
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
    EXPECTED_PRODUCTION_ADMISSION,
    EXPECTED_SOURCE_RAW_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_TRANSLATION_RAW_SHA256,
    EXPECTED_TRANSLATION_SHA256,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    canonical_json_sha256,
    read_json_strict,
)
from .verify_phase3_v46 import (
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
    EXPECTED_V46_OVERLAY_ORDER_SHA256,
    EXPECTED_V46_PATH_FINGERPRINT,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V46_FROZEN_TRANSITION_PATHS,
    V46_TRANSITION_PATHS,
    verify_release_chain,
)


EXPECTED_FREEZE_CHECK_COUNT = 20


def _semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def verify_freeze_contract(root: str | Path, contract_path: str | Path | None = None) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    target = Path(contract_path) if contract_path else release_root / FREEZE_PATH
    if not target.is_absolute():
        target = release_root / target
    errors: list[str] = []
    try:
        contract = read_json_strict(target)
    except Exception as exc:
        contract = {}
        errors.append(f"V4.6 freeze unavailable: {exc}")
    frozen = contract.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("frozen_files must be an object")
    fingerprint = hashlib.sha256(json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")).hexdigest()
    file_results: dict[str, bool] = {}
    for relative, expected in sorted(frozen.items()):
        item = Path(relative)
        try:
            if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
                raise ValueError("unsafe relative path")
            cursor = release_root
            for part in item.parts:
                cursor = cursor / part
                mode = cursor.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError("symlink rejected")
            cursor.resolve(strict=True).relative_to(release_root)
            if not stat.S_ISREG(cursor.lstat().st_mode):
                raise ValueError("not a regular file")
            file_results[str(relative)] = hashlib.sha256(cursor.read_bytes()).hexdigest() == expected
        except Exception as exc:
            file_results[str(relative)] = False
            errors.append(f"{relative}: {exc}")
    release = verify_release_chain(release_root, deep=False)
    lineage = contract.get("lineage") or {}
    identities = contract.get("v46_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    evidence = contract.get("validation_evidence") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    expected_identities = {
        "artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_sha256": EXPECTED_ARTIFACT_SHA256,
        "checker_raw_file_sha256": EXPECTED_CHECKER_RAW_SHA256,
        "path_oracle_raw_file_sha256": EXPECTED_PATH_ORACLE_RAW_SHA256,
        "path_oracle_sha256": EXPECTED_PATH_ORACLE_SHA256,
        "source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "translation_contract_raw_file_sha256": EXPECTED_TRANSLATION_RAW_SHA256,
        "translation_contract_sha256": EXPECTED_TRANSLATION_SHA256,
    }
    checks: dict[str, bool] = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.6 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _semantic(contract),
        "frozen_file_count_249": contract.get("frozen_file_count") == len(frozen) == EXPECTED_FROZEN_FILE_COUNT,
        "path_fingerprint_exact": fingerprint == contract.get("frozen_paths_fingerprint_sha256") == EXPECTED_V46_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_transition_payloads_and_parent_freeze_frozen": set(V46_FROZEN_TRANSITION_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == lineage.get("v45_freeze_raw_file_sha256"),
        "v45_lineage_exact": lineage.get("append_only") is True and lineage.get("v45_frozen_file_count") == 229 and lineage.get("v45_immutable_file_count") == 227 and lineage.get("allowed_v45_superseded_files") == [README_PATH, UI_PATH],
        "v46_core_identities_exact": all(identities.get(key) == value for key, value in expected_identities.items()),
        "routing_decision_exact": decisions.get("overall") == EXPECTED_OVERALL and decisions.get("production_admission") == EXPECTED_PRODUCTION_ADMISSION and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "aggregate_evidence_exact": evidence.get("total_input_instructions") == 48647214 and evidence.get("aggregate_swaps") == 33259620 and evidence.get("aggregate_native_cz") == 119029964 and evidence.get("aggregate_native_instructions") == 476876458 and evidence.get("maximum_native_cz") == 15527797 and evidence.get("maximum_routed_depth") == 24893376,
        "clean_replay_evidence_exact": evidence.get("clean_process_replay_byte_exact") is True and evidence.get("scientific_validation_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256 and evidence.get("sealed_evidence_raw_file_sha256") == EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256 and evidence.get("sealed_evidence_sha256") == EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
        "provider_hardware_performance_advantage_boundary_exact": boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == boundary.get("provider_calls") == boundary.get("network_calls") == boundary.get("backend_run_calls") == 0 and boundary.get("local_simulator_jobs_submitted") == boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "successor_policy_accepts_only_v45_or_exact_v46": successor.get("accepted_target_states") == ["V4.5", "V4.6"] and successor.get("allowed_v45_superseded_files") == [README_PATH, UI_PATH] and successor.get("mixed_or_third_state") == "REJECT",
        "successor_hashes_exact": successor.get("v46_successor_readme_sha256") == frozen.get(README_PATH) and successor.get("v46_successor_ui_sha256") == frozen.get(UI_PATH),
        "deployment_overlay_order_and_rollback_exact": deployment.get("ordered_transition_paths") == list(V46_TRANSITION_PATHS) and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V46_OVERLAY_ORDER_SHA256 and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP",
        "route_and_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_outer_tab_count") == 12 and deployment.get("v46_evidence_tab_count") == 6,
        "packaging_contract_exact": packaging.get("institutional_archive_entries") == 250 and packaging.get("overlay_archive_entries") == 22 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_symlink_entries") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256",
        "validation_targets_exact": targets.get("scientific_validation_checks") == 57 and targets.get("streamlit_ui_checks") == 30 and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("scientific_unit_tests") == 18 and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT,
        "identity_release_chain_valid": release.get("valid") is True and release.get("deep_scientific_validation") is False and release.get("check_count") == EXPECTED_RELEASE_CHECK_COUNT,
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    if len(checks) != EXPECTED_FREEZE_CHECK_COUNT:
        raise AssertionError(f"V4.6 freeze verifier check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    merged_errors = list(dict.fromkeys(errors + list(release.get("errors") or [])))
    return {
        "check_count": len(checks),
        "checks": checks,
        "contract": str(target),
        "errors": merged_errors,
        "failed_checks": failed,
        "frozen_file_count": len(file_results),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "verifier": "QUANTUM LAB V4.6 FREEZE CONTRACT · V1",
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
        report = {"check_count": EXPECTED_FREEZE_CHECK_COUNT, "checks": {}, "errors": [str(exc)], "failed_checks": ["unhandled_exception"], "root": str(root), "valid": False, "verifier": "QUANTUM LAB V4.6 FREEZE CONTRACT · V1"}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_FREEZE_CHECK_COUNT", "verify_freeze_contract"]
