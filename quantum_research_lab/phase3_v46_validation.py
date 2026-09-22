"""Independent fail-closed validation for the sealed Quantum Lab V4.6 result.

The validator never imports or executes the V4.6 compiler.  It authenticates
the immutable scientific inputs by exact SHA-256, asks the standard-library
checker to recompute its proof obligations, and independently pins the eight
observed routing/resource profiles.  It performs no network, provider,
simulator or QPU operation.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v46_independent_checker import validate_v46_artifact as run_sealed_checker


VALIDATION_VERSION = "QUANTUM LAB V4.6 INDEPENDENT SCIENTIFIC VALIDATION · V1"
EXPECTED_CHECK_COUNT = 57
EXPECTED_INDEPENDENT_CHECK_COUNT = 36

ARTIFACT_PATH = "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json"
PATH_ORACLE_PATH = "quantum_research_lab/PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
TRANSLATION_PATH = "quantum_research_lab/PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
SOURCE_PATH = "quantum_research_lab/phase3_v46_full_stream_routing.py"
CHECKER_PATH = "quantum_research_lab/phase3_v46_independent_checker.py"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_5.json"
PARENT_ARTIFACT_PATH = "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"

EXPECTED_ARTIFACT_RAW_SHA256 = "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694"
EXPECTED_ARTIFACT_SHA256 = "cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832"
EXPECTED_SPEC_RAW_SHA256 = "81ab1238a4623d334da31a686d676ddd5a6f01696f0ded271ecbd0de6b693e95"
EXPECTED_SPEC_SHA256 = "2a2480f6932f3ef41ff94b1450467a703ed260767370a6dc75304f55820addf8"
EXPECTED_PATH_ORACLE_RAW_SHA256 = "faf9573fa7fe7c50e0a872e0d989a8d8938f181a9c136e6138121a53a7e55a5b"
EXPECTED_PATH_ORACLE_SHA256 = "0956cfa11e6a507cf8e4197e8c054b0bd90f4ca2a37ac895b61265e95d91ecf7"
EXPECTED_TRANSLATION_RAW_SHA256 = "7600a95edce3af75fda671f836585e99b837a04527a2f3e29dca8812b0f008dc"
EXPECTED_TRANSLATION_SHA256 = "e0ab1b7612f7dac1ee9946ff296ee82ab603ed069a228d0dbffd537621f266a7"
EXPECTED_SOURCE_RAW_SHA256 = "3e3ab6162fc42e9581adb0510a0385c3b9e7a1c87691e01017a763e0afae1885"
EXPECTED_CHECKER_RAW_SHA256 = "87aa13cc0ea534bdf784bd53663477983cb4cabd02c1c1ed8ea84eb55c1024b7"
EXPECTED_V45_FREEZE_RAW_SHA256 = "1f20e7c3c82c9441132d530a9204b0db19ad0d31c43b867cc029394bda276cd7"
EXPECTED_V45_FREEZE_SHA256 = "05197d460b076275a3c7712aa895959d9d1916b09e1999750e1e36cc0c27a218"
EXPECTED_V45_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_V45_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_V45_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"

# Patched once after this validator's evidence schema is finalized.  The value
# authenticates the validation result, not a hardware or performance claim.
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "3252bce9ea58912261243c49ac3c9704b19f4f05479f5d6ba9f9e1fb4c7118d2"

EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_ROW_METRICS = (
    # seed, width, input instructions, input CX, native instructions, CZ,
    # swaps, structural depth, maximum pre-route distance, chunks, stages,
    # CZ margin and depth margin.
    (1103, 135, 6077566, 2405038, 59482464, 14839144, 4144702, 23878539, 27, 742, 99, 235160856, 226121461),
    (2207, 137, 6086776, 2408638, 59736353, 14916301, 4169221, 23925669, 27, 744, 100, 235083699, 226074331),
    (3301, 133, 5969118, 2361262, 58434154, 14579062, 4072600, 23449597, 26, 729, 99, 235420938, 226550403),
    (4409, 135, 5969230, 2361262, 58388465, 14563795, 4067511, 23416448, 27, 729, 99, 235436205, 226583552),
    (5501, 137, 5969310, 2361262, 58506751, 14603197, 4080645, 23436098, 27, 729, 99, 235396803, 226563902),
    (6607, 137, 6077382, 2405038, 59521637, 14852263, 4149075, 23876346, 26, 742, 99, 235147737, 226123654),
    (7703, 145, 6312490, 2499790, 62128995, 15527797, 4342669, 24893376, 30, 771, 101, 234472203, 225106624),
    (8807, 139, 6185342, 2448814, 60677639, 15148405, 4233197, 24375938, 27, 756, 99, 234851595, 225624062),
)
EXPECTED_AGGREGATE = {
    "aggregate_native_cz": 119029964,
    "aggregate_native_instructions": 476876458,
    "aggregate_swaps": 33259620,
    "maximum_logical_qubits": 145,
    "maximum_native_cz": 15527797,
    "maximum_routed_depth": 24893376,
    "minimum_logical_capacity_margin": 11,
    "ordered_route_ir_root_sha256": "e3552ceff09d10237f6000c75c39acb276745526c7f663b1778b5c07a3300d8f",
    "ordered_seed_routing_root_sha256": "4a3b069472814606134e82aa17823102a028093876cf45a2fad29e45dc3290e7",
    "seed_count": 8,
    "total_input_instructions": 48647214,
}
EXPECTED_OVERALL = "V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_PASSED_STRUCTURAL_AND_PREREGISTERED_RESOURCE_GATES"
EXPECTED_PRODUCTION_ADMISSION = "OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED"
EXPECTED_NEXT_GATE = "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS"


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
        raise ValueError(f"Expected a JSON object: {path}")
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


def _self_hash(payload: Mapping[str, Any], field: str, *also_excluded: str) -> bool:
    excluded = {field, *also_excluded}
    return payload.get(field) == canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in excluded}
    )


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return list(value)


def _static_checker_contract(checker_path: Path, source_path: Path) -> dict[str, bool]:
    forbidden = {
        "qiskit", "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests",
        "httpx", "urllib", "socket", "boto3", "braket", "pennylane",
    }
    checker_tree = ast.parse(checker_path.read_text(encoding="utf-8"))
    source_tree = ast.parse(source_path.read_text(encoding="utf-8"))

    def imports(tree: ast.AST) -> set[str]:
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        return modules

    checker_imports = imports(checker_tree)
    source_imports = imports(source_tree)
    return {
        "checker_no_compiler_import": not any(
            module.endswith("phase3_v46_full_stream_routing") for module in checker_imports
        ),
        "checker_standard_library_provider_free": not any(
            module.split(".")[0] in forbidden for module in checker_imports
        ),
        # The confirmatory compiler deliberately imports socket only to place a
        # blocking mock around reconstruction.  It still imports neither Qiskit
        # nor provider/network-client packages.
        "compiler_no_qiskit_or_provider_client_import": not any(
            module.split(".")[0] in (forbidden - {"socket"}) for module in source_imports
        ),
    }


def _row_metrics(row: Mapping[str, Any]) -> tuple[int, ...]:
    routed = _mapping(row.get("routed_compilation"))
    manifest = _mapping(routed.get("input_stream_manifest"))
    native = _mapping(routed.get("native_ledger"))
    routing = _mapping(routed.get("routing_ledger"))
    route_ir = _mapping(routed.get("route_ir"))
    resource = _mapping(row.get("resource_gate"))
    return (
        int(row.get("seed", -1)),
        int(row.get("logical_qubits", -1)),
        int(manifest.get("instruction_count", -1)),
        int(_mapping(manifest.get("elementary_counts")).get("CX", -1)),
        int(native.get("native_instruction_count", -1)),
        int(_mapping(native.get("native_operation_counts")).get("cz", -1)),
        int(native.get("swap_count", -1)),
        int(native.get("asap_structural_depth", -1)),
        int(routing.get("maximum_distance_before_routing", -1)),
        len(route_ir.get("chunk_sha256") or []),
        len(route_ir.get("stage_manifests") or []),
        int(resource.get("routed_cz_margin", -1)),
        int(resource.get("depth_margin", -1)),
    )


def validate_v46_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate the sealed V4.6 artifact without executing its compiler."""

    base = _root(root)
    errors: list[str] = []
    relative_paths = {
        "artifact": ARTIFACT_PATH,
        "spec": SPEC_PATH,
        "path_oracle": PATH_ORACLE_PATH,
        "translation": TRANSLATION_PATH,
        "source": SOURCE_PATH,
        "checker": CHECKER_PATH,
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
    for name in ("spec", "path_oracle", "translation", "parent_freeze", "parent_artifact"):
        try:
            payloads[name] = read_json_strict(paths[name])
        except Exception as exc:
            payloads[name] = {}
            errors.append(f"{name} strict JSON: {exc}")

    try:
        independent = run_sealed_checker(artifact, root=base, authenticate_parent=True)
    except Exception as exc:
        independent = {"check_count": 0, "errors": [str(exc)], "failed_checks": ["exception"], "valid": False}
        errors.append(f"Independent checker: {exc}")
    try:
        static = _static_checker_contract(paths["checker"], paths["source"])
    except Exception as exc:
        static = {}
        errors.append(f"Static source contract: {exc}")

    spec = payloads["spec"]
    oracle = payloads["path_oracle"]
    translation = payloads["translation"]
    parent_freeze = payloads["parent_freeze"]
    parent_artifact = payloads["parent_artifact"]
    frozen = _mapping(parent_freeze.get("frozen_files"))
    immutable_parent = {
        str(relative): str(expected)
        for relative, expected in frozen.items()
        if str(relative) not in {"quantum_research_lab/README.md", "quantum_research_lab/ui.py"}
    }
    immutable_mismatches: list[str] = []
    for relative, expected in sorted(immutable_parent.items()):
        try:
            candidate = _regular(base, relative)
            if raw_file_sha256(candidate) != expected:
                immutable_mismatches.append(relative)
        except Exception:
            immutable_mismatches.append(relative)

    rows = _rows(artifact.get("seed_routings"))
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    references = _mapping(artifact.get("reference_contracts"))
    parent_link = _mapping(artifact.get("parent"))
    spec_boundary = _mapping(spec.get("claim_boundary"))
    acceptance = _mapping(spec.get("acceptance_contract"))
    chronology = _mapping(spec.get("chronology"))
    thresholds = _mapping(spec.get("inherited_preregistered_resource_contract"))
    oracle_boundary = _mapping(oracle.get("generation_boundary"))
    translation_boundary = _mapping(translation.get("generation_boundary"))
    observed_rows = tuple(_row_metrics(row) for row in rows)

    zero_boundary = bool(
        boundary.get("provider_sdk_imported") is False
        and boundary.get("provider_credentials_read") is False
        and boundary.get("credential_reads") == 0
        and boundary.get("provider_calls") == 0
        and boundary.get("network_calls") == 0
        and boundary.get("backend_run_calls") == 0
        and boundary.get("local_simulator_jobs_submitted") == 0
        and boundary.get("qpu_jobs_submitted") == 0
    )
    reference_zero = all(
        ref.get("provider_sdk_imported") is False
        and ref.get("credential_reads") == 0
        and ref.get("provider_calls") == 0
        and ref.get("network_calls") == 0
        and ref.get("backend_run_calls") == 0
        and ref.get("qpu_jobs_submitted") == 0
        for ref in (oracle_boundary, translation_boundary)
    )
    aggregate_exact = all(aggregate.get(key) == value for key, value in EXPECTED_AGGREGATE.items())

    checks: dict[str, bool] = {
        "artifact_file_raw_identity": paths["artifact"].is_file() and raw_file_sha256(paths["artifact"]) == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_mapping_semantic_identity": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and _self_hash(artifact, "artifact_sha256"),
        "artifact_version_exact": artifact.get("artifact_version") == "PHASE III · V4.6 SEALED FULL-STREAM ROUTING ARTIFACT · V1",
        "artifact_research_classification_exact": artifact.get("research_classification") == "RESEARCH_ONLY",
        "spec_raw_identity": paths["spec"].is_file() and raw_file_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256,
        "spec_semantic_identity": spec.get("v46_spec_sha256") == EXPECTED_SPEC_SHA256 and _self_hash(spec, "v46_spec_sha256", "v46_spec_sha"),
        "spec_short_identity": spec.get("v46_spec_sha") == EXPECTED_SPEC_SHA256[:20].upper(),
        "spec_result_blind_chronology": chronology.get("result_state_at_seal") == "NOT_EVALUATED" and chronology.get("confirmatory_eight_seed_result_state_at_seal") == "NOT_EVALUATED" and acceptance.get("result_state_at_protocol_seal") == "NOT_EVALUATED",
        "spec_pilot_disclosure_retained": "NOT_CONFIRMATORY_EVIDENCE" in str(chronology.get("nonconfirmatory_pilot_disclosure")) and chronology.get("inherited_thresholds_were_sealed_in_v45_before_any_v46_pilot") is True,
        "oracle_raw_identity": paths["path_oracle"].is_file() and raw_file_sha256(paths["path_oracle"]) == EXPECTED_PATH_ORACLE_RAW_SHA256,
        "oracle_semantic_identity": oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256 and _self_hash(oracle, "path_oracle_sha256"),
        "oracle_frozen_shape_exact": oracle.get("backend_name") == "fake_marrakesh" and oracle.get("qiskit_version") == "2.5.2" and oracle.get("target_qubits") == 156 and oracle.get("ordered_path_count") == 24180 and oracle.get("maximum_shortest_path_distance") == 32,
        "translation_raw_identity": paths["translation"].is_file() and raw_file_sha256(paths["translation"]) == EXPECTED_TRANSLATION_RAW_SHA256,
        "translation_semantic_identity": translation.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256 and _self_hash(translation, "translation_contract_sha256"),
        "translation_frozen_shape_exact": translation.get("backend_name") == "fake_marrakesh" and translation.get("qiskit_version") == "2.5.2" and translation.get("target_qubits") == 156 and translation.get("canary_count") == 9 and translation.get("native_basis") == ["cz", "id", "rz", "sx", "x"],
        "source_raw_identity": paths["source"].is_file() and raw_file_sha256(paths["source"]) == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256,
        "checker_raw_identity": paths["checker"].is_file() and raw_file_sha256(paths["checker"]) == EXPECTED_CHECKER_RAW_SHA256 and artifact.get("independent_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256,
        "checker_does_not_import_compiler": static.get("checker_no_compiler_import") is True,
        "checker_standard_library_provider_free": static.get("checker_standard_library_provider_free") is True,
        "confirmatory_compiler_no_qiskit_or_provider_client": static.get("compiler_no_qiskit_or_provider_client_import") is True,
        "independent_checker_passes": independent.get("valid") is True,
        "independent_checker_exact_36_checks": independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT and not independent.get("failed_checks") and not independent.get("errors"),
        "parent_freeze_raw_identity": paths["parent_freeze"].is_file() and raw_file_sha256(paths["parent_freeze"]) == EXPECTED_V45_FREEZE_RAW_SHA256,
        "parent_freeze_semantic_identity": parent_freeze.get("freeze_contract_sha256") == EXPECTED_V45_FREEZE_SHA256 and _self_hash(parent_freeze, "freeze_contract_sha256"),
        "parent_freeze_inventory_exact": len(frozen) == parent_freeze.get("frozen_file_count") == 229 and _path_fingerprint(frozen) == EXPECTED_V45_PATH_FINGERPRINT,
        "parent_227_immutable_files_exact": len(immutable_parent) == 227 and not immutable_mismatches,
        "parent_artifact_raw_identity": paths["parent_artifact"].is_file() and raw_file_sha256(paths["parent_artifact"]) == EXPECTED_V45_ARTIFACT_RAW_SHA256,
        "parent_artifact_semantic_identity": parent_artifact.get("artifact_sha256") == EXPECTED_V45_ARTIFACT_SHA256 and _self_hash(parent_artifact, "artifact_sha256"),
        "parent_artifact_decision_exact": _mapping(parent_artifact.get("decisions")).get("overall") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY",
        "artifact_parent_crosslinks_exact": parent_link.get("freeze_raw_file_sha256") == EXPECTED_V45_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V45_FREEZE_SHA256 and parent_link.get("artifact_raw_file_sha256") == EXPECTED_V45_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V45_ARTIFACT_SHA256 and parent_link.get("immutable_file_count") == 227 and parent_link.get("immutable_files_exact") is True,
        "artifact_spec_crosslinks_exact": artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256,
        "artifact_oracle_crosslinks_exact": references.get("path_oracle_raw_file_sha256") == EXPECTED_PATH_ORACLE_RAW_SHA256 and references.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256,
        "artifact_translation_crosslinks_exact": references.get("translation_contract_raw_file_sha256") == EXPECTED_TRANSLATION_RAW_SHA256 and references.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256,
        "claim_boundary_equals_preregistered_boundary": dict(boundary) == dict(spec_boundary),
        "provider_credentials_network_backend_jobs_zero": zero_boundary,
        "reference_generation_provider_network_jobs_zero": reference_zero,
        "hardware_executable_false": boundary.get("hardware_executable") is False,
        "no_current_snapshot_claim": boundary.get("snapshot_is_current_hardware_evidence") is False,
        "calibration_fidelity_not_tested": boundary.get("calibration_aware_fidelity") == "NOT_TESTED",
        "optimization_performance_not_tested": boundary.get("optimization_performance") == "NOT_TESTED",
        "quantum_advantage_not_claimed": boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "hardware_timing_not_run": boundary.get("hardware_timing_schedule") == "NOT_RUN" and boundary.get("structural_asap_depth_uses_gate_layers_not_calibrated_durations") is True,
        "streaming_only_no_monolithic_qiskit_circuit": boundary.get("confirmatory_compiler_qiskit_imported") is False and boundary.get("monolithic_qiskit_quantum_circuit_constructed") is False,
        "exact_eight_seed_order": tuple(row.get("seed") for row in rows) == EXPECTED_SEEDS,
        "exact_eight_widths": tuple(row.get("logical_qubits") for row in rows) == EXPECTED_WIDTHS,
        "exact_eight_route_profiles": observed_rows == EXPECTED_ROW_METRICS,
        "all_row_statuses_pass": len(rows) == 8 and all(row.get("status") == "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING" for row in rows),
        "all_parent_streams_exact": len(rows) == 8 and all(_mapping(row.get("routed_compilation")).get("input_manifest_exact_parent") is True for row in rows),
        "all_zero_isa_and_coupling_violations": len(rows) == 8 and all(_mapping(_mapping(row.get("routed_compilation")).get("native_ledger")).get("isa_violations") == 0 and _mapping(_mapping(row.get("routed_compilation")).get("native_ledger")).get("coupling_violations") == 0 for row in rows),
        "all_resource_gates_pass": len(rows) == 8 and all(_mapping(row.get("resource_gate")).get("status") == "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE" for row in rows),
        "preregistered_thresholds_exact": thresholds.get("maximum_native_cz_expansion_over_v45_cnot") == 100 and thresholds.get("maximum_routed_cz_per_seed") == 250000000 and thresholds.get("maximum_routed_depth_per_seed") == 250000000 and thresholds.get("required_coupling_violations") == 0 and thresholds.get("required_isa_violations") == 0 and thresholds.get("seed_transpiler") == 4505,
        "aggregate_self_hash": _self_hash(aggregate, "aggregate_sha256"),
        "aggregate_exact_metrics": aggregate_exact,
        "aggregate_all_pass_flags": aggregate.get("all_eight_input_streams_exact_v45") is True and aggregate.get("all_eight_preregistered_resource_gates_pass") is True and aggregate.get("all_eight_structural_routes_pass") is True,
        "overall_decision_exact": decisions.get("overall") == EXPECTED_OVERALL,
        "production_admission_rejected_exact": decisions.get("production_admission") == EXPECTED_PRODUCTION_ADMISSION,
        "next_falsifiable_gate_exact": decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.6 validation check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(str(item) for item in independent.get("errors") or [])
    evidence_core = {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {
            "checks_passed": sum(value is True for value in checks.values()),
            "checks_total": len(checks),
        },
        "independent_checker_check_count": independent.get("check_count"),
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **evidence_core,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "immutable_parent_mismatches": immutable_mismatches,
        "passed": not failed and not errors,
        "root": str(base),
        "validation_evidence_sha256": canonical_json_sha256(evidence_core),
    }


def run_v46_validation(*, root: str | Path | None = None) -> dict[str, Any]:
    base = _root(root)
    artifact = read_json_strict(_regular(base, ARTIFACT_PATH))
    return validate_v46_artifact(artifact, root=base)


def seal_v46_validation_evidence(
    *,
    root: str | Path | None,
    replay_artifact: str | Path,
    output: str | Path,
) -> dict[str, Any]:
    """Seal validation plus an already completed clean-process replay.

    The caller is responsible for launching the replay in the declared clean
    process. This function authenticates the produced bytes and records only
    falsifiable identities; it does not infer hardware or physics evidence.
    """

    base = _root(root)
    report = run_v46_validation(root=base)
    replay_path = Path(replay_artifact).resolve(strict=True)
    sealed_path = _regular(base, ARTIFACT_PATH)
    replay_payload = read_json_strict(replay_path)
    replay_raw = raw_file_sha256(replay_path)
    replay_semantic = replay_payload.get("artifact_sha256")
    replay_self_hash = _self_hash(replay_payload, "artifact_sha256")
    replay_equal = replay_path.read_bytes() == sealed_path.read_bytes()
    replay_valid = bool(
        replay_raw == EXPECTED_ARTIFACT_RAW_SHA256
        and replay_semantic == EXPECTED_ARTIFACT_SHA256
        and replay_self_hash
        and replay_equal
    )
    if report.get("passed") is not True or not replay_valid:
        raise ValueError(
            "Cannot seal V4.6 validation evidence: scientific validation or "
            "clean-process replay identity failed."
        )
    core: dict[str, Any] = {
        "artifact_raw_file_sha256": EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_sha256": EXPECTED_ARTIFACT_SHA256,
        "claim_boundary": {
            "hardware_executable": False,
            "provider_calls": 0,
            "network_calls": 0,
            "backend_run_calls": 0,
            "local_simulator_jobs_submitted": 0,
            "qpu_jobs_submitted": 0,
            "quantum_advantage": "NOT_CLAIMED",
            "research_classification": "RESEARCH_ONLY",
        },
        "clean_process_replay": {
            "artifact_raw_file_sha256": replay_raw,
            "artifact_sha256": replay_semantic,
            "byte_for_byte_equal_to_sealed_artifact": replay_equal,
            "command_contract": "env -i PATH=<INHERITED> PYTHONPATH=<RELEASE_ROOT> python3 -m quantum_research_lab.phase3_v46_full_stream_routing --root <RELEASE_ROOT> --output <FRESH_TEMP>/replay.json",
            "performed": True,
            "provider_and_job_boundary_in_replayed_artifact": "ZERO_PROVIDER_ZERO_NETWORK_ZERO_BACKEND_RUN_ZERO_SIMULATOR_JOB_ZERO_QPU_JOB",
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
        "validation_evidence_version": "QUANTUM LAB V4.6 VALIDATION EVIDENCE · V1",
    }
    payload = {
        **core,
        "sealed_validation_evidence_sha256": canonical_json_sha256(core),
    }
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return payload


def _main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path)
    parser.add_argument("--root", dest="root_option", type=Path)
    parser.add_argument("--replay-artifact", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass root positionally or with --root, not both.")
    root = args.root_option or args.root_positional
    try:
        if bool(args.replay_artifact) != bool(args.output):
            parser.error("--replay-artifact and --output must be supplied together.")
        report = (
            seal_v46_validation_evidence(
                root=root,
                replay_artifact=args.replay_artifact,
                output=args.output,
            )
            if args.replay_artifact and args.output
            else run_v46_validation(root=root)
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
    sealed = report.get("validation_evidence_version") == "QUANTUM LAB V4.6 VALIDATION EVIDENCE · V1"
    return 0 if sealed or report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_PATH",
    "EXPECTED_AGGREGATE",
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CHECKER_RAW_SHA256",
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_INDEPENDENT_CHECK_COUNT",
    "EXPECTED_NEXT_GATE",
    "EXPECTED_OVERALL",
    "EXPECTED_PATH_ORACLE_RAW_SHA256",
    "EXPECTED_PATH_ORACLE_SHA256",
    "EXPECTED_PRODUCTION_ADMISSION",
    "EXPECTED_ROW_METRICS",
    "EXPECTED_SEEDS",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_SPEC_RAW_SHA256",
    "EXPECTED_SPEC_SHA256",
    "EXPECTED_TRANSLATION_RAW_SHA256",
    "EXPECTED_TRANSLATION_SHA256",
    "EXPECTED_VALIDATION_EVIDENCE_SHA256",
    "EXPECTED_WIDTHS",
    "VALIDATION_VERSION",
    "canonical_json_sha256",
    "raw_file_sha256",
    "read_json_strict",
    "run_v46_validation",
    "seal_v46_validation_evidence",
    "validate_v46_artifact",
]
