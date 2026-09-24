"""Build the compact deterministic V4.9 overlay and freeze contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


PARENT_FREEZE = Path("FREEZE_CONTRACT_V4_8.json")
FREEZE_PATH = Path("release/quantum_v49/freeze.json")
DIST_DIRECTORY = Path("release/quantum_v49/dist")
OVERLAY_NAME = "Quantum_Lab_V4_9_Deployment_Overlay.zip"
MANIFEST_NAME = "Quantum_Lab_V4_9_Release_Manifest.json"
PARENT_FREEZE_RAW = "6d51bb5496bfdc412154ed84cf4e4a038b76d85b69ef3329f515db6cb969e5c8"
PARENT_FREEZE_SEMANTIC = "6f6639f5f8ac3965f49b1107996718c6d8819637e6a65986013d5304cea6f2fa"
SUPERSEDED = {
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
}
TRANSITION_FILES = (
    ".vscode/settings.json",
    "QUANTUM_RELEASES.md",
    "quantum_research_lab/v49/__init__.py",
    "quantum_research_lab/v49/ARCHITECTURE.md",
    "quantum_research_lab/v49/PROTOCOL.json",
    "quantum_research_lab/v49/engine/__init__.py",
    "quantum_research_lab/v49/engine/checker.py",
    "quantum_research_lab/v49/engine/compiler.py",
    "quantum_research_lab/v49/engine/evaluator.py",
    "quantum_research_lab/v49/engine/validation.py",
    "quantum_research_lab/v49/snapshots/catalog.json",
    "quantum_research_lab/v49/snapshots/normalized.json",
    "quantum_research_lab/v49/snapshots/raw/README.md",
    "quantum_research_lab/v49/tests/__init__.py",
    "quantum_research_lab/v49/tests/test_app.py",
    "quantum_research_lab/v49/tests/test_release.py",
    "quantum_research_lab/v49/tests/test_science.py",
    "quantum_research_lab/v49/tests/test_ui.py",
    "quantum_research_lab/v49/ui.py",
    "outputs/quantum_phase3/v49_pre_hardware_admission/SEALED_V4_9_ADMISSION_ARTIFACT.json",
    "outputs/quantum_phase3/v49_pre_hardware_admission/SEALED_V4_9_VALIDATION_REPORT.json",
    "release/quantum_v49/DEPLOY.md",
    "release/quantum_v49/build.py",
    "release/quantum_v49/harness.py",
    "release/quantum_v49/install.py",
    "release/quantum_v49/freeze.json",
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
)


def _raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def _read(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object: {path}")
    return payload


def _verify_parent(root: Path) -> dict[str, object]:
    path = root / PARENT_FREEZE
    if not path.is_file() or path.is_symlink() or _raw(path) != PARENT_FREEZE_RAW:
        raise ValueError("Exact V4.8 freeze contract is unavailable")
    parent = _read(path)
    if parent.get("freeze_contract_sha256") != PARENT_FREEZE_SEMANTIC:
        raise ValueError("V4.8 freeze semantic identity mismatch")
    frozen = parent.get("frozen_files")
    if not isinstance(frozen, dict):
        raise ValueError("V4.8 frozen-file map is unavailable")
    for relative, expected in frozen.items():
        if relative in SUPERSEDED:
            continue
        target = root / relative
        if not target.is_file() or target.is_symlink() or _raw(target) != expected:
            raise ValueError(f"Immutable V4.8 path drift: {relative}")
    return parent


def build_freeze(root: Path) -> dict[str, object]:
    parent = _verify_parent(root)
    parent_files = dict(parent["frozen_files"])
    frozen_files = {
        relative: digest
        for relative, digest in parent_files.items()
        if relative not in SUPERSEDED
    }
    for relative in TRANSITION_FILES:
        if relative == str(FREEZE_PATH):
            continue
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"V4.9 transition path unavailable: {relative}")
        frozen_files[relative] = _raw(path)

    fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    transition_order = hashlib.sha256(
        json.dumps(list(TRANSITION_FILES), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    freeze: dict[str, object] = {
        "freeze_contract_version": "QUANTUM LAB V4.9 FREEZE CONTRACT · V1",
        "created_date": "2026-09-24",
        "parent": {
            "release": "V4.8",
            "freeze_raw_sha256": PARENT_FREEZE_RAW,
            "freeze_semantic_sha256": PARENT_FREEZE_SEMANTIC,
            "frozen_file_count": parent.get("frozen_file_count"),
        },
        "successor_policy": {
            "append_only": True,
            "immutable_parent_paths": len(parent_files) - len(SUPERSEDED),
            "allowed_superseded_paths": sorted(SUPERSEDED),
            "historical_paths_moved_or_renamed": False,
        },
        "transition_files": list(TRANSITION_FILES),
        "transition_order_sha256": transition_order,
        "frozen_files": dict(sorted(frozen_files.items())),
        "frozen_file_count": len(frozen_files),
        "frozen_paths_fingerprint_sha256": fingerprint,
        "scientific_decision": "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS",
        "claim_boundary": {
            "research_classification": "RESEARCH_ONLY",
            "hardware_executable": False,
            "provider_calls": 0,
            "network_calls": 0,
            "backend_run_calls": 0,
            "local_simulator_jobs_submitted": 0,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
        },
        "freeze_contract_sha256": "",
    }
    freeze["freeze_contract_sha256"] = _semantic(freeze, "freeze_contract_sha256")
    return freeze


def _write_zip(root: Path, target: Path) -> None:
    with zipfile.ZipFile(
        target,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative in TRANSITION_FILES:
            raw = (root / relative).read_bytes()
            info = zipfile.ZipInfo(relative, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, raw)


def build_release(root: Path) -> dict[str, object]:
    root = root.resolve()
    freeze = build_freeze(root)
    freeze_path = root / FREEZE_PATH
    freeze_path.parent.mkdir(parents=True, exist_ok=True)
    freeze_path.write_text(
        json.dumps(freeze, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dist = root / DIST_DIRECTORY
    dist.mkdir(parents=True, exist_ok=True)
    overlay = dist / OVERLAY_NAME
    _write_zip(root, overlay)
    manifest: dict[str, object] = {
        "release": "Quantum Lab V4.9",
        "overlay_path": str(DIST_DIRECTORY / OVERLAY_NAME),
        "overlay_raw_sha256": _raw(overlay),
        "overlay_size": overlay.stat().st_size,
        "freeze_path": str(FREEZE_PATH),
        "freeze_raw_sha256": _raw(freeze_path),
        "freeze_semantic_sha256": freeze["freeze_contract_sha256"],
        "transition_file_count": len(TRANSITION_FILES),
        "transition_order_sha256": freeze["transition_order_sha256"],
        "scientific_decision": freeze["scientific_decision"],
        "hardware_executable": False,
    }
    manifest_path = dist / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build_release(args.root), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
