"""Recoverable, fail-closed installer for the Quantum Lab V3.8 overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4


INSTALLER_VERSION = "QUANTUM LAB V3.8 RECOVERABLE INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v38-install.lock"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V3_7.json"
PARENT_FREEZE_RAW_SHA256 = "57b273f87e4e2f2a95e0ccbdd6c844c1c3f5d8bfec5dbfd5d488aaefb0290970"
PARENT_FREEZE_SEMANTIC_SHA256 = "86f247a9dfb918a2eca04ffe96c03adee62c3d8603d99aab3e0d6bf8c07167e7"
PARENT_FROZEN_FILE_COUNT = 99
PARENT_IMMUTABLE_FILE_COUNT = 97
PARENT_README_SHA256 = "d72c5801b08401fbb1785bc905764de7ae4434899ed9ce63c44601a1eba432a8"
PARENT_UI_SHA256 = "b1faa89c878f87d5c443582f3adb4aa430873e7f3e07c5869bc6da948a27b0d1"
EXPECTED_V38_FROZEN_FILE_COUNT = 114
EXPECTED_V38_FROZEN_PATHS_FINGERPRINT = "90df2180f9965d3721b91b215b2ac7da0eddcde38f890d374863b3079f1c2f19"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V38_FREEZE_PATH = "FREEZE_CONTRACT_V3_8.json"

V38_TRANSITION_FILES = (
    V38_FREEZE_PATH,
    "DEPLOY_V3_8.md",
    "app_v38_offline_harness.py",
    "install_quantum_lab_v38.py",
    "outputs/quantum_phase3/v38_elementary/SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_8_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v38_elementary_admission.py",
    "quantum_research_lab/phase3_v38_ui.py",
    "quantum_research_lab/phase3_v38_validation.py",
    "quantum_research_lab/test_phase3_v38.py",
    "quantum_research_lab/test_phase3_v38_release.py",
    "quantum_research_lab/verify_freeze_contract_v38.py",
    "quantum_research_lab/verify_phase3_v38.py",
    "quantum_research_lab/verify_phase3_v38_ui.py",
    README_PATH,
    UI_PATH,
)
V38_ONLY_FILES = frozenset(V38_TRANSITION_FILES) - {README_PATH, UI_PATH}


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
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe path rejected: {relative!r}")
    release_root = root.resolve(strict=True)
    lexical = release_root / item
    cursor = release_root
    for part in item.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"Symlinked ancestor rejected: {relative}")
        else:
            break
    if must_exist:
        mode = lexical.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError(f"Not a regular non-symlink file: {relative}")
        target = lexical.resolve(strict=True)
    else:
        target = lexical
        if lexical.exists() or lexical.is_symlink():
            mode = lexical.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise ValueError(f"Unsafe existing destination: {relative}")
    target.relative_to(release_root)
    return target


def _source_inventory(source_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        freeze_path = _contained(source_root, V38_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot read source V3.8 freeze: {exc}"]
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        return freeze, [], ["V3.8 frozen_files must be an object."]
    fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not (
        freeze.get("frozen_file_count") == EXPECTED_V38_FROZEN_FILE_COUNT
        and len(frozen) == EXPECTED_V38_FROZEN_FILE_COUNT
        and fingerprint == EXPECTED_V38_FROZEN_PATHS_FINGERPRINT
        and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
    ):
        errors.append("V3.8 source freeze identity, count, or path fingerprint mismatch.")
    policy = freeze.get("successor_policy") or {}
    if not (
        policy.get("accepted_target_states") == ["V3.7", "V3.8"]
        and policy.get("allowed_v37_superseded_files") == [README_PATH, UI_PATH]
        and policy.get("mixed_or_third_state") == "REJECT"
    ):
        errors.append("V3.8 successor policy mismatch.")
    rows: list[dict[str, Any]] = []
    for relative in V38_TRANSITION_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V38_FREEZE_PATH:
                actual = _freeze_semantic(freeze)
                expected = freeze.get("freeze_contract_sha256")
                integrity = "CANONICAL_JSON_SELF_HASH"
            else:
                actual = _sha256(path)
                expected = frozen.get(relative)
                integrity = "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except Exception as exc:
            actual, expected, integrity, valid = None, frozen.get(relative), "RAW_FILE_SHA256", False
            errors.append(f"Source path {relative}: {exc}")
        rows.append(
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
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(
    readme_sha: str | None, ui_sha: str | None, source_freeze: Mapping[str, Any]
) -> str:
    if (readme_sha, ui_sha) == (PARENT_README_SHA256, PARENT_UI_SHA256):
        return "V3.7"
    policy = source_freeze.get("successor_policy") or {}
    if (readme_sha, ui_sha) == (
        policy.get("v38_successor_readme_sha256"),
        policy.get("v38_successor_ui_sha256"),
    ):
        return "V3.8"
    return "INVALID"


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        source_freeze = _read_json_strict(_contained(source_root, V38_FREEZE_PATH, must_exist=True))
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V3.8 source freeze self-hash mismatch")
    except Exception as exc:
        source_freeze = {}
        errors.append(f"Source transition policy: {exc}")
    try:
        parent_path = _contained(target_root, PARENT_FREEZE_PATH, must_exist=True)
        parent = _read_json_strict(parent_path)
        parent_raw = _sha256(parent_path)
        parent_semantic = _freeze_semantic(parent)
    except Exception as exc:
        parent = {}
        parent_raw = parent_semantic = None
        errors.append(f"Cannot authenticate target V3.7 freeze: {exc}")
    parent_files = parent.get("frozen_files") or {}
    parent_identity = bool(
        parent_raw == PARENT_FREEZE_RAW_SHA256
        and parent_semantic == PARENT_FREEZE_SEMANTIC_SHA256
        and parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and isinstance(parent_files, dict)
        and len(parent_files) == PARENT_FROZEN_FILE_COUNT
    )
    if not parent_identity:
        errors.append("Target V3.7 freeze raw/semantic identity or inventory mismatch.")
    immutable: dict[str, bool] = {}
    if isinstance(parent_files, dict):
        for relative in sorted(set(parent_files) - {README_PATH, UI_PATH}):
            try:
                immutable[relative] = _sha256(_contained(target_root, relative, must_exist=True)) == parent_files.get(relative)
            except Exception as exc:
                immutable[relative] = False
                errors.append(f"Target parent {relative}: {exc}")
            if not immutable[relative]:
                errors.append(f"Target immutable V3.7 mismatch: {relative}")
    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    state = _successor_state(readme_sha, ui_sha, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown, or an unauthorized third state.")
    for relative in V38_TRANSITION_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")
    partial_paths: list[str] = []
    if state == "V3.7":
        partial_paths = sorted(
            relative
            for relative in V38_ONLY_FILES
            if (target_root / relative).exists() or (target_root / relative).is_symlink()
        )
        if partial_paths:
            errors.append("Partial V3.8 destinations exist on a V3.7 successor surface.")
    exact_overlay = False
    if state == "V3.8":
        exact_overlay = True
        expected = source_freeze.get("frozen_files") or {}
        for relative in V38_TRANSITION_FILES:
            try:
                if relative == V38_FREEZE_PATH:
                    source_value = _freeze_semantic(source_freeze)
                    target_value = _freeze_semantic(_read_json_strict(_contained(target_root, relative, must_exist=True)))
                else:
                    source_value = expected.get(relative)
                    target_value = _sha256(_contained(target_root, relative, must_exist=True))
                if not source_value or target_value != source_value:
                    exact_overlay = False
            except Exception:
                exact_overlay = False
        if not exact_overlay:
            errors.append("Target claims V3.8 surface state but overlay is incomplete or mismatched.")
    return {
        "errors": list(dict.fromkeys(errors)),
        "exact_overlay": exact_overlay,
        "immutable_v37_file_count": len(immutable),
        "immutable_v37_files_exact": len(immutable) == PARENT_IMMUTABLE_FILE_COUNT and all(immutable.values()),
        "parent_freeze_raw_sha256": parent_raw,
        "parent_freeze_semantic_sha256": parent_semantic,
        "parent_identity_exact": parent_identity,
        "partial_v38_paths": partial_paths,
        "successor_state": state,
        "valid": not errors,
    }


def preflight(source_root: Path, target_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    errors: list[str] = []
    if target_root in {Path("/").resolve(), Path.home().resolve()}:
        errors.append("Refusing a broad target directory.")
    if source_root == target_root:
        errors.append("Source and target must be distinct.")
    if not (target_root / "quantum_research_lab").is_dir():
        errors.append("Target does not contain quantum_research_lab/.")
    freeze, source_rows, source_errors = _source_inventory(source_root)
    errors.extend(source_errors)
    target = authenticate_target(source_root, target_root)
    errors.extend(target.get("errors") or [])
    return {
        "errors": list(dict.fromkeys(errors)),
        "installer_version": INSTALLER_VERSION,
        "overlay_file_count": len(V38_TRANSITION_FILES),
        "source_commitments": {
            row["path"]: row["actual_sha256"] for row in source_rows if row.get("valid")
        },
        "source_files": source_rows,
        "source_freeze_sha256": freeze.get("freeze_contract_sha256"),
        "target": target,
        "valid": not errors,
    }


def _verification_commands(target_root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        ("v38_unit_tests", [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v38"]),
        ("v38_release_tests", [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v38_release"]),
        ("v38_scientific_validation", [sys.executable, "-m", "quantum_research_lab.phase3_v38_validation"]),
        ("v38_release_chain", [sys.executable, "-m", "quantum_research_lab.verify_phase3_v38", str(target_root)]),
        (
            "v38_release_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v38",
                str(target_root),
                "--contract",
                str(target_root / V38_FREEZE_PATH),
            ],
        ),
        (
            "v38_streamlit_positive_rerun",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_phase3_v38_ui",
                str(target_root / "app_v38_offline_harness.py"),
                "--timeout",
                "180",
            ],
        ),
        (
            "historical_unit_regression",
            [
                sys.executable,
                "-m",
                "unittest",
                "quantum_research_lab.test_phase3_gate_compiler",
                "quantum_research_lab.test_phase3_algorithmic_contract",
                "quantum_research_lab.test_phase3_v34",
                "quantum_research_lab.test_phase3_v35",
                "quantum_research_lab.test_phase3_v36",
                "quantum_research_lab.test_phase3_v37",
            ],
        ),
    )


def _run_commands(commands: tuple[tuple[str, list[str]], ...], cwd: Path, *, force_failure: bool = False) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for index, (label, command) in enumerate(commands):
        if force_failure and index == 0:
            raise RuntimeError("Injected V3.8 post-install verification fault.")
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=900, check=False)
        reports[label] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise RuntimeError(f"Post-install verification failed: {label}")
    return reports


def _atomic_copy(source: Path, target: Path, token: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.v38-{token}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise FileExistsError(f"Temporary destination already exists: {temporary}")
    shutil.copy2(source, temporary, follow_symlinks=False)
    with temporary.open("rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, target)


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def install(
    source_root: str | Path,
    target_root: str | Path,
    *,
    apply: bool = False,
    force_verification_failure: bool = False,
) -> dict[str, Any]:
    source = Path(source_root).resolve(strict=True)
    target = Path(target_root).resolve(strict=True)
    report = preflight(source, target)
    if not report["valid"]:
        return {"applied": False, "no_op": False, "preflight": report, "valid": False}
    if report["target"]["exact_overlay"]:
        return {
            "applied": False,
            "no_op": True,
            "preflight": report,
            "postinstall": report["target"],
            "valid": True,
        }
    if not apply:
        return {"applied": False, "no_op": False, "preflight": report, "valid": True}
    token = uuid4().hex
    lock = target / LOCK_NAME
    descriptor: int | None = None
    backup: Path | None = None
    preimages: dict[str, dict[str, Any]] = {}
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        lock_payload = json.dumps({"installer": INSTALLER_VERSION, "pid": os.getpid(), "token": token}).encode("utf-8")
        os.write(descriptor, lock_payload)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = target / f".quantum-lab-v38-backup-{stamp}-{token[:12]}"
        backup.mkdir(mode=0o700)
        for relative in V38_TRANSITION_FILES:
            destination = target / relative
            existed = destination.exists() or destination.is_symlink()
            if existed:
                safe = _contained(target, relative, must_exist=True)
                entry = {"existed": True, "sha256": _sha256(safe)}
                backup_path = backup / relative
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(safe, backup_path, follow_symlinks=False)
            else:
                entry = {"existed": False, "sha256": None}
            preimages[relative] = entry
        _write_manifest(
            backup / "PREIMAGE_MANIFEST.json",
            {
                "installer": INSTALLER_VERSION,
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_freeze_sha256": report["source_freeze_sha256"],
                "preimages": preimages,
            },
        )
        for relative in V38_TRANSITION_FILES:
            _atomic_copy(_contained(source, relative, must_exist=True), _contained(target, relative), token)
        verification = _run_commands(
            _verification_commands(target), target, force_failure=force_verification_failure
        )
        postinstall = authenticate_target(source, target)
        if not (postinstall["valid"] and postinstall["exact_overlay"] and postinstall["successor_state"] == "V3.8"):
            raise RuntimeError("Installed V3.8 overlay failed exact post-authentication.")
        return {
            "applied": True,
            "backup": str(backup),
            "no_op": False,
            "postinstall": postinstall,
            "preflight": report,
            "valid": True,
            "verification": verification,
        }
    except BaseException as exc:
        rollback_errors: list[str] = []
        if backup is not None:
            for relative in reversed(V38_TRANSITION_FILES):
                try:
                    destination = target / relative
                    entry = preimages.get(relative) or {}
                    if entry.get("existed"):
                        _atomic_copy(backup / relative, _contained(target, relative), token + "-rollback")
                    elif destination.exists() or destination.is_symlink():
                        safe = _contained(target, relative, must_exist=True)
                        safe.unlink()
                except Exception as rollback_exc:
                    rollback_errors.append(f"{relative}: {rollback_exc}")
        rollback = authenticate_target(source, target) if not rollback_errors else {"valid": False}
        return {
            "applied": False,
            "backup": str(backup) if backup else None,
            "error": str(exc),
            "no_op": False,
            "preflight": report,
            "rollback": rollback,
            "rollback_errors": rollback_errors,
            "valid": False,
        }
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if lock.exists() and not lock.is_symlink():
            try:
                lock.unlink()
            except OSError:
                pass


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install the Quantum Lab V3.8 overlay.")
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = install(args.source, args.target, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "INSTALLER_VERSION",
    "V38_TRANSITION_FILES",
    "authenticate_target",
    "install",
    "preflight",
]
