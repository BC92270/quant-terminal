"""Recoverable, fail-closed installer for the Quantum Lab V3.7 overlay.

The overlay is a transition from one exact V3.6 tree to one exact V3.7 tree.
It does not install provider packages, inspect credentials, make network calls,
or enable a QPU path.
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


INSTALLER_VERSION = "QUANTUM LAB V3.7 RECOVERABLE INSTALLER · V1"
LOCK_NAME = ".quantum-lab-v37-install.lock"
V36_FREEZE_PATH = "FREEZE_CONTRACT_V3_6.json"
V36_FREEZE_RAW_SHA256 = "a297a23a6a253d378022fecd3890dd3ef014e75f6a16bcc38b94fcbf2ee1cd56"
V36_FREEZE_SEMANTIC_SHA256 = "8e7ea17da37878f6cd363273ca1a44ae8005740f37fd736524da3126813bd04a"
V36_FROZEN_PATHS_FINGERPRINT = (
    "8d62db5c4afcdf278a100e603143032c8fc3d45c45bc9d3c36d16c75abe84986"
)
V36_README_SHA256 = "c3ee7ba2ae1f83269eb13201a33f7f445cd015a0748f26c5347a4a41b14adc10"
V36_UI_SHA256 = "1cbf2571fdefdc88377cae45c141878c61ceddcd30078ed3a0f6d3fe555c927d"
EXPECTED_V37_FROZEN_PATHS_FINGERPRINT = (
    "2ee843710ccbb4b763beea07a61bd9f22c69751242e98f41d8ffb0dfb47885c1"
)

README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V37_FREEZE_PATH = "FREEZE_CONTRACT_V3_7.json"

# Dependencies first; the two human-facing integration surfaces are replaced
# only after every supporting file, with ui.py strictly last.
V37_TRANSITION_FILES = (
    V37_FREEZE_PATH,
    "DEPLOY_V3_7.md",
    "app_v36_offline_harness.py",
    "app_v37_offline_harness.py",
    "install_quantum_lab_v37.py",
    "outputs/quantum_phase3/v37_reversible/SEALED_V3_7_REVERSIBLE_PROTOTYPE_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_7_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v37_reversible_compiler.py",
    "quantum_research_lab/phase3_v37_ui.py",
    "quantum_research_lab/phase3_v37_validation.py",
    "quantum_research_lab/test_phase3_v37.py",
    "quantum_research_lab/test_phase3_v37_release.py",
    "quantum_research_lab/verify_freeze_contract_v37.py",
    "quantum_research_lab/verify_phase3_v37.py",
    "quantum_research_lab/verify_phase3_v37_ui.py",
    README_PATH,
    UI_PATH,
)
V37_ONLY_FILES = frozenset(V37_TRANSITION_FILES) - {
    "app_v36_offline_harness.py",
    README_PATH,
    UI_PATH,
}

LEGACY_SUPPORT_SHA256 = {
    "FREEZE_CONTRACT_V3_4.json": "a2309c3ae551e74970c1c405ac106045f6db85bb2ba5cb87107a88fbfc7ccb12",
    "NEXT_PHASE_V3_2_GATE_LEVEL_COMPILER.md": "e915b18b02118cb290b08ccdef64cdf34cc794ecaac5ece0a92639fe327d90a1",
    "app_v34_fast_harness.py": "467eac32f5a994db49ef04376f0ce2169f2642c73d5d05e6506d6c112d1ee11b",
    "app_v34_harness.py": "639876189b08cda1397b37b81c7a26426205fd842d3cdee512df2849c18fc424",
    "baseline_phase3_v31.png": "fd885ae90fe4b717e05bf0891b60db8d699bd36835b744f0e450470f9b97c7d3",
    "quantum_research_lab/PHASE_III_BANDS_ORACLE_SPEC_V1.json": "a344857690fe3819fead3629e611865761712f3add3c45afc5c03011f11822ef",
    "quantum_research_lab/PHASE_III_DYADIC_BANDS_ORACLE_SPEC_V1.json": "aa1893c226f6f8a557f3945c218501f28ddc3624b5bcc3b9104cf53143299851",
    "quantum_research_lab/PHASE_III_GATE_COMPILER_SPEC_V1.json": "6e190e5752440998d4b5c3e5050702d9c2b016b20f13a8ff93afa1d9e9487c6d",
    "quantum_research_lab/PHASE_III_QPU_PREPARATION_SPEC_V1.json": "b04196d41195177e86aaf042e06ffb669d20e4b8a2ecf0d953cedc9d3091925d",
    "quantum_research_lab/PHASE_II_PREREGISTRATION_V1.json": "3b46bffc8631834bea755d423ec24d3e17f417975cef3d096b58b4d5ded2e465",
    "quantum_research_lab/QPU_OPTIONAL_REQUIREMENTS.txt": "581c039a010cf398275ff1f388f289384d9d974d85275b232fb761a36c424c21",
    "quantum_research_lab/QUANTUM_LAB_V3_2_ARCHITECTURE.md": "681690e42c8962a72a392647b788d5e20c7b182b0be1d759a61b8c57cd244f7c",
    "quantum_research_lab/QUBO_PHASEII_EXECUTION_SPEC_V1.json": "4ed11a390a23c73dc65b761eed72f25c9a4738739f865ffc6ec42d2070688001",
    "quantum_research_lab/__init__.py": "868af06f227f9e1a70bae235503185f93dc6989101e0dce3d2979fb97117205b",
    "quantum_research_lab/data.py": "96b40e82fa938f2f2c25f89d4f4c75c85f1c981a5115f38f8cb6e7735ef02449",
    "quantum_research_lab/engine.py": "70726d2933c195edd89d94acdceb2d3fbb2fa114701b3210c309ddf0135f1e70",
    "quantum_research_lab/evidence.py": "aec17335d00dea42f96b7c06a95ece32759b61ce4f92fc8e223f08a89c7d5443",
    "quantum_research_lab/experiments.py": "0f426875098e117ad2b7458eadf55023e9ad04cf18867dd4fa3fbd88ddb5032f",
    "quantum_research_lab/phase2_qhardness.py": "30c2cb35444afeeff669b9772d5577e89f32dbead762a09fb90fde70c9b653ce",
    "quantum_research_lab/phase3_artifact_guard.py": "d151f01c26854b2b3742e88eed54fd8b1b5adfddcc932ad97c5012d6fe03a010",
    "quantum_research_lab/phase3_bands_oracle.py": "f870fc0a5b372f48abd1532370a25292f6ac9d6318afaae2b739d55dd1fd1827",
    "quantum_research_lab/phase3_circuit_validation.py": "363f532f8c155bac6e702ebbe9afc8d2a82c155e3d9c11e5515d6abe1cc71252",
    "quantum_research_lab/phase3_dyadic_oracle.py": "843db34f4bb140f9ed4066bb044b1754d12820521c8ee603389bf031bdd3b2e0",
    "quantum_research_lab/phase3_gate_compiler.py": "b76001c8502eec962dc998d1c8ffa37b2886432149fb193f26e52d82cd348c78",
    "quantum_research_lab/phase3_qpu.py": "31b94a26a88c9b7c79f22ff8426cfd5b597250ac2a642dfb9b54b56dda0fb2e3",
    "quantum_research_lab/test_phase3_gate_compiler.py": "bb90bd5e8f7cdb17046c357ad1fc07644703b29a68bf73a92c5e9a3ea93563a8",
    "quantum_research_lab/verify_phase3_v32.py": "1e5d3f7dade335947cb82ff79ebfa0778cefc546f8639629b6439b7dd77c7924",
}

# V3.6's deployment archive omitted these historical support files even though
# they were present in the authenticated source tree.  V3.7 carries the full
# closure so a known missing-file packaging gap can be repaired transactionally.
SUPPORT_CLOSURE_FILES = tuple(sorted(LEGACY_SUPPORT_SHA256))
OVERLAY_FILES = SUPPORT_CLOSURE_FILES + V37_TRANSITION_FILES


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


def _valid_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _contained(root: Path, relative: str, *, must_exist: bool = False) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"Unsafe path rejected: {relative!r}")
    release_root = root.resolve(strict=True)
    lexical = release_root / relative_path
    cursor = release_root
    for part in relative_path.parts[:-1]:
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
        freeze_path = _contained(source_root, V37_FREEZE_PATH, must_exist=True)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        return {}, [], [f"Cannot read source V3.7 freeze: {exc}"]
    frozen_files = freeze.get("frozen_files") or {}
    if not isinstance(frozen_files, dict):
        return freeze, [], ["V3.7 frozen_files must be an object."]
    path_fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not (
        freeze.get("frozen_file_count") == 99
        and len(frozen_files) == 99
        and _valid_sha256(EXPECTED_V37_FROZEN_PATHS_FINGERPRINT)
        and path_fingerprint == EXPECTED_V37_FROZEN_PATHS_FINGERPRINT
    ):
        errors.append("V3.7 99-path source inventory or fingerprint mismatch.")
    if freeze.get("freeze_contract_sha256") != _freeze_semantic(freeze):
        errors.append("V3.7 source freeze self-hash mismatch.")

    policy = freeze.get("successor_policy") or {}
    if not (
        policy.get("accepted_target_states") == ["V3.6", "V3.7"]
        and policy.get("mixed_or_third_state") == "REJECT"
        and policy.get("allowed_v36_superseded_files") == [README_PATH, UI_PATH]
        and _valid_sha256(policy.get("v37_successor_readme_sha256"))
        and _valid_sha256(policy.get("v37_successor_ui_sha256"))
    ):
        errors.append("V3.7 source successor policy is invalid.")

    rows: list[dict[str, Any]] = []
    for relative in OVERLAY_FILES:
        try:
            path = _contained(source_root, relative, must_exist=True)
            if relative == V37_FREEZE_PATH:
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
            expected = frozen_files.get(relative)
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
    if set(OVERLAY_FILES) - {V37_FREEZE_PATH} - set(frozen_files):
        errors.append("V3.7 freeze omits one or more overlay paths.")
    if frozen_files.get("app_v36_offline_harness.py") is None:
        errors.append("V3.7 source omits the direct V3.6 harness dependency.")
    return freeze, rows, list(dict.fromkeys(errors))


def _successor_state(
    readme_sha: str | None, ui_sha: str | None, source_freeze: Mapping[str, Any]
) -> str:
    pair = (readme_sha, ui_sha)
    if pair == (V36_README_SHA256, V36_UI_SHA256):
        return "V3.6"
    policy = source_freeze.get("successor_policy") or {}
    v37_pair = (
        policy.get("v37_successor_readme_sha256"),
        policy.get("v37_successor_ui_sha256"),
    )
    if all(_valid_sha256(value) for value in v37_pair) and pair == v37_pair:
        return "V3.7"
    return "INVALID"


def authenticate_target(source_root: Path, target_root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        source_freeze = _read_json_strict(
            _contained(source_root, V37_FREEZE_PATH, must_exist=True)
        )
        if source_freeze.get("freeze_contract_sha256") != _freeze_semantic(source_freeze):
            raise ValueError("V3.7 source freeze self-hash mismatch")
    except Exception as exc:
        source_freeze = {}
        errors.append(f"Source transition policy: {exc}")

    try:
        parent_freeze_path = _contained(target_root, V36_FREEZE_PATH, must_exist=True)
        parent_freeze = _read_json_strict(parent_freeze_path)
        parent_raw = _sha256(parent_freeze_path)
        parent_semantic = _freeze_semantic(parent_freeze)
    except Exception as exc:
        parent_freeze = {}
        parent_raw = parent_semantic = None
        errors.append(f"Cannot authenticate target V3.6 freeze: {exc}")
    parent_files = parent_freeze.get("frozen_files") or {}
    parent_fingerprint = hashlib.sha256(
        json.dumps(sorted(parent_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest() if isinstance(parent_files, dict) else None
    parent_identity = bool(
        parent_raw == V36_FREEZE_RAW_SHA256
        and parent_semantic == V36_FREEZE_SEMANTIC_SHA256
        and parent_freeze.get("freeze_contract_sha256") == V36_FREEZE_SEMANTIC_SHA256
        and parent_freeze.get("frozen_file_count") == 57
        and isinstance(parent_files, dict)
        and len(parent_files) == 57
        and parent_fingerprint == V36_FROZEN_PATHS_FINGERPRINT
    )
    if not parent_identity:
        errors.append("Target V3.6 freeze raw/semantic identity or inventory mismatch.")

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
                errors.append(f"Target immutable V3.6 mismatch: {relative}")

    support: dict[str, bool] = {}
    support_missing: list[str] = []
    support_mismatched: list[str] = []
    for relative, expected in sorted(LEGACY_SUPPORT_SHA256.items()):
        lexical = target_root / relative
        if not lexical.exists() and not lexical.is_symlink():
            support[relative] = False
            support_missing.append(relative)
            continue
        try:
            support[relative] = (
                _sha256(_contained(target_root, relative, must_exist=True)) == expected
            )
        except Exception as exc:
            support[relative] = False
            errors.append(f"Target support {relative}: {exc}")
        if not support[relative]:
            support_mismatched.append(relative)

    try:
        readme_sha = _sha256(_contained(target_root, README_PATH, must_exist=True))
        ui_sha = _sha256(_contained(target_root, UI_PATH, must_exist=True))
    except Exception as exc:
        readme_sha = ui_sha = None
        errors.append(f"Target successor surface: {exc}")
    state = _successor_state(readme_sha, ui_sha, source_freeze)
    if state == "INVALID":
        errors.append("Target README/UI are mixed, unknown, or an unauthorized third state.")
    if support_mismatched:
        errors.extend(
            f"Target V3.7 support snapshot mismatch: {relative}"
            for relative in support_mismatched
        )
    if state == "V3.7" and support_missing:
        errors.extend(
            f"Target V3.7 support path missing: {relative}"
            for relative in support_missing
        )

    for relative in OVERLAY_FILES:
        lexical = target_root.resolve() / relative
        if lexical.exists() or lexical.is_symlink():
            try:
                _contained(target_root, relative, must_exist=True)
            except Exception as exc:
                errors.append(f"Unsafe overlay destination {relative}: {exc}")

    partial_paths: list[str] = []
    if state == "V3.6":
        partial_paths = sorted(
            relative
            for relative in V37_ONLY_FILES
            if (target_root / relative).exists() or (target_root / relative).is_symlink()
        )
        if partial_paths:
            errors.append("Partial V3.7 destinations exist on a V3.6 successor surface.")

    exact_overlay = False
    if state == "V3.7":
        exact_overlay = True
        expected = source_freeze.get("frozen_files") or {}
        for relative in OVERLAY_FILES:
            try:
                if relative == V37_FREEZE_PATH:
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
            errors.append("Target claims V3.7 surface state but overlay is incomplete or mismatched.")

    return {
        "errors": list(dict.fromkeys(errors)),
        "exact_overlay": exact_overlay,
        "immutable_v36_file_count": len(immutable),
        "immutable_v36_files_exact": len(immutable) == 55 and all(immutable.values()),
        "legacy_support_file_count": len(support),
        "legacy_support_files_exact": len(support) == 27 and all(support.values()),
        "legacy_support_missing_paths": support_missing,
        "legacy_support_mismatched_paths": support_mismatched,
        "legacy_support_repair_required": state == "V3.6" and bool(support_missing),
        "parent_freeze_raw_sha256": parent_raw,
        "parent_freeze_semantic_sha256": parent_semantic,
        "parent_identity_exact": parent_identity,
        "partial_v37_paths": partial_paths,
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
    commitments = {
        row["path"]: row["actual_sha256"] for row in source_rows if row.get("valid")
    }
    return {
        "errors": list(dict.fromkeys(errors)),
        "installer_version": INSTALLER_VERSION,
        "overlay_file_count": len(OVERLAY_FILES),
        "source_commitments": commitments,
        "source_files": source_rows,
        "source_freeze_sha256": freeze.get("freeze_contract_sha256"),
        "target": target,
        "valid": not errors,
    }


def _verification_commands(target_root: Path) -> tuple[tuple[str, list[str]], ...]:
    return (
        (
            "v37_unit_tests",
            [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v37"],
        ),
        (
            "v37_release_tests",
            [sys.executable, "-m", "unittest", "quantum_research_lab.test_phase3_v37_release"],
        ),
        (
            "v37_scientific_validation",
            [sys.executable, "-m", "quantum_research_lab.phase3_v37_validation"],
        ),
        (
            "v37_release_chain",
            [sys.executable, "-m", "quantum_research_lab.verify_phase3_v37", str(target_root)],
        ),
        (
            "v37_release_freeze",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_freeze_contract_v37",
                str(target_root),
                "--contract",
                str(target_root / V37_FREEZE_PATH),
            ],
        ),
        (
            "v37_streamlit_positive_rerun",
            [
                sys.executable,
                "-m",
                "quantum_research_lab.verify_phase3_v37_ui",
                str(target_root / "app_v37_offline_harness.py"),
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
            ],
        ),
    )


def _run_commands(
    commands: tuple[tuple[str, list[str]], ...], cwd: Path, *, force_failure: bool = False
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for index, (label, command) in enumerate(commands):
        if force_failure and index == 0:
            raise RuntimeError("Injected V3.7 post-install verification fault.")
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=360,
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
    return {
        "existed": True,
        "mode": stat.S_IMODE(target.stat().st_mode),
        "sha256": _sha256(target),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_copy(source: Path, target: Path, token: str, label: str) -> None:
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


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    _fsync_directory(path.parent)


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
    if predecessor_state == "V3.6":
        commands = (
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
                    str(target_root / V36_FREEZE_PATH),
                ],
            ),
            (
                "v36_streamlit",
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
    else:
        commands = (
            (
                "v37_release_chain",
                [sys.executable, "-m", "quantum_research_lab.verify_phase3_v37", str(target_root)],
            ),
            (
                "v37_freeze",
                [
                    sys.executable,
                    "-m",
                    "quantum_research_lab.verify_freeze_contract_v37",
                    str(target_root),
                    "--contract",
                    str(target_root / V37_FREEZE_PATH),
                ],
            ),
        )
    reports: dict[str, Any] = {}
    okay = True
    for label, command in commands:
        completed = subprocess.run(
            command,
            cwd=target_root,
            capture_output=True,
            text=True,
            timeout=360,
            check=False,
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
    _test_fail_verification: bool = False,
    _test_after_stage: Callable[[Path, Path], None] | None = None,
    _test_after_preimages: Callable[[Path, Path], None] | None = None,
) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    target_root = target_root.resolve(strict=True)
    lock_path = target_root / LOCK_NAME
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        lock_fd = os.open(lock_path, flags, 0o600)
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
        os.fsync(lock_fd)
    finally:
        os.close(lock_fd)

    stage_root: Path | None = None
    backup_root: Path | None = None
    report: dict[str, Any] = {}
    applied: list[str] = []
    preimages: dict[str, dict[str, Any]] = {}
    predecessor_state = "V3.6"
    token = uuid4().hex[:12]
    try:
        report = preflight(source_root, target_root)
        if not report["valid"]:
            return {**report, "applied": False, "idempotent": False, "rolled_back": False}
        predecessor_state = str(report["target"].get("successor_state"))
        if (
            not _test_force_apply
            and predecessor_state == "V3.7"
            and report["target"].get("exact_overlay")
        ):
            return {**report, "applied": False, "idempotent": True, "rolled_back": False}

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stage_root = target_root / f".quantum-lab-v37-stage-{token}"
        backup_root = target_root / f".quantum-lab-v37-backup-{timestamp}-{token}"
        stage_root.mkdir(mode=0o700)
        backup_root.mkdir(mode=0o700)
        _fsync_directory(target_root)

        commitments = report["source_commitments"]
        for relative in OVERLAY_FILES:
            source = _contained(source_root, relative, must_exist=True)
            staged = stage_root / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, staged, follow_symlinks=False)
            actual = (
                _freeze_semantic(_read_json_strict(staged))
                if relative == V37_FREEZE_PATH
                else _sha256(staged)
            )
            if actual != commitments.get(relative):
                raise RuntimeError(f"Staged source commitment mismatch: {relative}")

        if _test_after_stage is not None:
            _test_after_stage(source_root, stage_root)

        for relative, expected in commitments.items():
            source = _contained(source_root, relative, must_exist=True)
            actual = (
                _freeze_semantic(_read_json_strict(source))
                if relative == V37_FREEZE_PATH
                else _sha256(source)
            )
            if actual != expected:
                raise RuntimeError(f"Source changed after preflight: {relative}")

        # Close the target-side preflight/staging window before capturing bytes.
        target_recheck = authenticate_target(source_root, target_root)
        if not target_recheck.get("valid"):
            raise RuntimeError(
                "Target changed after preflight: " + "; ".join(target_recheck.get("errors") or [])
            )

        for relative in OVERLAY_FILES:
            target = _contained(target_root, relative, must_exist=False)
            preimages[relative] = _preimage_entry(target)
            if target.exists():
                backup = backup_root / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup, follow_symlinks=False)
                if _sha256(backup) != preimages[relative]["sha256"]:
                    raise RuntimeError(f"Backup preimage mismatch: {relative}")

        if _test_after_preimages is not None:
            _test_after_preimages(target_root, backup_root)
        # A target mutation after preimage capture must fail before first replace.
        for relative, expected in preimages.items():
            target = target_root / relative
            actual = _preimage_entry(target)
            if actual != expected:
                raise RuntimeError(f"Target changed after preimage capture: {relative}")

        manifest_core = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "installer_version": INSTALLER_VERSION,
            "predecessor_state": predecessor_state,
            "preimages": preimages,
            "target_root": str(target_root),
        }
        manifest = {
            **manifest_core,
            "manifest_sha256": _canonical_json_sha256(manifest_core),
        }
        _write_manifest(backup_root / "PREIMAGE_MANIFEST.json", manifest)

        try:
            for relative in OVERLAY_FILES:
                staged = _contained(stage_root, relative, must_exist=True)
                target = _contained(target_root, relative, must_exist=False)
                target.parent.mkdir(parents=True, exist_ok=True)
                _atomic_copy(staged, target, token, "v37")
                applied.append(relative)
                if _test_fail_after is not None and len(applied) == _test_fail_after:
                    raise RuntimeError("Injected V3.7 installer rollback test fault.")
            if applied[-2:] != [README_PATH, UI_PATH]:
                raise RuntimeError("README/UI integration surfaces were not replaced last.")
            verification = _run_commands(
                _verification_commands(target_root),
                target_root,
                force_failure=_test_fail_verification,
            )
            return {
                **report,
                "applied": True,
                "applied_files": applied,
                "backup_root": str(backup_root),
                "idempotent": False,
                "readme_replaced_penultimate": applied[-2] == README_PATH,
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
                        _atomic_copy(backup, target, token, "rollback")
                        os.chmod(target, int(expected["mode"]))
                    elif target.exists() or target.is_symlink():
                        target.unlink()
                        _fsync_directory(target.parent)
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
    except Exception as exc:
        return {
            **report,
            "applied": False,
            "applied_files_before_failure": applied,
            "backup_root": str(backup_root) if backup_root else None,
            "error": str(exc),
            "idempotent": False,
            "rolled_back": False,
            "valid": False,
        }
    finally:
        if stage_root and stage_root.exists():
            shutil.rmtree(stage_root)
        try:
            lock_path.unlink()
            _fsync_directory(target_root)
        except FileNotFoundError:
            pass


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely install Quantum Lab V3.7.")
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
    "EXPECTED_V37_FROZEN_PATHS_FINGERPRINT",
    "INSTALLER_VERSION",
    "LEGACY_SUPPORT_SHA256",
    "LOCK_NAME",
    "OVERLAY_FILES",
    "SUPPORT_CLOSURE_FILES",
    "V37_ONLY_FILES",
    "authenticate_target",
    "install",
    "preflight",
]
