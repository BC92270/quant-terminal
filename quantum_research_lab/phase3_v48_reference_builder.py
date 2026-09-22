"""Build the fail-closed Quantum Lab V4.8 reference bundle.

V4.8 deliberately starts from the evidence that actually exists locally: one
authenticated historical FakeMarrakesh property identity.  Copies of those
bytes, a normalized representation, and the V4.4 structural snapshot are not
counted as additional calibration epochs.  Consequently this builder seals a
protocol-ready but multi-snapshot-ineligible bundle.

The module is standard-library only.  It does not import Qiskit, discover a
provider, read credentials, open a network connection, or execute a circuit.
It also does not create an optimizer result.  The cost model exposes a strict
interface through which a separately sealed architecture evaluation can later
be checked.
"""

from __future__ import annotations

import argparse
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


BUILDER_VERSION = "PHASE III · V4.8 MULTI-SNAPSHOT REFERENCE BUILDER · V1"
CATALOG_VERSION = "PHASE III · V4.8 AUTHENTIC SNAPSHOT CATALOG · V1"
ORACLE_VERSION = "PHASE III · V4.8 NORMALIZED SNAPSHOT SET ORACLE · V1"
MODEL_VERSION = "PHASE III · V4.8 MULTI-SNAPSHOT ROBUSTNESS COST MODEL · V1"
SPEC_VERSION = "PHASE III · V4.8 MULTI-SNAPSHOT ROBUSTNESS / ARCHITECTURE CZ REDUCTION SPEC · V1"
ARCHITECTURE_INTERFACE_VERSION = "PHASE III · V4.8 ARCHITECTURE EVALUATION INTERFACE · V1"
CREATED_UTC = "2026-09-21T16:20:13Z"

EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
MINIMUM_DISTINCT_SNAPSHOTS = 3
KNOWN_SNAPSHOT_ID = "fake_marrakesh-2025-02-26-d49d7ae07deb"
CURRENT_BLOCKED_DECISION = (
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_"
    "INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES"
)
PRODUCTION_DECISION = "RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED"
NEXT_GATE = (
    "ACQUIRE_AT_LEAST_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_"
    "AND_REDUCE_DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS"
)
ARCHITECTURE_CANDIDATE_ID = "CONTROL_LOADED_CONSTANT_CUCCARO_V1"

CATALOG_FILENAME = "PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json"
ORACLE_FILENAME = "PHASE_III_V4_8_NORMALIZED_SNAPSHOTS_ORACLE_V1.json"
MODEL_FILENAME = "PHASE_III_V4_8_ROBUSTNESS_COST_MODEL_V1.json"
SPEC_FILENAME = "PHASE_III_V4_8_MULTI_SNAPSHOT_CZ_REDUCTION_SPEC_V1.json"

RAW_PROPERTIES_PATH = (
    "quantum_research_lab/"
    "PHASE_III_V4_7_FAKEMARRAKESH_PROPERTIES_2025_02_26_RAW.json"
)
NORMALIZED_PROPERTIES_PATH = (
    "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"
)
V44_SNAPSHOT_PATH = "quantum_research_lab/PHASE_III_V4_4_FROZEN_BACKEND_SNAPSHOT_V1.json"
V47_SPEC_PATH = (
    "quantum_research_lab/"
    "PHASE_III_V4_7_PINNED_DATED_PROPERTIES_OPTIMIZATION_SPEC_V1.json"
)
V47_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/"
    "SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
)
V47_VALIDATION_REPORT_PATH = (
    "outputs/quantum_phase3/v47_dated_properties/SEALED_V4_7_VALIDATION_REPORT.json"
)
V47_FREEZE_PATH = "FREEZE_CONTRACT_V4_7.json"

