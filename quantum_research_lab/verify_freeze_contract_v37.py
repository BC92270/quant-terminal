"""Strict verifier for the exact Quantum Lab V3.7 release freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .verify_phase3_v37 import (
    EXPECTED_RELEASE_CHECKS,
    EXPECTED_V37_FROZEN_PATHS,
    README_PATH,
    UI_PATH,
    V36_FREEZE_PATH,
    V36_FREEZE_RAW_SHA256,
    V36_FREEZE_SEMANTIC_SHA256,
    V36_FROZEN_PATHS,
    V36_README_SHA256,
    V36_UI_SHA256,
    V37_ADDITIONAL_FROZEN_PATHS,
    V37_ARTIFACT_RAW_SHA256,
    V37_ARTIFACT_SHA256,
    V37_LEGACY_SUPPORT_SHA256,
    V37_README_SHA256,
    V37_SPEC_RAW_SHA256,
    V37_SPEC_SHA256,
    V37_UI_SHA256,
    V37_VALIDATION_MANIFEST_SHA256,
    V37_VALIDATION_SHA256,
    _read_json_strict,
    verify_release_chain,
)


VERIFY_VERSION = "QUANTUM LAB V3.7 FREEZE CONTRACT VERIFIER · V1"
FREEZE_NAME = "FREEZE_CONTRACT_V3_7.json"

EXPECTED_FREEZE_CHECKS = frozenset(
    {
        "freeze_schema_exact",
        "freeze_self_hash_exact",
        "frozen_inventory_99_paths_exact",
        "all_frozen_files_present_and_exact",
        "all_paths_contained_regular_and_no_symlinks",
        "v36_freeze_identity_exact",
        "v36_parent_inventory_exact",
        "v36_immutable_parent_files_55_exact",
        "legacy_support_snapshot_27_files_exact",
        "successor_policy_exact",
        "release_check_inventory_exact",
        "release_chain_30_of_30_passes",
        "lineage_identities_exact",
        "scientific_decision_exact",
        "zero_job_boundary_exact",
        "scientific_validation_18_of_18_exact",
        "deployment_and_archive_contract_exact",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _regular(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"Unsafe frozen path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in relative_path.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked frozen path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Frozen path is not a regular file: {relative}")
    resolved = cursor.resolve(strict=True)
    resolved.relative_to(release_root)
    return resolved


def verify_freeze_contract(root: str | Path, contract_path: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    candidate = Path(contract_path)
    candidate = candidate if candidate.is_absolute() else release_root / candidate
    errors: list[str] = []
    try:
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError("Freeze contract must be a regular non-symlink file.")
        freeze_path = candidate.resolve(strict=True)
        freeze_path.relative_to(release_root)
        if freeze_path.name != FREEZE_NAME:
            raise ValueError(f"Unexpected freeze contract name: {freeze_path.name}")
        payload = _read_json_strict(freeze_path)
    except Exception as exc:
        return {
            "checks": {"freeze_readable": False},
            "errors": [str(exc)],
            "failed_checks": ["freeze_readable"],
            "valid": False,
            "verifier_version": VERIFY_VERSION,
        }

    frozen_files = payload.get("frozen_files") or {}
    file_results: dict[str, dict[str, Any]] = {}
    contained = True
    if isinstance(frozen_files, dict):
        for relative, expected in sorted(frozen_files.items()):
            try:
                target = _regular(release_root, relative)
                actual = _sha256(target)
                valid = actual == expected
            except Exception as exc:
                actual = None
                valid = False
                contained = False
                errors.append(f"{relative}: {exc}")
            file_results[relative] = {
                "actual_sha256": actual,
                "expected_sha256": expected,
                "valid": valid,
            }

    try:
        release = verify_release_chain(release_root)
    except Exception as exc:
        release = {"valid": False, "checks": {}, "errors": [str(exc)]}
        errors.append(f"V3.7 release chain: {exc}")
    release_checks = release.get("checks") or {}

    try:
        v36_freeze_path = _regular(release_root, V36_FREEZE_PATH)
        v36_freeze = _read_json_strict(v36_freeze_path)
    except Exception as exc:
        v36_freeze_path = None
        v36_freeze = {}
        errors.append(f"V3.6 freeze: {exc}")
    v36_files = v36_freeze.get("frozen_files") or {}

    immutable_v36: dict[str, bool] = {}
    if isinstance(v36_files, dict):
        for relative in sorted(V36_FROZEN_PATHS - {README_PATH, UI_PATH}):
            try:
                immutable_v36[relative] = (
                    _sha256(_regular(release_root, relative)) == v36_files.get(relative)
                )
            except Exception:
                immutable_v36[relative] = False

    support_results: dict[str, bool] = {}
    for relative, expected in sorted(V37_LEGACY_SUPPORT_SHA256.items()):
        try:
            support_results[relative] = _sha256(_regular(release_root, relative)) == expected
        except Exception:
            support_results[relative] = False

    schema = {
        "claim_boundary",
        "created_utc",
        "deployment_contract",
        "family",
        "freeze_contract_sha256",
        "freeze_contract_version",
        "frozen_file_count",
        "frozen_files",
        "lineage",
        "release_paths",
        "scientific_decisions",
        "self_hash_contract",
        "successor_policy",
        "support_closure",
        "validation_evidence",
        "validation_targets",
    }
    successor = payload.get("successor_policy") or {}
    closure = payload.get("support_closure") or {}
    lineage = payload.get("lineage") or {}
    decisions = payload.get("scientific_decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    deployment = payload.get("deployment_contract") or {}
    targets = payload.get("validation_targets") or {}
    evidence = payload.get("validation_evidence") or {}
    release_paths = payload.get("release_paths") or {}
    computed_self_hash = _freeze_semantic(payload)

    checks = {
        "freeze_schema_exact": bool(
            set(payload) == schema
            and payload.get("family") == "QUANTUM_LAB"
            and payload.get("freeze_contract_version")
            == "QUANTUM LAB V3.7 FREEZE CONTRACT · V1"
            and payload.get("self_hash_contract")
            == "CANONICAL_JSON_SHA256_EXCLUDING_FREEZE_CONTRACT_SHA256"
            and release_paths.get("specification")
            == "quantum_research_lab/PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json"
            and release_paths.get("artifact")
            == "outputs/quantum_phase3/v37_reversible/SEALED_V3_7_REVERSIBLE_PROTOTYPE_ARTIFACT.json"
            and release_paths.get("architecture")
            == "quantum_research_lab/QUANTUM_LAB_V3_7_ARCHITECTURE.md"
        ),
        "freeze_self_hash_exact": bool(
            payload.get("freeze_contract_sha256") == computed_self_hash
        ),
        "frozen_inventory_99_paths_exact": bool(
            payload.get("frozen_file_count") == 99
            and isinstance(frozen_files, dict)
            and len(frozen_files) == 99
            and set(frozen_files) == EXPECTED_V37_FROZEN_PATHS
        ),
        "all_frozen_files_present_and_exact": bool(
            len(file_results) == 99
            and all(row.get("valid") is True for row in file_results.values())
        ),
        "all_paths_contained_regular_and_no_symlinks": bool(
            contained and len(file_results) == len(frozen_files)
        ),
        "v36_freeze_identity_exact": bool(
            v36_freeze_path is not None
            and _sha256(v36_freeze_path) == V36_FREEZE_RAW_SHA256
            and _freeze_semantic(v36_freeze) == V36_FREEZE_SEMANTIC_SHA256
            and v36_freeze.get("freeze_contract_sha256") == V36_FREEZE_SEMANTIC_SHA256
        ),
        "v36_parent_inventory_exact": bool(
            v36_freeze.get("frozen_file_count") == 57
            and isinstance(v36_files, dict)
            and len(v36_files) == 57
            and set(v36_files) == V36_FROZEN_PATHS
        ),
        "v36_immutable_parent_files_55_exact": bool(
            len(immutable_v36) == 55 and all(immutable_v36.values())
        ),
        "legacy_support_snapshot_27_files_exact": bool(
            len(support_results) == 27
            and all(support_results.values())
            and closure.get("classification")
            == "V3.7_LEGACY_SUPPORT_SNAPSHOT_NOT_RETROACTIVE_V3.6_FREEZE"
            and closure.get("captured_file_count") == 27
            and set(closure.get("captured_paths") or []) == set(V37_LEGACY_SUPPORT_SHA256)
        ),
        "successor_policy_exact": bool(
            successor.get("allowed_v36_superseded_files") == [README_PATH, UI_PATH]
            and successor.get("v36_frozen_readme_sha256") == V36_README_SHA256
            and successor.get("v36_frozen_ui_sha256") == V36_UI_SHA256
            and successor.get("v37_successor_readme_sha256") == V37_README_SHA256
            and successor.get("v37_successor_ui_sha256") == V37_UI_SHA256
            and successor.get("immutable_v36_frozen_file_count") == 55
            and successor.get("immutable_v36_predecessor_file_count") == 83
            and successor.get("accepted_target_states") == ["V3.6", "V3.7"]
            and successor.get("mixed_or_third_state") == "REJECT"
        ),
        "release_check_inventory_exact": bool(
            set(release_checks) == EXPECTED_RELEASE_CHECKS
            and targets.get("release_chain_checks") == 30
        ),
        "release_chain_30_of_30_passes": bool(
            release.get("valid") is True
            and len(release_checks) == 30
            and all(value is True for value in release_checks.values())
        ),
        "lineage_identities_exact": bool(
            lineage.get("v36_freeze_raw_file_sha256") == V36_FREEZE_RAW_SHA256
            and lineage.get("v36_freeze_sha256") == V36_FREEZE_SEMANTIC_SHA256
            and lineage.get("v37_spec_raw_file_sha256") == V37_SPEC_RAW_SHA256
            and lineage.get("v37_spec_sha256") == V37_SPEC_SHA256
            and lineage.get("v37_artifact_raw_file_sha256") == V37_ARTIFACT_RAW_SHA256
            and lineage.get("v37_artifact_sha256") == V37_ARTIFACT_SHA256
        ),
        "scientific_decision_exact": bool(
            decisions.get("overall") == "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
            and decisions.get("incremental_exposure_prototype")
            == "PASSED_ON_REGISTERED_N4_K2_FIXTURE"
            and decisions.get("production_n40_compiler") == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions.get("n40_rewrite_admission") == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions.get("elementary_basis_decomposition") == "BLOCKED_NOT_BUILT"
            and decisions.get("selected_model_cnot") == "NOT_ESTIMATED"
        ),
        "zero_job_boundary_exact": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("prototype_classification") == "PROTOTYPE_ONLY"
            and boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "scientific_validation_18_of_18_exact": bool(
            evidence.get("overall_pass") is True
            and evidence.get("check_count") == 18
            and evidence.get("failed_checks") == []
            and evidence.get("validation_source_sha256") == V37_VALIDATION_SHA256
            and evidence.get("validation_manifest_sha256")
            == V37_VALIDATION_MANIFEST_SHA256
            and evidence.get("artifact_sha256") == V37_ARTIFACT_SHA256
        ),
        "deployment_and_archive_contract_exact": bool(
            deployment.get("overlay_file_count") == 45
            and deployment.get("institutional_archive_file_count") == 104
            and deployment.get("route") == "?workspace=quantum-research"
            and deployment.get("integration_surface_last") == UI_PATH
            and deployment.get("readme_surface_penultimate") == README_PATH
            and deployment.get("install_lock") == ".quantum-lab-v37-install.lock"
            and deployment.get("rollback_requires_preimage_hashes") is True
            and deployment.get("idempotent_exact_reapply") == "NO_OP"
            and deployment.get("clean_extract_self_contained_verification") == "REQUIRED"
            and targets.get("freeze_contract_checks") == 17
            and targets.get("scientific_validation_checks") == 18
            and targets.get("frozen_file_count") == 99
            and targets.get("legacy_support_file_count") == 27
        ),
    }
    if set(checks) != EXPECTED_FREEZE_CHECKS:
        errors.append("Internal freeze-check inventory drifted from its hard-coded contract.")
    errors.extend(str(item) for item in release.get("errors") or [])
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "file_count": len(file_results),
        "file_results": file_results,
        "freeze_contract_sha256_computed": computed_self_hash,
        "freeze_contract_sha256_stored": payload.get("freeze_contract_sha256"),
        "release_checks": release_checks,
        "valid": not failed and not errors and set(checks) == EXPECTED_FREEZE_CHECKS,
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.7 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, default=Path(FREEZE_NAME))
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FREEZE_CHECKS",
    "FREEZE_NAME",
    "VERIFY_VERSION",
    "verify_freeze_contract",
]
