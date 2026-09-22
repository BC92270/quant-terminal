"""Recoverable, fail-closed installer for the Quantum Lab V3.6 overlay."""

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


INSTALLER_VERSION = "QUANTUM LAB V3.6 RECOVERABLE INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v36-install.lock"
V35_FREEZE_RAW_SHA256 = "8d0a5ca3f37cf4c7a755537d55eb7b2a202bb72603527ec9f4f8fb7d1ba21f52"
V35_FREEZE_SEMANTIC_SHA256 = "efda21e201cd9ecc7b4fab7544c4c024a96b925dc39f977c17331a5278c994d2"
V35_README_SHA256 = "17e623716e33cb3ee7f862bcb52e1d772655db69b0182e9ea08537f43bef9db9"
V35_UI_SHA256 = "0f6cc9930f3b9ca7003b662e84e83ea78fbd6c79ecb6676c7fa0dc032a72b6eb"
V35_FROZEN_PATHS_FINGERPRINT = "2ff324dbfb7d1516d7e1d7215bccd60a32668319d43dc33b9b3f55723bd00e87"

# Dependencies first; README is the penultimate integration surface and ui.py
# is replaced strictly last.
OVERLAY_FILES = (
    "FREEZE_CONTRACT_V3_6.json",
    "DEPLOY_V3_6.md",
    "app_v35_offline_harness.py",
    "app_v36_offline_harness.py",
    "install_quantum_lab_v36.py",
    "outputs/quantum_phase3/v36_reduction/SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_6_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v36_algorithmic_reduction.py",
    "quantum_research_lab/phase3_v36_ui.py",
    "quantum_research_lab/phase3_v36_validation.py",
    "quantum_research_lab/test_phase3_v36.py",
    "quantum_research_lab/test_phase3_v36_release.py",
    "quantum_research_lab/verify_freeze_contract_v36.py",
    "quantum_research_lab/verify_phase3_v36.py",
    "quantum_research_lab/verify_phase3_v36_ui.py",
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
)
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V35_FREEZE_PATH = "FREEZE_CONTRACT_V3_5.json"


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


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"Absolute/empty overlay path rejected: {relative!r}")
    root_resolved = root.resolve(strict=True)
    lexical = root_resolved / relative_path
    cursor = root_resolved
    for part in relative_path.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"Symlinked destination ancestor rejected: {relative}")
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
    target.relative_to(root_resolved)
    return target


def _successor_state(readme_sha: str | None, ui_sha: str | None, freeze: Mapping[str, Any]) -> str:
    policy = freeze.get("successor_policy") or {}
    v36_pair = (
        policy.get("v36_successor_readme_sha256"),
        policy.get("v36_successor_ui_sha256"),
    )
    pair = (readme_sha, ui_sha)
    if pair == (V35_README_SHA256, V35_UI_SHA256):
        return "V3.5"
    if all(v36_pair) and pair == v36_pair:
        return "V3.6"
    return "INVALID"


