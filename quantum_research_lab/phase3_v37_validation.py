"""Independent deterministic validation ladder for Quantum Lab V3.7."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .phase3_v37_reversible_compiler import (
    EXPECTED_V36_ARTIFACT_RAW_SHA256,
    EXPECTED_V36_ARTIFACT_SHA256,
    NUMERIC_TOLERANCE,
    apply_gate_sequence,
    authenticate_v36_parent,
    build_v37_artifact,
    compile_edge,
    decode_basis_state,
    encode_basis_state,
    exact_k_states,
    exposure_values,
    load_v37_artifact,
    load_v37_spec,
    portfolio_feasible,
    prototype_fixture,
    resource_ledger,
    transition_pairs,
    validate_v37_artifact,
)


VALIDATION_VERSION = "PHASE III · V3.7 REVERSIBLE PROTOTYPE VALIDATION · V1"


def validation_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run_v37_validation() -> dict[str, Any]:
    spec = load_v37_spec()
    parent = authenticate_v36_parent()
    fixture = prototype_fixture()
    artifact = build_v37_artifact()
    integrity = validate_v37_artifact(artifact)
    try:
        sealed_artifact, sealed_integrity = load_v37_artifact()
        sealed_artifact_exact = sealed_artifact == artifact
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sealed_artifact = {}
        sealed_integrity = {"valid": False, "errors": [str(exc)]}
        sealed_artifact_exact = False
    tampered = copy.deepcopy(artifact)
    tampered["claim_boundary"]["hardware_executable"] = True
    tamper_report = validate_v37_artifact(tampered)

    differential = artifact["differential_evidence"]
    compiler = artifact["compiler_evidence"]
    ledger = artifact["resource_ledger"]
    totals = ledger["complete_edge_scan"]
    decisions = artifact["decisions"]
    boundary = artifact["claim_boundary"]
    transitions = artifact["coherent_transition_ledger"]
    feasible = [state for state in exact_k_states(fixture) if portfolio_feasible(state, fixture)]
    pair_counts = {
        f"{edge[0]}-{edge[1]}": len(transition_pairs((int(edge[0]), int(edge[1])), fixture))
        for edge in fixture["edges"]
    }

    # Independent spot proof of coherent cache movement on a non-trivial pair.
    compiled = compile_edge((0, 1), fixture)
    witness_pair = compiled["pairs"][0]
    beta = 0.7853981633974483
    left = int(witness_pair["left_basis"])
    right = int(witness_pair["right_basis"])
    coherent = apply_gate_sequence({left: 1.0 + 0.0j}, compiled["gates"], beta)
    coherent_support = {index for index, amplitude in coherent.items() if abs(amplitude) > NUMERIC_TOLERANCE}
    coherent_cache_exact = coherent_support == {left, right} and all(
        decode_basis_state(index, fixture)["cache_consistent"] for index in coherent_support
    )

    ledger_duplicate = resource_ledger(fixture)
    checks = {
        "spec_self_hash_fixture_and_boundaries_are_exact": bool(
            len(spec["v37_spec_sha256"]) == 64
            and spec["fixture_contract"]
            == {key: value for key, value in fixture.items() if key != "fixture_sha256"}
            and spec["claim_boundary"]["research_classification"] == "RESEARCH_ONLY"
            and spec["claim_boundary"]["hardware_executable"] is False
            and spec["claim_boundary"]["selected_model_cnot"] == "NOT_ESTIMATED"
        ),
        "v36_parent_semantic_and_raw_identity_exact": bool(
            parent["valid"]
            and parent["comparisons"]["semantic_artifact_sha256"]["actual"]
            == EXPECTED_V36_ARTIFACT_SHA256
            and parent["comparisons"]["raw_file_sha256"]["actual"]
            == EXPECTED_V36_ARTIFACT_RAW_SHA256
        ),
        "fixture_is_registered_synthetic_n4_k2_only": bool(
            fixture["fixture_id"] == "V37_SYNTHETIC_EXACT_K_N4_K2_V1"
            and fixture["classification"] == "SYNTHETIC_COMPILER_FIXTURE · PROTOTYPE_ONLY"
            and fixture["n"] == 4
            and fixture["k"] == 2
        ),
        "exact_k_and_feasible_state_cardinalities_are_exact": bool(
            len(exact_k_states(fixture)) == 6 and len(feasible) == 4
        ),
        "differential_delta_and_predicate_ladder_passes": bool(
            differential["passed"]
            and differential["portfolio_edge_cases"] == 36
            and differential["constraint_row_cases"] == 72
            and all(differential["checks"].values())
        ),
        "transition_pair_inventory_is_exact": pair_counts
        == {"0-1": 2, "0-2": 0, "0-3": 0, "1-2": 0, "1-3": 0, "2-3": 2},
        "full_10_qubit_domain_action_is_exhaustive": bool(
            compiler["register_width"] == 10
            and compiler["full_domain_basis_states"] == 1024
            and compiler["basis_columns_checked"] == 18_432
            and compiler["two_level_pair_beta_checks"] == 12
        ),
        "compiled_two_level_action_and_adjoint_pass": bool(
            compiler["passed"]
            and compiler["maximum_action_error"] <= NUMERIC_TOLERANCE
            and compiler["maximum_roundtrip_error"] <= NUMERIC_TOLERANCE
            and compiler["maximum_norm_error"] <= NUMERIC_TOLERANCE
        ),
        "complete_layer_gram_and_reference_action_are_exhaustive": bool(
            compiler["complete_layer_basis_columns_checked"] == 3_072
            and compiler["complete_layer_gram_entries_checked"] == 3_145_728
            and compiler["complete_layer_maximum_action_error"] <= NUMERIC_TOLERANCE
            and compiler["complete_layer_maximum_roundtrip_error"] <= NUMERIC_TOLERANCE
            and compiler["complete_layer_maximum_gram_error"] <= NUMERIC_TOLERANCE
            and compiler["checks"][
                "complete_ordered_layer_matches_independent_reference_multi_beta"
            ]
            and compiler["checks"]["complete_ordered_layer_gram_is_identity"]
        ),
        "gray_compute_rotate_uncompute_restores_off_target_domain": bool(
            compiler["checks"]["all_non_target_basis_states_are_identity"]
            and compiler["scratch_cleanup_proof"]["allocated_ancilla_qubits"] == 0
            and compiler["scratch_cleanup_proof"]["allocated_scratch_qubits"] == 0
        ),
        "coherent_superposition_updates_portfolio_and_caches_together": coherent_cache_exact,
        "four_coherent_transition_proofs_are_sealed": bool(
            transitions["transition_count"] == 4
            and len(transitions["rows"]) == 4
            and all(
                row["reference_action_state"] == "PASSED_ALL_REGISTERED_BETAS"
                and row["roundtrip_state"] == "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
                and row["off_target_identity_state"] == "PASSED"
                and row["clean_scratch_state"] == "PASSED_ZERO_ANCILLA_ZERO_SCRATCH"
                and len(row["pair_ir_sha256"]) == 64
                for row in transitions["rows"]
            )
        ),
        "complete_layer_preserves_feasible_consistent_support": bool(
            compiler["checks"]["complete_ordered_layer_preserves_norm"]
            and compiler["checks"]["complete_ordered_layer_preserves_feasible_consistent_support"]
            and compiler["feasible_connectivity"]["connected"]
        ),
        "logical_resource_ledger_is_exact_and_deterministic": bool(
            totals["edge_count"] == 6
            and totals["two_level_pair_count"] == 4
            and totals["pattern_mcx_count"] == 36
            and totals["pattern_mcrx_count"] == 4
            and totals["logical_gate_count"] == 40
            and totals["maximum_control_count"] == 9
            and totals["ancilla_qubits"] == 0
            and ledger["resource_ledger_sha256"] == ledger_duplicate["resource_ledger_sha256"]
            and compiler["checks"]["logical_ir_replay_is_deterministic"]
            and len(compiler["logical_ir_replay_sha256"]) == 64
        ),
        "elementary_and_n40_resource_claims_remain_blocked": bool(
            ledger["elementary_basis_decomposition"] == "NOT_IMPLEMENTED"
            and ledger["selected_model_cnot"] == "NOT_ESTIMATED"
            and ledger["n40_projection"] == "NOT_RUN"
            and ledger["selected_model_budget_gate"] == "NOT_EVALUATED"
            and decisions["production_n40_compiler"] == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions["n40_rewrite_admission"] == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions["elementary_basis_decomposition"] == "BLOCKED_NOT_BUILT"
        ),
        "prototype_decision_is_narrow_and_positive": bool(
            decisions["overall"] == "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
            and decisions["incremental_exposure_prototype"]
            == "PASSED_ON_REGISTERED_N4_K2_FIXTURE"
            and decisions["next_falsifiable_gate"]
            == "ELEMENTARY_BASIS_DECOMPOSITION_AND_N40_RESOURCE_LEDGER"
        ),
        "provider_hardware_and_advantage_boundaries_fail_closed": bool(
            boundary["prototype_scope"] == "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY"
            and boundary["v34_exact_successor_equivalence"] == "NOT_CLAIMED"
            and boundary["production_n40_equivalence"] == "NOT_CLAIMED"
            and boundary["provider_sdk_imported"] is False
            and boundary["provider_credentials_read"] is False
            and boundary["provider_calls"] == 0
            and boundary["backend_transpilation"] == "NOT_RUN"
            and boundary["hardware_executable"] is False
            and boundary["qpu_submission_enabled"] is False
            and boundary["qpu_jobs_submitted"] == 0
            and boundary["quantum_advantage"] == "NOT_CLAIMED"
        ),
        "artifact_is_self_authenticating_and_tamper_evident": bool(
            integrity["valid"]
            and sealed_integrity.get("valid") is True
            and sealed_artifact_exact
            and not tamper_report["valid"]
            and tamper_report["errors"]
        ),
    }
    detail = {
        "artifact_sha256": artifact["artifact_sha256"],
        "compiler_validation_sha256": compiler["compiler_validation_sha256"],
        "differential_manifest_sha256": differential["differential_manifest_sha256"],
        "fixture_sha256": fixture["fixture_sha256"],
        "resource_ledger_sha256": ledger["resource_ledger_sha256"],
        "coherent_transition_ledger_sha256": transitions[
            "coherent_transition_ledger_sha256"
        ],
        "spec_sha256": spec["v37_spec_sha256"],
        "feasible_portfolios": [list(state) for state in feasible],
        "pair_counts": pair_counts,
    }
    core = {
        "checks": checks,
        "detail": detail,
        "validation_source_sha256": validation_source_sha256(),
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **core,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": canonical_json_sha256(core),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the V3.7 reversible prototype.")
    parser.parse_args(argv)
    report = run_v37_validation()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VALIDATION_VERSION", "run_v37_validation", "validation_source_sha256"]
