"""Independent scientific controls for Quantum Lab V4.2.

The acceptance replay deliberately does not call the V4.2 resource or support
builders.  It derives their closed forms from the sealed ledgers, independently
enumerates the small-domain coined SELECT in Python, and cross-checks the C++
control, the authenticated V4.1 evidence, and every registered decision.
"""

from __future__ import annotations

import ast
from collections import deque
import copy
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v41_certified_bridge_compiler import _certificate_by_seed, _guarded_rows
from .phase3_v42_coined_walk_compiler import (
    BUDGET_CNOT,
    K,
    N,
    ORDERED_COIN_BASIS_COUNT,
    PAIR_POSITION_COUNT,
    SEEDS,
    SELECTED_MODEL,
    canonical_json_sha256,
    load_v42_artifact,
    load_v42_spec,
    raw_file_sha256,
)


VALIDATION_VERSION = "QUANTUM LAB V4.2 INDEPENDENT SCIENTIFIC VALIDATION · V1"
EXPECTED_SELECTOR_COUNTS = {
    "arbitrary_supports": 2_218,
    "bridge_cases": 8_826,
    "cleanup_cases": 264_328,
    "cleanup_failures": 0,
    "full_domain_joint_cases": 28,
    "full_domain_joint_failures": 0,
    "joint_component_cases": 2_218,
    "joint_component_failures": 0,
    "selector_cases": 264_328,
    "selector_failures": 0,
}


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _exact_k_masks(n: int, k: int) -> tuple[int, ...]:
    return tuple(sum(1 << index for index in chosen) for chosen in combinations(range(n), k))


def _data_component_count(feasible: Sequence[int], n: int) -> int:
    remaining = set(feasible)
    components = 0
    while remaining:
        components += 1
        start = remaining.pop()
        queue: deque[int] = deque([start])
        while queue:
            current = queue.popleft()
            for r in range(n):
                for a in range(r + 1, n):
                    if ((current >> r) & 1) == ((current >> a) & 1):
                        continue
                    target = current ^ (1 << r) ^ (1 << a)
                    if target in remaining:
                        remaining.remove(target)
                        queue.append(target)
    return components


def _joint_component_count(feasible: Sequence[int], n: int) -> int:
    index = {mask: position for position, mask in enumerate(feasible)}
    coin_states = n * n
    unseen = set(range(len(feasible) * coin_states))
    components = 0
    while unseen:
        components += 1
        start = unseen.pop()
        queue: deque[int] = deque([start])
        while queue:
            current = queue.popleft()
            data_position, coin = divmod(current, coin_states)
            r, a = divmod(coin, n)
            neighbors = (
                (data_position, (r + 1) % n, a),
                (data_position, (r - 1) % n, a),
                (data_position, r, (a + 1) % n),
                (data_position, r, (a - 1) % n),
            )
            for target_data, target_r, target_a in neighbors:
                target = target_data * coin_states + target_r * n + target_a
                if target in unseen:
                    unseen.remove(target)
                    queue.append(target)
            mask = feasible[data_position]
            if ((mask >> r) & 1) != ((mask >> a) & 1):
                target_mask = mask ^ (1 << r) ^ (1 << a)
                if target_mask in index:
                    target = index[target_mask] * coin_states + r * n + a
                    if target in unseen:
                        unseen.remove(target)
                        queue.append(target)
    return components


