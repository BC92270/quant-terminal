"""Transactional, fail-closed installer for the compact V5.0 overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import uuid


FREEZE_RELATIVE = Path("release/quantum_v50/freeze.json")
PARENT_FREEZE_RELATIVE = Path("release/quantum_v49/freeze.json")
PARENT_ARTIFACT_RELATIVE = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_ADMISSION_ARTIFACT.json"
)
PARENT_FREEZE_RAW = "7c34668559955edde109820dc400f630621f18086ae47f4de8d2259ef6c97823"
PARENT_FREEZE_SEMANTIC = "f5168ff42d8a72111a0e740e8675203e1382c0bcb6a23d1d12b9e9c3c9d2f597"
PARENT_ARTIFACT_RAW = "1622e2ab0260ea12ef93685ddc75ca58254437b6c9b124c7fd35f8e012457e2b"
RECOGNIZED_STAGED_RELEASE_FREEZES = {
    "7f14c39d5a981c364d6e0d9eab8913f3bdea5a6f6e7d3f0d4bb523b4aee9e39c": (
        "7ea4daa73211daf6724f0a378363ad728bd79bfb6b83258ecef19fc2bf34b743"
    ),
    "c95b5442f6fcb560ccf3b7af91d47d8d23c69afe283666ea17d2b58da927e4a6": (
        "fa8acb511824cac448bec6a42b6c8b4b98f52571bec2a9b13f5fea7f595af6b5"
    ),
}
EXPECTED_SUPERSEDED = frozenset(
    {
        "QUANTUM_RELEASES.md",
        "quantum_research_lab/README.md",
        "quantum_research_lab/ui.py",
    }
)
EXPECTED_TRANSITIONS = (
    "QUANTUM_RELEASES.md",
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
    "quantum_research_lab/v50/__init__.py",
    "quantum_research_lab/v50/ARCHITECTURE.md",
    "quantum_research_lab/v50/PROTOCOL.json",
    "quantum_research_lab/v50/engine/__init__.py",
    "quantum_research_lab/v50/engine/checker.py",
    "quantum_research_lab/v50/engine/evaluator.py",
    "quantum_research_lab/v50/engine/evidence.py",
    "quantum_research_lab/v50/engine/provider_gate.py",
    "quantum_research_lab/v50/engine/validation.py",
    "quantum_research_lab/v50/evidence/SOURCES.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_37_0/conf_fez.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_37_0/conf_marrakesh.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_37_0/props_fez.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_37_0/props_marrakesh.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_47_0/conf_fez.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_47_0/conf_marrakesh.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_47_0/props_fez.json",
    "quantum_research_lab/v50/evidence/raw/qiskit_ibm_runtime_0_47_0/props_marrakesh.json",
    "quantum_research_lab/v50/tests/__init__.py",
    "quantum_research_lab/v50/tests/test_app.py",
    "quantum_research_lab/v50/tests/test_release.py",
    "quantum_research_lab/v50/tests/test_science.py",
    "quantum_research_lab/v50/tests/test_ui.py",
    "quantum_research_lab/v50/ui.py",
    "outputs/quantum_phase3/v50_hardware_evidence_control/SEALED_V5_0_PRE_ADMISSION_ARTIFACT.json",
    "outputs/quantum_phase3/v50_hardware_evidence_control/SEALED_V5_0_VALIDATION_REPORT.json",
    "release/quantum_v50/DEPLOY.md",
    "release/quantum_v50/build.py",
    "release/quantum_v50/harness.py",
    "release/quantum_v50/install.py",
    "release/quantum_v50/freeze.json",
)


def _raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object: {path}")
    return payload


def _semantic(payload: dict[str, object], field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_relative(relative: str) -> bool:
    path = PurePosixPath(relative)
    return (
        bool(relative)
        and not path.is_absolute()
        and str(path) == relative
        and all(part not in ("", ".", "..") for part in path.parts)
    )


def _has_symlink_component(root: Path, relative: str) -> bool:
    candidate = root
    for part in PurePosixPath(relative).parts:
        candidate /= part
        if candidate.is_symlink():
            return True
    return False


def _authenticate_source(
    source: Path,
) -> tuple[dict[str, object], tuple[str, ...], dict[str, str]]:
    freeze_path = source / FREEZE_RELATIVE
    if not freeze_path.is_file() or freeze_path.is_symlink():
        raise ValueError("V5.0 freeze is unavailable")
    freeze = _read(freeze_path)
    if freeze.get("freeze_contract_sha256") != _semantic(
        freeze, "freeze_contract_sha256"
    ):
        raise ValueError("V5.0 freeze self-hash mismatch")
    transitions = freeze.get("transition_files")
    frozen = freeze.get("frozen_files")
    successor = freeze.get("successor_policy")
    if not isinstance(transitions, list) or not all(
        isinstance(item, str) for item in transitions
    ):
        raise ValueError("V5.0 transition order is invalid")
    if tuple(transitions) != EXPECTED_TRANSITIONS or not all(
        _safe_relative(item) for item in transitions
    ):
        raise ValueError("V5.0 transition allowlist mismatch")
    if not isinstance(frozen, dict) or not isinstance(successor, dict):
        raise ValueError("V5.0 frozen-file map is invalid")
    parent = freeze.get("parent")
    if not isinstance(parent, dict) or (
        parent.get("freeze_path") != str(PARENT_FREEZE_RELATIVE)
        or parent.get("freeze_raw_sha256") != PARENT_FREEZE_RAW
        or parent.get("freeze_semantic_sha256") != PARENT_FREEZE_SEMANTIC
    ):
        raise ValueError("V5.0 parent contract mismatch")
    source_parent_freeze = source / PARENT_FREEZE_RELATIVE
    if (
        not source_parent_freeze.is_file()
        or source_parent_freeze.is_symlink()
        or _raw(source_parent_freeze) != PARENT_FREEZE_RAW
    ):
        raise ValueError("Exact V4.9 source freeze is unavailable")
    source_parent = _read(source_parent_freeze)
    if (
        source_parent.get("freeze_contract_sha256") != PARENT_FREEZE_SEMANTIC
        or _semantic(source_parent, "freeze_contract_sha256")
        != PARENT_FREEZE_SEMANTIC
    ):
        raise ValueError("V4.9 source freeze semantic identity mismatch")
    parent_hashes = successor.get("superseded_parent_sha256")
    if not isinstance(parent_hashes, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in parent_hashes.items()
    ):
        raise ValueError("V5.0 superseded-parent identities are invalid")
    if set(parent_hashes) != EXPECTED_SUPERSEDED or successor.get(
        "allowed_superseded_paths"
    ) != sorted(EXPECTED_SUPERSEDED):
        raise ValueError("V5.0 successor allowlist mismatch")
    source_parent_frozen = source_parent.get("frozen_files")
    if not isinstance(source_parent_frozen, dict) or any(
        source_parent_frozen.get(relative) != digest
        for relative, digest in parent_hashes.items()
    ):
        raise ValueError("V5.0 superseded-parent identity mismatch")
    for relative in transitions:
        path = source / relative
        if not path.is_file() or _has_symlink_component(source, relative):
            raise ValueError(f"V5.0 source path is unavailable: {relative}")
        if relative != str(FREEZE_RELATIVE) and _raw(path) != frozen.get(relative):
            raise ValueError(f"V5.0 source identity mismatch: {relative}")
    return freeze, tuple(transitions), dict(parent_hashes)


def _authenticate_target(
    target: Path,
    source: Path,
    transitions: tuple[str, ...],
    parent_hashes: dict[str, str],
) -> tuple[int, bool]:
    parent_freeze = target / PARENT_FREEZE_RELATIVE
    parent_artifact = target / PARENT_ARTIFACT_RELATIVE
    if (
        not parent_freeze.is_file()
        or _has_symlink_component(target, str(PARENT_FREEZE_RELATIVE))
        or _raw(parent_freeze) != PARENT_FREEZE_RAW
    ):
        raise ValueError("Target does not expose the exact V4.9 freeze")
    if (
        not parent_artifact.is_file()
        or _has_symlink_component(target, str(PARENT_ARTIFACT_RELATIVE))
        or _raw(parent_artifact) != PARENT_ARTIFACT_RAW
    ):
        raise ValueError("Target does not expose the exact V4.9 artifact")

    parent_contract = _read(parent_freeze)
    parent_frozen = parent_contract.get("frozen_files")
    if not isinstance(parent_frozen, dict) or not all(
        isinstance(relative, str) and isinstance(digest, str)
        for relative, digest in parent_frozen.items()
    ):
        raise ValueError("Exact V4.9 frozen-file map is unavailable")
    for relative, expected in parent_hashes.items():
        if parent_frozen.get(relative) != expected:
            raise ValueError(f"V4.9 successor identity mismatch: {relative}")

    immutable_parent = {
        relative: digest
        for relative, digest in parent_frozen.items()
        if relative not in parent_hashes
    }
    for relative, expected in immutable_parent.items():
        path = target / relative
        if (
            not path.is_file()
            or _has_symlink_component(target, relative)
            or _raw(path) != expected
        ):
            raise ValueError(
                f"Immutable V4.9 lineage unavailable or drifted: {relative}"
            )

    recognized_pre_release: dict[str, str] = {}
    target_v50_freeze = target / FREEZE_RELATIVE
    if target_v50_freeze.exists() or target_v50_freeze.is_symlink():
        if not target_v50_freeze.is_file() or _has_symlink_component(
            target, str(FREEZE_RELATIVE)
        ):
            raise ValueError("Target V5.0 freeze is not a regular file")
        observed_freeze_raw = _raw(target_v50_freeze)
        source_freeze_raw = _raw(source / FREEZE_RELATIVE)
        if observed_freeze_raw != source_freeze_raw:
            recognized_semantic = RECOGNIZED_STAGED_RELEASE_FREEZES.get(
                observed_freeze_raw
            )
            if recognized_semantic is None:
                raise ValueError("Target exposes an unrecognized V5.0 freeze")
            prior = _read(target_v50_freeze)
            prior_semantic = prior.get("freeze_contract_sha256")
            prior_transitions = prior.get("transition_files")
            prior_frozen = prior.get("frozen_files")
            if (
                prior_semantic != recognized_semantic
                or _semantic(prior, "freeze_contract_sha256")
                != recognized_semantic
                or not isinstance(prior_transitions, list)
                or tuple(prior_transitions) != EXPECTED_TRANSITIONS
                or not isinstance(prior_frozen, dict)
            ):
                raise ValueError("Recognized V5.0 pre-release contract is invalid")
            for relative in transitions:
                if relative == str(FREEZE_RELATIVE):
                    recognized_pre_release[relative] = observed_freeze_raw
                    continue
                digest = prior_frozen.get(relative)
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                ):
                    raise ValueError(
                        f"Recognized V5.0 pre-release identity is invalid: {relative}"
                    )
                recognized_pre_release[relative] = digest

    for relative in transitions:
        destination = target / relative
        if _has_symlink_component(target, relative):
            raise ValueError(f"Target path contains a symlink: {relative}")
        if not destination.exists():
            continue
        if not destination.is_file():
            raise ValueError(f"Target path is not a regular file: {relative}")
        observed = _raw(destination)
        allowed = {_raw(source / relative)}
        parent_hash = parent_hashes.get(relative)
        if parent_hash:
            allowed.add(parent_hash)
        pre_release_hash = recognized_pre_release.get(relative)
        if pre_release_hash:
            allowed.add(pre_release_hash)
        if observed not in allowed:
            raise ValueError(f"Target path has an unrecognized state: {relative}")
    return len(immutable_parent), bool(recognized_pre_release)


def install(source_root: Path, target_root: Path) -> dict[str, object]:
    source = source_root.resolve()
    target = target_root.resolve()
    freeze, transitions, parent_hashes = _authenticate_source(source)
    parent_immutable_path_count, migrated_recognized_pre_release = _authenticate_target(
        target, source, transitions, parent_hashes
    )

    backup_root = target / ".quantum-lab-v50-backups"
    if backup_root.is_symlink():
        raise ValueError("V5.0 backup root must not be a symlink")
    stage = Path(tempfile.mkdtemp(prefix="quantum-v50-stage-", dir=target.parent))
    backup = backup_root / uuid.uuid4().hex
    installed: list[str] = []
    overwritten: list[str] = []
    created: list[str] = []
    try:
        for relative in transitions:
            staged = stage / relative
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, staged)
        for relative in transitions:
            destination = target / relative
            staged = stage / relative
            if destination.exists():
                original = backup / relative
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, original)
                overwritten.append(relative)
            else:
                created.append(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(
                f".{destination.name}.v50-{uuid.uuid4().hex}.tmp"
            )
            shutil.copy2(staged, temporary)
            temporary.replace(destination)
            installed.append(relative)

        frozen = freeze["frozen_files"]
        drift = [
            relative
            for relative in transitions
            if relative != str(FREEZE_RELATIVE)
            and _raw(target / relative) != frozen.get(relative)
        ]
        target_freeze = _read(target / FREEZE_RELATIVE)
        if target_freeze.get("freeze_contract_sha256") != freeze.get(
            "freeze_contract_sha256"
        ):
            drift.append(str(FREEZE_RELATIVE))
        if drift:
            raise ValueError(f"Post-install identity drift: {drift}")
    except Exception:
        for relative in reversed(installed):
            destination = target / relative
            original = backup / relative
            if original.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
            elif relative in created and destination.exists():
                destination.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return {
        "installed": True,
        "idempotent_source_authenticated": True,
        "parent_immutable_lineage_authenticated": True,
        "parent_immutable_path_count": parent_immutable_path_count,
        "recognized_pre_release_migration": migrated_recognized_pre_release,
        "transition_file_count": len(transitions),
        "overwritten": overwritten,
        "created": created,
        "backup_directory": str(backup) if overwritten else None,
        "decision": freeze["scientific_decision"],
        "historical_epoch_gate": freeze["historical_epoch_gate"],
        "architecture_gate": freeze["architecture_gate"],
        "hardware_executable": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            install(args.source_root, args.target_root),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
