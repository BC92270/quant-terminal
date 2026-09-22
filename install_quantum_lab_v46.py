"""Transactional fail-closed installer for the Quantum Lab V4.6 overlay.

Only an exact authenticated V4.5 target or an exact V4.6 no-op state is
accepted. The installer performs no provider, credential, network, simulator
or hardware operation. It validates a complete candidate stage before commit,
rehashes the source immediately before commit, and rolls back from exact
preimages on any failure.
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
import tempfile
from typing import Any, Mapping, Sequence
from uuid import uuid4


INSTALLER_VERSION = "QUANTUM LAB V4.6 TRANSACTIONAL INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v46-install.lock"
RESIDUAL_LOCK_NAMES = (
    ".quantum-lab-v45-install.lock",
    ".quantum-lab-v44-install.lock",
    ".quantum-lab-v43-install.lock",
)
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_5.json"
V46_FREEZE_PATH = "FREEZE_CONTRACT_V4_6.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
PARENT_FREEZE_RAW_SHA256 = "1f20e7c3c82c9441132d530a9204b0db19ad0d31c43b867cc029394bda276cd7"
PARENT_FREEZE_SEMANTIC_SHA256 = "05197d460b076275a3c7712aa895959d9d1916b09e1999750e1e36cc0c27a218"
PARENT_FROZEN_FILE_COUNT = 229
PARENT_IMMUTABLE_FILE_COUNT = 227
PARENT_FROZEN_PATHS_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_V46_FROZEN_FILE_COUNT = 249
EXPECTED_V46_FROZEN_PATHS_FINGERPRINT = "6be1cbbc2d414298b4907878eac9e3924152679dfeb20e71079f409a0e22ccac"
EXPECTED_V46_OVERLAY_ORDER_SHA256 = "49cdd7ed81c6b71bb088cdbb259f7c4a4270cb6da525d68efb506d261e706294"

# Evidence first, human surface penultimate, integration surface last.
V46_TRANSITION_FILES = (
    V46_FREEZE_PATH,
    "DEPLOY_V4_6.md",
    "app_v46_offline_harness.py",
    "install_quantum_lab_v46.py",
    "build_quantum_lab_v46_release.py",
    "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json",
    "quantum_research_lab/PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json",
    "quantum_research_lab/PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_6_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v46_reference_builder.py",
    "quantum_research_lab/phase3_v46_full_stream_routing.py",
    "quantum_research_lab/phase3_v46_independent_checker.py",
    "quantum_research_lab/phase3_v46_validation.py",
    "quantum_research_lab/phase3_v46_ui.py",
    "quantum_research_lab/test_phase3_v46.py",
    "quantum_research_lab/test_phase3_v46_release.py",
    "quantum_research_lab/verify_freeze_contract_v46.py",
    "quantum_research_lab/verify_phase3_v46.py",
    "quantum_research_lab/verify_phase3_v46_ui.py",
    README_PATH,
    UI_PATH,
)
V46_ONLY_FILES = frozenset(V46_TRANSITION_FILES) - {README_PATH, UI_PATH}
V46_TRANSITION_ORDER_SHA256 = hashlib.sha256(
    json.dumps(list(V46_TRANSITION_FILES), separators=(",", ":")).encode("utf-8")
).hexdigest()
if V46_TRANSITION_ORDER_SHA256 != EXPECTED_V46_OVERLAY_ORDER_SHA256:
    raise RuntimeError("V4.6 ordered overlay inventory drifted.")


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


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"Non-finite JSON number: {token}")),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return _canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def _path_fingerprint(paths: Mapping[str, Any] | Sequence[str] | set[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe path rejected: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts[:-1]:
        cursor = cursor / part
        if cursor.exists() or cursor.is_symlink():
            if stat.S_ISLNK(cursor.lstat().st_mode):
                raise ValueError(f"Symlinked ancestor rejected: {relative}")
        else:
            break
    target = release_root / item
    if must_exist:
        mode = target.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError(f"Not a regular non-symlink file: {relative}")
        target.resolve(strict=True).relative_to(release_root)
    elif target.exists() or target.is_symlink():
        mode = target.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise ValueError(f"Unsafe existing destination: {relative}")
    return target


def _validate_roots(source_root: Path, target_root: Path) -> tuple[Path, Path, list[str]]:
    errors: list[str] = []
    try:
        source = source_root.resolve(strict=True)
        target = target_root.resolve(strict=True)
    except Exception as exc:
        return source_root, target_root, [f"Release root unavailable: {exc}"]
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
        freeze_path = _contained(source_root, V46_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot read source V4.6 freeze: {exc}"]
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        return freeze, [], ["V4.6 frozen_files must be an object."]
    if not (
        freeze.get("freeze_contract_version") == "QUANTUM LAB V4.6 FREEZE CONTRACT · V1"
        and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
        and freeze.get("frozen_file_count") == EXPECTED_V46_FROZEN_FILE_COUNT
        and len(frozen) == EXPECTED_V46_FROZEN_FILE_COUNT
        and _path_fingerprint(frozen) == EXPECTED_V46_FROZEN_PATHS_FINGERPRINT
    ):
        errors.append("V4.6 source freeze identity, count or path fingerprint mismatch.")
    if freeze.get("release_paths") != list(V46_TRANSITION_FILES):
        errors.append("V4.6 source release path order mismatch.")
    deployment = freeze.get("deployment_contract") or {}
    if not (
        deployment.get("ordered_transition_paths") == list(V46_TRANSITION_FILES)
        and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V46_OVERLAY_ORDER_SHA256
        and deployment.get("readme_surface_penultimate") == README_PATH
        and deployment.get("integration_surface_last") == UI_PATH
    ):
        errors.append("V4.6 deployment ordering contract mismatch.")
    policy = freeze.get("successor_policy") or {}
    if not (
        policy.get("accepted_target_states") == ["V4.5", "V4.6"]
        and policy.get("allowed_v45_superseded_files") == [README_PATH, UI_PATH]
        and policy.get("mixed_or_third_state") == "REJECT"
    ):
        errors.append("V4.6 source successor policy mismatch.")
    missing = set(V46_TRANSITION_FILES) - {V46_FREEZE_PATH} - set(frozen)
    if missing:
        errors.append("V4.6 freeze omits transition paths: " + ", ".join(sorted(missing)))
    if frozen.get(PARENT_FREEZE_PATH) != PARENT_FREEZE_RAW_SHA256:
        errors.append("V4.6 freeze does not preserve the exact V4.5 freeze file.")
    rows: list[dict[str, Any]] = []
    for relative in V46_TRANSITION_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V46_FREEZE_PATH:
                actual, expected, kind = _freeze_semantic(freeze), freeze.get("freeze_contract_sha256"), "CANONICAL_JSON_SELF_HASH"
            else:
                actual, expected, kind = _sha256(path), frozen.get(relative), "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except Exception as exc:
            actual, expected, kind, valid = None, frozen.get(relative), "RAW_FILE_SHA256", False
            errors.append(f"Source path {relative}: {exc}")
        rows.append({"path": relative, "actual_sha256": actual, "expected_sha256": expected, "integrity": kind, "valid": valid})
        if not valid:
            errors.append(f"Source overlay mismatch: {relative}")
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(readme_sha: str | None, ui_sha: str | None, parent: Mapping[str, Any], source: Mapping[str, Any]) -> str:
    parent_policy = parent.get("successor_policy") or {}
    source_policy = source.get("successor_policy") or {}
    pair = (readme_sha, ui_sha)
    if pair == (parent_policy.get("v45_successor_readme_sha256"), parent_policy.get("v45_successor_ui_sha256")):
        return "V4.5"
    if pair == (source_policy.get("v46_successor_readme_sha256"), source_policy.get("v46_successor_ui_sha256")):
        return "V4.6"
    return "INVALID"


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        source_freeze = _read_json_strict(_contained(source_root, V46_FREEZE_PATH, must_exist=True))
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V4.6 source freeze self-hash mismatch")
    except Exception as exc:
        source_freeze = {}
        errors.append(f"Source transition policy: {exc}")
    try:
        parent_path = _contained(target_root, PARENT_FREEZE_PATH, must_exist=True)
        parent = _read_json_strict(parent_path)
        parent_raw = _sha256(parent_path)
        parent_semantic = _freeze_semantic(parent)
    except Exception as exc:
        parent, parent_raw, parent_semantic = {}, None, None
        errors.append(f"Cannot authenticate target V4.5 freeze: {exc}")
    parent_files = parent.get("frozen_files") or {}
    parent_identity = bool(
        parent_raw == PARENT_FREEZE_RAW_SHA256
        and parent_semantic == parent.get("freeze_contract_sha256") == PARENT_FREEZE_SEMANTIC_SHA256
        and isinstance(parent_files, dict)
        and len(parent_files) == parent.get("frozen_file_count") == PARENT_FROZEN_FILE_COUNT
        and _path_fingerprint(parent_files) == PARENT_FROZEN_PATHS_FINGERPRINT
    )
    if not parent_identity:
        errors.append("Target V4.5 freeze raw/semantic identity or inventory mismatch.")
    immutable = {
        str(path): str(digest) for path, digest in parent_files.items()
        if str(path) not in {README_PATH, UI_PATH}
    } if isinstance(parent_files, dict) else {}
    mismatches: list[str] = []
    for relative, expected in sorted(immutable.items()):
        try:
            if _sha256(_contained(target_root, relative, must_exist=True)) != expected:
                mismatches.append(relative)
        except Exception:
            mismatches.append(relative)
    if len(immutable) != PARENT_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(f"Target immutable V4.5 mismatch count: {len(mismatches)}")
    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    state = _successor_state(readme_sha, ui_sha, parent, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown or an unauthorized third state.")
    partial: list[str] = []
    if state == "V4.5":
        partial = sorted(relative for relative in V46_ONLY_FILES if (target_root / relative).exists() or (target_root / relative).is_symlink())
        if partial:
            errors.append("Partial V4.6 state detected: " + ", ".join(partial))
    elif state == "V4.6":
        frozen = source_freeze.get("frozen_files") or {}
        for relative in V46_TRANSITION_FILES:
            try:
                path = _contained(target_root, relative, must_exist=True)
                actual = _freeze_semantic(_read_json_strict(path)) if relative == V46_FREEZE_PATH else _sha256(path)
                expected = source_freeze.get("freeze_contract_sha256") if relative == V46_FREEZE_PATH else frozen.get(relative)
                if actual != expected:
                    errors.append(f"Exact V4.6 target mismatch: {relative}")
            except Exception as exc:
                errors.append(f"Exact V4.6 target path {relative}: {exc}")
    for relative in V46_TRANSITION_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")
    return {
        "errors": list(dict.fromkeys(errors)),
        "immutable_file_count": len(immutable),
        "immutable_mismatches": mismatches,
        "partial_v46_paths": partial,
        "state": state,
        "valid": not errors,
    }


def _transition_root(source_root: Path) -> str:
    freeze, rows, errors = _source_inventory(source_root)
    if errors or not rows:
        raise ValueError("Cannot commit an unauthenticated V4.6 source: " + "; ".join(errors))
    return hashlib.sha256(
        json.dumps([(row["path"], row["actual_sha256"]) for row in rows], separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _build_candidate(source_root: Path, target_root: Path, source_freeze: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    stage = Path(tempfile.mkdtemp(prefix="quantum-lab-v46-candidate."))
    try:
        frozen = source_freeze.get("frozen_files") or {}
        for relative in sorted(frozen):
            source = (
                _contained(source_root, relative, must_exist=True)
                if relative in V46_TRANSITION_FILES and relative != V46_FREEZE_PATH
                else _contained(target_root, relative, must_exist=True)
            )
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        freeze_destination = stage / V46_FREEZE_PATH
        shutil.copy2(_contained(source_root, V46_FREEZE_PATH, must_exist=True), freeze_destination)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(stage)
        env["PYTHONNOUSERSITE"] = "1"
        completed = subprocess.run(
            [sys.executable, "-m", "quantum_research_lab.phase3_v46_validation", "--root", str(stage)],
            cwd=stage,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        try:
            validation = json.loads(completed.stdout)
        except Exception:
            validation = {"passed": False, "errors": [completed.stderr or completed.stdout]}
        if completed.returncode != 0 or validation.get("passed") is not True:
            raise RuntimeError(f"Candidate scientific validation failed: {validation}")
        return stage, validation
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def preflight(source_root: str | Path, target_root: str | Path) -> dict[str, Any]:
    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {"errors": root_errors, "installer": INSTALLER_VERSION, "valid": False}
    freeze, rows, source_errors = _source_inventory(source)
    target_report = authenticate_target(source, target) if not source_errors else {"valid": False, "state": "UNKNOWN", "errors": []}
    errors = list(root_errors) + list(source_errors) + list(target_report.get("errors") or [])
    candidate_validation: dict[str, Any] = {"performed": False, "passed": False}
    if not errors and target_report.get("state") == "V4.5":
        try:
            stage, validation = _build_candidate(source, target, freeze)
            shutil.rmtree(stage, ignore_errors=True)
            candidate_validation = {"performed": True, "passed": True, "scientific_checks": (validation.get("counts") or {}).get("checks_total")}
        except Exception as exc:
            errors.append(str(exc))
    elif not errors and target_report.get("state") == "V4.6":
        candidate_validation = {"performed": False, "passed": True, "reason": "EXACT_IDEMPOTENT_NO_OP"}
    return {
        "candidate_validation": candidate_validation,
        "errors": list(dict.fromkeys(errors)),
        "installer": INSTALLER_VERSION,
        "overlay_file_count": len(V46_TRANSITION_FILES),
        "source_inventory": rows,
        "source_transition_root_sha256": _transition_root(source) if not source_errors else None,
        "target": target_report,
        "valid": not errors and target_report.get("valid") is True and candidate_validation.get("passed") is True,
    }


def _acquire_lock(target: Path) -> tuple[Path, str]:
    for name in RESIDUAL_LOCK_NAMES:
        if (target / name).exists() or (target / name).is_symlink():
            raise RuntimeError(f"Residual predecessor install lock rejected: {name}")
    lock = target / LOCK_NAME
    token = uuid4().hex
    lock.mkdir(mode=0o700)
    (lock / "owner-token").write_text(token, encoding="utf-8")
    return lock, token


def _release_lock(lock: Path, token: str) -> None:
    token_path = lock / "owner-token"
    if not token_path.is_file() or token_path.read_text(encoding="utf-8") != token:
        raise RuntimeError("Refusing to release a V4.6 lock without the owned token.")
    token_path.unlink()
    lock.rmdir()


def apply_overlay(source_root: str | Path, target_root: str | Path, *, fault_after: int | None = None) -> dict[str, Any]:
    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {"applied": False, "errors": root_errors, "installer": INSTALLER_VERSION, "valid": False}
    initial = preflight(source, target)
    if initial.get("valid") is not True:
        return {"applied": False, "errors": initial.get("errors"), "installer": INSTALLER_VERSION, "preflight": initial, "valid": False}
    if (initial.get("target") or {}).get("state") == "V4.6":
        return {"applied": False, "errors": [], "idempotent_no_op": True, "installer": INSTALLER_VERSION, "preflight": initial, "target_state": "V4.6", "valid": True}
    lock: Path | None = None
    token = ""
    backup = target / ".quantum-lab-v46-backups" / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex}"
    preimages: dict[str, str | None] = {}
    committed: list[str] = []
    try:
        lock, token = _acquire_lock(target)
        source_root_before = _transition_root(source)
        if source_root_before != initial.get("source_transition_root_sha256"):
            raise RuntimeError("V4.6 source changed after preflight.")
        backup.mkdir(parents=True, mode=0o700)
        for index, relative in enumerate(V46_TRANSITION_FILES, start=1):
            source_path = _contained(source, relative, must_exist=True)
            destination = _contained(target, relative, must_exist=False)
            if destination.exists():
                preimages[relative] = _sha256(destination)
                backup_path = backup / relative
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
            else:
                preimages[relative] = None
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.v46-{uuid4().hex}.tmp")
            shutil.copy2(source_path, temporary)
            os.replace(temporary, destination)
            committed.append(relative)
            if fault_after is not None and index == fault_after:
                raise RuntimeError(f"Injected V4.6 commit fault after path {index}")
        if _transition_root(source) != source_root_before:
            raise RuntimeError("V4.6 source changed during commit.")
        final_target = authenticate_target(source, target)
        if final_target.get("valid") is not True or final_target.get("state") != "V4.6":
            raise RuntimeError(f"Post-commit target authentication failed: {final_target}")
        manifest = {
            "backup_directory": str(backup),
            "committed_paths": committed,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "installer": INSTALLER_VERSION,
            "preimage_sha256": preimages,
            "source_transition_root_sha256": source_root_before,
            "target_state": "V4.6",
        }
        (backup / "deployment-manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"applied": True, "errors": [], "idempotent_no_op": False, "installer": INSTALLER_VERSION, "manifest": manifest, "target_state": "V4.6", "valid": True}
    except Exception as exc:
        rollback_errors: list[str] = []
        for relative in reversed(committed):
            try:
                destination = _contained(target, relative, must_exist=True)
                previous = preimages.get(relative)
                if previous is None:
                    destination.unlink()
                else:
                    backup_path = _contained(backup, relative, must_exist=True)
                    if _sha256(backup_path) != previous:
                        raise RuntimeError("backup preimage hash mismatch")
                    temporary = destination.with_name(f".{destination.name}.rollback-{uuid4().hex}.tmp")
                    shutil.copy2(backup_path, temporary)
                    os.replace(temporary, destination)
            except Exception as rollback_exc:
                rollback_errors.append(f"{relative}: {rollback_exc}")
        return {"applied": False, "errors": [str(exc)], "installer": INSTALLER_VERSION, "rollback_errors": rollback_errors, "rolled_back": not rollback_errors, "valid": False}
    finally:
        if lock is not None and lock.exists():
            _release_lock(lock, token)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = apply_overlay(args.source, args.target) if args.apply else preflight(args.source, args.target)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_V46_FROZEN_FILE_COUNT",
    "EXPECTED_V46_FROZEN_PATHS_FINGERPRINT",
    "EXPECTED_V46_OVERLAY_ORDER_SHA256",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V46_FREEZE_PATH",
    "V46_ONLY_FILES",
    "V46_TRANSITION_FILES",
    "V46_TRANSITION_ORDER_SHA256",
    "_source_inventory",
    "_transition_root",
    "apply_overlay",
    "authenticate_target",
    "preflight",
]
