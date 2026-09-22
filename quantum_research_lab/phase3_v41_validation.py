"""Independent scientific validation controls for Quantum Lab V4.1."""

from __future__ import annotations

import copy
from fractions import Fraction
from itertools import combinations
from typing import Any, Mapping

from .phase3_v41_certified_bridge_compiler import (
    BUDGET_CNOT,
    SEEDS,
    _audit_python_delta,
    _audit_python_full,
    _certificate_by_seed,
    _gate_cost,
    _guarded_rows,
    _ripple_comparator_cost,
    _round_nearest_even,
    _controlled_ripple_add_cost,
    authenticate_parent_chain,
    build_augmented_connectivity_certificate,
    build_resource_evidence,
    build_seed_compression_certificate,
    canonical_json_sha256,
    compile_bridge_rotation,
    load_v41_artifact,
    load_v41_spec,
)


VALIDATION_VERSION = "QUANTUM LAB V4.1 SCIENTIFIC VALIDATION · V1"


def exhaustive_round_half_even_control() -> dict[str, Any]:
    cases = 0
    mismatches: list[dict[str, int]] = []
    for shift in range(8):
        scale = 1 << shift
        for value in range(-1024, 1025):
            actual = _round_nearest_even(value, scale)
            ratio = Fraction(value, scale)
            candidates = range(ratio.numerator // ratio.denominator - 2, ratio.numerator // ratio.denominator + 4)
            expected = min(candidates, key=lambda candidate: (abs(ratio - candidate), candidate & 1, candidate))
            if actual != expected and len(mismatches) < 10:
                mismatches.append({"actual": actual, "expected": expected, "scale": scale, "value": value})
            cases += 1
    core = {"cases": cases, "mismatches": mismatches, "passed": not mismatches}
    return {**core, "control_sha256": canonical_json_sha256(core)}


def exhaustive_strict_margin_theorem_control() -> dict[str, Any]:
    cases = 0
    mismatches: list[dict[str, Any]] = []
    coefficient_sets = (
        (-11, -3, 5, 12, 19, 24),
        (-17, -8, -1, 7, 16, 31),
        (-29, -4, 3, 9, 22, 37),
    )
    for coefficients in coefficient_sets:
        masks = [sum(1 << index for index in selected) for selected in combinations(range(6), 3)]
        values = {mask: sum(coefficients[index] for index in range(6) if (mask >> index) & 1) for mask in masks}
        for lower in range(-20, 11, 5):
            for upper in range(lower, 31, 5):
                margin = min(min(abs(value - lower), abs(value - upper)) for value in values.values())
                for shift in range(5):
                    scale = 1 << shift
                    compressed = tuple(_round_nearest_even(value, scale) for value in coefficients)
                    residuals = {
                        mask: values[mask] - scale * sum(compressed[index] for index in range(6) if (mask >> index) & 1)
                        for mask in masks
                    }
                    error = max(abs(value) for value in residuals.values())
                    certificate = shift == 0 or error < margin
                    compressed_lower = -((-lower) // scale)
                    compressed_upper = upper // scale
                    parity = all(
                        (lower <= values[mask] <= upper)
                        == (compressed_lower <= sum(compressed[index] for index in range(6) if (mask >> index) & 1) <= compressed_upper)
                        for mask in masks
                    )
                    if certificate and not parity and len(mismatches) < 10:
                        mismatches.append({
                            "coefficients": list(coefficients), "error": error, "lower": lower,
                            "margin": margin, "shift": shift, "upper": upper,
                        })
                    cases += 1
    core = {"certificate_cases": cases, "mismatches": mismatches, "passed": not mismatches}
    return {**core, "control_sha256": canonical_json_sha256(core)}


def selected_model_formula_control() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for width in range(3, 65):
        checks[f"controlled_add_w{width}"] = _controlled_ripple_add_cost(width, 0).cnot == 68 * width - 102
        checks[f"comparator_ge_w{width}"] = (
            _ripple_comparator_cost(width, 1, relation="GE").cnot
            == 16 * width - 9
        )
        checks[f"comparator_le_w{width}"] = (
            _ripple_comparator_cost(width, 0, relation="LE").cnot
            == 16 * width - 9
        )
    for controls in range(2, 65):
        expected = 6 if controls == 2 else 6 * (2 * controls - 3)
        checks[f"mcx_c{controls}"] = _gate_cost(controls).cnot == expected
    failed = [name for name, value in checks.items() if value is not True]
    core = {"checks": checks, "failed": failed, "passed": not failed}
    return {**core, "control_sha256": canonical_json_sha256(core)}


def _selected_model_cnot_from_terms(terms: Mapping[str, Any]) -> int:
    """Replay the registered selected-model CNOT formula from macro counts."""

    return (
        sum(
            int(count) * (68 * int(width) - 102)
            for width, count in (terms.get("controlled_add_by_width") or {}).items()
        )
        + sum(
            int(count) * (16 * int(width) - 9)
            for width, count in (terms.get("comparator_by_width") or {}).items()
        )
        + sum(
            int(count) * _gate_cost(int(controls)).cnot
            for controls, count in (terms.get("mcx_by_controls") or {}).items()
        )
        + int(terms.get("direct_cnot", 0))
    )


def _candidate_decision(connectivity_pass: bool, selected_model_cnot: int) -> str:
    if not connectivity_pass:
        return "REJECTED_CONNECTIVITY"
    if selected_model_cnot <= BUDGET_CNOT:
        return "PASSED"
    return "REJECTED_SELECTED_MODEL_CNOT_BUDGET"


def _expected_top_level_decisions(
    connectivity_decision: str,
    r2_all_seeds_pass: bool,
) -> dict[str, str]:
    connectivity_pass = (
        connectivity_decision
        == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
    )
    if connectivity_pass and r2_all_seeds_pass:
        return {
            "augmented_connectivity_decision": connectivity_decision,
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION",
            "overall": "V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_PASSED",
            "production_admission": "PROVIDER_NEUTRAL_RESEARCH_ARCHITECTURE_ADMITTED_HARDWARE_NOT_AUTHORIZED",
            "resource_architecture_decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET",
        }
    if connectivity_pass:
        return {
            "augmented_connectivity_decision": connectivity_decision,
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION",
            "overall": "V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED",
            "production_admission": "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED",
            "resource_architecture_decision": "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
        }
    return {
        "augmented_connectivity_decision": connectivity_decision,
        "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
        "next_falsifiable_gate": "COMPLETE_OR_REVISE_REGISTERED_BRIDGE_FAMILY",
        "overall": "V41_AUGMENTED_CONNECTIVITY_INCOMPLETE_RESOURCE_ADMISSION_BLOCKED",
        "production_admission": "BLOCKED_CONNECTIVITY_HARDWARE_NOT_AUTHORIZED",
        "resource_architecture_decision": "BLOCKED_BY_CONNECTIVITY",
    }


def run_v41_validation(*, root: str | None = None, progress: Any | None = None) -> dict[str, Any]:
    spec = load_v41_spec(root=root)
    parent = authenticate_parent_chain(root=root)
    artifact, artifact_report = load_v41_artifact(root=root)
    certificates = _certificate_by_seed(root)
    round_control = exhaustive_round_half_even_control()
    theorem_control = exhaustive_strict_margin_theorem_control()
    formula_control = selected_model_formula_control()

    sealed_audits = list((artifact.get("bridge_audits") or {}).get("rows") or [])
    replay_audits: list[dict[str, Any]] = []
    for sealed in sealed_audits:
        seed = int(sealed["seed"])
        source = str(sealed["source_mask_hex"])
        if progress is not None:
            progress(f"V4.1 validation · dual Python bridge replay · {seed}/{source}")
        method_a = _audit_python_delta(certificates[seed], source)
        method_b = _audit_python_full(certificates[seed], source)
        stable_sealed = {key: copy.deepcopy(value) for key, value in sealed.items() if key not in {"independent_methods", "isolate_audit_sha256", "triple_replay_match"}}
        stable_a = {key: copy.deepcopy(value) for key, value in method_a.items() if key != "algorithm"}
        stable_b = {key: copy.deepcopy(value) for key, value in method_b.items() if key != "algorithm"}
        replay_audits.append({
            "match": stable_sealed == stable_a == stable_b,
            "seed": seed,
            "source_mask_hex": source,
        })
    protocol = {
        "all_triple_replays_match": all(row["match"] for row in replay_audits),
        "audit_rows": sealed_audits,
    }
    connectivity_replay = build_augmented_connectivity_certificate(protocol, root=root)

    compression_replay: list[dict[str, Any]] = []
    for seed in SEEDS:
        if progress is not None:
            progress(f"V4.1 validation · independent dual-MITM compression replay · seed {seed}")
        compression_replay.append(build_seed_compression_certificate(certificates[seed]))
    sealed_compressions = list((artifact.get("compression_evidence") or {}).get("seed_rows") or [])
    if progress is not None:
        progress("V4.1 validation · selected-model resource replay · eight seeds")
    resource_replay = build_resource_evidence(certificates, compression_replay, connectivity_replay)

    connectivity = artifact["connectivity_evidence"]
    resources = artifact["resource_evidence"]
    boundary = artifact["claim_boundary"]
    decisions = artifact["decisions"]
    resource_seed_rows = resources["seed_rows"]
    compression_by_seed = {int(row["seed"]): row for row in compression_replay}
    connectivity_by_seed = {
        int(row["seed"]): row for row in connectivity_replay["seed_rows"]
    }

    one_swap_formula_valid = True
    bridge_ir_formula_valid = True
    compression_resource_cross_links_valid = True
    connectivity_resource_cross_links_valid = True
    candidate_decisions_valid = True
    cache_preparation_formula_valid = True
    for seed_row in resource_seed_rows:
        seed = int(seed_row["seed"])
        compression = compression_by_seed[seed]
        seed_connectivity = connectivity_by_seed[seed]
        certificate = certificates[seed]
        guarded_rows = _guarded_rows(certificate, compression)
        one_swap = seed_row["one_swap_layer"]
        r1 = seed_row["r1"]
        r2 = seed_row["r2"]
        independent = seed_row["independent_resource_replay"]

        one_swap_formula = one_swap["independent_cnot_formula_replay"]
        one_swap_terms = one_swap_formula["terms"]
        replayed_one_swap_cnot = _selected_model_cnot_from_terms(one_swap_terms)
        one_swap_cnot = int(
            one_swap["selected_model_layer_resources"]["selected_model_cnot"]
        )
        one_swap_formula_valid = one_swap_formula_valid and bool(
            one_swap_formula["match"] is True
            and int(one_swap_formula["replay_selected_model_cnot"])
            == replayed_one_swap_cnot
            == one_swap_cnot
            == int(r1["selected_model_layer_resources"]["selected_model_cnot"])
            == int(independent["one_swap_cnot"])
            and int(one_swap["ordered_positions"]) == 780
            and int(one_swap["live_positions"])
            == int(independent["live_one_swap_positions"])
            and int(one_swap["certified_identity_positions"])
            == int(independent["certified_identity_positions"])
            and one_swap["macro_totals"] == independent["one_swap_macro_totals"]
            and one_swap["selected_model_layer_resources"]
            == independent["one_swap_resources"]
            and independent["selected_model"] == one_swap["selected_model"]
            and one_swap["one_swap_layer_sha256"]
            == canonical_json_sha256(
                {
                    key: copy.deepcopy(value)
                    for key, value in one_swap.items()
                    if key != "one_swap_layer_sha256"
                }
            )
        )

        cache = one_swap["cache_preparation_outside_numerator"]
        cache_terms = cache["macros"]["controlled_add_by_width"]
        replayed_cache_cnot = sum(
            int(count) * (68 * int(width) - 102)
            for width, count in cache_terms.items()
        )
        cache_preparation_formula_valid = cache_preparation_formula_valid and bool(
            seed_row["cache_preparation_outside_numerator"] == cache
            and cache["macros"] == independent["cache_preparation_macros"]
            and cache["resources"] == independent["cache_preparation_resources"]
            and cache["macros"]["scope"]
            == "COHERENT_CACHE_PREPARATION_REPORTED_OUTSIDE_MIXER_NUMERATOR"
            and replayed_cache_cnot
            == int(cache["resources"]["selected_model_cnot"])
            == int(independent["cache_preparation_cnot_outside_numerator"])
        )

        expected_registers = [
            {
                "guard": int(row["guard"]),
                "kind": str(row["kind"]),
                "name": str(row["name"]),
                "no_wrap_max": 2 * int(row["guard"]) + int(row["span"]),
                "scale": int(row["scale"]),
                "shift": int(row["shift"]),
                "span": int(row["span"]),
                "width": int(row["width"]),
            }
            for row in guarded_rows
        ]
        compression_resource_cross_links_valid = (
            compression_resource_cross_links_valid
            and seed_row["compression_sha256"] == compression["seed_compression_sha256"]
            and one_swap["instance_id"] == compression["instance_id"]
            == certificate["instance_id"]
            and one_swap["parent_certificate_sha"]
            == compression["parent_certificate_sha"]
            == certificate["certificate_sha"]
            and one_swap["constraint_registers"] == expected_registers
            and independent["compression_sha256"]
            == compression["seed_compression_sha256"]
            and independent["guarded_rows_sha256"]
            == canonical_json_sha256(guarded_rows)
        )

        selected_bridges = list(seed_connectivity["selected_bridges"])
        bridge_irs = list(r2["selected_bridge_ir"])
        bridge_terms = list(independent["bridge_terms"])
        bridge_ir_formula_valid = bridge_ir_formula_valid and (
            len(selected_bridges) == len(bridge_irs) == len(bridge_terms)
        )
        for selected, bridge_ir, term in zip(
            selected_bridges, bridge_irs, bridge_terms
        ):
            independently_compiled_ir = compile_bridge_rotation(
                selected, guarded_rows
            )
            width = int(bridge_ir["joint_register_qubits"])
            hamming = int(bridge_ir["joint_endpoint_hamming_distance"])
            expected_bridge_cnot = 2 * hamming * (6 * (2 * (width - 1) - 3))
            bridge_ir_formula_valid = bridge_ir_formula_valid and bool(
                bridge_ir == independently_compiled_ir
                and bridge_ir["bridge_sha256"] == selected["bridge_sha256"]
                and bridge_ir["source_mask_hex"] == selected["source_mask_hex"]
                and bridge_ir["target_mask_hex"] == selected["target_mask_hex"]
                and int(bridge_ir["data_hamming_distance"]) == 4
                and int(bridge_ir["selected_model_mcx_occurrences"])
                == 2 * hamming
                and int(bridge_ir["selected_model_resources"]["selected_model_cnot"])
                == expected_bridge_cnot
                == int(term["resources"]["selected_model_cnot"])
                and term["bridge_sha256"] == selected["bridge_sha256"]
                and term["source_mask_hex"] == selected["source_mask_hex"]
                and term["target_mask_hex"] == selected["target_mask_hex"]
                and int(term["joint_register_qubits"]) == width
                and int(term["joint_hamming_distance"]) == hamming
                and term["resources"] == bridge_ir["selected_model_resources"]
            )
        bridge_cnot = sum(
            int(row["selected_model_resources"]["selected_model_cnot"])
            for row in bridge_irs
        )
        r2_cnot = int(r2["selected_model_layer_resources"]["selected_model_cnot"])
        connectivity_resource_cross_links_valid = (
            connectivity_resource_cross_links_valid
            and bool(r1["connectivity_pass"])
            == (int(seed_connectivity["authenticated_v40_component_count"]) == 1)
            and bool(r2["connectivity_pass"])
            == bool(seed_connectivity["connected_by_certified_subgraph"])
            and len(bridge_irs) == int(seed_connectivity["selected_bridge_count"])
            and bridge_cnot
            == int(r2["bridge_resources"]["selected_model_cnot"])
            == int(independent["bridge_cnot"])
            and r2_cnot == one_swap_cnot + bridge_cnot
            == int(independent["r2_cnot"])
            and independent["bridge_resources"] == r2["bridge_resources"]
            and independent["r2_resources"] == r2["selected_model_layer_resources"]
            and independent["selected_bridge_sha256"]
            == [bridge["bridge_sha256"] for bridge in selected_bridges]
        )
        candidate_decisions_valid = candidate_decisions_valid and bool(
            r1["candidate_id"] == "R1_LINEAR_SLACK_ALL_ONE_SWAP"
            and r2["candidate_id"]
            == "R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES"
            and int(r1["budget_cnot"]) == int(r2["budget_cnot"]) == BUDGET_CNOT
            and int(r1["budget_margin_cnot"]) == BUDGET_CNOT - one_swap_cnot
            and int(r2["budget_margin_cnot"]) == BUDGET_CNOT - r2_cnot
            and r1["decision"]
            == _candidate_decision(bool(r1["connectivity_pass"]), one_swap_cnot)
            and r2["decision"]
            == _candidate_decision(bool(r2["connectivity_pass"]), r2_cnot)
            and independent["r1"]
            == {
                "budget_margin_cnot": r1["budget_margin_cnot"],
                "connectivity_pass": r1["connectivity_pass"],
                "decision": r1["decision"],
                "logical_qubits_with_clean_decomposition_ancillas": r1[
                    "logical_qubits_with_clean_decomposition_ancillas"
                ],
            }
            and independent["r2"]
            == {
                "budget_margin_cnot": r2["budget_margin_cnot"],
                "connectivity_pass": r2["connectivity_pass"],
                "decision": r2["decision"],
                "logical_qubits_with_clean_decomposition_ancillas": r2[
                    "logical_qubits_with_clean_decomposition_ancillas"
                ],
            }
            and independent["independent_resource_replay_sha256"]
            == canonical_json_sha256(
                {
                    key: copy.deepcopy(value)
                    for key, value in independent.items()
                    if key != "independent_resource_replay_sha256"
                }
            )
        )

    resource_aggregate = resources["aggregate"]
    r1_maximum = max(
        int(row["r1"]["selected_model_layer_resources"]["selected_model_cnot"])
        for row in resource_seed_rows
    )
    r2_maximum = max(
        int(row["r2"]["selected_model_layer_resources"]["selected_model_cnot"])
        for row in resource_seed_rows
    )
    r1_all_seeds_pass = all(row["r1"]["decision"] == "PASSED" for row in resource_seed_rows)
    r2_all_seeds_pass = all(row["r2"]["decision"] == "PASSED" for row in resource_seed_rows)
    minimum_r2_margin = min(
        int(row["r2"]["budget_margin_cnot"]) for row in resource_seed_rows
    )
    resource_aggregate_derived = bool(
        resource_aggregate["budget_cnot"] == BUDGET_CNOT
        and resource_aggregate["cache_preparation_excluded_from_numerator"] is True
        and resource_aggregate["r1_all_seeds_pass"] == r1_all_seeds_pass
        and resource_aggregate["r1_decision"]
        == ("PASSED" if r1_all_seeds_pass else "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET")
        and resource_aggregate["r1_maximum_selected_model_cnot"] == r1_maximum
        and resource_aggregate["r2_all_seeds_pass"] == r2_all_seeds_pass
        and resource_aggregate["r2_decision"]
        == ("PASSED" if r2_all_seeds_pass else "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET")
        and resource_aggregate["r2_maximum_selected_model_cnot"] == r2_maximum
        and resource_aggregate["r2_minimum_budget_margin_cnot"]
        == minimum_r2_margin
        and resource_aggregate["independent_resource_replay_all_seeds"] is True
        and resource_aggregate["v39_maximum_selected_model_cnot"] == 781_332_180
        and resource_aggregate["v39_to_v41_r2_maximum_reduction_basis_points"]
        == (781_332_180 - r2_maximum) * 10_000 // 781_332_180
        and all(
            row["one_swap_layer"]["selected_model"]
            == resource_aggregate["selected_model"]
            for row in resource_seed_rows
        )
    )
    expected_decisions = _expected_top_level_decisions(
        str(connectivity["connectivity_decision"]), r2_all_seeds_pass
    )

    checks = {
        "spec_sealed_with_disclosed_exploration_and_amendments": bool(
            spec["chronology"]["confirmatory_protocol_state"] == "SEALED_BEFORE_CONFIRMATORY_REPLAY"
            and spec["chronology"]["exploratory_audit_disclosed"] is True
            and len(spec["chronology"].get("protocol_amendments") or []) == 2
        ),
        "parent_v40_and_143_immutable_paths_authenticated": bool(parent["valid"] and parent["immutable_v40_paths_authenticated"] == 143),
        "sealed_artifact_structurally_valid": artifact_report["valid"] is True,
        "round_half_even_exhaustive_control": round_control["passed"] is True,
        "strict_margin_theorem_exhaustive_control": theorem_control["passed"] is True,
        "selected_model_formula_control": formula_control["passed"] is True,
        "all_58725_bridge_candidates_dual_python_replayed": bool(
            len(replay_audits) == 3 and all(row["match"] for row in replay_audits)
            and sum(int(row["candidates_audited"]) for row in sealed_audits) == 58_725
        ),
        "connectivity_certificate_exact_replay": connectivity_replay == connectivity,
        "global_augmented_connectivity_certified": bool(
            connectivity["connectivity_decision"] == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
            and connectivity["aggregate"]["selected_bridge_count"] == 3
            and connectivity["aggregate"]["final_components_across_seeds"] == 8
            and connectivity["aggregate"]["selected_spanning_subgraph_edges"] == 337_710_606
        ),
        "complete_augmented_edge_count_not_overclaimed": connectivity["aggregate"]["complete_augmented_edge_count"] == "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE",
        "all_24_factor_compression_certificates_exact_replay": compression_replay == sealed_compressions and len(compression_replay) == 8,
        "selected_model_resource_exact_replay": resource_replay == resources,
        "resource_seed_order_exact": [row["seed"] for row in resource_seed_rows] == list(SEEDS),
        "compression_to_resource_cross_links": compression_resource_cross_links_valid,
        "connectivity_to_resource_cross_links": connectivity_resource_cross_links_valid,
        "one_swap_closed_formula_replay": one_swap_formula_valid,
        "bridge_ir_and_closed_formula_replay": bridge_ir_formula_valid,
        "cache_preparation_closed_formula_and_scope": cache_preparation_formula_valid,
        "r1_and_r2_both_published": all("r1" in row and "r2" in row for row in resource_seed_rows),
        "per_seed_candidate_decisions_derived": candidate_decisions_valid,
        "resource_aggregate_derived_from_seed_rows": resource_aggregate_derived,
        "top_level_decisions_derived_from_connectivity_and_resources": decisions == expected_decisions,
        "resource_budget_rejection_exact": bool(
            resources["aggregate"]["r2_maximum_selected_model_cnot"] == 15_663_936
            and resources["aggregate"]["r2_minimum_budget_margin_cnot"] == -13_163_936
            and decisions["resource_architecture_decision"] == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        ),
        "v39_rejection_preserved": artifact["v39_resource_rejection"]["maximum_selected_model_cnot"] == 781_332_180,
        "provider_backend_hardware_advantage_zero": bool(
            boundary["provider_calls"] == 0 and boundary["qpu_jobs_submitted"] == 0
            and boundary["backend_transpilation"] == "NOT_RUN" and boundary["hardware_executable"] is False
            and boundary["quantum_advantage"] == "NOT_CLAIMED"
        ),
        "production_remains_fail_closed": decisions["production_admission"] == "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED",
        "next_gate_is_falsifiable": decisions["next_falsifiable_gate"] == "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION",
        "budget_constant_unchanged": BUDGET_CNOT == 2_500_000,
    }
    failed = [name for name, value in checks.items() if value is not True]
    errors = list(dict.fromkeys(list(parent.get("errors") or []) + list(artifact_report.get("errors") or [])))
    core = {
        "artifact_sha256": artifact["artifact_sha256"],
        "checks": checks,
        "counts": {
            "bridge_candidates_audited": 58_725,
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "compressed_factor_rows": sum(len(row["factor_rows"]) for row in compression_replay),
            "feasible_bridge_neighbors": connectivity["aggregate"]["feasible_incident_two_swap_candidates"],
            "selected_bridges": connectivity["aggregate"]["selected_bridge_count"],
            "selected_spanning_subgraph_edges": connectivity["aggregate"]["selected_spanning_subgraph_edges"],
        },
        "errors": errors,
        "failed_checks": failed,
        "formula_control": formula_control,
        "rounding_control": round_control,
        "strict_margin_control": theorem_control,
        "validation_version": VALIDATION_VERSION,
    }
    return {**core, "passed": not failed and not errors, "validation_evidence_sha256": canonical_json_sha256(core)}


__all__ = [
    "VALIDATION_VERSION",
    "exhaustive_round_half_even_control",
    "exhaustive_strict_margin_theorem_control",
    "run_v41_validation",
    "selected_model_formula_control",
]