EXPECTED_RAW_PROPERTIES_SHA256 = "d49d7ae07deb95947ea10e5b9b9c5cbab6df21f98610543817f35ade2b1aece6"
EXPECTED_RAW_PROPERTIES_SIZE = 565_487
EXPECTED_NORMALIZED_RAW_SHA256 = "46203d513fc295639a314cdb4b95aa1eb407f6a303be28c5033086aa2a210a99"
EXPECTED_NORMALIZED_SHA256 = "0e436981a23bd6e75679752f4c139658ef811acc94adc6758b0dc99075e75fe7"
EXPECTED_V44_RAW_SHA256 = "816814f383c7b9890a137ead7799c28f3fbfc0cac188ab274dfb65050e2b7fbd"
EXPECTED_V44_SHA256 = "3a604026627653e697fba1b2b9b06d84298a13ca7a7f2c2f9f2ed551bdbfdaf3"
EXPECTED_V47_SPEC_RAW_SHA256 = "07cd0b0be907e417f5dbe1df62defb90322828e9181a81016b78432e8b5e9644"
EXPECTED_V47_SPEC_SHA256 = "c5b0b294f00a002cf351774c6e91fe17c02896f1517444a42d9dd1b63995574b"
EXPECTED_V47_ARTIFACT_RAW_SHA256 = "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185"
EXPECTED_V47_ARTIFACT_SHA256 = "fa1b8a2be1471080134f34ada7ba8cff488c870aa4e5f271fd29828f1fffbaf"
EXPECTED_V47_VALIDATION_RAW_SHA256 = "60c83320bfe81dddcdfa83ee5c41e6dc17316a6c75ca9140fdffb9ef2f02c082"
EXPECTED_V47_VALIDATION_SHA256 = "1e2b16ab079daddcf59dec200b4df06677c7501bb3ead2532c4d80b0b7302d5c"
EXPECTED_V47_FREEZE_RAW_SHA256 = "89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a"
EXPECTED_V47_FREEZE_SHA256 = "3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858"

# Corrected immediately below in a form that makes accidental partial-string
# edits obvious to source scanners and unit tests.
EXPECTED_V47_ARTIFACT_SHA256 = "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf"


def canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def rendered_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def raw_file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def read_json_strict(path: str | Path) -> dict[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"Non-finite JSON number rejected: {token}")
        ),
    )
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return payload


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    value = payload.get(field)
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == canonical_json_sha256({key: item for key, item in payload.items() if key != field})
    )


def _regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe evidence path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked evidence path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Evidence path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _load_authenticated_parent(root: Path) -> dict[str, dict[str, Any]]:
    expected_raw = {
        RAW_PROPERTIES_PATH: EXPECTED_RAW_PROPERTIES_SHA256,
        NORMALIZED_PROPERTIES_PATH: EXPECTED_NORMALIZED_RAW_SHA256,
        V44_SNAPSHOT_PATH: EXPECTED_V44_RAW_SHA256,
        V47_SPEC_PATH: EXPECTED_V47_SPEC_RAW_SHA256,
        V47_ARTIFACT_PATH: EXPECTED_V47_ARTIFACT_RAW_SHA256,
        V47_VALIDATION_REPORT_PATH: EXPECTED_V47_VALIDATION_RAW_SHA256,
        V47_FREEZE_PATH: EXPECTED_V47_FREEZE_RAW_SHA256,
    }
    paths = {name: _regular(root, name) for name in expected_raw}
    for name, expected in expected_raw.items():
        if raw_file_sha256(paths[name]) != expected:
            raise ValueError(f"Authenticated V4.7 input raw identity mismatch: {name}")
    if paths[RAW_PROPERTIES_PATH].stat().st_size != EXPECTED_RAW_PROPERTIES_SIZE:
        raise ValueError("Authenticated V4.7 raw properties size mismatch.")

    payloads = {
        name: read_json_strict(path)
        for name, path in paths.items()
        if name != RAW_PROPERTIES_PATH
    }
    normalized = payloads[NORMALIZED_PROPERTIES_PATH]
    v44 = payloads[V44_SNAPSHOT_PATH]
    v47_spec = payloads[V47_SPEC_PATH]
    artifact = payloads[V47_ARTIFACT_PATH]
    validation = payloads[V47_VALIDATION_REPORT_PATH]
    freeze = payloads[V47_FREEZE_PATH]
    semantic_checks = (
        normalized.get("properties_snapshot_sha256") == EXPECTED_NORMALIZED_SHA256
        and _self_hash(normalized, "properties_snapshot_sha256")
        and v44.get("snapshot_sha256") == EXPECTED_V44_SHA256
        and _self_hash(v44, "snapshot_sha256")
        and v47_spec.get("v47_spec_sha256") == EXPECTED_V47_SPEC_SHA256
        and canonical_json_sha256(
            {
                key: value
                for key, value in v47_spec.items()
                if key not in {"v47_spec_sha", "v47_spec_sha256"}
            }
        )
        == EXPECTED_V47_SPEC_SHA256
        and artifact.get("artifact_sha256") == EXPECTED_V47_ARTIFACT_SHA256
        and _self_hash(artifact, "artifact_sha256")
        and validation.get("sealed_validation_evidence_sha256") == EXPECTED_V47_VALIDATION_SHA256
        and _self_hash(validation, "sealed_validation_evidence_sha256")
        and freeze.get("freeze_contract_sha256") == EXPECTED_V47_FREEZE_SHA256
        and _self_hash(freeze, "freeze_contract_sha256")
    )
    if not semantic_checks:
        raise ValueError("Authenticated V4.7 semantic lineage mismatch.")
    if (v44.get("properties_provenance") or {}).get("raw_properties_file_sha256") != EXPECTED_RAW_PROPERTIES_SHA256:
        raise ValueError("V4.4 structural snapshot does not point to the exact V4.7 raw property identity.")
    return payloads


