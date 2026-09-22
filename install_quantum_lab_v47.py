"""Transactional, fail-closed installer for the Quantum Lab V4.7 overlay.

Only an exact authenticated V4.6 predecessor or an exact V4.7 no-op target is
accepted.  A trusted out-of-band raw-tree pin must authenticate all 25 source
files, including the raw freeze bytes, before any source-controlled Python is
executed.  The installer performs no credential, provider, network, simulator,
backend or QPU operation.  It authenticates a complete candidate tree before
commit, reauthenticates both source and predecessor under an owned lock, writes
the human README penultimately and the integration surface last, and restores
hash-authenticated preimages after any injected or organic commit failure.
The source may be the complete institutional tree or the exact 25-file sparse
overlay; sparse predecessor bytes are authenticated against the named target.
"""

from __future__ import annotations

import argparse
import ast
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


INSTALLER_VERSION = "QUANTUM LAB V4.7 TRANSACTIONAL INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v47-install.lock"
RESIDUAL_LOCK_NAMES = (
    ".quantum-lab-v46-install.lock",
    ".quantum-lab-v45-install.lock",
    ".quantum-lab-v44-install.lock",
    ".quantum-lab-v43-install.lock",
)
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_6.json"
V47_FREEZE_PATH = "FREEZE_CONTRACT_V4_7.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
PARENT_FREEZE_RAW_SHA256 = "2a025b3a67fd56287deca8d793745a6a3a6b8db5063f85a5af4057cb8b29e5bd"
PARENT_FREEZE_SEMANTIC_SHA256 = "178e60504085130b774d60bff794f6d5602400b87b13aa28f5308e33ce417104"
PARENT_FROZEN_FILE_COUNT = 249
PARENT_IMMUTABLE_FILE_COUNT = 247
PARENT_FROZEN_PATHS_FINGERPRINT = "6be1cbbc2d414298b4907878eac9e3924152679dfeb20e71079f409a0e22ccac"
EXPECTED_V47_FROZEN_FILE_COUNT = 272
EXPECTED_V47_FROZEN_PATHS_FINGERPRINT = "ae031bfffbb63989a382fb03aef942481c1a1d685ff0b574217bfb8e4fb037aa"
EXPECTED_V47_OVERLAY_ORDER_SHA256 = "fd79355920e5ea82da07a67de5c46623cab7b28ae6d1b34f830c372e66adc7c9"

# Evidence first; the human-facing successor surface is penultimate and the
# integration surface is last.  This order is part of the release identity.
V47_TRANSITION_FILES = (
    V47_FREEZE_PATH,
    "DEPLOY_V4_7.md",
    "app_v47_offline_harness.py",
    "install_quantum_lab_v47.py",
    "build_quantum_lab_v47_release.py",
    "outputs/quantum_phase3/v47_dated_properties/SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json",
    "outputs/quantum_phase3/v47_dated_properties/SEALED_V4_7_VALIDATION_REPORT.json",
    "quantum_research_lab/PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json",
    "quantum_research_lab/PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json",
    "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json",
    "quantum_research_lab/PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json",
    "quantum_research_lab/PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_7_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v47_reference_builder.py",
    "quantum_research_lab/phase3_v47_dated_properties_optimizer.py",
    "quantum_research_lab/phase3_v47_independent_checker.py",
    "quantum_research_lab/phase3_v47_validation.py",
    "quantum_research_lab/phase3_v47_ui.py",
    "quantum_research_lab/test_phase3_v47.py",
    "quantum_research_lab/test_phase3_v47_release.py",
    "quantum_research_lab/verify_freeze_contract_v47.py",
    "quantum_research_lab/verify_phase3_v47.py",
    "quantum_research_lab/verify_phase3_v47_ui.py",
    README_PATH,
    UI_PATH,
)
V47_ONLY_FILES = frozenset(V47_TRANSITION_FILES) - {README_PATH, UI_PATH}
V47_TRANSITION_ORDER_SHA256 = hashlib.sha256(
    json.dumps(list(V47_TRANSITION_FILES), separators=(",", ":")).encode("utf-8")
).hexdigest()
if V47_TRANSITION_ORDER_SHA256 != EXPECTED_V47_OVERLAY_ORDER_SHA256:
    raise RuntimeError("V4.7 ordered overlay inventory drifted.")

