"""Fail-closed release-chain verifier for Quantum Lab V4.2."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v42_coined_walk_compiler import canonical_json_sha256, load_v42_spec, raw_file_sha256
from .phase3_v42_validation import run_v42_validation


FREEZE_PATH = "FREEZE_CONTRACT_V4_2.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_1.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V42_PATHS = (
    "DEPLOY_V4_2.md",
    "app_v42_offline_harness.py",
    "install_quantum_lab_v42.py",
    "outputs/quantum_phase3/v42_coined_walk/SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_2_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v42_selector_engine.cpp",
    "quantum_research_lab/phase3_v42_coined_walk_compiler.py",
    "quantum_research_lab/phase3_v42_ui.py",
    "quantum_research_lab/phase3_v42_validation.py",
    "quantum_research_lab/test_phase3_v42.py",
    "quantum_research_lab/test_phase3_v42_release.py",
    "quantum_research_lab/verify_freeze_contract_v42.py",
    "quantum_research_lab/verify_phase3_v42.py",
    "quantum_research_lab/verify_phase3_v42_ui.py",
    README_PATH,
    UI_PATH,
)

EXPECTED_FROZEN_FILE_COUNT = 177
EXPECTED_V42_PATH_FINGERPRINT = "cc3dd736d2475cfc1d143bc720fc37863d62ede26019a3aa99cd33e96643b166"
EXPECTED_V41_FREEZE_RAW = "43d3bd4e9cdcb54e9a7c1649430f6bd10cae9ef51ac5d77319a7630639b0c34f"
EXPECTED_V41_FREEZE_SHA = "b9ec84e2110e40cf1c77fb90b18794ff80e26ddf12233d5193eb18ca5aa6c201"
EXPECTED_V41_PATH_FINGERPRINT = "27bb43b53f3c6847d1ef80518c595755c1e606015b423c194c8a2e61f3f76ea8"
EXPECTED_V42_SPEC_RAW = "11b9d7a86fc1617f7c313c2cda58c4b8874d33cb9e4fe11460a65b8920e40674"
EXPECTED_V42_SPEC_SHA = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_V42_ENGINE_RAW = "3d73cddfc7c06cf6e0e5bc22a3ad29c3ea79ac22d7c1e5a8b1ca1044789c65ab"
EXPECTED_V42_SOURCE_RAW = "fc4b9ce991cc866aa7a9b809172df41227e9dcd133a41d210068663ee7bd77e9"
EXPECTED_V42_ARTIFACT_RAW = "0952111064db57f6c1122e9a7b4d45ee997667e0d57137ea173be0009ba4feec"
EXPECTED_V42_ARTIFACT_SHA = "f2f294f8f0a21804d7dd6a23d7695b161723fcc1efea48b2f9d1ce7bcbb3f5be"
EXPECTED_VALIDATION_EVIDENCE_SHA = "8f392dee270fd7d5fd0d7d21fc6e8ec4d3aebe6077bb16ad4f122521da8f93e3"


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
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _contained_regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe release path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked release path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Release path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _spec_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in {"v42_spec_sha", "v42_spec_sha256"}}
    )


def _artifact_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "artifact_sha256"}
    )


def _fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _provider_free_imports(path: Path) -> bool:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name.split(".")[0] in forbidden for name in names):
            return False
    return True


def _identity_validation(freeze: Mapping[str, Any]) -> dict[str, Any]:
    identities = freeze.get("v42_identities") or {}
    exact = identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA
    return {
        "checks": {"frozen_validation_evidence_identity": exact},
        "counts": {"checks_passed": 35 if exact else 0, "checks_total": 35},
        "errors": [] if exact else ["Frozen V4.2 scientific-validation identity mismatch."],
        "failed_checks": [] if exact else ["frozen_validation_evidence_identity"],
        "passed": exact,
        "validation_evidence_sha256": identities.get("validation_evidence_sha256"),
        "validation_version": "IDENTITY_ONLY · DEEP REPLAY NOT RUN IN THIS INVOCATION",
    }


def verify_release_chain(root: str | Path, *, deep: bool = True) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.2 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.2 frozen_files must be an object.")

    frozen_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen.items()):
        try:
            actual = raw_file_sha256(_contained_regular(release_root, relative))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        frozen_rows.append({"path": relative, "actual": actual, "expected": expected, "valid": valid})
        if not valid:
            errors.append(f"Frozen file mismatch: {relative}")

    try:
        parent_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent = _read_json_strict(parent_path)
        parent_raw = raw_file_sha256(parent_path)
        parent_semantic = _freeze_semantic(parent)
    except Exception as exc:
        parent = {}
        parent_raw = parent_semantic = None
        errors.append(f"V4.1 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent_paths = (
        sorted(set(parent_files) - {README_PATH, UI_PATH})
        if isinstance(parent_files, dict) else []
    )
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 159
        and all(frozen.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    spec_relative = "quantum_research_lab/PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json"
    artifact_relative = "outputs/quantum_phase3/v42_coined_walk/SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json"
    engine_relative = "quantum_research_lab/phase3_v42_selector_engine.cpp"
    source_relative = "quantum_research_lab/phase3_v42_coined_walk_compiler.py"
    try:
        spec_path = _contained_regular(release_root, spec_relative)
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v42_spec(spec_path, root=release_root)
    except Exception as exc:
        spec_path = release_root / spec_relative
        spec_payload = spec_loaded = {}
        errors.append(f"V4.2 specification unavailable: {exc}")
    try:
        artifact_path = _contained_regular(release_root, artifact_relative)
        artifact = _read_json_strict(artifact_path)
    except Exception as exc:
        artifact_path = release_root / artifact_relative
        artifact = {}
        errors.append(f"V4.2 artifact unavailable: {exc}")
    try:
        engine_path = _contained_regular(release_root, engine_relative)
        source_path = _contained_regular(release_root, source_relative)
    except Exception as exc:
        engine_path = release_root / engine_relative
        source_path = release_root / source_relative
        errors.append(f"V4.2 source unavailable: {exc}")

    if deep:
        try:
            validation = run_v42_validation(root=release_root, deep_parent=True)
        except Exception as exc:
            validation = {"passed": False, "errors": [str(exc)], "failed_checks": ["exception"], "counts": {}}
            errors.append(f"Deep V4.2 scientific validation failed: {exc}")
    else:
        validation = _identity_validation(freeze)

    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    selector = artifact.get("selector_control") or {}
    support = (artifact.get("support_evidence") or {}).get("aggregate") or {}
    resources = (artifact.get("resource_evidence") or {}).get("aggregate") or {}
    identities = freeze.get("v42_identities") or {}
    deployment = freeze.get("deployment_contract") or {}
    targets = freeze.get("validation_targets") or {}
    checks = {
        "freeze_contract_version_exact": freeze.get("freeze_contract_version") == "QUANTUM LAB V4.2 FREEZE CONTRACT · V1",
        "freeze_self_hash_exact": freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze),
        "frozen_file_count_177": freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "frozen_path_fingerprint_exact": _fingerprint(frozen) == EXPECTED_V42_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in frozen_rows),
        "all_v42_release_paths_frozen": set(V42_PATHS).issubset(frozen),
        "v41_freeze_raw_identity": parent_raw == EXPECTED_V41_FREEZE_RAW,
        "v41_freeze_semantic_identity": parent_semantic == parent.get("freeze_contract_sha256") == EXPECTED_V41_FREEZE_SHA,
        "v41_freeze_inventory_identity": bool(isinstance(parent_files, dict) and len(parent_files) == 161 and _fingerprint(parent_files) == EXPECTED_V41_PATH_FINGERPRINT),
        "all_159_v41_immutable_paths_preserved": immutable_parent_exact,
        "v42_spec_raw_identity": spec_path.is_file() and raw_file_sha256(spec_path) == EXPECTED_V42_SPEC_RAW,
        "v42_spec_semantic_identity": _spec_semantic(spec_payload) == spec_loaded.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA,
        "v42_engine_raw_identity": engine_path.is_file() and raw_file_sha256(engine_path) == EXPECTED_V42_ENGINE_RAW,
        "v42_compiler_raw_identity": source_path.is_file() and raw_file_sha256(source_path) == EXPECTED_V42_SOURCE_RAW,
        "v42_artifact_raw_identity": artifact_path.is_file() and raw_file_sha256(artifact_path) == EXPECTED_V42_ARTIFACT_RAW,
        "v42_artifact_semantic_identity": _artifact_semantic(artifact) == artifact.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA,
        "artifact_source_spec_engine_crosslinks": bool(artifact.get("source_sha256") == EXPECTED_V42_SOURCE_RAW and artifact.get("spec_sha256") == EXPECTED_V42_SPEC_SHA and artifact.get("spec_raw_file_sha256") == EXPECTED_V42_SPEC_RAW and artifact.get("engine_source_raw_file_sha256") == EXPECTED_V42_ENGINE_RAW),
        "artifact_v41_parent_crosslinks": bool((artifact.get("parent") or {}).get("artifact_sha256") == "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e" and (artifact.get("parent") or {}).get("immutable_file_count") == 159 and (artifact.get("parent") or {}).get("immutable_files_exact") is True),
        "selector_dual_traversal_controls_exact": bool(selector.get("stable_replay_match") is True and (selector.get("forward") or {}).get("selector_cases") == 264_328 and (selector.get("forward") or {}).get("selector_failures") == 0 and (selector.get("forward") or {}).get("cleanup_failures") == 0),
        "joint_support_gate_exact": bool(support.get("all_pair_positions_preserved") is True and support.get("all_seeds_connected") is True and support.get("parent_selected_bridge_count") == 3 and support.get("joint_promise_vertices") == 34_649_241_600 and support.get("joint_support_edges") == 69_973_909_206),
        "resource_gate_exact": bool(resources.get("all_eight_seeds_pass") is True and resources.get("maximum_selected_model_cnot") == 1_135_430 and resources.get("minimum_budget_margin_cnot") == 1_364_570 and resources.get("maximum_logical_qubits_with_recycled_workspace") == 331 and resources.get("budget_cnot") == 2_500_000),
        "bounded_decisions_exact": bool(decisions.get("overall") == "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED" and decisions.get("resource_architecture_decision") == "PASSED_SELECTED_MODEL_CNOT_BUDGET" and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED" and decisions.get("next_falsifiable_gate") == "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION"),
        "provider_circuit_hardware_advantage_boundary_exact": bool(boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("circuit_materialization") == "NOT_RUN_NEXT_GATE" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "compiler_validation_ui_and_installer_provider_free": all(_provider_free_imports(_contained_regular(release_root, path)) for path in (source_relative, "quantum_research_lab/phase3_v42_validation.py", "quantum_research_lab/phase3_v42_ui.py", "install_quantum_lab_v42.py")),
        "scientific_validation_commitment_exact": identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA,
        "scientific_validation_passed_or_identity_verified": validation.get("passed") is True,
        "scientific_validation_has_35_checks": (validation.get("counts") or {}).get("checks_total") == 35,
        "readme_declares_bounded_v42_decision": "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED" in _contained_regular(release_root, README_PATH).read_text(encoding="utf-8"),
        "deployment_contract_is_transactional_idempotent": bool(deployment.get("overlay_file_count") == 18 and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH),
        "route_and_12_tab_contract_preserved": deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12,
        "validation_targets_exact": bool(targets.get("artifact_reconstruction_checks") == 16 and targets.get("scientific_validation_checks") == 35 and targets.get("streamlit_ui_checks") == 30 and targets.get("scientific_unit_tests") == 18 and targets.get("release_hardening_tests") == 15 and targets.get("frozen_file_count") == 177),
        "freeze_identity_block_exact": bool(identities.get("v42_spec_raw_file_sha256") == EXPECTED_V42_SPEC_RAW and identities.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA and identities.get("v42_engine_raw_file_sha256") == EXPECTED_V42_ENGINE_RAW and identities.get("v42_source_raw_file_sha256") == EXPECTED_V42_SOURCE_RAW and identities.get("v42_artifact_raw_file_sha256") == EXPECTED_V42_ARTIFACT_RAW and identities.get("v42_artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    merged_errors = list(dict.fromkeys(errors + list(validation.get("errors") or [])))
    return {
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_replay": bool(deep),
        "errors": merged_errors,
        "failed_checks": failed,
        "freeze_contract_sha256": freeze.get("freeze_contract_sha256"),
        "frozen_file_count": len(frozen_rows),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "verifier": "QUANTUM LAB V4.2 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("--identity-only", action="store_true")
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root, deep=not args.identity_only)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_VALIDATION_EVIDENCE_SHA",
    "EXPECTED_V41_FREEZE_RAW",
    "EXPECTED_V41_FREEZE_SHA",
    "EXPECTED_V42_ARTIFACT_RAW",
    "EXPECTED_V42_ARTIFACT_SHA",
    "EXPECTED_V42_ENGINE_RAW",
    "EXPECTED_V42_PATH_FINGERPRINT",
    "EXPECTED_V42_SOURCE_RAW",
    "EXPECTED_V42_SPEC_RAW",
    "EXPECTED_V42_SPEC_SHA",
    "FREEZE_PATH",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V42_PATHS",
    "verify_release_chain",
]
