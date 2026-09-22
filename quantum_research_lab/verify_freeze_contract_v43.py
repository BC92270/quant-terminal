"""Independent immutable-freeze verifier for Quantum Lab V4.3."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v43_reversible_circuit_ir import canonical_json_sha256
from .verify_phase3_v43 import (
    EXPECTED_FREEZE_CHECK_COUNT,
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
    EXPECTED_UI_CHECK_COUNT,
    EXPECTED_V42_FREEZE_RAW,
    EXPECTED_V42_FREEZE_SHA,
    EXPECTED_V43_ARTIFACT_RAW,
    EXPECTED_V43_ARTIFACT_SHA,
    EXPECTED_V43_PATH_FINGERPRINT,
    EXPECTED_V43_SIMULATOR_RAW,
    EXPECTED_V43_SOURCE_RAW,
    EXPECTED_V43_SPEC_RAW,
    EXPECTED_V43_SPEC_SHA,
    EXPECTED_V43_VALIDATION_RAW,
    EXPECTED_VALIDATION_EVIDENCE_SHA,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V43_PATHS,
    verify_release_chain,
)


# Seal-time identity patch points.  Keep these values and the matching constants
# in verify_phase3_v43.py synchronized if any scientific source is changed
# before the immutable V4.3 freeze is generated.
SEAL_TIME_IDENTITY_PATCH_POINTS = {
    "v43_artifact_raw_file_sha256": EXPECTED_V43_ARTIFACT_RAW,
    "v43_artifact_sha256": EXPECTED_V43_ARTIFACT_SHA,
    "v43_simulator_raw_file_sha256": EXPECTED_V43_SIMULATOR_RAW,
    "v43_source_raw_file_sha256": EXPECTED_V43_SOURCE_RAW,
    "v43_spec_raw_file_sha256": EXPECTED_V43_SPEC_RAW,
    "v43_spec_sha256": EXPECTED_V43_SPEC_SHA,
    "validation_evidence_sha256": EXPECTED_VALIDATION_EVIDENCE_SHA,
    "validation_source_raw_file_sha256": EXPECTED_V43_VALIDATION_RAW,
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


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def verify_freeze_contract(
    root: str | Path,
    contract_path: str | Path | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    target = Path(contract_path) if contract_path else release_root / FREEZE_PATH
    if not target.is_absolute():
        target = release_root / target
    errors: list[str] = []
    try:
        contract = _read_json_strict(target)
    except Exception as exc:
        contract = {}
        errors.append(f"V4.3 freeze unavailable: {exc}")
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

    try:
        release = verify_release_chain(release_root, deep=False)
    except Exception as exc:
        release = {"check_count": EXPECTED_RELEASE_CHECK_COUNT, "errors": [str(exc)], "valid": False}
        errors.append(f"release verifier failed: {exc}")

    lineage = contract.get("lineage") or {}
    identities = contract.get("v43_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    evidence = contract.get("validation_evidence") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    checks: dict[str, bool] = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.3 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _freeze_semantic(contract),
        "frozen_file_count_193": contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "path_fingerprint_exact": fingerprint == contract.get("frozen_paths_fingerprint_sha256") == EXPECTED_V43_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_v43_transition_paths_and_v42_freeze_frozen": set(V43_PATHS).issubset(frozen) and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V42_FREEZE_RAW,
        "v42_lineage_exact": bool(lineage.get("v42_freeze_raw_file_sha256") == EXPECTED_V42_FREEZE_RAW and lineage.get("v42_freeze_sha256") == EXPECTED_V42_FREEZE_SHA and lineage.get("v42_frozen_file_count") == 177 and lineage.get("v42_immutable_file_count") == 175),
        "v43_identities_exact": bool(all(identities.get(key) == value for key, value in SEAL_TIME_IDENTITY_PATCH_POINTS.items())),
        "bounded_scientific_decisions_exact": bool(decisions.get("overall") == "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED" and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED" and decisions.get("next_falsifiable_gate") == "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL" and decisions.get("promise_scope") == "ACCEPTED_ONLY_FOR_EXACT_FEASIBLE_N40_DATA_AND_TWO_ONE_HOT_COIN_REGISTERS"),
        "materialization_and_simulation_evidence_exact": bool(evidence.get("seed_count") == 8 and evidence.get("maximum_materialized_cnot") == 1_158_046 and evidence.get("minimum_budget_margin_cnot") == 1_341_954 and evidence.get("maximum_logical_qubits") == 339 and evidence.get("total_elementary_instructions") == 21_925_902 and evidence.get("cpp_arithmetic_cases") == 107_520 and evidence.get("cpp_promise_select_cases") == 64 and evidence.get("cpp_promise_select_roundtrips") == 64 and evidence.get("off_promise_status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"),
        "provider_backend_hardware_advantage_boundary_exact": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "successor_policy_accepts_only_v42_or_exact_v43": bool(successor.get("accepted_target_states") == ["V4.2", "V4.3"] and successor.get("allowed_v42_superseded_files") == [README_PATH, UI_PATH] and successor.get("immutable_v42_frozen_file_count") == 175 and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_rollback_exact": bool(deployment.get("overlay_file_count") == 18 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP"),
        "route_and_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "packaging_contract_exact": bool(packaging.get("institutional_archive_entries") == 194 and packaging.get("overlay_archive_entries") == 18 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY"),
        "validation_targets_exact": bool(targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT),
        "identity_release_chain_valid_and_labelled": bool(release.get("valid") is True and release.get("deep_scientific_replay") is False and release.get("deep_stream_rebuild") is False and release.get("check_count") == EXPECTED_RELEASE_CHECK_COUNT),
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    if len(checks) != EXPECTED_FREEZE_CHECK_COUNT:
        raise AssertionError(f"V4.3 freeze verifier check count drifted: {len(checks)}")
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
        "verifier": "QUANTUM LAB V4.3 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path, help="Release root (default: current directory).")
    parser.add_argument("--root", dest="root_option", type=Path, help="Release root (explicit option form).")
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass the release root either positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_freeze_contract(root, args.contract)
    except Exception as exc:
        report = {
            "check_count": EXPECTED_FREEZE_CHECK_COUNT,
            "checks": {},
            "contract": str(args.contract or FREEZE_PATH),
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "root": str(root),
            "valid": False,
            "verifier": "QUANTUM LAB V4.3 FREEZE CONTRACT · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["SEAL_TIME_IDENTITY_PATCH_POINTS", "verify_freeze_contract"]