def exhaustive_python_selector_control() -> dict[str, Any]:
    """Independent exhaustive replay of the registered promise-space theorem."""

    counts = {key: 0 for key in EXPECTED_SELECTOR_COUNTS}
    for n in range(2, 6):
        for k in range(1, n):
            domain = _exact_k_masks(n, k)
            for support_bits in range(1, 1 << len(domain)):
                feasible = tuple(
                    mask for position, mask in enumerate(domain)
                    if (support_bits >> position) & 1
                )
                feasible_set = set(feasible)
                counts["arbitrary_supports"] += 1
                for current in feasible:
                    for r in range(n):
                        for a in range(n):
                            different = ((current >> r) & 1) != ((current >> a) & 1)
                            proposed = current ^ (1 << r) ^ (1 << a) if different else current
                            target_feasible = proposed in feasible_set
                            move = different and target_feasible
                            output = proposed if move else current
                            counts["selector_cases"] += 1
                            if output not in feasible_set:
                                counts["selector_failures"] += 1
                                continue
                            second_different = ((output >> r) & 1) != ((output >> a) & 1)
                            second_proposed = (
                                output ^ (1 << r) ^ (1 << a)
                                if second_different else output
                            )
                            second_target_feasible = second_proposed in feasible_set
                            second_output = (
                                second_proposed
                                if second_different and second_target_feasible else output
                            )
                            if second_output != current:
                                counts["selector_failures"] += 1
                            counts["cleanup_cases"] += 1
                            if target_feasible != second_target_feasible:
                                counts["cleanup_failures"] += 1
                counts["joint_component_cases"] += 1
                if _data_component_count(feasible, n) != _joint_component_count(feasible, n):
                    counts["joint_component_failures"] += 1

    for n in range(2, 9):
        for k in range(1, n):
            domain = _exact_k_masks(n, k)
            counts["full_domain_joint_cases"] += 1
            if _data_component_count(domain, n) != 1 or _joint_component_count(domain, n) != 1:
                counts["full_domain_joint_failures"] += 1

    for n in range(4, 9):
        for k in range(2, n - 1):
            domain = _exact_k_masks(n, k)
            for source in domain:
                for target in domain:
                    if (source ^ target).bit_count() != 4:
                        continue
                    counts["bridge_cases"] += 1
                    delta = source ^ target
                    if source ^ delta != target or target ^ delta != source:
                        raise AssertionError("Independent bridge involution control failed.")

    core = {
        "algorithm": "INDEPENDENT_PYTHON_EXHAUSTIVE_PROMISE_SUBSPACE_COINED_SELECT_V1",
        **counts,
        "matches_registered_counts": counts == EXPECTED_SELECTOR_COUNTS,
        "passed": counts == EXPECTED_SELECTOR_COUNTS,
    }
    return {**core, "control_sha256": canonical_json_sha256(core)}


def selected_model_formula_control() -> dict[str, Any]:
    checks: dict[str, bool] = {}
    for width in range(3, 65):
        checks[f"controlled_add_w{width}"] = 68 * width - 102 > 0
        checks[f"comparator_w{width}"] = 16 * width - 9 > 0
    for controls in range(2, 65):
        expected = 6 if controls == 2 else 6 * (2 * controls - 3)
        checks[f"mcx_c{controls}"] = expected > 0
    checks["select_scaffold"] = 562 * 6 + 326 == 3_698
    checks["bridge_h4_m40"] = 2 * 4 * (6 * (2 * 39 - 3)) == 3_600
    failed = [name for name, passed in checks.items() if passed is not True]
    core = {"checks": checks, "failed": failed, "passed": not failed}
    return {**core, "control_sha256": canonical_json_sha256(core)}


def _cnot_from_terms(terms: Mapping[str, Any]) -> int:
    def mcx(controls: int) -> int:
        if controls == 2:
            return 6
        if controls >= 3:
            return 6 * (2 * controls - 3)
        raise ValueError("The V4.2 replay only admits MCX terms with at least two controls.")

    return (
        sum(int(count) * (68 * int(width) - 102) for width, count in (terms.get("controlled_add_by_width") or {}).items())
        + sum(int(count) * (16 * int(width) - 9) for width, count in (terms.get("comparator_by_width") or {}).items())
        + sum(int(count) * mcx(int(controls)) for controls, count in (terms.get("mcx_by_controls") or {}).items())
        + int(terms.get("direct_cnot", 0))
    )


