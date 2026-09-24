"""Build the deterministic V5.0 overlay and append-only freeze contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile


PARENT_FREEZE = Path("release/quantum_v49/freeze.json")
FREEZE_PATH = Path("release/quantum_v50/freeze.json")
DIST_DIRECTORY = Path("release/quantum_v50/dist")
OVERLAY_NAME = "Quantum_Lab_V5_0_Deployment_Overlay.zip"
MANIFEST_NAME = "Quantum_Lab_V5_0_Release_Manifest.json"
PARENT_FREEZE_RAW = "7c34668559955edde109820dc400f630621f18086ae47f4de8d2259ef6c97823"
PARENT_FREEZE_SEMANTIC = "f5168ff42d8a72111a0e740e8675203e1382c0bcb6a23d1d12b9e9c3c9d2f597"
SUPERSEDED = {
    "QUANTUM_RELEASES.md",
    "quantum_research_lab/README.md",
    "quantum_research_lab/ui.py",
}
TRANSITION_FILES = (
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


def _verify_parent(root: Path) -> dict[str, object]:
    path = root / PARENT_FREEZE
    if not path.is_file() or path.is_symlink() or _raw(path) != PARENT_FREEZE_RAW:
        raise ValueError("Exact V4.9 freeze contract is unavailable")
    parent = _read(path)
    if parent.get("freeze_contract_sha256") != PARENT_FREEZE_SEMANTIC:
        raise ValueError("V4.9 freeze embedded semantic identity mismatch")
    if _semantic(parent, "freeze_contract_sha256") != PARENT_FREEZE_SEMANTIC:
        raise ValueError("V4.9 freeze semantic identity mismatch")
    frozen = parent.get("frozen_files")
    if not isinstance(frozen, dict):
        raise ValueError("V4.9 frozen-file map is unavailable")
    for relative, expected in frozen.items():
        if relative in SUPERSEDED:
            continue
        target = root / relative
        if not target.is_file() or target.is_symlink() or _raw(target) != expected:
            raise ValueError(f"Immutable V4.9 path drift: {relative}")
    return parent


def build_freeze(root: Path) -> dict[str, object]:
    parent = _verify_parent(root)
    parent_files = dict(parent["frozen_files"])
    frozen_files = {
        relative: digest for relative, digest in parent_files.items() if relative not in SUPERSEDED
    }
    for relative in TRANSITION_FILES:
        if relative == str(FREEZE_PATH):
            continue
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"V5.0 transition path unavailable: {relative}")
        frozen_files[relative] = _raw(path)

    fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    transition_order = hashlib.sha256(
        json.dumps(list(TRANSITION_FILES), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    freeze: dict[str, object] = {
        "freeze_contract_version": "QUANTUM LAB V5.0 FREEZE CONTRACT · V1",
        "created_date": "2026-09-24",
        "parent": {
            "release": "V4.9",
            "freeze_path": str(PARENT_FREEZE),
            "freeze_raw_sha256": PARENT_FREEZE_RAW,
            "freeze_semantic_sha256": PARENT_FREEZE_SEMANTIC,
            "frozen_file_count": parent.get("frozen_file_count"),
        },
        "successor_policy": {
            "append_only": True,
            "immutable_parent_paths": len(parent_files) - len(SUPERSEDED),
            "allowed_superseded_paths": sorted(SUPERSEDED),
            "superseded_parent_sha256": {
                relative: parent_files[relative] for relative in sorted(SUPERSEDED)
            },
            "historical_paths_moved_or_renamed": False,
        },
        "transition_files": list(TRANSITION_FILES),
        "transition_order_sha256": transition_order,
        "frozen_files": dict(sorted(frozen_files.items())),
        "frozen_file_count": len(frozen_files),
        "frozen_paths_fingerprint_sha256": fingerprint,
        "scientific_decision": "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO",
        "historical_epoch_gate": "PASS",
        "architecture_gate": "FAIL",
        "claim_boundary": {
            "research_classification": "RESEARCH_ONLY",
            "current_hardware_evidence": False,
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
        json.dumps(freeze, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    dist = root / DIST_DIRECTORY
    dist.mkdir(parents=True, exist_ok=True)
    overlay = dist / OVERLAY_NAME
    _write_zip(root, overlay)
    manifest: dict[str, object] = {
        "release": "Quantum Lab V5.0",
        "overlay_path": str(DIST_DIRECTORY / OVERLAY_NAME),
        "overlay_raw_sha256": _raw(overlay),
        "overlay_size": overlay.stat().st_size,
        "freeze_path": str(FREEZE_PATH),
        "freeze_raw_sha256": _raw(freeze_path),
        "freeze_semantic_sha256": freeze["freeze_contract_sha256"],
        "transition_file_count": len(TRANSITION_FILES),
        "transition_order_sha256": freeze["transition_order_sha256"],
        "scientific_decision": freeze["scientific_decision"],
        "historical_epoch_gate": "PASS",
        "architecture_gate": "FAIL",
        "hardware_executable": False,
    }
    manifest_path = dist / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
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
