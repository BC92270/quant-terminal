"""Deterministic package builder for the Quantum Lab V4.5 release."""

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

from install_quantum_lab_v45 import (
    EXPECTED_V45_OVERLAY_ORDER_SHA256,
    PARENT_FREEZE_PATH,
    PARENT_FREEZE_RAW_SHA256,
    PARENT_FREEZE_SEMANTIC_SHA256,
    PARENT_FROZEN_FILE_COUNT,
    PARENT_FROZEN_PATHS_FINGERPRINT,
    PARENT_IMMUTABLE_FILE_COUNT,
    README_PATH,
    UI_PATH,
    V45_FREEZE_PATH,
    V45_TRANSITION_FILES,
    V45_TRANSITION_ORDER_SHA256,
)
from quantum_research_lab.phase3_v45_proof_carrying_width_reduction import (
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
)
from quantum_research_lab.phase3_v45_validation import (
    EXPECTED_ARTIFACT_RAW_SHA256,
    EXPECTED_ARTIFACT_SHA256,
    EXPECTED_CERTIFICATE_RAW_SHA256,
    EXPECTED_CERTIFICATE_SHA256,
    EXPECTED_CHECKER_RAW_SHA256,
    EXPECTED_CHECK_COUNT as EXPECTED_SCIENTIFIC_CHECK_COUNT,
    EXPECTED_SOURCE_RAW_SHA256,
    EXPECTED_VALIDATION_EVIDENCE_SHA256,
    run_v45_validation,
)


