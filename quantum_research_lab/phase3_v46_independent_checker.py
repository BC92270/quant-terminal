"""Standard-library-only independent checker for Quantum Lab V4.6.

The checker does not import the V4.6 compiler, Qiskit, a provider SDK or any
network client.  It authenticates the sealed parent, all nested commitments,
the exact native-count algebra, BasicSwap distance/SWAP accounting, final
layout permutations and every preregistered resource and governance boundary.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_SPEC_RAW_SHA256 = "81ab1238a4623d334da31a686d676ddd5a6f01696f0ded271ecbd0de6b693e95"
EXPECTED_SPEC_SHA256 = "2a2480f6932f3ef41ff94b1450467a703ed260767370a6dc75304f55820addf8"
EXPECTED_PATH_ORACLE_RAW_SHA256 = "faf9573fa7fe7c50e0a872e0d989a8d8938f181a9c136e6138121a53a7e55a5b"
EXPECTED_PATH_ORACLE_SHA256 = "0956cfa11e6a507cf8e4197e8c054b0bd90f4ca2a37ac895b61265e95d91ecf7"
EXPECTED_TRANSLATION_RAW_SHA256 = "7600a95edce3af75fda671f836585e99b837a04527a2f3e29dca8812b0f008dc"
EXPECTED_TRANSLATION_SHA256 = "e0ab1b7612f7dac1ee9946ff296ee82ab603ed069a228d0dbffd537621f266a7"
EXPECTED_V45_FREEZE_RAW_SHA256 = "1f20e7c3c82c9441132d530a9204b0db19ad0d31c43b867cc029394bda276cd7"
EXPECTED_V45_FREEZE_SHA256 = "05197d460b076275a3c7712aa895959d9d1916b09e1999750e1e36cc0c27a218"
EXPECTED_V45_PATH_FINGERPRINT = "1c81474eee596a857d099c7882ddb02d409a620a2ddf311f25c783c491370d14"
EXPECTED_V45_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_V45_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
TARGET_QUBITS = 156
SUCCESSOR_MUTABLE = {"quantum_research_lab/README.md", "quantum_research_lab/ui.py"}
EXPECTED_CHECK_COUNT = 36


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


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
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


def _authenticate_parent(root: Path) -> tuple[dict[str, Any], bool, list[str]]:
    errors: list[str] = []
    try:
        freeze_path = root / "FREEZE_CONTRACT_V4_5.json"
        freeze = read_json_strict(freeze_path)
        frozen = _mapping(freeze.get("frozen_files"))
        freeze_ok = bool(
            raw_file_sha256(freeze_path) == EXPECTED_V45_FREEZE_RAW_SHA256
            and freeze.get("freeze_contract_sha256") == EXPECTED_V45_FREEZE_SHA256
            and _self_hash(freeze, "freeze_contract_sha256")
            and len(frozen) == freeze.get("frozen_file_count") == 229
            and _path_fingerprint(frozen) == EXPECTED_V45_PATH_FINGERPRINT
        )
        immutable = {str(key): str(value) for key, value in frozen.items() if str(key) not in SUCCESSOR_MUTABLE}
        mismatches = [
            relative
            for relative, expected in immutable.items()
            if not (root / relative).is_file()
            or (root / relative).is_symlink()
            or raw_file_sha256(root / relative) != expected
        ]
        if not freeze_ok or len(immutable) != 227 or mismatches:
            errors.append(f"V4.5 freeze/immutable mismatch: count={len(immutable)} paths={mismatches[:5]}")
        artifact_path = root / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"
        artifact = read_json_strict(artifact_path)
        artifact_ok = bool(
            raw_file_sha256(artifact_path) == EXPECTED_V45_ARTIFACT_RAW_SHA256
            and artifact.get("artifact_sha256") == EXPECTED_V45_ARTIFACT_SHA256
            and _self_hash(artifact, "artifact_sha256")
            and (_mapping(artifact.get("decisions"))).get("overall")
            == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY"
        )
        if not artifact_ok:
            errors.append("V4.5 artifact identity or decision mismatch.")
    except Exception as exc:
        artifact = {}
        errors.append(str(exc))
    return artifact, not errors, errors


def validate_v46_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    base = Path(root).resolve()
    errors: list[str] = []
    try:
        spec_path = base / "quantum_research_lab/PHASE_III_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_SPEC_V1.json"
        oracle_path = base / "quantum_research_lab/PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
        translation_path = base / "quantum_research_lab/PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
        source_path = base / "quantum_research_lab/phase3_v46_full_stream_routing.py"
        checker_path = base / "quantum_research_lab/phase3_v46_independent_checker.py"
        spec = read_json_strict(spec_path)
        oracle = read_json_strict(oracle_path)
        translation = read_json_strict(translation_path)
        parent, parent_ok, parent_errors = _authenticate_parent(base)
        if not authenticate_parent:
            # Candidate construction still binds the exact frozen parent artifact;
            # immutable-path authentication is exercised by the compiler itself.
            parent_ok = bool(
                raw_file_sha256(base / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json")
                == EXPECTED_V45_ARTIFACT_RAW_SHA256
                and parent.get("artifact_sha256") == EXPECTED_V45_ARTIFACT_SHA256
            )
            parent_errors = [] if parent_ok else parent_errors
        errors.extend(parent_errors)
    except Exception as exc:
        spec = oracle = translation = parent = {}
        source_path = checker_path = base
        parent_ok = False
        errors.append(str(exc))

    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    parent_link = _mapping(artifact.get("parent"))
    references = _mapping(artifact.get("reference_contracts"))
    aggregate = _mapping(artifact.get("aggregate"))
    seed_rows = _rows(artifact.get("seed_routings"))
    parent_seed_rows = _rows(parent.get("seed_materializations"))
    parent_by_seed = {int(row.get("seed", -1)): row for row in parent_seed_rows}
    thresholds = _mapping(spec.get("inherited_preregistered_resource_contract"))

    seed_self_hashes = True
    nested_self_hashes = True
    stream_parent_exact = True
    route_chunks_exact = True
    route_stage_totals_exact = True
    distance_swap_identity = True
    native_count_algebra = True
    layout_permutations_exact = True
    resource_rows_exact = True
    structural_rows_exact = True
    seed_hashes: list[Any] = []
    total_instructions = 0
    total_native = 0
    total_cz = 0
    total_swaps = 0
    maximum_cz = 0
    maximum_depth = 0
    maximum_width = 0
    minimum_margin = TARGET_QUBITS
    route_roots: list[Any] = []

    for row in seed_rows:
        seed = int(row.get("seed", -1))
        seed_hashes.append(row.get("seed_routing_sha256"))
        seed_self_hashes = seed_self_hashes and _self_hash(row, "seed_routing_sha256")
        routed = _mapping(row.get("routed_compilation"))
        manifest = _mapping(routed.get("input_stream_manifest"))
        route_ir = _mapping(routed.get("route_ir"))
        native = _mapping(routed.get("native_ledger"))
        layout = _mapping(routed.get("layout"))
        routing = _mapping(routed.get("routing_ledger"))
        resource = _mapping(row.get("resource_gate"))
        nested_self_hashes = nested_self_hashes and all(
            (
                _self_hash(manifest, "stream_manifest_sha256"),
                _self_hash(route_ir, "route_ir_sha256"),
                _self_hash(native, "native_ledger_sha256"),
                _self_hash(layout, "layout_sha256"),
                _self_hash(routing, "routing_ledger_sha256"),
                _self_hash(resource, "resource_gate_sha256"),
            )
        )
        parent_row = _mapping(parent_by_seed.get(seed))
        stream_parent_exact = stream_parent_exact and bool(
            routed.get("input_manifest_exact_parent") is True
            and manifest == _mapping(parent_row.get("stream_manifest"))
            and row.get("parent_seed_materialization_sha256") == parent_row.get("seed_materialization_sha256")
        )
        instruction_count = int(manifest.get("instruction_count", -1))
        chunk_sizes = route_ir.get("chunk_instruction_sizes") or []
        chunk_hashes = route_ir.get("chunk_sha256") or []
        route_chunks_exact = route_chunks_exact and bool(
            route_ir.get("input_instruction_count") == instruction_count
            and sum(int(value) for value in chunk_sizes) == instruction_count
            and len(chunk_sizes) == len(chunk_hashes)
            and all(0 < int(value) <= 8192 for value in chunk_sizes)
            and all(_is_sha(value) for value in chunk_hashes)
            and _is_sha(route_ir.get("route_record_stream_sha256"))
        )
        stage_rows = _rows(route_ir.get("stage_manifests"))
        stage_instruction_sum = sum(int(stage.get("input_instruction_count", 0)) for stage in stage_rows)
        stage_swap_sum = sum(int(stage.get("swap_count", 0)) for stage in stage_rows)
        swap_count = int(native.get("swap_count", -1))
        route_stage_totals_exact = route_stage_totals_exact and bool(
            stage_instruction_sum == instruction_count
            and stage_swap_sum == swap_count
            and all(_is_sha(stage.get("route_record_sha256")) for stage in stage_rows)
        )
        histogram = _mapping(routing.get("distance_histogram_before_each_cx"))
        input_counts = _mapping(manifest.get("elementary_counts"))
        input_cx = int(input_counts.get("CX", -1))
        distance_swap_identity = distance_swap_identity and bool(
            sum(int(count) for count in histogram.values()) == input_cx
            and sum((int(distance) - 1) * int(count) for distance, count in histogram.items()) == swap_count
            and int(routing.get("maximum_distance_before_routing", -1)) == max((int(value) for value in histogram), default=0)
        )
        native_counts = _mapping(native.get("native_operation_counts"))
        expected_counts = {
            "cz": input_cx + 3 * swap_count,
            "id": 0,
            "rz": 2 * int(input_counts.get("H", 0)) + int(input_counts.get("T", 0)) + int(input_counts.get("TDG", 0)) + 3 * int(input_counts.get("RY", 0)) + int(input_counts.get("RZ", 0)) + 4 * input_cx,
            "sx": int(input_counts.get("H", 0)) + 2 * int(input_counts.get("RY", 0)) + 2 * input_cx + 6 * swap_count,
            "x": int(input_counts.get("X", 0)),
        }
        native_count_algebra = native_count_algebra and bool(
            dict(native_counts) == expected_counts
            and native.get("direct_translated_cx_count") == input_cx
            and native.get("native_instruction_count") == sum(expected_counts.values())
        )
        logical_to_physical = layout.get("final_logical_to_physical") or []
        physical_to_logical = layout.get("final_physical_to_logical") or []
        width = int(row.get("logical_qubits", -1))
        inverse_ok = bool(
            len(logical_to_physical) == width
            and len(physical_to_logical) == TARGET_QUBITS
            and len(set(int(value) for value in logical_to_physical)) == width
            and all(0 <= int(value) < TARGET_QUBITS for value in logical_to_physical)
        )
        if inverse_ok:
            inverse_ok = all(physical_to_logical[int(physical)] == logical for logical, physical in enumerate(logical_to_physical))
        layout_permutations_exact = layout_permutations_exact and inverse_ok
        routed_cz = int(native_counts.get("cz", -1))
        depth = int(native.get("asap_structural_depth", -1))
        ratio = Fraction(routed_cz, input_cx)
        resource_rows_exact = resource_rows_exact and bool(
            resource.get("v45_input_cx") == input_cx
            and resource.get("cz_expansion_ratio_exact") == f"{ratio.numerator}/{ratio.denominator}"
            and resource.get("cz_expansion_ratio_maximum") == thresholds.get("maximum_native_cz_expansion_over_v45_cnot")
            and resource.get("maximum_routed_cz") == thresholds.get("maximum_routed_cz_per_seed")
            and resource.get("maximum_routed_depth") == thresholds.get("maximum_routed_depth_per_seed")
            and resource.get("routed_cz_margin") == int(thresholds.get("maximum_routed_cz_per_seed", -1)) - routed_cz
            and resource.get("depth_margin") == int(thresholds.get("maximum_routed_depth_per_seed", -1)) - depth
            and ratio <= int(thresholds.get("maximum_native_cz_expansion_over_v45_cnot", -1))
            and routed_cz <= int(thresholds.get("maximum_routed_cz_per_seed", -1))
            and depth <= int(thresholds.get("maximum_routed_depth_per_seed", -1))
            and resource.get("status") == "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE"
        )
        structural_rows_exact = structural_rows_exact and bool(
            row.get("status") == "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING"
            and width <= TARGET_QUBITS
            and native.get("coupling_violations") == 0
            and native.get("isa_violations") == 0
            and native.get("native_basis") == ["cz", "id", "rz", "sx", "x"]
            and routing.get("routing_method") == "QISKIT_2_5_2_BASIC_SWAP_FROZEN_ORDERED_SHORTEST_PATH_ORACLE"
            and routing.get("transpiler_seed") == 4505
        )
        total_instructions += instruction_count
        total_native += int(native.get("native_instruction_count", 0))
        total_cz += routed_cz
        total_swaps += swap_count
        maximum_cz = max(maximum_cz, routed_cz)
        maximum_depth = max(maximum_depth, depth)
        maximum_width = max(maximum_width, width)
        minimum_margin = min(minimum_margin, TARGET_QUBITS - width)
        route_roots.append(route_ir.get("route_ir_sha256"))

    aggregate_recomputed = bool(
        aggregate.get("seed_count") == len(seed_rows) == 8
        and aggregate.get("total_input_instructions") == total_instructions
        and aggregate.get("aggregate_native_instructions") == total_native
        and aggregate.get("aggregate_native_cz") == total_cz
        and aggregate.get("aggregate_swaps") == total_swaps
        and aggregate.get("maximum_native_cz") == maximum_cz
        and aggregate.get("maximum_routed_depth") == maximum_depth
        and aggregate.get("maximum_logical_qubits") == maximum_width
        and aggregate.get("minimum_logical_capacity_margin") == minimum_margin
        and aggregate.get("ordered_seed_routing_root_sha256") == canonical_json_sha256(seed_hashes)
        and aggregate.get("ordered_route_ir_root_sha256") == canonical_json_sha256(route_roots)
    )

    checks: dict[str, bool] = {
        "artifact_self_hash": _self_hash(artifact, "artifact_sha256"),
        "artifact_version": artifact.get("artifact_version") == "PHASE III · V4.6 SEALED FULL-STREAM ROUTING ARTIFACT · V1",
        "spec_raw_identity": spec_path.is_file() and raw_file_sha256(spec_path) == EXPECTED_SPEC_RAW_SHA256,
        "spec_semantic_identity": bool(spec.get("v46_spec_sha256") == EXPECTED_SPEC_SHA256 and canonical_json_sha256({key: value for key, value in spec.items() if key not in {"v46_spec_sha", "v46_spec_sha256"}}) == EXPECTED_SPEC_SHA256),
        "oracle_raw_identity": oracle_path.is_file() and raw_file_sha256(oracle_path) == EXPECTED_PATH_ORACLE_RAW_SHA256,
        "oracle_semantic_identity": bool(oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256 and _self_hash(oracle, "path_oracle_sha256")),
        "translation_raw_identity": translation_path.is_file() and raw_file_sha256(translation_path) == EXPECTED_TRANSLATION_RAW_SHA256,
        "translation_semantic_identity": bool(translation.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256 and _self_hash(translation, "translation_contract_sha256")),
        "source_crosslink": source_path.is_file() and artifact.get("source_raw_file_sha256") == raw_file_sha256(source_path),
        "checker_crosslink": checker_path.is_file() and artifact.get("independent_checker_raw_file_sha256") == raw_file_sha256(checker_path),
        "artifact_spec_crosslinks": artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256,
        "artifact_reference_crosslinks": bool(references.get("path_oracle_raw_file_sha256") == EXPECTED_PATH_ORACLE_RAW_SHA256 and references.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256 and references.get("translation_contract_raw_file_sha256") == EXPECTED_TRANSLATION_RAW_SHA256 and references.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256),
        "parent_authentication": parent_ok,
        "parent_crosslinks": bool(parent_link.get("freeze_raw_file_sha256") == EXPECTED_V45_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V45_FREEZE_SHA256 and parent_link.get("artifact_raw_file_sha256") == EXPECTED_V45_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V45_ARTIFACT_SHA256 and parent_link.get("immutable_file_count") == 227 and parent_link.get("immutable_files_exact") is True),
        "seed_order": [row.get("seed") for row in seed_rows] == list(EXPECTED_SEEDS),
        "widths_exact": [row.get("logical_qubits") for row in seed_rows] == list(EXPECTED_WIDTHS),
        "seed_self_hashes": seed_self_hashes,
        "nested_self_hashes": nested_self_hashes,
        "stream_parent_exact": stream_parent_exact,
        "route_chunks_exact": route_chunks_exact,
        "route_stage_totals_exact": route_stage_totals_exact,
        "distance_swap_identity": distance_swap_identity,
        "native_count_algebra": native_count_algebra,
        "layout_permutations_exact": layout_permutations_exact,
        "resource_rows_exact": resource_rows_exact,
        "structural_rows_exact": structural_rows_exact,
        "aggregate_self_hash": _self_hash(aggregate, "aggregate_sha256"),
        "aggregate_recomputed": aggregate_recomputed,
        "aggregate_pass_flags": bool(aggregate.get("all_eight_input_streams_exact_v45") is True and aggregate.get("all_eight_preregistered_resource_gates_pass") is True and aggregate.get("all_eight_structural_routes_pass") is True),
        "decision_exact": decisions.get("overall") == "V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_PASSED_STRUCTURAL_AND_PREREGISTERED_RESOURCE_GATES",
        "production_rejected": decisions.get("production_admission") == "OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED",
        "next_gate_exact": decisions.get("next_falsifiable_gate") == "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS",
        "research_classification": artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("research_classification") == "RESEARCH_ONLY",
        "provider_network_job_zero": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0),
        "hardware_false": boundary.get("hardware_executable") is False,
        "calibration_performance_advantage_boundary": bool(boundary.get("snapshot_is_current_hardware_evidence") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.6 independent checker count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.6 STANDARD-LIBRARY INDEPENDENT CHECKER · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    artifact_path = Path(args.artifact)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parents[1]
    report = validate_v46_artifact(read_json_strict(artifact_path), root=root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_CHECK_COUNT", "validate_v46_artifact"]
