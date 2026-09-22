"""Fast end-to-end verifier for a deployed Quantum Lab V3.2 release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_artifact_guard import (
    EXPECTED_PARENT_RAW_SHA256,
    load_and_validate_dyadic_artifact,
)
from .phase3_circuit_validation import load_compiler_artifact
from .phase3_gate_compiler import compiler_source_sha256, load_compiler_spec


VERIFY_VERSION = "PHASE III · V3.2 RELEASE CHAIN VERIFIER · V1"


def verify_release_chain(
    parent_path: str | Path, artifact_path: str | Path
) -> dict[str, Any]:
    parent_report = load_and_validate_dyadic_artifact(
        parent_path, expected_raw_sha256=EXPECTED_PARENT_RAW_SHA256
    )
    errors: list[str] = []
    try:
        artifact, artifact_report = load_compiler_artifact(artifact_path)
    except Exception as exc:
        artifact = {}
        artifact_report = {"valid": False, "errors": [str(exc)]}
    try:
        spec = load_compiler_spec()
    except Exception as exc:
        spec = {}
        errors.append(f"Compiler spec: {exc}")

    entries = artifact.get("validation", {}).get("compilation_entries") or []
    gate_hashes = [str(entry.get("gate_ir_sha256", "")) for entry in entries]
    checks = {
        "artifact_internal_integrity": bool(artifact_report.get("valid")),
        "canonical_circuit_count_16": len(entries) == 16,
        "canonical_gate_hashes_complete": bool(
            len(gate_hashes) == 16
            and all(len(value) == 64 for value in gate_hashes)
        ),
        "compiler_source_hash_live": bool(
            artifact.get("compiler", {}).get("compiler_source_sha256")
            == compiler_source_sha256()
        ),
        "compiler_spec_hash_live": bool(
            artifact.get("compiler", {}).get("compiler_spec_sha256")
            == spec.get("gate_compiler_spec_sha256")
        ),
        "hardware_execution_false": bool(
            artifact.get("claim_boundary", {}).get("hardware_executable") is False
            and artifact.get("claim_boundary", {}).get("qpu_submission_enabled")
            is False
        ),
        "parent_guard": bool(parent_report.get("valid")),
        "parent_raw_hash_chain": bool(
            artifact.get("parent", {}).get("raw_file_sha256")
            == (parent_report.get("hashes") or {}).get("raw_file_sha256")
            == EXPECTED_PARENT_RAW_SHA256
        ),
        "validation_ladder_pass": bool(
            artifact.get("validation", {}).get("overall_pass") is True
            and all(
                bool(value)
                for value in (
                    artifact.get("validation", {}).get("checks") or {}
                ).values()
            )
        ),
    }
    errors.extend(str(item) for item in artifact_report.get("errors", []))
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "parent_raw_sha256": (parent_report.get("hashes") or {}).get(
            "raw_file_sha256"
        ),
        "valid": bool(all(checks.values()) and not errors),
        "validation_manifest_sha256": artifact.get("validation", {}).get(
            "validation_manifest_sha256"
        ),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a deployed V3.2 chain.")
    parser.add_argument("parent", type=Path)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)
    report = verify_release_chain(args.parent, args.artifact)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VERIFY_VERSION", "verify_release_chain"]
