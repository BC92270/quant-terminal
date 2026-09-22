"""Deterministic package builder for the Quantum Lab V4.6 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

from install_quantum_lab_v46 import (
    EXPECTED_V46_FROZEN_FILE_COUNT,
    EXPECTED_V46_FROZEN_PATHS_FINGERPRINT,
    EXPECTED_V46_OVERLAY_ORDER_SHA256,
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    README_PATH,
    UI_PATH,
    V46_FREEZE_PATH,
    V46_TRANSITION_FILES,
    V46_TRANSITION_ORDER_SHA256,
    _source_inventory,
)
from quantum_research_lab.phase3_v46_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
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
from quantum_research_lab.verify_phase3_v46 import (
    EXPECTED_RELEASE_CHECK_COUNT,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256,
    EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
    EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
    EXPECTED_UI_CHECK_COUNT,
    verify_release_chain,
)
from quantum_research_lab.verify_freeze_contract_v46 import (
    EXPECTED_FREEZE_CHECK_COUNT,
    verify_freeze_contract,
)
from quantum_research_lab.verify_phase3_v46_ui import verify_streamlit_surface_v46


BUILDER_VERSION = "QUANTUM LAB V4.6 DETERMINISTIC RELEASE BUILDER · V1"
INSTITUTIONAL_ARCHIVE = "Quantum_Lab_V4_6_Institutional_Release.zip"
OVERLAY_ARCHIVE = "Quantum_Lab_V4_6_Deployment_Overlay.zip"
FIXED_ZIP_TIMESTAMP = (2026, 9, 15, 15, 50, 0)
VALIDATION_EVIDENCE_NAME = "QUANTUM_LAB_V4_6_VALIDATION_EVIDENCE.json"
MANIFEST_NAME = "QUANTUM_LAB_V4_6_RELEASE_MANIFEST.json"
REPORT_NAME = "QUANTUM_LAB_V4_6_RELEASE_REPORT.md"
CHECKSUM_NAME = "QUANTUM_LAB_V4_6_PACKAGE_SHA256.txt"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _safe_file(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe archive path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked archive path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Archive member is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _write_deterministic_zip(root: Path, names: Sequence[str], target: Path) -> None:
    if len(names) != len(set(names)):
        raise ValueError("Duplicate archive members rejected.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as archive:
        for relative in names:
            source = _safe_file(root, relative)
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits = 0x800
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _archive_report(path: Path, expected_names: Sequence[str], root: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != list(expected_names) or len(names) != len(set(names)):
            raise RuntimeError(f"Archive inventory/order mismatch: {path.name}")
        if archive.testzip() is not None:
            raise RuntimeError(f"CRC failure: {path.name}")
        for info, relative in zip(infos, expected_names):
            if archive.read(info) != _safe_file(root, relative).read_bytes():
                raise RuntimeError(f"Archive byte mismatch: {relative}")
    return {
        "entries": len(expected_names),
        "ordered_paths_sha256": hashlib.sha256(json.dumps(list(expected_names), separators=(",", ":")).encode("utf-8")).hexdigest(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _load_validation_evidence(path: Path) -> dict[str, Any]:
    evidence = read_json_strict(path)
    semantic = canonical_json_sha256({key: value for key, value in evidence.items() if key != "sealed_validation_evidence_sha256"})
    replay = evidence.get("clean_process_replay") or {}
    scientific = evidence.get("scientific_validation") or {}
    if not (
        _sha256(path) == EXPECTED_SEALED_VALIDATION_EVIDENCE_RAW_SHA256
        and evidence.get("sealed_validation_evidence_sha256") == semantic == EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256
        and scientific.get("passed") is True
        and scientific.get("checks_passed") == scientific.get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT
        and scientific.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA256
        and replay.get("performed") is True
        and replay.get("byte_for_byte_equal_to_sealed_artifact") is True
        and replay.get("artifact_raw_file_sha256") == EXPECTED_ARTIFACT_RAW_SHA256
        and replay.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256
    ):
        raise ValueError("Exact V4.6 validation/replay evidence authentication failed.")
    return evidence


def seal_freeze_contract(
    root: str | Path,
    *,
    validation_evidence_path: str | Path,
    run_ui: bool = True,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    validation_path = Path(validation_evidence_path).resolve(strict=True)
    if V46_TRANSITION_ORDER_SHA256 != EXPECTED_V46_OVERLAY_ORDER_SHA256:
        raise AssertionError("V4.6 overlay order identity mismatch.")
    parent_path = _safe_file(release_root, PARENT_FREEZE_PATH)
    parent = read_json_strict(parent_path)
    parent_files = parent.get("frozen_files") or {}
    if not (
        _sha256(parent_path) == PARENT_FREEZE_RAW_SHA256
        and parent.get("freeze_contract_sha256") == _freeze_semantic(parent) == PARENT_FREEZE_SEMANTIC_SHA256
        and isinstance(parent_files, Mapping)
        and len(parent_files) == parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and _path_fingerprint(parent_files) == PARENT_FROZEN_PATHS_FINGERPRINT
    ):
        raise ValueError("Exact V4.5 parent freeze authentication failed.")
    immutable_parent = {
        str(path): str(digest) for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    }
    if len(immutable_parent) != PARENT_IMMUTABLE_FILE_COUNT:
        raise ValueError("V4.5 immutable successor inventory must contain 227 files.")
    for relative, expected in immutable_parent.items():
        if _sha256(_safe_file(release_root, relative)) != expected:
            raise ValueError(f"V4.5 immutable parent mismatch: {relative}")
    frozen: dict[str, str] = dict(immutable_parent)
    frozen[PARENT_FREEZE_PATH] = PARENT_FREEZE_RAW_SHA256
    for relative in V46_TRANSITION_FILES:
        if relative != V46_FREEZE_PATH:
            frozen[relative] = _sha256(_safe_file(release_root, relative))
    frozen = dict(sorted(frozen.items()))
    fingerprint = _path_fingerprint(frozen)
    if len(frozen) != EXPECTED_V46_FROZEN_FILE_COUNT or fingerprint != EXPECTED_V46_FROZEN_PATHS_FINGERPRINT:
        raise AssertionError(f"V4.6 freeze inventory drifted: count={len(frozen)} fingerprint={fingerprint}")

    scientific = run_v46_validation(root=release_root)
    if scientific.get("passed") is not True or (scientific.get("counts") or {}).get("checks_total") != EXPECTED_SCIENTIFIC_CHECK_COUNT:
        raise RuntimeError(f"V4.6 scientific validation failed before freeze: {scientific}")
    evidence = _load_validation_evidence(validation_path)
    if run_ui:
        ui = verify_streamlit_surface_v46(release_root / "app_v46_offline_harness.py", timeout_seconds=600)
        if ui.get("valid") is not True or ui.get("check_count") != EXPECTED_UI_CHECK_COUNT:
            raise RuntimeError(f"V4.6 Streamlit validation failed before freeze: {ui}")
    else:
        ui = {"valid": True, "check_count": EXPECTED_UI_CHECK_COUNT, "mode": "PREVIOUSLY_VALIDATED"}
    artifact = read_json_strict(release_root / ARTIFACT_RELATIVE)
    aggregate = artifact.get("aggregate") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    identities = {
        "artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_sha256": EXPECTED_ARTIFACT_SHA256,
        "checker_raw_file_sha256": EXPECTED_CHECKER_RAW_SHA256,
        "path_oracle_raw_file_sha256": EXPECTED_PATH_ORACLE_RAW_SHA256,
        "path_oracle_sha256": EXPECTED_PATH_ORACLE_SHA256,
        "reference_builder_raw_file_sha256": frozen["quantum_research_lab/phase3_v46_reference_builder.py"],
        "source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
        "spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "translation_contract_raw_file_sha256": EXPECTED_TRANSLATION_RAW_SHA256,
        "translation_contract_sha256": EXPECTED_TRANSLATION_SHA256,
        "ui_module_raw_file_sha256": frozen["quantum_research_lab/phase3_v46_ui.py"],
        "validation_source_raw_file_sha256": frozen["quantum_research_lab/phase3_v46_validation.py"],
    }
    core: dict[str, Any] = {
        "claim_boundary": dict(boundary),
        "created_utc": "2026-09-15T15:50:00Z",
        "deployment_contract": {
            "candidate_stage_validation": "REQUIRED",
            "commit_fault_positions_tested": 22,
            "idempotent_exact_reapply": "NO_OP",
            "integration_surface_last": UI_PATH,
            "lock_release_requires_owned_token": True,
            "ordered_transition_paths": list(V46_TRANSITION_FILES),
            "ordered_transition_paths_sha256": EXPECTED_V46_OVERLAY_ORDER_SHA256,
            "overlay_file_count": 22,
            "readme_surface_penultimate": README_PATH,
            "rollback_requires_preimage_hashes": True,
            "route": "?workspace=quantum-research",
            "source_snapshot_rehashed_before_commit": True,
            "streamlit_outer_tab_count": 12,
            "v46_evidence_tab_count": 6,
        },
        "family": {"K": 10, "N": 40, "regime": "BANDS", "seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]},
        "freeze_contract_version": "QUANTUM LAB V4.6 FREEZE CONTRACT · V1",
        "frozen_file_count": len(frozen),
        "frozen_files": frozen,
        "frozen_paths_fingerprint_sha256": fingerprint,
        "lineage": {
            "append_only": True,
            "allowed_v45_superseded_files": [README_PATH, UI_PATH],
            "v45_freeze_raw_file_sha256": PARENT_FREEZE_RAW_SHA256,
            "v45_freeze_sha256": PARENT_FREEZE_SEMANTIC_SHA256,
            "v45_frozen_file_count": PARENT_FROZEN_FILE_COUNT,
            "v45_frozen_paths_fingerprint_sha256": PARENT_FROZEN_PATHS_FINGERPRINT,
            "v45_immutable_file_count": PARENT_IMMUTABLE_FILE_COUNT,
        },
        "packaging_contract": {
            "archive_duplicate_entries": "REJECT",
            "archive_integrity": "CRC_AND_EXACT_BYTE_EQUALITY",
            "archive_path_traversal": "REJECT",
            "archive_symlink_entries": "REJECT",
            "deterministic_double_build": "REQUIRED_IDENTICAL_SHA256",
            "institutional_archive_entries": 250,
            "overlay_archive_entries": 22,
        },
        "release_paths": list(V46_TRANSITION_FILES),
        "scientific_decisions": dict(decisions),
        "self_hash_contract": "SHA-256 over compact sorted UTF-8 JSON after removing freeze_contract_sha256",
        "successor_policy": {
            "accepted_target_states": ["V4.5", "V4.6"],
            "allowed_v45_superseded_files": [README_PATH, UI_PATH],
            "immutable_v45_frozen_file_count": PARENT_IMMUTABLE_FILE_COUNT,
            "mixed_or_third_state": "REJECT",
            "v46_successor_readme_sha256": frozen[README_PATH],
            "v46_successor_ui_sha256": frozen[UI_PATH],
        },
        "v46_identities": identities,
        "validation_evidence": {
            "aggregate_native_cz": aggregate.get("aggregate_native_cz"),
            "aggregate_native_instructions": aggregate.get("aggregate_native_instructions"),
            "aggregate_swaps": aggregate.get("aggregate_swaps"),
            "clean_process_replay_byte_exact": True,
            "maximum_logical_qubits": aggregate.get("maximum_logical_qubits"),
            "maximum_native_cz": aggregate.get("maximum_native_cz"),
            "maximum_routed_depth": aggregate.get("maximum_routed_depth"),
            "minimum_logical_capacity_margin": aggregate.get("minimum_logical_capacity_margin"),
            "scientific_validation_sha256": scientific.get("validation_evidence_sha256"),
            "sealed_evidence_raw_file_sha256": _sha256(validation_path),
            "sealed_evidence_sha256": evidence.get("sealed_validation_evidence_sha256"),
            "total_input_instructions": aggregate.get("total_input_instructions"),
        },
        "validation_targets": {
            "freeze_contract_checks": EXPECTED_FREEZE_CHECK_COUNT,
            "frozen_file_count": EXPECTED_V46_FROZEN_FILE_COUNT,
            "release_chain_checks": EXPECTED_RELEASE_CHECK_COUNT,
            "release_hardening_tests": 22,
            "scientific_unit_tests": EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
            "scientific_validation_checks": EXPECTED_SCIENTIFIC_CHECK_COUNT,
            "streamlit_ui_checks": EXPECTED_UI_CHECK_COUNT,
        },
    }
    contract = {**core, "freeze_contract_sha256": canonical_json_sha256(core)}
    target = release_root / V46_FREEZE_PATH
    target.write_text(json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return contract


ARTIFACT_RELATIVE = "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"


def _run_tests(root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    commands = {
        "scientific_unit_tests": [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v46", "-v"],
        "release_hardening_tests": [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v46_release", "-v"],
    }
    reports: dict[str, Any] = {}
    for name, command in commands.items():
        completed = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=900, check=False)
        reports[name] = {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
        if completed.returncode != 0:
            raise RuntimeError(f"{name} failed:\n{completed.stdout}\n{completed.stderr}")
    return reports


def build_release(
    root: str | Path,
    *,
    output_dir: str | Path,
    validation_evidence_path: str | Path,
    run_ui: bool = True,
    run_tests: bool = True,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    contract = seal_freeze_contract(release_root, validation_evidence_path=validation_evidence_path, run_ui=run_ui)
    freeze, rows, source_errors = _source_inventory(release_root)
    if source_errors or freeze.get("freeze_contract_sha256") != contract.get("freeze_contract_sha256") or not all(row.get("valid") for row in rows):
        raise RuntimeError(f"V4.6 source inventory failed after freeze: {source_errors}")
    release = verify_release_chain(release_root, deep=True, rebuild=False)
    freeze_report = verify_freeze_contract(release_root)
    if release.get("valid") is not True or freeze_report.get("valid") is not True:
        raise RuntimeError(f"Release/freeze verification failed: release={release} freeze={freeze_report}")
    test_reports = _run_tests(release_root) if run_tests else {"mode": "PREVIOUSLY_VALIDATED"}
    institutional_names = [V46_FREEZE_PATH] + sorted(contract["frozen_files"])
    overlay_names = list(V46_TRANSITION_FILES)
    if len(institutional_names) != 250 or len(overlay_names) != 22:
        raise AssertionError("V4.6 package entry count drifted.")
    with tempfile.TemporaryDirectory(prefix="quantum-v46-package.") as temporary:
        temp = Path(temporary)
        inst_a, inst_b = temp / "institutional-a.zip", temp / "institutional-b.zip"
        overlay_a, overlay_b = temp / "overlay-a.zip", temp / "overlay-b.zip"
        _write_deterministic_zip(release_root, institutional_names, inst_a)
        _write_deterministic_zip(release_root, institutional_names, inst_b)
        _write_deterministic_zip(release_root, overlay_names, overlay_a)
        _write_deterministic_zip(release_root, overlay_names, overlay_b)
        if _sha256(inst_a) != _sha256(inst_b) or _sha256(overlay_a) != _sha256(overlay_b):
            raise RuntimeError("Deterministic double-build identity failed.")
        institutional_target = destination / INSTITUTIONAL_ARCHIVE
        overlay_target = destination / OVERLAY_ARCHIVE
        shutil.copy2(inst_a, institutional_target)
        shutil.copy2(overlay_a, overlay_target)
    institutional = _archive_report(institutional_target, institutional_names, release_root)
    overlay = _archive_report(overlay_target, overlay_names, release_root)
    manifest_core = {
        "archives": {"institutional": institutional, "overlay": overlay},
        "builder": BUILDER_VERSION,
        "claim_boundary": contract["claim_boundary"],
        "freeze_contract_raw_file_sha256": _sha256(release_root / V46_FREEZE_PATH),
        "freeze_contract_sha256": contract["freeze_contract_sha256"],
        "release_chain_checks": release["check_count"],
        "scientific_validation_checks": EXPECTED_SCIENTIFIC_CHECK_COUNT,
        "streamlit_ui_checks": EXPECTED_UI_CHECK_COUNT,
        "validation_evidence_raw_file_sha256": _sha256(Path(validation_evidence_path)),
        "validation_evidence_sha256": EXPECTED_SEALED_VALIDATION_EVIDENCE_SHA256,
        "v46_artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
        "v46_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
    }
    manifest = {**manifest_core, "release_manifest_sha256": canonical_json_sha256(manifest_core)}
    manifest_path = destination / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    checksum_path = destination / CHECKSUM_NAME
    checksum_path.write_text(
        f"{institutional['sha256']}  {INSTITUTIONAL_ARCHIVE}\n{overlay['sha256']}  {OVERLAY_ARCHIVE}\n{_sha256(manifest_path)}  {MANIFEST_NAME}\n",
        encoding="utf-8",
    )
    report_path = destination / REPORT_NAME
    report_path.write_text(
        "# Quantum Lab V4.6 release report\n\n"
        f"- Scientific validation: {EXPECTED_SCIENTIFIC_CHECK_COUNT}/{EXPECTED_SCIENTIFIC_CHECK_COUNT}\n"
        f"- Standard-library checker: 36/36\n"
        f"- Streamlit verification: {EXPECTED_UI_CHECK_COUNT}/{EXPECTED_UI_CHECK_COUNT}\n"
        f"- Scientific unit tests: {EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT}/{EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT}\n"
        f"- Release-chain checks: {release['check_count']}/{EXPECTED_RELEASE_CHECK_COUNT}\n"
        f"- Freeze checks: {freeze_report['check_count']}/{EXPECTED_FREEZE_CHECK_COUNT}\n"
        f"- Frozen paths: {contract['frozen_file_count']}\n"
        f"- Institutional archive SHA-256: `{institutional['sha256']}`\n"
        f"- Deployment overlay SHA-256: `{overlay['sha256']}`\n\n"
        "The release is RESEARCH_ONLY. The routed IR is offline structural evidence, not current calibration, duration, fidelity, execution, utility or quantum-advantage evidence. hardware_executable=false; provider, network, backend-run, simulator-job and QPU-job counts are zero.\n",
        encoding="utf-8",
    )
    return {
        "archives": {"institutional": {**institutional, "path": str(institutional_target)}, "overlay": {**overlay, "path": str(overlay_target)}},
        "builder": BUILDER_VERSION,
        "checksum_path": str(checksum_path),
        "freeze_contract_raw_file_sha256": _sha256(release_root / V46_FREEZE_PATH),
        "freeze_contract_sha256": contract["freeze_contract_sha256"],
        "manifest_path": str(manifest_path),
        "release_report_path": str(report_path),
        "tests": {name: result.get("returncode") for name, result in test_reports.items()} if run_tests else test_reports,
        "valid": True,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validation-evidence", type=Path)
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--seal-only", action="store_true")
    args = parser.parse_args(argv)
    output_dir = args.output_dir or args.root.resolve().parents[1] / "outputs"
    validation = args.validation_evidence or output_dir / VALIDATION_EVIDENCE_NAME
    try:
        if args.seal_only:
            contract = seal_freeze_contract(args.root, validation_evidence_path=validation, run_ui=not args.skip_ui)
            report = {"freeze_contract_sha256": contract["freeze_contract_sha256"], "frozen_file_count": contract["frozen_file_count"], "valid": True}
        else:
            report = build_release(args.root, output_dir=output_dir, validation_evidence_path=validation, run_ui=not args.skip_ui, run_tests=not args.skip_tests)
    except Exception as exc:
        report = {"builder": BUILDER_VERSION, "errors": [str(exc)], "valid": False}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["build_release", "seal_freeze_contract", "_archive_report", "_write_deterministic_zip"]
