"""Fail-closed scientific validation for Quantum Lab V4.7.

The validator does not import or execute the V4.7 optimizer.  It authenticates
the dated-property inputs and the immutable V4.6 parent, delegates the detailed
route/duration/error recomputation to the standard-library independent checker,
and adds a separate static and release-identity layer.

The FakeMarrakesh properties remain dated, offline evidence.  A passing report
is not evidence of a current calibration, hardware executability, circuit
fidelity, utility or quantum advantage.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v47_independent_checker import (
    ARTIFACT_VERSION,
    BASELINE_NAME,
    CANDIDATE_NAME,
    EXPECTED_CHECK_COUNT as EXPECTED_INDEPENDENT_CHECK_COUNT,
    EXPECTED_MODEL_RAW_SHA256,
    EXPECTED_MODEL_SHA256,
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
    EXPECTED_PROPERTIES_RAW_SHA256,
    EXPECTED_PROPERTIES_SHA256,
    EXPECTED_RAW_PROPERTIES_SHA256,
    EXPECTED_RAW_PROPERTIES_SIZE,
    EXPECTED_SEEDS,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_V46_ARTIFACT_RAW_SHA256,
    EXPECTED_V46_ARTIFACT_SHA256,
    EXPECTED_V46_FREEZE_RAW_SHA256,
    EXPECTED_V46_FREEZE_SHA256,
    EXPECTED_V46_ROUTE_ROOT_SHA256,
    EXPECTED_WIDTHS,
    validate_v47_artifact as run_independent_checker,
)


VALIDATION_VERSION = "QUANTUM LAB V4.7 INDEPENDENT SCIENTIFIC VALIDATION · V1"
EXPECTED_CHECK_COUNT = 96

ARTIFACT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
)
VALIDATION_EVIDENCE_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_VALIDATION_REPORT.json"
)
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json"
RAW_PROPERTIES_PATH = "quantum_research_lab/PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json"
PROPERTIES_PATH = "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
PATH_ORACLE_PATH = "quantum_research_lab/PHASE_III_V4_7_FAULT_EXCLUDED_PATH_ORACLE_V1.json"
MODEL_PATH = "quantum_research_lab/PHASE_III_V4_7_DURATION_ERROR_MODEL_CONTRACT_V1.json"
SOURCE_PATH = "quantum_research_lab/phase3_v47_dated_properties_optimizer.py"
CHECKER_PATH = "quantum_research_lab/phase3_v47_independent_checker.py"
VALIDATION_PATH = "quantum_research_lab/phase3_v47_validation.py"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_6.json"
PARENT_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v46_full_stream_routing/"
    "SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
)

# These two post-result pins are patched exactly once after the first sealed
# eight-seed artifact.  Until both are populated, the default validation entry
# point fails closed.  Callers validating a just-built candidate may supply the
# two explicit keyword arguments, which is how the sealing workflow avoids a
# circular pre-result commitment.
EXPECTED_ARTIFACT_RAW_SHA256: str | None = (
    "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185"
)
EXPECTED_ARTIFACT_SHA256: str | None = (
    "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf"
)

EXPECTED_NEXT_GATE = (
    "MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_"
    "BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY"
)
EXPECTED_PRODUCTION_ADMISSION = (
    "OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED"
)
EXPECTED_INDEPENDENT_CHECK_NAMES = (
    "artifact_self_hash",
    "artifact_version",
    "spec_raw_identity",
    "spec_semantic_identity",
    "spec_chronology_and_boundary",
    "raw_properties_identity",
    "normalized_properties_raw_identity",
    "normalized_properties_semantic_identity",
    "properties_backend_contract",
    "properties_tuple_coverage",
    "properties_qubit_coverage",
    "properties_fault_screen_recomputed",
    "properties_claim_boundary",
    "path_oracle_raw_identity",
    "path_oracle_semantic_identity",
    "path_oracle_contract",
    "path_oracle_stream_hash",
    "path_oracle_rows_complete",
    "path_oracle_objective_recomputed",
    "model_raw_identity",
    "model_semantic_identity",
    "model_contract_boundary",
    "parent_authentication",
    "parent_crosslinks",
    "source_crosslink",
    "checker_crosslink",
    "artifact_input_crosslinks",
    "properties_snapshot_crosslink",
    "seed_order",
    "widths_exact",
    "seed_self_hashes_and_parent_rows",
    "nested_self_hashes",
    "manifests_exact_v46",
    "route_accounting",
    "distance_swap_identity",
    "native_count_algebra",
    "native_structural_boundary",
    "layout_bijections",
    "property_usage_recomputed",
    "error_screens_recomputed",
    "stage_usage_recomputed",
    "timing_ledgers_recomputed",
    "resource_gates_recomputed",
    "baseline_commitments_exact_v46",
    "architecture_lower_bounds_recomputed",
    "comparisons_recomputed",
    "aggregate_recomputed",
    "decisions_recomputed",
    "research_classification",
    "provider_network_job_zero",
    "hardware_and_claim_boundary",
)
ALLOWED_OVERALL_DECISIONS = {
    "V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_"
    "ARCHITECTURE_NO_CURRENT_HARDWARE_INFERENCE",
    "V47_DATED_PROPERTIES_AUDIT_COMPLETED_NO_HARDWARE_ADMISSION",
}


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def raw_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def read_json_strict(path: str | Path) -> dict[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve(strict=True) if root is not None else Path(__file__).resolve().parents[1]


def _regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe scientific path: {relative!r}")
    cursor = root.resolve(strict=True)
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked scientific path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Scientific path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(root.resolve(strict=True))
    return cursor


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return list(value)


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _static_source_contract(checker: Path, optimizer: Path, validation: Path) -> dict[str, bool]:
    checker_text = checker.read_text(encoding="utf-8")
    optimizer_text = optimizer.read_text(encoding="utf-8")
    checker_imports = _imports(ast.parse(checker_text))
    optimizer_imports = _imports(ast.parse(optimizer_text))
    validation_imports = _imports(ast.parse(validation.read_text(encoding="utf-8")))
    provider_or_network = {
        "qiskit",
        "qiskit_ibm_runtime",
        "qiskit_ibm_provider",
        "requests",
        "httpx",
        "urllib",
        "boto3",
        "braket",
        "pennylane",
    }
    checker_forbidden = provider_or_network | {"socket"}
    return {
        "checker_no_optimizer_import": not any(
            module.endswith("phase3_v47_dated_properties_optimizer")
            for module in checker_imports
        ),
        "checker_standard_library_provider_network_free": not any(
            module.split(".")[0] in checker_forbidden for module in checker_imports
        ),
        "optimizer_no_qiskit_provider_or_network_client_import": not any(
            module.split(".")[0] in provider_or_network for module in optimizer_imports
        ),
        "optimizer_network_guard_is_explicit": bool(
            "import socket" in optimizer_text
            and 'mock.patch.object(socket.socket, "connect", deny_network)' in optimizer_text
            and '"socket.create_connection", side_effect=deny_network' in optimizer_text
            and "if network_attempts:" in optimizer_text
        ),
        "validation_no_optimizer_import": not any(
            module.endswith("phase3_v47_dated_properties_optimizer")
            for module in validation_imports
        ),
    }


def _pin_pair(
    expected_raw: str | None,
    expected_semantic: str | None,
) -> tuple[str | None, str | None, bool]:
    raw = expected_raw if expected_raw is not None else EXPECTED_ARTIFACT_RAW_SHA256
    semantic = expected_semantic if expected_semantic is not None else EXPECTED_ARTIFACT_SHA256
    return raw, semantic, _is_sha(raw) and _is_sha(semantic)


def validate_v47_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    """Validate one sealed V4.7 result without executing its optimizer.

    Both artifact identities are mandatory.  The module-level pins are used by
    default after release sealing; an explicit pair is accepted for the first
    candidate/replay sealing transaction.
    """

    base = _root(root)
    errors: list[str] = []
    relative_paths = {
        "artifact": ARTIFACT_PATH,
        "spec": SPEC_PATH,
        "raw_properties": RAW_PROPERTIES_PATH,
        "properties": PROPERTIES_PATH,
        "path_oracle": PATH_ORACLE_PATH,
        "model": MODEL_PATH,
        "source": SOURCE_PATH,
        "checker": CHECKER_PATH,
        "validation": VALIDATION_PATH,
        "parent_freeze": PARENT_FREEZE_PATH,
        "parent_artifact": PARENT_ARTIFACT_PATH,
    }
    paths: dict[str, Path] = {}
    for name, relative in relative_paths.items():
        try:
            paths[name] = _regular(base, relative)
        except Exception as exc:
            paths[name] = base / relative
            errors.append(f"{name}: {exc}")

    payloads: dict[str, dict[str, Any]] = {}
    for name in ("artifact", "spec", "properties", "path_oracle", "model", "parent_freeze", "parent_artifact"):
        try:
            payloads[name] = read_json_strict(paths[name])
        except Exception as exc:
            payloads[name] = {}
            errors.append(f"{name} strict JSON: {exc}")

    raw_pin, semantic_pin, pins_present = _pin_pair(
        expected_artifact_raw_sha256,
        expected_artifact_sha256,
    )
    artifact_raw = raw_file_sha256(paths["artifact"]) if paths["artifact"].is_file() else None
    try:
        independent = run_independent_checker(
            artifact,
            root=base,
            authenticate_parent=authenticate_parent,
            expected_artifact_sha256=semantic_pin if pins_present else None,
            artifact_raw_file_sha256=artifact_raw,
            expected_artifact_raw_sha256=raw_pin if pins_present else None,
        )
    except Exception as exc:
        independent = {
            "check_count": 0,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["exception"],
            "valid": False,
        }
        errors.append(f"Independent checker: {exc}")
    try:
        static = _static_source_contract(paths["checker"], paths["source"], paths["validation"])
    except Exception as exc:
        static = {}
        errors.append(f"Static source contract: {exc}")

    spec = payloads["spec"]
    properties = payloads["properties"]
    oracle = payloads["path_oracle"]
    model = payloads["model"]
    parent_freeze = payloads["parent_freeze"]
    parent_artifact = payloads["parent_artifact"]
    rows = _rows(artifact.get("seed_evaluations"))
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    property_dates = _mapping(properties.get("property_time_range"))
    property_boundary = _mapping(properties.get("claim_boundary"))
    model_boundary = _mapping(model.get("claim_boundary"))
    chronology = _mapping(spec.get("chronology"))
    spec_boundary = _mapping(spec.get("claim_boundary"))

    zero_fields = (
        "credential_reads",
        "provider_calls",
        "network_calls",
        "backend_run_calls",
        "local_simulator_jobs_submitted",
        "qpu_jobs_submitted",
    )
    artifact_zero = all(boundary.get(field) == 0 for field in zero_fields)
    baseline_names = [
        _mapping(row.get("baseline_v46")).get("candidate_name") for row in rows
    ]
    candidate_names = [
        _mapping(row.get("candidate")).get("candidate_name") for row in rows
    ]
    baseline_statuses = [
        _mapping(row.get("baseline_v46")).get("status") for row in rows
    ]
    candidate_statuses = [
        _mapping(row.get("candidate")).get("status") for row in rows
    ]
    independent_checks = _mapping(independent.get("checks"))

    own_checks: dict[str, bool] = {
        "artifact_identity_pins_present": pins_present,
        "artifact_file_raw_identity": bool(pins_present and artifact_raw == raw_pin),
        "artifact_mapping_semantic_identity": bool(
            pins_present and artifact.get("artifact_sha256") == semantic_pin and _self_hash(artifact, "artifact_sha256")
        ),
        "artifact_file_matches_validated_mapping": payloads["artifact"] == dict(artifact),
        "artifact_version_exact": artifact.get("artifact_version") == ARTIFACT_VERSION,
        "artifact_research_classification_exact": artifact.get("research_classification") == "RESEARCH_ONLY",
        "independent_checker_valid": independent.get("valid") is True,
        "independent_checker_exact_count": bool(
            independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT
            and set(independent_checks) == set(EXPECTED_INDEPENDENT_CHECK_NAMES)
        ),
        "independent_checker_no_errors": not independent.get("errors") and not independent.get("failed_checks"),
        "source_crosslink_raw": bool(
            paths["source"].is_file()
            and artifact.get("source_raw_file_sha256") == raw_file_sha256(paths["source"])
        ),
        "checker_crosslink_raw": bool(
            paths["checker"].is_file()
            and artifact.get("independent_checker_raw_file_sha256") == raw_file_sha256(paths["checker"])
        ),
        "checker_no_optimizer_import": static.get("checker_no_optimizer_import") is True,
        "checker_standard_library_provider_network_free": static.get("checker_standard_library_provider_network_free") is True,
        "optimizer_no_qiskit_provider_or_network_client_import": static.get("optimizer_no_qiskit_provider_or_network_client_import") is True,
        "optimizer_network_guard_is_explicit": static.get("optimizer_network_guard_is_explicit") is True,
        "validation_no_optimizer_import": static.get("validation_no_optimizer_import") is True,
        "exact_eight_seed_rows": len(rows) == 8,
        "seed_order_exact": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "widths_exact": [row.get("logical_qubits") for row in rows] == list(EXPECTED_WIDTHS),
        "all_baseline_commitment_flags_exact": len(rows) == 8 and all(
            row.get("baseline_v46_commitments_exact") is True for row in rows
        ),
        "baseline_names_exact": baseline_names == [BASELINE_NAME] * 8,
        "candidate_names_exact": candidate_names == [CANDIDATE_NAME] * 8,
        "baseline_status_vocabulary_exact": len(rows) == 8 and all(
            status in {"REJECT_DATED_PROPERTIES_UNIT_ERROR_USAGE", "MODELED_ONLY_NO_HARDWARE_ADMISSION"}
            for status in baseline_statuses
        ),
        "candidate_status_vocabulary_exact": len(rows) == 8 and all(
            status in {"PASS_RESEARCH_OPTIMIZATION_FEASIBILITY", "REJECT_RESEARCH_OPTIMIZATION_FEASIBILITY"}
            for status in candidate_statuses
        ),
        "aggregate_seed_count_exact": aggregate.get("seed_count") == len(rows) == 8,
        "aggregate_boolean_outcomes_typed": all(
            isinstance(aggregate.get(field), bool)
            for field in (
                "all_eight_architecture_lower_bounds_fail_both_screens",
                "all_eight_baseline_commitments_exact_v46",
                "all_eight_candidate_research_feasible",
                "all_eight_pareto_safe",
            )
        ),
        "production_admission_rejected_exact": decisions.get("production_admission") == EXPECTED_PRODUCTION_ADMISSION,
        "next_falsifiable_gate_exact": decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "overall_decision_vocabulary_exact": decisions.get("overall") in ALLOWED_OVERALL_DECISIONS,
        "provider_credentials_network_backend_jobs_zero": artifact_zero,
        "provider_sdk_and_credentials_not_used": boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False,
        "hardware_executable_false": boundary.get("hardware_executable") is False,
        "dated_snapshot_not_current_hardware_evidence": boundary.get("snapshot_is_current_hardware_evidence") is False,
        "error_mass_is_descriptive_not_fidelity": boundary.get("reported_gate_error_mass") == "EVALUATED_DESCRIPTIVE_NOT_FIDELITY" and boundary.get("calibration_aware_circuit_fidelity") == "NOT_CLAIMED",
        "quantum_advantage_not_claimed": boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "spec_result_blind_at_seal": chronology.get("result_state_at_seal") == "NOT_EVALUATED",
        "spec_research_boundary_exact": spec_boundary.get("research_classification") == "RESEARCH_ONLY" and spec_boundary.get("hardware_executable") is False,
        "property_snapshot_research_boundary_exact": property_boundary.get("research_classification") == "RESEARCH_ONLY" and property_boundary.get("hardware_executable") is False and property_boundary.get("snapshot_is_current_hardware_evidence") is False,
        "property_dates_preserve_non_cutoff_disclosure": property_dates.get("global_date_is_not_asserted_as_strict_cutoff") is True and bool(property_dates.get("global_last_update_date")) and bool(property_dates.get("maximum_embedded_property_date")),
        "model_research_boundary_exact": model_boundary.get("research_classification") == "RESEARCH_ONLY" and model_boundary.get("hardware_executable") is False and model_boundary.get("snapshot_is_current_hardware_evidence") is False,
        "input_raw_identities_exact": bool(
            raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256
            and paths["raw_properties"].stat().st_size == EXPECTED_RAW_PROPERTIES_SIZE
            and raw_file_sha256(paths["raw_properties"]) == EXPECTED_RAW_PROPERTIES_SHA256
            and raw_file_sha256(paths["properties"]) == EXPECTED_PROPERTIES_RAW_SHA256
            and raw_file_sha256(paths["path_oracle"]) == EXPECTED_PATH_ORACLE_RAW_SHA256
            and raw_file_sha256(paths["model"]) == EXPECTED_MODEL_RAW_SHA256
        ) if all(paths[name].is_file() for name in ("spec", "raw_properties", "properties", "path_oracle", "model")) else False,
        "input_semantic_identities_exact": bool(
            spec.get("v47_spec_sha256") == EXPECTED_SPEC_SHA256
            and properties.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
            and oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256
            and model.get("model_contract_sha256") == EXPECTED_MODEL_SHA256
        ),
        "parent_raw_identities_exact": bool(
            paths["parent_freeze"].is_file()
            and raw_file_sha256(paths["parent_freeze"]) == EXPECTED_V46_FREEZE_RAW_SHA256
            and paths["parent_artifact"].is_file()
            and raw_file_sha256(paths["parent_artifact"]) == EXPECTED_V46_ARTIFACT_RAW_SHA256
        ),
        "parent_semantic_identities_exact": bool(
            parent_freeze.get("freeze_contract_sha256") == EXPECTED_V46_FREEZE_SHA256
            and parent_artifact.get("artifact_sha256") == EXPECTED_V46_ARTIFACT_SHA256
            and _mapping(parent_artifact.get("aggregate")).get("ordered_route_ir_root_sha256") == EXPECTED_V46_ROUTE_ROOT_SHA256
        ),
        "candidate_contract_exact": bool(
            _mapping(artifact.get("candidate_contract")).get("candidate_name") == CANDIDATE_NAME
            and _mapping(artifact.get("candidate_contract")).get("component_size") == 153
            and _mapping(artifact.get("candidate_contract")).get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256
        ),
    }
    checks = {
        **own_checks,
        **{
            f"independent::{name}": independent_checks.get(name) is True
            for name in sorted(EXPECTED_INDEPENDENT_CHECK_NAMES)
        },
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(
            f"V4.7 validation check count drifted: {len(checks)} != {EXPECTED_CHECK_COUNT}"
        )
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(str(item) for item in independent.get("errors") or [])
    evidence_core = {
        "artifact_raw_file_sha256": artifact_raw,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {
            "checks_passed": sum(passed is True for passed in checks.values()),
            "checks_total": len(checks),
        },
        "independent_checker_check_count": independent.get("check_count"),
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **evidence_core,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "passed": not failed and not errors,
        "root": str(base),
        "validation_evidence_sha256": canonical_json_sha256(evidence_core),
    }


def run_v47_validation(
    *,
    root: str | Path | None = None,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    base = _root(root)
    artifact = read_json_strict(_regular(base, ARTIFACT_PATH))
    return validate_v47_artifact(
        artifact,
        root=base,
        expected_artifact_raw_sha256=expected_artifact_raw_sha256,
        expected_artifact_sha256=expected_artifact_sha256,
        authenticate_parent=authenticate_parent,
    )


def seal_v47_validation_evidence(
    *,
    root: str | Path | None,
    replay_artifact: str | Path,
    output: str | Path | None = None,
    output_path: str | Path | None = None,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    """Seal validation plus a byte-identical clean-process replay."""

    base = _root(root)
    raw_pin, semantic_pin, pins_present = _pin_pair(
        expected_artifact_raw_sha256,
        expected_artifact_sha256,
    )
    if not pins_present:
        raise ValueError("Cannot seal V4.7 validation without exact raw and semantic artifact pins.")
    report = run_v47_validation(
        root=base,
        expected_artifact_raw_sha256=raw_pin,
        expected_artifact_sha256=semantic_pin,
        authenticate_parent=True,
    )
    sealed_path = _regular(base, ARTIFACT_PATH)
    replay_path = Path(replay_artifact).resolve(strict=True)
    replay_payload = read_json_strict(replay_path)
    replay_raw = raw_file_sha256(replay_path)
    replay_semantic = replay_payload.get("artifact_sha256")
    replay_self_hash = _self_hash(replay_payload, "artifact_sha256")
    replay_equal = replay_path.read_bytes() == sealed_path.read_bytes()
    replay_valid = bool(
        replay_raw == raw_pin
        and replay_semantic == semantic_pin
        and replay_self_hash
        and replay_equal
    )
    if report.get("passed") is not True or not replay_valid:
        raise ValueError(
            "Cannot seal V4.7 validation evidence: scientific validation or "
            "clean-process replay identity failed."
        )
    core: dict[str, Any] = {
        "artifact_raw_file_sha256": raw_pin,
        "artifact_sha256": semantic_pin,
        "claim_boundary": {
            "hardware_executable": False,
            "provider_calls": 0,
            "network_calls": 0,
            "backend_run_calls": 0,
            "local_simulator_jobs_submitted": 0,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "clean_process_replay": {
            "artifact_raw_file_sha256": replay_raw,
            "artifact_sha256": replay_semantic,
            "byte_for_byte_equal_to_sealed_artifact": replay_equal,
            "command_contract": (
                "env -i PATH=<INHERITED> PYTHONPATH=<RELEASE_ROOT> "
                "PYTHONHASHSEED=0 python3 -m "
                "quantum_research_lab.phase3_v47_dated_properties_optimizer "
                "--root <RELEASE_ROOT> --output <FRESH_TEMP>/replay.json"
            ),
            "performed": True,
            "provider_and_job_boundary_in_replayed_artifact": (
                "ZERO_PROVIDER_ZERO_NETWORK_ZERO_BACKEND_RUN_ZERO_SIMULATOR_JOB_ZERO_QPU_JOB"
            ),
            "semantic_self_hash_valid": replay_self_hash,
        },
        "scientific_validation": {
            "checks": report.get("checks"),
            "checks_passed": _mapping(report.get("counts")).get("checks_passed"),
            "checks_total": _mapping(report.get("counts")).get("checks_total"),
            "errors": report.get("errors"),
            "failed_checks": report.get("failed_checks"),
            "independent_checker_check_count": report.get("independent_checker_check_count"),
            "passed": True,
            "validation_evidence_sha256": report.get("validation_evidence_sha256"),
        },
        "validation_evidence_version": "QUANTUM LAB V4.7 VALIDATION EVIDENCE · V1",
    }
    payload = {
        **core,
        "sealed_validation_evidence_sha256": canonical_json_sha256(core),
    }
    if output is not None and output_path is not None:
        raise ValueError("Pass output or output_path, not both.")
    selected_output = output_path if output_path is not None else output
    target = Path(selected_output).resolve() if selected_output is not None else base / VALIDATION_EVIDENCE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--expected-artifact-raw-sha256")
    parser.add_argument("--expected-artifact-sha256")
    parser.add_argument("--skip-parent-files", action="store_true")
    parser.add_argument("--replay-artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    if bool(args.replay_artifact) != bool(args.output):
        parser.error("--replay-artifact and --output must be supplied together.")
    root = args.root_option or args.root_positional
    try:
        report = (
            seal_v47_validation_evidence(
                root=root,
                replay_artifact=args.replay_artifact,
                output=args.output,
                expected_artifact_raw_sha256=args.expected_artifact_raw_sha256,
                expected_artifact_sha256=args.expected_artifact_sha256,
            )
            if args.replay_artifact and args.output
            else run_v47_validation(
                root=root,
                expected_artifact_raw_sha256=args.expected_artifact_raw_sha256,
                expected_artifact_sha256=args.expected_artifact_sha256,
                authenticate_parent=not args.skip_parent_files,
            )
        )
    except Exception as exc:
        report = {
            "counts": {"checks_passed": 0, "checks_total": EXPECTED_CHECK_COUNT},
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "passed": False,
            "validation_version": VALIDATION_VERSION,
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    sealed = report.get("validation_evidence_version") == "QUANTUM LAB V4.7 VALIDATION EVIDENCE · V1"
    return 0 if sealed or report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ALLOWED_OVERALL_DECISIONS",
    "ARTIFACT_PATH",
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_INDEPENDENT_CHECK_COUNT",
    "EXPECTED_NEXT_GATE",
    "EXPECTED_PRODUCTION_ADMISSION",
    "EXPECTED_SEEDS",
    "EXPECTED_WIDTHS",
    "VALIDATION_EVIDENCE_PATH",
    "VALIDATION_VERSION",
    "canonical_json_sha256",
    "raw_file_sha256",
    "read_json_strict",
    "run_v47_validation",
    "seal_v47_validation_evidence",
    "validate_v47_artifact",
]