CANDIDATE_EXECUTED_PYTHON_PATHS = (
    "quantum_research_lab/__init__.py",
    "quantum_research_lab/phase3_v47_independent_checker.py",
    "quantum_research_lab/phase3_v47_validation.py",
)
CANDIDATE_FORBIDDEN_IMPORT_ROOTS = frozenset(
    {
        "aiohttp",
        "boto3",
        "builtins",
        "ctypes",
        "ftplib",
        "http",
        "httpx",
        "importlib",
        "os",
        "paramiko",
        "qiskit",
        "qiskit_ibm_provider",
        "qiskit_ibm_runtime",
        "requests",
        "socket",
        "ssl",
        "subprocess",
        "urllib",
    }
)
CANDIDATE_FORBIDDEN_DYNAMIC_CALLS = frozenset(
    {"__import__", "compile", "eval", "exec", "open"}
)

FAULT_PHASES = frozenset(
    {
        "after_lock",
        "after_source_reauthentication",
        "after_predecessor_reauthentication",
        "after_backup_directory",
        "after_all_paths",
        "before_final_authentication",
        "after_final_authentication",
        "before_manifest",
        "after_manifest",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


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
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"Non-finite JSON number: {token}")
        ),
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


def source_tree_raw_sha256(source_root: str | Path) -> str:
    """Hash the ordered 25-file overlay, including the raw freeze bytes.

    This helper creates a release identity; it is not an authentication step by
    itself.  Deployment callers must obtain the expected value from a trusted
    release manifest or out-of-band channel, never derive it from the source
    they are about to install.
    """

    root = Path(source_root).resolve(strict=True)
    rows = [
        (relative, _sha256(_contained(root, relative, must_exist=True)))
        for relative in V47_TRANSITION_FILES
    ]
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _authenticate_source_tree_raw(
    source_root: Path,
    expected_source_tree_raw_sha256: str,
) -> tuple[str | None, list[str]]:
    if not _is_sha256(expected_source_tree_raw_sha256):
        return None, [
            "A lowercase 64-character expected_source_tree_raw_sha256 external pin is required."
        ]
    try:
        actual = source_tree_raw_sha256(source_root)
    except Exception as exc:
        return None, [f"Cannot hash exact V4.7 source tree: {exc}"]
    if actual != expected_source_tree_raw_sha256:
        return actual, [
            "V4.7 source-tree raw identity mismatch: "
            f"{actual} != {expected_source_tree_raw_sha256}"
        ]
    return actual, []


def _candidate_environment(stage: Path) -> dict[str, str]:
    """Return a deterministic environment with no inherited secrets."""

    return {
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(stage),
        "TZ": "UTC",
    }


def _candidate_static_boundary(stage: Path) -> dict[str, list[str]]:
    """Reject network/provider/environment-capable imports before execution."""

    admitted: dict[str, list[str]] = {}
    for relative in CANDIDATE_EXECUTED_PYTHON_PATHS:
        path = _contained(stage, relative, must_exist=True)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        roots: set[str] = set()
        dynamic_calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.lstrip(".").split(".", 1)[0])
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in CANDIDATE_FORBIDDEN_DYNAMIC_CALLS
            ):
                dynamic_calls.add(node.func.id)
        forbidden = sorted(roots & CANDIDATE_FORBIDDEN_IMPORT_ROOTS)
        if forbidden or dynamic_calls:
            raise RuntimeError(
                f"Candidate static offline boundary failed for {relative}: "
                f"forbidden_imports={forbidden}, forbidden_calls={sorted(dynamic_calls)}"
            )
        admitted[relative] = sorted(roots)
    return admitted


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


