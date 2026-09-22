"""Fail-closed institutional evidence surface for Quantum Lab V4.5.

This module only reads and authenticates sealed local evidence.  It never
rebuilds a circuit, imports a provider SDK, reads credentials, accesses the
network, routes a workload or submits a job.  Until the post-seal identities
below are patched to exact SHA-256 values, every scientific result is masked.
"""

from __future__ import annotations

import copy
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v45_proof_carrying_width_reduction import (
    BUDGET_CNOT,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_V44_ARTIFACT_RAW_SHA256,
    EXPECTED_V44_ARTIFACT_SHA256,
    EXPECTED_V44_FREEZE_RAW_SHA256,
    EXPECTED_V44_FREEZE_SHA256,
    LIVENESS_CERTIFICATE_FILENAME,
    SEEDS,
    SPEC_FILENAME,
    TARGET_LOGICAL_QUBITS,
    authenticate_v44_parent,
    canonical_json_sha256,
    load_v45_spec,
    raw_file_sha256,
    read_json_strict,
)


SectionHeader = Callable[[str, str, str], None]

# POST-SEAL PATCH POINTS.  The UI intentionally fails closed while any value
# remains a named placeholder.  Patching these constants does not mutate the
# sealed generator, checker, protocol, certificate or result artifact.
EXPECTED_ARTIFACT_RAW_SHA256 = "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257"
EXPECTED_ARTIFACT_SHA256 = "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"
EXPECTED_SOURCE_RAW_SHA256 = "5167e23d7096d8f2b6671decc06c4ac4e3822be4bd7990a057f3daf2370db74c"
EXPECTED_CHECKER_RAW_SHA256 = "c9723894e85d7ce651502622b9d557beee1efb8a92663c92341e42c071d74558"
EXPECTED_LIVENESS_RAW_SHA256 = "5ae77c160255d881a2f596459e6f1ca61bf7fd0645bbfeb118f753e43930b7da"
EXPECTED_LIVENESS_SHA256 = "93f119c6493fac2eb0e7d281db1842482201cd7a680cf8ca93b9fdcc69a53102"

