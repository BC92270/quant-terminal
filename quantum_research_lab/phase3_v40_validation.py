"""Independent scientific validation ladder for Quantum Lab V4.0."""

from __future__ import annotations

import copy
import itertools
from pathlib import Path
from typing import Any, Iterable, Mapping

from .phase3_v40_global_connectivity import (
    EXPECTED_ENGINE_RAW,
    K,
    N,
    SEEDS,
    authenticate_parent_chain,
    build_isolated_counterexample,
    canonical_json_sha256,
    load_v40_artifact,
    load_v40_spec,
    raw_file_sha256,
)


VALIDATION_VERSION = "QUANTUM LAB V4.0 SCIENTIFIC VALIDATION · V1"


def _components_explicit(vertices: Iterable[int], n: int) -> list[tuple[int, ...]]:
    remaining = set(vertices)
    components: list[tuple[int, ...]] = []
    while remaining:
        root = min(remaining)
        queue = [root]
        remaining.remove(root)
        component: list[int] = []
        while queue:
            current = queue.pop()
            component.append(current)
            neighbors = [candidate for candidate in remaining if (current ^ candidate).bit_count() == 2]
            for neighbor in neighbors:
                remaining.remove(neighbor)
                queue.append(neighbor)
        components.append(tuple(sorted(component)))
    return sorted(components)


