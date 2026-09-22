"""Independent immutable-freeze verifier for Quantum Lab V4.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v41_certified_bridge_compiler import canonical_json_sha256
from .verify_phase3_v41 import (
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_VALIDATION_EVIDENCE_SHA,
    EXPECTED_V40_FREEZE_RAW,
    EXPECTED_V40_FREEZE_SHA,
    EXPECTED_V41_ARTIFACT_RAW,
    EXPECTED_V41_ARTIFACT_SHA,
    EXPECTED_V41_ENGINE_RAW,
    EXPECTED_V41_PATH_FINGERPRINT,
    EXPECTED_V41_SOURCE_RAW,
    EXPECTED_V41_SPEC_RAW,
    EXPECTED_V41_SPEC_SHA,
    FREEZE_PATH,
    PARENT_FREEZE_PATH,
    README_PATH,
    UI_PATH,
    V41_PATHS,
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
            if not relative or item.is_absolute() or any(
                part in {"", ".", ".."} for part in item.parts
            ):
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
    identities = contract.get("v41_identities") or {}
    decisions = contract.get("scientific_decisions") or {}
    boundary = contract.get("claim_boundary") or {}
    deployment = contract.get("deployment_contract") or {}
    successor = contract.get("successor_policy") or {}
    targets = contract.get("validation_targets") or {}
    checks = {
        "contract_version_is_exact": contract.get("freeze_contract_version")
        == "QUANTUM LAB V4.1 FREEZE CONTRACT · V1",
        "contract_self_hash_is_exact": contract.get("freeze_contract_sha256")
        == _freeze_semantic(contract),
        "frozen_file_count_is_161": bool(
            contract.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT
            and len(frozen) == EXPECTED_FROZEN_FILE_COUNT
        ),
        "path_fingerprint_is_exact": fingerprint == EXPECTED_V41_PATH_FINGERPRINT,
        "all_frozen_files_are_regular_contained_and_exact": bool(
            len(file_results) == EXPECTED_FROZEN_FILE_COUNT
            and all(file_results.values())
        ),
        "all_v41_transition_paths_are_frozen": set(V41_PATHS).issubset(frozen),
        "v40_lineage_is_exact": bool(
            lineage.get("v40_freeze_raw_file_sha256") == EXPECTED_V40_FREEZE_RAW
            and lineage.get("v40_freeze_sha256") == EXPECTED_V40_FREEZE_SHA
            and lineage.get("v40_frozen_file_count") == 145
            and lineage.get("v40_immutable_file_count") == 143
            and frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V40_FREEZE_RAW
        ),
        "v41_spec_artifact_engine_source_and_validation_identities_are_exact": bool(
            identities.get("v41_spec_raw_file_sha256") == EXPECTED_V41_SPEC_RAW
            and identities.get("v41_spec_sha256") == EXPECTED_V41_SPEC_SHA
            and identities.get("v41_artifact_raw_file_sha256")
            == EXPECTED_V41_ARTIFACT_RAW
            and identities.get("v41_artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA
            and identities.get("v41_engine_raw_file_sha256") == EXPECTED_V41_ENGINE_RAW
            and identities.get("v41_source_raw_file_sha256") == EXPECTED_V41_SOURCE_RAW
            and identities.get("validation_evidence_sha256")
            == EXPECTED_VALIDATION_EVIDENCE_SHA
        ),
        "bounded_scientific_decisions_are_exact": bool(
            decisions.get("overall")
            == "V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED"
            and decisions.get("augmented_connectivity_decision")
            == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
            and decisions.get("resource_architecture_decision")
            == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            and decisions.get("production_admission")
            == "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED"
            and decisions.get("next_falsifiable_gate")
            == "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION"
        ),
        "provider_hardware_and_advantage_boundary_is_zero": bool(
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
        "successor_policy_accepts_only_v40_or_exact_v41": bool(
            successor.get("accepted_target_states") == ["V4.0", "V4.1"]
            and successor.get("allowed_v40_superseded_files")
            == [README_PATH, UI_PATH]
            and successor.get("mixed_or_third_state") == "REJECT"
        ),
        "deployment_overlay_and_order_are_exact": bool(
            deployment.get("overlay_file_count") == 18
            and deployment.get("readme_surface_penultimate") == README_PATH
            and deployment.get("integration_surface_last") == UI_PATH
        ),
        "deployment_is_staged_owned_lock_idempotent_and_rollback_capable": bool(
            deployment.get("source_snapshot_rehashed_before_commit") is True
            and deployment.get("lock_release_requires_owned_token") is True
            and deployment.get("idempotent_exact_reapply") == "NO_OP"
            and deployment.get("rollback_requires_preimage_hashes") is True
            and deployment.get("candidate_stage_validation") == "REQUIRED"
        ),
        "route_and_tab_contract_are_preserved": bool(
            deployment.get("route") == "?workspace=quantum-research"
            and deployment.get("streamlit_tab_count") == 12
        ),
        "validation_target_counts_are_exact": bool(
            targets.get("artifact_reconstruction_checks") == 16
            and targets.get("scientific_validation_checks") == 28
            and targets.get("release_chain_checks") == 29
            and targets.get("freeze_contract_checks") == 18
            and targets.get("streamlit_ui_checks") == 31
        ),
        "identity_release_chain_is_independently_valid": release.get("valid") is True,
        "identity_release_chain_has_29_checks_and_is_labelled": bool(
            release.get("check_count") == 29
            and release.get("deep_scientific_replay") is False
        ),
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    failed = [name for name, value in checks.items() if value is not True]
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
        "verifier": "QUANTUM LAB V4.1 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V4.1 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["verify_freeze_contract"]
