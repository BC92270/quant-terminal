"""Institutional, fail-closed V4.1 certified-bridge compiler surface.

The panel deliberately keeps three claims separate: exact augmented-graph
connectivity, the selected-model resource screen, and hardware execution.  A
valid connectivity certificate cannot turn a rejected resource ledger into a
production or hardware admission.
"""

from __future__ import annotations

import hashlib
from html import escape
import json
import math
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v41_certified_bridge_compiler import (
    canonical_json_sha256,
    default_v41_artifact_path,
)


SectionHeader = Callable[[str, str, str], None]

# RELEASE IDENTITY PINS
# Immutable release identities populated only after the complete independent
# rebuild accepted the sealed V4.1 artifact.
EXPECTED_V41_ARTIFACT_SHA256 = "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e"
EXPECTED_V41_ARTIFACT_RAW_SHA256 = "42a5d7caf4e9fab18e771b2bd55fc38c9a77f7fac42f2599feb4fe789cf88c07"

EXPECTED_V41_SPEC_SHA256 = "a5977ce4dda24d2fe6e8308e299b8a6b9097cf4fdf7e2835ca8e2fdc6aa99c89"
EXPECTED_V41_SPEC_RAW_SHA256 = "0bbe903e7520213f8effcd592051420ac54502934a1840b6052e3b4865950c35"
EXPECTED_V41_ENGINE_RAW_SHA256 = "6b065ac1fb834e9ff226954984fe466901314c9b556c2c253a0ace873f2bf26e"
EXPECTED_V41_SOURCE_RAW_SHA256 = "5565ce436034183228d27e37b249afc56f19121a5a8c2638533d4480762c62d1"
EXPECTED_V40_FREEZE_RAW_SHA256 = "748829b2153611ffba0751ea5da9d0785ca44ce4f12a02546436d4a1e79a94b4"
EXPECTED_V40_FROZEN_PATHS_FINGERPRINT_SHA256 = "43e80508152726db7fb8b255ba5642301abaadb6a562783fd235367475000fe3"
V40_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})
EXPECTED_V41_AUDITED_TWO_SWAP_CANDIDATES = 58_725
EXPECTED_V41_FEASIBLE_TWO_SWAP_CANDIDATES = 787
EXPECTED_V41_SELECTED_BRIDGES = 3
EXPECTED_V41_FINAL_COMPONENTS_ACROSS_SEEDS = 8
EXPECTED_V41_SELECTED_SPANNING_SUBGRAPH_EDGES = 337_710_606
EXPECTED_V41_MAXIMUM_R1_CNOT = 15_256_056
EXPECTED_V41_MAXIMUM_R2_CNOT = 15_663_936
EXPECTED_V41_BUDGET_CNOT = 2_500_000
EXPECTED_V41_MINIMUM_R2_MARGIN_CNOT = -13_163_936
EXPECTED_V41_MAXIMUM_R2_LOGICAL_QUBITS = 311
EXPECTED_SEEDS = [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _fmt(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "NOT AUTHENTICATED"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError, OverflowError):
        return str(value)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def v41_release_identity_pins_resolved() -> bool:
    """Return whether both immutable artifact identity pins are populated."""

    return _is_sha256(EXPECTED_V41_ARTIFACT_SHA256) and _is_sha256(EXPECTED_V41_ARTIFACT_RAW_SHA256)


def _scientific_validation_context() -> tuple[str, list[str]]:
    """Authenticate and commit to every immutable scientific dependency.

    The startup path verifies the exact V4.0 frozen byte set (apart from the two
    explicitly successor-mutable presentation files) and the sealed V4.1
    scientific sources.  The resulting digest invalidates the Streamlit cache
    after any byte-level mutation.  Exhaustive scientific replay remains a
    release-verifier obligation rather than a multi-minute UI side effect.
    """

    root = Path(__file__).resolve().parents[1]
    frozen_contract = root / "FREEZE_CONTRACT_V4_0.json"
    relative_paths: dict[str, str | None] = {
        "FREEZE_CONTRACT_V4_0.json": EXPECTED_V40_FREEZE_RAW_SHA256,
        "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json": EXPECTED_V41_SPEC_RAW_SHA256,
        "quantum_research_lab/phase3_v41_bridge_engine.cpp": EXPECTED_V41_ENGINE_RAW_SHA256,
        "quantum_research_lab/phase3_v41_certified_bridge_compiler.py": EXPECTED_V41_SOURCE_RAW_SHA256,
    }
    errors: list[str] = []
    try:
        if hashlib.sha256(frozen_contract.read_bytes()).hexdigest() != EXPECTED_V40_FREEZE_RAW_SHA256:
            raise ValueError("V4.0 freeze raw-file identity mismatch.")
        freeze_payload = json.loads(
            frozen_contract.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
        frozen_files = _mapping(freeze_payload).get("frozen_files")
        if not isinstance(frozen_files, Mapping):
            raise ValueError("V4.0 freeze contract has no frozen_files mapping.")
        if freeze_payload.get("frozen_paths_fingerprint_sha256") != EXPECTED_V40_FROZEN_PATHS_FINGERPRINT_SHA256:
            raise ValueError("V4.0 frozen-path fingerprint mismatch.")
        for relative, expected_sha in frozen_files.items():
            normalized = str(relative)
            if normalized not in V40_SUCCESSOR_MUTABLE:
                relative_paths[normalized] = str(expected_sha)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"Unable to bind validation cache to V4.0 freeze contents: {exc}")

    digest = hashlib.sha256()
    for relative, expected_sha in sorted(relative_paths.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        try:
            candidate = (root / relative).resolve(strict=True)
            candidate.relative_to(root)
            raw = candidate.read_bytes()
        except (OSError, ValueError) as exc:
            errors.append(f"Unable to hash validation dependency {relative}: {exc}")
            digest.update(b"INVALID_OR_MISSING")
        else:
            actual_sha = hashlib.sha256(raw).hexdigest()
            digest.update(bytes.fromhex(actual_sha))
            digest.update(len(raw).to_bytes(8, byteorder="big", signed=False))
            if expected_sha is not None and actual_sha != expected_sha:
                errors.append(f"Immutable validation dependency identity mismatch: {relative}")
        digest.update(b"\n")
    return digest.hexdigest(), list(dict.fromkeys(errors))


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_v41_scientific_validation(
    raw_artifact: bytes,
    raw_artifact_sha256: str,
    semantic_artifact_sha256: str,
    validation_context_sha256: str,
) -> dict[str, Any]:
    """Cache exact startup identity authentication.

    The sealed artifact is accepted only at its registered raw and semantic
    identities and only while every immutable predecessor/source byte matches.
    The slower 16-obligation independent reconstruction is executed by
    ``verify_phase3_v41.py`` during sealing, packaging and deployment.
    """

    if hashlib.sha256(raw_artifact).hexdigest() != raw_artifact_sha256:
        return {"valid": False, "checks": {}, "failed_checks": ["raw_cache_identity"], "errors": []}
    if not _is_sha256(validation_context_sha256):
        return {"valid": False, "checks": {}, "failed_checks": ["validation_context_identity"], "errors": []}
    try:
        payload = json.loads(
            raw_artifact.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
        if not isinstance(payload, dict):
            raise ValueError("V4.1 artifact must be a JSON object.")
        semantic = canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})
        if semantic != semantic_artifact_sha256:
            raise ValueError("V4.1 semantic cache identity mismatch.")
        parent = _mapping(_mapping(payload.get("parent")).get("authentication"))
        raw_checks = _mapping(parent.get("raw_checks"))
        required_parent_raw = {
            "engine": EXPECTED_V41_ENGINE_RAW_SHA256,
            "v40_artifact": "3e2918c31ff01d0545125fb641c850af6429a1f8db11709f419c38a2d9f619f2",
            "v40_engine": "16cdfffe8dde853f534349d0531f52c4026271f6f03de53ade77af4ec6726944",
            "v40_freeze": EXPECTED_V40_FREEZE_RAW_SHA256,
            "v40_source": "4ad9704cf4007a447195c6c9544ba38caa02316c32c1c0d7032b6a0cb6755afc",
            "v40_spec": "c86e73ebc4e7852407972dfcab89000e68dbeac4e9d635093a31eadc835109e2",
        }
        parent_raw_valid = all(
            _mapping(raw_checks.get(name)).get("actual") == expected
            and _mapping(raw_checks.get(name)).get("expected") == expected
            and _mapping(raw_checks.get(name)).get("valid") is True
            for name, expected in required_parent_raw.items()
        )
        semantic_checks = _mapping(parent.get("semantic_checks"))
        checks = {
            "artifact_raw_identity": raw_artifact_sha256 == EXPECTED_V41_ARTIFACT_RAW_SHA256,
            "artifact_semantic_identity": (
                semantic == payload.get("artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA256
            ),
            "sealed_v41_sources": (
                payload.get("spec_raw_file_sha256") == EXPECTED_V41_SPEC_RAW_SHA256
                and payload.get("spec_sha256") == EXPECTED_V41_SPEC_SHA256
                and payload.get("engine_source_raw_file_sha256") == EXPECTED_V41_ENGINE_RAW_SHA256
                and payload.get("source_sha256") == EXPECTED_V41_SOURCE_RAW_SHA256
            ),
            "embedded_parent_authentication": (
                parent.get("valid") is True
                and parent.get("errors") == []
                and parent.get("immutable_v40_paths_authenticated") == 143
                and parent.get("v40_frozen_paths_fingerprint_sha256")
                == EXPECTED_V40_FROZEN_PATHS_FINGERPRINT_SHA256
                and parent_raw_valid
                and semantic_checks.get("v40_artifact") is True
                and semantic_checks.get("v40_freeze") is True
                and semantic_checks.get("v40_spec") is True
            ),
            "claim_boundary": (
                payload.get("research_classification") == "RESEARCH_ONLY"
                and _mapping(payload.get("claim_boundary")).get("hardware_executable") is False
                and _mapping(payload.get("claim_boundary")).get("provider_calls") == 0
                and _mapping(payload.get("claim_boundary")).get("qpu_jobs_submitted") == 0
                and _mapping(payload.get("claim_boundary")).get("quantum_advantage") == "NOT_CLAIMED"
            ),
        }
        failed = [name for name, passed in checks.items() if not passed]
        return {"valid": not failed, "checks": checks, "failed_checks": failed, "errors": []}
    except Exception as exc:  # all cached validation failures remain data, never admission
        return {"valid": False, "checks": {}, "failed_checks": ["exception"], "errors": [str(exc)]}


def load_v41_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the exact sealed V4.1 artifact, rejecting every unpinned variant."""

    target = Path(path) if path is not None else default_v41_artifact_path()
    errors: list[str] = []
    try:
        raw = target.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        return {}, {"valid": False, "errors": [str(exc)]}
    if not isinstance(payload, dict):
        return {}, {"valid": False, "errors": ["V4.1 artifact must be a JSON object."]}
    try:
        semantic = canonical_json_sha256({key: value for key, value in payload.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError) as exc:
        return payload, {"valid": False, "errors": [str(exc)]}
    raw_sha = hashlib.sha256(raw).hexdigest()
    if not v41_release_identity_pins_resolved():
        errors.append("V4.1 UI release identity pins are unresolved; evidence is masked fail-closed.")
    if payload.get("artifact_sha256") != semantic:
        errors.append("V4.1 artifact self-hash mismatch.")
    if semantic != EXPECTED_V41_ARTIFACT_SHA256:
        errors.append("V4.1 artifact semantic identity mismatch.")
    if raw_sha != EXPECTED_V41_ARTIFACT_RAW_SHA256:
        errors.append("V4.1 artifact raw-file identity mismatch.")
    validation_context_sha, context_errors = _scientific_validation_context()
    errors.extend(context_errors)
    scientific_report = _cached_v41_scientific_validation(raw, raw_sha, semantic, validation_context_sha)
    if scientific_report.get("valid") is not True:
        failures = scientific_report.get("errors") or scientific_report.get("failed_checks") or ["unknown failure"]
        errors.extend(f"Scientific artifact validation: {item}" for item in failures)
    return payload, {
        "valid": not errors,
        "errors": errors,
        "semantic_sha256": semantic,
        "raw_file_sha256": raw_sha,
        "validation_context_sha256": validation_context_sha,
        "scientific_checks": scientific_report.get("checks") or {},
    }


def normalize_v41_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    """Expose scientific evidence only when the complete V4.1 contract matches."""

    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    parent = _mapping(_mapping(source.get("parent")).get("authentication"))
    boundary = _mapping(source.get("claim_boundary"))
    bridge_audits = _mapping(source.get("bridge_audits"))
    audit_rows = _rows(bridge_audits.get("rows"))
    connectivity = _mapping(source.get("connectivity_evidence"))
    connectivity_aggregate = _mapping(connectivity.get("aggregate"))
    connectivity_rows = _rows(connectivity.get("seed_rows"))
    compression = _mapping(source.get("compression_evidence"))
    resource = _mapping(source.get("resource_evidence"))
    resource_aggregate = _mapping(resource.get("aggregate"))
    resource_seed_rows = _rows(resource.get("seed_rows"))
    try:
        semantic = canonical_json_sha256({key: value for key, value in source.items() if key != "artifact_sha256"})
    except (TypeError, ValueError, OverflowError):
        semantic = ""

    expected_audit_sources = [(2207, "08b4208484"), (7703, "a8180000ec"), (7703, "e2008a4082")]
    observed_audit_sources = [(row.get("seed"), row.get("source_mask_hex")) for row in audit_rows]
    audit_counts = sorted(int(row.get("feasible_neighbor_count", -1)) for row in audit_rows)
    resource_seeds = [row.get("seed") for row in resource_seed_rows]
    connectivity_seeds = [row.get("seed") for row in connectivity_rows]
    r1_maximum = resource_aggregate.get("r1_maximum_selected_model_cnot")
    r2_maximum = resource_aggregate.get("r2_maximum_selected_model_cnot")
    r2_logical_qubits = [
        _mapping(row.get("r2")).get("logical_qubits_with_clean_decomposition_ancillas")
        for row in resource_seed_rows
    ]

    authenticated = bool(
        artifact_integrity is True
        and spec_integrity is True
        and parent_integrity is True
        and v41_release_identity_pins_resolved()
        and source.get("artifact_sha256") == semantic == EXPECTED_V41_ARTIFACT_SHA256
        and source.get("spec_sha256") == EXPECTED_V41_SPEC_SHA256
        and parent.get("valid") is True
        and source.get("research_classification") == "RESEARCH_ONLY"
        and decisions.get("augmented_connectivity_decision")
        == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
        and decisions.get("resource_architecture_decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        and decisions.get("production_admission") == "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED"
        and decisions.get("backend_native") == "NOT_RUN_PROVIDER_FREE_PHASE"
        and bridge_audits.get("all_triple_replays_match") is True
        and len(audit_rows) == 3
        and observed_audit_sources == expected_audit_sources
        and all(int(row.get("candidates_audited", -1)) == 19_575 for row in audit_rows)
        and audit_counts == [260, 260, 267]
        and sum(int(row.get("candidates_audited", 0)) for row in audit_rows)
        == EXPECTED_V41_AUDITED_TWO_SWAP_CANDIDATES
        and sum(int(row.get("feasible_neighbor_count", 0)) for row in audit_rows)
        == EXPECTED_V41_FEASIBLE_TWO_SWAP_CANDIDATES
        and connectivity.get("connectivity_decision")
        == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
        and connectivity_aggregate.get("all_eight_seeds_connected_by_certified_subgraph") is True
        and connectivity_aggregate.get("audited_incident_two_swap_candidates")
        == EXPECTED_V41_AUDITED_TWO_SWAP_CANDIDATES
        and connectivity_aggregate.get("feasible_incident_two_swap_candidates")
        == EXPECTED_V41_FEASIBLE_TWO_SWAP_CANDIDATES
        and connectivity_aggregate.get("selected_bridge_count") == EXPECTED_V41_SELECTED_BRIDGES
        and connectivity_aggregate.get("final_components_across_seeds")
        == EXPECTED_V41_FINAL_COMPONENTS_ACROSS_SEEDS
        and connectivity_aggregate.get("selected_spanning_subgraph_edges")
        == EXPECTED_V41_SELECTED_SPANNING_SUBGRAPH_EDGES
        and connectivity_aggregate.get("complete_augmented_edge_count")
        == "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE"
        and connectivity_seeds == EXPECTED_SEEDS
        and all(row.get("connected_by_certified_subgraph") is True for row in connectivity_rows)
        and compression.get("all_factor_predicates_exact") is True
        and resource.get("architecture_id")
        == "EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1"
        and resource_seeds == EXPECTED_SEEDS
        and resource_aggregate.get("budget_cnot") == EXPECTED_V41_BUDGET_CNOT
        and resource_aggregate.get("cache_preparation_excluded_from_numerator") is True
        and resource_aggregate.get("r1_all_seeds_pass") is False
        and resource_aggregate.get("r2_all_seeds_pass") is False
        and resource_aggregate.get("r1_decision") == "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET"
        and resource_aggregate.get("r2_decision") == "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET"
        and r1_maximum == EXPECTED_V41_MAXIMUM_R1_CNOT
        and r2_maximum == EXPECTED_V41_MAXIMUM_R2_CNOT
        and resource_aggregate.get("r2_minimum_budget_margin_cnot") == EXPECTED_V41_MINIMUM_R2_MARGIN_CNOT
        and len(r2_logical_qubits) == len(EXPECTED_SEEDS)
        and all(type(value) is int for value in r2_logical_qubits)
        and max(int(value) for value in r2_logical_qubits)
        == EXPECTED_V41_MAXIMUM_R2_LOGICAL_QUBITS
        and max(r1_maximum, r2_maximum) == EXPECTED_V41_MAXIMUM_R2_CNOT
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("provider_credentials_read") is False
        and boundary.get("provider_sdk_imported") is False
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        and boundary.get("backend_transpilation") == "NOT_RUN"
    )
    reveal = lambda value: value if authenticated else None
    return {
        "authenticated": authenticated,
        "artifact": dict(source) if authenticated else {},
        "artifact_sha256": str(source.get("artifact_sha256")) if authenticated else "NOT AUTHENTICATED",
        "overall": str(decisions.get("overall")) if authenticated else "NOT AUTHENTICATED",
        "connectivity_decision": str(decisions.get("augmented_connectivity_decision")) if authenticated else "NOT AUTHENTICATED",
        "resource_decision": str(decisions.get("resource_architecture_decision")) if authenticated else "NOT AUTHENTICATED",
        "production_admission": str(decisions.get("production_admission")) if authenticated else "NOT AUTHENTICATED",
        "next_gate": str(decisions.get("next_falsifiable_gate")) if authenticated else "NOT AUTHENTICATED",
        "audit_rows": audit_rows if authenticated else [],
        "connectivity": dict(connectivity) if authenticated else {},
        "connectivity_rows": connectivity_rows if authenticated else [],
        "connectivity_aggregate": dict(connectivity_aggregate) if authenticated else {},
        "compression_rows": _rows(compression.get("seed_rows")) if authenticated else [],
        "resource_seed_rows": resource_seed_rows if authenticated else [],
        "resource_aggregate": dict(resource_aggregate) if authenticated else {},
        "boundary": dict(boundary) if authenticated else {},
        "r1_maximum": reveal(r1_maximum),
        "r2_maximum": reveal(r2_maximum),
        "minimum_r2_margin": reveal(resource_aggregate.get("r2_minimum_budget_margin_cnot")),
    }


def _bridge_audit_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("audit_rows") or []:
        first = _mapping((row.get("feasible_records") or [{}])[0])
        rows.append({
            "Seed": row.get("seed"),
            "Isolated source": row.get("source_mask_hex"),
            "Candidates audited": row.get("candidates_audited"),
            "Feasible two-swaps": row.get("feasible_neighbor_count"),
            "Triple replay": row.get("triple_replay_match"),
            "Independent methods": " · ".join(str(value) for value in row.get("independent_methods") or []),
            "First feasible target": first.get("target_mask_hex"),
            "First removed": ", ".join(str(value) for value in first.get("removed") or []),
            "First added": ", ".join(str(value) for value in first.get("added") or []),
            "Classification ledger SHA": row.get("classification_ledger_sha256"),
            "Feasible-record SHA": row.get("feasible_record_sha256"),
            "Audit SHA": row.get("isolate_audit_sha256"),
        })
    return pd.DataFrame(rows)


def _selected_bridge_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in state.get("connectivity_rows") or []:
        for bridge in seed_row.get("selected_bridges") or []:
            rows.append({
                "Seed": seed_row.get("seed"),
                "Selection rank": bridge.get("selection_rank"),
                "Source": bridge.get("source_mask_hex"),
                "Target": bridge.get("target_mask_hex"),
                "Source component": bridge.get("source_component_representative"),
                "Target component": bridge.get("target_component_representative"),
                "Removed": ", ".join(str(value) for value in bridge.get("removed") or []),
                "Added": ", ".join(str(value) for value in bridge.get("added") or []),
                "Hamming distance": bridge.get("hamming_distance"),
                "Exact seven values": ", ".join(str(value) for value in bridge.get("exact_values") or []),
                "Bridge SHA": bridge.get("bridge_sha256"),
            })
    return pd.DataFrame(rows)


def _connectivity_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Seed": row.get("seed"),
            "V4 feasible vertices": row.get("authenticated_v40_feasible_vertices"),
            "V4 exact one-swap edges": row.get("authenticated_v40_exact_one_swap_edges"),
            "Components before": row.get("authenticated_v40_component_count"),
            "Singletons": row.get("singleton_component_count"),
            "Candidate bridges": row.get("candidate_bridge_count"),
            "Selected bridges": row.get("selected_bridge_count"),
            "Certified-subgraph edges": row.get("selected_spanning_subgraph_edges"),
            "Components after": row.get("final_component_count"),
            "Connected": row.get("connected_by_certified_subgraph"),
            "All incident candidates audited": row.get("all_incident_candidates_audited"),
            "Certificate SHA": row.get("seed_connectivity_sha256"),
        }
        for row in state.get("connectivity_rows") or []
    ])


def _resource_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("resource_seed_rows") or []:
        r1 = _mapping(row.get("r1"))
        r2 = _mapping(row.get("r2"))
        r1_resources = _mapping(r1.get("selected_model_layer_resources"))
        r2_resources = _mapping(r2.get("selected_model_layer_resources"))
        bridge_resources = _mapping(r2.get("bridge_resources"))
        one_swap = _mapping(row.get("one_swap_layer"))
        cache = _mapping(row.get("cache_preparation_outside_numerator"))
        cache_resources = _mapping(cache.get("resources"))
        cache_macros = _mapping(cache.get("macros"))
        rows.append({
            "Seed": row.get("seed"),
            "Ordered one-swap positions": one_swap.get("ordered_positions"),
            "Live positions": one_swap.get("live_positions"),
            "Certified identities": one_swap.get("certified_identity_positions"),
            "R1 connected": r1.get("connectivity_pass"),
            "R1 CNOT": r1_resources.get("selected_model_cnot"),
            "R1 margin": r1.get("budget_margin_cnot"),
            "R1 decision": r1.get("decision"),
            "R2 connected": r2.get("connectivity_pass"),
            "Bridge CNOT": bridge_resources.get("selected_model_cnot"),
            "R2 CNOT": r2_resources.get("selected_model_cnot"),
            "R2 margin": r2.get("budget_margin_cnot"),
            "R2 decision": r2.get("decision"),
            "Cache prep CNOT (excluded)": cache_resources.get("selected_model_cnot"),
            "Cache controlled adds": cache_macros.get("controlled_add_macros"),
            "Cache qubits": one_swap.get("cache_qubits"),
            "R1 logical qubits + clean ancillas": r1.get("logical_qubits_with_clean_decomposition_ancillas"),
            "R2 logical qubits + clean ancillas": r2.get("logical_qubits_with_clean_decomposition_ancillas"),
            "Seed ledger SHA": row.get("seed_resource_sha256"),
        })
    return pd.DataFrame(rows)


def _compression_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    # Several exact dyadic thresholds and proof distances intentionally exceed
    # Arrow/int64.  Decimal strings preserve every bit and keep Streamlit from
    # coercing a scientific integer ledger through a platform C long.
    exact_decimal = lambda value: str(value) if type(value) is int else value
    rows: list[dict[str, Any]] = []
    for seed_row in state.get("compression_rows") or []:
        for factor in seed_row.get("factor_rows") or []:
            rows.append({
                "Seed": seed_row.get("seed"),
                "Factor": factor.get("factor"),
                "Complete domain": factor.get("classification_domain_count"),
                "Shift": factor.get("selected_shift"),
                "Scale": factor.get("scale"),
                "Original lower": exact_decimal(factor.get("original_lower_int")),
                "Original upper": exact_decimal(factor.get("original_upper_int")),
                "Compressed lower": exact_decimal(factor.get("compressed_lower_int")),
                "Compressed upper": exact_decimal(factor.get("compressed_upper_int")),
                "Exact min threshold distance": exact_decimal(factor.get("exact_minimum_threshold_distance")),
                "Exact error bound": exact_decimal(factor.get("exact_error_bound")),
                "Predicate parity": factor.get("identity_or_strict_margin_parity_proof"),
                "Certificate SHA": factor.get("compression_certificate_sha256"),
            })
    return pd.DataFrame(rows)


def render_v41_certified_bridge_compiler_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    """Render the V4.1 evidence room without initiating scientific work."""

    state = normalize_v41_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
    )
    section_header(
        "V4.1 Certified Bridge Compiler & Proof-Carrying Resources",
        "V4.0 FOREST → 58,725 EXACT AUDITS → 3 BRIDGES → CONNECTED SUBGRAPH → R1/R2 RESOURCE SCREEN",
        "The complete V4.0 one-swap forest plus three deterministic exact two-swap bridges certifies augmented connectivity. "
        "The proof-carrying resource architecture is evaluated independently and remains rejected by the frozen CNOT budget.",
    )
    st.markdown(
        """<style>
        .qv41-shell{border:1px solid rgba(100,237,255,.38);border-radius:23px;padding:22px 23px;margin:10px 0 14px;background:radial-gradient(circle at 91% 8%,rgba(57,255,184,.15),transparent 29%),radial-gradient(circle at 9% 100%,rgba(108,80,255,.18),transparent 32%),linear-gradient(132deg,rgba(2,18,31,.99),rgba(15,17,52,.98) 58%,rgba(41,10,43,.97));box-shadow:0 0 54px rgba(67,219,255,.11)}
        .qv41-k{font-size:.61rem;letter-spacing:.18em;color:#76efff;font-weight:950}.qv41-title{font-size:1.17rem;color:#9dffd6;font-weight:950;margin:7px 0}.qv41-copy{font-size:.74rem;color:#afbed2;line-height:1.5}.qv41-tags{font-size:.61rem;color:#a1b3ce;letter-spacing:.10em;margin-top:10px}.qv41-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:11px 0 16px}.qv41-card{border:1px solid rgba(109,219,255,.18);background:rgba(3,15,29,.80);border-radius:14px;padding:12px}.qv41-label{font-size:.49rem;color:#879dbd;letter-spacing:.11em;font-weight:900}.qv41-value{font-size:.86rem;color:#f7f9ff;font-weight:950;margin:5px 0;overflow-wrap:anywhere}.qv41-pass{color:#78efbe}.qv41-reject{color:#ffaaa9}.qv41-warn{color:#ffd08b}.qv41-note{font-size:.60rem;color:#93a7bd;line-height:1.38}@media(max-width:1120px){.qv41-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:560px){.qv41-grid{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    ok = bool(state["authenticated"])
    connectivity = _mapping(state.get("connectivity_aggregate"))
    resources = _mapping(state.get("resource_aggregate"))
    st.markdown(
        f"""<div class="qv41-shell" data-qv41-surface="certified-bridge-compiler" data-qv41-release="4.1" data-qv41-auth="{'pass' if ok else 'fail'}" data-qv41-connectivity="{'CONNECTED_BY_CERTIFIED_SUBGRAPH' if ok else 'INDETERMINATE'}" data-qv41-bridge-count="{'3' if ok else 'masked'}" data-qv41-resource="{'REJECTED' if ok else 'INDETERMINATE'}" data-qv41-cache-prep="EXCLUDED_FROM_NUMERATOR" data-qv41-production="REJECTED" data-qv41-hardware="false" data-qv41-jobs="0">
        <div class="qv41-k">V4.1 · CERTIFIED BRIDGE COMPILER &amp; PROOF-CARRYING RESOURCES</div>
        <div class="qv41-title">{escape(state['overall'])}</div>
        <div class="qv41-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT / UNPINNED'} · SHA {escape(state['artifact_sha256'])}<br>Connectivity: {escape(state['connectivity_decision'])}<br>Resources: {escape(state['resource_decision'])} · production: {escape(state['production_admission'])}</div>
        <div class="qv41-tags">RESEARCH_ONLY · EXACT INT128 · TRIPLE REPLAY · PROVIDER FREE · HARDWARE EXECUTABLE FALSE</div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown("**V4.1 · AUGMENTED 1+2 EXCHANGE GRAPH & PROOF-CARRYING RESOURCE ADMISSION**")
    st.markdown(
        f"""<div class="qv41-grid">
        <div class="qv41-card"><div class="qv41-label">ARTIFACT AUTH</div><div class="qv41-value {'qv41-pass' if ok else 'qv41-reject'}">{'PASS' if ok else 'NOT AUTHENTICATED'}</div><div class="qv41-note">raw + semantic + V4.0 immutable lineage</div></div>
        <div class="qv41-card"><div class="qv41-label">TWO-SWAP AUDITS</div><div class="qv41-value">{escape(_fmt(connectivity.get('audited_incident_two_swap_candidates')))}</div><div class="qv41-note">19,575 × 3 isolated sources</div></div>
        <div class="qv41-card"><div class="qv41-label">EXACT FEASIBLE</div><div class="qv41-value">{escape(_fmt(connectivity.get('feasible_incident_two_swap_candidates')))}</div><div class="qv41-note">triple-replayed incident bridges</div></div>
        <div class="qv41-card"><div class="qv41-label">SELECTED BRIDGES</div><div class="qv41-value qv41-pass">{escape(_fmt(connectivity.get('selected_bridge_count')))}</div><div class="qv41-note">deterministic Kruskal order</div></div>
        <div class="qv41-card"><div class="qv41-label">FINAL COMPONENTS</div><div class="qv41-value qv41-pass">{'8 / 8' if ok else 'NOT AUTHENTICATED'}</div><div class="qv41-note">one connected component per seed</div></div>
        <div class="qv41-card"><div class="qv41-label">CERTIFIED SUBGRAPH EDGES</div><div class="qv41-value">{escape(_fmt(connectivity.get('selected_spanning_subgraph_edges')))}</div><div class="qv41-note">337,710,603 V4 edges + 3 bridges</div></div>
        <div class="qv41-card"><div class="qv41-label">R1 MAX CNOT</div><div class="qv41-value qv41-reject">{escape(_fmt(state.get('r1_maximum')))}</div><div class="qv41-note">15,256,056 · candidate rejected</div></div>
        <div class="qv41-card"><div class="qv41-label">R2 MAX CNOT</div><div class="qv41-value qv41-reject">{escape(_fmt(state.get('r2_maximum')))}</div><div class="qv41-note">15,663,936 vs 2,500,000</div></div>
        <div class="qv41-card"><div class="qv41-label">R2 BUDGET MARGIN</div><div class="qv41-value qv41-reject">{escape(_fmt(state.get('minimum_r2_margin')))}</div><div class="qv41-note">architecture-specific exact screen</div></div>
        <div class="qv41-card"><div class="qv41-label">HARDWARE / JOBS</div><div class="qv41-value qv41-reject">FALSE / 0</div><div class="qv41-note">no SDK, credentials or provider calls</div></div></div>""",
        unsafe_allow_html=True,
    )

    if ok:
        st.success(
            "CONNECTED BY CERTIFIED SUBGRAPH · PASS — all eight authenticated V4.0 component forests become connected after three exact, deterministic Hamming-distance-four bridges."
        )
        st.info(
            "58,725 / 58,725 INCIDENT TWO-SWAP CANDIDATES AUDITED — 787 are exactly feasible; Python delta, Python full recomputation and independent C++ int128 replays agree."
        )
        st.error(
            "RESOURCE ADMISSION · REJECTED — R1 and R2 are both published and rejected. The maximum R2 numerator is 15,663,936 CNOT against the immutable 2,500,000 gate (margin -13,163,936)."
        )
    else:
        st.error(
            "V4.1 evidence is absent, invalid, or not release-pinned. Connectivity, bridge inventories, compression certificates, resource counts and downloads remain masked."
        )

    st.markdown("**FULL AUGMENTED EDGE COUNT · NOT ENUMERATED · NOT REQUIRED FOR THE CONNECTIVITY CERTIFICATE**")
    st.caption(
        "The displayed 337,710,606 edges belong to the authenticated connected spanning subgraph: every complete V4.0 one-swap edge plus three selected bridges. It is not the full 1+2 edge count."
    )

    bridge_audits = _bridge_audit_ledger(state)
    st.markdown("**Complete incident two-swap audit ledger · three V4.0 singleton components**")
    st.dataframe(bridge_audits, width="stretch", hide_index=True)

    selected_bridges = _selected_bridge_ledger(state)
    st.markdown("**Deterministically selected exact component bridges**")
    st.dataframe(selected_bridges, width="stretch", hide_index=True)

    connectivity_ledger = _connectivity_ledger(state)
    st.markdown("**Eight-seed augmented-connectivity certificate ledger**")
    st.dataframe(connectivity_ledger, width="stretch", hide_index=True)

    if ok and not connectivity_ledger.empty:
        chart = connectivity_ledger[["Seed", "V4 feasible vertices", "Certified-subgraph edges"]].copy().set_index("Seed")
        chart = chart.apply(lambda column: column.map(lambda value: math.log10(max(1, int(value)))))
        st.markdown("**Authenticated certificate scale by seed · log10 counts**")
        st.bar_chart(chart, width="stretch")

    resource_ledger = _resource_ledger(state)
    st.markdown("**R1 + R2 exact selected-model resource ledger · all eight seeds**")
    st.dataframe(resource_ledger, width="stretch", hide_index=True)
    st.warning(
        "CACHE PREPARATION · REPORTED SEPARATELY · EXCLUDED FROM NUMERATOR — coherent guarded-slack cache construction has its own exact selected-model ledger. It is never hidden inside, nor credited against, the ordered mixer-layer CNOT endpoint."
    )
    st.markdown("**R1_LINEAR_SLACK_ALL_ONE_SWAP · REJECTED**")
    st.markdown("**R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES · REJECTED_SELECTED_MODEL_CNOT_BUDGET**")
    st.markdown("**PRIMARY ENDPOINT · MAXIMUM R2 CNOT ACROSS ALL EIGHT FROZEN SEEDS**")
    st.markdown("**POST-OBSERVATION CANDIDATE SWITCHING · PROHIBITED**")

    compression_ledger = _compression_ledger(state)
    st.markdown("**Exact coefficient-compression certificates · complete-domain predicate parity**")
    st.dataframe(compression_ledger, width="stretch", hide_index=True)

    obligations = pd.DataFrame(
        [
            ("V4.0 immutable lineage", "Artifact + spec + sources + freeze + frozen paths", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Incident bridge universe", "19,575 candidates per singleton; 58,725 total", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Independent exact replay", "Python delta + Python full + C++ int128", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Augmented connectivity", "Complete V4 forest + deterministic selected bridges", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Full augmented edge enumeration", "Not required for connected-subgraph proof", "NOT RUN"),
            ("Compression predicate parity", "Dual MITM exact strict-margin certificates", "PASS" if ok else "NOT AUTHENTICATED"),
            ("R1 resource admission", "Connectivity and 2.5M selected-model CNOT gate", "REJECTED" if ok else "NOT AUTHENTICATED"),
            ("R2 resource admission", "Connectivity pass; 2.5M selected-model CNOT gate", "REJECTED" if ok else "NOT AUTHENTICATED"),
            ("Cache preparation", "Exact separate selected-model ledger", "EXCLUDED FROM NUMERATOR"),
            ("Named backend / hardware", "Not run; zero jobs", "BLOCKED"),
        ],
        columns=["Evidence obligation", "Method / scope", "State"],
    )
    st.markdown("**Evidence obligations · proof layers remain non-substitutable**")
    st.dataframe(obligations, width="stretch", hide_index=True)

    with st.expander("Architecture contract · exact guarded-slack compiler", expanded=False):
        st.markdown("**EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1**")
        st.markdown(
            "Compressed predicates retain exact complete-domain classification under dual MITM certificates. "
            "Each cache stores guarded unsigned slack with a no-wrap proof; measurement-free pair actions compute, rotate and uncompute clean scratch."
        )
        st.markdown("**SELECTED MODEL · CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1**")

    for label, suffix, help_text in (
        ("Recompute sealed V4.1 evidence", "recompute", "The release surface exposes immutable offline evidence only."),
        ("Override deterministic bridge selection", "bridge_override", "Registered Kruskal ordering is immutable."),
        ("Relabel incomplete bridge coverage", "relabel", "Incomplete audit coverage always fails closed."),
        ("Claim the full augmented edge count", "edge_claim", "The full two-swap edge universe was not enumerated."),
        ("Include cache preparation selectively", "cache_switch", "Numerator and preparation ledgers are fixed and separate."),
        ("Switch R1/R2 after observation", "candidate_switch", "Both registered candidates are always published."),
        ("Override 2,500,000 CNOT gate", "budget_override", "The primary endpoint is immutable."),
        ("Open named-backend or QPU lane", "backend", "Resource rejection blocks backend and hardware admission."),
    ):
        st.button(label, disabled=True, key=f"{key_prefix}_v41_{suffix}", help=help_text)

    if ok:
        artifact_bytes = (json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        st.download_button(
            "Download sealed V4.1 certified-bridge compiler artifact",
            data=artifact_bytes,
            file_name="SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v41_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V4.1 frozen compiler specification",
                data=(json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
                file_name="PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v41_spec_download",
            )
        st.download_button(
            "Download V4.1 bridge-audit ledger CSV",
            data=bridge_audits.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V4_1_BRIDGE_AUDITS.csv",
            mime="text/csv",
            key=f"{key_prefix}_v41_bridge_audit_download",
        )
        st.download_button(
            "Download V4.1 selected-bridge ledger CSV",
            data=selected_bridges.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V4_1_SELECTED_BRIDGES.csv",
            mime="text/csv",
            key=f"{key_prefix}_v41_selected_bridge_download",
        )
        st.download_button(
            "Download V4.1 resource ledger CSV",
            data=resource_ledger.to_csv(index=False).encode("utf-8"),
            file_name="QUANTUM_LAB_V4_1_RESOURCE_LEDGER.csv",
            mime="text/csv",
            key=f"{key_prefix}_v41_resource_download",
        )

    st.warning(
        "V4.1 CLAIM BOUNDARY · EXACT CONNECTIVITY AND PROVIDER-NEUTRAL RESOURCE EVIDENCE ONLY. "
        "Connectivity is certified for the frozen 1+2 exchange family; optimization performance, backend transpilation, hardware execution and quantum advantage are not established."
    )
    st.markdown(f"**{escape(state['next_gate'])}**")
    st.markdown("**BACKEND TRANSPILATION · NOT RUN**")
    st.markdown("**HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0**")
    st.markdown("**PROVIDER CALLS · 0 · CREDENTIALS READ · FALSE · SDK IMPORTED · FALSE**")
    st.markdown("**QUANTUM ADVANTAGE · NOT CLAIMED**")
    return state


def apply_v41_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project only authenticated V4.1 bounded decisions into BANDS state."""

    if encoding is None:
        return None
    projected = dict(encoding)
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True:
        return projected
    source = _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    connectivity = _mapping(_mapping(source.get("connectivity_evidence")).get("aggregate"))
    resources = _mapping(_mapping(source.get("resource_evidence")).get("aggregate"))
    projected.update({
        "v41_artifact_sha": source.get("artifact_sha256"),
        "v41_augmented_connectivity_decision": decisions.get("augmented_connectivity_decision"),
        "v41_resource_architecture_decision": decisions.get("resource_architecture_decision"),
        "v41_production_admission": decisions.get("production_admission"),
        "v41_next_falsifiable_gate": decisions.get("next_falsifiable_gate"),
        "v41_augmented_connectivity": "CONNECTED_BY_CERTIFIED_SUBGRAPH",
        "v41_selected_bridge_count": connectivity.get("selected_bridge_count"),
        "v41_audited_incident_two_swap_candidates": connectivity.get("audited_incident_two_swap_candidates"),
        "v41_feasible_incident_two_swap_candidates": connectivity.get("feasible_incident_two_swap_candidates"),
        "v41_r1_maximum_selected_model_cnot": resources.get("r1_maximum_selected_model_cnot"),
        "v41_r2_maximum_selected_model_cnot": resources.get("r2_maximum_selected_model_cnot"),
        "v41_r2_budget_margin_cnot": resources.get("r2_minimum_budget_margin_cnot"),
        "v41_cache_preparation_excluded_from_numerator": resources.get("cache_preparation_excluded_from_numerator"),
        "encoding_status": "V4.1 CONNECTIVITY CERTIFIED · RESOURCE BUDGET REJECTED",
        "hardware_executable": False,
        "qpu_jobs_submitted": 0,
        "quantum_advantage": "NOT_CLAIMED",
    })
    return projected


__all__ = [
    "EXPECTED_V41_ARTIFACT_RAW_SHA256",
    "EXPECTED_V41_ARTIFACT_SHA256",
    "EXPECTED_V41_SPEC_SHA256",
    "apply_v41_encoding_state",
    "load_v41_ui_artifact",
    "normalize_v41_artifact",
    "render_v41_certified_bridge_compiler_panel",
    "v41_release_identity_pins_resolved",
]
