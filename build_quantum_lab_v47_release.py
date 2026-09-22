"""Deterministic package and freeze builder for Quantum Lab V4.7."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

from install_quantum_lab_v47 import (
    EXPECTED_V47_FROZEN_FILE_COUNT,
    EXPECTED_V47_FROZEN_PATHS_FINGERPRINT,
    EXPECTED_V47_OVERLAY_ORDER_SHA256,
    FAULT_PHASES,
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    README_PATH,
    UI_PATH,
    V47_FREEZE_PATH,
    V47_TRANSITION_FILES,
    V47_TRANSITION_ORDER_SHA256,
    _canonical_json_sha256,
    _read_json_strict,
    _source_inventory,
    _transition_root,
    source_tree_raw_sha256,
)
from quantum_research_lab.verify_freeze_contract_v47 import (
    ARTIFACT_PATH,
    EXPECTED_FREEZE_CHECK_COUNT,
    RAW_IDENTITY_PATHS,
    SEMANTIC_IDENTITY_PATHS,
    VALIDATION_REPORT_PATH,
    verify_freeze_contract,
)


BUILDER_VERSION = "QUANTUM LAB V4.7 DETERMINISTIC RELEASE BUILDER · V1"
INSTITUTIONAL_ARCHIVE = "Quantum_Lab_V4_7_Institutional_Release.zip"
OVERLAY_ARCHIVE = "Quantum_Lab_V4_7_Deployment_Overlay.zip"
FIXED_ZIP_TIMESTAMP = (2026, 9, 21, 12, 0, 0)
MANIFEST_NAME = "QUANTUM_LAB_V4_7_RELEASE_MANIFEST.json"
REPORT_NAME = "QUANTUM_LAB_V4_7_RELEASE_REPORT.md"
CHECKSUM_NAME = "QUANTUM_LAB_V4_7_PACKAGE_SHA256.txt"
SOURCE_TREE_IDENTITY_NAME = "QUANTUM_LAB_V4_7_SOURCE_TREE_25_PATH_RAW_SHA256"
EXPECTED_RELEASE_HARDENING_TEST_COUNT = 29
EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT = 26


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic(payload: Mapping[str, Any], field: str) -> str:
    return _canonical_json_sha256({key: value for key, value in payload.items() if key != field})


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def _write_deterministic_zip(
    root: Path,
    names: Sequence[str],
    target: Path,
) -> None:
    if len(names) != len(set(names)):
        raise ValueError("Duplicate archive members rejected.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative in names:
            source = _safe_file(root, relative)
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.flag_bits = 0x800
            archive.writestr(
                info,
                source.read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )


def _archive_report(
    path: Path,
    expected_names: Sequence[str],
    root: Path,
) -> dict[str, Any]:
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
        "ordered_paths_sha256": hashlib.sha256(
            json.dumps(list(expected_names), separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _module(name: str) -> Any:
    return importlib.import_module(name)


def _validation_api() -> Any:
    module = _module("quantum_research_lab.phase3_v47_validation")
    for attribute in (
        "EXPECTED_CHECK_COUNT",
        "run_v47_validation",
    ):
        if not hasattr(module, attribute):
            raise RuntimeError(f"V4.7 validation API missing {attribute}")
    return module


def _ui_api() -> Any:
    module = _module("quantum_research_lab.verify_phase3_v47_ui")
    if not hasattr(module, "verify_streamlit_surface_v47"):
        raise RuntimeError("V4.7 UI verifier API missing verify_streamlit_surface_v47")
    return module


def _load_validation_report(
    path: Path,
    *,
    artifact_raw_sha256: str,
    artifact_sha256: str,
    scientific_validation: Mapping[str, Any],
) -> dict[str, Any]:
    report = _read_json_strict(path)
    field = "sealed_validation_evidence_sha256"
    scientific = report.get("scientific_validation") or {}
    replay = report.get("clean_process_replay") or {}
    boundary = report.get("claim_boundary") or {}
    current_counts = scientific_validation.get("counts") or {}
    expected_validation_sha256 = scientific_validation.get("validation_evidence_sha256")
    zero_operation_fields = (
        "provider_calls",
        "network_calls",
        "backend_run_calls",
        "local_simulator_jobs_submitted",
        "qpu_jobs_submitted",
    )
    if not (
        report.get(field) == _semantic(report, field)
        and report.get("validation_evidence_version")
        == "QUANTUM LAB V4.7 VALIDATION EVIDENCE · V1"
        and report.get("artifact_raw_file_sha256") == artifact_raw_sha256
        and report.get("artifact_sha256") == artifact_sha256
        and scientific.get("passed") is True
        and scientific.get("checks") == scientific_validation.get("checks")
        and scientific.get("checks_passed")
        == scientific.get("checks_total")
        == current_counts.get("checks_passed")
        == current_counts.get("checks_total")
        == 96
        and scientific.get("independent_checker_check_count") == 51
        and scientific.get("validation_evidence_sha256")
        == expected_validation_sha256
        and scientific.get("errors") in ([], None)
        and scientific.get("failed_checks") in ([], None)
        and replay.get("performed") is True
        and replay.get("byte_for_byte_equal_to_sealed_artifact") is True
        and replay.get("semantic_self_hash_valid") is True
        and replay.get("artifact_raw_file_sha256") == artifact_raw_sha256
        and replay.get("artifact_sha256") == artifact_sha256
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("snapshot_is_current_hardware_evidence") is False
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        and all(boundary.get(key) == 0 for key in zero_operation_fields)
    ):
        raise ValueError(
            "Exact V4.7 sealed validation/replay report is not bound to the "
            "current artifact and 96-check validation evidence."
        )
    return report


def _run_validation(root: Path) -> dict[str, Any]:
    api = _validation_api()
    validation = api.run_v47_validation(root=root)
    counts = validation.get("counts") or {}
    if not (
        validation.get("passed") is True
        and counts.get("checks_passed")
        == counts.get("checks_total")
        == api.EXPECTED_CHECK_COUNT
        == 96
    ):
        raise RuntimeError(f"V4.7 scientific validation failed before freeze: {validation}")
    return validation


def _ensure_validation_report(
    root: Path,
    path: Path,
    *,
    artifact_raw_sha256: str,
    artifact_sha256: str,
    scientific_validation: Mapping[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(
            "V4.7 validation report missing. Generate it explicitly with a fresh "
            "clean-process replay and exact raw/semantic artifact pins before "
            f"freezing the release: {path}"
        )
    return _load_validation_report(
        path,
        artifact_raw_sha256=artifact_raw_sha256,
        artifact_sha256=artifact_sha256,
        scientific_validation=scientific_validation,
    )


def _semantic_identity(root: Path, relative: str, field: str) -> str:
    payload = _read_json_strict(_safe_file(root, relative))
    excluded = {field}
    if field == "v47_spec_sha256":
        excluded.add("v47_spec_sha")
    actual = _canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in excluded}
    )
    if payload.get(field) != actual:
        raise ValueError(f"V4.7 semantic self-hash mismatch: {relative}")
    return actual


def _safe_claim_boundary(artifact: Mapping[str, Any]) -> dict[str, Any]:
    artifact_boundary = artifact.get("claim_boundary") or {}
    if not isinstance(artifact_boundary, Mapping):
        raise ValueError("V4.7 artifact claim_boundary must be an object")
    for key in (
        "provider_calls",
        "network_calls",
        "backend_run_calls",
        "local_simulator_jobs_submitted",
        "qpu_jobs_submitted",
    ):
        if artifact_boundary.get(key) not in {None, 0}:
            raise ValueError(f"V4.7 artifact violates zero-operation boundary: {key}")
    if artifact_boundary.get("hardware_executable") not in {None, False}:
        raise ValueError("V4.7 artifact cannot be hardware executable")
    for key in ("provider_sdk_imported", "provider_credentials_read"):
        if artifact_boundary.get(key) not in {None, False}:
            raise ValueError(f"V4.7 artifact violates offline boundary: {key}")
    return {
        "backend_name": "fake_marrakesh",
        "backend_properties_last_update": "2025-02-26T14:52:45-05:00",
        "backend_run_calls": 0,
        "backend_selection_kind": "PINNED_DATED_OFFLINE_FAKE_BACKEND_PROPERTIES",
        "credential_reads": 0,
        "current_calibration_claimed": False,
        "dated_properties_are_historical_offline_evidence_only": True,
        "hardware_executable": False,
        "hardware_fidelity_claimed": False,
        "local_simulator_jobs_submitted": 0,
        "network_calls": 0,
        "provider_calls": 0,
        "provider_credentials_read": False,
        "provider_sdk_imported": False,
        "qpu_jobs_submitted": 0,
        "quantum_advantage": "NOT_CLAIMED",
        "research_classification": "RESEARCH_ONLY",
        "snapshot_is_current_hardware_evidence": False,
    }


def _ui_validation(root: Path) -> tuple[dict[str, Any], int]:
    api = _ui_api()
    expected = getattr(
        api,
        "EXPECTED_UI_CHECK_COUNT",
        getattr(api, "EXPECTED_CHECK_COUNT", None),
    )
    if expected != 42:
        raise RuntimeError(
            f"V4.7 UI verifier check-count drifted: {expected} != 42"
        )
    report = api.verify_streamlit_surface_v47(
        root / "app_v47_offline_harness.py",
        timeout_seconds=600,
    )
    if report.get("valid") is not True or report.get("check_count") != expected:
        raise RuntimeError(f"V4.7 Streamlit validation failed before freeze: {report}")
    return report, expected


def seal_freeze_contract(
    root: str | Path,
    *,
    validation_report_path: str | Path | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    if V47_TRANSITION_ORDER_SHA256 != EXPECTED_V47_OVERLAY_ORDER_SHA256:
        raise AssertionError("V4.7 overlay order identity mismatch.")
    parent_path = _safe_file(release_root, PARENT_FREEZE_PATH)
    parent = _read_json_strict(parent_path)
    parent_files = parent.get("frozen_files") or {}
    if not (
        _sha256(parent_path) == PARENT_FREEZE_RAW_SHA256
        and parent.get("freeze_contract_sha256")
        == _semantic(parent, "freeze_contract_sha256")
        == PARENT_FREEZE_SEMANTIC_SHA256
        and isinstance(parent_files, Mapping)
        and len(parent_files) == parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and _path_fingerprint(parent_files) == PARENT_FROZEN_PATHS_FINGERPRINT
    ):
        raise ValueError("Exact V4.6 parent freeze authentication failed.")
    immutable_parent = {
        str(path): str(digest)
        for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    }
    if len(immutable_parent) != PARENT_IMMUTABLE_FILE_COUNT:
        raise ValueError("V4.6 immutable successor inventory must contain 247 files.")
    for relative, expected in immutable_parent.items():
        if _sha256(_safe_file(release_root, relative)) != expected:
            raise ValueError(f"V4.6 immutable parent mismatch: {relative}")

    report_path = (
        Path(validation_report_path).resolve()
        if validation_report_path is not None
        else release_root / VALIDATION_REPORT_PATH
    )
    packaged_report_path = (release_root / VALIDATION_REPORT_PATH).resolve()
    if report_path != packaged_report_path:
        raise ValueError(
            "The V4.7 validation report must be the exact packaged transition path: "
            f"{packaged_report_path}"
        )
    artifact = _read_json_strict(_safe_file(release_root, ARTIFACT_PATH))
    if artifact.get("artifact_sha256") != _semantic(artifact, "artifact_sha256"):
        raise ValueError("V4.7 artifact semantic identity mismatch.")
    artifact_raw_sha256 = _sha256(release_root / ARTIFACT_PATH)
    validation = _run_validation(release_root)
    report = _ensure_validation_report(
        release_root,
        report_path,
        artifact_raw_sha256=artifact_raw_sha256,
        artifact_sha256=str(artifact.get("artifact_sha256")),
        scientific_validation=validation,
    )
    _ui_report, ui_check_count = _ui_validation(release_root)

    boundary = _safe_claim_boundary(artifact)
    release_api = _module("quantum_research_lab.verify_phase3_v47")
    release_chain = release_api.verify_release_chain(
        release_root,
        deep=True,
        rebuild=False,
        expected_artifact_raw_sha256=artifact_raw_sha256,
        expected_artifact_sha256=artifact.get("artifact_sha256"),
    )
    if release_chain.get("passed") is not True:
        raise RuntimeError(
            f"V4.7 scientific release-chain validation failed before freeze: {release_chain}"
        )

    frozen: dict[str, str] = dict(immutable_parent)
    frozen[PARENT_FREEZE_PATH] = PARENT_FREEZE_RAW_SHA256
    for relative in V47_TRANSITION_FILES:
        if relative != V47_FREEZE_PATH:
            frozen[relative] = _sha256(_safe_file(release_root, relative))
    frozen = dict(sorted(frozen.items()))
    fingerprint = _path_fingerprint(frozen)
    if len(frozen) != EXPECTED_V47_FROZEN_FILE_COUNT or fingerprint != EXPECTED_V47_FROZEN_PATHS_FINGERPRINT:
        raise AssertionError(
            f"V4.7 freeze inventory drifted: count={len(frozen)} fingerprint={fingerprint}"
        )

    identities: dict[str, Any] = {
        key: frozen[relative]
        for key, relative in RAW_IDENTITY_PATHS.items()
    }
    identities.update(
        {
            key: _semantic_identity(release_root, relative, field)
            for key, (relative, field) in SEMANTIC_IDENTITY_PATHS.items()
        }
    )
    validation_api = _validation_api()
    scientific_checks = int(validation_api.EXPECTED_CHECK_COUNT)
    unit_tests = EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT
    release_checks = int(getattr(release_api, "EXPECTED_RELEASE_CHECK_COUNT", 0) or 0)
    if release_chain.get("counts", {}).get("checks_total") != release_checks:
        raise RuntimeError("V4.7 release-chain check-count drift detected.")
    decisions = artifact.get("decisions") or {}
    aggregate = artifact.get("aggregate") or artifact.get("paired_aggregate") or {}
    validation_semantic = (
        validation.get("validation_evidence_sha256")
        or validation.get("evidence_sha256")
        or _canonical_json_sha256(validation)
    )
    core: dict[str, Any] = {
        "claim_boundary": boundary,
        "created_utc": "2026-09-21T01:00:00Z",
        "deployment_contract": {
            "candidate_stage_validation": "REQUIRED",
            "candidate_static_offline_boundary": "REQUIRED_BEFORE_EXECUTION",
            "candidate_subprocess_environment": "SCRUBBED_ALLOWLIST_ONLY",
            "commit_fault_phases_tested": sorted(FAULT_PHASES),
            "commit_fault_positions_tested": len(V47_TRANSITION_FILES),
            "exact_v47_freeze_raw_bytes_required": True,
            "idempotent_exact_reapply": "NO_OP",
            "integration_surface_last": UI_PATH,
            "lock_release_requires_owned_token": True,
            "ordered_transition_paths": list(V47_TRANSITION_FILES),
            "ordered_transition_paths_sha256": EXPECTED_V47_OVERLAY_ORDER_SHA256,
            "overlay_file_count": len(V47_TRANSITION_FILES),
            "predecessor_reauthenticated_under_lock_before_commit": True,
            "readme_surface_penultimate": README_PATH,
            "rollback_requires_preimage_hashes": True,
            "route": "?workspace=quantum-research",
            "source_snapshot_rehashed_before_commit": True,
            "source_tree_raw_external_pin_required": True,
            "source_tree_raw_pin_scope": (
                "ORDERED_25_TRANSITION_PATHS_INCLUDING_RAW_FREEZE_BYTES"
            ),
            "streamlit_outer_tab_count": 12,
            "v47_evidence_tab_count": 6,
        },
        "family": {
            "K": 10,
            "N": 40,
            "regime": "BANDS",
            "seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807],
        },
        "freeze_contract_version": "QUANTUM LAB V4.7 FREEZE CONTRACT · V1",
        "frozen_file_count": len(frozen),
        "frozen_files": frozen,
        "frozen_paths_fingerprint_sha256": fingerprint,
        "lineage": {
            "append_only": True,
            "allowed_v46_superseded_files": [README_PATH, UI_PATH],
            "v46_freeze_raw_file_sha256": PARENT_FREEZE_RAW_SHA256,
            "v46_freeze_sha256": PARENT_FREEZE_SEMANTIC_SHA256,
            "v46_frozen_file_count": PARENT_FROZEN_FILE_COUNT,
            "v46_frozen_paths_fingerprint_sha256": PARENT_FROZEN_PATHS_FINGERPRINT,
            "v46_immutable_file_count": PARENT_IMMUTABLE_FILE_COUNT,
        },
        "packaging_contract": {
            "archive_duplicate_entries": "REJECT",
            "archive_integrity": "CRC_AND_EXACT_BYTE_EQUALITY",
            "archive_path_traversal": "REJECT",
            "archive_symlink_entries": "REJECT",
            "deterministic_double_build": "REQUIRED_IDENTICAL_SHA256",
            "institutional_archive_entries": EXPECTED_V47_FROZEN_FILE_COUNT + 1,
            "overlay_archive_entries": len(V47_TRANSITION_FILES),
            "source_tree_raw_sha256_emitted_out_of_band": True,
        },
        "release_paths": list(V47_TRANSITION_FILES),
        "scientific_decisions": dict(decisions) if isinstance(decisions, Mapping) else {},
        "self_hash_contract": "SHA-256 over compact sorted UTF-8 JSON after removing freeze_contract_sha256",
        "successor_policy": {
            "accepted_target_states": ["V4.6", "V4.7"],
            "allowed_v46_superseded_files": [README_PATH, UI_PATH],
            "immutable_v46_frozen_file_count": PARENT_IMMUTABLE_FILE_COUNT,
            "mixed_or_third_state": "REJECT",
            "v47_successor_readme_sha256": frozen[README_PATH],
            "v47_successor_ui_sha256": frozen[UI_PATH],
        },
        "v47_identities": identities,
        "validation_evidence": {
            "aggregate": dict(aggregate) if isinstance(aggregate, Mapping) else {},
            "clean_process_replay_byte_exact": True,
            "scientific_validation_sha256": validation_semantic,
            "sealed_report_raw_file_sha256": _sha256(report_path),
            "sealed_report_sha256": report.get("sealed_validation_evidence_sha256"),
        },
        "validation_targets": {
            "freeze_contract_checks": EXPECTED_FREEZE_CHECK_COUNT,
            "frozen_file_count": EXPECTED_V47_FROZEN_FILE_COUNT,
            "independent_scientific_checks": 51,
            "release_chain_checks": release_checks,
            "release_hardening_tests": EXPECTED_RELEASE_HARDENING_TEST_COUNT,
            "scientific_unit_tests": unit_tests,
            "scientific_validation_checks": scientific_checks,
            "streamlit_ui_checks": ui_check_count,
        },
    }
    contract = {**core, "freeze_contract_sha256": _canonical_json_sha256(core)}
    target = release_root / V47_FREEZE_PATH
    target.write_text(
        json.dumps(
            contract,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return contract


def _run_tests(root: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    env["PYTHONNOUSERSITE"] = "1"
    commands = {
        "scientific_unit_tests": (
            EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT,
            [
                sys.executable,
                "-m",
                "unittest",
                "quantum_research_lab.test_phase3_v47",
                "-v",
            ],
        ),
        "release_hardening_tests": (
            EXPECTED_RELEASE_HARDENING_TEST_COUNT,
            [
                sys.executable,
                "-m",
                "unittest",
                "quantum_research_lab.test_phase3_v47_release",
                "-v",
            ],
        ),
    }
    reports: dict[str, Any] = {}
    for name, (expected_test_count, command) in commands.items():
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        combined_output = completed.stdout + "\n" + completed.stderr
        count_match = re.search(r"\bRan (\d+) tests? in\b", combined_output)
        observed_test_count = int(count_match.group(1)) if count_match else None
        skipped = "skipped=" in combined_output
        reports[name] = {
            "expected_test_count": expected_test_count,
            "returncode": completed.returncode,
            "skipped": skipped,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "tests_run": observed_test_count,
        }
        if (
            completed.returncode != 0
            or observed_test_count != expected_test_count
            or skipped
        ):
            raise RuntimeError(
                f"{name} failed, skipped or count-drifted "
                f"({observed_test_count} != {expected_test_count}):\n"
                f"{completed.stdout}\n{completed.stderr}"
            )
    return reports


def _reauthenticate_release_source(
    root: Path,
    *,
    expected_freeze_sha256: str,
    expected_source_tree_raw_sha256: str,
    expected_transition_root_sha256: str,
    phase: str,
) -> dict[str, Any]:
    """Reauthenticate every frozen byte and the ordered overlay at a boundary."""

    freeze, rows, source_errors = _source_inventory(root)
    observed_transition_root = _transition_root(root) if not source_errors else None
    observed_source_tree_raw = (
        source_tree_raw_sha256(root) if not source_errors else None
    )
    if (
        source_errors
        or freeze.get("freeze_contract_sha256") != expected_freeze_sha256
        or not rows
        or not all(row.get("valid") for row in rows)
        or observed_transition_root != expected_transition_root_sha256
        or observed_source_tree_raw != expected_source_tree_raw_sha256
    ):
        raise RuntimeError(
            f"V4.7 source authentication failed at {phase}: "
            f"errors={source_errors} transition_root={observed_transition_root} "
            f"source_tree_raw={observed_source_tree_raw}"
        )
    freeze_report = verify_freeze_contract(root)
    if (
        freeze_report.get("valid") is not True
        or freeze_report.get("check_count") != EXPECTED_FREEZE_CHECK_COUNT
    ):
        raise RuntimeError(
            f"V4.7 freeze verification failed at {phase}: {freeze_report}"
        )
    return freeze_report


def build_release(
    root: str | Path,
    *,
    output_dir: str | Path,
    validation_report_path: str | Path | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    report_path = (
        Path(validation_report_path).resolve()
        if validation_report_path is not None
        else release_root / VALIDATION_REPORT_PATH
    )
    contract = seal_freeze_contract(
        release_root,
        validation_report_path=report_path,
    )
    expected_transition_root = _transition_root(release_root)
    expected_source_tree_raw = source_tree_raw_sha256(release_root)
    freeze_report = _reauthenticate_release_source(
        release_root,
        expected_freeze_sha256=str(contract.get("freeze_contract_sha256")),
        expected_source_tree_raw_sha256=expected_source_tree_raw,
        expected_transition_root_sha256=expected_transition_root,
        phase="POST_FREEZE_PRE_TEST",
    )
    test_reports = _run_tests(release_root)
    freeze_report = _reauthenticate_release_source(
        release_root,
        expected_freeze_sha256=str(contract.get("freeze_contract_sha256")),
        expected_source_tree_raw_sha256=expected_source_tree_raw,
        expected_transition_root_sha256=expected_transition_root,
        phase="POST_TEST_PRE_PACKAGE",
    )
    institutional_names = [V47_FREEZE_PATH] + sorted(contract["frozen_files"])
    overlay_names = list(V47_TRANSITION_FILES)
    if (
        len(institutional_names) != EXPECTED_V47_FROZEN_FILE_COUNT + 1
        or len(overlay_names) != len(V47_TRANSITION_FILES)
    ):
        raise AssertionError("V4.7 package entry count drifted.")
    with tempfile.TemporaryDirectory(prefix="quantum-v47-package.") as temporary:
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
    freeze_report = _reauthenticate_release_source(
        release_root,
        expected_freeze_sha256=str(contract.get("freeze_contract_sha256")),
        expected_source_tree_raw_sha256=expected_source_tree_raw,
        expected_transition_root_sha256=expected_transition_root,
        phase="POST_ZIP",
    )
    institutional = _archive_report(
        institutional_target,
        institutional_names,
        release_root,
    )
    overlay = _archive_report(overlay_target, overlay_names, release_root)
    freeze_report = _reauthenticate_release_source(
        release_root,
        expected_freeze_sha256=str(contract.get("freeze_contract_sha256")),
        expected_source_tree_raw_sha256=expected_source_tree_raw,
        expected_transition_root_sha256=expected_transition_root,
        phase="POST_ARCHIVE_BYTE_AUDIT",
    )
    manifest_core = {
        "archives": {"institutional": institutional, "overlay": overlay},
        "builder": BUILDER_VERSION,
        "claim_boundary": contract["claim_boundary"],
        "freeze_contract_raw_file_sha256": _sha256(release_root / V47_FREEZE_PATH),
        "freeze_contract_sha256": contract["freeze_contract_sha256"],
        "freeze_contract_checks": freeze_report["check_count"],
        "independent_scientific_checks": contract["validation_targets"]["independent_scientific_checks"],
        "release_chain_checks": contract["validation_targets"]["release_chain_checks"],
        "source_tree_raw_sha256": expected_source_tree_raw,
        "source_transition_root_sha256": expected_transition_root,
        "scientific_validation_checks": contract["validation_targets"]["scientific_validation_checks"],
        "streamlit_ui_checks": contract["validation_targets"]["streamlit_ui_checks"],
        "test_results": {
            name: {
                "expected_test_count": result.get("expected_test_count"),
                "returncode": result.get("returncode"),
                "skipped": result.get("skipped"),
                "tests_run": result.get("tests_run"),
            }
            for name, result in test_reports.items()
        },
        "validation_report_raw_file_sha256": _sha256(report_path),
        "validation_report_sha256": contract["v47_identities"]["validation_report_sha256"],
        "v47_artifact_raw_file_sha256": contract["v47_identities"]["artifact_raw_file_sha256"],
        "v47_artifact_sha256": contract["v47_identities"]["artifact_sha256"],
    }
    manifest = {
        **manifest_core,
        "release_manifest_sha256": _canonical_json_sha256(manifest_core),
    }
    manifest_path = destination / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    checksum_path = destination / CHECKSUM_NAME
    checksum_path.write_text(
        f"{institutional['sha256']}  {INSTITUTIONAL_ARCHIVE}\n"
        f"{overlay['sha256']}  {OVERLAY_ARCHIVE}\n"
        f"{_sha256(manifest_path)}  {MANIFEST_NAME}\n"
        f"# {SOURCE_TREE_IDENTITY_NAME} {expected_source_tree_raw}\n",
        encoding="utf-8",
    )
    release_report_path = destination / REPORT_NAME
    release_report_path.write_text(
        "# Quantum Lab V4.7 release report\n\n"
        f"- Scientific validation: {contract['validation_targets']['scientific_validation_checks']}/"
        f"{contract['validation_targets']['scientific_validation_checks']}\n"
        "- Independent standard-library checks: 51/51\n"
        f"- Scientific unit tests: {EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT}/"
        f"{EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT}\n"
        f"- Release-hardening tests: {EXPECTED_RELEASE_HARDENING_TEST_COUNT}/"
        f"{EXPECTED_RELEASE_HARDENING_TEST_COUNT}\n"
        f"- Release-chain checks: {contract['validation_targets']['release_chain_checks']}/"
        f"{contract['validation_targets']['release_chain_checks']}\n"
        f"- Streamlit verification: {contract['validation_targets']['streamlit_ui_checks']}/"
        f"{contract['validation_targets']['streamlit_ui_checks']}\n"
        f"- Freeze checks: {freeze_report['check_count']}/{EXPECTED_FREEZE_CHECK_COUNT}\n"
        f"- Frozen paths: {contract['frozen_file_count']}\n"
        f"- Ordered 25-path raw source-tree SHA-256: `{expected_source_tree_raw}`\n"
        f"- Institutional archive SHA-256: `{institutional['sha256']}`\n"
        f"- Deployment overlay SHA-256: `{overlay['sha256']}`\n\n"
        "The release is RESEARCH_ONLY. Dated FakeMarrakesh properties are historical "
        "offline evidence only, not current calibration, hardware execution, fidelity, "
        "utility or quantum-advantage evidence. hardware_executable=false; credential, "
        "provider, network, backend-run, simulator-job and QPU-job counts are zero.\n",
        encoding="utf-8",
    )
    return {
        "archives": {
            "institutional": {**institutional, "path": str(institutional_target)},
            "overlay": {**overlay, "path": str(overlay_target)},
        },
        "builder": BUILDER_VERSION,
        "checksum_path": str(checksum_path),
        "freeze_contract_raw_file_sha256": _sha256(release_root / V47_FREEZE_PATH),
        "freeze_contract_sha256": contract["freeze_contract_sha256"],
        "manifest_path": str(manifest_path),
        "release_report_path": str(release_report_path),
        "source_tree_raw_sha256": expected_source_tree_raw,
        "tests": {
            name: {
                "expected_test_count": result.get("expected_test_count"),
                "returncode": result.get("returncode"),
                "skipped": result.get("skipped"),
                "tests_run": result.get("tests_run"),
            }
            for name, result in test_reports.items()
        },
        "valid": True,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--validation-report", type=Path)
    args = parser.parse_args(argv)
    output_dir = args.output_dir or args.root.resolve().parents[1] / "outputs"
    try:
        report = build_release(
            args.root,
            output_dir=output_dir,
            validation_report_path=args.validation_report,
        )
    except Exception as exc:
        report = {"builder": BUILDER_VERSION, "errors": [str(exc)], "valid": False}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "build_release",
    "seal_freeze_contract",
    "_archive_report",
    "_write_deterministic_zip",
]
