"""Transactional, fail-closed installer for the Quantum Lab V4.1 overlay.

The only accepted transition is an exact V4.0 release to an exact V4.1
release.  The installer is deliberately provider-free: it does not inspect
credentials, install packages, make network calls, transpile a circuit, or
submit a QPU job.
"""

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
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4


INSTALLER_VERSION = "QUANTUM LAB V4.1 TRANSACTIONAL INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v41-install.lock"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_0.json"
V41_FREEZE_PATH = "FREEZE_CONTRACT_V4_1.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"

PARENT_FREEZE_RAW_SHA256 = (
    "748829b2153611ffba0751ea5da9d0785ca44ce4f12a02546436d4a1e79a94b4"
)
PARENT_FREEZE_SEMANTIC_SHA256 = (
    "c6d380e5541182b6cc2096c3d2a6de6f129cb92c80288a43dae6f924314cff1e"
)
PARENT_FROZEN_FILE_COUNT = 145
PARENT_IMMUTABLE_FILE_COUNT = 143
PARENT_FROZEN_PATHS_FINGERPRINT = (
    "43e80508152726db7fb8b255ba5642301abaadb6a562783fd235367475000fe3"
)
PARENT_README_SHA256 = (
    "f9a790ee308466882ff8b030ce0bdae40ac9e82cab873813e32e9067de8dd0d2"
)
PARENT_UI_SHA256 = (
    "3c3282da1537740493da9e195cb9c7d016cb8cabfce8a466f373b48cd6c31f84"
)

EXPECTED_V41_FROZEN_FILE_COUNT = 161
EXPECTED_V41_FROZEN_PATHS_FINGERPRINT = (
    "27bb43b53f3c6847d1ef80518c595755c1e606015b423c194c8a2e61f3f76ea8"
)