def _parent_identity(root: Path) -> tuple[dict[str, Any], dict[str, str], list[str]]:
    errors: list[str] = []
    try:
        path = _contained(root, PARENT_FREEZE_PATH, must_exist=True)
        parent = _read_json_strict(path)
        frozen = parent.get("frozen_files") or {}
        if not isinstance(frozen, dict):
            raise ValueError("V4.6 frozen_files must be an object")
        if not (
            _sha256(path) == PARENT_FREEZE_RAW_SHA256
            and parent.get("freeze_contract_sha256")
            == _freeze_semantic(parent)
            == PARENT_FREEZE_SEMANTIC_SHA256
            and parent.get("freeze_contract_version") == "QUANTUM LAB V4.6 FREEZE CONTRACT · V1"
            and parent.get("frozen_file_count") == len(frozen) == PARENT_FROZEN_FILE_COUNT
            and _path_fingerprint(frozen) == PARENT_FROZEN_PATHS_FINGERPRINT
        ):
            raise ValueError("V4.6 freeze raw, semantic or inventory identity mismatch")
    except Exception as exc:
        return {}, {}, [f"Cannot authenticate exact V4.6 freeze: {exc}"]
    immutable = {
        str(relative): str(digest)
        for relative, digest in frozen.items()
        if str(relative) not in {README_PATH, UI_PATH}
    }
    if len(immutable) != PARENT_IMMUTABLE_FILE_COUNT:
        errors.append(
            f"V4.6 immutable inventory mismatch: {len(immutable)} != {PARENT_IMMUTABLE_FILE_COUNT}"
        )
    return parent, immutable, errors


def _lineage_root(
    source_root: Path,
    predecessor_root: Path | None,
) -> tuple[Path, str]:
    """Use a complete source lineage when present, otherwise the sparse target."""

    source_parent = source_root / PARENT_FREEZE_PATH
    if source_parent.exists() or source_parent.is_symlink():
        return source_root, "FULL_SOURCE"
    if predecessor_root is not None:
        return predecessor_root, "SPARSE_TARGET_PREDECESSOR"
    return source_root, "FULL_SOURCE_REQUIRED_BUT_MISSING"


