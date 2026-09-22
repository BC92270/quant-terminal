"""Deterministic package builder for the Quantum Lab V4.4 release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Mapping, Sequence
import zipfile

from install_quantum_lab_v44 import (
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    README_PATH,
    UI_PATH,
    V44_FREEZE_PATH,
    V44_TRANSITION_FILES,
)
from quantum_research_lab.phase3_v44_named_backend_routing import (
    EXPECTED_SNAPSHOT_RAW_SHA256,
    EXPECTED_SNAPSHOT_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_TOOLCHAIN_RAW_SHA256,
    EXPECTED_TOOLCHAIN_SHA256,
)
from quantum_research_lab.phase3_v44_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CANARY_BUNDLE_SHA256,
    EXPECTED_CANARY_ROOT_SHA256,
    EXPECTED_CAPACITY_PRECHECK_SHA256,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SOURCE_RAW_SHA256,
    run_v44_validation,
)


BUILDER_VERSION = "QUANTUM LAB V4.4 DETERMINISTIC RELEASE BUILDER · V1"
INSTITUTIONAL_ARCHIVE = "Quantum_Lab_V4_4_Institutional_Release.zip"
OVERLAY_ARCHIVE = "Quantum_Lab_V4_4_Deployment_Overlay.zip"
FIXED_ZIP_TIMESTAMP = (2026, 9, 14, 13, 30, 0)
EXPECTED_PATH_FINGERPRINT = "eb4fda2c2b862fa279a7f0d60f0a2694e50f9c63bf89f60de9d0af52638c0516"


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"Non-finite JSON number: {token}")),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


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


def _write_deterministic_zip(root: Path, names: Sequence[str], target: Path) -> None:
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
            archive.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _archive_report(path: Path, expected_names: Sequence[str], root: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != list(expected_names):
            raise RuntimeError(f"Archive order mismatch: {path.name}")
        if len(names) != len(set(names)):
            raise RuntimeError(f"Duplicate archive member: {path.name}")
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


def seal_freeze_contract(root: str | Path) -> dict[str, Any]:
    """Materialize the final append-only freeze from already finalized files."""

    release_root = Path(root).resolve(strict=True)
    parent_path = _safe_file(release_root, PARENT_FREEZE_PATH)
    parent = _read_json(parent_path)
    parent_files = parent.get("frozen_files") or {}
    parent_core = {key: value for key, value in parent.items() if key != "freeze_contract_sha256"}
    if not (
        _sha256(parent_path) == PARENT_FREEZE_RAW_SHA256
        and _canonical_json_sha256(parent_core) == parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and isinstance(parent_files, Mapping)
        and len(parent_files) == PARENT_FROZEN_FILE_COUNT == 193
        and _path_fingerprint(parent_files) == PARENT_FROZEN_PATHS_FINGERPRINT
    ):
        raise ValueError("Exact V4.3 parent freeze authentication failed.")
    immutable_parent = {
        str(path): str(digest)
        for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    }
    if len(immutable_parent) != PARENT_IMMUTABLE_FILE_COUNT:
        raise ValueError("V4.3 immutable successor inventory must contain 191 files.")

    frozen: dict[str, str] = dict(immutable_parent)
    frozen[PARENT_FREEZE_PATH] = PARENT_FREEZE_RAW_SHA256
    for relative in V44_TRANSITION_FILES:
        if relative == V44_FREEZE_PATH:
            continue
        frozen[relative] = _sha256(_safe_file(release_root, relative))
    frozen = dict(sorted(frozen.items()))
    fingerprint = _path_fingerprint(frozen)
    if len(frozen) != 211 or fingerprint != EXPECTED_PATH_FINGERPRINT:
        raise AssertionError(f"V4.4 freeze inventory drifted: count={len(frozen)} fingerprint={fingerprint}")

    scientific = run_v44_validation(root=release_root, replay_toolchain=False)
    if scientific.get("passed") is not True or (scientific.get("counts") or {}).get("checks_total") != EXPECTED_SCIENTIFIC_CHECK_COUNT:
        raise RuntimeError(f"V4.4 scientific validation failed before freeze: {scientific}")
    validation_sha = str(scientific.get("validation_evidence_sha256"))
    validation_source = release_root / "quantum_research_lab/phase3_v44_validation.py"
    artifact = _read_json(release_root / "outputs/quantum_phase3/v44_named_backend/SEALED_V4_4_NAMED_BACKEND_ZERO_JOB_ARTIFACT.json")
    capacity = artifact.get("capacity_precheck") or {}
    canary = (artifact.get("canary_evidence") or {}).get("canonical_canary_bundle") or {}
    boundary = artifact.get("claim_boundary") or {}

    core: dict[str, Any] = {
        "claim_boundary": {
            "backend_selection_kind": "PINNED_OFFLINE_FAKE_BACKEND_SNAPSHOT",
            "calibration_aware_fidelity": "NOT_TESTED",
            "credential_reads": 0,
            "full_workload_routing": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "full_workload_transpilation": "NOT_RUN_CAPACITY_PRECHECK_REJECTED",
            "hardware_executable": False,
            "network_calls": 0,
            "optimization_performance": "NOT_TESTED",
            "provider_calls": 0,
            "provider_credentials_read": False,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "created_utc": "2026-09-14T16:15:00Z",
        "deployment_contract": {
            "candidate_stage_validation": "REQUIRED",
            "commit_fault_positions_tested": 20,
            "idempotent_exact_reapply": "NO_OP",
            "integration_surface_last": UI_PATH,
            "lock_release_requires_owned_token": True,
            "ordered_transition_paths": list(V44_TRANSITION_FILES),
            "overlay_file_count": 20,
            "readme_surface_penultimate": README_PATH,
            "rollback_requires_preimage_hashes": True,
            "route": "?workspace=quantum-research",
            "source_snapshot_rehashed_before_commit": True,
            "streamlit_tab_count": 12,
        },
        "family": {"K": 10, "N": 40, "regime": "BANDS", "seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]},
        "freeze_contract_version": "QUANTUM LAB V4.4 FREEZE CONTRACT · V1",
        "frozen_file_count": len(frozen),
        "frozen_files": frozen,
        "frozen_paths_fingerprint_sha256": fingerprint,
        "lineage": {
            "append_only": True,
            "allowed_v43_superseded_files": [README_PATH, UI_PATH],
            "v43_freeze_raw_file_sha256": PARENT_FREEZE_RAW_SHA256,
            "v43_freeze_sha256": PARENT_FREEZE_SEMANTIC_SHA256,
            "v43_frozen_file_count": PARENT_FROZEN_FILE_COUNT,
            "v43_frozen_paths_fingerprint_sha256": PARENT_FROZEN_PATHS_FINGERPRINT,
            "v43_immutable_file_count": PARENT_IMMUTABLE_FILE_COUNT,
        },
        "packaging_contract": {
            "archive_duplicate_entries": "REJECT",
            "archive_integrity": "CRC_AND_EXACT_BYTE_EQUALITY",
            "archive_path_traversal": "REJECT",
            "deterministic_double_build": "REQUIRED_IDENTICAL_SHA256",
            "institutional_archive_entries": 212,
            "overlay_archive_entries": 20,
        },
        "release_paths": list(V44_TRANSITION_FILES),
        "scientific_decisions": {
            "canary_toolchain": "VALIDATED_ON_FIVE_ACCEPTED_CANARIES_AND_ONE_157Q_NEGATIVE_CONTROL",
            "full_workload": "REJECTED_AT_CAPACITY_PRECHECK_BEFORE_TRANSPILATION_AND_ROUTING",
            "next_falsifiable_gate": "PROOF_CARRYING_WIDTH_REDUCTION_TO_156_QUBITS_OR_LOWER_WITH_EXACT_PROMISE_PARITY",
            "overall": "V44_FAKE_MARRAKESH_CAPACITY_REJECTED_CANARY_PIPELINE_VALIDATED_ZERO_JOB",
            "production_admission": "REJECTED_RESEARCH_ARCHITECTURE_REQUIRES_PROOF_CARRYING_WIDTH_REDUCTION",
        },
        "self_hash_contract": "SHA-256 over compact sorted UTF-8 JSON after removing freeze_contract_sha256",
        "successor_policy": {
            "accepted_target_states": ["V4.3", "V4.4"],
            "allowed_v43_superseded_files": [README_PATH, UI_PATH],
            "immutable_v43_frozen_file_count": 191,
            "mixed_or_third_state": "REJECT",
            "v44_successor_readme_sha256": frozen[README_PATH],
            "v44_successor_ui_sha256": frozen[UI_PATH],
        },
        "support_closure": {
            "all_frozen_paths_regular_and_non_symlink_at_seal": True,
            "frozen_path_count": 211,
            "parent_freeze_included": True,
            "successor_mutable_parent_surfaces_replaced": [README_PATH, UI_PATH],
        },
        "v44_identities": {
            "snapshot_raw_file_sha256": EXPECTED_SNAPSHOT_RAW_SHA256,
            "snapshot_sha256": EXPECTED_SNAPSHOT_SHA256,
            "toolchain_manifest_raw_file_sha256": EXPECTED_TOOLCHAIN_RAW_SHA256,
            "toolchain_manifest_sha256": EXPECTED_TOOLCHAIN_SHA256,
            "v44_artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
            "v44_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
            "v44_source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
            "v44_spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
            "v44_spec_sha256": EXPECTED_SPEC_SHA256,
            "v44_validation_source_raw_file_sha256": _sha256(validation_source),
            "validation_evidence_sha256": validation_sha,
        },
        "validation_evidence": {
            "accepted_canary_count": canary.get("accepted_canary_count"),
            "canary_bundle_sha256": canary.get("canary_bundle_sha256"),
            "canary_result_root_sha256": canary.get("canonical_result_root_sha256"),
            "capacity_157_control": (canary.get("mandatory_negative_canary") or {}).get("status"),
            "capacity_precheck_sha256": capacity.get("capacity_precheck_sha256"),
            "clean_process_replay_count": (artifact.get("canary_evidence") or {}).get("clean_process_replay_count"),
            "clean_process_replay_stable": (artifact.get("canary_evidence") or {}).get("replay_stable"),
            "maximum_capacity_deficit_qubits": capacity.get("maximum_capacity_deficit_qubits"),
            "maximum_logical_qubits": capacity.get("maximum_logical_qubits"),
            "persistent_register_floor_qubits": (capacity.get("persistent_register_floor") or {}).get("persistent_register_floor_qubits"),
            "rejected_seed_count": capacity.get("rejected_seed_count"),
            "target_qubits": capacity.get("backend_capacity_qubits"),
            "validation_evidence_sha256": validation_sha,
        },
        "validation_targets": {
            "freeze_contract_checks": 18,
            "frozen_file_count": 211,
            "historical_scientific_unit_tests": 143,
            "release_chain_checks": 34,
            "release_hardening_tests": 28,
            "scientific_unit_tests": 18,
            "scientific_validation_checks": EXPECTED_SCIENTIFIC_CHECK_COUNT,
            "streamlit_ui_checks": 26,
        },
    }
    if validation_sha != "ec43dfa6ba209c4376a79b5e57cabbeb7f1f86e1bcc1b6e4797752c4427a66dd":
        raise RuntimeError(f"Unexpected validation evidence identity: {validation_sha}")
    if canary.get("canary_bundle_sha256") != EXPECTED_CANARY_BUNDLE_SHA256 or canary.get("canonical_result_root_sha256") != EXPECTED_CANARY_ROOT_SHA256 or capacity.get("capacity_precheck_sha256") != EXPECTED_CAPACITY_PRECHECK_SHA256:
        raise RuntimeError("Sealed V4.4 scientific identities changed before freeze.")
    contract = {**core, "freeze_contract_sha256": _canonical_json_sha256(core)}
    freeze_path = release_root / V44_FREEZE_PATH
    freeze_path.write_text(json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return contract


def build_release(root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    destination = Path(output_dir).resolve()
    freeze = _read_json(_safe_file(release_root, V44_FREEZE_PATH))
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, Mapping) or len(frozen) != 211:
        raise ValueError("V4.4 freeze must contain exactly 211 frozen files.")
    institutional_names = tuple(sorted(str(path) for path in frozen)) + (V44_FREEZE_PATH,)
    overlay_names = tuple(V44_TRANSITION_FILES)
    if len(institutional_names) != 212 or len(overlay_names) != 20:
        raise AssertionError("V4.4 archive inventory count drifted.")

    destination.mkdir(parents=True, exist_ok=True)
    reports: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="quantum-v44-double-build-") as temporary:
        temp = Path(temporary)
        for archive_name, names in (
            (INSTITUTIONAL_ARCHIVE, institutional_names),
            (OVERLAY_ARCHIVE, overlay_names),
        ):
            first = temp / f"first-{archive_name}"
            second = temp / f"second-{archive_name}"
            _write_deterministic_zip(release_root, names, first)
            _write_deterministic_zip(release_root, names, second)
            first_sha = _sha256(first)
            second_sha = _sha256(second)
            if first_sha != second_sha or first.read_bytes() != second.read_bytes():
                raise RuntimeError(f"Deterministic double build mismatch: {archive_name}")
            final = destination / archive_name
            temporary_final = destination / f".{archive_name}.{os.getpid()}.tmp"
            temporary_final.write_bytes(first.read_bytes())
            os.replace(temporary_final, final)
            reports[archive_name] = {
                **_archive_report(final, names, release_root),
                "double_build_first_sha256": first_sha,
                "double_build_second_sha256": second_sha,
                "double_build_identical": True,
            }
    return {
        "archives": reports,
        "builder": BUILDER_VERSION,
        "deterministic_double_build": True,
        "freeze_contract_sha256": freeze.get("freeze_contract_sha256"),
        "institutional_order": list(institutional_names),
        "overlay_order": list(overlay_names),
        "root": str(release_root),
        "valid": True,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "outputs")
    parser.add_argument("--seal-freeze", action="store_true", help="Generate FREEZE_CONTRACT_V4_4.json before packaging.")
    args = parser.parse_args(argv)
    try:
        if args.seal_freeze:
            contract = seal_freeze_contract(args.root)
            report = {
                "builder": BUILDER_VERSION,
                "freeze_contract_sha256": contract.get("freeze_contract_sha256"),
                "frozen_file_count": contract.get("frozen_file_count"),
                "frozen_paths_fingerprint_sha256": contract.get("frozen_paths_fingerprint_sha256"),
                "valid": True,
            }
        else:
            report = build_release(args.root, args.output_dir)
    except Exception as exc:
        report = {"builder": BUILDER_VERSION, "errors": [str(exc)], "valid": False}
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BUILDER_VERSION",
    "INSTITUTIONAL_ARCHIVE",
    "OVERLAY_ARCHIVE",
    "build_release",
    "seal_freeze_contract",
]
