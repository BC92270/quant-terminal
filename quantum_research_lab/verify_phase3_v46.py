"""Fail-closed release-chain verifier for Quantum Lab V4.6."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence

from .phase3_v46_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_NEXT_GATE,
    EXPECTED_OVERALL,
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
    EXPECTED_PRODUCTION_ADMISSION,
    EXPECTED_SOURCE_RAW_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_TRANSLATION_RAW_SHA256,
    EXPECTED_TRANSLATION_SHA256,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    canonical_json_sha256,
    read_json_strict,
    run_v46_validation,
)


FREEZE_PATH = "FREEZE_CONTRACT_V4_6.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_5.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
ARTIFACT_PATH = "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json"
ORACLE_PATH = "quantum_research_lab/PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
TRANSLATION_PATH = "quantum_research_lab/PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
SOURCE_PATH = "quantum_research_lab/phase3_v46_full_stream_routing.py"
CHECKER_PATH = "quantum_research_lab/phase3_v46_independent_checker.py"
VALIDATION_PATH = "quantum_research_lab/phase3_v46_validation.py"
V46_UI_PATH = "quantum_research_lab/phase3_v46_ui.py"

V46_TRANSITION_PATHS = (
    FREEZE_PATH,
    "DEPLOY_V4_6.md",
    "app_v46_offline_harness.py",
    "install_quantum_lab_v46.py",
    "build_quantum_lab_v46_release.py",
    ARTIFACT_PATH,
    SPEC_PATH,
    ORACLE_PATH,
    TRANSLATION_PATH,
    "quantum_research_lab/QUANTUM_LAB_V4_6_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v46_reference_builder.py",
    SOURCE_PATH,
    CHECKER_PATH,
    VALIDATION_PATH,
    V46_UI_PATH,
    "quantum_research_lab/test_phase3_v46.py",
    "quantum_research_lab/test_phase3_v46_release.py",
    "quantum_research_lab/verify_freeze_contract_v46.py",
    "quantum_research_lab/verify_phase3_v46.py",
    "quantum_research_lab/verify_phase3_v46_ui.py",
    README_PATH,
    UI_PATH,
)
V46_FROZEN_TRANSITION_PATHS = tuple(path for path in V46_TRANSITION_PATHS if path != FREEZE_PATH)
EXPECTED_FROZEN_FILE_COUNT = 249
EXPECTED_V46_PATH_FINGERPRINT = "6be1cbbc2d414298b4907878eac9e3924152679dfeb20e71079f409a0e22ccac"
EXPECTED_V46_OVERLAY_ORDER_SHA256 = "49cdd7ed81c6b71bb088cdbb259f7c4a4270cb6da525d68efb506d261e706294"
EXPECTED_V45_FREEZE_RAW_SHA256 = "1f20e7c3c82c9441132d530a9204b0db19ad0d31c43b867cc029394bda276cd7"
EXPECTED_V45_FREEZE_SHA256 = "05197d460b076275a3c7712aa895959d9d1916b09e1999750e1e36cc0c27a218"
EXPECTED_V45_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256 = "a09a6d4406ac19285d2b68add0c86fb3b62975cdfebd3ddca450adace623f6b9"
EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256 = "2f6887f063db1e4191fffc97b74de617df15cd3f456fcd322fd568b44a143c42"
EXPECTED_RELEASE_CHECK_COUNT = 38
EXPECTED_UI_CHECK_COUNT = 30
EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT = 18


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic(payload: Mapping[str, Any], field: str) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key != field})


def _fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


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


def _identity_validation(freeze: Mapping[str, Any]) -> dict[str, Any]:
    evidence = freeze.get("validation_evidence") or {}
    exact = bool(
        evidence.get("scientific_validation_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256
        and evidence.get("sealed_evidence_raw_file_sha256") == EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256
        and evidence.get("sealed_evidence_sha256") == EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256
        and evidence.get("clean_process_replay_byte_exact") is True
    )
    return {
        "counts": {"checks_passed": EXPECTED_SCIENTIFIC_CHECK_COUNT if exact else 0, "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT},
        "errors": [] if exact else ["Frozen V4.6 validation evidence identity mismatch."],
        "failed_checks": [] if exact else ["frozen_validation_evidence_identity"],
        "passed": exact,
        "validation_evidence_sha256": evidence.get("scientific_validation_sha256"),
        "validation_version": "IDENTITY_ONLY · SCIENTIFIC ENGINES NOT RUN IN THIS INVOCATION",
    }


def _clean_rebuild(root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="quantum-v46-release-replay.") as temporary:
        output = Path(temporary) / "replay.json"
        env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(root)}
        completed = subprocess.run(
            [sys.executable, "-m", "quantum_research_lab.phase3_v46_full_stream_routing", "--root", str(root), "--output", str(output)],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            return {"errors": [completed.stderr or completed.stdout], "performed": True, "valid": False}
        payload = read_json_strict(output)
        return {
            "artifact_raw_file_sha256": _sha256(output),
            "artifact_sha256": payload.get("artifact_sha256"),
            "errors": [],
            "performed": True,
            "valid": _sha256(output) == EXPECTED_ARTIFACT_RAW_SHA256 and payload.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256,
        }


def verify_release_chain(root: str | Path, *, deep: bool = True, rebuild: bool = False) -> dict[str, Any]:
    if rebuild and not deep:
        raise ValueError("Deterministic rebuild requires deep validation.")
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.6 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.6 frozen_files must be an object.")
    mismatches: list[str] = []
    for relative, expected in sorted(frozen.items()):
        try:
            if _sha256(_contained_regular(release_root, str(relative))) != expected:
                mismatches.append(str(relative))
        except Exception as exc:
            mismatches.append(str(relative))
            errors.append(f"Frozen path {relative}: {exc}")
    try:
        parent_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent = read_json_strict(parent_path)
        parent_raw, parent_semantic = _sha256(parent_path), _semantic(parent, "freeze_contract_sha256")
    except Exception as exc:
        parent, parent_raw, parent_semantic = {}, None, None
        errors.append(f"V4.5 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent = {
        str(path): str(digest) for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    } if isinstance(parent_files, Mapping) else {}
    identities = freeze.get("v46_identities") or {}
    decisions = freeze.get("scientific_decisions") or {}
    boundary = freeze.get("claim_boundary") or {}
    deployment = freeze.get("deployment_contract") or {}
    packaging = freeze.get("packaging_contract") or {}
    targets = freeze.get("validation_targets") or {}
    successor = freeze.get("successor_policy") or {}
    lineage = freeze.get("lineage") or {}
    artifact = {}
    try:
        artifact = read_json_strict(_contained_regular(release_root, ARTIFACT_PATH))
    except Exception as exc:
        errors.append(f"V4.6 artifact unavailable: {exc}")
    scientific = run_v46_validation(root=release_root) if deep else _identity_validation(freeze)
    rebuild_report = _clean_rebuild(release_root) if rebuild else {"performed": False, "valid": True, "errors": []}
    errors.extend(str(item) for item in scientific.get("errors") or [])
    errors.extend(str(item) for item in rebuild_report.get("errors") or [])
    expected_identity_paths = {
        "artifact_raw_file_sha256": (ARTIFACT_PATH, EXPECTED_ARTIFACT_RAW_SHA256),
        "artifact_sha256": (None, EXPECTED_ARTIFACT_SHA256),
        "checker_raw_file_sha256": (CHECKER_PATH, EXPECTED_CHECKER_RAW_SHA256),
        "path_oracle_raw_file_sha256": (ORACLE_PATH, EXPECTED_PATH_ORACLE_RAW_SHA256),
        "path_oracle_sha256": (None, EXPECTED_PATH_ORACLE_SHA256),
        "source_raw_file_sha256": (SOURCE_PATH, EXPECTED_SOURCE_RAW_SHA256),
        "spec_raw_file_sha256": (SPEC_PATH, EXPECTED_SPEC_RAW_SHA256),
        "spec_sha256": (None, EXPECTED_SPEC_SHA256),
        "translation_contract_raw_file_sha256": (TRANSLATION_PATH, EXPECTED_TRANSLATION_RAW_SHA256),
        "translation_contract_sha256": (None, EXPECTED_TRANSLATION_SHA256),
    }
    identities_exact = True
    for key, (relative, expected) in expected_identity_paths.items():
        if identities.get(key) != expected:
            identities_exact = False
        if relative and frozen.get(relative) != expected:
            identities_exact = False
    checks: dict[str, bool] = {
        "freeze_version_exact": freeze.get("freeze_contract_version") == "QUANTUM LAB V4.6 FREEZE CONTRACT · V1",
        "freeze_self_hash_exact": freeze.get("freeze_contract_sha256") == _semantic(freeze, "freeze_contract_sha256"),
        "frozen_file_count_249": freeze.get("frozen_file_count") == len(frozen) == EXPECTED_FROZEN_FILE_COUNT,
        "frozen_path_fingerprint_exact": _fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V46_PATH_FINGERPRINT,
        "all_frozen_files_exact": len(mismatches) == 0 and len(frozen) == EXPECTED_FROZEN_FILE_COUNT,
        "all_transition_payloads_frozen": set(V46_FROZEN_TRANSITION_PATHS).issubset(frozen),
        "parent_freeze_file_frozen_exact": frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V45_FREEZE_RAW_SHA256,
        "parent_freeze_raw_identity": parent_raw == EXPECTED_V45_FREEZE_RAW_SHA256,
        "parent_freeze_semantic_identity": parent_semantic == parent.get("freeze_contract_sha256") == EXPECTED_V45_FREEZE_SHA256,
        "parent_inventory_exact": isinstance(parent_files, Mapping) and len(parent_files) == parent.get("frozen_file_count") == 229 and _fingerprint(parent_files) == EXPECTED_V45_PATH_FINGERPRINT,
        "parent_227_immutable_paths_preserved": len(immutable_parent) == 227 and all(frozen.get(path) == digest for path, digest in immutable_parent.items()),
        "lineage_append_only_exact": lineage.get("append_only") is True and lineage.get("v45_immutable_file_count") == 227 and lineage.get("allowed_v45_superseded_files") == [README_PATH, UI_PATH],
        "release_paths_order_exact": freeze.get("release_paths") == list(V46_TRANSITION_PATHS),
        "overlay_order_hash_exact": deployment.get("ordered_transition_paths_sha256") == EXPECTED_V46_OVERLAY_ORDER_SHA256 and hashlib.sha256(json.dumps(deployment.get("ordered_transition_paths"), separators=(",", ":")).encode("utf-8")).hexdigest() == EXPECTED_V46_OVERLAY_ORDER_SHA256,
        "readme_penultimate_ui_last": deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH,
        "candidate_stage_required": deployment.get("candidate_stage_validation") == "REQUIRED",
        "rollback_and_preimage_contract": deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("source_snapshot_rehashed_before_commit") is True,
        "idempotent_exact_reapply": deployment.get("idempotent_exact_reapply") == "NO_OP",
        "successor_states_exact": successor.get("accepted_target_states") == ["V4.5", "V4.6"] and successor.get("mixed_or_third_state") == "REJECT",
        "successor_surface_hashes_frozen": successor.get("v46_successor_readme_sha256") == frozen.get(README_PATH) and successor.get("v46_successor_ui_sha256") == frozen.get(UI_PATH),
        "core_v46_identities_exact": identities_exact,
        "artifact_self_hash_exact": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and artifact.get("artifact_sha256") == _semantic(artifact, "artifact_sha256"),
        "scientific_validation_passes": scientific.get("passed") is True,
        "scientific_validation_57_checks": (scientific.get("counts") or {}).get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT and (scientific.get("counts") or {}).get("checks_passed") == EXPECTED_SCIENTIFIC_CHECK_COUNT,
        "scientific_validation_identity_exact": scientific.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256,
        "clean_replay_evidence_exact": (freeze.get("validation_evidence") or {}).get("clean_process_replay_byte_exact") is True and (freeze.get("validation_evidence") or {}).get("sealed_evidence_sha256") == EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
        "optional_rebuild_exact": rebuild_report.get("valid") is True,
        "decision_exact": decisions.get("overall") == EXPECTED_OVERALL,
        "production_admission_rejected": decisions.get("production_admission") == EXPECTED_PRODUCTION_ADMISSION,
        "next_gate_exact": decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "research_only_hardware_false": boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False,
        "provider_credentials_network_backend_zero": boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == boundary.get("provider_calls") == boundary.get("network_calls") == boundary.get("backend_run_calls") == 0,
        "simulator_qpu_jobs_zero": boundary.get("local_simulator_jobs_submitted") == boundary.get("qpu_jobs_submitted") == 0,
        "current_calibration_not_claimed": boundary.get("snapshot_is_current_hardware_evidence") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED",
        "performance_advantage_not_claimed": boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "packaging_entry_counts_exact": packaging.get("institutional_archive_entries") == 250 and packaging.get("overlay_archive_entries") == 22,
        "validation_targets_exact": targets.get("scientific_validation_checks") == 57 and targets.get("streamlit_ui_checks") == 30 and targets.get("scientific_unit_tests") == 18 and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT,
        "no_release_errors": not errors,
    }
    if len(checks) != EXPECTED_RELEASE_CHECK_COUNT:
        raise AssertionError(f"V4.6 release check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_validation": deep,
        "deterministic_rebuild_performed": rebuild,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "frozen_file_count": len(frozen),
        "root": str(release_root),
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.6 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--identity-only", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_release_chain(root, deep=not args.identity_only, rebuild=args.rebuild)
    except Exception as exc:
        report = {"check_count": EXPECTED_RELEASE_CHECK_COUNT, "checks": {}, "errors": [str(exc)], "failed_checks": ["unhandled_exception"], "root": str(root), "valid": False, "verifier": "QUANTUM LAB V4.6 RELEASE CHAIN · V1"}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_RELEASE_CHECK_COUNT",
    "EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT",
    "EXPECTED_UI_CHECK_COUNT",
    "EXPECTED_V46_PATH_FINGERPRINT",
    "FREEZE_PATH",
    "V46_FROZEN_TRANSITION_PATHS",
    "V46_TRANSITION_PATHS",
    "verify_release_chain",
]
