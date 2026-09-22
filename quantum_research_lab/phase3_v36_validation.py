"""Deterministic validation ladder for the provider-free V3.6 engine."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_v36_algorithmic_reduction import (
    EXPECTED_SEEDS,
    SEMANTICS_CHANGED,
    SEMANTICS_FEASIBLE,
    SEMANTICS_FULL,
    SEMANTICS_UNPROVEN,
    authenticate_parent_chain,
    build_v36_artifact,
    canonical_json_sha256,
    load_v36_spec,
    validate_v36_artifact,
)


VALIDATION_VERSION = "PHASE III · V3.6 STRUCTURAL COST + REWRITE VALIDATION · V1"
EXPECTED_ORACLE_CNOT = {
    1103: 92_113_403,
    2207: 94_092_865,
    3301: 94_836_617,
    4409: 92_681_391,
    5501: 95_650_135,
    6607: 92_095_707,
    7703: 95_619_337,
    8807: 92_971_589,
}


def validation_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run_v36_validation() -> dict[str, Any]:
    spec = load_v36_spec()
    parent = authenticate_parent_chain(spec)
    artifact = build_v36_artifact()
    duplicate = build_v36_artifact()
    integrity = validate_v36_artifact(artifact)
    tampered = copy.deepcopy(artifact)
    tampered["decisions"]["global_impossibility"] = "CLAIMED"
    tamper_report = validate_v36_artifact(tampered)
    attribution = artifact["structural_cost_attribution"]
    summary = attribution["summary"]
    rows = attribution["rows"]
    guard = artifact["guard_scope_proof"]
    incremental = artifact["incremental_exposure_audit"]
    lanes = artifact["rewrite_admission"]["lanes"]
    boundary = artifact["claim_boundary"]
    observed_oracles = {int(row["seed"]): int(row["per_oracle_cnot"]) for row in rows}
    allowed_semantics = {
        SEMANTICS_FULL,
        SEMANTICS_FEASIBLE,
        SEMANTICS_CHANGED,
        SEMANTICS_UNPROVEN,
        "NOT_EVALUATED",
    }
    checks = {
        "spec_self_hash_and_provider_free_boundary": bool(
            len(spec["v36_spec_sha256"]) == 64
            and spec["claim_boundary"]["research_classification"] == "RESEARCH_ONLY"
            and spec["claim_boundary"]["provider_calls"] == 0
            and spec["claim_boundary"]["qpu_submission_enabled"] is False
        ),
        "v31_v34_v35_parent_chain_exact": bool(
            parent["valid"]
            and len(parent["comparisons"]) == 15
            and all(row["valid"] for row in parent["comparisons"].values())
        ),
        "all_eight_cnot_equations_exact": bool(
            tuple(row["seed"] for row in rows) == EXPECTED_SEEDS
            and summary["all_eight_equations_exact"]
            and all(row["division_remainder"] == 0 for row in rows)
            and all(row["reconstructed_total_cnot"] == row["total_cnot"] for row in rows)
        ),
        "per_oracle_cnot_identities_exact": observed_oracles == EXPECTED_ORACLE_CNOT,
        "oracle_range_and_pair_floor_exact": bool(
            summary["per_oracle_cnot_min"] == 92_095_707
            and summary["per_oracle_cnot_max"] == 95_650_135
            and summary["required_compute_uncompute_pair_cnot_floor"] == 184_191_414
        ),
        "provider_neutral_headroom_budget_rejects_pair_floor": bool(
            summary["selected_model_budget_cnot"] == 2_500_000
            and summary["pair_floor_exceeds_budget"]
            and summary["pair_floor_multiple_of_budget"] == 73.6765656
        ),
        "single_guard_scope_is_exactly_bounded": bool(
            guard["total_cases"] == 8
            and guard["feasible_support_cases"] == 4
            and guard["equal_on_all_feasible_support_cases"]
            and guard["different_outside_feasible_support"]
            and guard["semantic_classification"] == SEMANTICS_FEASIBLE
        ),
        "incremental_delta_all_43680_rows_exact": bool(
            incremental["passed"]
            and incremental["total_swap_cases"] == 6_240
            and incremental["total_constraint_row_cases"] == 43_680
            and all(incremental["checks"].values())
        ),
        "incremental_lane_remains_unadmitted": bool(
            lanes["INCREMENTAL_EXPOSURE_GUARD"]["semantic_classification"]
            == SEMANTICS_UNPROVEN
            and lanes["INCREMENTAL_EXPOSURE_GUARD"]["admission_decision"] == "BLOCKED"
            and lanes["INCREMENTAL_EXPOSURE_GUARD"]["selected_model_cnot"]
            == "NOT_ESTIMATED"
        ),
        "changed_semantics_lanes_are_explicit": bool(
            lanes["TOPOLOGY_ONLY_PRUNED"]["semantic_classification"]
            == SEMANTICS_CHANGED
            and lanes["BLOCK_COORDINATE"]["semantic_classification"]
            == SEMANTICS_CHANGED
            and lanes["BLOCK_COORDINATE"]["inherit_v34_equivalence"] is False
            and all(
                row["semantic_classification"] in allowed_semantics
                for row in lanes.values()
            )
        ),
        "topology_only_negative_result_retained": bool(
            artifact["decisions"]["overall"]
            == "ARCHITECTURE_REWRITE_REQUIRED"
            and
            artifact["decisions"]["topology_only"]
            == "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE"
            and lanes["TOPOLOGY_ONLY_PRESERVE_OPERATOR"]["admission_decision"]
            == "REJECTED"
            and lanes["TOPOLOGY_ONLY_PRUNED"]["admission_decision"] == "REJECTED"
        ),
        "artifact_deterministic_and_tamper_evident": bool(
            artifact["artifact_sha256"] == duplicate["artifact_sha256"]
            and integrity["valid"]
            and not tamper_report["valid"]
            and tamper_report["errors"]
        ),
        "backend_hardware_advantage_fail_closed": bool(
            lanes["BACKEND_NATIVE"]["admission_decision"] == "NOT_RUN"
            and boundary["provider_sdk_imported"] is False
            and boundary["provider_credentials_read"] is False
            and boundary["provider_calls"] == 0
            and boundary["backend_transpilation"] == "NOT_RUN"
            and boundary["hardware_executable"] is False
            and boundary["qpu_submission_enabled"] is False
            and boundary["qpu_jobs_submitted"] == 0
            and boundary["global_impossibility"] == "NOT_CLAIMED"
            and boundary["quantum_advantage"] == "NOT_CLAIMED"
        ),
    }
    detail = {
        "artifact_sha256": artifact["artifact_sha256"],
        "incremental_audit_sha256": incremental["incremental_audit_sha256"],
        "observed_per_oracle_cnot": observed_oracles,
        "rewrite_manifest_sha256": artifact["rewrite_admission"][
            "rewrite_manifest_sha256"
        ],
        "structural_manifest_sha256": attribution["structural_manifest_sha256"],
    }
    manifest_core = {
        "checks": checks,
        "detail": detail,
        "spec_sha256": spec["v36_spec_sha256"],
        "validation_source_sha256": validation_source_sha256(),
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **manifest_core,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": canonical_json_sha256(manifest_core),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the V3.6 reduction engine.")
    parser.parse_args(argv)
    report = run_v36_validation()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_ORACLE_CNOT",
    "VALIDATION_VERSION",
    "run_v36_validation",
    "validation_source_sha256",
]
