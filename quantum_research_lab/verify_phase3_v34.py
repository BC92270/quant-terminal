"""Fast independent verifier for a deployed Quantum Lab V3.4 release chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_algorithmic_contract import PROFILE_DUAL_GUARD, TOPOLOGY_COMPLETE
from .phase3_gate_compiler import canonical_json_sha256
from .phase3_native_mixer import (
    elementary_schedule_sha256,
    native_mixer_source_sha256,
)
from .phase3_optimized_oracle import load_v34_spec, optimizer_source_sha256
from .phase3_v34_validation import (
    load_optimized_native_artifact,
    validation_source_sha256,
    verifier_source_sha256,
    verify_v33_freeze_snapshot,
    verify_v33_parent_chain,
)


VERIFY_VERSION = "PHASE III · V3.4 RELEASE CHAIN VERIFIER · V1"


def _safe_sha256(path: str | Path) -> tuple[str | None, str | None]:
    try:
        import hashlib

        return hashlib.sha256(Path(path).read_bytes()).hexdigest(), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def verify_release_chain(
    v31_path: str | Path,
    v32_path: str | Path,
    v33_path: str | Path,
    v33_freeze_path: str | Path,
    v34_path: str | Path,
) -> dict[str, Any]:
    """Verify identities, sources, evidence gates and fail-closed boundaries."""

    errors: list[str] = []
    try:
        spec = load_v34_spec()
    except Exception as exc:
        spec = {}
        errors.append(f"V3.4 spec: {exc}")
    try:
        artifact, integrity = load_optimized_native_artifact(v34_path)
    except Exception as exc:
        artifact = {}
        integrity = {"valid": False, "errors": [str(exc)]}
    try:
        v33_report = verify_v33_parent_chain(v31_path, v32_path, v33_path)
    except Exception as exc:
        v33_report = {"valid": False, "errors": [str(exc)], "checks": {}}
    try:
        freeze_report = verify_v33_freeze_snapshot(
            Path(v31_path).resolve().parent,
            v33_freeze_path,
            parent_report=v33_report,
            superseded_files=(
                (load_v34_spec().get("lineage_change_control") or {}).get(
                    "v33_frozen_files_superseded_after_v34_artifact", []
                )
            ),
        )
    except Exception as exc:
        freeze_report = {"valid": False, "errors": [str(exc)], "checks": {}}

    parent_spec = spec.get("parent_contract") or {}
    parents = artifact.get("parents") or {}
    validation = artifact.get("validation") or {}
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    resources = artifact.get("resource_envelopes") or {}
    canonical = (resources.get("ledgers") or {}).get(
        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
    )
    comparisons = resources.get("comparison_vs_v33") or []
    v31_raw, v31_error = _safe_sha256(v31_path)
    v32_raw, v32_error = _safe_sha256(v32_path)
    v33_raw, v33_error = _safe_sha256(v33_path)
    v34_raw, v34_error = _safe_sha256(v34_path)
    resource_core = {
        key: value for key, value in resources.items() if key != "resource_manifest_sha256"
    }
    checks = {
        "artifact_internal_integrity": bool(integrity.get("valid")),
        "v34_spec_self_hash_live": bool(
            spec
            and spec.get("v34_spec_sha256")
            == canonical_json_sha256(
                {
                    key: value
                    for key, value in spec.items()
                    if key not in {"v34_spec_sha", "v34_spec_sha256"}
                }
            )
            == artifact.get("optimizer", {}).get("spec_sha256")
        ),
        "optimizer_and_native_sources_live": bool(
            validation.get("optimizer_source_sha256") == optimizer_source_sha256()
            and validation.get("native_mixer_source_sha256")
            == native_mixer_source_sha256()
        ),
        "validation_and_verifier_sources_live": bool(
            validation.get("validation_source_sha256") == validation_source_sha256()
            and validation.get("verifier_source_sha256") == verifier_source_sha256()
        ),
        "elementary_schedule_live": bool(
            artifact.get("native_lowering", {}).get("schedule_sha256")
            == elementary_schedule_sha256()
            == artifact.get("construction", {}).get(
                "controlled_xy_schedule_sha256"
            )
        ),
        "v33_release_chain_13_of_13": bool(
            v33_report.get("valid")
            and len(v33_report.get("checks") or {}) == 13
            and all((v33_report.get("checks") or {}).values())
        ),
        "v33_freeze_5_of_5": bool(
            freeze_report.get("valid")
            and len(freeze_report.get("checks") or {}) == 5
            and all((freeze_report.get("checks") or {}).values())
        ),
        "all_parent_raw_hashes_exact": bool(
            v31_raw
            == parents.get("v31_raw_file_sha256")
            == parent_spec.get("expected_parent_v31_raw_file_sha256")
            and v32_raw
            == parents.get("v32_raw_file_sha256")
            == parent_spec.get("expected_parent_v32_raw_file_sha256")
            and v33_raw
            == parents.get("v33_raw_file_sha256")
            == parent_spec.get("expected_parent_v33_artifact_raw_file_sha256")
        ),
        "validation_ladder_9_of_9": bool(
            validation.get("overall_pass") is True
            and len(validation.get("checks") or {}) == 9
            and all(bool(value) for value in (validation.get("checks") or {}).values())
        ),
        "interval_and_actual_boundaries_pass": bool(
            validation.get("interval_identity", {}).get("passed")
            and validation.get("actual_constraint_boundaries", {}).get("passed")
            and validation.get("actual_constraint_boundaries", {}).get(
                "constraint_count"
            )
            == 56
        ),
        "n40_differential_scope_exact": bool(
            validation.get("n40_optimized_oracle", {}).get("passed")
            and validation.get("n40_optimized_oracle", {}).get(
                "total_nontrivial_witness_swaps"
            )
            == 2400
            and validation.get("n40_optimized_oracle", {}).get(
                "total_gate_level_cases"
            )
            == 48
        ),
        "native_matrix_scope_exact": bool(
            validation.get("native_c2xy", {}).get("passed")
            and validation.get("native_c2xy", {}).get("total_basis_angle_cases")
            == 96
            and validation.get("native_c2xy", {}).get(
                "maximum_dirty_scratch_probability"
            )
            == 0.0
        ),
        "resource_manifest_exact": bool(
            resources.get("resource_manifest_sha256")
            == canonical_json_sha256(resource_core)
            == validation.get("resource_manifest_sha256")
        ),
        "canonical_resource_scope_exact": bool(
            canonical.get("edge_count") == 780
            and canonical.get("oracle_calls") == 1562
            and canonical.get("backend_transpilation_status") == "NOT_RUN"
            and canonical.get("maxima", {}).get("logical_qubits_sequential_reuse")
            == 118
            and canonical.get("per_edge", {})
            .get("abstract_elementary", {})
            .get("gate_count")
            == 12
        ),
        "resource_reduction_all_eight_seeds": bool(
            len(comparisons) == 8
            and all(row.get("logical_qubit_reduction") == 2 for row in comparisons)
            and all(
                int(
                    row.get(
                        "provider_neutral_gate_reduction_after_12_gate_c2xy_lowering",
                        0,
                    )
                )
                > 0
                and int(row.get("t_subtotal_reduction_after_c2xy_ccx_cost", 0)) > 0
                for row in comparisons
            )
        ),
        "negative_connectivity_result_retained": bool(
            str(decisions.get("ring_topology", "")).startswith("REJECTED")
            and decisions.get("complete_global_connectivity") == "INDETERMINATE"
        ),
        "rotation_and_backend_boundary_retained": bool(
            decisions.get("fault_tolerant_rotation_synthesis") == "NOT_ESTIMATED"
            and decisions.get("backend_native_lowering") == "NOT_RUN"
        ),
        "hardware_and_advantage_fail_closed": bool(
            boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and decisions.get("hardware_execution") == "BLOCKED · ZERO JOBS"
            and decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }
    errors.extend(str(item) for item in integrity.get("errors", []))
    errors.extend(str(item) for item in v33_report.get("errors", []))
    errors.extend(str(item) for item in freeze_report.get("errors", []))
    for label, error in (
        ("V3.1", v31_error),
        ("V3.2", v32_error),
        ("V3.3", v33_error),
        ("V3.4", v34_error),
    ):
        if error:
            errors.append(f"{label} raw file: {error}")
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "artifact_raw_file_sha256": v34_raw,
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
    parser = argparse.ArgumentParser(description="Verify a deployed V3.4 release chain.")
    parser.add_argument("v31_parent", type=Path)
    parser.add_argument("v32_parent", type=Path)
    parser.add_argument("v33_parent", type=Path)
    parser.add_argument("v33_freeze", type=Path)
    parser.add_argument("v34_artifact", type=Path)
    args = parser.parse_args(argv)
    report = verify_release_chain(
        args.v31_parent,
        args.v32_parent,
        args.v33_parent,
        args.v33_freeze,
        args.v34_artifact,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VERIFY_VERSION", "verify_release_chain"]