EXPECTED_UI_AUTH_CHECK_COUNT = 28
EXPECTED_OLD_WIDTHS = (330, 331, 327, 328, 329, 331, 339, 334)
EXPECTED_NEW_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_MARGINS = (21, 19, 23, 21, 19, 19, 11, 17)
EXPECTED_OVERALL = "V45_PROOF_CARRYING_WIDTH_REDUCTION_PASSED_EXACT_PROMISE_PARITY"
EXPECTED_PRODUCTION = "WIDTH_PROOF_ADMITTED_TO_NEXT_OFFLINE_GATE_ONLY_HARDWARE_EXECUTION_REJECTED"
EXPECTED_NEXT_GATE = "PINNED_FAKEMARRAKESH_FULL_RECONSTRUCTION_TRANSLATION_AND_ROUTING_OF_WIDTH_ADMITTED_V4_5_STREAMS"
NOT_RUN = "NOT_RUN_IN_V4_5"
REGISTER_LIVENESS_CERTIFICATE_FILENAME = (
    "PHASE_III_V4_5_REGISTER_LIVENESS_CERTIFICATE_V1.json"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _decode_json_strict(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key rejected: {key}")
            result[key] = value
        return result

    def reject_nonfinite(token: str) -> None:
        raise ValueError(f"Non-finite JSON number rejected: {token}")

    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return payload


def _is_sha256(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _post_seal_identities_finalized() -> bool:
    return all(
        _is_sha256(value)
        for value in (
            EXPECTED_ARTIFACT_RAW_SHA256,
            EXPECTED_ARTIFACT_SHA256,
            EXPECTED_SOURCE_RAW_SHA256,
            EXPECTED_CHECKER_RAW_SHA256,
            EXPECTED_LIVENESS_RAW_SHA256,
            EXPECTED_LIVENESS_SHA256,
        )
    )


def _short_sha(value: Any) -> str:
    text = str(value or "")
    return f"{text[:12]}…{text[-8:]}" if _is_sha256(text) else "MASKED"


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_v45_ui_artifact_path() -> Path:
    return (
        _root()
        / "outputs/quantum_phase3/v45_width_reduction"
        / "SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"
    )


def default_v45_ui_spec_path() -> Path:
    return _root() / "quantum_research_lab" / SPEC_FILENAME


def default_v45_ui_liveness_path() -> Path:
    """Prefer the institutional filename while accepting the generator name."""

    institutional = _root() / "quantum_research_lab" / REGISTER_LIVENESS_CERTIFICATE_FILENAME
    generated = _root() / "quantum_research_lab" / LIVENESS_CERTIFICATE_FILENAME
    return institutional if institutional.exists() else generated


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha256(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _validate_v45_artifact(
    artifact_raw: bytes,
    liveness_raw: bytes,
    *,
    root: Path,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        artifact = _decode_json_strict(artifact_raw)
        liveness = _decode_json_strict(liveness_raw)
    except Exception as exc:
        return {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_json"],
            "valid": False,
        }

    if not _post_seal_identities_finalized():
        errors.append("V4.5 UI post-seal SHA-256 constants have not been finalized.")
    try:
        spec = load_v45_spec(root=root)
        parent = authenticate_v44_parent(root=root)
    except Exception as exc:
        spec, parent = {}, {"valid": False, "errors": [str(exc)]}
        errors.append(str(exc))

    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    parent_link = _mapping(artifact.get("parent"))
    live_link = _mapping(artifact.get("standalone_liveness_certificate"))
    seed_rows = _rows(artifact.get("seed_materializations"))
    live_seed_rows = _rows(liveness.get("seed_rows"))
    width_rows = [_mapping(row.get("width_certificate")) for row in seed_rows]
    layouts = [_mapping(row.get("register_layout")) for row in seed_rows]
    streams = [_mapping(row.get("stream_manifest")) for row in seed_rows]
    semantics = [_mapping(row.get("semantic_trace_certificate")) for row in seed_rows]
    cnots = [int((_mapping(row.get("elementary_counts"))).get("CX", -1)) for row in streams]
    source = root / "quantum_research_lab/phase3_v45_proof_carrying_width_reduction.py"
    checker = root / "quantum_research_lab/phase3_v45_width_proof_checker.py"

    checks: dict[str, bool] = {
        "artifact_raw_identity": hashlib.sha256(artifact_raw).hexdigest() == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": bool(artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and _self_hash(artifact, "artifact_sha256")),
        "source_raw_identity": source.is_file() and raw_file_sha256(source) == EXPECTED_SOURCE_RAW_SHA256,
        "checker_raw_identity": checker.is_file() and raw_file_sha256(checker) == EXPECTED_CHECKER_RAW_SHA256,
        "spec_raw_semantic_identity": bool(spec.get("v45_spec_sha256") == EXPECTED_SPEC_SHA256 and raw_file_sha256(root / "quantum_research_lab" / SPEC_FILENAME) == EXPECTED_SPEC_RAW_SHA256),
        "liveness_raw_identity": hashlib.sha256(liveness_raw).hexdigest() == EXPECTED_LIVENESS_RAW_SHA256,
        "liveness_semantic_identity": bool(liveness.get("certificate_sha256") == EXPECTED_LIVENESS_SHA256 and _self_hash(liveness, "certificate_sha256")),
        "v44_parent_and_209_immutable_paths": bool(parent.get("valid") is True and parent.get("immutable_file_count") == 209 and parent.get("immutable_files_exact") is True),
        "artifact_parent_crosslinks": bool(parent_link.get("artifact_raw_file_sha256") == EXPECTED_V44_ARTIFACT_RAW_SHA256 and parent_link.get("artifact_sha256") == EXPECTED_V44_ARTIFACT_SHA256 and parent_link.get("freeze_raw_file_sha256") == EXPECTED_V44_FREEZE_RAW_SHA256 and parent_link.get("freeze_sha256") == EXPECTED_V44_FREEZE_SHA256),
        "artifact_source_checker_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("width_proof_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256),
        "artifact_spec_crosslinks": bool(artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256),
        "artifact_liveness_crosslinks": bool(live_link.get("certificate_raw_file_sha256") == EXPECTED_LIVENESS_RAW_SHA256 and live_link.get("certificate_sha256") == EXPECTED_LIVENESS_SHA256),
        "aggregate_self_identity": _self_hash(aggregate, "aggregate_sha256"),
        "eight_seed_order": [row.get("seed") for row in seed_rows] == list(SEEDS),
        "eight_liveness_seed_order": [row.get("seed") for row in live_seed_rows] == list(SEEDS),
        "old_widths_exact": [row.get("old_logical_qubits") for row in width_rows] == list(EXPECTED_OLD_WIDTHS),
        "new_widths_exact": [row.get("new_logical_qubits") for row in width_rows] == list(EXPECTED_NEW_WIDTHS),
        "capacity_margins_exact": [row.get("capacity_margin_qubits") for row in width_rows] == list(EXPECTED_MARGINS),
        "all_widths_fit_156": bool(aggregate.get("all_eight_widths_fit_156") is True and aggregate.get("maximum_logical_qubits") == 145 and aggregate.get("minimum_capacity_margin_qubits") == 11),
        "register_formula_and_maps": bool(layouts and all(layout.get("allocation_formula") == "67+2W" and layout.get("total_qubits") == expected and _self_hash(layout, "register_map_sha256") for layout, expected in zip(layouts, EXPECTED_NEW_WIDTHS))),
        "ordered_liveness_and_clean_exit": bool(live_seed_rows and all((_mapping(row.get("liveness"))).get("liveness_decision") == "PASSED_STATIC_PHASE_LOCAL_BORROW_AND_CLEAN_EXIT_CONTRACT" and (_mapping(row.get("liveness"))).get("reset_instruction_count") == 0 for row in live_seed_rows)),
        "semantic_trace_certificates": bool(semantics and all(int(row.get("sample_count", 0)) >= 1 and row.get("v43_promise_relation") == "EXACT_SELECT_TRACE_PARITY_FOR_ALL_1600_ADDRESS_PAIRS_OF_EACH_AUTHENTICATED_COMPONENT_REPRESENTATIVE" and _self_hash(row, "semantic_trace_certificate_sha256") for row in semantics)),
        "off_promise_scope_retained": decisions.get("promise_scope") == "EXACT_ONLY_FOR_FEASIBLE_N40_DATA_AND_TWO_VALID_BINARY_ADDRESSES_0_TO_39",
        "cnot_budget_all_eight": bool(len(cnots) == 8 and all(0 <= count <= BUDGET_CNOT for count in cnots) and aggregate.get("all_eight_materialized_cnot_counts_at_or_below_2500000") is True and aggregate.get("cnot_budget_pass_count") == 8),
        "decision_exact": decisions.get("overall") == EXPECTED_OVERALL,
        "production_and_next_gate_exact": bool(decisions.get("production_admission") == EXPECTED_PRODUCTION and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE),
        "provider_network_job_boundary": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0),
        "research_hardware_routing_boundary": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False and boundary.get("full_workload_transpilation") == NOT_RUN and boundary.get("full_workload_routing") == NOT_RUN and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
    }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        raise AssertionError(f"V4.5 UI authentication check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(parent.get("errors") or [])
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": not failed and not errors,
    }


def load_v45_ui_artifact(
    path: str | Path | None = None,
    *,
    liveness_path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v45_ui_artifact_path()
    liveness_target = Path(liveness_path) if liveness_path is not None else default_v45_ui_liveness_path()
    try:
        artifact_raw = target.read_bytes()
        liveness_raw = liveness_target.read_bytes()
        payload = _decode_json_strict(artifact_raw)
        report = _validate_v45_artifact(artifact_raw, liveness_raw, root=_root())
        return payload if isinstance(payload, dict) else None, report
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["artifact_or_liveness_available"],
            "valid": False,
        }


def load_v45_ui_supporting_evidence() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    try:
        spec = read_json_strict(default_v45_ui_spec_path())
    except Exception:
        spec = None
    try:
        liveness = read_json_strict(default_v45_ui_liveness_path())
    except Exception:
        liveness = None
    return spec, liveness


def normalize_v45_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    liveness_integrity: bool | None,
    parent_integrity: bool | None,
    source_integrity: bool | None = True,
    checker_integrity: bool | None = True,
) -> dict[str, Any]:
    authenticated = bool(
        isinstance(artifact, Mapping)
        and artifact_integrity is True
        and spec_integrity is True
        and liveness_integrity is True
        and parent_integrity is True
        and source_integrity is True
        and checker_integrity is True
    )
    if not authenticated:
        return {
            "authenticated": False,
            "decision": "MASKED_FAIL_CLOSED",
            "full_workload_routing": NOT_RUN,
            "hardware_executable": False,
            "network_calls": 0,
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "reason": "V4.5 evidence is absent, incomplete, unsealed or unauthenticated.",
            "research_classification": "RESEARCH_ONLY",
        }
    payload = dict(artifact or {})
    aggregate = _mapping(payload.get("aggregate"))
    boundary = _mapping(payload.get("claim_boundary"))
    decisions = _mapping(payload.get("decisions"))
    return {
        "artifact_sha256": payload.get("artifact_sha256"),
        "authenticated": True,
        "cnot_budget_pass_count": aggregate.get("cnot_budget_pass_count"),
        "decision": decisions.get("overall"),
        "full_workload_routing": boundary.get("full_workload_routing"),
        "full_workload_transpilation": boundary.get("full_workload_transpilation"),
        "hardware_executable": boundary.get("hardware_executable"),
        "maximum_logical_qubits": aggregate.get("maximum_logical_qubits"),
        "maximum_materialized_cnot": aggregate.get("maximum_materialized_cnot"),
        "minimum_capacity_margin_qubits": aggregate.get("minimum_capacity_margin_qubits"),
        "network_calls": boundary.get("network_calls"),
        "next_gate": decisions.get("next_falsifiable_gate"),
        "production_admission": decisions.get("production_admission"),
        "promise_scope": decisions.get("promise_scope"),
        "provider_calls": boundary.get("provider_calls"),
        "qpu_jobs_submitted": boundary.get("qpu_jobs_submitted"),
        "research_classification": payload.get("research_classification"),
        "seed_count": aggregate.get("seed_count"),
    }


def _width_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    columns = ["Seed", "V4.3 width", "V4.5 width", "Reduction", "156Q margin", "Capacity"]
    if not state.get("authenticated"):
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([
        {
            "Seed": row.get("seed"),
            "V4.3 width": width.get("old_logical_qubits"),
            "V4.5 width": width.get("new_logical_qubits"),
            "Reduction": width.get("reduction_qubits"),
            "156Q margin": width.get("capacity_margin_qubits"),
            "Capacity": "PASS" if width.get("capacity_fit") else "FAIL",
        }
        for row in _rows(artifact.get("seed_materializations"))
        for width in [_mapping(row.get("width_certificate"))]
    ], columns=columns)


def _cnot_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    columns = ["Seed", "Materialized CX", "Budget", "Margin", "Decision"]
    if not state.get("authenticated"):
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([
        {
            "Seed": row.get("seed"),
            "Materialized CX": (_mapping(_mapping(row.get("stream_manifest")).get("elementary_counts"))).get("CX"),
            "Budget": row.get("budget_cnot"),
            "Margin": row.get("budget_margin_cnot"),
            "Decision": row.get("resource_decision"),
        }
        for row in _rows(artifact.get("seed_materializations"))
    ], columns=columns)


def _register_ledger(state: Mapping[str, Any], liveness: Mapping[str, Any]) -> pd.DataFrame:
    columns = ["Seed", "Register", "Start", "Qubits", "Role"]
    if not state.get("authenticated"):
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(liveness.get("seed_rows")):
        for register in _rows((_mapping(seed_row.get("register_layout"))).get("registers")):
            rows.append({
                "Seed": seed_row.get("seed"),
                "Register": register.get("name"),
                "Start": register.get("start"),
                "Qubits": register.get("width"),
                "Role": register.get("role"),
            })
    return pd.DataFrame(rows, columns=columns)


def _liveness_ledger(state: Mapping[str, Any], liveness: Mapping[str, Any]) -> pd.DataFrame:
    columns = ["Seed", "Phase", "Borrowed clean qubits", "Clean before", "Clean after", "Reason"]
    if not state.get("authenticated"):
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(liveness.get("seed_rows")):
        live = _mapping(seed_row.get("liveness"))
        for event in _rows(live.get("events")):
            rows.append({
                "Seed": seed_row.get("seed"),
                "Phase": event.get("phase"),
                "Borrowed clean qubits": len(event.get("borrowed_clean_qubits") or []),
                "Clean before": " · ".join(str(value) for value in event.get("clean_before") or []),
                "Clean after": " · ".join(str(value) for value in event.get("clean_after") or []),
                "Reason": event.get("borrow_reason"),
            })
    return pd.DataFrame(rows, columns=columns)


def _semantic_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    columns = ["Seed", "Representatives", "Address pairs / representative", "Accepted moves", "Trace root", "Relation"]
    if not state.get("authenticated"):
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_materializations")):
        semantic = _mapping(seed_row.get("semantic_trace_certificate"))
        samples = _rows(semantic.get("samples"))
        rows.append({
            "Seed": seed_row.get("seed"),
            "Representatives": semantic.get("sample_count"),
            "Address pairs / representative": 1600,
            "Accepted moves": sum(int(sample.get("accepted_move_count", 0)) for sample in samples),
            "Trace root": semantic.get("trace_root_sha256"),
            "Relation": semantic.get("v43_promise_relation"),
        })
    return pd.DataFrame(rows, columns=columns)


def _boundary_ledger(state: Mapping[str, Any], artifact: Mapping[str, Any]) -> pd.DataFrame:
    boundary = _mapping(artifact.get("claim_boundary")) if state.get("authenticated") else {}
    fields = (
        ("Research classification", artifact.get("research_classification")),
        ("Provider SDK imported", boundary.get("provider_sdk_imported")),
        ("Credentials read", boundary.get("credential_reads")),
        ("Provider calls", boundary.get("provider_calls")),
        ("Network calls", boundary.get("network_calls")),
        ("QPU jobs", boundary.get("qpu_jobs_submitted")),
        ("Hardware executable", boundary.get("hardware_executable")),
        ("Full reconstruction", boundary.get("full_workload_circuit_reconstruction")),
        ("Full transpilation", boundary.get("full_workload_transpilation")),
        ("Full routing", boundary.get("full_workload_routing")),
        ("Optimization performance", boundary.get("optimization_performance")),
        ("Quantum advantage", boundary.get("quantum_advantage")),
    ) if boundary else (("Evidence", "MASKED"),)
    return pd.DataFrame([{"Boundary": label, "Value": str(value)} for label, value in fields])


def _hash_ledger(
    state: Mapping[str, Any], artifact: Mapping[str, Any], liveness: Mapping[str, Any]
) -> pd.DataFrame:
    if not state.get("authenticated"):
        return pd.DataFrame([{"Evidence": "MASKED", "SHA-256": "MASKED"}])
    aggregate = _mapping(artifact.get("aggregate"))
    return pd.DataFrame([
        {"Evidence": "V4.5 artifact", "SHA-256": artifact.get("artifact_sha256")},
        {"Evidence": "V4.5 specification", "SHA-256": artifact.get("spec_sha256")},
        {"Evidence": "Register/liveness certificate", "SHA-256": liveness.get("certificate_sha256")},
        {"Evidence": "Aggregate", "SHA-256": aggregate.get("aggregate_sha256")},
        {"Evidence": "Register-map root", "SHA-256": aggregate.get("register_map_root_sha256")},
        {"Evidence": "Semantic-trace root", "SHA-256": aggregate.get("semantic_trace_root_sha256")},
        {"Evidence": "Ordered stream root", "SHA-256": aggregate.get("ordered_stream_manifest_root_sha256")},
        {"Evidence": "V4.4 artifact parent", "SHA-256": EXPECTED_V44_ARTIFACT_SHA256},
        {"Evidence": "V4.4 freeze parent", "SHA-256": EXPECTED_V44_FREEZE_SHA256},
    ])


def apply_v45_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if encoding is None:
        return None
    result = copy.deepcopy(dict(encoding))
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        return result
    result.update({
        "backend_capacity_ok": True,
        "backend_qubits": TARGET_LOGICAL_QUBITS,
        "backend_transpilation": NOT_RUN,
        "binary_coin_address_qubits": 6,
        "encoding_status": "V4.5 WIDTH + EXACT PROMISE PARITY PASS · ROUTING NOT RUN",
        "full_workload_routing": NOT_RUN,
        "hardware_executable": False,
        "logical_qubits_max": state.get("maximum_logical_qubits"),
        "network_calls": 0,
        "provider_calls": 0,
        "qpu_jobs_submitted": 0,
        "quantum_advantage": "NOT_CLAIMED",
        "v45_cnot_budget_pass_count": state.get("cnot_budget_pass_count"),
        "v45_decision": state.get("decision"),
        "v45_minimum_capacity_margin_qubits": state.get("minimum_capacity_margin_qubits"),
        "v45_next_gate": state.get("next_gate"),
        "v45_register_formula": "67+2W",
        "v45_routing": NOT_RUN,
    })
    return result


def render_v45_width_reduction_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    liveness: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    liveness_integrity: bool | None,
    parent_integrity: bool | None,
    source_integrity: bool | None = True,
    checker_integrity: bool | None = True,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    state = normalize_v45_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        liveness_integrity=liveness_integrity,
        parent_integrity=parent_integrity,
        source_integrity=source_integrity,
        checker_integrity=checker_integrity,
    )
    payload = dict(artifact or {})
    spec_payload = dict(spec or {})
    liveness_payload = dict(liveness or {})
    authenticated = state.get("authenticated") is True

    section_header(
        "V4.5 · Proof-Carrying Width Reduction",
        "BINARY COINS · BENNETT RECOMPUTATION · 145Q MAXIMUM",
        "Eight frozen instances now fit the 156-qubit logical-capacity gate with exact promise-subspace SELECT traces and explicit register-liveness certificates. Full backend reconstruction, transpilation and routing remain the next gate and were not run in V4.5.",
    )
    hooks = (
        f'<span data-qv45-surface="proof-carrying-width-reduction" data-qv45-release="4.5" '
        f'data-qv45-auth="{("pass" if authenticated else "fail")}" data-qv45-parent="{("pass" if parent_integrity is True else "fail")}" '
        f'data-qv45-max-width="{(state.get("maximum_logical_qubits") if authenticated else "MASKED")}" '
        f'data-qv45-min-margin="{(state.get("minimum_capacity_margin_qubits") if authenticated else "MASKED")}" '
        f'data-qv45-cnot-budget="{BUDGET_CNOT}" data-qv45-provider-sdk="false" data-qv45-credential-reads="0" '
        f'data-qv45-provider-calls="0" data-qv45-network-calls="0" data-qv45-jobs="0" data-qv45-qpu-submit="disabled" '
        f'data-qv45-hardware="false" data-qv45-transpilation="NOT_RUN_IN_V4_5" data-qv45-routing="NOT_RUN_IN_V4_5" '
        f'data-qv45-performance="NOT_TESTED" data-qv45-advantage="NOT_CLAIMED" data-qv45-research="RESEARCH_ONLY" style="display:none"></span>'
    )
    st.markdown(hooks, unsafe_allow_html=True)

    if authenticated:
        st.success(
            "Authenticated V4.5 width admission: all eight frozen seeds fit within 156 logical qubits (133–145), exact promise-subspace traces pass, and every materialized stream remains within the 2,500,000-CX budget."
        )
    else:
        st.error("V4.5 evidence authentication failed or post-seal identities are unfinished. All scientific outcomes are masked fail-closed.")

    values = [
        ("FROZEN SEEDS", "8 / 8 PASS", "WIDTH + TRACE"),
        ("V4.3 WIDTH", "327–339", "AUTHENTICATED PARENT"),
        ("V4.5 WIDTH", "133–145", "67 + 2W"),
        ("TARGET", "156 QUBITS", "LOGICAL CAPACITY"),
        ("MINIMUM MARGIN", "+11", "145 → 156"),
        ("COIN REGISTERS", "6 + 6", "VALID ADDRESSES 0–39"),
        ("ROW WORKSPACE", "1 RECYCLED", "BENNETT UNCOMPUTE"),
        ("CNOT BUDGET", "8 / 8 PASS", f"≤ {BUDGET_CNOT:,}"),
        ("TRACE DOMAIN", "1,600 / REP", "40 × 40 PAIRS"),
        ("FULL ROUTING", "NOT RUN", "NEXT FALSIFIABLE GATE"),
        ("PROVIDER / NETWORK", "0 / 0", "NO CREDENTIAL READ"),
        ("QPU / HARDWARE", "0 / FALSE", "RESEARCH_ONLY"),
    ] if authenticated else [(label, "MASKED", "AUTHENTICATION REQUIRED") for label in (
        "FROZEN SEEDS", "V4.3 WIDTH", "V4.5 WIDTH", "TARGET", "MINIMUM MARGIN", "COIN REGISTERS", "ROW WORKSPACE", "CNOT BUDGET", "TRACE DOMAIN", "FULL ROUTING", "PROVIDER / NETWORK", "QPU / HARDWARE"
    )]
    cards = "".join(
        f'<div class="qp3-card qv45-metric"><div class="qp3-ck">{escape(label)}</div><div class="qp3-cv">{escape(value)}</div><div class="qp3-cn">{escape(note)}</div></div>'
        for label, value, note in values
    )
    st.markdown(f'<div class="qp3-grid">{cards}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="qp3-panel"><div class="qp3-pk">SEALED V4.5 DECISION</div><div class="qp3-pt {("qp3-ok" if authenticated else "qp3-block")}">{escape(str(state.get("decision", "MASKED_FAIL_CLOSED")))}</div><div class="qp3-note">Production · {escape(str(state.get("production_admission", "MASKED")))}<br>Promise · {escape(str(state.get("promise_scope", "MASKED")))}<br>Next gate · {escape(str(state.get("next_gate", "MASKED")))}</div></div>',
        unsafe_allow_html=True,
    )

    width_frame = _width_ledger(state, payload)
    cnot_frame = _cnot_ledger(state, payload)
    st.dataframe(width_frame, width="stretch", hide_index=True)
    if authenticated and not width_frame.empty:
        st.bar_chart(width_frame.set_index("Seed")[["V4.3 width", "V4.5 width"]])
    st.dataframe(cnot_frame, width="stretch", hide_index=True)
    st.caption("Logical width is a wire count, not a hardware claim. CX values are provider-neutral materialized-stream counts; routed CZ and depth are not yet measured.")

    with st.expander("Register allocation and phase-local liveness", expanded=True):
        register_frame = _register_ledger(state, liveness_payload)
        liveness_frame = _liveness_ledger(state, liveness_payload)
        st.dataframe(register_frame, width="stretch", hide_index=True)
        st.dataframe(liveness_frame, width="stretch", hide_index=True)
        st.caption("Workspace reuse is admitted only after explicit inverse computation restores clean zero. RESET, measurement, discard and dependency destruction are forbidden.")
        st.download_button("Download V4.5 register/liveness certificate", data=json.dumps(liveness_payload, indent=2, sort_keys=True, ensure_ascii=False), file_name=REGISTER_LIVENESS_CERTIFICATE_FILENAME, mime="application/json", disabled=not authenticated, key=f"{key_prefix}_v45_download_liveness")
        st.download_button("Download V4.5 register ledger CSV", data=register_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_REGISTER_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_registers")
        st.download_button("Download V4.5 liveness events CSV", data=liveness_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_LIVENESS_EVENTS.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_events")

    with st.expander("Exact promise-subspace semantic traces", expanded=True):
        semantic_frame = _semantic_ledger(state, payload)
        st.dataframe(semantic_frame, width="stretch", hide_index=True)
        st.caption("Each authenticated feasible representative exhausts all 1,600 valid remove/add address pairs. Invalid six-bit encodings 40–63 and off-promise states are not promoted into the acceptance claim.")
        st.download_button("Download V4.5 semantic trace ledger CSV", data=semantic_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_SEMANTIC_TRACE_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_semantics")

    with st.expander("Integrity, boundary and sealed evidence", expanded=False):
        boundary_frame = _boundary_ledger(state, payload)
        hash_frame = _hash_ledger(state, payload, liveness_payload)
        st.dataframe(boundary_frame, width="stretch", hide_index=True)
        st.dataframe(hash_frame, width="stretch", hide_index=True)
        st.code(str(state.get("next_gate", "MASKED")))
        st.download_button("Download sealed V4.5 artifact", data=json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False), file_name="SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json", mime="application/json", disabled=not authenticated, key=f"{key_prefix}_v45_download_artifact")
        st.download_button("Download frozen V4.5 protocol", data=json.dumps(spec_payload, indent=2, sort_keys=True, ensure_ascii=False), file_name=SPEC_FILENAME, mime="application/json", disabled=not authenticated, key=f"{key_prefix}_v45_download_spec")
        st.download_button("Download V4.5 width ledger CSV", data=width_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_WIDTH_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_widths")
        st.download_button("Download V4.5 CNOT budget ledger CSV", data=cnot_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_CNOT_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_cnot")
        st.download_button("Download V4.5 boundary ledger CSV", data=boundary_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_BOUNDARY_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_boundary")
        st.download_button("Download V4.5 hash ledger CSV", data=hash_frame.to_csv(index=False), file_name="QUANTUM_LAB_V4_5_HASH_LEDGER.csv", mime="text/csv", disabled=not authenticated, key=f"{key_prefix}_v45_download_hashes")

    with st.expander("Governance controls · all disabled by the sealed boundary", expanded=False):
        labels = (
            "Rebuild or mutate the sealed V4.5 artifact",
            "Change the frozen V4.4 parent lineage",
            "Override the 156-qubit logical-capacity gate",
            "Expand the exact claim beyond valid addresses 0–39",
            "Discard garbage instead of reversible uncompute",
            "Reset or measure borrowed workspace",
            "Treat logical width as routed hardware fit",
            "Run full-workload transpilation inside V4.5",
            "Run full-workload routing inside V4.5",
            "Read credentials or contact a provider",
            "Submit a simulator or QPU job",
            "Claim hardware execution, performance or quantum advantage",
        )
        for index, label in enumerate(labels):
            st.button(label, disabled=True, key=f"{key_prefix}_v45_governance_{index}")

    if authenticated:
        st.warning(
            "WIDTH + PROMISE PARITY · PASSED. HARDWARE EXECUTION · FALSE. V4.5 has not reconstructed, translated or routed these full streams on FakeMarrakesh; no current calibration, fidelity, runtime, utility or advantage conclusion is authorized."
        )
        st.info(f"Next falsifiable gate: {state.get('next_gate')}.")
    return state


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CHECKER_RAW_SHA256",
    "EXPECTED_LIVENESS_RAW_SHA256",
    "EXPECTED_LIVENESS_SHA256",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "NOT_RUN",
    "REGISTER_LIVENESS_CERTIFICATE_FILENAME",
    "_boundary_ledger",
    "_cnot_ledger",
    "_hash_ledger",
    "_liveness_ledger",
    "_register_ledger",
    "_semantic_ledger",
    "_width_ledger",
    "apply_v45_encoding_state",
    "default_v45_ui_artifact_path",
    "default_v45_ui_liveness_path",
    "default_v45_ui_spec_path",
    "load_v45_ui_artifact",
    "load_v45_ui_supporting_evidence",
    "normalize_v45_artifact",
    "render_v45_width_reduction_panel",
]
