"""Strict verifier for the exact Quantum Lab V3.6 release freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .verify_phase3_v36 import (
    EXPECTED_RELEASE_CHECKS,
    V35_FREEZE_PATH,
    V35_FREEZE_RAW_SHA256,
    V35_FREEZE_SEMANTIC_SHA256,
    V35_FROZEN_PATHS,
    V35_README_PATH,
    V35_README_SHA256,
    V35_UI_PATH,
    V35_UI_SHA256,
    V36_ARTIFACT_RAW_SHA256,
    V36_ARTIFACT_SHA256,
    V36_README_SHA256,
    V36_SPEC_RAW_SHA256,
    V36_SPEC_SHA256,
    V36_UI_SHA256,
    verify_release_chain,
)


VERIFY_VERSION = "QUANTUM LAB V3.6 FREEZE CONTRACT VERIFIER · V1"
FREEZE_NAME = "FREEZE_CONTRACT_V3_6.json"
V36_ADDITIONAL_FROZEN_PATHS = frozenset(
    {
        "DEPLOY_V3_6.md",
        "app_v35_offline_harness.py",
        "app_v36_offline_harness.py",
        "install_quantum_lab_v36.py",
        "outputs/quantum_phase3/v36_reduction/SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json",
        "quantum_research_lab/PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json",
        "quantum_research_lab/QUANTUM_LAB_V3_6_ARCHITECTURE.md",
        "quantum_research_lab/phase3_v36_algorithmic_reduction.py",
        "quantum_research_lab/phase3_v36_ui.py",
        "quantum_research_lab/phase3_v36_validation.py",
        "quantum_research_lab/test_phase3_v36.py",
        "quantum_research_lab/test_phase3_v36_release.py",
        "quantum_research_lab/verify_freeze_contract_v36.py",
        "quantum_research_lab/verify_phase3_v36.py",
        "quantum_research_lab/verify_phase3_v36_ui.py",
    }
)
EXPECTED_FROZEN_PATHS = frozenset(
    V35_FROZEN_PATHS | {V35_FREEZE_PATH} | V36_ADDITIONAL_FROZEN_PATHS
)
EXPECTED_FREEZE_CHECKS = frozenset(
    {
        "freeze_schema_exact",
        "freeze_self_hash_exact",
        "frozen_inventory_57_paths_exact",
        "all_frozen_files_present_and_exact",
        "all_paths_contained_regular_and_no_symlinks",
        "v35_freeze_identity_exact",
        "v35_parent_inventory_exact",
        "successor_policy_exact",
        "release_check_inventory_exact",
        "release_chain_28_of_28_passes",
        "lineage_identities_exact",
        "scientific_decision_exact",
        "zero_job_boundary_exact",
        "deployment_contract_exact",
    }
)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"Unsafe frozen path: {relative!r}")
    root = root.resolve(strict=True)
    lexical = root / relative_path
    mode = lexical.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"Frozen path is not a regular non-symlink file: {relative}")
    target = lexical.resolve(strict=True)
    target.relative_to(root)
    return target


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
        payload = _read_json(freeze_path)
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
    for relative, expected in sorted(frozen_files.items() if isinstance(frozen_files, dict) else []):
        try:
            target = _regular(release_root, relative)
            actual = _sha256(target)
            valid = actual == expected
        except Exception as exc:
            target = None
            actual = None
            valid = False
            contained = False
            errors.append(f"{relative}: {exc}")
        file_results[relative] = {
            "actual_sha256": actual,
            "expected_sha256": expected,
            "valid": valid,
        }

    core = {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    computed_self_hash = canonical_json_sha256(core)
    try:
        release = verify_release_chain(release_root)
    except Exception as exc:
        release = {"valid": False, "checks": {}, "errors": [str(exc)]}
        errors.append(f"V3.6 release chain: {exc}")
    release_checks = release.get("checks") or {}

    try:
        v35_freeze_path = _regular(release_root, V35_FREEZE_PATH)
        v35_freeze = _read_json(v35_freeze_path)
        v35_core = {
            key: value
            for key, value in v35_freeze.items()
            if key != "freeze_contract_sha256"
        }
    except Exception as exc:
        v35_freeze_path = None
        v35_freeze = {}
        v35_core = {}
        errors.append(f"V3.5 freeze: {exc}")

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
        "validation_evidence",
        "validation_targets",
    }
    lineage = payload.get("lineage") or {}
    successor = payload.get("successor_policy") or {}
    decisions = payload.get("scientific_decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    deployment = payload.get("deployment_contract") or {}
    targets = payload.get("validation_targets") or {}

    checks = {
        "freeze_schema_exact": set(payload) == schema,
        "freeze_self_hash_exact": bool(
            payload.get("freeze_contract_sha256") == computed_self_hash
        ),
        "frozen_inventory_57_paths_exact": bool(
            payload.get("frozen_file_count") == 57
            and len(frozen_files) == 57
            and set(frozen_files) == EXPECTED_FROZEN_PATHS
        ),
        "all_frozen_files_present_and_exact": bool(
            len(file_results) == 57
            and all(row.get("valid") is True for row in file_results.values())
        ),
        "all_paths_contained_regular_and_no_symlinks": bool(
            contained and len(file_results) == len(frozen_files)
        ),
        "v35_freeze_identity_exact": bool(
            v35_freeze_path is not None
            and _sha256(v35_freeze_path) == V35_FREEZE_RAW_SHA256
            and canonical_json_sha256(v35_core) == V35_FREEZE_SEMANTIC_SHA256
            and v35_freeze.get("freeze_contract_sha256") == V35_FREEZE_SEMANTIC_SHA256
        ),
        "v35_parent_inventory_exact": bool(
            v35_freeze.get("frozen_file_count") == 41
            and len(v35_freeze.get("frozen_files") or {}) == 41
            and set(v35_freeze.get("frozen_files") or {}) == V35_FROZEN_PATHS
        ),
        "successor_policy_exact": bool(
            successor.get("allowed_v35_superseded_files") == [V35_README_PATH, V35_UI_PATH]
            and successor.get("v35_frozen_readme_sha256") == V35_README_SHA256
            and successor.get("v35_frozen_ui_sha256") == V35_UI_SHA256
            and successor.get("v36_successor_readme_sha256") == V36_README_SHA256
            and successor.get("v36_successor_ui_sha256") == V36_UI_SHA256
            and successor.get("accepted_target_states") == ["V3.5", "V3.6"]
            and successor.get("mixed_or_third_state") == "REJECT"
        ),
        "release_check_inventory_exact": bool(
            set(release_checks) == EXPECTED_RELEASE_CHECKS
            and targets.get("release_chain_checks") == 28
        ),
        "release_chain_28_of_28_passes": bool(
            release.get("valid") is True
            and len(release_checks) == 28
            and all(value is True for value in release_checks.values())
        ),
        "lineage_identities_exact": bool(
            lineage.get("v35_freeze_raw_file_sha256") == V35_FREEZE_RAW_SHA256
            and lineage.get("v35_freeze_sha256") == V35_FREEZE_SEMANTIC_SHA256
            and lineage.get("v36_spec_raw_file_sha256") == V36_SPEC_RAW_SHA256
            and lineage.get("v36_spec_sha256") == V36_SPEC_SHA256
            and lineage.get("v36_artifact_raw_file_sha256") == V36_ARTIFACT_RAW_SHA256
            and lineage.get("v36_artifact_sha256") == V36_ARTIFACT_SHA256
            and lineage.get("v36_validation_manifest_sha256")
            == "f7cedcc858862bd3ae83e683b256685e16f5958f34cd36b6a2cdbb0b52854364"
        ),
        "scientific_decision_exact": bool(
            decisions.get("overall") == "ARCHITECTURE_REWRITE_REQUIRED"
            and decisions.get("topology_only")
            == "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE"
            and decisions.get("incremental_exposure")
            == "BLOCKED_PENDING_REVERSIBLE_COMPILER"
            and decisions.get("pair_floor_selected_model_cnot") == 184_191_414
            and decisions.get("internal_budget_selected_model_cnot") == 2_500_000
        ),
        "zero_job_boundary_exact": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "deployment_contract_exact": bool(
            deployment.get("overlay_file_count") == 18
            and deployment.get("route") == "?workspace=quantum-research"
            and deployment.get("integration_surface_last") == V35_UI_PATH
            and deployment.get("install_lock") == ".quantum-lab-v36-install.lock"
            and deployment.get("rollback_requires_preimage_hashes") is True
            and deployment.get("idempotent_exact_reapply") == "NO_OP"
            and targets.get("freeze_contract_checks") == 14
            and targets.get("validation_ladder_checks") == 13
            and targets.get("unit_tests_v36") == 9
            and targets.get("release_hardening_tests") == 10
            and targets.get("regression_tests_v32_to_v36") == 55
            and targets.get("streamlit_acceptance_checks") == 13
        ),
    }
    if set(checks) != EXPECTED_FREEZE_CHECKS:
        errors.append("Internal freeze-check inventory drifted from the hard-coded contract.")
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
    parser = argparse.ArgumentParser(description="Verify the V3.6 freeze contract.")
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
    "EXPECTED_FROZEN_PATHS",
    "VERIFY_VERSION",
    "verify_freeze_contract",
]