def _source_inventory(
    source_root: Path,
    predecessor_root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    lineage_root, lineage_mode = _lineage_root(source_root, predecessor_root)
    parent, parent_immutable, parent_errors = _parent_identity(lineage_root)
    errors.extend(parent_errors)
    try:
        freeze_path = _contained(source_root, V47_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], list(dict.fromkeys(errors + [f"Cannot read source V4.7 freeze: {exc}"]))
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        return freeze, [], list(dict.fromkeys(errors + ["V4.7 frozen_files must be an object."]))
    if not (
        freeze.get("freeze_contract_version") == "QUANTUM LAB V4.7 FREEZE CONTRACT · V1"
        and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
        and freeze.get("frozen_file_count") == len(frozen) == EXPECTED_V47_FROZEN_FILE_COUNT
        and _path_fingerprint(frozen)
        == freeze.get("frozen_paths_fingerprint_sha256")
        == EXPECTED_V47_FROZEN_PATHS_FINGERPRINT
    ):
        errors.append("V4.7 source freeze identity, count or path fingerprint mismatch.")
    deployment = freeze.get("deployment_contract") or {}
    successor = freeze.get("successor_policy") or {}
    if freeze.get("release_paths") != list(V47_TRANSITION_FILES):
        errors.append("V4.7 source release path order mismatch.")
    if not (
        deployment.get("ordered_transition_paths") == list(V47_TRANSITION_FILES)
        and deployment.get("ordered_transition_paths_sha256") == EXPECTED_V47_OVERLAY_ORDER_SHA256
        and deployment.get("overlay_file_count") == len(V47_TRANSITION_FILES)
        and deployment.get("readme_surface_penultimate") == README_PATH
        and deployment.get("integration_surface_last") == UI_PATH
    ):
        errors.append("V4.7 deployment ordering contract mismatch.")
    if not (
        successor.get("accepted_target_states") == ["V4.6", "V4.7"]
        and successor.get("allowed_v46_superseded_files") == [README_PATH, UI_PATH]
        and successor.get("mixed_or_third_state") == "REJECT"
    ):
        errors.append("V4.7 source successor policy mismatch.")
    for relative, expected in parent_immutable.items():
        if frozen.get(relative) != expected:
            errors.append(f"V4.7 freeze altered immutable V4.6 digest: {relative}")
    if frozen.get(PARENT_FREEZE_PATH) != PARENT_FREEZE_RAW_SHA256:
        errors.append("V4.7 freeze does not preserve the exact V4.6 freeze file.")
    expected_paths = set(parent_immutable) | {PARENT_FREEZE_PATH} | (
        set(V47_TRANSITION_FILES) - {V47_FREEZE_PATH}
    )
    if set(frozen) != expected_paths:
        errors.append("V4.7 frozen path set is not the exact append-only successor inventory.")
    rows: list[dict[str, Any]] = []
    for relative in V47_TRANSITION_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V47_FREEZE_PATH:
                actual = _freeze_semantic(freeze)
                expected = freeze.get("freeze_contract_sha256")
                kind = "CANONICAL_JSON_SELF_HASH"
            else:
                actual = _sha256(path)
                expected = frozen.get(relative)
                kind = "RAW_FILE_SHA256"
            valid = bool(expected and actual == expected)
        except Exception as exc:
            actual, expected, kind, valid = None, frozen.get(relative), "RAW_FILE_SHA256", False
            errors.append(f"Source path {relative}: {exc}")
        rows.append(
            {
                "path": relative,
                "actual_sha256": actual,
                "expected_sha256": expected,
                "integrity": kind,
                "lineage_mode": lineage_mode,
                "valid": valid,
            }
        )
        if not valid:
            errors.append(f"Source overlay mismatch: {relative}")
    # Authenticate every frozen byte, not only the overlay payload.  A full
    # institutional source carries the predecessor bytes itself.  A sparse
    # deployment overlay binds those bytes to the separately authenticated
    # target predecessor instead, which keeps the 25-file transport usable
    # without weakening the append-only lineage check.
    for relative, expected in sorted(frozen.items()):
        try:
            byte_root = (
                source_root
                if relative in V47_TRANSITION_FILES and relative != V47_FREEZE_PATH
                else lineage_root
            )
            if _sha256(_contained(byte_root, relative, must_exist=True)) != expected:
                errors.append(f"Source frozen byte mismatch: {relative}")
        except Exception as exc:
            errors.append(f"Source frozen path {relative}: {exc}")
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(
    readme_sha: str | None,
    ui_sha: str | None,
    parent: Mapping[str, Any],
    source: Mapping[str, Any],
) -> str:
    parent_policy = parent.get("successor_policy") or {}
    source_policy = source.get("successor_policy") or {}
    pair = (readme_sha, ui_sha)
    if pair == (
        parent_policy.get("v46_successor_readme_sha256"),
        parent_policy.get("v46_successor_ui_sha256"),
    ):
        return "V4.6"
    if pair == (
        source_policy.get("v47_successor_readme_sha256"),
        source_policy.get("v47_successor_ui_sha256"),
    ):
        return "V4.7"
    return "INVALID"


def authenticate_target(
    source_root: Path,
    target_root: Path,
    *,
    expected_source_tree_raw_sha256: str,
) -> dict[str, Any]:
    source_tree_raw, errors = _authenticate_source_tree_raw(
        source_root,
        expected_source_tree_raw_sha256,
    )
    if errors:
        return {
            "errors": errors,
            "immutable_file_count": 0,
            "immutable_mismatches": [],
            "partial_v47_paths": [],
            "source_tree_raw_sha256": source_tree_raw,
            "state": "INVALID",
            "valid": False,
        }
    try:
        source_freeze = _read_json_strict(
            _contained(source_root, V47_FREEZE_PATH, must_exist=True)
        )
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V4.7 source freeze self-hash mismatch")
    except Exception as exc:
        source_freeze = {}
        errors.append(f"Source transition policy: {exc}")
    parent, immutable, parent_errors = _parent_identity(target_root)
    errors.extend(parent_errors)
    mismatches: list[str] = []
    for relative, expected in sorted(immutable.items()):
        try:
            if _sha256(_contained(target_root, relative, must_exist=True)) != expected:
                mismatches.append(relative)
        except Exception:
            mismatches.append(relative)
    if len(immutable) != PARENT_IMMUTABLE_FILE_COUNT or mismatches:
        errors.append(f"Target immutable V4.6 mismatch count: {len(mismatches)}")
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
    if state == "V4.6":
        partial = sorted(
            relative
            for relative in V47_ONLY_FILES
            if (target_root / relative).exists() or (target_root / relative).is_symlink()
        )
        if partial:
            errors.append("Partial V4.7 state detected: " + ", ".join(partial))
    elif state == "V4.7":
        frozen = source_freeze.get("frozen_files") or {}
        for relative in V47_TRANSITION_FILES:
            try:
                path = _contained(target_root, relative, must_exist=True)
                actual = _sha256(path)
                expected = (
                    _sha256(
                        _contained(
                            source_root,
                            V47_FREEZE_PATH,
                            must_exist=True,
                        )
                    )
                    if relative == V47_FREEZE_PATH
                    else frozen.get(relative)
                )
                if actual != expected:
                    errors.append(f"Exact V4.7 target mismatch: {relative}")
            except Exception as exc:
                errors.append(f"Exact V4.7 target path {relative}: {exc}")
    for relative in V47_TRANSITION_FILES:
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
        "partial_v47_paths": partial,
        "source_tree_raw_sha256": source_tree_raw,
        "state": state,
        "valid": not errors,
    }


