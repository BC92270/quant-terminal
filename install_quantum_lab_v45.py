"""Transactional fail-closed installer for the Quantum Lab V4.5 overlay.

Only an exact V4.4 target or an exact V4.5 no-op state is accepted. The
installer itself performs no network, credential, provider-client or hardware
operation. Candidate checks authenticate already sealed zero-job evidence.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4


INSTALLER_VERSION = "QUANTUM LAB V4.5 TRANSACTIONAL INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v45-install.lock"
PARENT_LOCK_NAME = ".quantum-lab-v44-install.lock"
RESIDUAL_LOCK_NAMES = (
    PARENT_LOCK_NAME,
    ".quantum-lab-v43-install.lock",
    ".quantum-lab-v42-install.lock",
)
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_4.json"
V45_FREEZE_PATH = "FREEZE_CONTRACT_V4_5.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
PARENT_FREEZE_RAW_SHA256 = "f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13"
PARENT_FREEZE_SEMANTIC_SHA256 = "e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3"
PARENT_FROZEN_FILE_COUNT = 211
PARENT_IMMUTABLE_FILE_COUNT = 209
PARENT_FROZEN_PATHS_FINGERPRINT = "eb4fda2c2b862fa279a7f0d60f0a2694e50f9c63bf89f60de9d0af52638c0516"
EXPECTED_V45_FROZEN_FILE_COUNT = 229
EXPECTED_V45_FROZEN_PATHS_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_V45_OVERLAY_ORDER_SHA256 = "d1c59d3e9a83675d67cb62f6b20aa9ca3fa3494a1376fadf8aa8e0a873d8073f"

# Supporting evidence first, human surface penultimate, integration surface last.
V45_TRANSITION_FILES = (
    V45_FREEZE_PATH,
    "DEPLOY_V4_5.md",
    "app_v45_offline_harness.py",
    "install_quantum_lab_v45.py",
    "build_quantum_lab_v45_release.py",
    "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json",
    "quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_5_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py",
    "quantum_research_lab/phase3_v45_width_proof_checker.py",
    "quantum_research_lab/phase3_v45_validation.py",
    "quantum_research_lab/phase3_v45_ui.py",
    "quantum_research_lab/test_phase3_v45.py",
    "quantum_research_lab/test_phase3_v45_release.py",
    "quantum_research_lab/verify_freeze_contract_v45.py",
    "quantum_research_lab/verify_phase3_v45.py",
    "quantum_research_lab/verify_phase3_v45_ui.py",
    README_PATH,
    UI_PATH,
)
V45_ONLY_FILES = frozenset(V45_TRANSITION_FILES) - {README_PATH, UI_PATH}
V45_TRANSITION_ORDER_SHA256 = hashlib.sha256(
    json.dumps(list(V45_TRANSITION_FILES), separators=(",", ":")).encode("utf-8")
).hexdigest()
if V45_TRANSITION_ORDER_SHA256 != EXPECTED_V45_OVERLAY_ORDER_SHA256:
    raise RuntimeError("V4.5 ordered overlay inventory drifted.")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _path_fingerprint(paths: Mapping[str, Any] | Sequence[str] | set[str]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


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
        lexical.resolve(strict=True).relative_to(release_root)
    elif lexical.exists() or lexical.is_symlink():
        mode = lexical.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError(f"Unsafe existing destination: {relative}")
    return lexical


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


def _source_inventory(source_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        freeze_path = _contained(source_root, V45_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot read source V4.5 freeze: {exc}"]
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        return freeze, [], ["V4.5 frozen_files must be an object."]
    if not (
        freeze.get("frozen_file_count") == EXPECTED_V45_FROZEN_FILE_COUNT
        and len(frozen) == EXPECTED_V45_FROZEN_FILE_COUNT
        and _path_fingerprint(frozen) == EXPECTED_V45_FROZEN_PATHS_FINGERPRINT
        and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
    ):
        errors.append("V4.5 source freeze identity, count or path fingerprint mismatch.")
    policy = freeze.get("successor_policy") or {}
    if not (
        policy.get("accepted_target_states") == ["V4.4", "V4.5"]
        and policy.get("allowed_v44_superseded_files") == [README_PATH, UI_PATH]
        and policy.get("mixed_or_third_state") == "REJECT"
        and _valid_sha(policy.get("v45_successor_readme_sha256"))
        and _valid_sha(policy.get("v45_successor_ui_sha256"))
    ):
        errors.append("V4.5 source successor policy is invalid.")
    missing = set(V45_TRANSITION_FILES) - {V45_FREEZE_PATH} - set(frozen)
    if missing:
        errors.append("V4.5 freeze omits transition paths: " + ", ".join(sorted(missing)))
    if frozen.get(PARENT_FREEZE_PATH) != PARENT_FREEZE_RAW_SHA256:
        errors.append("V4.5 freeze does not preserve the exact V4.4 freeze file.")
    rows: list[dict[str, Any]] = []
    for relative in V45_TRANSITION_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V45_FREEZE_PATH:
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
        rows.append({"path": relative, "actual_sha256": actual, "expected_sha256": expected, "integrity": integrity, "valid": valid})
        if not valid:
            errors.append(f"Source overlay mismatch: {relative}")
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(readme_sha: str | None, ui_sha: str | None, parent: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    parent_policy = parent.get("successor_policy") or {}
    source_policy = source.get("successor_policy") or {}
    pair = (readme_sha, ui_sha)
    if pair == (parent_policy.get("v44_successor_readme_sha256"), parent_policy.get("v44_successor_ui_sha256")):
        return "V4.4"
    if pair == (source_policy.get("v45_successor_readme_sha256"), source_policy.get("v45_successor_ui_sha256")):
        return "V4.5"
    return "INVALID"


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        source_freeze = _read_json_strict(_contained(source_root, V45_FREEZE_PATH, must_exist=True))
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V4.5 source freeze self-hash mismatch")
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
        errors.append(f"Cannot authenticate target V4.4 freeze: {exc}")
    parent_files = parent.get("frozen_files") or {}
    parent_fingerprint = _path_fingerprint(parent_files) if isinstance(parent_files, dict) else None
    parent_identity = bool(
        parent_raw == PARENT_FREEZE_RAW_SHA256
        and parent_semantic == parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and isinstance(parent_files, dict) and len(parent_files) == PARENT_FROZEN_FILE_COUNT
        and parent_fingerprint == PARENT_FROZEN_PATHS_FINGERPRINT
    )
    if not parent_identity:
        errors.append("Target V4.4 freeze raw/semantic identity or inventory mismatch.")
    immutable: dict[str, bool] = {}
    if isinstance(parent_files, dict):
        for relative in sorted(set(parent_files) - {README_PATH, UI_PATH}):
            try:
                immutable[relative] = _sha256(_contained(target_root, relative, must_exist=True)) == parent_files.get(relative)
            except Exception as exc:
                immutable[relative] = False
                errors.append(f"Target parent {relative}: {exc}")
            if not immutable[relative]:
                errors.append(f"Target immutable V4.4 mismatch: {relative}")
    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    state = _successor_state(readme_sha, ui_sha, parent, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown or an unauthorized third state.")
    for relative in V45_TRANSITION_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")
    partial: list[str] = []
    if state == "V4.4":
        partial = sorted(relative for relative in V45_ONLY_FILES if (target_root / relative).exists() or (target_root / relative).is_symlink())
        if partial:
            errors.append("Partial V4.5 destinations exist on a V4.4 successor surface.")
    exact_overlay = False
    if state == "V4.5":
        exact_overlay = True
        expected = source_freeze.get("frozen_files") or {}
        for relative in V45_TRANSITION_FILES:
            try:
                if relative == V45_FREEZE_PATH:
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
            errors.append("Target claims V4.5 state but its overlay is incomplete or mismatched.")
    return {
        "errors": list(dict.fromkeys(errors)),
        "exact_overlay": exact_overlay,
        "immutable_v44_file_count": len(immutable),
        "immutable_v44_files_exact": len(immutable) == PARENT_IMMUTABLE_FILE_COUNT and all(immutable.values()),
        "parent_freeze_paths_fingerprint": parent_fingerprint,
        "parent_freeze_raw_sha256": parent_raw,
        "parent_freeze_semantic_sha256": parent_semantic,
        "parent_identity_exact": parent_identity,
        "partial_v45_paths": partial,
        "successor_state": state,
        "valid": not errors,
    }


def preflight(source_root: str | Path, target_root: str | Path) -> dict[str, Any]:
    source, target, errors = _validate_roots(Path(source_root), Path(target_root))
    if errors:
        return {
            "errors": errors,
            "installer_version": INSTALLER_VERSION,
            "overlay_file_count": len(V45_TRANSITION_FILES),
            "overlay_order_sha256": V45_TRANSITION_ORDER_SHA256,
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
        "overlay_file_count": len(V45_TRANSITION_FILES),
        "overlay_order_sha256": V45_TRANSITION_ORDER_SHA256,
        "source_commitments": {row["path"]: row["actual_sha256"] for row in source_rows if row.get("valid")},
        "source_files": source_rows,
        "source_freeze_sha256": freeze.get("freeze_contract_sha256"),
        "target": target_report,
        "valid": not errors,
    }


def _verification_commands(root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        ("v45_unit_tests", [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v45"]),
        ("v45_release_identity", [sys.executable, "-m", "quantum_research_lab.verify_phase3_v45", str(root), "--identity-only"]),
        ("v45_release_freeze", [sys.executable, "-m", "quantum_research_lab.verify_freeze_contract_v45", str(root)]),
        ("v45_streamlit_positive_rerun", [sys.executable, "-m", "quantum_research_lab.verify_phase3_v45_ui", str(root / "app_v45_offline_harness.py"), "--timeout", "600"]),
        ("historical_scientific_unit_regression", [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_gate_compiler", "quantum_research_lab.test_phase3_algorithmic_contract", "quantum_research_lab.test_phase3_v34", "quantum_research_lab.test_phase3_v35", "quantum_research_lab.test_phase3_v36", "quantum_research_lab.test_phase3_v37", "quantum_research_lab.test_phase3_v38", "quantum_research_lab.test_phase3_v39", "quantum_research_lab.test_phase3_v40", "quantum_research_lab.test_phase3_v41", "quantum_research_lab.test_phase3_v42", "quantum_research_lab.test_phase3_v43", "quantum_research_lab.test_phase3_v44"]),
    )


def _python_subprocess_environment() -> dict[str, str]:
    """Return an environment that cannot inherit a source-overlay PYTHONPATH."""

    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run_commands(commands: Sequence[tuple[str, list[str]]], cwd: Path, *, force_failure: bool = False) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for index, (label, command) in enumerate(commands):
        if force_failure and index == 0:
            raise RuntimeError("Injected V4.5 post-install verification fault.")
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=_python_subprocess_environment(),
            capture_output=True,
            text=True,
            timeout=1200,
            check=False,
        )
        reports[label] = {"command": command, "returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
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
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


def _preimage(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"existed": False, "mode": None, "sha256": None}
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"Unsafe preimage path: {path}")
    return {"existed": True, "mode": stat.S_IMODE(mode), "sha256": _sha256(path)}


def _verify_release_identity_in_root(root: Path, label: str) -> dict[str, Any]:
    """Run the authenticated V4.5 verifier from the candidate root itself.

    The deployment overlay intentionally contains only the 20 transition files.
    Importing its verifier in the installer process would turn that partial
    namespace into the active package and hide predecessor modules that live in
    the staged or installed root.  A clean subprocess binds imports to the
    complete candidate instead.
    """

    command = [
        sys.executable,
        "-m",
        "quantum_research_lab.verify_phase3_v45",
        str(root),
        "--identity-only",
    ]
    completed = subprocess.run(
        command,
        cwd=root,
        env=_python_subprocess_environment(),
        capture_output=True,
        text=True,
        timeout=1200,
        check=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip()[-1200:]
        raise RuntimeError(
            f"{label} release identity failed with return code "
            f"{completed.returncode}: {diagnostic}"
        )
    try:
        report = json.loads(completed.stdout)
    except Exception as exc:
        raise RuntimeError(f"{label} release identity emitted invalid JSON: {exc}") from exc
    if not isinstance(report, dict) or report.get("valid") is not True:
        failed = report.get("failed_checks") if isinstance(report, dict) else None
        raise RuntimeError(f"{label} release identity failed: {failed}")
    return report


def _verify_preimages(target_root: Path, preimages: Mapping[str, Mapping[str, Any]]) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for relative, expected in preimages.items():
        try:
            if _preimage(target_root / relative) != expected:
                errors.append(f"Rollback preimage mismatch: {relative}")
        except Exception as exc:
            errors.append(f"Rollback verification {relative}: {exc}")
    return not errors, errors


def _stage_candidate(
    source_root: Path,
    target_root: Path,
    stage_root: Path,
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    frozen = freeze.get("frozen_files") or {}
    transition_payloads = set(V45_TRANSITION_FILES) - {V45_FREEZE_PATH}
    for relative, expected in sorted(frozen.items()):
        origin_root = source_root if relative in transition_payloads else target_root
        origin = _contained(origin_root, relative, must_exist=True)
        destination = stage_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, destination, follow_symlinks=False)
        if _sha256(destination) != expected:
            raise RuntimeError(f"Candidate frozen-file mismatch: {relative}")
    freeze_source = _contained(source_root, V45_FREEZE_PATH, must_exist=True)
    shutil.copy2(freeze_source, stage_root / V45_FREEZE_PATH, follow_symlinks=False)
    release_identity = _verify_release_identity_in_root(stage_root, "Candidate-stage")
    validations = _run_commands(_verification_commands(stage_root), stage_root)
    return {"release_identity": release_identity, "validations": validations}


def _rehash_source(source_root: Path, commitments: Mapping[str, str]) -> None:
    freeze = _read_json_strict(_contained(source_root, V45_FREEZE_PATH, must_exist=True))
    for relative, expected in commitments.items():
        if relative == V45_FREEZE_PATH:
            actual = _freeze_semantic(freeze)
        else:
            actual = _sha256(_contained(source_root, relative, must_exist=True))
        if actual != expected:
            raise RuntimeError(f"Source changed after preflight: {relative}")


def _rehash_transition_root(root: Path, commitments: Mapping[str, str], label: str) -> None:
    freeze = _read_json_strict(_contained(root, V45_FREEZE_PATH, must_exist=True))
    for relative in V45_TRANSITION_FILES:
        expected = commitments.get(relative)
        if not expected:
            raise RuntimeError(f"{label} commitment missing: {relative}")
        if relative == V45_FREEZE_PATH:
            actual = _freeze_semantic(freeze)
        else:
            actual = _sha256(_contained(root, relative, must_exist=True))
        if actual != expected:
            raise RuntimeError(f"{label} transition mismatch: {relative}")


def _owned_lock(target_root: Path, token: str) -> Path:
    lock = target_root / LOCK_NAME
    _write_json_exclusive(lock, {"installer": INSTALLER_VERSION, "pid": os.getpid(), "token": token, "utc": datetime.now(timezone.utc).isoformat()})
    return lock


def _reject_parent_lock(target_root: Path) -> None:
    present = [name for name in RESIDUAL_LOCK_NAMES if (target_root / name).exists() or (target_root / name).is_symlink()]
    if present:
        raise RuntimeError(
            "Residual predecessor installer lock rejected; inspect before V4.5 deployment: "
            + ", ".join(present)
        )


def _release_owned_lock(lock: Path, token: str) -> None:
    if not lock.exists() or lock.is_symlink():
        raise RuntimeError("Install lock disappeared or became unsafe.")
    payload = _read_json_strict(lock)
    if payload.get("token") != token:
        raise RuntimeError("Refusing to release a lock owned by another token.")
    lock.unlink()
    _fsync_directory(lock.parent)


def _write_audit_manifest(
    path: Path,
    payload: Mapping[str, Any],
    *,
    hash_field: str,
) -> dict[str, Any]:
    materialized = dict(payload)
    materialized[hash_field] = _canonical_json_sha256(payload)
    _write_json_exclusive(path, materialized)
    return materialized


def _rollback(
    target_root: Path,
    backup_root: Path,
    preimages: Mapping[str, Mapping[str, Any]],
    installed_states: Mapping[str, Mapping[str, Any]],
    touched_paths: Sequence[str],
    token: str,
) -> dict[str, Any]:
    errors: list[str] = []
    restored: list[str] = []
    external_mutations: list[str] = []
    for relative in reversed(tuple(touched_paths)):
        target = target_root / relative
        expected = preimages[relative]
        try:
            current = _preimage(target)
            installed = installed_states.get(relative)
            if installed is None or current != installed:
                external_mutations.append(relative)
                raise RuntimeError(
                    f"External mutation detected after V4.5 write; refusing rollback overwrite: {relative}"
                )
            if expected["existed"]:
                _atomic_copy(backup_root / relative, target, token, "rollback")
                os.chmod(target, int(expected["mode"]))
            elif target.exists() or target.is_symlink():
                if target.is_symlink() or not target.is_file():
                    raise RuntimeError(f"Unsafe rollback deletion target: {relative}")
                target.unlink()
                _fsync_directory(target.parent)
            restored.append(relative)
        except Exception as exc:
            errors.append(f"Rollback failed for {relative}: {exc}")
    valid, verification_errors = _verify_preimages(target_root, preimages)
    errors.extend(verification_errors)
    return {
        "errors": list(dict.fromkeys(errors)),
        "external_mutations": external_mutations,
        "preimages_restored": valid and not errors,
        "restored_paths": restored,
        "touched_paths": list(touched_paths),
    }


def apply_overlay(
    source_root: str | Path,
    target_root: str | Path,
    *,
    force_post_failure: bool = False,
    force_commit_failure_after: int | None = None,
) -> dict[str, Any]:
    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {"applied": False, "errors": root_errors, "status": "PREFLIGHT_REJECTED", "valid": False}
    if force_commit_failure_after is not None and not 1 <= force_commit_failure_after <= len(V45_TRANSITION_FILES):
        return {
            "applied": False,
            "errors": [
                "force_commit_failure_after must identify one of the "
                f"{len(V45_TRANSITION_FILES)} ordered overlay writes."
            ],
            "status": "TEST_FAULT_ARGUMENT_REJECTED",
            "valid": False,
        }

    token = uuid4().hex
    lock: Path | None = None
    backup_root = target / f".quantum-lab-v45-backup-{token}"
    stage_root = target / f".quantum-lab-v45-stage-{token}"
    report: dict[str, Any] = {}
    preimages: dict[str, dict[str, Any]] = {}
    installed_states: dict[str, dict[str, Any]] = {}
    touched_paths: list[str] = []
    rollback_report: dict[str, Any] | None = None
    stage_checks: dict[str, Any] = {}
    post_checks: dict[str, Any] = {}
    backup_manifest: dict[str, Any] = {}
    intent_manifest: dict[str, Any] = {}
    backup_created = False
    status = "LOCK_ACQUISITION_FAILED"
    valid = False
    errors: list[str] = []
    try:
        lock = _owned_lock(target, token)
        _reject_parent_lock(target)
        report = preflight(source, target)
        if not report.get("valid"):
            raise RuntimeError("Preflight rejected: " + "; ".join(report.get("errors") or []))
        if (
            (report.get("target") or {}).get("successor_state") == "V4.5"
            and (report.get("target") or {}).get("exact_overlay") is True
        ):
            status = "NO_OP_ALREADY_EXACT_V4_5"
            valid = True
        else:
            status = "PREPARING_TRANSACTION"
            backup_root.mkdir(mode=0o700)
            backup_created = True
            stage_root.mkdir(mode=0o700)
            for relative in V45_TRANSITION_FILES:
                target_path = target / relative
                preimages[relative] = _preimage(target_path)
                if preimages[relative]["existed"]:
                    backup = backup_root / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target_path, backup, follow_symlinks=False)
                    if _sha256(backup) != preimages[relative]["sha256"]:
                        raise RuntimeError(f"Backup hash mismatch: {relative}")
            backup_manifest = _write_audit_manifest(
                backup_root / "PREIMAGE_MANIFEST.json",
                {
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "format": "QUANTUM LAB V4.5 PREIMAGE MANIFEST · V1",
                    "installer": INSTALLER_VERSION,
                    "preimages": preimages,
                    "target_root": str(target),
                    "token": token,
                },
                hash_field="preimage_manifest_sha256",
            )
            freeze = _read_json_strict(_contained(source, V45_FREEZE_PATH, must_exist=True))
            stage_checks = _stage_candidate(source, target, stage_root, freeze)
            commitments = report.get("source_commitments") or {}
            _rehash_source(source, commitments)
            _rehash_transition_root(stage_root, commitments, "Candidate-stage")
            intent_manifest = _write_audit_manifest(
                backup_root / "INSTALL_INTENT.json",
                {
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "format": "QUANTUM LAB V4.5 INSTALL INTENT · V1",
                    "installer": INSTALLER_VERSION,
                    "ordered_transition_paths": list(V45_TRANSITION_FILES),
                    "ordered_transition_paths_sha256": V45_TRANSITION_ORDER_SHA256,
                    "preimage_manifest_sha256": backup_manifest.get("preimage_manifest_sha256"),
                    "source_commitments": commitments,
                    "stage_release_valid": bool((stage_checks.get("release_identity") or {}).get("valid")),
                    "target_root": str(target),
                    "token": token,
                },
                hash_field="install_intent_sha256",
            )
            status = "COMMITTING"
            for index, relative in enumerate(V45_TRANSITION_FILES, start=1):
                target_path = target / relative
                if _preimage(target_path) != preimages[relative]:
                    raise RuntimeError(f"Target changed after locked snapshot: {relative}")
                _atomic_copy(
                    _contained(stage_root, relative, must_exist=True),
                    target_path,
                    token,
                    "commit",
                )
                touched_paths.append(relative)
                installed_states[relative] = _preimage(target_path)
                if force_commit_failure_after == index:
                    raise RuntimeError(f"Injected V4.5 commit fault after ordered write {index}.")
            _rehash_transition_root(target, commitments, "Installed")
            _verify_release_identity_in_root(target, "Installed")
            post_checks = _run_commands(
                _verification_commands(target),
                target,
                force_failure=force_post_failure,
            )
            status = "APPLIED_AND_VERIFIED"
            valid = True
    except Exception as exc:
        errors = [str(exc)]
        status = (
            "LOCK_ACQUISITION_FAILED"
            if lock is None
            else "ROLLED_BACK_AFTER_FAILURE" if touched_paths else "ABORTED_BEFORE_COMMIT"
        )
        valid = False
        if touched_paths:
            rollback_report = _rollback(
                target,
                backup_root,
                preimages,
                installed_states,
                touched_paths,
                token,
            )
            if not rollback_report.get("preimages_restored"):
                status = "ROLLBACK_INCOMPLETE"
                errors.extend(rollback_report.get("errors") or [])
            else:
                predecessor = authenticate_target(source, target)
                rollback_report["predecessor_reauthenticated"] = bool(
                    predecessor.get("valid") is True
                    and predecessor.get("successor_state") == "V4.4"
                )
                if rollback_report["predecessor_reauthenticated"] is not True:
                    status = "ROLLBACK_INCOMPLETE"
                    errors.extend(predecessor.get("errors") or ["Restored V4.4 predecessor did not reauthenticate."])
    finally:
        if stage_root.exists() and stage_root.is_dir() and stage_root.parent == target:
            shutil.rmtree(stage_root)
        if lock is not None and lock.exists():
            try:
                _release_owned_lock(lock, token)
            except Exception as exc:
                errors = list(locals().get("errors", [])) + [str(exc)]
                valid = False
                status = "LOCK_RELEASE_FAILED"
    return {
        "applied": valid and status == "APPLIED_AND_VERIFIED",
        "backup_preserved": str(backup_root) if backup_created else None,
        "backup_manifest_sha256": backup_manifest.get("preimage_manifest_sha256"),
        "errors": list(dict.fromkeys(errors)),
        "install_intent_sha256": intent_manifest.get("install_intent_sha256"),
        "installer_version": INSTALLER_VERSION,
        "overlay_file_count": len(V45_TRANSITION_FILES),
        "overlay_order_sha256": V45_TRANSITION_ORDER_SHA256,
        "post_checks": post_checks,
        "preflight": report,
        "rollback": rollback_report,
        "stage_checks": stage_checks,
        "status": status,
        "touched_paths": touched_paths,
        "valid": valid,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = preflight(args.source, args.target) if args.preflight else apply_overlay(args.source, args.target)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_V45_FROZEN_FILE_COUNT",
    "EXPECTED_V45_OVERLAY_ORDER_SHA256",
    "EXPECTED_V45_FROZEN_PATHS_FINGERPRINT",
    "INSTALLER_VERSION",
    "PARENT_FREEZE_RAW_SHA256",
    "PARENT_FREEZE_SEMANTIC_SHA256",
    "PARENT_FROZEN_FILE_COUNT",
    "PARENT_FROZEN_PATHS_FINGERPRINT",
    "V45_TRANSITION_FILES",
    "V45_TRANSITION_ORDER_SHA256",
    "apply_overlay",
    "authenticate_target",
    "preflight",
]
