"""Fail-closed transactional installer for the Quantum Lab V3.4 overlay."""

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


INSTALLER_VERSION = "QUANTUM LAB V3.4 TRANSACTIONAL INSTALLER · V1"
V33_PARENT_BYTES = {
    "FREEZE_CONTRACT_V3_3.json": "f01532faf2947a8eff321ca68aed8cc139a50c1ed808558de276a7237846f927",
    "SEALED_EXACT_DYADIC_BANDS_ORACLE.json": "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e",
    "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json": "616cc12808465916dfcfcde6c8e2c9feed1be4b294ad034f29cb7cb36704031b",
    "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json": "af04ddd8986d59cc18ba33f756b24ade93ef005ff0b0df14d88d4c52d537b565",
}
V33_UI_SHA256 = "e9862c581cb4c77824c67b2570bcc1a081f4da944a347f558e051f86227b26df"
V34_UI_SHA256 = "2ab26702f0066574136eee0e93a46121a1273fee3d2d6a3c9354139e0aa27684"
OVERLAY_FILES = (
    "FREEZE_CONTRACT_V3_4.json",
    "DEPLOY_V3_4.md",
    "install_quantum_lab_v34.py",
    "outputs/quantum_phase3/optimized_native/SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_4_ARCHITECTURE.md",
    "quantum_research_lab/phase3_native_mixer.py",
    "quantum_research_lab/phase3_optimized_oracle.py",
    "quantum_research_lab/phase3_v34_ui.py",
    "quantum_research_lab/phase3_v34_validation.py",
    "quantum_research_lab/test_phase3_v34.py",
    "quantum_research_lab/ui.py",
    "quantum_research_lab/verify_freeze_contract_v34.py",
    "quantum_research_lab/verify_phase3_v34.py",
    "quantum_research_lab/verify_phase3_v34_ui.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _freeze_semantic_sha256(payload: dict[str, Any]) -> str:
    core = {
        key: value for key, value in payload.items() if key != "freeze_contract_sha256"
    }
    return _canonical_json_sha256(core)


def _contained(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    target.relative_to(root.resolve())
    return target


def preflight(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    if target_root.resolve() in {Path("/").resolve(), Path.home().resolve()}:
        errors.append("Refusing a broad target directory.")
    if not (target_root / "quantum_research_lab").is_dir():
        errors.append("Target does not contain quantum_research_lab/.")
    try:
        freeze = json.loads((source_root / "FREEZE_CONTRACT_V3_4.json").read_text())
    except Exception as exc:
        freeze = {}
        errors.append(f"Cannot load V3.4 freeze: {exc}")
    frozen_files = freeze.get("frozen_files") or {}
    source_rows: list[dict[str, Any]] = []
    for relative in OVERLAY_FILES:
        source = _contained(source_root, relative)
        if relative == "FREEZE_CONTRACT_V3_4.json":
            expected = freeze.get("freeze_contract_sha256")
            actual = _freeze_semantic_sha256(freeze) if freeze else None
            integrity = "CANONICAL_JSON_SELF_HASH"
        else:
            expected = frozen_files.get(relative)
            actual = _sha256(source) if source.is_file() else None
            integrity = "RAW_FILE_SHA256"
        valid = bool(expected and actual == expected)
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
    parent_rows: list[dict[str, Any]] = []
    for relative, expected in V33_PARENT_BYTES.items():
        target = _contained(target_root, relative)
        actual = _sha256(target) if target.is_file() else None
        valid = actual == expected
        parent_rows.append(
            {"path": relative, "actual_sha256": actual, "expected_sha256": expected, "valid": valid}
        )
        if not valid:
            errors.append(f"Target V3.3 parent mismatch: {relative}")
    ui_target = _contained(target_root, "quantum_research_lab/ui.py")
    ui_actual = _sha256(ui_target) if ui_target.is_file() else None
    ui_valid = ui_actual in {V33_UI_SHA256, V34_UI_SHA256}
    if not ui_valid:
        errors.append("Target UI is neither the frozen V3.3 parent nor this exact V3.4 successor.")
    return {
        "errors": errors,
        "installer_version": INSTALLER_VERSION,
        "parent_files": parent_rows,
        "source_files": source_rows,
        "target_ui": {
            "actual_sha256": ui_actual,
            "accepted_sha256": [V33_UI_SHA256, V34_UI_SHA256],
            "valid": ui_valid,
        },
        "valid": not errors,
    }


def _verification_command(target_root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "quantum_research_lab.verify_phase3_v34",
        "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json",
        "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json",
        "FREEZE_CONTRACT_V3_3.json",
        "outputs/quantum_phase3/optimized_native/SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json",
    ]


def _freeze_verification_command(target_root: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "quantum_research_lab.verify_freeze_contract_v34",
        str(target_root),
        "--contract",
        str(target_root / "FREEZE_CONTRACT_V3_4.json"),
    ]


def install(source_root: Path, target_root: Path) -> dict[str, Any]:
    report = preflight(source_root, target_root)
    if source_root.resolve() == target_root.resolve():
        report["errors"].append(
            "Source and target must be distinct so rollback evidence remains independent."
        )
        report["valid"] = False
    if not report["valid"]:
        return {**report, "applied": False, "rolled_back": False}
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = target_root / f".quantum-lab-v34-backup-{timestamp}-{uuid4().hex[:8]}"
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
            temporary = target.with_name(f".{target.name}.v34-{uuid4().hex}.tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
            applied.append(relative)
        verification: dict[str, Any] = {}
        for label, command in (
            ("release_chain", _verification_command(target_root)),
            ("release_freeze", _freeze_verification_command(target_root)),
        ):
            completed = subprocess.run(
                command,
                cwd=target_root,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
            verification[label] = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            if completed.returncode != 0:
                raise RuntimeError(f"Post-install V3.4 {label} verification failed.")
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
    parser = argparse.ArgumentParser(description="Safely install Quantum Lab V3.4.")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
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
