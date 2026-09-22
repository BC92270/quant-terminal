"""Fast end-to-end verifier for a deployed Quantum Lab V3.3 release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_algorithmic_contract import (
    EXPECTED_V31_RAW_SHA256,
    EXPECTED_V32_ARTIFACT_SHA256,
    EXPECTED_V32_RAW_SHA256,
    PROFILE_DUAL_GUARD,
    TOPOLOGY_COMPLETE,
    algorithm_source_sha256,
    load_algorithm_spec,
    raw_file_sha256,
)
from .phase3_algorithmic_validation import (
    load_algorithmic_artifact,
    validation_source_sha256,
    verifier_source_sha256,
)
from .verify_phase3_v32 import verify_release_chain as verify_v32_release_chain


VERIFY_VERSION = "PHASE III · V3.3 RELEASE CHAIN VERIFIER · V1"


def _safe_raw_file_sha256(path: str | Path) -> tuple[str | None, str | None]:
    try:
        return raw_file_sha256(path), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def verify_release_chain(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
) -> dict[str, Any]:
    errors: list[str] = []
    v31_raw, v31_raw_error = _safe_raw_file_sha256(v31_path)
    v32_raw, v32_raw_error = _safe_raw_file_sha256(v32_path)
    try:
        v32_report = verify_v32_release_chain(v31_path, v32_path)
    except Exception as exc:
        v32_report = {"valid": False, "errors": [str(exc)]}
    try:
        spec = load_algorithm_spec()
    except Exception as exc:
        spec = {}
        errors.append(f"V3.3 spec: {exc}")
    try:
        artifact, integrity = load_algorithmic_artifact(v33_path)
    except Exception as exc:
        artifact = {}
        integrity = {"valid": False, "errors": [str(exc)]}

    decisions = artifact.get("decisions") or {}
    resources = artifact.get("resource_envelopes") or {}
    canonical = (resources.get("ledgers") or {}).get(
        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
    )
    validation = artifact.get("validation") or {}
    parents = artifact.get("parents") or {}
    checks = {
        "artifact_internal_integrity": bool(integrity.get("valid")),
        "algorithm_source_hash_live": bool(
            artifact.get("algorithm", {}).get("algorithm_source_sha256")
            == algorithm_source_sha256()
        ),
        "algorithm_spec_hash_live": bool(
            artifact.get("algorithm", {}).get("algorithm_spec_sha256")
            == spec.get("algorithm_contract_spec_sha256")
        ),
        "validation_and_verifier_source_hashes_live": bool(
            validation.get("validation_source_sha256")
            == validation_source_sha256()
            and validation.get("verifier_source_sha256")
            == verifier_source_sha256()
        ),
        "v31_parent_raw_hash": bool(
            v31_raw
            == parents.get("v31_raw_file_sha256")
            == EXPECTED_V31_RAW_SHA256
        ),
        "v32_parent_release_chain": bool(v32_report.get("valid")),
        "v32_parent_raw_hash": bool(
            v32_raw
            == parents.get("v32_raw_file_sha256")
            == EXPECTED_V32_RAW_SHA256
        ),
        "v32_parent_semantic_hash": bool(
            parents.get("v32_artifact_sha256")
            == EXPECTED_V32_ARTIFACT_SHA256
        ),
        "validation_ladder_pass": bool(
            validation.get("overall_pass") is True
            and len(validation.get("checks") or {}) == 8
            and all(bool(value) for value in (validation.get("checks") or {}).values())
        ),
        "invariance_and_cleanup_pass": bool(
            str(decisions.get("feasibility_invariance", "")).startswith("PASS")
            and decisions.get("guard_ancilla_cleanup") == "PASS"
        ),
        "connectivity_boundary_retained": bool(
            str(decisions.get("ring_topology", "")).startswith("REJECTED")
            and decisions.get("complete_global_connectivity") == "INDETERMINATE"
        ),
        "resource_boundary_retained": bool(
            canonical.get("edge_count") == 780
            and canonical.get("oracle_calls") == 1562
            and canonical.get("controlled_xy_native_cost") == "NOT_ESTIMATED"
            and canonical.get("backend_transpilation_status") == "NOT_RUN"
        ),
        "hardware_fail_closed": bool(
            artifact.get("claim_boundary", {}).get("hardware_executable") is False
            and artifact.get("claim_boundary", {}).get("qpu_submission_enabled")
            is False
            and decisions.get("hardware_execution") == "BLOCKED · ZERO JOBS"
            and decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }
    errors.extend(str(item) for item in integrity.get("errors", []))
    errors.extend(str(item) for item in v32_report.get("errors", []))
    if v31_raw_error:
        errors.append(f"V3.1 raw file: {v31_raw_error}")
    if v32_raw_error:
        errors.append(f"V3.2 raw file: {v32_raw_error}")
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "artifact_raw_file_sha256": (
            _safe_raw_file_sha256(v33_path)[0]
        ),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "resource_manifest_sha256": resources.get("resource_manifest_sha256"),
        "valid": bool(all(checks.values()) and not errors),
        "validation_manifest_sha256": validation.get("validation_manifest_sha256"),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a deployed V3.3 chain.")
    parser.add_argument("v31_parent", type=Path)
    parser.add_argument("v32_parent", type=Path)
    parser.add_argument("v33_artifact", type=Path)
    args = parser.parse_args(argv)
    report = verify_release_chain(
        args.v31_parent,
        args.v32_parent,
        args.v33_artifact,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VERIFY_VERSION", "verify_release_chain"]