# Supporting files first.  The human-readable surface is penultimate and the
# executable integration surface is strictly last.
V41_TRANSITION_FILES = (
    V41_FREEZE_PATH,
    "DEPLOY_V4_1.md",
    "app_v41_offline_harness.py",
    "install_quantum_lab_v41.py",
    "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_1_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v41_bridge_engine.cpp",
    "quantum_research_lab/phase3_v41_certified_bridge_compiler.py",
    "quantum_research_lab/phase3_v41_ui.py",
    "quantum_research_lab/phase3_v41_validation.py",
    "quantum_research_lab/test_phase3_v41.py",
    "quantum_research_lab/test_phase3_v41_release.py",
    "quantum_research_lab/verify_freeze_contract_v41.py",
    "quantum_research_lab/verify_phase3_v41.py",
    "quantum_research_lab/verify_phase3_v41_ui.py",
    README_PATH,
    UI_PATH,
)
V41_ONLY_FILES = frozenset(V41_TRANSITION_FILES) - {README_PATH, UI_PATH}


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
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _valid_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _path_fingerprint(paths: Sequence[str] | set[str] | Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    item = Path(relative)
    if (
        not relative
        or item.is_absolute()
        or any(part in {"", ".", ".."} for part in item.parts)
    ):
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
        resolved = lexical.resolve(strict=True)
    else:
        resolved = lexical
        if lexical.exists() or lexical.is_symlink():
            mode = lexical.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                raise ValueError(f"Unsafe existing destination: {relative}")
    resolved.relative_to(release_root)
    return resolved


def _validate_roots(source_root: Path, target_root: Path) -> tuple[Path, Path, list[str]]:
    errors: list[str] = []
    try:
        source = source_root.resolve(strict=True)
    except Exception as exc:
        return source_root, target_root, [f"Source root unavailable: {exc}"]
    try:
        target = target_root.resolve(strict=True)
    except Exception as exc:
        return source, target_root, [f"Target root unavailable: {exc}"]
    broad = {Path("/").resolve(), Path.home().resolve()}
    if source in broad or target in broad:
        errors.append("Refusing a filesystem root or home-directory release root.")
    if source == target:
        errors.append("Source and target must be distinct.")
    elif source in target.parents or target in source.parents:
        errors.append("Source and target must not be ancestor/descendant paths.")
    if not (source / "quantum_research_lab").is_dir():
        errors.append("Source does not contain quantum_research_lab/.")
    if not (target / "quantum_research_lab").is_dir():
        errors.append("Target does not contain quantum_research_lab/.")
    return source, target, errors


def _source_inventory(
    source_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        freeze_path = _contained(source_root, V41_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot read source V4.1 freeze: {exc}"]
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        return freeze, [], ["V4.1 frozen_files must be an object."]
    if not (
        freeze.get("frozen_file_count") == EXPECTED_V41_FROZEN_FILE_COUNT
        and len(frozen) == EXPECTED_V41_FROZEN_FILE_COUNT
        and _path_fingerprint(frozen) == EXPECTED_V41_FROZEN_PATHS_FINGERPRINT
        and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
    ):
        errors.append("V4.1 source freeze identity, count, or path fingerprint mismatch.")
    policy = freeze.get("successor_policy") or {}
    if not (
        policy.get("accepted_target_states") == ["V4.0", "V4.1"]
        and policy.get("allowed_v40_superseded_files") == [README_PATH, UI_PATH]
        and policy.get("mixed_or_third_state") == "REJECT"
        and _valid_sha256(policy.get("v41_successor_readme_sha256"))
        and _valid_sha256(policy.get("v41_successor_ui_sha256"))
    ):
        errors.append("V4.1 source successor policy is invalid.")
    missing_from_freeze = set(V41_TRANSITION_FILES) - {V41_FREEZE_PATH} - set(frozen)
    if missing_from_freeze:
        errors.append(
            "V4.1 freeze omits transition paths: " + ", ".join(sorted(missing_from_freeze))
        )
    if frozen.get(PARENT_FREEZE_PATH) != PARENT_FREEZE_RAW_SHA256:
        errors.append("V4.1 freeze does not preserve the exact V4.0 freeze file.")

    rows: list[dict[str, Any]] = []
    for relative in V41_TRANSITION_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V41_FREEZE_PATH:
                actual = _freeze_semantic(freeze)
                expected = freeze.get("freeze_contract_sha256")
                integrity = "CANONICAL_JSON_SELF_HASH"
            else:
                actual = _sha256(path)
                expected = frozen.get(relative)
                integrity = "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except Exception as exc:
            actual = None
            expected = frozen.get(relative)
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
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(
    readme_sha: str | None,
    ui_sha: str | None,
    source_freeze: Mapping[str, Any],
) -> str:
    pair = (readme_sha, ui_sha)
    if pair == (PARENT_README_SHA256, PARENT_UI_SHA256):
        return "V4.0"
    policy = source_freeze.get("successor_policy") or {}
    successor = (
        policy.get("v41_successor_readme_sha256"),
        policy.get("v41_successor_ui_sha256"),
    )
    if all(_valid_sha256(value) for value in successor) and pair == successor:
        return "V4.1"
    return "INVALID"


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        source_freeze = _read_json_strict(
            _contained(source_root, V41_FREEZE_PATH, must_exist=True)
        )
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V4.1 source freeze self-hash mismatch")
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
        errors.append(f"Cannot authenticate target V4.0 freeze: {exc}")
    parent_files = parent.get("frozen_files") or {}
    parent_fingerprint = (
        _path_fingerprint(parent_files) if isinstance(parent_files, dict) else None
    )
    parent_identity = bool(
        parent_raw == PARENT_FREEZE_RAW_SHA256
        and parent_semantic == PARENT_FREEZE_SEMANTIC_SHA256
        and parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and isinstance(parent_files, dict)
        and len(parent_files) == PARENT_FROZEN_FILE_COUNT
        and parent_fingerprint == PARENT_FROZEN_PATHS_FINGERPRINT
    )
    if not parent_identity:
        errors.append("Target V4.0 freeze raw/semantic identity or inventory mismatch.")

    immutable: dict[str, bool] = {}
    if isinstance(parent_files, dict):
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
                errors.append(f"Target immutable V4.0 mismatch: {relative}")

    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    state = _successor_state(readme_sha, ui_sha, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown, or an unauthorized third state.")

    for relative in V41_TRANSITION_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")

    partial_paths: list[str] = []
    if state == "V4.0":
        partial_paths = sorted(
            relative
            for relative in V41_ONLY_FILES
            if (target_root / relative).exists() or (target_root / relative).is_symlink()
        )
        if partial_paths:
            errors.append("Partial V4.1 destinations exist on a V4.0 successor surface.")

    exact_overlay = False
    if state == "V4.1":
        exact_overlay = True
        expected = source_freeze.get("frozen_files") or {}
        for relative in V41_TRANSITION_FILES:
            try:
                if relative == V41_FREEZE_PATH:
                    source_value = _freeze_semantic(source_freeze)
                    target_value = _freeze_semantic(
                        _read_json_strict(
                            _contained(target_root, relative, must_exist=True)
                        )
                    )
                else:
                    source_value = expected.get(relative)
                    target_value = _sha256(
                        _contained(target_root, relative, must_exist=True)
                    )
                if not source_value or target_value != source_value:
                    exact_overlay = False
            except Exception:
                exact_overlay = False
        if not exact_overlay:
            errors.append("Target claims V4.1 state but its overlay is incomplete or mismatched.")

    return {
        "errors": list(dict.fromkeys(errors)),
        "exact_overlay": exact_overlay,
        "immutable_v40_file_count": len(immutable),
        "immutable_v40_files_exact": (
            len(immutable) == PARENT_IMMUTABLE_FILE_COUNT and all(immutable.values())
        ),
        "parent_freeze_paths_fingerprint": parent_fingerprint,
        "parent_freeze_raw_sha256": parent_raw,
        "parent_freeze_semantic_sha256": parent_semantic,
        "parent_identity_exact": parent_identity,
        "partial_v41_paths": partial_paths,
        "successor_state": state,
        "valid": not errors,
    }


def preflight(source_root: str | Path, target_root: str | Path) -> dict[str, Any]:
    source, target, errors = _validate_roots(Path(source_root), Path(target_root))
    if errors:
        return {
            "errors": errors,
            "installer_version": INSTALLER_VERSION,
            "overlay_file_count": len(V41_TRANSITION_FILES),
            "source_commitments": {},
            "source_files": [],
            "target": {"valid": False},
            "valid": False,
        }
    freeze, source_rows, source_errors = _source_inventory(source)
    errors.extend(source_errors)
    target_report = authenticate_target(source, target)
    errors.extend(target_report.get("errors") or [])
    return {
        "errors": list(dict.fromkeys(errors)),
        "installer_version": INSTALLER_VERSION,
        "overlay_file_count": len(V41_TRANSITION_FILES),
        "source_commitments": {
            row["path"]: row["actual_sha256"]
            for row in source_rows
            if row.get("valid")
        },
        "source_files": source_rows,
        "source_freeze_sha256": freeze.get("freeze_contract_sha256"),
        "target": target_report,
        "valid": not errors,
    }


def _verification_commands(root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        (
            "v41_unit_tests",
            [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v41"],
        ),
        (
            "v41_release_tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "quantum_research_lab.test_phase3_v41_release",
            ],
        ),
        (
            "v41_release_chain",
            [sys.executable, "-m", "quantum_research_lab.verify_phase3_v41", str(root)],
        ),
        (
            "v41_release_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v41",
                str(root),
                "--contract",
                str(root / V41_FREEZE_PATH),
            ],
        ),
        (
            "v41_streamlit_positive_rerun",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_phase3_v41_ui",
                str(root / "app_v41_offline_harness.py"),
                "--timeout",
                "600",
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
                "quantum_research_lab.test_phase3_v38",
                "quantum_research_lab.test_phase3_v39",
                "quantum_research_lab.test_phase3_v40",
            ],
        ),
    )


def _run_commands(
    commands: tuple[tuple[str, list[str]], ...],
    cwd: Path,
    *,
    force_failure: bool = False,
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for index, (label, command) in enumerate(commands):
        if force_failure and index == 0:
            raise RuntimeError("Injected V4.1 post-install verification fault.")
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
        reports[label] = {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
        if completed.returncode != 0:
            raise RuntimeError(f"Verification failed: {label}")
    return reports


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_copy(source: Path, target: Path, token: str, label: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{label}-{token}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, stat.S_IMODE(source.stat().st_mode))
    try:
        with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        os.chmod(temporary, stat.S_IMODE(source.stat().st_mode))
        os.replace(temporary, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _preimage_entry(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"existed": False, "mode": None, "sha256": None}
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"Unsafe preimage path: {path}")
    return {
        "existed": True,
        "mode": stat.S_IMODE(mode),
        "sha256": _sha256(path),
    }


def _verify_preimages(
    target_root: Path, preimages: Mapping[str, Mapping[str, Any]]
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for relative, expected in preimages.items():
        lexical = target_root / relative
        try:
            actual = _preimage_entry(lexical)
            if actual != expected:
                errors.append(f"Rollback preimage mismatch: {relative}")
        except Exception as exc:
            errors.append(f"Rollback verification {relative}: {exc}")
    return not errors, errors


def _stage_candidate(
    source_root: Path,
    target_root: Path,
    stage_root: Path,
    freeze: Mapping[str, Any],
    commitments: Mapping[str, str],
) -> None:
    frozen = freeze.get("frozen_files") or {}
    transition_payloads = set(V41_TRANSITION_FILES) - {V41_FREEZE_PATH}
    for relative, expected in sorted(frozen.items()):
        origin = source_root if relative in transition_payloads else target_root
        source = _contained(origin, relative, must_exist=True)
        destination = stage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)
        if _sha256(destination) != expected:
            raise RuntimeError(f"Candidate frozen-file mismatch: {relative}")
    freeze_source = _contained(source_root, V41_FREEZE_PATH, must_exist=True)
    freeze_target = stage_root / V41_FREEZE_PATH
    shutil.copy2(freeze_source, freeze_target, follow_symlinks=False)
    staged_freeze = _read_json_strict(freeze_target)
    if _freeze_semantic(staged_freeze) != commitments.get(V41_FREEZE_PATH):
        raise RuntimeError("Candidate V4.1 freeze commitment mismatch.")
    for relative in V41_TRANSITION_FILES:
        staged = _contained(stage_root, relative, must_exist=True)
        actual = (
            _freeze_semantic(_read_json_strict(staged))
            if relative == V41_FREEZE_PATH
            else _sha256(staged)
        )
        if actual != commitments.get(relative):
            raise RuntimeError(f"Candidate overlay commitment mismatch: {relative}")


def _verify_staged_candidate(
    stage_root: Path,
    freeze: Mapping[str, Any],
    commitments: Mapping[str, str],
) -> None:
    """Re-authenticate the private candidate immediately before commit."""

    frozen = freeze.get("frozen_files") or {}
    if len(frozen) != EXPECTED_V41_FROZEN_FILE_COUNT:
        raise RuntimeError("Candidate frozen inventory count changed.")
    for relative, expected in sorted(frozen.items()):
        if _sha256(_contained(stage_root, relative, must_exist=True)) != expected:
            raise RuntimeError(f"Candidate changed after validation: {relative}")
    staged_freeze = _read_json_strict(
        _contained(stage_root, V41_FREEZE_PATH, must_exist=True)
    )
    if (
        _freeze_semantic(staged_freeze) != commitments.get(V41_FREEZE_PATH)
        or staged_freeze.get("freeze_contract_sha256")
        != commitments.get(V41_FREEZE_PATH)
    ):
        raise RuntimeError("Candidate V4.1 freeze changed after validation.")


def _acquire_lock(target_root: Path, token: str) -> tuple[bool, str | None]:
    lock = target_root / LOCK_NAME
    payload = {
        "installer": INSTALLER_VERSION,
        "pid": os.getpid(),
        "token": token,
    }
    try:
        _write_json_exclusive(lock, payload)
    except FileExistsError:
        return False, f"Install lock already exists: {lock}"
    except Exception as exc:
        return False, f"Cannot acquire install lock: {exc}"
    return True, None


def _release_owned_lock(target_root: Path, token: str) -> str | None:
    lock = target_root / LOCK_NAME
    try:
        mode = lock.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            return "Owned lock path was replaced by an unsafe filesystem object."
        payload = _read_json_strict(lock)
        if payload.get("token") != token or payload.get("installer") != INSTALLER_VERSION:
            return "Owned lock token changed; refusing to remove a foreign lock."
        lock.unlink()
        _fsync_directory(target_root)
        return None
    except FileNotFoundError:
        return "Owned install lock disappeared before release."
    except Exception as exc:
        return f"Cannot release owned install lock: {exc}"


def install(
    source_root: str | Path,
    target_root: str | Path,
    *,
    apply: bool = False,
    _test_fail_after: int | None = None,
    _test_force_apply: bool = False,
    _test_fail_verification: bool = False,
    _test_after_stage: Callable[[Path, Path], None] | None = None,
    _test_after_preimages: Callable[[Path, Path], None] | None = None,
    _test_skip_verification: bool = False,
) -> dict[str, Any]:
    """Authenticate and optionally apply the V4.0 -> V4.1 transition."""

    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {
            "applied": False,
            "errors": root_errors,
            "no_op": False,
            "valid": False,
        }
    if not apply:
        return {
            **preflight(source, target),
            "applied": False,
            "no_op": False,
        }

    token = uuid4().hex
    lock_owned, lock_error = _acquire_lock(target, token)
    if not lock_owned:
        return {
            "applied": False,
            "errors": [str(lock_error)],
            "no_op": False,
            "valid": False,
        }

    result: dict[str, Any] = {}
    stage_root: Path | None = None
    backup_root: Path | None = None
    touched: list[str] = []
    preimages: dict[str, dict[str, Any]] = {}
    predecessor_state = "V4.0"
    try:
        report = preflight(source, target)
        result = report
        if not report["valid"]:
            result = {**report, "applied": False, "no_op": False}
        elif (
            not _test_force_apply
            and report["target"].get("successor_state") == "V4.1"
            and report["target"].get("exact_overlay")
        ):
            # Exact reapplication is the only admitted NO_OP state.
            result = {
                **report,
                "applied": False,
                "no_op": True,
                "postinstall": report["target"],
                "valid": True,
            }
        else:
            predecessor_state = str(report["target"].get("successor_state"))
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            short = token[:12]
            stage_root = target / f".quantum-lab-v41-stage-{short}"
            backup_root = target / f".quantum-lab-v41-backup-{timestamp}-{short}"
            stage_root.mkdir(mode=0o700)
            backup_root.mkdir(mode=0o700)
            _fsync_directory(target)

            freeze = _read_json_strict(
                _contained(source, V41_FREEZE_PATH, must_exist=True)
            )
            commitments = report["source_commitments"]
            _stage_candidate(source, target, stage_root, freeze, commitments)
            if _test_after_stage is not None:
                _test_after_stage(source, stage_root)

            # A later source mutation cannot influence the staged candidate and
            # is nevertheless rejected to preserve the preflight audit trail.
            for relative, expected in commitments.items():
                source_path = _contained(source, relative, must_exist=True)
                actual = (
                    _freeze_semantic(_read_json_strict(source_path))
                    if relative == V41_FREEZE_PATH
                    else _sha256(source_path)
                )
                if actual != expected:
                    raise RuntimeError(f"Source changed after staging: {relative}")

            target_recheck = authenticate_target(source, target)
            if not target_recheck.get("valid"):
                raise RuntimeError(
                    "Target changed after preflight: "
                    + "; ".join(target_recheck.get("errors") or [])
                )

            candidate_verification: dict[str, Any] = {}
            if not _test_skip_verification:
                candidate_verification = _run_commands(
                    _verification_commands(stage_root), stage_root
                )
            _verify_staged_candidate(stage_root, freeze, commitments)

            for relative in V41_TRANSITION_FILES:
                destination = _contained(target, relative, must_exist=False)
                preimages[relative] = _preimage_entry(destination)
                if preimages[relative]["existed"]:
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup, follow_symlinks=False)
                    if _sha256(backup) != preimages[relative]["sha256"]:
                        raise RuntimeError(f"Backup preimage mismatch: {relative}")

            if _test_after_preimages is not None:
                _test_after_preimages(target, backup_root)
            for relative, expected in preimages.items():
                if _preimage_entry(target / relative) != expected:
                    raise RuntimeError(f"Target changed after preimage capture: {relative}")

            manifest_core = {
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "installer_version": INSTALLER_VERSION,
                "predecessor_state": predecessor_state,
                "preimages": preimages,
                "source_freeze_sha256": report.get("source_freeze_sha256"),
                "target_root": str(target),
                "token": token,
            }
            _write_json_exclusive(
                backup_root / "PREIMAGE_MANIFEST.json",
                {
                    **manifest_core,
                    "manifest_sha256": _canonical_json_sha256(manifest_core),
                },
            )

            try:
                for relative in V41_TRANSITION_FILES:
                    # Register intent before replace so even an fsync failure
                    # after os.replace is covered by rollback.
                    touched.append(relative)
                    _atomic_copy(
                        _contained(stage_root, relative, must_exist=True),
                        _contained(target, relative, must_exist=False),
                        short,
                        "v41",
                    )
                    if _test_fail_after is not None and len(touched) == _test_fail_after:
                        raise RuntimeError("Injected V4.1 partial-commit fault.")
                if tuple(touched[-2:]) != (README_PATH, UI_PATH):
                    raise RuntimeError("README/UI were not committed penultimate/last.")

                postinstall = authenticate_target(source, target)
                if not (
                    postinstall.get("valid")
                    and postinstall.get("exact_overlay")
                    and postinstall.get("successor_state") == "V4.1"
                ):
                    raise RuntimeError("Installed overlay failed exact V4.1 authentication.")
                verification: dict[str, Any] = {}
                if not _test_skip_verification:
                    verification = _run_commands(
                        _verification_commands(target),
                        target,
                        force_failure=_test_fail_verification,
                    )
                result = {
                    **report,
                    "applied": True,
                    "applied_files": touched,
                    "backup_root": str(backup_root),
                    "candidate_verification": candidate_verification,
                    "no_op": False,
                    "postinstall": postinstall,
                    "readme_committed_penultimate": touched[-2] == README_PATH,
                    "rolled_back": False,
                    "ui_committed_last": touched[-1] == UI_PATH,
                    "valid": True,
                    "verification": verification,
                }
            except Exception as exc:
                rollback_errors: list[str] = []
                for relative in reversed(touched):
                    expected = preimages[relative]
                    destination = target / relative
                    try:
                        if expected["existed"]:
                            backup = _contained(backup_root, relative, must_exist=True)
                            if _sha256(backup) != expected["sha256"]:
                                raise RuntimeError("backup hash changed before rollback")
                            _atomic_copy(backup, destination, short, "rollback")
                            os.chmod(destination, int(expected["mode"]))
                        elif destination.exists() or destination.is_symlink():
                            mode = destination.lstat().st_mode
                            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                                raise RuntimeError("unsafe new destination during rollback")
                            destination.unlink()
                            _fsync_directory(destination.parent)
                    except Exception as rollback_exc:
                        rollback_errors.append(f"{relative}: {rollback_exc}")
                preimages_exact, preimage_errors = _verify_preimages(target, preimages)
                rollback_errors.extend(preimage_errors)
                rollback_state = authenticate_target(source, target)
                rolled_back = bool(
                    not rollback_errors
                    and preimages_exact
                    and rollback_state.get("valid")
                    and rollback_state.get("successor_state") == predecessor_state
                )
                result = {
                    **report,
                    "applied": False,
                    "applied_files_before_failure": touched,
                    "backup_root": str(backup_root),
                    "error": str(exc),
                    "no_op": False,
                    "preimages_restored": preimages_exact,
                    "rollback": rollback_state,
                    "rollback_errors": rollback_errors,
                    "rolled_back": rolled_back,
                    "valid": False,
                }
    except Exception as exc:
        result = {
            **result,
            "applied": False,
            "backup_root": str(backup_root) if backup_root else None,
            "error": str(exc),
            "no_op": False,
            "rolled_back": False,
            "valid": False,
        }
    finally:
        if stage_root is not None and stage_root.exists():
            shutil.rmtree(stage_root)
            _fsync_directory(target)
        release_error = _release_owned_lock(target, token)
        if release_error is not None:
            result["lock_release_error"] = release_error
            result["valid"] = False
    return result


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely install Quantum Lab V4.1.")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = install(args.source, args.target, apply=args.apply)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    success = report.get("valid") and (
        not args.apply or report.get("applied") or report.get("no_op")
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_V41_FROZEN_FILE_COUNT",
    "EXPECTED_V41_FROZEN_PATHS_FINGERPRINT",
    "INSTALLER_VERSION",
    "LOCK_NAME",
    "V41_ONLY_FILES",
    "V41_TRANSITION_FILES",
    "authenticate_target",
    "install",
    "preflight",
]
