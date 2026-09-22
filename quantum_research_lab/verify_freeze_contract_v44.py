"""Independent immutable-freeze verifier for Quantum Lab V4.4."""

from __future__ import annotations

import argparse
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
    EXPECTED_V43_FREEZE_RAW_SHA256,
    EXPECTED_V43_FREEZE_SHA256,
    canonical_json_sha256,
)
from .phase3_v44_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CANARY_BUNDLE_SHA256,
    EXPECTED_CAPACITY_PRECHECK_SHA256,
    EXPECTED_SOURCE_RAW_SHA256,
)
from .verify_phase3_v44 import (
    EXPECTED_FREEZE_CHECK_COUNT,
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_RELEASE_HARDENING_TEST_COUNT,
    EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
    EXPECTED_UI_CHECK_COUNT,
    EXPECTED_V44_PATH_FINGERPRINT,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V44_FROZEN_TRANSITION_PATHS,
    verify_release_chain,
)


SEAL_TIME_IDENTITY_PATCH_POINTS = {
    "snapshot_raw_file_sha256": EXPECTED_SNAPSHOT_RAW_SHA256,
    "snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
    "toolchain_manifest_raw_file_sha256": EXPECTED_TOOLCHAIN_RAW_SHA256,
    "toolchain_manifest_sha256": EXPECTED_TOOLCHAIN_SHA256,
    "v44_artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
    "v44_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
    "v44_source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
    "v44_spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
    "v44_spec_sha256": EXPECTED_SPEC_SHA256,
    "v44_validation_source_raw_file_sha256": EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
    "validation_evidence_sha256": EXPECTED_VALIDATION_EVIDENCE_SHA256,
}


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError("Freeze contract must be a JSON object.")
    return payload


def _semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def verify_freeze_contract(root: str | Path, contract_path: str | Path | None = None) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    target = Path(contract_path) if contract_path else release_root / FREEZE_PATH
    if not target.is_absolute():
        target = release_root / target
    errors: list[str] = []
    try:
        contract = _read_json_strict(target)
    except Exception as exc:
        contract = {}
        errors.append(f"V4.4 freeze unavailable: {exc}")
    frozen = contract.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("frozen_files must be an object")
    fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
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
    try:
        release = verify_release_chain(release_root, deep=False)
    except Exception as exc:
        release = {"check_count": EXPECTED_RELEASE_CHECK_COUNT, "errors": [str(exc)], "valid": False}
        errors.append(f"Release verifier failed: {exc}")

    lineage = contract.get("lineage") or {}
    identities = contract.get("v44_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    evidence = contract.get("validation_evidence") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    checks: dict[str, bool] = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.4 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _semantic(contract),
        "frozen_file_count_211": contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "path_fingerprint_exact": fingerprint == contract.get("frozen_paths_fingerprint_sha256") == EXPECTED_V44_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_v44_transition_payloads_and_v43_freeze_frozen": set(V44_FROZEN_TRANSITION_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V43_FREEZE_RAW_SHA256,
        "v43_lineage_exact": bool(lineage.get("v43_freeze_raw_file_sha256") == EXPECTED_V43_FREEZE_RAW_SHA256 and lineage.get("v43_freeze_sha256") == EXPECTED_V43_FREEZE_SHA256 and lineage.get("v43_frozen_file_count") == 193 and lineage.get("v43_immutable_file_count") == 191),
        "v44_identities_exact": all(identities.get(key) == value for key, value in SEAL_TIME_IDENTITY_PATCH_POINTS.items()),
        "capacity_decision_exact": bool(decisions.get("overall") == "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB" and decisions.get("production_admission") == "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION" and decisions.get("next_falsifiable_gate") == "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY" and evidence.get("capacity_precheck_sha256") == EXPECTED_CAPACITY_PRECHECK_SHA256 and evidence.get("target_qubits") == 156 and evidence.get("rejected_seed_count") == 8 and evidence.get("maximum_logical_qubits") == 339 and evidence.get("maximum_capacity_deficit_qubits") == -183 and evidence.get("persistent_register_floor_qubits") == 160),
        "canary_evidence_exact": bool(evidence.get("accepted_canary_count") == 5 and evidence.get("clean_process_replay_count") == 2 and evidence.get("clean_process_replay_stable") is True and evidence.get("canary_bundle_sha256") == EXPECTED_CANARY_BUNDLE_SHA256 and evidence.get("capacity_157_control") == "EXPECTED_REJECTION"),
        "provider_hardware_performance_advantage_boundary_exact": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("full_workload_transpilation") == "NOT_RUN_CAPACITY_PRECHECK_REJECTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "successor_policy_accepts_only_v43_or_exact_v44": bool(successor.get("accepted_target_states") == ["V4.3", "V4.4"] and successor.get("allowed_v43_superseded_files") == [README_PATH, UI_PATH] and successor.get("immutable_v43_frozen_file_count") == 191 and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_rollback_exact": bool(deployment.get("overlay_file_count") == 20 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP"),
        "route_and_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "packaging_contract_exact": bool(packaging.get("institutional_archive_entries") == 212 and packaging.get("overlay_archive_entries") == 20 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256"),
        "validation_targets_exact": bool(targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("release_hardening_tests") == EXPECTED_RELEASE_HARDENING_TEST_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT),
        "identity_release_chain_valid_and_labelled": bool(release.get("valid") is True and release.get("deep_scientific_replay") is False and release.get("fresh_qiskit_replay") is False and release.get("check_count") == EXPECTED_RELEASE_CHECK_COUNT),
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    if len(checks) != EXPECTED_FREEZE_CHECK_COUNT:
        raise AssertionError(f"V4.4 freeze verifier check count drifted: {len(checks)}")
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
        "verifier": "QUANTUM LAB V4.4 FREEZE CONTRACT · V1",
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
            "verifier": "QUANTUM LAB V4.4 FREEZE CONTRACT · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["SEAL_TIME_IDENTITY_PATCH_POINTS", "verify_freeze_contract"]