BUILDER_VERSION = "QUANTUM LAB V4.5 DETERMINISTIC RELEASE BUILDER · V1"
INSTITUTIONAL_ARCHIVE = "Quantum_Lab_V4_5_Institutional_Release.zip"
OVERLAY_ARCHIVE = "Quantum_Lab_V4_5_Deployment_Overlay.zip"
FIXED_ZIP_TIMESTAMP = (2026, 9, 14, 21, 30, 0)
EXPECTED_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"


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
    if V45_TRANSITION_ORDER_SHA256 != EXPECTED_V45_OVERLAY_ORDER_SHA256:
        raise AssertionError("V4.5 ordered overlay inventory identity mismatch.")
    parent_path = _safe_file(release_root, PARENT_FREEZE_PATH)
    parent = _read_json(parent_path)
    parent_files = parent.get("frozen_files") or {}
    parent_core = {key: value for key, value in parent.items() if key != "freeze_contract_sha256"}
    if not (
        _sha256(parent_path) == PARENT_FREEZE_RAW_SHA256
        and _canonical_json_sha256(parent_core) == parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and isinstance(parent_files, Mapping)
        and len(parent_files) == PARENT_FROZEN_FILE_COUNT == 211
        and _path_fingerprint(parent_files) == PARENT_FROZEN_PATHS_FINGERPRINT
    ):
        raise ValueError("Exact V4.4 parent freeze authentication failed.")
    immutable_parent = {
        str(path): str(digest)
        for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    }
    if len(immutable_parent) != PARENT_IMMUTABLE_FILE_COUNT:
        raise ValueError("V4.4 immutable successor inventory must contain 209 files.")

    frozen: dict[str, str] = dict(immutable_parent)
    frozen[PARENT_FREEZE_PATH] = PARENT_FREEZE_RAW_SHA256
    for relative in V45_TRANSITION_FILES:
        if relative == V45_FREEZE_PATH:
            continue
        frozen[relative] = _sha256(_safe_file(release_root, relative))
    frozen = dict(sorted(frozen.items()))
    fingerprint = _path_fingerprint(frozen)
    if len(frozen) != 229 or fingerprint != EXPECTED_PATH_FINGERPRINT:
        raise AssertionError(f"V4.5 freeze inventory drifted: count={len(frozen)} fingerprint={fingerprint}")

    scientific = run_v45_validation(root=release_root, rebuild=True)
    if (
        scientific.get("passed") is not True
        or (scientific.get("counts") or {}).get("checks_total") != EXPECTED_SCIENTIFIC_CHECK_COUNT
        or scientific.get("deterministic_rebuild_performed") is not True
        or scientific.get("replay_artifact_sha256") != EXPECTED_ARTIFACT_SHA256
    ):
        raise RuntimeError(f"V4.5 scientific validation failed before freeze: {scientific}")
    validation_sha = str(scientific.get("validation_evidence_sha256"))
    validation_source = release_root / "quantum_research_lab/phase3_v45_validation.py"
    artifact = _read_json(release_root / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json")
    certificate = _read_json(release_root / "quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json")
    aggregate = artifact.get("aggregate") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}

    core: dict[str, Any] = {
        "claim_boundary": dict(boundary),
        "created_utc": "2026-09-14T21:30:14Z",
        "deployment_contract": {
            "candidate_stage_validation": "REQUIRED",
            "commit_fault_positions_tested": 20,
            "idempotent_exact_reapply": "NO_OP",
            "integration_surface_last": UI_PATH,
            "lock_release_requires_owned_token": True,
            "ordered_transition_paths": list(V45_TRANSITION_FILES),
            "ordered_transition_paths_sha256": EXPECTED_V45_OVERLAY_ORDER_SHA256,
            "overlay_file_count": 20,
            "readme_surface_penultimate": README_PATH,
            "rollback_requires_preimage_hashes": True,
            "route": "?workspace=quantum-research",
            "source_snapshot_rehashed_before_commit": True,
            "streamlit_tab_count": 12,
        },
        "family": {"K": 10, "N": 40, "regime": "BANDS", "seeds": [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]},
        "freeze_contract_version": "QUANTUM LAB V4.5 FREEZE CONTRACT · V1",
        "frozen_file_count": len(frozen),
        "frozen_files": frozen,
        "frozen_paths_fingerprint_sha256": fingerprint,
        "lineage": {
            "append_only": True,
            "allowed_v44_superseded_files": [README_PATH, UI_PATH],
            "v44_freeze_raw_file_sha256": PARENT_FREEZE_RAW_SHA256,
            "v44_freeze_sha256": PARENT_FREEZE_SEMANTIC_SHA256,
            "v44_frozen_file_count": PARENT_FROZEN_FILE_COUNT,
            "v44_frozen_paths_fingerprint_sha256": PARENT_FROZEN_PATHS_FINGERPRINT,
            "v44_immutable_file_count": PARENT_IMMUTABLE_FILE_COUNT,
        },
        "packaging_contract": {
            "archive_duplicate_entries": "REJECT",
            "archive_integrity": "CRC_AND_EXACT_BYTE_EQUALITY",
            "archive_path_traversal": "REJECT",
            "deterministic_double_build": "REQUIRED_IDENTICAL_SHA256",
            "archive_symlink_entries": "REJECT",
            "institutional_archive_entries": 230,
            "overlay_archive_entries": 20,
        },
        "release_paths": list(V45_TRANSITION_FILES),
        "scientific_decisions": dict(decisions),
        "self_hash_contract": "SHA-256 over compact sorted UTF-8 JSON after removing freeze_contract_sha256",
        "successor_policy": {
            "accepted_target_states": ["V4.4", "V4.5"],
            "allowed_v44_superseded_files": [README_PATH, UI_PATH],
            "immutable_v44_frozen_file_count": 209,
            "mixed_or_third_state": "REJECT",
            "v45_successor_readme_sha256": frozen[README_PATH],
            "v45_successor_ui_sha256": frozen[UI_PATH],
        },
        "support_closure": {
            "all_frozen_paths_regular_and_non_symlink_at_seal": True,
            "frozen_path_count": 229,
            "parent_freeze_included": True,
            "successor_mutable_parent_surfaces_replaced": [README_PATH, UI_PATH],
        },
        "v45_identities": {
            "liveness_certificate_raw_file_sha256": EXPECTED_CERTIFICATE_RAW_SHA256,
            "liveness_certificate_sha256": EXPECTED_CERTIFICATE_SHA256,
            "v45_artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
            "v45_artifact_sha256": EXPECTED_ARTIFACT_SHA256,
            "v45_checker_raw_file_sha256": EXPECTED_CHECKER_RAW_SHA256,
            "v45_source_raw_file_sha256": EXPECTED_SOURCE_RAW_SHA256,
            "v45_spec_raw_file_sha256": EXPECTED_SPEC_RAW_SHA256,
            "v45_spec_sha256": EXPECTED_SPEC_SHA256,
            "v45_validation_source_raw_file_sha256": _sha256(validation_source),
            "validation_evidence_sha256": validation_sha,
        },
        "validation_evidence": {
            "all_eight_cnot_budget_pass": aggregate.get("all_eight_materialized_cnot_counts_at_or_below_2500000"),
            "all_eight_widths": aggregate.get("all_eight_widths"),
            "all_eight_widths_fit_156": aggregate.get("all_eight_widths_fit_156"),
            "certificate_sha256": certificate.get("certificate_sha256"),
            "clean_process_replay_count": 2,
            "cnot_budget_pass_count": aggregate.get("cnot_budget_pass_count"),
            "maximum_logical_qubits": aggregate.get("maximum_logical_qubits"),
            "maximum_materialized_cnot": aggregate.get("maximum_materialized_cnot"),
            "minimum_capacity_margin_qubits": aggregate.get("minimum_capacity_margin_qubits"),
            "ordered_stream_manifest_root_sha256": aggregate.get("ordered_stream_manifest_root_sha256"),
            "register_map_root_sha256": aggregate.get("register_map_root_sha256"),
            "replay_artifact_sha256": scientific.get("replay_artifact_sha256"),
            "replay_stable": scientific.get("replay_artifact_sha256") == artifact.get("artifact_sha256"),
            "semantic_trace_root_sha256": aggregate.get("semantic_trace_root_sha256"),
            "validation_evidence_sha256": validation_sha,
        },
        "validation_targets": {
            "freeze_contract_checks": 18,
            "frozen_file_count": 229,
            "historical_scientific_unit_tests": 161,
            "release_chain_checks": 36,
            "release_hardening_tests": 28,
            "scientific_unit_tests": 20,
            "scientific_validation_checks": EXPECTED_SCIENTIFIC_CHECK_COUNT,
            "streamlit_ui_checks": 28,
        },
    }
    if validation_sha != EXPECTED_VALIDATION_EVIDENCE_SHA256:
        raise RuntimeError(f"Unexpected validation evidence identity: {validation_sha}")
    if not (
        aggregate.get("all_eight_widths_fit_156") is True
        and aggregate.get("all_eight_materialized_cnot_counts_at_or_below_2500000") is True
        and aggregate.get("maximum_logical_qubits") == 145
        and aggregate.get("minimum_capacity_margin_qubits") == 11
        and certificate.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256
    ):
        raise RuntimeError("Sealed V4.5 width, resource or certificate identities changed before freeze.")
    contract = {**core, "freeze_contract_sha256": _canonical_json_sha256(core)}
    freeze_path = release_root / V45_FREEZE_PATH
    freeze_path.write_text(json.dumps(contract, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    return contract


def build_release(root: str | Path, output_dir: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    destination = Path(output_dir).resolve()
    freeze = _read_json(_safe_file(release_root, V45_FREEZE_PATH))
    frozen = freeze.get("frozen_files") or {}
    freeze_core = {
        key: value for key, value in freeze.items()
        if key != "freeze_contract_sha256"
    }
    if not (
        isinstance(frozen, Mapping)
        and freeze.get("frozen_file_count") == len(frozen) == 229
        and freeze.get("freeze_contract_sha256") == _canonical_json_sha256(freeze_core)
        and freeze.get("frozen_paths_fingerprint_sha256")
        == _path_fingerprint(frozen)
        == EXPECTED_PATH_FINGERPRINT
        and set(V45_TRANSITION_FILES) - {V45_FREEZE_PATH} <= set(frozen)
        and frozen.get(PARENT_FREEZE_PATH) == PARENT_FREEZE_RAW_SHA256
    ):
        raise ValueError("V4.5 freeze identity, inventory or lineage is invalid.")
    for relative, expected in frozen.items():
        if not isinstance(expected, str) or _sha256(_safe_file(release_root, str(relative))) != expected:
            raise ValueError(f"V4.5 frozen payload identity mismatch: {relative}")
    deployment = freeze.get("deployment_contract") or {}
    if not (
        deployment.get("ordered_transition_paths") == list(V45_TRANSITION_FILES)
        and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V45_OVERLAY_ORDER_SHA256
    ):
        raise ValueError("V4.5 frozen deployment order is invalid.")
    institutional_names = tuple(sorted(str(path) for path in frozen)) + (V45_FREEZE_PATH,)
    overlay_names = tuple(V45_TRANSITION_FILES)
    if len(institutional_names) != 230 or len(overlay_names) != 20:
        raise AssertionError("V4.5 archive inventory count drifted.")
    overlay_order_sha256 = hashlib.sha256(
        json.dumps(list(overlay_names), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if overlay_order_sha256 != EXPECTED_V45_OVERLAY_ORDER_SHA256:
        raise AssertionError("V4.5 overlay archive order identity drifted.")

    destination.mkdir(parents=True, exist_ok=True)
    reports: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="quantum-v45-double-build-") as temporary:
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
        "overlay_order_sha256": overlay_order_sha256,
        "root": str(release_root),
        "valid": True,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parents[2] / "outputs")
    parser.add_argument("--seal-freeze", action="store_true", help="Generate FREEZE_CONTRACT_V4_5.json before packaging.")
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