def _transition_root(source_root: Path, predecessor_root: Path | None = None) -> str:
    _freeze, rows, errors = _source_inventory(source_root, predecessor_root)
    if errors or not rows:
        raise ValueError("Cannot commit an unauthenticated V4.7 source: " + "; ".join(errors))
    return hashlib.sha256(
        json.dumps(
            [(row["path"], row["actual_sha256"]) for row in rows],
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _authenticate_candidate_tree(stage: Path, freeze: Mapping[str, Any]) -> None:
    frozen = freeze.get("frozen_files") or {}
    for relative, expected in sorted(frozen.items()):
        if _sha256(_contained(stage, str(relative), must_exist=True)) != expected:
            raise RuntimeError(f"Candidate frozen byte mismatch: {relative}")
    candidate_freeze = _read_json_strict(_contained(stage, V47_FREEZE_PATH, must_exist=True))
    if candidate_freeze != freeze or candidate_freeze.get("freeze_contract_sha256") != _freeze_semantic(candidate_freeze):
        raise RuntimeError("Candidate V4.7 freeze identity mismatch.")


def _build_candidate(
    source_root: Path,
    target_root: Path,
    source_freeze: Mapping[str, Any],
) -> tuple[Path, dict[str, Any]]:
    stage = Path(tempfile.mkdtemp(prefix="quantum-lab-v47-candidate."))
    try:
        frozen = source_freeze.get("frozen_files") or {}
        lineage_root, lineage_mode = _lineage_root(source_root, target_root)
        for relative in sorted(frozen):
            source = (
                _contained(source_root, relative, must_exist=True)
                if relative in V47_TRANSITION_FILES and relative != V47_FREEZE_PATH
                else _contained(lineage_root, relative, must_exist=True)
            )
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        shutil.copy2(
            _contained(source_root, V47_FREEZE_PATH, must_exist=True),
            stage / V47_FREEZE_PATH,
        )
        _authenticate_candidate_tree(stage, source_freeze)
        static_boundary = _candidate_static_boundary(stage)
        env = _candidate_environment(stage)
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "quantum_research_lab.phase3_v47_validation",
                "--root",
                str(stage),
            ],
            cwd=stage,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        try:
            validation = json.loads(completed.stdout)
        except Exception:
            validation = {"passed": False, "errors": [completed.stderr or completed.stdout]}
        if completed.returncode != 0 or validation.get("passed") is not True:
            raise RuntimeError(f"Candidate scientific validation failed: {validation}")
        validation = {
            **validation,
            "installer_candidate_environment_keys": sorted(env),
            "installer_candidate_lineage_mode": lineage_mode,
            "installer_static_offline_boundary": static_boundary,
        }
        return stage, validation
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def preflight(
    source_root: str | Path,
    target_root: str | Path,
    *,
    expected_source_tree_raw_sha256: str,
) -> dict[str, Any]:
    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {
            "errors": root_errors,
            "expected_source_tree_raw_sha256": expected_source_tree_raw_sha256,
            "installer": INSTALLER_VERSION,
            "valid": False,
        }
    source_tree_raw, anchor_errors = _authenticate_source_tree_raw(
        source,
        expected_source_tree_raw_sha256,
    )
    if anchor_errors:
        return {
            "errors": anchor_errors,
            "expected_source_tree_raw_sha256": expected_source_tree_raw_sha256,
            "installer": INSTALLER_VERSION,
            "source_tree_raw_sha256": source_tree_raw,
            "target": {"state": "UNKNOWN", "valid": False},
            "valid": False,
        }
    freeze, rows, source_errors = _source_inventory(source, target)
    target_report = (
        authenticate_target(
            source,
            target,
            expected_source_tree_raw_sha256=expected_source_tree_raw_sha256,
        )
        if not source_errors
        else {"valid": False, "state": "UNKNOWN", "errors": []}
    )
    errors = list(root_errors) + list(source_errors) + list(target_report.get("errors") or [])
    candidate_validation: dict[str, Any] = {"performed": False, "passed": False}
    if not errors and target_report.get("state") == "V4.6":
        try:
            stage, validation = _build_candidate(source, target, freeze)
            shutil.rmtree(stage, ignore_errors=True)
            candidate_validation = {
                "performed": True,
                "passed": True,
                "scientific_checks": (validation.get("counts") or {}).get("checks_total")
                or validation.get("check_count"),
                "source_lineage_mode": validation.get("installer_candidate_lineage_mode"),
                "static_offline_boundary": bool(
                    validation.get("installer_static_offline_boundary")
                ),
            }
        except Exception as exc:
            errors.append(str(exc))
    elif not errors and target_report.get("state") == "V4.7":
        candidate_validation = {
            "performed": False,
            "passed": True,
            "reason": "EXACT_IDEMPOTENT_NO_OP",
        }
    return {
        "candidate_validation": candidate_validation,
        "errors": list(dict.fromkeys(errors)),
        "expected_source_tree_raw_sha256": expected_source_tree_raw_sha256,
        "installer": INSTALLER_VERSION,
        "overlay_file_count": len(V47_TRANSITION_FILES),
        "source_lineage_mode": (
            rows[0].get("lineage_mode") if rows else None
        ),
        "source_inventory": rows,
        "source_tree_raw_sha256": source_tree_raw,
        "source_transition_root_sha256": (
            _transition_root(source, target) if not source_errors else None
        ),
        "target": target_report,
        "valid": not errors
        and target_report.get("valid") is True
        and candidate_validation.get("passed") is True,
    }


def _acquire_lock(target: Path) -> tuple[Path, str]:
    for name in RESIDUAL_LOCK_NAMES:
        if (target / name).exists() or (target / name).is_symlink():
            raise RuntimeError(f"Residual predecessor install lock rejected: {name}")
    lock = target / LOCK_NAME
    token = uuid4().hex
    lock.mkdir(mode=0o700)
    try:
        (lock / "owner-token").write_text(token, encoding="utf-8")
    except Exception:
        lock.rmdir()
        raise
    return lock, token


def _release_lock(lock: Path, token: str) -> None:
    token_path = lock / "owner-token"
    if not token_path.is_file() or token_path.read_text(encoding="utf-8") != token:
        raise RuntimeError("Refusing to release a V4.7 lock without the owned token.")
    token_path.unlink()
    lock.rmdir()


def _inject(requested: str | None, phase: str) -> None:
    if requested == phase:
        raise RuntimeError(f"Injected V4.7 phase fault: {phase}")


def apply_overlay(
    source_root: str | Path,
    target_root: str | Path,
    *,
    expected_source_tree_raw_sha256: str,
    fault_after: int | None = None,
    fault_phase: str | None = None,
) -> dict[str, Any]:
    if fault_after is not None and not 1 <= fault_after <= len(V47_TRANSITION_FILES):
        return {
            "applied": False,
            "errors": [f"fault_after must be within 1..{len(V47_TRANSITION_FILES)}"],
            "installer": INSTALLER_VERSION,
            "valid": False,
        }
    if fault_phase is not None and fault_phase not in FAULT_PHASES:
        return {
            "applied": False,
            "errors": [f"Unknown fault phase: {fault_phase}"],
            "installer": INSTALLER_VERSION,
            "valid": False,
        }
    source, target, root_errors = _validate_roots(Path(source_root), Path(target_root))
    if root_errors:
        return {"applied": False, "errors": root_errors, "installer": INSTALLER_VERSION, "valid": False}
    initial = preflight(
        source,
        target,
        expected_source_tree_raw_sha256=expected_source_tree_raw_sha256,
    )
    if initial.get("valid") is not True:
        return {
            "applied": False,
            "errors": initial.get("errors"),
            "installer": INSTALLER_VERSION,
            "preflight": initial,
            "valid": False,
        }
    if (initial.get("target") or {}).get("state") == "V4.7":
        return {
            "applied": False,
            "errors": [],
            "idempotent_no_op": True,
            "installer": INSTALLER_VERSION,
            "preflight": initial,
            "target_state": "V4.7",
            "valid": True,
        }
    lock: Path | None = None
    token = ""
    backup = target / ".quantum-lab-v47-backups" / (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex}"
    )
    preimages: dict[str, str | None] = {}
    committed: list[str] = []
    temporary_paths: set[Path] = set()
    manifest_path: Path | None = None
    try:
        lock, token = _acquire_lock(target)
        _inject(fault_phase, "after_lock")
        source_tree_raw_before, source_anchor_errors = _authenticate_source_tree_raw(
            source,
            expected_source_tree_raw_sha256,
        )
        if source_anchor_errors or source_tree_raw_before != initial.get(
            "source_tree_raw_sha256"
        ):
            raise RuntimeError(
                "V4.7 raw source tree changed after preflight: "
                + "; ".join(source_anchor_errors)
            )
        source_root_before = _transition_root(source, target)
        if source_root_before != initial.get("source_transition_root_sha256"):
            raise RuntimeError("V4.7 source changed after preflight.")
        _inject(fault_phase, "after_source_reauthentication")
        predecessor = authenticate_target(
            source,
            target,
            expected_source_tree_raw_sha256=expected_source_tree_raw_sha256,
        )
        if predecessor.get("valid") is not True or predecessor.get("state") != "V4.6":
            raise RuntimeError(
                f"V4.6 predecessor changed before commit: {predecessor}"
            )
        _inject(fault_phase, "after_predecessor_reauthentication")
        backup.mkdir(parents=True, mode=0o700)
        _inject(fault_phase, "after_backup_directory")
        for index, relative in enumerate(V47_TRANSITION_FILES, start=1):
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
            temporary = destination.with_name(f".{destination.name}.v47-{uuid4().hex}.tmp")
            temporary_paths.add(temporary)
            try:
                shutil.copy2(source_path, temporary)
                os.replace(temporary, destination)
            finally:
                if not temporary.exists() and not temporary.is_symlink():
                    temporary_paths.discard(temporary)
            committed.append(relative)
            if fault_after == index:
                raise RuntimeError(f"Injected V4.7 commit fault after path {index}")
        _inject(fault_phase, "after_all_paths")
        source_tree_raw_after, source_anchor_errors = _authenticate_source_tree_raw(
            source,
            expected_source_tree_raw_sha256,
        )
        if (
            source_anchor_errors
            or source_tree_raw_after != source_tree_raw_before
            or _transition_root(source, target) != source_root_before
        ):
            raise RuntimeError("V4.7 source changed during commit.")
        _inject(fault_phase, "before_final_authentication")
        final_target = authenticate_target(
            source,
            target,
            expected_source_tree_raw_sha256=expected_source_tree_raw_sha256,
        )
        if final_target.get("valid") is not True or final_target.get("state") != "V4.7":
            raise RuntimeError(f"Post-commit target authentication failed: {final_target}")
        _inject(fault_phase, "after_final_authentication")
        manifest = {
            "backup_directory": str(backup),
            "committed_paths": committed,
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "installer": INSTALLER_VERSION,
            "preimage_sha256": preimages,
            "source_tree_raw_sha256": source_tree_raw_before,
            "source_transition_root_sha256": source_root_before,
            "target_state": "V4.7",
        }
        _inject(fault_phase, "before_manifest")
        manifest_path = backup / "deployment-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        _inject(fault_phase, "after_manifest")
        return {
            "applied": True,
            "errors": [],
            "idempotent_no_op": False,
            "installer": INSTALLER_VERSION,
            "manifest": manifest,
            "target_state": "V4.7",
            "valid": True,
        }
    except Exception as exc:
        rollback_errors: list[str] = []
        for temporary in sorted(temporary_paths, key=str):
            try:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
                temporary_paths.discard(temporary)
            except Exception as rollback_exc:
                rollback_errors.append(f"temporary {temporary}: {rollback_exc}")
        if manifest_path is not None and manifest_path.exists():
            try:
                manifest_path.unlink()
            except Exception as rollback_exc:
                rollback_errors.append(f"deployment-manifest.json: {rollback_exc}")
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
                    temporary = destination.with_name(
                        f".{destination.name}.rollback-{uuid4().hex}.tmp"
                    )
                    temporary_paths.add(temporary)
                    try:
                        shutil.copy2(backup_path, temporary)
                        os.replace(temporary, destination)
                    finally:
                        if not temporary.exists() and not temporary.is_symlink():
                            temporary_paths.discard(temporary)
                    if _sha256(destination) != previous:
                        raise RuntimeError("restored preimage hash mismatch")
            except Exception as rollback_exc:
                rollback_errors.append(f"{relative}: {rollback_exc}")
        for temporary in sorted(temporary_paths, key=str):
            try:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
                temporary_paths.discard(temporary)
            except Exception as rollback_exc:
                rollback_errors.append(f"temporary {temporary}: {rollback_exc}")
        return {
            "applied": False,
            "errors": [str(exc)],
            "installer": INSTALLER_VERSION,
            "rollback_errors": rollback_errors,
            "rolled_back": not rollback_errors,
            "valid": False,
        }
    finally:
        if lock is not None and lock.exists():
            _release_lock(lock, token)


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument(
        "--expected-source-tree-raw-sha256",
        required=True,
        help=(
            "Trusted out-of-band SHA-256 over the ordered 25 raw overlay files; "
            "obtain it from the authenticated release manifest, not the source tree."
        ),
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    report = (
        apply_overlay(
            args.source,
            args.target,
            expected_source_tree_raw_sha256=args.expected_source_tree_raw_sha256,
        )
        if args.apply
        else preflight(
            args.source,
            args.target,
            expected_source_tree_raw_sha256=args.expected_source_tree_raw_sha256,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_V47_FROZEN_FILE_COUNT",
    "EXPECTED_V47_FROZEN_PATHS_FINGERPRINT",
    "EXPECTED_V47_OVERLAY_ORDER_SHA256",
    "FAULT_PHASES",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V47_FREEZE_PATH",
    "V47_ONLY_FILES",
    "V47_TRANSITION_FILES",
    "V47_TRANSITION_ORDER_SHA256",
    "CANDIDATE_EXECUTED_PYTHON_PATHS",
    "CANDIDATE_FORBIDDEN_IMPORT_ROOTS",
    "CANDIDATE_FORBIDDEN_DYNAMIC_CALLS",
    "source_tree_raw_sha256",
    "_source_inventory",
    "_transition_root",
    "apply_overlay",
    "authenticate_target",
    "preflight",
]
