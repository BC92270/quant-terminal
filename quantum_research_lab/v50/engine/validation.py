"""Generate and independently validate the sealed V5.0 offline artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from .checker import EXPECTED_CHECK_COUNT, validate_artifact
from .evaluator import ARTIFACT, build_control_plane_artifact, default_root
from .evidence import raw_file_sha256, semantic_sha256


REPORT = Path(
    "outputs/quantum_phase3/v50_hardware_evidence_control/"
    "SEALED_V5_0_VALIDATION_REPORT.json"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def run_validation(
    root: str | Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    artifact = build_control_plane_artifact(project_root)
    artifact_path = project_root / ARTIFACT
    if write:
        _write_json(artifact_path, artifact)
    encoded = (
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")
    artifact_raw = hashlib.sha256(encoded).hexdigest()
    independent = validate_artifact(
        artifact,
        root=project_root,
        artifact_raw_sha256=artifact_raw,
    )
    deterministic_rebuild = build_control_plane_artifact(project_root) == artifact
    report: dict[str, Any] = {
        "report_version": "QUANTUM LAB V5.0 VALIDATION REPORT · V1",
        "artifact_path": str(ARTIFACT),
        "artifact_raw_sha256": artifact_raw,
        "artifact_sha256": artifact["artifact_sha256"],
        "deterministic_rebuild": deterministic_rebuild,
        "independent_check_count": independent["check_count"],
        "independent_expected_check_count": EXPECTED_CHECK_COUNT,
        "independent_checker": independent,
        "scientific_decision": artifact["decisions"]["overall"],
        "historical_epoch_gate": artifact["historical_epoch_gate"]["status"],
        "architecture_gate": artifact["architecture_gate"]["status"],
        "hardware_executable": False,
        "provider_calls": 0,
        "network_calls": 0,
        "qpu_jobs_submitted": 0,
        "valid": deterministic_rebuild and independent.get("valid") is True,
    }
    report["validation_report_sha256"] = semantic_sha256(
        report, exclude=("validation_report_sha256",)
    )
    if write:
        _write_json(project_root / REPORT, report)
        if raw_file_sha256(artifact_path) != artifact_raw:
            raise ValueError("Written artifact raw identity mismatch")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    report = run_validation(args.root, write=not args.no_write)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
