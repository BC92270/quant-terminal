"""Independent deterministic validation ladder for Quantum Lab V3.8."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_v38_elementary_admission import (
    ELEMENTARY_BASIS,
    N40_BUDGET_CNOT,
    N40_SEEDS,
    SELECTED_MODEL,
    authenticate_v37_parent,
    build_v38_artifact,
    ccx_template,
    compile_elementary_layer,
    crx_template,
    load_v38_artifact,
    load_v38_spec,
    validate_v38_artifact,
)


VALIDATION_VERSION = "PHASE III · V3.8 ELEMENTARY ADMISSION VALIDATION · V1"


def validation_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def run_v38_validation() -> dict[str, Any]:
    spec = load_v38_spec()
    parent = authenticate_v37_parent()
    artifact = build_v38_artifact()
    integrity = validate_v38_artifact(artifact)
    sealed, sealed_integrity = load_v38_artifact()
    replay = compile_elementary_layer()

    model_tamper = copy.deepcopy(artifact)
    model_tamper["decomposition_contract"]["selected_model"] = "POST_HOC_ALTERNATIVE"
    model_tamper_report = validate_v38_artifact(model_tamper)
    n40_tamper = copy.deepcopy(artifact)
    n40_tamper["n40_admission"]["rows"][0]["selected_model_cnot"] = 1
    n40_tamper_report = validate_v38_artifact(n40_tamper)
    rehashed_tamper = copy.deepcopy(n40_tamper)
    from .phase3_v36_algorithmic_reduction import canonical_json_sha256

    rehashed_tamper["artifact_sha256"] = canonical_json_sha256(
        {key: value for key, value in rehashed_tamper.items() if key != "artifact_sha256"}
    )
    rehashed_tamper_report = validate_v38_artifact(rehashed_tamper)

    elementary = artifact["elementary_validation"]
    templates = elementary["template_validation"]
    ledger = artifact["elementary_resource_ledger"]
    n40 = artifact["n40_admission"]
    coverage = n40["coverage_counts_out_of_8"]
    decisions = artifact["decisions"]
    boundary = artifact["claim_boundary"]
    kind_counts = ledger["elementary_gate_counts"]
    checks = {
        "spec_identity_model_and_budget_are_exact": bool(
            len(spec["v38_spec_sha256"]) == 64
            and tuple(spec["acceptance_contract"]["elementary_basis"]) == ELEMENTARY_BASIS
            and spec["counting_contract"]["selected_decomposition_model"] == SELECTED_MODEL
            and spec["n40_admission_contract"]["budget_cnot"] == N40_BUDGET_CNOT
        ),
        "v37_parent_and_freeze_authentication_is_nested_and_exact": bool(
            parent["valid"] and parent["nested_artifact_integrity"]["valid"]
        ),
        "ccx_and_crx_templates_are_exact": bool(
            templates["passed"]
            and templates["ccx_basis_columns_checked"] == 8
            and templates["crx_basis_beta_cases_checked"] == 12
            and templates["ccx_maximum_action_error"] <= 1.0e-12
            and templates["crx_maximum_action_error"] <= 1.0e-12
            and sum(gate["kind"] == "CX" for gate in ccx_template(0, 1, 2)) == 6
            and sum(gate["kind"] == "CX" for gate in crx_template(0, 1, 2.0)) == 2
        ),
        "all_registered_primitive_basis_beta_cases_pass": bool(
            elementary["passed"]
            and elementary["primitive_basis_beta_cases_checked"] == 49_152
            and elementary["logical_occurrences_checked"] == 40
            and elementary["maximum_action_error"] <= 1.0e-12
            and elementary["maximum_norm_error"] <= 1.0e-12
        ),
        "clean_ancilla_return_is_exhaustive_per_primitive": bool(
            elementary["clean_ancilla_failures"] == 0
            and all(row["clean_ancilla_return"] for row in elementary["rows"])
        ),
        "complete_elementary_resource_ledger_is_exact": bool(
            ledger["cnot_count"] == 3_632
            and ledger["one_qubit_gate_count"] == 5_920
            and ledger["maximum_clean_ancilla_qubits"] == 8
            and ledger["maximum_total_qubits"] == 18
            and sum(kind_counts.values()) == 9_552
            and kind_counts["CX"] == 3_632
        ),
        "elementary_ir_replay_is_deterministic": bool(
            replay["elementary_ir_sha256"] == ledger["elementary_ir_sha256"]
            and replay["elementary_ledger_sha256"] == ledger["elementary_ledger_sha256"]
        ),
        "all_eight_n40_seed_contracts_and_seven_constraints_are_authenticated": bool(
            tuple(row["seed"] for row in n40["rows"]) == N40_SEEDS
            and coverage["authenticated_seed_contract"] == 8
            and coverage["seven_constraint_parent_evidence"] == 8
            and coverage["classical_delta_equivalence"] == 8
            and all(row["constraint_count"] == 7 for row in n40["rows"])
        ),
        "n40_missing_reversible_evidence_fails_closed": bool(
            coverage["scalable_reversible_ir"] == 0
            and coverage["elementary_lowering"] == 0
            and coverage["full_coherent_equivalence"] == 0
            and coverage["clean_ancilla_proof"] == 0
            and coverage["ordered_layer_connectivity"] == 0
            and coverage["selected_model_cnot_ledger"] == 0
            and n40["maximum_selected_model_cnot"] == "NOT_ESTIMATED"
            and n40["budget_gate"] == "NOT_EVALUATED"
            and n40["admission_decision"] == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
        ),
        "historical_v34_negative_cost_result_is_preserved_not_relabelled": bool(
            all(
                row["historical_v34_selected_model_cnot"] > N40_BUDGET_CNOT
                and row["historical_v34_status"]
                == "REJECTED_SELECTED_MODEL_BUDGET_NONCOMPARABLE_PARENT"
                and row["selected_model_cnot"] == "NOT_ESTIMATED"
                for row in n40["rows"]
            )
        ),
        "post_observation_candidate_switching_is_prohibited": artifact[
            "decomposition_contract"
        ]["post_observation_candidate_switching"]
        == "PROHIBITED",
        "bounded_decision_and_next_gate_are_exact": bool(
            decisions["overall"] == "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED"
            and decisions["elementary_decomposition"]
            == "VALIDATED_ON_REGISTERED_N4_K2_PROTOTYPE"
            and decisions["n40_resource_admission"] == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
            and decisions["next_falsifiable_gate"]
            == "SCALABLE_N40_REVERSIBLE_ARITHMETIC_IR_AND_EIGHT_SEED_EQUIVALENCE"
        ),
        "provider_hardware_and_advantage_boundaries_remain_zero": bool(
            boundary["production_n40_equivalence"] == "NOT_PROVEN"
            and boundary["n40_selected_model_cnot"] == "NOT_ESTIMATED"
            and boundary["provider_sdk_imported"] is False
            and boundary["provider_credentials_read"] is False
            and boundary["provider_calls"] == 0
            and boundary["backend_transpilation"] == "NOT_RUN"
            and boundary["hardware_executable"] is False
            and boundary["qpu_submission_enabled"] is False
            and boundary["qpu_jobs_submitted"] == 0
            and boundary["quantum_advantage"] == "NOT_CLAIMED"
        ),
        "sealed_artifact_is_exact_and_nested_valid": bool(
            integrity["valid"]
            and sealed_integrity["valid"]
            and sealed == artifact
        ),
        "ordinary_and_rehashed_nested_tampering_are_rejected": bool(
            not model_tamper_report["valid"]
            and not n40_tamper_report["valid"]
            and not rehashed_tamper_report["valid"]
        ),
    }
    core = {
        "validation_version": VALIDATION_VERSION,
        "validation_source_sha256": validation_source_sha256(),
        "artifact_sha256": artifact["artifact_sha256"],
        "checks": checks,
        "evidence_summary": {
            "template_basis_beta_cases": 20,
            "primitive_basis_beta_cases": elementary["primitive_basis_beta_cases_checked"],
            "logical_occurrences": elementary["logical_occurrences_checked"],
            "maximum_action_error": elementary["maximum_action_error"],
            "maximum_norm_error": elementary["maximum_norm_error"],
            "clean_ancilla_failures": elementary["clean_ancilla_failures"],
            "elementary_one_qubit_gates": ledger["one_qubit_gate_count"],
            "elementary_cnot": ledger["cnot_count"],
            "n40_authenticated_seeds": coverage["authenticated_seed_contract"],
            "n40_compiled_seeds": coverage["scalable_reversible_ir"],
            "n40_admission": n40["admission_decision"],
        },
    }
    return {
        **core,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": canonical_json_sha256(core),
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the V3.8 elementary admission release.")
    parser.parse_args(argv)
    report = run_v38_validation()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VALIDATION_VERSION", "run_v38_validation", "validation_source_sha256"]
