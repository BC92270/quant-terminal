"""Deterministic V5.0 offline hardware-evidence control-plane evaluator."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from .evidence import (
    SOURCE_CATALOG,
    load_evidence_cohort,
    raw_file_sha256,
    read_json_strict,
    semantic_sha256,
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
ARTIFACT = Path(
    "outputs/quantum_phase3/v50_hardware_evidence_control/"
    "SEALED_V5_0_PRE_ADMISSION_ARTIFACT.json"
)

EXPECTED_PARENT_FREEZE_RAW = "7c34668559955edde109820dc400f630621f18086ae47f4de8d2259ef6c97823"
EXPECTED_PARENT_FREEZE_SEMANTIC = "f5168ff42d8a72111a0e740e8675203e1382c0bcb6a23d1d12b9e9c3c9d2f597"
EXPECTED_PARENT_ARTIFACT_RAW = "1622e2ab0260ea12ef93685ddc75ca58254437b6c9b124c7fd35f8e012457e2b"
EXPECTED_PARENT_ARTIFACT_SEMANTIC = "2ffc0c593ef070f1fccfd04a7dc6bf16e6d002a4210e87b3cc20f50f270e7299"
EXPECTED_PARENT_VALIDATION_RAW = "13c6265f28d766b846c964943c110981a404bc6aabad577e50867bd6484b23ad"
EXPECTED_PARENT_DECISION = "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS"
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)


def default_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _regular(root: Path, relative: Path) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Required regular file is unavailable: {relative}")
    return path


def authenticate_parent(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    freeze_path = _regular(root, PARENT_FREEZE)
    artifact_path = _regular(root, PARENT_ARTIFACT)
    validation_path = _regular(root, PARENT_VALIDATION)
    if raw_file_sha256(freeze_path) != EXPECTED_PARENT_FREEZE_RAW:
        raise ValueError("V4.9 freeze raw identity mismatch")
    if raw_file_sha256(artifact_path) != EXPECTED_PARENT_ARTIFACT_RAW:
        raise ValueError("V4.9 artifact raw identity mismatch")
    if raw_file_sha256(validation_path) != EXPECTED_PARENT_VALIDATION_RAW:
        raise ValueError("V4.9 validation raw identity mismatch")
    freeze = read_json_strict(freeze_path)
    artifact = read_json_strict(artifact_path)
    validation = read_json_strict(validation_path)
    if freeze.get("freeze_contract_sha256") != EXPECTED_PARENT_FREEZE_SEMANTIC:
        raise ValueError("V4.9 freeze embedded semantic identity mismatch")
    if semantic_sha256(freeze, exclude=("freeze_contract_sha256",)) != EXPECTED_PARENT_FREEZE_SEMANTIC:
        raise ValueError("V4.9 freeze semantic identity mismatch")
    if artifact.get("artifact_sha256") != EXPECTED_PARENT_ARTIFACT_SEMANTIC:
        raise ValueError("V4.9 artifact embedded semantic identity mismatch")
    if semantic_sha256(artifact, exclude=("artifact_sha256",)) != EXPECTED_PARENT_ARTIFACT_SEMANTIC:
        raise ValueError("V4.9 artifact semantic identity mismatch")
    decisions = artifact.get("decisions")
    if not isinstance(decisions, Mapping) or decisions.get("overall") != EXPECTED_PARENT_DECISION:
        raise ValueError("V4.9 scientific decision mismatch")
    if validation.get("valid") is not True:
        raise ValueError("V4.9 validation report is not valid")
    return freeze, artifact, validation


def _seed_rows(parent_artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = parent_artifact.get("seed_admission")
    if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("V4.9 seed admission rows are unavailable")
    if tuple(int(row.get("seed", -1)) for row in rows) != EXPECTED_SEEDS:
        raise ValueError("V4.9 seed order mismatch")
    return rows


def _cohort_gate(
    observations: list[Mapping[str, Any]], required: int
) -> dict[str, Any]:
    raw_hashes = {str(row["properties_raw_sha256"]) for row in observations}
    normalized_hashes = {str(row["normalized_properties_sha256"]) for row in observations}
    epochs = {str(row["source_epoch"]) for row in observations}
    families = {str(row["processor_family"]) for row in observations}
    revisions = {str(row["processor_revision"]) for row in observations}
    topologies = {str(row["directed_topology_sha256"]) for row in observations}
    bases = {tuple(row["basis_gates"]) for row in observations}
    widths = {int(row["num_qubits"]) for row in observations}
    dts = {str(row["dt_ns"]) for row in observations}
    count = len(observations)
    checks = {
        "minimum_epoch_count": count >= required,
        "distinct_raw_properties": len(raw_hashes) == count,
        "distinct_normalized_properties": len(normalized_hashes) == count,
        "distinct_source_epochs": len(epochs) == count,
        "same_processor_family": len(families) == 1,
        "same_processor_revision": len(revisions) == 1,
        "same_directed_topology": len(topologies) == 1,
        "same_basis": len(bases) == 1,
        "same_width": len(widths) == 1,
        "same_dt": len(dts) == 1,
        "historical_only": all(row.get("current_hardware_evidence") is False for row in observations),
        "not_live_exports": all(row.get("live_provider_export") is False for row in observations),
    }
    passed = all(checks.values())
    return {
        "required_distinct_authentic_epochs": required,
        "observed_distinct_authentic_epochs": count,
        "missing_distinct_authentic_epochs": max(0, required - count),
        "distinct_backend_names": len({str(row["backend_name"]) for row in observations}),
        "distinct_distribution_versions": len(
            {str(row["distribution"]["version"]) for row in observations}
        ),
        "checks": checks,
        "pass": passed,
        "status": "PASS" if passed else "NOT_EVALUABLE",
    }


def _matrix(
    observations: list[Mapping[str, Any]], seeds: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
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
    return cells


def build_control_plane_artifact(root: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    parent_freeze, parent_artifact, parent_validation = authenticate_parent(project_root)
    protocol_path = _regular(project_root, PROTOCOL)
    catalog_path = _regular(project_root, SOURCE_CATALOG)
    protocol = read_json_strict(protocol_path)
    catalog, observations = load_evidence_cohort(project_root)
    seeds = _seed_rows(parent_artifact)

    parent_contract = protocol.get("parent_v49")
    if not isinstance(parent_contract, Mapping):
        raise ValueError("V5.0 parent contract is unavailable")
    expected_parent = {
        "freeze_raw_sha256": EXPECTED_PARENT_FREEZE_RAW,
        "freeze_semantic_sha256": EXPECTED_PARENT_FREEZE_SEMANTIC,
        "artifact_raw_sha256": EXPECTED_PARENT_ARTIFACT_RAW,
        "artifact_semantic_sha256": EXPECTED_PARENT_ARTIFACT_SEMANTIC,
        "validation_report_raw_sha256": EXPECTED_PARENT_VALIDATION_RAW,
    }
    if any(parent_contract.get(key) != value for key, value in expected_parent.items()):
        raise ValueError("V5.0 protocol does not bind the exact V4.9 parent")
    epoch_protocol = protocol.get("historical_epoch_gate")
    if not isinstance(epoch_protocol, Mapping):
        raise ValueError("V5.0 historical epoch gate is unavailable")
    required_epochs = int(epoch_protocol["minimum_distinct_epochs"])
    cohort_gate = _cohort_gate(observations, required_epochs)
    cells = _matrix(observations, seeds)
    architecture_pass = bool(cells) and all(row["cell_admission_pass"] for row in cells)
    if not cohort_gate["pass"]:
        overall = "V50_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS"
    elif not architecture_pass:
        overall = "V50_AUTHENTIC_EPOCH_GATE_PASSED_ARCHITECTURE_NO_GO"
    else:
        overall = "V50_PRE_ADMISSION_PASSED_HUMAN_REVIEW_REQUIRED"

    direct_values = [int(row["direct_cx"]) for row in seeds]
    required_maxima = [int(row["required_maximum_direct_cx"]) for row in observations]
    minimum_capacity = min(
        int(row["largest_fault_excluded_component_qubits"]) for row in observations
    )
    cross_snapshot_required_maximum = min(required_maxima)
    architecture_gate = {
        "reference_architecture_id": "CONTROL_LOADED_CONSTANT_CUCCARO_V1",
        "candidate_is_unchanged_v48_reference": True,
        "snapshot_seed_cell_count": len(cells),
        "minimum_fault_excluded_capacity": minimum_capacity,
        "cross_snapshot_required_maximum_direct_cx": cross_snapshot_required_maximum,
        "observed_minimum_direct_cx": min(direct_values),
        "observed_maximum_direct_cx": max(direct_values),
        "minimum_additional_cx_reduction_required": min(direct_values)
        - cross_snapshot_required_maximum,
        "maximum_additional_cx_reduction_required": max(direct_values)
        - cross_snapshot_required_maximum,
        "all_cells_capacity_pass": all(row["capacity_pass"] for row in cells),
        "all_cells_route_replay_pass": all(row["route_replay_pass"] for row in cells),
        "all_cells_error_screen_pass": all(row["error_screen_pass"] for row in cells),
        "all_cells_duration_screen_pass": all(row["duration_screen_pass"] for row in cells),
        "all_cells_pass": architecture_pass,
        "status": "PASS" if architecture_pass else "FAIL",
    }
    provider_discovery = (
        "ELIGIBLE_FOR_HUMAN_REVIEW_METADATA_ONLY"
        if overall == "V50_PRE_ADMISSION_PASSED_HUMAN_REVIEW_REQUIRED"
        else "DENIED_ARCHITECTURE_NO_GO"
    )
    claim_boundary = copy.deepcopy(protocol["execution_boundary"])
    artifact: dict[str, Any] = {
        "artifact_version": "QUANTUM LAB V5.0 SEALED HARDWARE-EVIDENCE CONTROL-PLANE ARTIFACT · V1",
        "v50_version": "5.0.0-pre-admission",
        "chronology": {
            "v49_thresholds_preexist_v50_evidence_registration": True,
            "v49_negative_result_preserved": True,
            "v48_architecture_unchanged": True,
            "all_outcomes_admissible": True,
            "no_data_dependent_threshold_change": True,
        },
        "parent": {
            "authenticated": True,
            "v49_freeze_raw_sha256": raw_file_sha256(project_root / PARENT_FREEZE),
            "v49_freeze_sha256": parent_freeze["freeze_contract_sha256"],
            "v49_artifact_raw_sha256": raw_file_sha256(project_root / PARENT_ARTIFACT),
            "v49_artifact_sha256": parent_artifact["artifact_sha256"],
            "v49_validation_raw_sha256": raw_file_sha256(project_root / PARENT_VALIDATION),
            "v49_validation_valid": parent_validation["valid"],
            "v49_scientific_decision": parent_artifact["decisions"]["overall"],
        },
        "evidence_identities": {
            "protocol_path": str(PROTOCOL),
            "protocol_raw_sha256": raw_file_sha256(protocol_path),
            "protocol_semantic_sha256": semantic_sha256(protocol),
            "source_catalog_path": str(SOURCE_CATALOG),
            "source_catalog_raw_sha256": raw_file_sha256(catalog_path),
            "source_catalog_semantic_sha256": semantic_sha256(catalog),
        },
        "historical_epoch_gate": cohort_gate,
        "historical_observations": observations,
        "architecture_gate": architecture_gate,
        "snapshot_seed_matrix": cells,
        "decisions": {
            "historical_epoch_gate": "PASS" if cohort_gate["pass"] else "NOT_EVALUABLE",
            "architecture_gate": "PASS" if architecture_pass else "FAIL_STRICT_NECESSARY_SCREENS",
            "overall": overall,
            "current_provider_discovery": provider_discovery,
            "provider_metadata_calls": "PROHIBITED",
            "v5_execution": "CLOSED",
            "qpu_jobs": "PROHIBITED",
            "human_review_eligibility": "ELIGIBLE" if architecture_pass else "NOT_ELIGIBLE",
            "next_permissible_test": (
                "DESIGN_AND_FORMALLY_VALIDATE_AN_EXACT_EQUIVALENT_ARCHITECTURE_WITH_"
                f"MAX_DIRECT_CX_AT_MOST_{cross_snapshot_required_maximum}_BEFORE_CURRENT_PROVIDER_DISCOVERY"
            ),
        },
        "claim_boundary": claim_boundary,
    }
    artifact["artifact_sha256"] = semantic_sha256(artifact)
    return artifact


def evaluate_and_write(
    root: str | Path | None = None, output: str | Path | None = None
) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    artifact = build_control_plane_artifact(project_root)
    target = Path(output) if output is not None else project_root / ARTIFACT
    if not target.is_absolute():
        target = project_root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    artifact = evaluate_and_write(args.root, args.output)
    print(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
