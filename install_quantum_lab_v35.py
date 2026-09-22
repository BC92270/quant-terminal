"""Fail-closed transactional installer for the Quantum Lab V3.5 overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4


INSTALLER_VERSION = "QUANTUM LAB V3.5 TRANSACTIONAL INSTALLER · V1"
V34_FREEZE_RAW_SHA256 = (
    "a2309c3ae551e74970c1c405ac106045f6db85bb2ba5cb87107a88fbfc7ccb12"
)
V34_FREEZE_SEMANTIC_SHA256 = (
    "ef0c6406b6946e347885699c19422a5a7e224833d19936ec9f5e1298f993c0d6"
)
V34_ARTIFACT_RAW_SHA256 = (
    "4e15aba6c83dcec0ff3e22652df03c624f635956d10b769514cfbd78cdaed7fd"
)
V34_ARTIFACT_PATH = (
    "outputs/quantum_phase3/optimized_native/"
    "SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json"
)
V34_SUPERSEDED_FILES = (
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
)
OVERLAY_FILES = (
    "FREEZE_CONTRACT_V3_5.json",
    "DEPLOY_V3_5.md",
    "install_quantum_lab_v35.py",
    "outputs/quantum_phase3/backend_admission/"
    "SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
    "quantum_research_lab/PHASE_III_BACKEND_ADMISSION_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_5_ARCHITECTURE.md",
    "quantum_research_lab/README.md",
    "quantum_research_lab/phase3_backend_admission.py",
    "quantum_research_lab/phase3_v35_ui.py",
    "quantum_research_lab/phase3_v35_validation.py",
    "quantum_research_lab/test_phase3_v35.py",
    "quantum_research_lab/ui.py",
    "quantum_research_lab/verify_freeze_contract_v35.py",
    "quantum_research_lab/verify_phase3_v35.py",
    "quantum_research_lab/verify_phase3_v35_ui.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze_semantic_sha256(payload: dict[str, Any]) -> str:
    core = {
        key: value for key, value in payload.items() if key != "freeze_contract_sha256"
    }
    return _canonical_json_sha256(core)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _contained(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    target.relative_to(root.resolve())
    return target


def preflight(source_root: Path, target_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    errors: list[str] = []
    if target_root in {Path("/").resolve(), Path.home().resolve()}:
        errors.append("Refusing a broad target directory.")
    if not (target_root / "quantum_research_lab").is_dir():
        errors.append("Target does not contain quantum_research_lab/.")

    try:
        freeze = _read_json(source_root / "FREEZE_CONTRACT_V3_5.json")
    except Exception as exc:
        freeze = {}
        errors.append(f"Cannot load V3.5 freeze: {exc}")
    frozen_files = freeze.get("frozen_files") or {}
    source_rows: list[dict[str, Any]] = []
    for relative in OVERLAY_FILES:
        try:
            source = _contained(source_root, relative)
            if relative == "FREEZE_CONTRACT_V3_5.json":
                expected = freeze.get("freeze_contract_sha256")
                actual = _freeze_semantic_sha256(freeze) if freeze else None
                integrity = "CANONICAL_JSON_SELF_HASH"
            else:
                expected = frozen_files.get(relative)
                actual = _sha256(source) if source.is_file() else None
                integrity = "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except (OSError, ValueError) as exc:
            source = source_root / relative
            expected = frozen_files.get(relative)
            actual = None
            integrity = "RAW_FILE_SHA256"
            valid = False
            errors.append(f"Source overlay read error {relative}: {exc}")
        source_rows.append(
            {
                "path": relative,
                "actual_sha256": actual,
                "expected_sha256": expected,
                "integrity": integrity,
                "valid": valid,
            }
        )
        if not valid:
            errors.append(f"Source overlay mismatch: {relative}")

    try:
        target_v34_freeze_path = _contained(target_root, "FREEZE_CONTRACT_V3_4.json")
        target_v34_freeze = _read_json(target_v34_freeze_path)
        target_v34_freeze_raw = _sha256(target_v34_freeze_path)
        target_v34_freeze_semantic = _freeze_semantic_sha256(target_v34_freeze)
    except Exception as exc:
        target_v34_freeze = {}
        target_v34_freeze_raw = None
        target_v34_freeze_semantic = None
        errors.append(f"Cannot authenticate target V3.4 freeze: {exc}")
    freeze_valid = bool(
        target_v34_freeze_raw == V34_FREEZE_RAW_SHA256
        and target_v34_freeze_semantic == V34_FREEZE_SEMANTIC_SHA256
        and target_v34_freeze.get("freeze_contract_sha256")
        == V34_FREEZE_SEMANTIC_SHA256
    )
    if not freeze_valid:
        errors.append("Target V3.4 freeze identity mismatch.")

    target_parent_rows: list[dict[str, Any]] = []
    for relative, expected_v34 in sorted(
        (target_v34_freeze.get("frozen_files") or {}).items()
    ):
        target = _contained(target_root, relative)
        actual = _sha256(target) if target.is_file() else None
        accepted = [expected_v34]
        if relative in V34_SUPERSEDED_FILES:
            successor = frozen_files.get(relative)
            if successor:
                accepted.append(successor)
        valid = bool(actual in accepted)
        target_parent_rows.append(
            {
                "path": relative,
                "actual_sha256": actual,
                "accepted_sha256": accepted,
                "successor_state_allowed": relative in V34_SUPERSEDED_FILES,
                "valid": valid,
            }
        )
        if not valid:
            errors.append(f"Target V3.4 parent mismatch: {relative}")
    if len(target_parent_rows) != 29:
        errors.append("Target V3.4 freeze does not declare exactly 29 files.")

    target_v34_artifact = _contained(target_root, V34_ARTIFACT_PATH)
    target_v34_artifact_raw = (
        _sha256(target_v34_artifact) if target_v34_artifact.is_file() else None
    )
    if target_v34_artifact_raw != V34_ARTIFACT_RAW_SHA256:
        errors.append("Target V3.4 scientific artifact identity mismatch.")

    errors = list(dict.fromkeys(errors))
    return {
        "errors": errors,
        "installer_version": INSTALLER_VERSION,
        "parent_files": target_parent_rows,
        "source_files": source_rows,
        "target_v34_artifact": {
            "actual_sha256": target_v34_artifact_raw,
            "expected_sha256": V34_ARTIFACT_RAW_SHA256,
            "valid": target_v34_artifact_raw == V34_ARTIFACT_RAW_SHA256,
        },
        "target_v34_freeze": {
            "raw_file_sha256": target_v34_freeze_raw,
            "semantic_sha256": target_v34_freeze_semantic,
            "valid": freeze_valid,
        },
        "valid": not errors,
    }


def _verification_commands(target_root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        (
            "v35_unit_tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "quantum_research_lab.test_phase3_v35",
            ],
        ),
        (
            "v35_release_chain",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_phase3_v35",
                str(target_root),
            ],
        ),
        (
            "v35_release_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v35",
                str(target_root),
                "--contract",
                str(target_root / "FREEZE_CONTRACT_V3_5.json"),
            ],
        ),
    )


def install(source_root: Path, target_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    report = preflight(source_root, target_root)
    if source_root == target_root:
        report["errors"].append(
            "Source and target must be distinct so rollback evidence remains independent."
        )
        report["valid"] = False
    if not report["valid"]:
        return {**report, "applied": False, "rolled_back": False}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = target_root / (
        f".quantum-lab-v35-backup-{timestamp}-{uuid4().hex[:8]}"
    )
    backup_root.mkdir(parents=False, exist_ok=False)
    existed: dict[str, bool] = {}
    applied: list[str] = []
    try:
        for relative in OVERLAY_FILES:
            source = _contained(source_root, relative)
            target = _contained(target_root, relative)
            existed[relative] = target.exists()
            if target.exists():
                backup = _contained(backup_root, relative)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(
                f".{target.name}.v35-{uuid4().hex}.tmp"
            )
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
            applied.append(relative)

        verification: dict[str, Any] = {}
        for label, command in _verification_commands(target_root):
            completed = subprocess.run(
                command,
                cwd=target_root,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            verification[label] = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            if completed.returncode != 0:
                raise RuntimeError(f"Post-install V3.5 {label} verification failed.")
        return {
            **report,
            "applied": True,
            "applied_files": applied,
            "backup_root": str(backup_root),
            "rolled_back": False,
            "verification": verification,
        }
    except Exception as exc:
        rollback_errors: list[str] = []
        for relative in reversed(applied):
            target = _contained(target_root, relative)
            try:
                if existed.get(relative):
                    shutil.copy2(_contained(backup_root, relative), target)
                elif target.exists():
                    target.unlink()
            except OSError as rollback_exc:
                rollback_errors.append(f"{relative}: {rollback_exc}")
        return {
            **report,
            "applied": False,
            "applied_files_before_failure": applied,
            "backup_root": str(backup_root),
            "error": str(exc),
            "rollback_errors": rollback_errors,
            "rolled_back": not rollback_errors,
        }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely install Quantum Lab V3.5.")
    parser.add_argument(
        "--source", type=Path, default=Path(__file__).resolve().parent
    )
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply atomically after preflight; omission performs check-only mode.",
    )
    args = parser.parse_args(argv)
    source = args.source.resolve()
    target = args.target.resolve()
    result = install(source, target) if args.apply else preflight(source, target)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.get("valid") and (not args.apply or result.get("applied")) else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["INSTALLER_VERSION", "OVERLAY_FILES", "install", "preflight"]
