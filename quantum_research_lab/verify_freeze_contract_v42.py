"""Independent immutable-freeze verifier for Quantum Lab V4.2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v42_coined_walk_compiler import canonical_json_sha256
from .verify_phase3_v42 import (
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_VALIDATION_EVIDENCE_SHA,
    EXPECTED_V41_FREEZE_RAW,
    EXPECTED_V41_FREEZE_SHA,
    EXPECTED_V42_ARTIFACT_RAW,
    EXPECTED_V42_ARTIFACT_SHA,
    EXPECTED_V42_ENGINE_RAW,
    EXPECTED_V42_PATH_FINGERPRINT,
    EXPECTED_V42_SOURCE_RAW,
    EXPECTED_V42_SPEC_RAW,
    EXPECTED_V42_SPEC_SHA,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V42_PATHS,
    verify_release_chain,
)


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
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


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
        return {"valid": False, "errors": [str(exc)], "checks": {}}
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
            file_results[relative] = hashlib.sha256(cursor.read_bytes()).hexdigest() == expected
        except Exception as exc:
            file_results[relative] = False
            errors.append(f"{relative}: {exc}")
    try:
        release = verify_release_chain(release_root, deep=False)
    except Exception as exc:
        release = {"valid": False, "errors": [str(exc)], "checks": {}}
        errors.append(f"release verifier failed: {exc}")

    lineage = contract.get("lineage") or {}
    identities = contract.get("v42_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    evidence = contract.get("validation_evidence") or {}
    boundary = contract.get("claim_boundary") or {}
    successor = contract.get("successor_policy") or {}
    deployment = contract.get("deployment_contract") or {}
    packaging = contract.get("packaging_contract") or {}
    targets = contract.get("validation_targets") or {}
    checks = {
        "contract_version_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V4.2 FREEZE CONTRACT · V1",
        "contract_self_hash_exact": contract.get("freeze_contract_sha256") == _freeze_semantic(contract),
        "frozen_file_count_177": contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "path_fingerprint_exact": fingerprint == EXPECTED_V42_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_v42_transition_paths_frozen": set(V42_PATHS).issubset(frozen),
        "v41_lineage_exact": bool(lineage.get("v41_freeze_raw_file_sha256") == EXPECTED_V41_FREEZE_RAW and lineage.get("v41_freeze_sha256") == EXPECTED_V41_FREEZE_SHA and lineage.get("v41_frozen_file_count") == 161 and lineage.get("v41_immutable_file_count") == 159 and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V41_FREEZE_RAW),
        "v42_identities_exact": bool(identities.get("v42_spec_raw_file_sha256") == EXPECTED_V42_SPEC_RAW and identities.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA and identities.get("v42_engine_raw_file_sha256") == EXPECTED_V42_ENGINE_RAW and identities.get("v42_source_raw_file_sha256") == EXPECTED_V42_SOURCE_RAW and identities.get("v42_artifact_raw_file_sha256") == EXPECTED_V42_ARTIFACT_RAW and identities.get("v42_artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA and identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA),
        "bounded_scientific_decisions_exact": bool(decisions.get("overall") == "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED" and decisions.get("generator_support_decision") == "CONNECTED_ALL_SEEDS_EXACT_V41_SUPPORT_PRESERVED" and decisions.get("resource_architecture_decision") == "PASSED_SELECTED_MODEL_CNOT_BUDGET" and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED" and decisions.get("next_falsifiable_gate") == "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION"),
        "support_and_resource_evidence_exact": bool(evidence.get("seed_count") == 8 and evidence.get("pair_positions_preserved_per_seed") == 780 and evidence.get("parent_selected_bridges") == 3 and evidence.get("joint_promise_vertices") == 34_649_241_600 and evidence.get("joint_support_edges") == 69_973_909_206 and evidence.get("maximum_selected_model_cnot") == 1_135_430 and evidence.get("minimum_budget_margin_cnot") == 1_364_570 and evidence.get("maximum_logical_qubits") == 331),
        "provider_circuit_hardware_advantage_boundary_exact": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("circuit_materialization") == "NOT_RUN_NEXT_GATE" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "successor_policy_accepts_only_v41_or_exact_v42": bool(successor.get("accepted_target_states") == ["V4.1", "V4.2"] and successor.get("allowed_v41_superseded_files") == [README_PATH, UI_PATH] and successor.get("immutable_v41_frozen_file_count") == 159 and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_rollback_exact": bool(deployment.get("overlay_file_count") == 18 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP"),
        "route_and_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "packaging_contract_exact": bool(packaging.get("institutional_archive_entries") == 178 and packaging.get("overlay_archive_entries") == 18 and packaging.get("archive_duplicate_entries") == "REJECT" and packaging.get("archive_path_traversal") == "REJECT" and packaging.get("archive_integrity") == "CRC_AND_EXACT_BYTE_EQUALITY"),
        "validation_targets_exact": bool(targets.get("artifact_reconstruction_checks") == 16 and targets.get("scientific_validation_checks") == 35 and targets.get("streamlit_ui_checks") == 30 and targets.get("freeze_contract_checks") == 18 and targets.get("scientific_unit_tests") == 18 and targets.get("release_hardening_tests") == 15 and targets.get("frozen_file_count") == 177),
        "identity_release_chain_valid_and_labelled": bool(release.get("valid") is True and release.get("deep_scientific_replay") is False and release.get("check_count") == 32),
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
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
        "verifier": "QUANTUM LAB V4.2 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["verify_freeze_contract"]
