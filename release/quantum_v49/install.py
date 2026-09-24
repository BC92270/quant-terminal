"""Transactional, fail-closed installer for the compact V4.9 overlay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid


FREEZE_RELATIVE = Path("release/quantum_v49/freeze.json")
PARENT_FREEZE_RELATIVE = Path("FREEZE_CONTRACT_V4_8.json")
PARENT_ARTIFACT_RELATIVE = Path(
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
)
PARENT_FREEZE_RAW = "6d51bb5496bfdc412154ed84cf4e4a038b76d85b69ef3329f515db6cb969e5c8"
PARENT_ARTIFACT_RAW = "f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76"
V48_README_RAW = "6fca169f6197872cb41467a91e935512ed3b025f2573de1dc6c7f8c71b7a78df"
V48_UI_RAW = "61574e150e74a212c3af8e41dd17cc98b440aafdd7255cf9abda1b81c65d3f5c"
SUCCESSOR_PARENT_HASHES = {
    "quantum_research_lab/README.md": V48_README_RAW,
    "quantum_research_lab/ui.py": V48_UI_RAW,
}
ACCEPTED_PREVIOUS_V49_HASHES = {
    "quantum_research_lab/ui.py": "3515f038dd0025291c2f18327d8a4ead1f19f9bfb86ff54b4de4e8f99d529ad9",
    "quantum_research_lab/v49/tests/test_ui.py": "b349b3eb3ecec77f391dbe5af21d5d4ef77dfec598d2152eb1307dfd48b23055",
    "release/quantum_v49/freeze.json": "47709a799287bb320845a511eeca540218d0c343797de32621425f7575e69dd7",
    "release/quantum_v49/install.py": "f51af71054e65a23335bdb39a880ab21ac6587b7e20f587d495126a44e6209bb",
}


def _raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object: {path}")
    return payload


def _semantic(payload: dict[str, object], field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authenticate_source(source: Path) -> tuple[dict[str, object], tuple[str, ...]]:
    freeze_path = source / FREEZE_RELATIVE
    if not freeze_path.is_file() or freeze_path.is_symlink():
        raise ValueError("V4.9 freeze is unavailable")
    freeze = _read(freeze_path)
    if freeze.get("freeze_contract_sha256") != _semantic(freeze, "freeze_contract_sha256"):
        raise ValueError("V4.9 freeze self-hash mismatch")
    transitions = freeze.get("transition_files")
    frozen = freeze.get("frozen_files")
    if not isinstance(transitions, list) or not all(isinstance(item, str) for item in transitions):
        raise ValueError("V4.9 transition order is invalid")
    if not isinstance(frozen, dict):
        raise ValueError("V4.9 frozen-file map is invalid")
    for relative in transitions:
        path = source / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"V4.9 source path is unavailable: {relative}")
        if relative != str(FREEZE_RELATIVE) and _raw(path) != frozen.get(relative):
            raise ValueError(f"V4.9 source identity mismatch: {relative}")
    return freeze, tuple(transitions)


def _authenticate_target(target: Path, source: Path, transitions: tuple[str, ...]) -> None:
    parent_freeze = target / PARENT_FREEZE_RELATIVE
    parent_artifact = target / PARENT_ARTIFACT_RELATIVE
    if not parent_freeze.is_file() or _raw(parent_freeze) != PARENT_FREEZE_RAW:
        raise ValueError("Target does not expose the exact V4.8 freeze")
    if not parent_artifact.is_file() or _raw(parent_artifact) != PARENT_ARTIFACT_RAW:
        raise ValueError("Target does not expose the exact V4.8 artifact")
    for relative in transitions:
        destination = target / relative
        if not destination.exists():
            continue
        source_hash = _raw(source / relative)
        observed = _raw(destination)
        allowed = {source_hash}
        if relative in SUCCESSOR_PARENT_HASHES:
            allowed.add(SUCCESSOR_PARENT_HASHES[relative])
        if relative in ACCEPTED_PREVIOUS_V49_HASHES:
            allowed.add(ACCEPTED_PREVIOUS_V49_HASHES[relative])
        if observed not in allowed:
            raise ValueError(f"Target path has an unrecognized state: {relative}")


def install(source_root: Path, target_root: Path) -> dict[str, object]:
    source = source_root.resolve()
    target = target_root.resolve()
    freeze, transitions = _authenticate_source(source)
    _authenticate_target(target, source, transitions)

    stage = Path(tempfile.mkdtemp(prefix="quantum-v49-stage-", dir=target.parent))
    backup = target / ".quantum-lab-v49-backups" / uuid.uuid4().hex
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
            temporary = destination.with_name(f".{destination.name}.v49-{uuid.uuid4().hex}.tmp")
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
        "transition_file_count": len(transitions),
        "overwritten": overwritten,
        "created": created,
        "backup_directory": str(backup) if overwritten else None,
        "decision": freeze["scientific_decision"],
        "hardware_executable": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.source_root, args.target_root), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
