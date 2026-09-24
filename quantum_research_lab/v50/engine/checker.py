"""Independent structural checker for the sealed V5.0 control-plane artifact.

The checker never imports the evaluator and never exposes a provider or
execution path.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .evidence import (
    EXPECTED_BASIS,
    EXPECTED_FAMILY,
    EXPECTED_QUBITS,
    EXPECTED_REVISION,
    EXPECTED_TOPOLOGY_SHA256,
    SOURCE_CATALOG,
    load_evidence_cohort,
    raw_file_sha256,
    read_json_strict,
    semantic_sha256,
)


EXPECTED_CHECK_COUNT = 82
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_SNAPSHOT_IDS = (
    "heron-r2-ibm-marrakesh-2025-01-22-30ecf00e",
    "heron-r2-ibm-fez-2025-01-23-47fc88e5",
    "heron-r2-ibm-marrakesh-2025-02-26-d49d7ae0",
    "heron-r2-ibm-fez-2025-02-26-7657d388",
)
EXPECTED_ERROR_CEILINGS = (1054, 566, 965, 468)
EXPECTED_DURATION_CEILINGS = (517063, 231739, 613393, 281113)
EXPECTED_REQUIRED_MAXIMA = (1053, 565, 964, 467)
EXPECTED_CAPACITIES = (152, 156, 153, 154)
EXPECTED_PARENT_FREEZE_RAW = "7c34668559955edde109820dc400f630621f18086ae47f4de8d2259ef6c97823"
EXPECTED_PARENT_FREEZE_SEMANTIC = "f5168ff42d8a72111a0e740e8675203e1382c0bcb6a23d1d12b9e9c3c9d2f597"
EXPECTED_PARENT_ARTIFACT_RAW = "1622e2ab0260ea12ef93685ddc75ca58254437b6c9b124c7fd35f8e012457e2b"
EXPECTED_PARENT_ARTIFACT_SEMANTIC = "2ffc0c593ef070f1fccfd04a7dc6bf16e6d002a4210e87b3cc20f50f270e7299"
EXPECTED_PARENT_VALIDATION_RAW = "13c6265f28d766b846c964943c110981a404bc6aabad577e50867bd6484b23ad"
EXPECTED_ARTIFACT_RAW_SHA256 = "3ef7ec081ca45db61da8248d687e60e6da6c9e5eabd1d9eba58626489b865140"
EXPECTED_OVERALL = "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO"
EXPECTED_NEXT_TEST = (
    "DESIGN_AND_FORMALLY_VALIDATE_AN_EXACT_EQUIVALENT_ARCHITECTURE_WITH_"
    "MAX_DIRECT_CX_AT_MOST_467_BEFORE_CURRENT_PROVIDER_DISCOVERY"
)

PARENT_FREEZE = Path("release/quantum_v49/freeze.json")
PARENT_ARTIFACT = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_ADMISSION_ARTIFACT.json"
)
PARENT_VALIDATION = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_VALIDATION_REPORT.json"
)
PROTOCOL = Path("quantum_research_lab/v50/PROTOCOL.json")
DEFAULT_ARTIFACT = Path(
    "outputs/quantum_phase3/v50_hardware_evidence_control/"
    "SEALED_V5_0_PRE_ADMISSION_ARTIFACT.json"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def _regular(root: Path, relative: Path) -> bool:
    path = root / relative
    return path.is_file() and not path.is_symlink()


def _all_zero(boundary: Mapping[str, Any], names: Iterable[str]) -> bool:
    return all(boundary.get(name) == 0 for name in names)


def _sealed_raw_sha256(payload: Mapping[str, Any]) -> str:
    encoded = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _expected_epoch_gate(
    observations: list[Mapping[str, Any]], required: int
) -> dict[str, Any]:
    count = len(observations)
    checks = {
        "minimum_epoch_count": count >= required,
        "distinct_raw_properties": len(
            {str(row["properties_raw_sha256"]) for row in observations}
        )
        == count,
        "distinct_normalized_properties": len(
            {str(row["normalized_properties_sha256"]) for row in observations}
        )
        == count,
        "distinct_source_epochs": len(
            {str(row["source_epoch"]) for row in observations}
        )
        == count,
        "same_processor_family": len(
            {str(row["processor_family"]) for row in observations}
        )
        == 1,
        "same_processor_revision": len(
            {str(row["processor_revision"]) for row in observations}
        )
        == 1,
        "same_directed_topology": len(
            {str(row["directed_topology_sha256"]) for row in observations}
        )
        == 1,
        "same_basis": len(
            {tuple(row["basis_gates"]) for row in observations}
        )
        == 1,
        "same_width": len({int(row["num_qubits"]) for row in observations}) == 1,
        "same_dt": len({str(row["dt_ns"]) for row in observations}) == 1,
        "historical_only": all(
            row.get("current_hardware_evidence") is False for row in observations
        ),
        "not_live_exports": all(
            row.get("live_provider_export") is False for row in observations
        ),
    }
    passed = all(checks.values())
    return {
        "required_distinct_authentic_epochs": required,
        "observed_distinct_authentic_epochs": count,
        "missing_distinct_authentic_epochs": max(0, required - count),
        "distinct_backend_names": len(
            {str(row["backend_name"]) for row in observations}
        ),
        "distinct_distribution_versions": len(
            {str(_mapping(row["distribution"])["version"]) for row in observations}
        ),
        "checks": checks,
        "pass": passed,
        "status": "PASS" if passed else "NOT_EVALUABLE",
    }


def _expected_matrix(
    observations: list[Mapping[str, Any]], parent: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[Mapping[str, Any]]]:
    seeds = _rows(parent.get("seed_admission"))
    if tuple(int(row.get("seed", -1)) for row in seeds) != EXPECTED_SEEDS:
        return [], seeds
    cells: list[dict[str, Any]] = []
    for observation in observations:
        for seed_row in seeds:
            direct_cx = int(seed_row["direct_cx"])
            logical_qubits = int(seed_row["logical_qubits"])
            capacity = int(observation["largest_fault_excluded_component_qubits"])
            error_ceiling = int(observation["strict_error_ceiling_exclusive"])
            duration_ceiling = int(observation["strict_duration_ceiling_exclusive"])
            required_maximum = int(observation["required_maximum_direct_cx"])
            capacity_pass = logical_qubits <= capacity
            route_replay_pass = bool(seed_row.get("route_replay_pass"))
            error_pass = direct_cx < error_ceiling
            duration_pass = direct_cx < duration_ceiling
            cell_pass = capacity_pass and route_replay_pass and error_pass and duration_pass
            cells.append(
                {
                    "snapshot_id": observation["snapshot_id"],
                    "backend_name": observation["backend_name"],
                    "source_epoch": observation["source_epoch"],
                    "seed": int(seed_row["seed"]),
                    "instance_id": seed_row["instance_id"],
                    "logical_qubits": logical_qubits,
                    "fault_excluded_capacity": capacity,
                    "direct_cx": direct_cx,
                    "strict_error_ceiling_exclusive": error_ceiling,
                    "strict_duration_ceiling_exclusive": duration_ceiling,
                    "required_maximum_direct_cx": required_maximum,
                    "cx_reduction_required": max(0, direct_cx - required_maximum),
                    "capacity_pass": capacity_pass,
                    "route_replay_pass": route_replay_pass,
                    "error_screen_pass": error_pass,
                    "duration_screen_pass": duration_pass,
                    "cell_admission_pass": cell_pass,
                    "status": "PASS" if cell_pass else "FAIL",
                }
            )
    return cells, seeds


def _expected_architecture(
    observations: list[Mapping[str, Any]],
    cells: list[Mapping[str, Any]],
    seeds: list[Mapping[str, Any]],
) -> dict[str, Any]:
    direct_values = [int(row["direct_cx"]) for row in seeds]
    required_maxima = [int(row["required_maximum_direct_cx"]) for row in observations]
    required_maximum = min(required_maxima)
    architecture_pass = bool(cells) and all(row["cell_admission_pass"] for row in cells)
    return {
        "reference_architecture_id": "CONTROL_LOADED_CONSTANT_CUCCARO_V1",
        "candidate_is_unchanged_v48_reference": True,
        "snapshot_seed_cell_count": len(cells),
        "minimum_fault_excluded_capacity": min(
            int(row["largest_fault_excluded_component_qubits"])
            for row in observations
        ),
        "cross_snapshot_required_maximum_direct_cx": required_maximum,
        "observed_minimum_direct_cx": min(direct_values),
        "observed_maximum_direct_cx": max(direct_values),
        "minimum_additional_cx_reduction_required": min(direct_values)
        - required_maximum,
        "maximum_additional_cx_reduction_required": max(direct_values)
        - required_maximum,
        "all_cells_capacity_pass": all(row["capacity_pass"] for row in cells),
        "all_cells_route_replay_pass": all(
            row["route_replay_pass"] for row in cells
        ),
        "all_cells_error_screen_pass": all(
            row["error_screen_pass"] for row in cells
        ),
        "all_cells_duration_screen_pass": all(
            row["duration_screen_pass"] for row in cells
        ),
        "all_cells_pass": architecture_pass,
        "status": "PASS" if architecture_pass else "FAIL",
    }


def validate_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path,
    artifact_raw_sha256: str | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve()
    errors: list[str] = []
    try:
        freeze_path = project_root / PARENT_FREEZE
        parent_path = project_root / PARENT_ARTIFACT
        validation_path = project_root / PARENT_VALIDATION
        protocol_path = project_root / PROTOCOL
        source_path = project_root / SOURCE_CATALOG
        freeze = read_json_strict(freeze_path)
        parent = read_json_strict(parent_path)
        parent_validation = read_json_strict(validation_path)
        protocol = read_json_strict(protocol_path)
        catalog, recomputed_observations = load_evidence_cohort(project_root)
    except Exception as exc:
        return {
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_evidence_load"],
            "valid": False,
        }

    parent_link = _mapping(artifact.get("parent"))
    identities = _mapping(artifact.get("evidence_identities"))
    chronology = _mapping(artifact.get("chronology"))
    epoch_gate = _mapping(artifact.get("historical_epoch_gate"))
    epoch_checks = _mapping(epoch_gate.get("checks"))
    observations = _rows(artifact.get("historical_observations"))
    architecture = _mapping(artifact.get("architecture_gate"))
    matrix = _rows(artifact.get("snapshot_seed_matrix"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    protocol_boundary = _mapping(protocol.get("execution_boundary"))

    snapshot_ids = tuple(str(row.get("snapshot_id")) for row in observations)
    matrix_order = tuple(
        (str(row.get("snapshot_id")), int(row.get("seed", -1))) for row in matrix
    )
    expected_matrix_order = tuple(
        (snapshot_id, seed) for snapshot_id in EXPECTED_SNAPSHOT_IDS for seed in EXPECTED_SEEDS
    )
    raw_hashes = {str(row.get("properties_raw_sha256")) for row in observations}
    normalized_hashes = {
        str(row.get("normalized_properties_sha256")) for row in observations
    }
    source_epochs = {str(row.get("source_epoch")) for row in observations}
    distribution_versions = {
        str(_mapping(row.get("distribution")).get("version")) for row in observations
    }
    backend_names = {str(row.get("backend_name")) for row in observations}

    required_epochs = int(
        _mapping(protocol.get("historical_epoch_gate")).get(
            "minimum_distinct_epochs", -1
        )
    )
    expected_parent_link = {
        "authenticated": True,
        "v49_freeze_raw_sha256": raw_file_sha256(freeze_path),
        "v49_freeze_sha256": freeze["freeze_contract_sha256"],
        "v49_artifact_raw_sha256": raw_file_sha256(parent_path),
        "v49_artifact_sha256": parent["artifact_sha256"],
        "v49_validation_raw_sha256": raw_file_sha256(validation_path),
        "v49_validation_valid": parent_validation["valid"],
        "v49_scientific_decision": parent["decisions"]["overall"],
    }
    expected_identities = {
        "protocol_path": str(PROTOCOL),
        "protocol_raw_sha256": raw_file_sha256(protocol_path),
        "protocol_semantic_sha256": semantic_sha256(protocol),
        "source_catalog_path": str(SOURCE_CATALOG),
        "source_catalog_raw_sha256": raw_file_sha256(source_path),
        "source_catalog_semantic_sha256": semantic_sha256(catalog),
    }
    expected_epoch_gate = _expected_epoch_gate(
        recomputed_observations, required_epochs
    )
    expected_matrix, parent_seed_rows = _expected_matrix(
        recomputed_observations, parent
    )
    expected_architecture = _expected_architecture(
        recomputed_observations, expected_matrix, parent_seed_rows
    )
    expected_architecture_pass = bool(expected_matrix) and all(
        row["cell_admission_pass"] for row in expected_matrix
    )
    if not expected_epoch_gate["pass"]:
        expected_overall = "V50_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS"
    elif not expected_architecture_pass:
        expected_overall = EXPECTED_OVERALL
    else:
        expected_overall = "V50_PRE_ADMISSION_PASSED_HUMAN_REVIEW_REQUIRED"
    expected_required_maximum = int(
        expected_architecture["cross_snapshot_required_maximum_direct_cx"]
    )
    expected_decisions = {
        "historical_epoch_gate": (
            "PASS" if expected_epoch_gate["pass"] else "NOT_EVALUABLE"
        ),
        "architecture_gate": (
            "PASS"
            if expected_architecture_pass
            else "FAIL_STRICT_NECESSARY_SCREENS"
        ),
        "overall": expected_overall,
        "current_provider_discovery": (
            "ELIGIBLE_FOR_HUMAN_REVIEW_METADATA_ONLY"
            if expected_overall
            == "V50_PRE_ADMISSION_PASSED_HUMAN_REVIEW_REQUIRED"
            else "DENIED_ARCHITECTURE_NO_GO"
        ),
        "provider_metadata_calls": "PROHIBITED",
        "v5_execution": "CLOSED",
        "qpu_jobs": "PROHIBITED",
        "human_review_eligibility": (
            "ELIGIBLE" if expected_architecture_pass else "NOT_ELIGIBLE"
        ),
        "next_permissible_test": (
            "DESIGN_AND_FORMALLY_VALIDATE_AN_EXACT_EQUIVALENT_ARCHITECTURE_WITH_"
            f"MAX_DIRECT_CX_AT_MOST_{expected_required_maximum}_BEFORE_CURRENT_PROVIDER_DISCOVERY"
        ),
    }

    checks: dict[str, bool] = {
        "artifact_version": artifact.get("artifact_version")
        == "QUANTUM LAB V5.0 SEALED HARDWARE-EVIDENCE CONTROL-PLANE ARTIFACT · V1",
        "release_version": artifact.get("v50_version") == "5.0.0-pre-admission",
        "artifact_semantic": artifact.get("artifact_sha256")
        == semantic_sha256(artifact, exclude=("artifact_sha256",)),
        "artifact_raw_exact": artifact_raw_sha256 == EXPECTED_ARTIFACT_RAW_SHA256
        and _sealed_raw_sha256(artifact) == EXPECTED_ARTIFACT_RAW_SHA256,
        "parent_freeze_regular": _regular(project_root, PARENT_FREEZE),
        "parent_artifact_regular": _regular(project_root, PARENT_ARTIFACT),
        "parent_validation_regular": _regular(project_root, PARENT_VALIDATION),
        "protocol_regular": _regular(project_root, PROTOCOL),
        "source_catalog_regular": _regular(project_root, SOURCE_CATALOG),
        "parent_freeze_raw": raw_file_sha256(freeze_path) == EXPECTED_PARENT_FREEZE_RAW,
        "parent_artifact_raw": raw_file_sha256(parent_path) == EXPECTED_PARENT_ARTIFACT_RAW,
        "parent_validation_raw": raw_file_sha256(validation_path)
        == EXPECTED_PARENT_VALIDATION_RAW,
        "parent_freeze_semantic": freeze.get("freeze_contract_sha256")
        == EXPECTED_PARENT_FREEZE_SEMANTIC
        and semantic_sha256(freeze, exclude=("freeze_contract_sha256",))
        == EXPECTED_PARENT_FREEZE_SEMANTIC,
        "parent_artifact_semantic": parent.get("artifact_sha256")
        == EXPECTED_PARENT_ARTIFACT_SEMANTIC
        and semantic_sha256(parent, exclude=("artifact_sha256",))
        == EXPECTED_PARENT_ARTIFACT_SEMANTIC,
        "parent_validation_valid": parent_validation.get("valid") is True,
        "parent_link_authenticated": parent_link.get("authenticated") is True,
        "parent_link_decision": parent_link.get("v49_scientific_decision")
        == "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS",
        "parent_link_recomputed": parent_link == expected_parent_link,
        "protocol_raw_crosslink": identities.get("protocol_raw_sha256")
        == raw_file_sha256(protocol_path),
        "protocol_semantic_crosslink": identities.get("protocol_semantic_sha256")
        == semantic_sha256(protocol),
        "catalog_raw_crosslink": identities.get("source_catalog_raw_sha256")
        == raw_file_sha256(source_path),
        "catalog_semantic_crosslink": identities.get("source_catalog_semantic_sha256")
        == semantic_sha256(catalog),
        "evidence_identities_recomputed": identities == expected_identities,
        "chronology_thresholds": chronology.get("v49_thresholds_preexist_v50_evidence_registration")
        is True,
        "chronology_parent_preserved": chronology.get("v49_negative_result_preserved") is True,
        "chronology_architecture_unchanged": chronology.get("v48_architecture_unchanged")
        is True,
        "chronology_all_outcomes": chronology.get("all_outcomes_admissible") is True,
        "chronology_no_threshold_change": chronology.get("no_data_dependent_threshold_change")
        is True,
        "observation_count": len(observations) == 4,
        "observation_order": snapshot_ids == EXPECTED_SNAPSHOT_IDS,
        "observations_recomputed": observations == recomputed_observations,
        "epoch_required": epoch_gate.get("required_distinct_authentic_epochs") == 3,
        "epoch_observed": epoch_gate.get("observed_distinct_authentic_epochs") == 4,
        "epoch_missing_zero": epoch_gate.get("missing_distinct_authentic_epochs") == 0,
        "epoch_distinct_raw": len(raw_hashes) == 4
        and epoch_checks.get("distinct_raw_properties") is True,
        "epoch_distinct_normalized": len(normalized_hashes) == 4
        and epoch_checks.get("distinct_normalized_properties") is True,
        "epoch_distinct_source_time": len(source_epochs) == 4
        and epoch_checks.get("distinct_source_epochs") is True,
        "epoch_same_family": {str(row.get("processor_family")) for row in observations}
        == {EXPECTED_FAMILY},
        "epoch_same_revision": {str(row.get("processor_revision")) for row in observations}
        == {EXPECTED_REVISION},
        "epoch_same_topology": {
            str(row.get("directed_topology_sha256")) for row in observations
        }
        == {EXPECTED_TOPOLOGY_SHA256},
        "epoch_same_basis": all(tuple(row.get("basis_gates") or ()) == EXPECTED_BASIS for row in observations),
        "epoch_same_width": all(row.get("num_qubits") == EXPECTED_QUBITS for row in observations),
        "epoch_historical": all(
            row.get("current_hardware_evidence") is False
            and row.get("live_provider_export") is False
            for row in observations
        ),
        "epoch_two_distributions": distribution_versions == {"0.37.0", "0.47.0"},
        "epoch_two_backends": backend_names == {"ibm_fez", "ibm_marrakesh"},
        "epoch_gate_pass": epoch_gate.get("pass") is True
        and epoch_gate.get("status") == "PASS",
        "epoch_gate_recomputed": epoch_gate == expected_epoch_gate,
        "per_snapshot_error_ceilings": tuple(
            int(row.get("strict_error_ceiling_exclusive", -1)) for row in observations
        )
        == EXPECTED_ERROR_CEILINGS,
        "per_snapshot_duration_ceilings": tuple(
            int(row.get("strict_duration_ceiling_exclusive", -1)) for row in observations
        )
        == EXPECTED_DURATION_CEILINGS,
        "per_snapshot_required_maxima": tuple(
            int(row.get("required_maximum_direct_cx", -1)) for row in observations
        )
        == EXPECTED_REQUIRED_MAXIMA,
        "per_snapshot_capacities": tuple(
            int(row.get("largest_fault_excluded_component_qubits", -1))
            for row in observations
        )
        == EXPECTED_CAPACITIES,
        "matrix_size": len(matrix) == 32,
        "matrix_order": matrix_order == expected_matrix_order,
        "matrix_all_capacity_pass": all(row.get("capacity_pass") is True for row in matrix),
        "matrix_all_route_pass": all(row.get("route_replay_pass") is True for row in matrix),
        "matrix_all_error_fail": all(row.get("error_screen_pass") is False for row in matrix),
        "matrix_all_duration_fail": all(row.get("duration_screen_pass") is False for row in matrix),
        "matrix_all_cells_fail": all(
            row.get("cell_admission_pass") is False and row.get("status") == "FAIL"
            for row in matrix
        ),
        "matrix_recomputed": matrix == expected_matrix,
        "architecture_cell_count": architecture.get("snapshot_seed_cell_count") == 32,
        "architecture_capacity": architecture.get("minimum_fault_excluded_capacity") == 152,
        "architecture_required_max": architecture.get("cross_snapshot_required_maximum_direct_cx")
        == 467,
        "architecture_direct_range": architecture.get("observed_minimum_direct_cx")
        == 795990
        and architecture.get("observed_maximum_direct_cx") == 838686,
        "architecture_fail": architecture.get("all_cells_pass") is False
        and architecture.get("status") == "FAIL",
        "architecture_recomputed": architecture == expected_architecture,
        "overall_decision": decisions.get("overall") == EXPECTED_OVERALL,
        "provider_denied": decisions.get("current_provider_discovery")
        == "DENIED_ARCHITECTURE_NO_GO",
        "provider_calls_prohibited": decisions.get("provider_metadata_calls") == "PROHIBITED",
        "v5_execution_closed": decisions.get("v5_execution") == "CLOSED",
        "qpu_jobs_prohibited": decisions.get("qpu_jobs") == "PROHIBITED",
        "human_review_not_eligible": decisions.get("human_review_eligibility")
        == "NOT_ELIGIBLE",
        "next_test": decisions.get("next_permissible_test") == EXPECTED_NEXT_TEST,
        "decisions_recomputed": decisions == expected_decisions,
        "boundary_matches_protocol": boundary == protocol_boundary,
        "boundary_research_only": boundary.get("research_classification") == "RESEARCH_ONLY",
        "boundary_hardware_false": boundary.get("hardware_executable") is False,
        "boundary_current_false": boundary.get("current_hardware_evidence") is False,
        "boundary_provider_false": boundary.get("provider_sdk_imported") is False,
        "boundary_credentials_false": boundary.get("provider_credentials_read") is False
        and boundary.get("credential_reads") == 0,
        "boundary_zero_calls_jobs": _all_zero(
            boundary,
            (
                "provider_calls",
                "network_calls",
                "backend_run_calls",
                "local_simulator_jobs_submitted",
                "qpu_jobs_submitted",
            ),
        ),
        "boundary_no_advantage": boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "boundary_not_ready": boundary.get("hardware_readiness") == "NOT_DEMONSTRATED",
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        errors.append(f"Checker count drift: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "artifact_raw_sha256": artifact_raw_sha256,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "valid": not errors and not failed,
    }


__all__ = ["EXPECTED_CHECK_COUNT", "validate_artifact"]
