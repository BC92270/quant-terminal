"""Independent immutable-freeze verifier for Quantum Lab V3.8."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .verify_phase3_v38 import (
    EXPECTED_FROZEN_FILE_COUNT,
    EXPECTED_V38_PATH_FINGERPRINT,
    FREEZE_PATH,
    V38_PATHS,
    verify_release_chain,
)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_non_finite,
    )
    if not isinstance(payload, dict):
        raise ValueError("Freeze contract must be a JSON object.")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def verify_freeze_contract(
    root: str | Path, contract_path: str | Path | None = None
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
    path_fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    file_results: dict[str, bool] = {}
    for relative, expected in sorted(frozen.items()):
        item = Path(relative)
        try:
            if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
                raise ValueError("unsafe relative path")
            path = release_root / item
            cursor = release_root
            for part in item.parts:
                cursor = cursor / part
                mode = cursor.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise ValueError("symlink rejected")
            cursor.resolve(strict=True).relative_to(release_root)
            if not stat.S_ISREG(cursor.lstat().st_mode):
                raise ValueError("not a regular file")
            file_results[relative] = hashlib.sha256(path.read_bytes()).hexdigest() == expected
        except Exception as exc:
            file_results[relative] = False
            errors.append(f"{relative}: {exc}")
    try:
        release = verify_release_chain(release_root)
    except Exception as exc:
        release = {"valid": False, "errors": [str(exc)], "checks": {}}
        errors.append(f"release verifier failed: {exc}")
    lineage = contract.get("lineage") or {}
    decisions = contract.get("scientific_decisions") or {}
    boundary = contract.get("claim_boundary") or {}
    deployment = contract.get("deployment_contract") or {}
    successor = contract.get("successor_policy") or {}
    checks = {
        "contract_version_is_exact": contract.get("freeze_contract_version")
        == "QUANTUM LAB V3.8 FREEZE CONTRACT · V1",
        "contract_self_hash_is_exact": contract.get("freeze_contract_sha256")
        == _freeze_semantic(contract),
        "frozen_file_count_is_114": contract.get("frozen_file_count")
        == EXPECTED_FROZEN_FILE_COUNT
        and len(frozen) == EXPECTED_FROZEN_FILE_COUNT,
        "path_fingerprint_is_exact": path_fingerprint == EXPECTED_V38_PATH_FINGERPRINT,
        "all_frozen_files_are_regular_contained_and_exact": len(file_results)
        == EXPECTED_FROZEN_FILE_COUNT
        and all(file_results.values()),
        "all_v38_transition_paths_are_frozen": set(V38_PATHS).issubset(frozen),
        "v37_lineage_is_exact": bool(
            lineage.get("v37_artifact_sha256")
            == "5773b8f38bd1400f4eb1edf5a016ab69c85fc794aefe31fd1a742d08174bee36"
            and lineage.get("v37_artifact_raw_file_sha256")
            == "93c207a6c0d6723277bf682a678740b330a6a3127d59d63ce28a244bdf606365"
            and lineage.get("v37_freeze_sha256")
            == "86f247a9dfb918a2eca04ffe96c03adee62c3d8603d99aab3e0d6bf8c07167e7"
            and lineage.get("v37_freeze_raw_file_sha256")
            == "57b273f87e4e2f2a95e0ccbdd6c844c1c3f5d8bfec5dbfd5d488aaefb0290970"
        ),
        "bounded_scientific_decisions_are_exact": bool(
            decisions.get("overall") == "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED"
            and decisions.get("elementary_decomposition")
            == "VALIDATED_ON_REGISTERED_N4_K2_PROTOTYPE"
            and decisions.get("n40_resource_admission")
            == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
            and decisions.get("n40_selected_model_cnot") == "NOT_ESTIMATED"
            and decisions.get("n40_budget_gate") == "NOT_EVALUATED"
        ),
        "provider_hardware_and_advantage_boundary_is_zero": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "successor_policy_accepts_only_v37_or_exact_v38": bool(
            successor.get("accepted_target_states") == ["V3.7", "V3.8"]
            and successor.get("allowed_v37_superseded_files") == [
                "quantum_research_lab/README.md",
                "quantum_research_lab/ui.py",
            ]
            and successor.get("mixed_or_third_state") == "REJECT"
        ),
        "deployment_overlay_and_order_are_exact": bool(
            deployment.get("overlay_file_count") == len(V38_PATHS) + 1
            and deployment.get("readme_surface_penultimate") == "quantum_research_lab/README.md"
            and deployment.get("integration_surface_last") == "quantum_research_lab/ui.py"
        ),
        "deployment_is_idempotent_and_rollback_capable": bool(
            deployment.get("idempotent_exact_reapply") == "NO_OP"
            and deployment.get("rollback_requires_preimage_hashes") is True
            and deployment.get("clean_extract_self_contained_verification") == "REQUIRED"
        ),
        "route_and_tab_contract_are_preserved": bool(
            deployment.get("route") == "?workspace=quantum-research"
            and deployment.get("streamlit_tab_count") == 12
        ),
        "validation_target_counts_are_exact": bool(
            (contract.get("validation_targets") or {}).get("scientific_validation_checks") == 15
            and (contract.get("validation_targets") or {}).get("release_chain_checks") == 21
            and (contract.get("validation_targets") or {}).get("freeze_contract_checks") == 17
            and (contract.get("validation_targets") or {}).get("streamlit_ui_checks") == 31
        ),
        "release_chain_is_independently_valid": release.get("valid") is True,
        "release_chain_has_21_checks": release.get("check_count") == 21,
        "no_release_or_freeze_errors": not errors and not release.get("errors"),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "root": str(release_root),
        "contract": str(target),
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": failed,
        "errors": list(dict.fromkeys(errors + list(release.get("errors") or []))),
        "frozen_file_count": len(file_results),
        "valid": not failed and not errors and release.get("valid") is True,
        "verifier": "QUANTUM LAB V3.8 FREEZE CONTRACT · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.8 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--contract", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["verify_freeze_contract"]
