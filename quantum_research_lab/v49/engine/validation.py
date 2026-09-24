"""Build and persist the independent V4.9 validation report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .checker import EXPECTED_CHECK_COUNT, read_json_strict, validate_artifact
from .evaluator import ARTIFACT_RELATIVE_PATH, default_root


REPORT_RELATIVE_PATH = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_VALIDATION_REPORT.json"
)


def _semantic(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "validation_report_sha256"}
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_validation_report(root: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    artifact_path = project_root / ARTIFACT_RELATIVE_PATH
    artifact = read_json_strict(artifact_path)
    raw_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    independent = validate_artifact(
        artifact,
        root=project_root,
        artifact_raw_sha256=raw_sha,
    )
    report: dict[str, Any] = {
        "report_version": "PHASE III · V4.9 INDEPENDENT VALIDATION REPORT · V1",
        "artifact_path": str(ARTIFACT_RELATIVE_PATH),
        "artifact_raw_sha256": raw_sha,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "expected_check_count": EXPECTED_CHECK_COUNT,
        "independent_checker": independent,
        "decision": (artifact.get("decisions") or {}).get("overall"),
        "research_classification": (artifact.get("claim_boundary") or {}).get("research_classification"),
        "hardware_executable": (artifact.get("claim_boundary") or {}).get("hardware_executable"),
        "valid": independent.get("valid") is True,
    }
    report["validation_report_sha256"] = _semantic(report)
    return report


def validate_and_write(
    root: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    report = build_validation_report(project_root)
    target = Path(output) if output is not None else project_root / REPORT_RELATIVE_PATH
    if not target.is_absolute():
        target = project_root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_and_write(args.root, args.output)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
