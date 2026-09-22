"""Independent immutable-freeze verifier for Quantum Lab V3.9."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v39_scalable_reversible_ir import canonical_json_sha256
from .verify_phase3_v39 import (
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_V38_FREEZE_RAW,
    EXPECTED_V38_FREEZE_SHA,
    EXPECTED_V39_ARTIFACT_RAW,
    EXPECTED_V39_ARTIFACT_SHA,
    EXPECTED_V39_PATH_FINGERPRINT,
    EXPECTED_V39_SPEC_RAW,
    EXPECTED_V39_SPEC_SHA,
    FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V39_PATHS,
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
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates, parse_constant=_reject_nonfinite)
    if not isinstance(payload, dict):
        raise ValueError("Freeze contract must be a JSON object.")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
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
        return {"valid": False, "errors": [str(exc)], "checks": {}}
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
            file_results[relative] = hashlib.sha256(cursor.read_bytes()).hexdigest() == expected
        except Exception as exc:
            file_results[relative] = False
            errors.append(f"{relative}: {exc}")
    try:
        release = verify_release_chain(release_root)
    except Exception as exc:
        release = {"valid": False, "errors": [str(exc)], "checks": {}}
        errors.append(f"release verifier failed: {exc}")
    lineage = contract.get("lineage") or {}
    identities = contract.get("v39_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    boundary = contract.get("claim_boundary") or {}
    deployment = contract.get("deployment_contract") or {}
    successor = contract.get("successor_policy") or {}
    targets = contract.get("validation_targets") or {}
    checks = {
        "contract_version_is_exact": contract.get("freeze_contract_version") == "QUANTUM LAB V3.9 FREEZE CONTRACT · V1",
        "contract_self_hash_is_exact": contract.get("freeze_contract_sha256") == _freeze_semantic(contract),
        "frozen_file_count_is_129": contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and len(frozen) == EXPECTED_FROZEN_FILE_COUNT,
        "path_fingerprint_is_exact": fingerprint == EXPECTED_V39_PATH_FINGERPRINT,
        "all_frozen_files_are_regular_contained_and_exact": len(file_results) == EXPECTED_FROZEN_FILE_COUNT and all(file_results.values()),
        "all_v39_transition_paths_are_frozen": set(V39_PATHS).issubset(frozen),
        "v38_lineage_is_exact": bool(lineage.get("v38_freeze_raw_file_sha256") == EXPECTED_V38_FREEZE_RAW and lineage.get("v38_freeze_sha256") == EXPECTED_V38_FREEZE_SHA and frozen.get("FREEZE_CONTRACT_V3_8.json") == EXPECTED_V38_FREEZE_RAW),
        "v39_spec_and_artifact_identities_are_exact": bool(identities.get("v39_spec_raw_file_sha256") == EXPECTED_V39_SPEC_RAW and identities.get("v39_spec_sha256") == EXPECTED_V39_SPEC_SHA and identities.get("v39_artifact_raw_file_sha256") == EXPECTED_V39_ARTIFACT_RAW and identities.get("v39_artifact_sha256") == EXPECTED_V39_ARTIFACT_SHA),
        "bounded_scientific_decisions_are_exact": bool(decisions.get("overall") == "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED" and decisions.get("reversible_ir_decision") == "N40_REVERSIBLE_IR_PASSED" and decisions.get("budget_decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET" and decisions.get("complete_global_connectivity") == "INDETERMINATE" and decisions.get("production_admission") == "BLOCKED_GLOBAL_CONNECTIVITY_AND_BACKEND"),
        "provider_hardware_and_advantage_boundary_is_zero": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_calls") == 0 and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("hardware_executable") is False and boundary.get("qpu_submission_enabled") is False and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "successor_policy_accepts_only_v38_or_exact_v39": bool(successor.get("accepted_target_states") == ["V3.8", "V3.9"] and successor.get("allowed_v38_superseded_files") == [README_PATH, UI_PATH] and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_and_order_are_exact": bool(deployment.get("overlay_file_count") == 17 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH),
        "deployment_is_staged_owned_lock_idempotent_and_rollback_capable": bool(deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("lock_release_requires_owned_token") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("rollback_requires_preimage_hashes") is True),
        "route_and_tab_contract_are_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "validation_target_counts_are_exact": targets.get("scientific_validation_checks") == 18 and targets.get("release_chain_checks") == 24 and targets.get("freeze_contract_checks") == 18 and targets.get("streamlit_ui_checks") == 23,
        "release_chain_is_independently_valid": release.get("valid") is True,
        "release_chain_has_24_checks": release.get("check_count") == 24,
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "root": str(release_root),
        "contract": str(target),
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": failed,
        "errors": list(dict.fromkeys(errors + list(release.get("errors") or []))),
        "frozen_file_count": len(file_results),
        "valid": not failed and not errors and release.get("valid") is True,
        "verifier": "QUANTUM LAB V3.9 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.9 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["verify_freeze_contract"]
