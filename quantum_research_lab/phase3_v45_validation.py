"""Fail-closed independent validation for Quantum Lab V4.5.

The default path authenticates the sealed artifact, the standalone liveness
certificate and the standard-library proof checker without importing the V4.5
generator.  An explicit ``rebuild=True`` adds a deterministic reconstruction;
that opt-in path is still provider-free and submits no simulator or QPU job.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v45_width_proof_checker import (
    canonical_json_sha256,
    read_json_strict,
    validate_v45_artifact as run_independent_checker,
)


EXPECTED_CHECK_COUNT = 51
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_V43_WIDTHS = (330, 331, 327, 328, 329, 331, 339, 334)
EXPECTED_SPEC_RAW_SHA256 = "fca97bae23543fccb04ba7ca606fa2abb9e4c6e4ebeae3c1501031967a3bfea2"
EXPECTED_SPEC_SHA256 = "ba0c41d1bd0d43817a46c9d66d84eb2ba517bf8dd3975387324726d24487e4e6"
EXPECTED_V44_FREEZE_RAW_SHA256 = "f7b4507410aee41e409b3a0a1ce36ba1adff38299dc8a2d424e13885598ada13"
EXPECTED_V44_FREEZE_SHA256 = "e17aa8ce04c97416f7f0565f2eda4f16b739c5c921fb58ee25752a546ffe95b3"
EXPECTED_V44_ARTIFACT_RAW_SHA256 = "3b6824965fa7b2829981d6d35eec5413a24f7340719613e7cd2e8512d6285488"
EXPECTED_V44_ARTIFACT_SHA256 = "de1ba4194a0f7220b1cfcb0c61f8faed3f187c0e9c7712775cba53fa79ed98bb"

# Result-derived identities are intentionally impossible sentinels until the
# certificate and artifact have been sealed.  The release seal must replace
# all result identities and the stable validation commitment with lowercase
# 64-character SHA-256 digests.
EXPECTED_SOURCE_RAW_SHA256 = "5167e23d7096d8f2b6671decc06c4ac4e3822be4bd7990a057f3daf2370db74c"
EXPECTED_CHECKER_RAW_SHA256 = "c9723894e85d7ce651502622b9d557beee1efb8a92663c92341e42c071d74558"
EXPECTED_CERTIFICATE_RAW_SHA256 = "5ae77c160255d881a2f596459e6f1ca61bf7fd0645bbfeb118f753e43930b7da"
EXPECTED_CERTIFICATE_SHA256 = "93f119c6493fac2eb0e7d281db1842482201cd7a680cf8ca93b9fdcc69a53102"
EXPECTED_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "c6eaa30664e80c62c63441536dc4900ce138fb7f5ecbd4521d856d5bc3808eda"

CNOT_BUDGET = 2_500_000
TARGET_QUBITS = 156
DESIGN_CEILING_QUBITS = 145


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _paths(root: str | Path | None = None) -> dict[str, Path]:
    base = _root(root)
    return {
        "root": base,
        "artifact": base / "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json",
        "certificate": base / "quantum_research_lab/PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json",
        "checker": base / "quantum_research_lab/phase3_v45_width_proof_checker.py",
        "source": base / "quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py",
        "spec": base / "quantum_research_lab/PHASE_III_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_SPEC_V1.json",
    }


def _raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _self_hashed(payload: Mapping[str, Any], field: str) -> bool:
    return payload.get(field) == canonical_json_sha256(
        {key: value for key, value in payload.items() if key != field}
    )


def _finalized_sha(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _static_contract(source_path: Path, checker_path: Path, validation_path: Path) -> dict[str, Any]:
    """Inspect source structure without executing the generator."""

    forbidden_modules = {
        "qiskit_ibm_runtime", "qiskit_ibm_provider", "requests", "httpx",
        "urllib", "socket", "boto3", "braket", "pennylane",
    }
    forbidden_symbols = {
        "QiskitRuntimeService", "IBMProvider", "SamplerV2", "EstimatorV2",
        "least_busy", "save_account",
    }
    details: dict[str, Any] = {}
    provider_free = True
    checker_imports_generator = False
    for label, path in (("source", source_path), ("checker", checker_path), ("validation", validation_path)):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        names: set[str] = set()
        attributes: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                attributes.add(node.attr)
        forbidden_imports = sorted(
            module for module in imported
            if module.split(".")[0] in forbidden_modules or module in forbidden_modules
        )
        forbidden_names = sorted((names | attributes) & forbidden_symbols)
        provider_free &= not forbidden_imports and not forbidden_names
        if label == "checker":
            checker_imports_generator = any(
                module.endswith("phase3_v45_proof_carrying_width_reduction") for module in imported
            )
        details[label] = {
            "forbidden_imports": forbidden_imports,
            "forbidden_symbols": forbidden_names,
        }

    source_text = source_path.read_text(encoding="utf-8")
    source_tree = ast.parse(source_text)
    functions = {
        node.name: node for node in source_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    rccx_text = ast.get_source_segment(source_text, functions.get("_emit_rccx")) or ""
    relative_text = ast.get_source_segment(source_text, functions.get("_emit_relative_phase_mcx")) or ""
    clear_text = ast.get_source_segment(source_text, functions.get("_emit_streamed_target_bit_clear")) or ""
    oracle_text = ast.get_source_segment(source_text, functions.get("emit_streamed_feasibility_oracle")) or ""
    selector_text = ast.get_source_segment(source_text, functions.get("emit_binary_selector")) or ""
    rings_text = ast.get_source_segment(source_text, functions.get("emit_binary_coin_rings")) or ""
    exact_adjoint = bool(
        "reversed(operations) if adjoint else operations" in rccx_text
        and '"T": "TDG"' in rccx_text
        and '"TDG": "T"' in rccx_text
        and "reversed(gates) if adjoint else gates" in relative_text
        and "adjoint=adjoint" in relative_text
    )
    clear_is_reverse = bool(
        clear_text.find("address=add_address") < clear_text.find("address=remove_address")
        and clear_text.count("adjoint=True") == 2
        and clear_text.rfind("stream.cx") > clear_text.find("address=remove_address")
    )
    bennett_reverse = bool(
        "range(len(rows) - 1, -1, -1)" in oracle_text
        and "_REBUILD" in oracle_text
        and "_PREDICATE_CLEAR" in oracle_text
        and "_RECLEAR" in oracle_text
    )
    selector_exact = all(
        marker in selector_text
        for marker in (
            "SELECT_ADDRESS_READ_REMOVE", "SELECT_ADDRESS_READ_ADD",
            "SELECT_FORWARD_ORACLE", "SELECT_MOVE_COMPUTE",
            "SELECT_DATA_UPDATE_REMOVE", "SELECT_DATA_UPDATE_ADD",
            "SELECT_MOVE_CLEAR", "SELECT_REVERSE_ORACLE",
            "SELECT_ADDRESS_CLEAR_ADD", "SELECT_ADDRESS_CLEAR_REMOVE",
        )
    )
    rings_exact = bool(
        'for register_name in ("REMOVE_ADDR", "ADD_ADDR")' in rings_text
        and "for source in range(VALID_ADDRESS_COUNT)" in rings_text
        and "target=(source + 1) % VALID_ADDRESS_COUNT" in rings_text
    )
    reset_calls = [
        node for node in ast.walk(source_tree)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name) and node.func.id.lower() in {"reset", "measure"}
            or isinstance(node.func, ast.Attribute) and node.func.attr.lower() in {"reset", "measure"}
        )
    ]
    return {
        "bennett_reverse_structure": bennett_reverse,
        "checker_imports_generator": checker_imports_generator,
        "details": details,
        "exact_adjoint_structure": exact_adjoint and clear_is_reverse,
        "provider_free": provider_free,
        "selector_structure": selector_exact,
        "two_coin_40_edge_structure": rings_exact,
        "zero_reset_measure_calls": not reset_calls,
    }


def validate_v45_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    rebuild: bool = False,
) -> dict[str, Any]:
    """Validate sealed V4.5 evidence and return a stable evidence record."""

    paths = _paths(root)
    errors: list[str] = []
    try:
        spec = read_json_strict(paths["spec"])
    except Exception as exc:
        spec = {}
        errors.append(f"Specification parse/authentication failure: {exc}")
    try:
        certificate = read_json_strict(paths["certificate"])
    except Exception as exc:
        certificate = {}
        errors.append(f"Liveness certificate parse/authentication failure: {exc}")
    try:
        independent = run_independent_checker(artifact, root=paths["root"])
    except Exception as exc:
        independent = {"valid": False, "errors": [str(exc)], "check_count": 0}
        errors.append(f"Independent checker failed: {exc}")
    try:
        static = _static_contract(paths["source"], paths["checker"], Path(__file__))
    except Exception as exc:
        static = {}
        errors.append(f"Static source validation failed: {exc}")

    rows = list(artifact.get("seed_materializations") or [])
    aggregate = artifact.get("aggregate") or {}
    parent = artifact.get("parent") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    certificate_link = artifact.get("standalone_liveness_certificate") or {}
    layouts = [row.get("register_layout") or {} for row in rows]
    streams = [row.get("stream_manifest") or {} for row in rows]
    widths = [row.get("width_certificate") or {} for row in rows]

    replay_exact = True
    replay_artifact_sha256: str | None = None
    if rebuild:
        try:
            from .phase3_v45_proof_carrying_width_reduction import build_v45_artifact

            rebuilt = build_v45_artifact(root=paths["root"])
            replay_artifact_sha256 = str(rebuilt.get("artifact_sha256"))
            replay_exact = canonical_json_sha256(rebuilt) == canonical_json_sha256(artifact)
        except Exception as exc:
            replay_exact = False
            errors.append(f"Requested deterministic rebuild failed: {exc}")

    stream_hashes = [stream.get("stream_manifest_sha256") for stream in streams]
    register_hashes = [layout.get("register_map_sha256") for layout in layouts]
    semantic_hashes = [
        (row.get("semantic_trace_certificate") or {}).get("semantic_trace_certificate_sha256")
        for row in rows
    ]
    all_register_ids = []
    for layout in layouts:
        all_register_ids.append([
            int(qubit)
            for register in layout.get("registers") or []
            for qubit in register.get("qubit_ids") or []
        ])
    cnot_counts = [int((stream.get("elementary_counts") or {}).get("CX", -1)) for stream in streams]

    result_identities_finalized = all(
        _finalized_sha(value)
        for value in (
            EXPECTED_SOURCE_RAW_SHA256,
            EXPECTED_CHECKER_RAW_SHA256,
            EXPECTED_CERTIFICATE_RAW_SHA256,
            EXPECTED_CERTIFICATE_SHA256,
            EXPECTED_ARTIFACT_RAW_SHA256,
            EXPECTED_ARTIFACT_SHA256,
        )
    )
    checks: dict[str, bool] = {
        "result_identities_finalized": result_identities_finalized,
        "artifact_raw_identity": paths["artifact"].is_file() and _raw_sha256(paths["artifact"]) == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and _self_hashed(artifact, "artifact_sha256"),
        "artifact_version_and_classification": artifact.get("artifact_version") == "PHASE III · V4.5 SEALED PROOF-CARRYING WIDTH REDUCTION · V1" and artifact.get("research_classification") == "RESEARCH_ONLY",
        "spec_raw_identity": paths["spec"].is_file() and _raw_sha256(paths["spec"]) == EXPECTED_SPEC_RAW_SHA256,
        "spec_semantic_identity": spec.get("v45_spec_sha256") == EXPECTED_SPEC_SHA256 and canonical_json_sha256({key: value for key, value in spec.items() if key not in {"v45_spec_sha", "v45_spec_sha256"}}) == EXPECTED_SPEC_SHA256,
        "spec_preregistered_before_result": (spec.get("chronology") or {}).get("result_state_at_seal") == "NOT_EVALUATED" and (spec.get("acceptance_contract") or {}).get("result_state_at_protocol_seal") == "NOT_EVALUATED",
        "spec_success_contract_exact": (spec.get("acceptance_contract") or {}).get("success_status") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY",
        "parent_identities_exact": parent.get("freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256 and parent.get("freeze_sha256") == EXPECTED_V44_FREEZE_SHA256 and parent.get("artifact_raw_file_sha256") == EXPECTED_V44_ARTIFACT_RAW_SHA256 and parent.get("artifact_sha256") == EXPECTED_V44_ARTIFACT_SHA256,
        "parent_209_immutable_paths_exact": parent.get("immutable_file_count") == 209 and parent.get("immutable_files_exact") is True,
        "independent_checker_accepts": independent.get("valid") is True,
        "independent_checker_is_substantial": int(independent.get("check_count", 0)) >= 250,
        "independent_checker_self_hash": independent.get("verification_sha256") == canonical_json_sha256({key: value for key, value in independent.items() if key != "verification_sha256"}),
        "source_raw_identity": paths["source"].is_file() and _raw_sha256(paths["source"]) == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256,
        "checker_raw_identity": paths["checker"].is_file() and _raw_sha256(paths["checker"]) == EXPECTED_CHECKER_RAW_SHA256 and artifact.get("width_proof_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256,
        "certificate_raw_identity": paths["certificate"].is_file() and _raw_sha256(paths["certificate"]) == EXPECTED_CERTIFICATE_RAW_SHA256 and certificate_link.get("certificate_raw_file_sha256") == EXPECTED_CERTIFICATE_RAW_SHA256,
        "certificate_semantic_identity": certificate.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256 and certificate_link.get("certificate_sha256") == EXPECTED_CERTIFICATE_SHA256,
        "certificate_self_hash": _self_hashed(certificate, "certificate_sha256"),
        "seed_order_exact": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "all_eight_widths_exact": [layout.get("total_qubits") for layout in layouts] == list(EXPECTED_WIDTHS),
        "parent_widths_exact": [width.get("old_logical_qubits") for width in widths] == list(EXPECTED_V43_WIDTHS),
        "maximum_145_margin_11": aggregate.get("maximum_logical_qubits") == DESIGN_CEILING_QUBITS and aggregate.get("minimum_capacity_margin_qubits") == TARGET_QUBITS - DESIGN_CEILING_QUBITS,
        "allocation_formula_all_seeds": len(layouts) == 8 and all(layout.get("total_qubits") == 67 + 2 * int(layout.get("arithmetic_width", -1000)) for layout in layouts),
        "registers_contiguous_all_seeds": len(layouts) == 8 and all(ids == list(range(int(layout.get("total_qubits", -1)))) for ids, layout in zip(all_register_ids, layouts)),
        "registers_nonoverlapping_all_seeds": len(layouts) == 8 and all(len(ids) == len(set(ids)) for ids in all_register_ids),
        "register_map_self_hashes": len(layouts) == 8 and all(_self_hashed(layout, "register_map_sha256") for layout in layouts),
        "width_certificate_self_hashes": len(widths) == 8 and all(_self_hashed(width, "width_certificate_sha256") for width in widths),
        "seed_materialization_self_hashes": len(rows) == 8 and all(_self_hashed(row, "seed_materialization_sha256") for row in rows),
        "stream_manifest_self_hashes": len(streams) == 8 and all(_self_hashed(stream, "stream_manifest_sha256") for stream in streams),
        "stream_counts_positive_and_elementary": len(streams) == 8 and all(int(stream.get("instruction_count", 0)) > 0 and set(stream.get("basis") or []) <= {"X", "H", "T", "TDG", "RY", "RZ", "CX"} for stream in streams),
        "cnot_budget_all_seeds": len(cnot_counts) == 8 and all(0 <= count <= CNOT_BUDGET for count in cnot_counts),
        "coin_two_rings_40_edges": len(streams) == 8 and all((stream.get("macro_counts") or {}).get("BINARY_TWO_LEVEL_RX") == 80 for stream in streams),
        "coin_binary_domain_contract": len(rows) == 8 and all((row.get("semantic_trace_certificate") or {}).get("binary_domain") == {"address_width": 6, "invalid_encodings": list(range(40, 64)), "valid": [0, 39]} for row in rows),
        "relative_phase_forward_adjoint_counts": len(streams) == 8 and all(int((stream.get("macro_counts") or {}).get("RELATIVE_PHASE_C7X", 0)) == int((stream.get("macro_counts") or {}).get("RELATIVE_PHASE_C7X_DAGGER", -1)) > 0 for stream in streams),
        "liveness_self_hashes": len(rows) == 8 and all(_self_hashed(row.get("liveness") or {}, "liveness_certificate_sha256") for row in rows),
        "liveness_ordered_phase_ledger": len(rows) == 8 and all([event.get("phase") for event in (row.get("liveness") or {}).get("events") or []] == ["BINARY_COIN_RINGS", "SELECT_ADDRESS_READ_AND_DATA_UPDATE", "STREAMED_TARGET_ROW_ARITHMETIC", "CERTIFIED_DATA_BRIDGES"] for row in rows),
        "liveness_no_reset_and_clean_exit": len(rows) == 8 and all((row.get("liveness") or {}).get("reset_instruction_count") == 0 and (row.get("liveness") or {}).get("clean_exit_registers") == ["SUM_WORK", "CONSTANT", "CARRY", "ADDRESSED", "ROW_FLAGS", "CONTROL_FLAGS"] for row in rows),
        "relative_phase_b_dagger_u_b_marker": len(rows) == 8 and all("B_DAGGER_U_B" in str(((row.get("liveness") or {}).get("relative_phase_compute_use_uncompute") or {}).get("exactness_argument")) and ((row.get("liveness") or {}).get("relative_phase_compute_use_uncompute") or {}).get("uncompute") == "EXPLICIT_EXACT_ADJOINT_IN_REVERSE_ORDER" for row in rows),
        "relative_phase_exact_adjoint_static_ast": static.get("exact_adjoint_structure") is True,
        "bennett_and_selector_static_ast": static.get("bennett_reverse_structure") is True and static.get("selector_structure") is True,
        "coin_ring_static_ast": static.get("two_coin_40_edge_structure") is True,
        "semantic_trace_self_hashes": len(rows) == 8 and all(_self_hashed(row.get("semantic_trace_certificate") or {}, "semantic_trace_certificate_sha256") for row in rows),
        "selector_trace_parity_1600_pairs": len(rows) == 8 and all(int((row.get("semantic_trace_certificate") or {}).get("sample_count", 0)) >= 1 and all(sample.get("address_pair_count") == 1600 and sample.get("all_valid_binary_address_pairs_exhausted") is True for sample in (row.get("semantic_trace_certificate") or {}).get("samples") or []) for row in rows),
        "off_promise_negative_witness_retained": (artifact.get("mandatory_off_promise_control") or {}).get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" and (artifact.get("mandatory_off_promise_control") or {}).get("witness_detected") is True,
        "aggregate_roots_exact": aggregate.get("ordered_stream_manifest_root_sha256") == canonical_json_sha256(stream_hashes) and aggregate.get("register_map_root_sha256") == canonical_json_sha256(register_hashes) and aggregate.get("semantic_trace_root_sha256") == canonical_json_sha256(semantic_hashes),
        "provider_free_static_boundary": static.get("provider_free") is True and static.get("checker_imports_generator") is False and static.get("zero_reset_measure_calls") is True,
        "zero_provider_network_credentials_jobs": boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == boundary.get("provider_calls") == boundary.get("network_calls") == boundary.get("qpu_jobs_submitted") == 0,
        "routing_and_transpilation_not_run": boundary.get("full_workload_routing") == "NOT_RUN_IN_V4_5" and boundary.get("full_workload_transpilation") == "NOT_RUN_IN_V4_5",
        "no_hardware_performance_or_advantage_claim": boundary.get("hardware_executable") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED" and boundary.get("snapshot_is_current_hardware_evidence") is False,
        "decision_and_next_gate_exact": decisions.get("overall") == "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY" and decisions.get("production_admission") == "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED" and decisions.get("materialized_cnot_budget") == "PASSED_AT_OR_BELOW_2500000_ALL_EIGHT_SEEDS" and decisions.get("next_falsifiable_gate") == "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS",
        "deterministic_rebuild_contract": replay_exact,
    }
    if len(checks) != EXPECTED_CHECK_COUNT:
        raise AssertionError(f"V4.5 scientific check count drifted: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, valid in checks.items() if valid is not True]
    if independent.get("errors"):
        errors.extend(str(item) for item in independent.get("errors") or [])
    evidence_core = {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {"checks_passed": sum(value is True for value in checks.values()), "checks_total": len(checks)},
        "independent_checker_verification_sha256": independent.get("verification_sha256"),
        "validation_version": "QUANTUM LAB V4.5 INDEPENDENT VALIDATION · V1",
    }
    return {
        **evidence_core,
        "deterministic_rebuild_performed": rebuild,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "passed": not failed and not errors,
        "replay_artifact_sha256": replay_artifact_sha256,
        "root": str(paths["root"]),
        "static_boundary": static,
        "validation_evidence_sha256": canonical_json_sha256(evidence_core),
    }


def run_v45_validation(*, root: str | Path | None = None, rebuild: bool = False) -> dict[str, Any]:
    paths = _paths(root)
    artifact = read_json_strict(paths["artifact"])
    return validate_v45_artifact(artifact, root=paths["root"], rebuild=rebuild)


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CERTIFICATE_RAW_SHA256",
    "EXPECTED_CERTIFICATE_SHA256",
    "EXPECTED_CHECKER_RAW_SHA256",
    "EXPECTED_CHECK_COUNT",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_VALIDATION_EVIDENCE_SHA256",
    "run_v45_validation",
    "validate_v45_artifact",
]