def _components_by_cores(vertices: Iterable[int], k: int) -> list[tuple[int, ...]]:
    ordered = sorted(vertices)
    if not ordered:
        return []
    parent = list(range(len(ordered)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    first: dict[int, int] = {}
    for index, mask in enumerate(ordered):
        if mask.bit_count() != k:
            raise ValueError("Core verifier received a non-K subset.")
        bits = mask
        while bits:
            bit = (bits & -bits).bit_length() - 1
            bits &= bits - 1
            core = mask ^ (1 << bit)
            if core in first:
                union(index, first[core])
            else:
                first[core] = index
    groups: dict[int, list[int]] = {}
    for index, mask in enumerate(ordered):
        groups.setdefault(find(index), []).append(mask)
    return sorted(tuple(sorted(values)) for values in groups.values())


def exhaustive_small_graph_equivalence() -> dict[str, Any]:
    universe = [sum(1 << index for index in combo) for combo in itertools.combinations(range(5), 2)]
    cases = 0
    mismatches = 0
    for selection in range(1 << len(universe)):
        vertices = [mask for index, mask in enumerate(universe) if (selection >> index) & 1]
        explicit = _components_explicit(vertices, 5)
        cores = _components_by_cores(vertices, 2)
        cases += 1
        if explicit != cores:
            mismatches += 1
    core = {"all_induced_subgraphs_n5_k2": cases, "mismatches": mismatches, "passed": mismatches == 0}
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def exhaustive_core_adjacency_identity() -> dict[str, Any]:
    cases = 0
    mismatches = 0
    for n in range(3, 9):
        for k in range(1, n):
            vertices = [sum(1 << index for index in combo) for combo in itertools.combinations(range(n), k)]
            core_sets = [{mask ^ (1 << bit) for bit in range(n) if (mask >> bit) & 1} for mask in vertices]
            for left in range(len(vertices)):
                for right in range(left + 1, len(vertices)):
                    explicit = (vertices[left] ^ vertices[right]).bit_count() == 2
                    shared_unique_core = len(core_sets[left] & core_sets[right]) == 1
                    cases += 1
                    if explicit != shared_unique_core:
                        mismatches += 1
    core = {"n_values": list(range(3, 9)), "pair_cases": cases, "mismatches": mismatches, "passed": mismatches == 0}
    return {**core, "evidence_sha256": canonical_json_sha256(core)}


def run_v40_validation(*, root: str | Path | None = None) -> dict[str, Any]:
    spec = load_v40_spec(root=root)
    parent = authenticate_parent_chain(root=root)
    artifact, artifact_report = load_v40_artifact(root=root)
    small_graph = exhaustive_small_graph_equivalence()
    core_identity = exhaustive_core_adjacency_identity()
    evidence = artifact["connectivity_evidence"]
    rows = evidence["seed_rows"]
    aggregate = artifact["aggregate_evidence"]
    decisions = artifact["decisions"]
    isolated = [item for row in rows for item in row["isolated_counterexamples"]]
    expected_vertices = {
        1103: 5_050_560,
        2207: 3_981_553,
        3301: 623_921,
        4409: 4_268_642,
        5501: 165_775,
        6607: 2_559_471,
        7703: 3_053_396,
        8807: 1_952_458,
    }
    expected_components = {1103: 1, 2207: 2, 3301: 1, 4409: 1, 5501: 1, 6607: 1, 7703: 3, 8807: 1}
    boundary = artifact["claim_boundary"]
    redesign = artifact["resource_redesign"]
    checks = {
        "spec_self_hash_and_chronology": bool(
            spec["chronology"]["exploratory_audit_disclosed"] is True
            and spec["chronology"]["confirmatory_protocol_state"] == "SEALED_BEFORE_CONFIRMATORY_REPLAY"
        ),
        "parent_v39_through_v31_authenticated": parent["valid"] is True,
        "engine_source_identity": raw_file_sha256(Path(__file__).with_name("phase3_v40_connectivity_engine.cpp")) == EXPECTED_ENGINE_RAW,
        "sealed_artifact_semantically_valid": artifact_report["valid"] is True,
        "small_graph_dsu_equals_explicit": small_graph["passed"] is True,
        "nine_core_adjacency_identity": core_identity["passed"] is True,
        "all_eight_seed_rows_in_frozen_order": [row["seed"] for row in rows] == list(SEEDS),
        "exact_confirmatory_vertex_counts": all(row["feasible_vertex_count"] == expected_vertices[row["seed"]] for row in rows),
        "exact_confirmatory_component_counts": all(row["component_count"] == expected_components[row["seed"]] for row in rows),
        "dual_structural_replay_all_seeds": all(row["replay"]["all_stable_fields_match"] is True for row in rows),
        "incidence_identity_all_seeds": all(row["observed_nine_core_incidences"] == K * row["feasible_vertex_count"] for row in rows),
        "union_forest_identity_all_seeds": all(row["successful_unions"] + row["component_count"] == row["feasible_vertex_count"] for row in rows),
        "aggregate_exact_universe": bool(
            aggregate["total_feasible_vertices"] == 21_655_776
            and aggregate["total_nine_core_incidences"] == 216_557_760
            and aggregate["total_exact_state_graph_edges"] == 337_710_603
        ),
        "disconnected_seeds_exact": aggregate["disconnected_seeds"] == [2207, 7703] and aggregate["disconnected_seed_count"] == 2,
        "three_isolated_counterexamples": len(isolated) == 3 and all(item["vertex_exactly_feasible"] and item["all_neighbors_rejected"] for item in isolated),
        "all_900_isolated_neighbors_audited": sum(item["neighbors_audited"] for item in isolated) == 900 and all(item["feasible_neighbor_count"] == 0 for item in isolated),
        "global_counterexample_decision": decisions["global_connectivity_decision"] == "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE",
        "no_one_swap_subgraph_can_repair_full_graph": bool(
            decisions["next_falsifiable_gate"] == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE"
            and decisions["production_admission"] == "REJECTED_CONNECTIVITY_AND_V39_RESOURCE_ARCHITECTURE"
        ),
        "v39_resource_rejection_preserved": artifact["v39_resource_rejection"] == {
            "budget_cnot": 2_500_000,
            "budget_decision": "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
            "maximum_selected_model_cnot": 781_332_180,
            "minimum_budget_margin_cnot": -778_832_180,
            "preserved": True,
        },
        "resource_redesign_preregistered_not_evaluated": bool(
            redesign["status"] == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
            and redesign["result_fields"]["cnot"] == "NOT_EVALUATED"
            and redesign["result_fields"]["budget_margin"] == "NOT_COMPUTED"
            and len(redesign["candidate_set"]) == 2
        ),
        "provider_backend_hardware_advantage_zero": bool(
            boundary["provider_calls"] == 0
            and boundary["qpu_jobs_submitted"] == 0
            and boundary["backend_transpilation"] == "NOT_RUN"
            and boundary["hardware_executable"] is False
            and boundary["quantum_advantage"] == "NOT_CLAIMED"
        ),
    }
    failed = [name for name, value in checks.items() if value is not True]
    report_core = {
        "artifact_sha256": artifact["artifact_sha256"],
        "checks": checks,
        "counts": {
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "disconnected_seeds": 2,
            "exact_state_graph_edges": aggregate["total_exact_state_graph_edges"],
            "feasible_vertices": aggregate["total_feasible_vertices"],
            "isolated_counterexamples": len(isolated),
            "isolated_neighbors_audited": sum(item["neighbors_audited"] for item in isolated),
            "nine_core_incidences": aggregate["total_nine_core_incidences"],
        },
        "core_adjacency_validation": core_identity,
        "errors": list(dict.fromkeys(list(parent.get("errors") or []) + list(artifact_report.get("errors") or []))),
        "failed_checks": failed,
        "small_graph_validation": small_graph,
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **report_core,
        "passed": not failed and not report_core["errors"],
        "validation_evidence_sha256": canonical_json_sha256(report_core),
    }


__all__ = [
    "VALIDATION_VERSION",
    "exhaustive_core_adjacency_identity",
    "exhaustive_small_graph_equivalence",
    "run_v40_validation",
]