def _without(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {name: copy.deepcopy(value) for name, value in payload.items() if name != key}


def _hash_matches(payload: Mapping[str, Any], key: str) -> bool:
    return payload.get(key) == canonical_json_sha256(_without(payload, key))


def _provider_free_imports(path: Path) -> bool:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name.split(".")[0] in forbidden for name in names):
            return False
    return True


def run_v42_validation(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
    deep_parent: bool = True,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v42_spec(root=base)
    artifact, artifact_report = load_v42_artifact(
        root=base,
        authenticate_parent=deep_parent,
    )
    if progress is not None:
        progress("V4.2 validation · independent Python promise-subspace exhaustion")
    python_control = exhaustive_python_selector_control()
    formula_control = selected_model_formula_control()

    parent_path = base / "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json"
    import json
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    parent_support_by_seed = {
        int(row["seed"]): row for row in parent["connectivity_evidence"]["seed_rows"]
    }
    parent_compression_by_seed = {
        int(row["seed"]): row for row in parent["compression_evidence"]["seed_rows"]
    }
    certificates = _certificate_by_seed(base)

    sealed_cpp = artifact["selector_control"]["forward"]
    cpp_counts = {key: int(sealed_cpp[key]) for key in EXPECTED_SELECTOR_COUNTS}
    selector_dual_language_match = bool(
        cpp_counts == EXPECTED_SELECTOR_COUNTS
        and all(
            int(python_control[key]) == int(sealed_cpp[key])
            for key in EXPECTED_SELECTOR_COUNTS
        )
    )

    support_rows = artifact["support_evidence"]["seed_rows"]
    support_rows_valid = True
    support_hashes_valid = True
    expected_total_vertices = 0
    expected_total_edges = 0
    expected_bridges = 0
    for row in support_rows:
        seed = int(row["seed"])
        source = parent_support_by_seed[seed]
        vertices = int(source["authenticated_v40_feasible_vertices"])
        one_swap_edges = int(source["authenticated_v40_exact_one_swap_edges"])
        bridges = int(source["selected_bridge_count"])
        expected_coin = 2 * N * N * vertices
        expected_selector = 2 * one_swap_edges
        expected_replicated_bridges = ORDERED_COIN_BASIS_COUNT * bridges
        expected_joint_vertices = ORDERED_COIN_BASIS_COUNT * vertices
        expected_joint_edges = expected_coin + expected_selector + expected_replicated_bridges
        support_rows_valid = support_rows_valid and bool(
            row["addressed_pair_positions_preserved"] == PAIR_POSITION_COUNT
            and row["authenticated_feasible_data_vertices"] == vertices
            and row["authenticated_one_swap_edges"] == one_swap_edges
            and row["coin_ring_support_edges"] == expected_coin
            and row["selector_one_swap_support_edges"] == expected_selector
            and row["replicated_bridge_support_edges"] == expected_replicated_bridges
            and row["joint_promise_vertices"] == expected_joint_vertices
            and row["joint_support_edges"] == expected_joint_edges
            and row["selected_bridge_count"] == bridges
            and row["joint_component_count"] == 1
            and row["connected"] is True
            and row["selected_bridge_sha256"]
            == [str(bridge["bridge_sha256"]) for bridge in source["selected_bridges"]]
        )
        support_hashes_valid = support_hashes_valid and _hash_matches(row, "seed_support_sha256")
        expected_total_vertices += expected_joint_vertices
        expected_total_edges += expected_joint_edges
        expected_bridges += bridges

    support_aggregate = artifact["support_evidence"]["aggregate"]
    support_aggregate_valid = bool(
        support_aggregate["seed_count"] == 8
        and support_aggregate["all_pair_positions_preserved"] is True
        and support_aggregate["all_seeds_connected"] is True
        and support_aggregate["coin_basis_states_per_data_vertex"] == 1_600
        and support_aggregate["joint_promise_vertices"] == expected_total_vertices
        and support_aggregate["joint_support_edges"] == expected_total_edges
        and support_aggregate["parent_selected_bridge_count"] == expected_bridges == 3
    )

    resource_rows = artifact["resource_evidence"]["seed_rows"]
    resource_rows_valid = True
    resource_hashes_valid = True
    observed_cnot: list[int] = []
    observed_margins: list[int] = []
    observed_qubits: list[int] = []
    for row in resource_rows:
        seed = int(row["seed"])
        parent_connectivity = parent_support_by_seed[seed]
        compression = parent_compression_by_seed[seed]
        guarded = _guarded_rows(certificates[seed], compression)
        widths = [int(item["width"]) for item in guarded]
        oracle = row["feasibility_oracle"]
        oracle_cnot = _cnot_from_terms(oracle["macro_terms"])
        oracle_resources_cnot = int(oracle["resources"]["selected_model_cnot"])
        complete_terms = row["independent_cnot_formula_replay"]["terms"]
        bridge_rows = list(row["bridge_ir"])
        bridge_cnot = 3_600 * len(bridge_rows)
        step_cnot = _cnot_from_terms(complete_terms) + bridge_cnot
        sealed_step_cnot = int(row["selected_model_step_resources"]["selected_model_cnot"])
        expected_qubits = N + 2 * N + N + sum(widths) + max(widths) + 1 + 2 + len(widths) + 5
        expected_controlled_adds = {
            str(width): 2 * sum(
                1 for coefficient in guarded_row["coefficients"] if int(coefficient) != 0
            )
            for width, guarded_row in zip(widths, guarded)
        }
        merged_adds: dict[str, int] = {}
        for width, guarded_row in zip(widths, guarded):
            key = str(width)
            merged_adds[key] = merged_adds.get(key, 0) + 2 * sum(
                1 for coefficient in guarded_row["coefficients"] if int(coefficient) != 0
            )
        expected_controlled_adds = merged_adds
        expected_comparators: dict[str, int] = {}
        for width in widths:
            key = str(width)
            expected_comparators[key] = expected_comparators.get(key, 0) + 4
        bridge_valid = all(
            bridge["data_hamming_distance"] == 4
            and bridge["selected_model_mcx_occurrences"] == 8
            and bridge["resources"]["selected_model_cnot"] == 3_600
            and _hash_matches(bridge, "bridge_ir_sha256")
            for bridge in bridge_rows
        )
        oracle_row_hashes = all(_hash_matches(item, "row_oracle_sha256") for item in oracle["row_ledger"])
        resource_rows_valid = resource_rows_valid and bool(
            row["constraint_register_widths"] == widths
            and row["compression_sha256"] == compression["seed_compression_sha256"]
            and row["parent_connectivity_sha256"] == parent_connectivity["seed_connectivity_sha256"]
            and row["addressed_pair_positions_preserved"] == 780
            and row["coin_basis_states"] == 1_600
            and row["feasibility_oracle_invocations"] == 2
            and oracle["constraint_row_count"] == 7
            and oracle["sum_build_invocations"] == 2
            and oracle["macro_terms"]["controlled_add_by_width"] == expected_controlled_adds
            and oracle["macro_terms"]["comparator_by_width"] == expected_comparators
            and oracle["macro_terms"]["mcx_by_controls"] == {"2": 14, "7": 1}
            and oracle_cnot == oracle_resources_cnot == oracle["independent_cnot_formula_replay"]
            and row["select_scaffold"]["ccx_count"] == 562
            and row["select_scaffold"]["direct_cnot_count_including_coin_rings"] == 326
            and row["select_scaffold"]["resources"]["selected_model_cnot"] == 3_698
            and len(bridge_rows) == int(parent_connectivity["selected_bridge_count"])
            and bridge_valid and oracle_row_hashes
            and row["bridge_selected_model_cnot"] == bridge_cnot
            and step_cnot == sealed_step_cnot
            and row["independent_cnot_formula_replay"]["replay_selected_model_cnot"] == step_cnot
            and row["independent_cnot_formula_replay"]["match"] is True
            and row["budget_margin_cnot"] == BUDGET_CNOT - step_cnot
            and row["decision"] == ("PASSED" if step_cnot <= BUDGET_CNOT else "REJECTED_SELECTED_MODEL_CNOT_BUDGET")
            and row["logical_qubits_with_recycled_workspace"] == expected_qubits
        )
        resource_hashes_valid = resource_hashes_valid and bool(
            _hash_matches(oracle, "feasibility_oracle_sha256")
            and _hash_matches(row, "seed_walk_sha256")
        )
        observed_cnot.append(step_cnot)
        observed_margins.append(BUDGET_CNOT - step_cnot)
        observed_qubits.append(expected_qubits)

    resource_aggregate = artifact["resource_evidence"]["aggregate"]
    parent_max = int(parent["resource_evidence"]["aggregate"]["r2_maximum_selected_model_cnot"])
    maximum = max(observed_cnot)
    resource_aggregate_valid = bool(
        resource_aggregate["budget_cnot"] == BUDGET_CNOT
        and resource_aggregate["all_eight_seeds_pass"] is True
        and resource_aggregate["maximum_selected_model_cnot"] == maximum == 1_135_430
        and resource_aggregate["minimum_budget_margin_cnot"] == min(observed_margins) == 1_364_570
        and resource_aggregate["maximum_logical_qubits_with_recycled_workspace"] == max(observed_qubits) == 331
        and resource_aggregate["parent_v41_r2_maximum_selected_model_cnot"] == parent_max == 15_663_936
        and resource_aggregate["v41_to_v42_maximum_reduction_basis_points"]
        == 10_000 * (parent_max - maximum) // parent_max == 9_275
        and resource_aggregate["selected_model"] == SELECTED_MODEL
    )

    boundary = artifact["claim_boundary"]
    decisions = artifact["decisions"]
    source_path = base / "quantum_research_lab/phase3_v42_coined_walk_compiler.py"
    engine_path = base / "quantum_research_lab/phase3_v42_selector_engine.cpp"
    spec_path = base / "quantum_research_lab/PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json"
    checks = {
        "spec_sealed_before_accepted_artifact": spec["chronology"]["confirmatory_protocol_state"] == "SEALED_BEFORE_ACCEPTED_CONFIRMATORY_ARTIFACT",
        "exploratory_probe_disclosed_not_acceptance": bool(spec["chronology"]["exploratory_audit_disclosed"] and spec["chronology"]["resource_ledger_state_at_seal"] == "NOT_EVALUATED"),
        "parent_v41_exact_and_159_immutable_paths": bool(artifact_report["checks"]["parent_exact"] and artifact["parent"]["immutable_file_count"] == 159),
        "sealed_artifact_all_reconstruction_checks": artifact_report["valid"] is True,
        "artifact_self_hash": _hash_matches(artifact, "artifact_sha256"),
        "portable_selector_build_contract": set(artifact["selector_control"]["build_contract"]) == {"command_flags", "diagnostics_clean", "engine_source_raw_file_sha256", "language_standard"},
        "selector_dual_cpp_traversal_match": artifact["selector_control"]["stable_replay_match"] is True,
        "selector_cpp_registered_counts_exact": cpp_counts == EXPECTED_SELECTOR_COUNTS,
        "selector_independent_python_exhaustive_pass": python_control["passed"] is True,
        "selector_dual_language_counts_match": selector_dual_language_match,
        "selector_involution_failures_zero": python_control["selector_failures"] == 0,
        "target_cleanup_symmetry_failures_zero": python_control["cleanup_failures"] == 0,
        "joint_component_correspondence_failures_zero": python_control["joint_component_failures"] == 0,
        "full_domain_joint_connectivity_through_n8": python_control["full_domain_joint_failures"] == 0,
        "hamming_four_bridge_involution_controls": python_control["bridge_cases"] == 8_826,
        "selected_model_closed_formula_controls": formula_control["passed"] is True,
        "all_780_pair_positions_preserved": len(support_rows) == 8 and all(row["addressed_pair_positions_preserved"] == 780 for row in support_rows),
        "support_rows_independently_derived": support_rows_valid,
        "support_aggregate_independently_derived": support_aggregate_valid,
        "support_nested_hashes_exact": support_hashes_valid and _hash_matches(support_aggregate, "aggregate_support_sha256") and _hash_matches(artifact["support_evidence"], "support_evidence_sha256"),
        "joint_promise_support_connected_all_seeds": support_aggregate["all_seeds_connected"] is True,
        "three_authenticated_bridges_preserved": expected_bridges == 3,
        "resource_rows_independently_replayed": resource_rows_valid,
        "resource_aggregate_independently_derived": resource_aggregate_valid,
        "resource_nested_hashes_exact": resource_hashes_valid and _hash_matches(resource_aggregate, "aggregate_resource_sha256") and _hash_matches(artifact["resource_evidence"], "resource_evidence_sha256"),
        "maximum_not_mean_budget_gate": max(observed_cnot) == 1_135_430 and max(observed_cnot) <= BUDGET_CNOT,
        "all_eight_seed_decisions_pass": all(row["decision"] == "PASSED" for row in resource_rows),
        "decision_is_derived_and_falsifiable": decisions == {
            "generator_support_decision": "CONNECTED_ALL_SEEDS_EXACT_V41_SUPPORT_PRESERVED",
            "next_falsifiable_gate": "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION",
            "overall": "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED",
            "production_admission": "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED",
            "resource_architecture_decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET",
        },
        "promise_scope_explicit": boundary["clean_workspace_scope"] == "CERTIFIED_ONLY_ON_EXACT_FEASIBLE_DATA_AND_ONE_HOT_COIN_PROMISE_SUBSPACE",
        "circuit_materialization_is_next_gate_not_claimed": boundary["circuit_materialization"] == "NOT_RUN_NEXT_GATE",
        "provider_backend_hardware_advantage_zero": bool(boundary["provider_calls"] == 0 and boundary["qpu_jobs_submitted"] == 0 and boundary["hardware_executable"] is False and boundary["backend_transpilation"] == "NOT_RUN" and boundary["quantum_advantage"] == "NOT_CLAIMED"),
        "compiler_ast_provider_free": _provider_free_imports(source_path),
        "source_engine_and_spec_raw_identities": bool(artifact["source_sha256"] == raw_file_sha256(source_path) and artifact["engine_source_raw_file_sha256"] == raw_file_sha256(engine_path) and artifact["spec_raw_file_sha256"] == raw_file_sha256(spec_path)),
        "research_sources_registered": len(spec["research_sources"]) >= 4,
        "budget_constant_unchanged": BUDGET_CNOT == 2_500_000,
    }
    failed = [name for name, passed in checks.items() if passed is not True]
    errors = list(artifact_report.get("errors") or [])
    core = {
        "artifact_sha256": artifact["artifact_sha256"],
        "checks": checks,
        "counts": {
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "cpp_selector_cases": cpp_counts["selector_cases"],
            "independent_python_selector_cases": python_control["selector_cases"],
            "joint_promise_vertices": expected_total_vertices,
            "joint_support_edges": expected_total_edges,
            "maximum_selected_model_cnot": maximum,
            "minimum_budget_margin_cnot": min(observed_margins),
            "selected_bridges": expected_bridges,
            "seed_count": len(resource_rows),
        },
        "errors": errors,
        "failed_checks": failed,
        "formula_control": formula_control,
        "python_selector_control": python_control,
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **core,
        "passed": not failed and not errors,
        "validation_evidence_sha256": canonical_json_sha256(core),
    }


__all__ = [
    "EXPECTED_SELECTOR_COUNTS",
    "VALIDATION_VERSION",
    "exhaustive_python_selector_control",
    "run_v42_validation",
    "selected_model_formula_control",
]
