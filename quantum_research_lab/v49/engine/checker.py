"""Independent standard-library checker for the sealed V4.9 artifact.

The checker intentionally does not import the evaluator or compiler.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


EXPECTED_CHECK_COUNT = 59
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_PARENT_FREEZE_RAW = "6d51bb5496bfdc412154ed84cf4e4a038b76d85b69ef3329f515db6cb969e5c8"
EXPECTED_PARENT_FREEZE_SEMANTIC = "6f6639f5f8ac3965f49b1107996718c6d8819637e6a65986013d5304cea6f2fa"
EXPECTED_PARENT_ARTIFACT_RAW = "f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76"
EXPECTED_PARENT_ARTIFACT_SEMANTIC = "6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f"
EXPECTED_OVERALL = "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS"
EXPECTED_NEXT_TEST = (
    "ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_EPOCHS_AND_PRODUCE_AN_"
    "EXACT_ARCHITECTURE_WITH_MAX_DIRECT_CX_AT_MOST_963"
)

PARENT_FREEZE = Path("FREEZE_CONTRACT_V4_8.json")
PARENT_ARTIFACT = Path(
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
)
PROTOCOL = Path("quantum_research_lab/v49/PROTOCOL.json")
CATALOG = Path("quantum_research_lab/v49/snapshots/catalog.json")
NORMALIZED = Path("quantum_research_lab/v49/snapshots/normalized.json")
DEFAULT_ARTIFACT = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_ADMISSION_ARTIFACT.json"
)


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object: {path}")
    return payload


def _semantic(
    payload: Mapping[str, Any], *, exclude_top_level: Iterable[str] = ()
) -> str:
    excluded = set(exclude_top_level)
    body = {key: value for key, value in payload.items() if key not in excluded}
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


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
        protocol_path = project_root / PROTOCOL
        catalog_path = project_root / CATALOG
        normalized_path = project_root / NORMALIZED
        artifact_path = project_root / DEFAULT_ARTIFACT
        freeze = read_json_strict(freeze_path)
        parent = read_json_strict(parent_path)
        protocol = read_json_strict(protocol_path)
        catalog = read_json_strict(catalog_path)
        normalized = read_json_strict(normalized_path)
    except Exception as exc:
        return {
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_evidence_load"],
            "valid": False,
        }

    parent_link = artifact.get("parent") if isinstance(artifact.get("parent"), Mapping) else {}
    identities = artifact.get("evidence_identities") if isinstance(artifact.get("evidence_identities"), Mapping) else {}
    chronology = artifact.get("chronology") if isinstance(artifact.get("chronology"), Mapping) else {}
    snapshot = artifact.get("snapshot_gate") if isinstance(artifact.get("snapshot_gate"), Mapping) else {}
    architecture = artifact.get("architecture_gate") if isinstance(artifact.get("architecture_gate"), Mapping) else {}
    decisions = artifact.get("decisions") if isinstance(artifact.get("decisions"), Mapping) else {}
    boundary = artifact.get("claim_boundary") if isinstance(artifact.get("claim_boundary"), Mapping) else {}
    terminal = protocol.get("terminal_scope") if isinstance(protocol.get("terminal_scope"), Mapping) else {}
    protocol_boundary = protocol.get("execution_boundary") if isinstance(protocol.get("execution_boundary"), Mapping) else {}
    seeds = artifact.get("seed_admission") if isinstance(artifact.get("seed_admission"), list) else []
    cells = artifact.get("snapshot_seed_matrix") if isinstance(artifact.get("snapshot_seed_matrix"), list) else []
    observed_raw = artifact_raw_sha256
    if observed_raw is None and _regular(artifact_path):
        observed_raw = _raw(artifact_path)

    checks: dict[str, bool] = {
        "artifact_version": artifact.get("artifact_version") == "PHASE III · V4.9 SEALED OFFLINE PRE-HARDWARE ADMISSION ARTIFACT · V1",
        "artifact_semantic": artifact.get("artifact_sha256") == _semantic(artifact, exclude_top_level=("artifact_sha256",)),
        "artifact_raw_supplied": isinstance(observed_raw, str) and len(observed_raw) == 64,
        "parent_freeze_regular": _regular(freeze_path),
        "parent_artifact_regular": _regular(parent_path),
        "protocol_regular": _regular(protocol_path),
        "catalog_regular": _regular(catalog_path),
        "normalized_regular": _regular(normalized_path),
        "parent_freeze_raw": _raw(freeze_path) == EXPECTED_PARENT_FREEZE_RAW,
        "parent_artifact_raw": _raw(parent_path) == EXPECTED_PARENT_ARTIFACT_RAW,
        "parent_freeze_semantic": freeze.get("freeze_contract_sha256") == EXPECTED_PARENT_FREEZE_SEMANTIC and _semantic(freeze, exclude_top_level=("freeze_contract_sha256",)) == EXPECTED_PARENT_FREEZE_SEMANTIC,
        "parent_artifact_semantic": parent.get("artifact_sha256") == EXPECTED_PARENT_ARTIFACT_SEMANTIC and _semantic(parent, exclude_top_level=("artifact_sha256",)) == EXPECTED_PARENT_ARTIFACT_SEMANTIC,
        "parent_authenticated": parent_link.get("authenticated") is True,
        "protocol_raw_crosslink": identities.get("protocol_raw_sha256") == _raw(protocol_path),
        "protocol_semantic_crosslink": identities.get("protocol_semantic_sha256") == _semantic(protocol),
        "catalog_raw_crosslink": identities.get("catalog_raw_sha256") == _raw(catalog_path),
        "catalog_semantic_crosslink": identities.get("catalog_semantic_sha256") == _semantic(catalog),
        "normalized_raw_crosslink": identities.get("normalized_cohort_raw_sha256") == _raw(normalized_path),
        "normalized_semantic_crosslink": identities.get("normalized_cohort_semantic_sha256") == _semantic(normalized),
        "chronology_sealed": chronology.get("protocol_sealed_before_evaluation") is True,
        "chronology_holdout": chronology.get("known_v48_development_snapshot_not_relabelled_as_holdout") is True,
        "chronology_negative": chronology.get("negative_and_not_evaluable_results_admissible") is True,
        "snapshot_required": snapshot.get("required_distinct_authentic_epochs") == 3,
        "snapshot_observed": snapshot.get("observed_distinct_authentic_epochs") == 1,
        "snapshot_missing": snapshot.get("missing_distinct_authentic_epochs") == 2,
        "snapshot_incomplete": snapshot.get("registry_complete") is False and snapshot.get("pass") is False,
        "snapshot_not_evaluable": snapshot.get("status") == "NOT_EVALUABLE",
        "no_synthetic": snapshot.get("synthetic_substitution_allowed") is False,
        "architecture_error_ceiling": architecture.get("strict_error_ceiling_exclusive") == 964,
        "architecture_duration_ceiling": architecture.get("strict_duration_ceiling_exclusive") == 613392,
        "architecture_required_max": architecture.get("required_maximum_direct_cx") == 963,
        "architecture_observed_min": architecture.get("observed_minimum_direct_cx") == 795990,
        "architecture_observed_max": architecture.get("observed_maximum_direct_cx") == 838686,
        "architecture_capacity": architecture.get("all_seeds_capacity_pass") is True,
        "architecture_route": architecture.get("all_seeds_route_replay_pass") is True,
        "architecture_error_fail": architecture.get("all_seeds_error_screen_pass") is False,
        "architecture_duration_fail": architecture.get("all_seeds_duration_screen_pass") is False,
        "architecture_status_fail": architecture.get("pass") is False and architecture.get("status") == "FAIL",
        "seed_order": tuple(int(row.get("seed", -1)) for row in seeds if isinstance(row, Mapping)) == EXPECTED_SEEDS,
        "seed_count": len(seeds) == len(EXPECTED_SEEDS),
        "seed_cells_all_fail": len(seeds) == 8 and all(isinstance(row, Mapping) and row.get("seed_admission_pass") is False and row.get("status") == "FAIL" for row in seeds),
        "matrix_order": tuple(int(row.get("seed", -1)) for row in cells if isinstance(row, Mapping)) == EXPECTED_SEEDS,
        "matrix_size": len(cells) == 8,
        "overall_decision": decisions.get("overall") == EXPECTED_OVERALL,
        "provider_denied": decisions.get("provider_discovery") == "DENIED",
        "v5_closed": decisions.get("v5_hardware_protocol_entry") == "CLOSED",
        "next_test": decisions.get("next_permissible_test") == EXPECTED_NEXT_TEST,
        "research_only": boundary.get("research_classification") == "RESEARCH_ONLY",
        "hardware_false": boundary.get("hardware_executable") is False,
        "provider_sdk_false": boundary.get("provider_sdk_imported") is False,
        "credentials_false": boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0,
        "zero_calls_jobs": all(boundary.get(key) == 0 for key in ("provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted")),
        "no_advantage": boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "historical_not_current": boundary.get("snapshot_is_current_hardware_evidence") is False,
        "readiness_not_demonstrated": boundary.get("hardware_readiness") == "NOT_DEMONSTRATED",
        "protocol_terminal": terminal.get("v49_is_final_offline_v4_phase") is True and terminal.get("negative_result_closes_v4_lineage") is True,
        "protocol_pass_no_qpu": terminal.get("pass_only_opens_v5_hardware_protocol") is True and terminal.get("pass_does_not_authorize_qpu_execution") is True,
        "parent_architecture_id": architecture.get("reference_architecture_id") == "CONTROL_LOADED_CONSTANT_CUCCARO_V1",
        "boundary_matches_protocol": all(boundary.get(key) == value for key, value in protocol_boundary.items()),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        errors.append(f"Checker count drift: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "artifact_raw_sha256": observed_raw,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "valid": not errors and not failed,
    }


__all__ = ["EXPECTED_CHECK_COUNT", "read_json_strict", "validate_artifact"]