def build_snapshot_catalog(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    parent = _load_authenticated_parent(release_root)
    normalized = parent[NORMALIZED_PROPERTIES_PATH]
    v44 = parent[V44_SNAPSHOT_PATH]
    dates = normalized["property_time_range"]
    provenance = normalized["source_provenance"]
    core: dict[str, Any] = {
        "alias_policy": {
            "archive_or_release_copy_of_identical_raw_bytes": "NOT_A_DISTINCT_SNAPSHOT_AND_NOT_CATALOGED_AS_AN_ALIAS",
            "metadata_only_or_filename_only_change": "NOT_A_DISTINCT_SNAPSHOT",
            "normalized_representation_of_same_raw_bytes": "NOT_A_DISTINCT_SNAPSHOT",
            "synthetic_jitter_bootstrap_or_resampling": "NOT_ADMISSIBLE_AS_AN_AUTHENTIC_SNAPSHOT",
        },
        "aliases": [],
        "catalog_version": CATALOG_VERSION,
        "claim_boundary": {
            "current_provider_status": "NOT_QUERIED",
            "hardware_executable": False,
            "network_calls": 0,
            "provider_calls": 0,
            "provider_credentials_read": False,
            "qpu_jobs_submitted": 0,
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "counts": {
            "admitted_alias_count": 0,
            "admitted_snapshot_observation_count": 1,
            "distinct_epoch_count": 1,
            "minimum_distinct_snapshot_identities_required": MINIMUM_DISTINCT_SNAPSHOTS,
            "unique_normalized_property_identity_count": 1,
            "unique_raw_snapshot_identity_count": 1,
        },
        "created_utc": CREATED_UTC,
        "decision": CURRENT_BLOCKED_DECISION,
        "discovery_scope": {
            "catalog_is_exhaustive_for_authenticated_v47_release_inputs": True,
            "copy_containers_are_not_snapshot_observations": True,
            "current_provider_discovery": "NOT_AUTHORIZED_NOT_PERFORMED",
            "known_local_input": RAW_PROPERTIES_PATH,
            "v44_structural_snapshot_is_a_second_property_epoch": False,
        },
        "identity_contract": {
            "distinct_epoch_requires_distinct_property_vector_sha256": True,
            "distinct_epoch_requires_distinct_raw_file_sha256": True,
            "distinct_epoch_requires_distinct_source_timestamp": True,
            "duplicate_bytes_never_increase_sample_size": True,
            "same_backend_family_and_structural_target_required": True,
        },
        "snapshots": [
            {
                "backend_name": normalized["backend"]["backend_name"],
                "basis_gates": normalized["backend"]["basis_gates"],
                "dt_nanoseconds": normalized["backend"]["dt_nanoseconds"],
                "global_last_update_date": dates["global_last_update_date"],
                "maximum_embedded_property_date": dates["maximum_embedded_property_date"],
                "minimum_embedded_property_date": dates["minimum_embedded_property_date"],
                "normalized_properties_path": NORMALIZED_PROPERTIES_PATH,
                "normalized_properties_raw_file_sha256": EXPECTED_NORMALIZED_RAW_SHA256,
                "normalized_properties_sha256": EXPECTED_NORMALIZED_SHA256,
                "num_qubits": normalized["backend"]["num_qubits"],
                "raw_properties_path": RAW_PROPERTIES_PATH,
                "raw_properties_raw_file_sha256": EXPECTED_RAW_PROPERTIES_SHA256,
                "raw_properties_size": EXPECTED_RAW_PROPERTIES_SIZE,
                "role": "DEVELOPMENT_SNAPSHOT_KNOWN_BEFORE_V4_8_PROTOCOL_SEAL",
                "snapshot_id": KNOWN_SNAPSHOT_ID,
                "snapshot_is_current_hardware_evidence": False,
                "source_archive_member": provenance["archive_member"],
                "source_backend_name": normalized["backend"]["source_backend_name"],
                "source_backend_version": normalized["backend"]["source_backend_version"],
                "source_kind": "PINNED_FAKE_PROVIDER_WHEEL_MEMBER_NOT_LIVE_PROVIDER_EXPORT",
                "source_wheel_filename": provenance["wheel_filename"],
                "source_wheel_sha256": provenance["wheel_sha256"],
                "structural_snapshot_path": V44_SNAPSHOT_PATH,
                "structural_snapshot_raw_file_sha256": EXPECTED_V44_RAW_SHA256,
                "structural_snapshot_sha256": EXPECTED_V44_SHA256,
                "structural_target_family": v44["target"]["family"],
            }
        ],
    }
    return {**core, "snapshot_catalog_sha256": canonical_json_sha256(core)}


def build_normalized_snapshots_oracle(
    root: str | Path,
    catalog: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    parent = _load_authenticated_parent(release_root)
    normalized = parent[NORMALIZED_PROPERTIES_PATH]
    actual_catalog = dict(catalog or build_snapshot_catalog(release_root))
    coverage = normalized["coverage"]
    fault = normalized["fault_screen"]
    stats = normalized["statistics"]
    core: dict[str, Any] = {
        "claim_boundary": {
            "hardware_executable": False,
            "network_calls": 0,
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "cohort": {
            "admitted_snapshot_ids": [KNOWN_SNAPSHOT_ID],
            "alias_count": 0,
            "decision": CURRENT_BLOCKED_DECISION,
            "distinct_authentic_snapshot_count": 1,
            "minimum_required": MINIMUM_DISTINCT_SNAPSHOTS,
            "multi_snapshot_eligible": False,
        },
        "created_utc": CREATED_UTC,
        "materialization_contract": {
            "all_976_native_tuples_must_be_loaded_from_the_authenticated_reference": True,
            "missing_invalid_or_nonfinite_property": "REJECT_SNAPSHOT_FAIL_CLOSED",
            "no_imputation": True,
            "no_reverse_edge_fallback": True,
            "normalized_summary_is_not_a_second_snapshot": True,
        },
        "normalized_snapshots": [
            {
                "backend": normalized["backend"],
                "coverage": {
                    "all_required_gate_tuples_complete": coverage["all_required_gate_tuples_complete"],
                    "expected_gate_counts": coverage["expected_gate_counts"],
                    "native_gate_tuple_count": coverage["native_gate_tuple_count"],
                    "required_property_value_count": coverage["required_property_value_count"],
                },
                "fault_screen": {
                    "excluded_directed_cz_edge_count": fault["excluded_directed_cz_edge_count"],
                    "excluded_undirected_cz_edge_count": fault["excluded_undirected_cz_edge_count"],
                    "fault_excluded_component_sizes": fault["fault_excluded_component_sizes"],
                    "isolated_qubits": fault["isolated_qubits"],
                    "largest_component_size": fault["largest_component_size"],
                    "maximum_v46_logical_width": fault["maximum_v46_logical_width"],
                    "width_margin": fault["width_margin"],
                },
                "gate_statistics": stats["gate_properties"],
                "normalized_properties_path": NORMALIZED_PROPERTIES_PATH,
                "normalized_properties_raw_file_sha256": EXPECTED_NORMALIZED_RAW_SHA256,
                "normalized_properties_sha256": EXPECTED_NORMALIZED_SHA256,
                "property_time_range": normalized["property_time_range"],
                "qubit_statistics": stats["qubits"],
                "raw_properties_raw_file_sha256": EXPECTED_RAW_PROPERTIES_SHA256,
                "role": "DEVELOPMENT_ONLY_NOT_A_MULTI_SNAPSHOT_COHORT",
                "snapshot_id": KNOWN_SNAPSHOT_ID,
            }
        ],
        "oracle_version": ORACLE_VERSION,
        "snapshot_catalog_sha256": actual_catalog["snapshot_catalog_sha256"],
    }
    return {**core, "normalized_snapshots_oracle_sha256": canonical_json_sha256(core)}


def _direct_cx_rows(artifact: Mapping[str, Any]) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    for expected_seed, expected_width, row in zip(
        EXPECTED_SEEDS,
        EXPECTED_WIDTHS,
        artifact.get("seed_evaluations") or [],
    ):
        lower = row.get("architecture_lower_bound") or {}
        if int(row.get("seed", -1)) != expected_seed or int(row.get("logical_qubits", -1)) != expected_width:
            raise ValueError("V4.7 seed order or width drifted.")
        rows.append(
            {
                "direct_translated_cx": int(lower["direct_translated_cx"]),
                "logical_qubits": expected_width,
                "seed": expected_seed,
            }
        )
    if len(rows) != len(EXPECTED_SEEDS):
        raise ValueError("V4.7 exact eight-seed architecture evidence required.")
    return rows


def build_robustness_cost_model(
    root: str | Path,
    oracle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    parent = _load_authenticated_parent(release_root)
    artifact = parent[V47_ARTIFACT_PATH]
    actual_oracle = dict(oracle or build_normalized_snapshots_oracle(release_root))
    normalized = parent[NORMALIZED_PROPERTIES_PATH]
    cz_stats = normalized["statistics"]["gate_properties"]["cz"]
    minimum_cz_error = Decimal(str(cz_stats["gate_error"]["minimum"]))
    minimum_cz_duration_ticks = int(cz_stats["duration_ticks"]["minimum"])
    maximum_t2_seconds = Decimal(str(normalized["statistics"]["qubits"]["t2_seconds"]["maximum"]))
    dt_seconds = Decimal(str(normalized["backend"]["dt_seconds"]))
    maximum_t2_ticks = math.floor(maximum_t2_seconds / dt_seconds)
    idealized_parallel_cz_capacity = 78
    duration_screen_direct_cx_ceiling = (
        maximum_t2_ticks // minimum_cz_duration_ticks
    ) * idealized_parallel_cz_capacity
    error_screen_direct_cx_ceiling = int(
        (Decimal(1) / minimum_cz_error).to_integral_value(rounding=ROUND_CEILING)
    ) - 1
    direct_rows = _direct_cx_rows(artifact)
    core: dict[str, Any] = {
        "architecture_evaluation_interface": {
            "architecture_result_may_be_absent": True,
            "candidate_selection_rule": "MINIMIZE_MAXIMUM_DIRECT_CX_THEN_TOTAL_DIRECT_CX_THEN_MAXIMUM_WIDTH_THEN_ARCHITECTURE_ID",
            "interface_version": ARCHITECTURE_INTERFACE_VERSION,
            "required_claim_boundary": {
                "hardware_executable": False,
                "network_calls": 0,
                "provider_calls": 0,
                "qpu_jobs_submitted": 0,
                "research_classification": "RESEARCH_ONLY",
            },
            "required_seed_architecture_fields": [
                "seed",
                "logical_qubits",
                "direct_cx",
                "stream_sha256",
                "semantic_parity_status",
                "clean_ancilla_status",
            ],
            "required_snapshot_seed_fields": [
                "snapshot_id",
                "seed",
                "baseline_native_cz",
                "candidate_native_cz",
                "baseline_makespan_ticks",
                "candidate_makespan_ticks",
                "baseline_reported_gate_error_mass",
                "candidate_reported_gate_error_mass",
                "missing_property_occurrences",
                "unit_error_gate_occurrences",
                "isa_violations",
                "coupling_violations",
            ],
        },
        "architecture_reduction_gate": {
            "candidate_architecture_id": ARCHITECTURE_CANDIDATE_ID,
            "candidate_is_not_evaluated_by_this_reference_bundle": True,
            "candidate_cx_per_add": "17*w-25+2*popcount(c_mod_2_pow_w)",
            "direct_cx_ceiling_all_eight_seeds": duration_screen_direct_cx_ceiling,
            "direct_cx_must_be_strictly_below_v47_for_every_seed": True,
            "legacy_cx_per_add": "68*w-102",
            "maximum_logical_qubits": 156,
            "production_meaning": "NONE_RESEARCH_RESOURCE_GATE_ONLY",
            "required_construction": "CONTROL_LOAD_CLEAN_CONSTANT_EXACT_CUCCARO_CONTROL_UNLOAD",
            "unchanged_scope": "V45_LAYOUT_COIN_SELECTOR_EXCEPT_ADDER_AND_CERTIFIED_BRIDGES",
        },
        "claim_boundary": {
            "calibration_aware_circuit_fidelity": "NOT_CLAIMED",
            "hardware_executable": False,
            "hardware_timing_schedule": "NOT_RUN",
            "network_calls": 0,
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "created_utc": CREATED_UTC,
        "current_evaluation_state": {
            "architecture_evaluation": "NOT_SUPPLIED",
            "multi_snapshot_decision": CURRENT_BLOCKED_DECISION,
            "production_admission": PRODUCTION_DECISION,
        },
        "known_snapshot_necessary_condition_context": {
            "additive_error_mass_exclusive_limit": "1",
            "direct_cx_ceiling_for_strict_additive_error_mass_screen": error_screen_direct_cx_ceiling,
            "direct_cx_ceiling_for_idealized_duration_screen": duration_screen_direct_cx_ceiling,
            "idealized_parallel_cz_capacity": idealized_parallel_cz_capacity,
            "maximum_t2_seconds": format(maximum_t2_seconds, "f"),
            "maximum_t2_ticks_floor": maximum_t2_ticks,
            "minimum_cz_duration_ticks": minimum_cz_duration_ticks,
            "minimum_cz_reported_error": format(minimum_cz_error, "f"),
            "screen_is_necessary_not_sufficient": True,
            "strict_additive_error_mass_is_not_fidelity_or_success_probability": True,
        },
        "model_version": MODEL_VERSION,
        "multi_snapshot_gate": {
            "all_snapshot_seed_cells_required": True,
            "averaging_cannot_rescue_a_failed_cell": True,
            "candidate_makespan_ticks_lte_baseline_every_cell": True,
            "candidate_native_cz_strictly_lt_baseline_every_cell": True,
            "candidate_reported_error_mass_strictly_lt_baseline_every_cell": True,
            "minimum_distinct_authentic_snapshot_identities": MINIMUM_DISTINCT_SNAPSHOTS,
            "missing_property_occurrences_required": 0,
            "snapshot_specific_deterministic_route_required": True,
            "unit_error_gate_occurrences_required": 0,
            "zero_isa_and_coupling_violations_required": True,
        },
        "normalized_snapshots_oracle_sha256": actual_oracle[
            "normalized_snapshots_oracle_sha256"
        ],
        "parent_v47_direct_cx": direct_rows,
        "parent_v47_artifact_sha256": EXPECTED_V47_ARTIFACT_SHA256,
    }
    return {**core, "robustness_cost_model_sha256": canonical_json_sha256(core)}


def build_specification(
    root: str | Path,
    *,
    catalog: Mapping[str, Any] | None = None,
    oracle: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    actual_catalog = dict(catalog or build_snapshot_catalog(release_root))
    actual_oracle = dict(oracle or build_normalized_snapshots_oracle(release_root, actual_catalog))
    actual_model = dict(model or build_robustness_cost_model(release_root, actual_oracle))
    core: dict[str, Any] = {
        "acceptance_contract": {
            "architecture_result_required_for_architecture_pass": True,
            "fail_closed_if_any_seed_or_snapshot_cell_is_missing": True,
            "minimum_distinct_authentic_snapshot_identities": MINIMUM_DISTINCT_SNAPSHOTS,
            "multi_snapshot_pass_requires_every_admitted_snapshot_and_every_seed": True,
            "negative_or_not_evaluable_result_is_valid_scientific_output": True,
            "production_admission_always_rejected_in_v48": True,
        },
        "architecture_contract": {
            "candidate_architecture_id": ARCHITECTURE_CANDIDATE_ID,
            "candidate_selection_and_thresholds_fixed_before_any_new_snapshot_result": True,
            "exact_modular_addition_only": True,
            "frozen_v46_basic_swap_replay_required": True,
            "only_controlled_constant_adder_primitive_may_change": True,
            "semantic_parity_and_clean_ancilla_certificates_required": True,
            "v47_development_snapshot_may_not_be_relabelled_as_holdout": True,
        },
        "chronology": {
            "known_v47_snapshot_inspected_before_v48_seal": True,
            "new_snapshot_results_inspected_before_v48_seal": False,
            "result_state_at_seal": "NOT_EVALUATED",
            "sealed_utc": CREATED_UTC,
        },
        "claim_boundary": {
            "backend_run_calls": 0,
            "credential_reads": 0,
            "hardware_executable": False,
            "local_simulator_jobs_submitted": 0,
            "network_calls": 0,
            "provider_calls": 0,
            "provider_credentials_read": False,
            "provider_sdk_imported": False,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
            "snapshot_is_current_hardware_evidence": False,
        },
        "decision_tree": {
            "architecture_missing_or_invalid": "ARCHITECTURE_CZ_REDUCTION_NOT_EVALUATED_OR_REJECTED",
            "fewer_than_three_distinct_authentic_snapshots": CURRENT_BLOCKED_DECISION,
            "multi_snapshot_all_cells_dominate": "V48_MULTI_SNAPSHOT_MODEL_ROBUSTNESS_DEMONSTRATED_RESEARCH_ONLY",
            "multi_snapshot_any_cell_fails": "V48_MULTI_SNAPSHOT_MODEL_ROBUSTNESS_NOT_DEMONSTRATED",
            "next_falsifiable_gate_when_blocked": NEXT_GATE,
            "production_admission": PRODUCTION_DECISION,
        },
        "family": {
            "K": 10,
            "N": 40,
            "logical_widths": list(EXPECTED_WIDTHS),
            "regime": "BANDS",
            "seeds": list(EXPECTED_SEEDS),
        },
        "input_identities": {
            "normalized_snapshots_oracle_raw_file_sha256": hashlib.sha256(
                rendered_json_bytes(actual_oracle)
            ).hexdigest(),
            "normalized_snapshots_oracle_sha256": actual_oracle[
                "normalized_snapshots_oracle_sha256"
            ],
            "robustness_cost_model_raw_file_sha256": hashlib.sha256(
                rendered_json_bytes(actual_model)
            ).hexdigest(),
            "robustness_cost_model_sha256": actual_model["robustness_cost_model_sha256"],
            "snapshot_catalog_raw_file_sha256": hashlib.sha256(
                rendered_json_bytes(actual_catalog)
            ).hexdigest(),
            "snapshot_catalog_sha256": actual_catalog["snapshot_catalog_sha256"],
            "v47_artifact_raw_file_sha256": EXPECTED_V47_ARTIFACT_RAW_SHA256,
            "v47_artifact_sha256": EXPECTED_V47_ARTIFACT_SHA256,
            "v47_freeze_raw_file_sha256": EXPECTED_V47_FREEZE_RAW_SHA256,
            "v47_freeze_sha256": EXPECTED_V47_FREEZE_SHA256,
        },
        "snapshot_admission_contract": {
            "current_admitted_alias_count": 0,
            "current_distinct_authentic_snapshot_count": 1,
            "distinct_identity_requires_unique_raw_hash_property_vector_hash_and_epoch": True,
            "minimum_distinct_authentic_snapshot_identities": MINIMUM_DISTINCT_SNAPSHOTS,
            "same_bytes_in_multiple_archives_count_once": True,
            "synthetic_or_perturbed_inputs_never_count_as_authentic_snapshots": True,
        },
        "spec_version": SPEC_VERSION,
    }
    return {**core, "v48_spec_sha256": canonical_json_sha256(core)}


def build_reference_bundle(root: str | Path) -> dict[str, dict[str, Any]]:
    catalog = build_snapshot_catalog(root)
    oracle = build_normalized_snapshots_oracle(root, catalog)
    model = build_robustness_cost_model(root, oracle)
    spec = build_specification(root, catalog=catalog, oracle=oracle, model=model)
    return {
        CATALOG_FILENAME: catalog,
        ORACLE_FILENAME: oracle,
        MODEL_FILENAME: model,
        SPEC_FILENAME: spec,
    }


def validate_reference_bundle(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    expected = build_reference_bundle(release_root)
    checks: dict[str, bool] = {}
    errors: list[str] = []
    for filename, payload in expected.items():
        relative = f"quantum_research_lab/{filename}"
        try:
            path = _regular(release_root, relative)
            actual = read_json_strict(path)
            checks[f"{filename}:semantic_exact"] = actual == payload
            checks[f"{filename}:rendered_raw_exact"] = path.read_bytes() == rendered_json_bytes(payload)
        except Exception as exc:
            checks[f"{filename}:semantic_exact"] = False
            checks[f"{filename}:rendered_raw_exact"] = False
            errors.append(f"{filename}: {exc}")
    checks.update(
        {
            "single_unique_snapshot_identity": expected[CATALOG_FILENAME]["counts"][
                "unique_raw_snapshot_identity_count"
            ]
            == 1,
            "zero_admitted_aliases": expected[CATALOG_FILENAME]["counts"]["admitted_alias_count"]
            == 0
            and expected[CATALOG_FILENAME]["aliases"] == [],
            "multi_snapshot_gate_fail_closed": expected[SPEC_FILENAME]["decision_tree"][
                "fewer_than_three_distinct_authentic_snapshots"
            ]
            == CURRENT_BLOCKED_DECISION,
        }
    )
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "builder_version": BUILDER_VERSION,
        "checks": checks,
        "counts": {"checks_passed": len(checks) - len(failed), "checks_total": len(checks)},
        "errors": errors,
        "failed_checks": failed,
        "passed": not failed and not errors,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--emit",
        choices=("catalog", "oracle", "model", "spec", "bundle", "write", "check"),
        default="check",
    )
    args = parser.parse_args(argv)
    if args.emit == "check":
        result: Any = validate_reference_bundle(args.root)
    else:
        bundle = build_reference_bundle(args.root)
        if args.emit == "write":
            output_root = Path(args.root).resolve(strict=True) / "quantum_research_lab"
            written: dict[str, str] = {}
            for filename, payload in bundle.items():
                target = output_root / filename
                target.write_bytes(rendered_json_bytes(payload))
                written[filename] = raw_file_sha256(target)
            result = {"written": written}
            print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
            return 0
        key = {
            "catalog": CATALOG_FILENAME,
            "oracle": ORACLE_FILENAME,
            "model": MODEL_FILENAME,
            "spec": SPEC_FILENAME,
        }.get(args.emit)
        result = bundle if key is None else bundle[key]
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if args.emit != "check" or result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARCHITECTURE_INTERFACE_VERSION",
    "CATALOG_FILENAME",
    "CURRENT_BLOCKED_DECISION",
    "EXPECTED_SEEDS",
    "EXPECTED_WIDTHS",
    "MINIMUM_DISTINCT_SNAPSHOTS",
    "MODEL_FILENAME",
    "NEXT_GATE",
    "ORACLE_FILENAME",
    "PRODUCTION_DECISION",
    "SPEC_FILENAME",
    "build_normalized_snapshots_oracle",
    "build_reference_bundle",
    "build_robustness_cost_model",
    "build_snapshot_catalog",
    "build_specification",
    "canonical_json_sha256",
    "raw_file_sha256",
    "read_json_strict",
    "rendered_json_bytes",
    "validate_reference_bundle",
]
