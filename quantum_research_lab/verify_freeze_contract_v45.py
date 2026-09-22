"""Independent immutable-freeze verifier for Quantum Lab V4.5."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v45_proof_carrying_width_reduction import (
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_V44_FREEZE_RAW_SHA256,
    EXPECTED_V44_FREEZE_SHA256,
    EXPECTED_V44_PATH_FINGERPRINT,
    canonical_json_sha256,
)
from .phase3_v45_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CERTIFICATE_RAW_SHA256,
    EXPECTED_CERTIFICATE_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_SOURCE_RAW_SHA256,
)
from .verify_phase3_v45 import (
    EXPECTED_FREEZE_CHECK_COUNT,
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_RELEASE_HARDENING_TEST_COUNT,
    EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
    EXPECTED_UI_CHECK_COUNT,
    EXPECTED_V45_PATH_FINGERPRINT,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V45_FROZEN_TRANSITION_PATHS,
    verify_release_chain,
)


SEAL_TIME_IDENTITY_PATCH_POINTS = {
    "liveness_certificate_raw_file_sha256": EXPECTED_CERTIFICATE_RAW_SHA256,
    "liveness_certificate_sha256": EXPECTED_CERTIFICATE_SHA256,
    "v45_artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
    "v45_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
    "v45_checker_raw_file_sha256": EXPECTED_CHECKER_RAW_SHA256,
    "v45_source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
    "v45_spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
    "v45_spec_sha256": EXPECTED_SPEC_SHA256,
    "v45_validation_source_raw_file_sha256": EXPECTED_VALIDATION_SOURCE_RAW_SHA256,
    "validation_evidence_sha256": EXPECTED_VALIDATION_EVIDENCE_SHA256,
}
EXPECTED_V45_OVERLAY_ORDER_SHA256 = "d1c59d3e9a83675d67cb62f6b20aa9ca3fa3494a1376fadf8aa8e0a873d8073f"


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
        errors.append(f"V4.5 freeze unavailable: {exc}")
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
    identities = contract.get("v45_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    evidence = contract.get("validation_evidence") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    checks: dict[str, bool] = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.5 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _semantic(contract),
        "frozen_file_count_229": contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "path_fingerprint_exact": fingerprint == contract.get("frozen_paths_fingerprint_sha256") == EXPECTED_V45_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_v45_transition_payloads_and_v44_freeze_frozen": set(V45_FROZEN_TRANSITION_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V44_FREEZE_RAW_SHA256,
        "v44_lineage_exact": bool(lineage.get("v44_freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256 and lineage.get("v44_freeze_sha256") == EXPECTED_V44_FREEZE_SHA256 and lineage.get("v44_frozen_file_count") == 211 and lineage.get("v44_frozen_paths_fingerprint_sha256") == EXPECTED_V44_PATH_FINGERPRINT and lineage.get("v44_immutable_file_count") == 209),
        "v45_identities_exact": all(identities.get(key) == value for key, value in SEAL_TIME_IDENTITY_PATCH_POINTS.items()),
        "width_decision_exact": bool(decisions.get("overall") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY" and decisions.get("production_admission") == "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED" and decisions.get("next_falsifiable_gate") == "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS" and evidence.get("all_eight_widths") == [135, 137, 133, 135, 137, 137, 145, 139] and evidence.get("all_eight_widths_fit_156") is True and evidence.get("maximum_logical_qubits") == 145 and evidence.get("minimum_capacity_margin_qubits") == 11),
        "resource_and_certificate_evidence_exact": bool(evidence.get("all_eight_cnot_budget_pass") is True and evidence.get("cnot_budget_pass_count") == 8 and evidence.get("maximum_materialized_cnot") == 2499790 and evidence.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256 and evidence.get("clean_process_replay_count") == 2 and evidence.get("replay_artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and evidence.get("replay_stable") is True),
        "provider_hardware_performance_advantage_boundary_exact": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("full_workload_transpilation") == "NOT_RUN_IN_V4_5" and boundary.get("full_workload_routing") == "NOT_RUN_IN_V4_5" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "successor_policy_accepts_only_v44_or_exact_v45": bool(successor.get("accepted_target_states") == ["V4.4", "V4.5"] and successor.get("allowed_v44_superseded_files") == [README_PATH, UI_PATH] and successor.get("immutable_v44_frozen_file_count") == 209 and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_rollback_exact": bool(deployment.get("overlay_file_count") == 20 and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V45_OVERLAY_ORDER_SHA256 and hashlib.sha256(json.dumps(deployment.get("ordered_transition_paths"), separators=(",", ":")).encode("utf-8")).hexdigest() == EXPECTED_V45_OVERLAY_ORDER_SHA256 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP"),
        "route_and_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "packaging_contract_exact": bool(packaging.get("institutional_archive_entries") == 230 and packaging.get("overlay_archive_entries") == 20 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_symlink_entries") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY" and packaging.get("deterministic_double_build") == "REQUIRED_IDENTICAL_SHA256"),
        "validation_targets_exact": bool(targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("historical_scientific_unit_tests") == 161 and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("release_hardening_tests") == EXPECTED_RELEASE_HARDENING_TEST_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT),
        "identity_release_chain_valid_and_labelled": bool(release.get("valid") is True and release.get("deep_scientific_replay") is False and release.get("fresh_qiskit_replay") is False and release.get("check_count") == EXPECTED_RELEASE_CHECK_COUNT),
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    if len(checks) != EXPECTED_FREEZE_CHECK_COUNT:
        raise AssertionError(f"V4.5 freeze verifier check count drifted: {len(checks)}")
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
        "verifier": "QUANTUM LAB V4.5 FREEZE CONTRACT · V1",
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
            "verifier": "QUANTUM LAB V4.5 FREEZE CONTRACT · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["SEAL_TIME_IDENTITY_PATCH_POINTS", "verify_freeze_contract"]