def _source_inventory(source_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        freeze_path = _contained(source_root, "FREEZE_CONTRACT_V3_6.json", must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot authenticate source V3.6 freeze: {exc}"]
    frozen_files = freeze.get("frozen_files") or {}
    rows: list[dict[str, Any]] = []
    for relative in OVERLAY_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == "FREEZE_CONTRACT_V3_6.json":
                actual = _freeze_semantic(freeze)
                expected = freeze.get("freeze_contract_sha256")
                integrity = "CANONICAL_JSON_SELF_HASH"
            else:
                actual = _sha256(path)
                expected = frozen_files.get(relative)
                integrity = "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except Exception as exc:
            actual = None
            expected = frozen_files.get(relative) if isinstance(frozen_files, dict) else None
            integrity = "RAW_FILE_SHA256"
            valid = False
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
    if set(OVERLAY_FILES) - {"FREEZE_CONTRACT_V3_6.json"} - set(frozen_files):
        errors.append("V3.6 freeze omits one or more overlay paths.")
    return freeze, rows, list(dict.fromkeys(errors))


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    """Authenticate the exact V3.5/V3.6 transition state before any mutation."""

    errors: list[str] = []
    try:
        parent_freeze_path = _contained(target_root, V35_FREEZE_PATH, must_exist=True)
        parent_freeze = _read_json_strict(parent_freeze_path)
        parent_raw = _sha256(parent_freeze_path)
        parent_semantic = _freeze_semantic(parent_freeze)
    except Exception as exc:
        parent_freeze = {}
        parent_raw = parent_semantic = None
        errors.append(f"Cannot authenticate target V3.5 freeze: {exc}")
    parent_files = parent_freeze.get("frozen_files") or {}
    parent_path_fingerprint = hashlib.sha256(
        json.dumps(sorted(parent_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    parent_identity = bool(
        parent_raw == V35_FREEZE_RAW_SHA256
        and parent_semantic == V35_FREEZE_SEMANTIC_SHA256
        and parent_freeze.get("freeze_contract_sha256") == V35_FREEZE_SEMANTIC_SHA256
        and parent_freeze.get("frozen_file_count") == 41
        and len(parent_files) == 41
        and parent_path_fingerprint == V35_FROZEN_PATHS_FINGERPRINT
    )
    if not parent_identity:
        errors.append("Target V3.5 freeze raw/semantic identity or 41-path inventory mismatch.")

    immutable: dict[str, bool] = {}
    for relative in sorted(set(parent_files) - {README_PATH, UI_PATH}):
        try:
            immutable[relative] = (
                _sha256(_contained(target_root, relative, must_exist=True))
                == parent_files.get(relative)
            )
        except Exception as exc:
            immutable[relative] = False
            errors.append(f"Target parent {relative}: {exc}")
        if not immutable[relative]:
            errors.append(f"Target immutable V3.5 mismatch: {relative}")

    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    try:
        source_freeze = _read_json_strict(
            _contained(source_root, "FREEZE_CONTRACT_V3_6.json", must_exist=True)
        )
    except Exception as exc:
        source_freeze = {}
        errors.append(f"Source transition policy: {exc}")
    state = _successor_state(readme_sha, ui_sha, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown or an unauthorized third state.")

    # Existing overlay destinations must be regular files; absent new files are allowed.
    for relative in OVERLAY_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")

    exact_overlay = False
    if state == "V3.6":
        exact_overlay = True
        expected = source_freeze.get("frozen_files") or {}
        for relative in OVERLAY_FILES:
            try:
                if relative == "FREEZE_CONTRACT_V3_6.json":
                    source_value = _freeze_semantic(source_freeze)
                    target_value = _freeze_semantic(
                        _read_json_strict(_contained(target_root, relative, must_exist=True))
                    )
                else:
                    source_value = expected.get(relative)
                    target_value = _sha256(_contained(target_root, relative, must_exist=True))
                if not source_value or target_value != source_value:
                    exact_overlay = False
            except Exception:
                exact_overlay = False
        if not exact_overlay:
            errors.append("Target claims V3.6 surface state but overlay is incomplete or mismatched.")

    return {
        "errors": list(dict.fromkeys(errors)),
        "exact_overlay": exact_overlay,
        "immutable_file_count": len(immutable),
        "immutable_files_exact": len(immutable) == 39 and all(immutable.values()),
        "parent_freeze_raw_sha256": parent_raw,
        "parent_freeze_semantic_sha256": parent_semantic,
        "parent_identity_exact": parent_identity,
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
    source_commitments = {
        row["path"]: row["actual_sha256"] for row in source_rows if row.get("valid")
    }
    return {
        "errors": list(dict.fromkeys(errors)),
        "installer_version": INSTALLER_VERSION,
        "overlay_file_count": len(OVERLAY_FILES),
        "source_commitments": source_commitments,
        "source_files": source_rows,
        "source_freeze_sha256": freeze.get("freeze_contract_sha256"),
        "target": target,
        "valid": not errors,
    }


def _verification_commands(target_root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        (
            "v36_unit_tests",
            [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v36"],
        ),
        (
            "v36_release_tests",
            [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v36_release"],
        ),
        (
            "v36_release_chain",
            [sys.executable, "-m", "quantum_research_lab.verify_phase3_v36", str(target_root)],
        ),
        (
            "v36_release_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v36",
                str(target_root),
                "--contract",
                str(target_root / "FREEZE_CONTRACT_V3_6.json"),
            ],
        ),
        (
            "v36_streamlit_positive_rerun",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_phase3_v36_ui",
                str(target_root / "app_v36_offline_harness.py"),
                "--timeout",
                "180",
            ],
        ),
    )


def _run_commands(commands: tuple[tuple[str, list[str]], ...], cwd: Path) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for label, command in commands:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        reports[label] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise RuntimeError(f"Post-install verification failed: {label}")
    return reports


def _preimage_entry(target: Path) -> dict[str, Any]:
    if not target.exists():
        return {"existed": False, "mode": None, "sha256": None}
    mode = stat.S_IMODE(target.stat().st_mode)
    return {"existed": True, "mode": mode, "sha256": _sha256(target)}


def _verify_preimages(target_root: Path, preimages: Mapping[str, Any]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for relative, expected in preimages.items():
        target = target_root / relative
        try:
            if expected.get("existed"):
                actual = _preimage_entry(_contained(target_root, relative, must_exist=True))
                if actual != expected:
                    errors.append(f"Rollback preimage mismatch: {relative}")
            elif target.exists() or target.is_symlink():
                errors.append(f"Rollback failed to remove new path: {relative}")
        except Exception as exc:
            errors.append(f"Rollback verification {relative}: {exc}")
    return not errors, errors


def _verify_state_after_rollback(
    target_root: Path, predecessor_state: str
) -> tuple[bool, dict[str, Any]]:
    v35_commands = (
        (
            "v35_release_chain",
            [sys.executable, "-m", "quantum_research_lab.verify_phase3_v35", str(target_root)],
        ),
        (
            "v35_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v35",
                str(target_root),
                "--contract",
                str(target_root / V35_FREEZE_PATH),
            ],
        ),
    )
    v36_commands = (
        (
            "v36_release_chain",
            [sys.executable, "-m", "quantum_research_lab.verify_phase3_v36", str(target_root)],
        ),
        (
            "v36_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v36",
                str(target_root),
                "--contract",
                str(target_root / "FREEZE_CONTRACT_V3_6.json"),
            ],
        ),
    )
    commands = v35_commands if predecessor_state == "V3.5" else v36_commands
    reports: dict[str, Any] = {}
    okay = True
    for label, command in commands:
        completed = subprocess.run(
            command, cwd=target_root, capture_output=True, text=True, timeout=300, check=False
        )
        reports[label] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        okay = okay and completed.returncode == 0
    return okay, reports


def install(
    source_root: Path,
    target_root: Path,
    *,
    _test_fail_after: int | None = None,
    _test_force_apply: bool = False,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    lock_path = target_root / LOCK_NAME
    try:
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return {
            "applied": False,
            "errors": [f"Install lock already exists: {lock_path}"],
            "idempotent": False,
            "rolled_back": False,
            "valid": False,
        }
    try:
        os.write(lock_fd, f"pid={os.getpid()}\n".encode("ascii"))
    finally:
        os.close(lock_fd)

    stage_root: Path | None = None
    backup_root: Path | None = None
    report: dict[str, Any] = {}
    try:
        report = preflight(source_root, target_root)
        if not report["valid"]:
            return {**report, "applied": False, "idempotent": False, "rolled_back": False}
        predecessor_state = str(report["target"].get("successor_state"))
        if (
            not _test_force_apply
            and predecessor_state == "V3.6"
            and report["target"].get("exact_overlay")
        ):
            return {**report, "applied": False, "idempotent": True, "rolled_back": False}

        token = uuid4().hex[:10]
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stage_root = target_root / f".quantum-lab-v36-stage-{token}"
        backup_root = target_root / f".quantum-lab-v36-backup-{timestamp}-{token}"
        stage_root.mkdir(mode=0o700)
        backup_root.mkdir(mode=0o700)

        commitments = report["source_commitments"]
        for relative in OVERLAY_FILES:
            source = _contained(source_root, relative, must_exist=True)
            staged = stage_root / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged, follow_symlinks=False)
            if relative == "FREEZE_CONTRACT_V3_6.json":
                actual = _freeze_semantic(_read_json_strict(staged))
            else:
                actual = _sha256(staged)
            if actual != commitments.get(relative):
                raise RuntimeError(f"Staged source commitment mismatch: {relative}")

        # Detect source mutation after preflight/staging.
        for relative, expected in commitments.items():
            source = _contained(source_root, relative, must_exist=True)
            actual = (
                _freeze_semantic(_read_json_strict(source))
                if relative == "FREEZE_CONTRACT_V3_6.json"
                else _sha256(source)
            )
            if actual != expected:
                raise RuntimeError(f"Source changed after preflight: {relative}")

        preimages: dict[str, dict[str, Any]] = {}
        for relative in OVERLAY_FILES:
            target = _contained(target_root, relative, must_exist=False)
            preimages[relative] = _preimage_entry(target)
            if target.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup, follow_symlinks=False)
        manifest_core = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "installer_version": INSTALLER_VERSION,
            "preimages": preimages,
            "target_root": str(target_root),
        }
        manifest = {
            **manifest_core,
            "manifest_sha256": _canonical_json_sha256(manifest_core),
        }
        (backup_root / "PREIMAGE_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        applied: list[str] = []
        try:
            for relative in OVERLAY_FILES:
                staged = _contained(stage_root, relative, must_exist=True)
                target = _contained(target_root, relative, must_exist=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(f".{target.name}.v36-{token}.tmp")
                shutil.copy2(staged, temporary, follow_symlinks=False)
                os.replace(temporary, target)
                applied.append(relative)
                if _test_fail_after is not None and len(applied) == _test_fail_after:
                    raise RuntimeError("Injected V3.6 installer rollback test fault.")
            if not applied or applied[-1] != UI_PATH:
                raise RuntimeError("ui.py was not the final replaced path.")
            verification = _run_commands(_verification_commands(target_root), target_root)
            return {
                **report,
                "applied": True,
                "applied_files": applied,
                "backup_root": str(backup_root),
                "idempotent": False,
                "rolled_back": False,
                "ui_replaced_last": applied[-1] == UI_PATH,
                "verification": verification,
            }
        except Exception as exc:
            rollback_errors: list[str] = []
            for relative in reversed(applied):
                expected = preimages[relative]
                target = target_root / relative
                try:
                    if expected["existed"]:
                        backup = _contained(backup_root, relative, must_exist=True)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        temporary = target.with_name(f".{target.name}.rollback-{token}.tmp")
                        shutil.copy2(backup, temporary, follow_symlinks=False)
                        os.chmod(temporary, int(expected["mode"]))
                        os.replace(temporary, target)
                    elif target.exists() or target.is_symlink():
                        target.unlink()
                except Exception as rollback_exc:
                    rollback_errors.append(f"{relative}: {rollback_exc}")
            preimage_ok, preimage_errors = _verify_preimages(target_root, preimages)
            rollback_errors.extend(preimage_errors)
            predecessor_ok, predecessor_verification = _verify_state_after_rollback(
                target_root, predecessor_state
            )
            rolled_back = not rollback_errors and preimage_ok and predecessor_ok
            return {
                **report,
                "applied": False,
                "applied_files_before_failure": applied,
                "backup_root": str(backup_root),
                "error": str(exc),
                "idempotent": False,
                "preimages_restored": preimage_ok,
                "predecessor_verification": predecessor_verification,
                "rollback_errors": rollback_errors,
                "rolled_back": rolled_back,
            }
    finally:
        if stage_root and stage_root.exists():
            shutil.rmtree(stage_root)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely install Quantum Lab V3.6.")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = install(args.source, args.target) if args.apply else preflight(args.source, args.target)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    success = result.get("valid") and (
        not args.apply or result.get("applied") or result.get("idempotent")
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "INSTALLER_VERSION",
    "LOCK_NAME",
    "OVERLAY_FILES",
    "authenticate_target",
    "install",
    "preflight",
]
