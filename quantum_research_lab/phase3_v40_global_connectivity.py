"""Exact global feasible-graph connectivity evidence for Quantum Lab V4.0.

V4.0 answers the graph question deliberately left open by V3.9.  It compiles
and runs a provider-free C++ engine twice with different meet-in-the-middle
partitions, authenticates equality of all stable evidence, and seals compact
connected-component certificates.  Quantum backend execution is outside this
module by construction.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from .phase3_v39_scalable_reversible_ir import validate_v39_artifact


V40_VERSION = "PHASE III · V4.0 GLOBAL FEASIBLE-GRAPH CONNECTIVITY · V1"
ARTIFACT_VERSION = "PHASE III · V4.0 GLOBAL CONNECTIVITY COUNTEREXAMPLE ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json"
ENGINE_FILENAME = "phase3_v40_connectivity_engine.cpp"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json"
SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
N = 40
K = 10
EXPECTED_V39_ARTIFACT_RAW = "38d2d16856f1930f1f86848929a4341cab18e02edf387208debc6cd5213aed29"
EXPECTED_V39_ARTIFACT_SHA = "26856f1e26bed5dc5b9a6d6af7bb25c53ef0b25188d8c787276afbeb08027775"
EXPECTED_V39_SPEC_RAW = "b710e884216a765118c6309b59b0a30adf284ba89163ac34151e26d4629d1b7d"
EXPECTED_V39_SPEC_SHA = "a3845e1b553f25eaebb4a80cb697c28dae2da07e1193ecf6cd03158de428ec5c"
EXPECTED_V39_SOURCE_RAW = "94dfd1691252bc4896e6f29bb0727ad75a2736a0de019d22bb0dea7643ceda94"
EXPECTED_V39_FREEZE_RAW = "e44295aaab7689be7090ff6022a67e2e7d96cc40fcdaedf0328aa50294880c59"
EXPECTED_V39_FREEZE_SHA = "510790b4682e09376feb226b9d0b8b0046477ea456abf0a38e0cadb2410300ac"
EXPECTED_V31_RAW = "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e"
EXPECTED_V31_SHA = "D9D109D117E1795CFFEF"
EXPECTED_ENGINE_RAW = "16cdfffe8dde853f534349d0531f52c4026271f6f03de53ade77af4ec6726944"
V39_MUTABLE_SUCCESSOR_PATHS = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})


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


def source_sha256() -> str:
    return raw_file_sha256(Path(__file__))


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: str | Path) -> dict[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _paths(root: str | Path | None = None) -> dict[str, Path]:
    base = _root(root)
    return {
        "root": base,
        "spec": base / "quantum_research_lab" / SPEC_FILENAME,
        "engine": base / "quantum_research_lab" / ENGINE_FILENAME,
        "v39_artifact": base / "outputs" / "quantum_phase3" / "v39_scalable_ir" / "SEALED_V3_9_SCALABLE_REVERSIBLE_IR_ARTIFACT.json",
        "v39_spec": base / "quantum_research_lab" / "PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json",
        "v39_source": base / "quantum_research_lab" / "phase3_v39_scalable_reversible_ir.py",
        "v39_freeze": base / "FREEZE_CONTRACT_V3_9.json",
        "v31": base / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        "witness_spec": base / "quantum_research_lab" / "PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
    }


def load_v40_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["spec"]
    payload = _read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v40_spec_sha", "v40_spec_sha256"}}
    digest = canonical_json_sha256(core)
    if payload.get("v40_spec_sha256") != digest or payload.get("v40_spec_sha") != digest[:20].upper():
        raise ValueError("V4.0 specification self-hash mismatch.")
    boundary = payload.get("claim_boundary") or {}
    redesign = payload.get("resource_redesign_preregistration") or {}
    if not (
        boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and redesign.get("status") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and (redesign.get("result_fields") or {}).get("cnot") == "NOT_EVALUATED"
    ):
        raise ValueError("V4.0 specification violates the scientific boundary.")
    return payload


def authenticate_parent_chain(*, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v40_spec(root=paths["root"])
    expected = spec["parent_contract"]
    errors: list[str] = []
    expected_raw = {
        "v39_artifact": EXPECTED_V39_ARTIFACT_RAW,
        "v39_spec": EXPECTED_V39_SPEC_RAW,
        "v39_source": EXPECTED_V39_SOURCE_RAW,
        "v39_freeze": EXPECTED_V39_FREEZE_RAW,
        "v31": EXPECTED_V31_RAW,
        "engine": EXPECTED_ENGINE_RAW,
    }
    actual_raw: dict[str, str] = {}
    for name, registered in expected_raw.items():
        try:
            actual_raw[name] = raw_file_sha256(paths[name])
        except Exception as exc:
            actual_raw[name] = ""
            errors.append(f"Unable to hash {name}: {exc}")
            continue
        if actual_raw[name] != registered:
            errors.append(f"Raw identity mismatch: {name}")

    if expected.get("expected_v39_artifact_raw_file_sha256") != EXPECTED_V39_ARTIFACT_RAW:
        errors.append("Specification V3.9 artifact constant drift.")
    if expected.get("expected_v39_freeze_raw_file_sha256") != EXPECTED_V39_FREEZE_RAW:
        errors.append("Specification V3.9 freeze constant drift.")
    if (spec.get("connectivity_protocol") or {}).get("engine_source_raw_file_sha256") != EXPECTED_ENGINE_RAW:
        errors.append("Specification engine source constant drift.")

    semantic_checks: dict[str, bool] = {}
    try:
        artifact = _read_json_strict(paths["v39_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        semantic_checks["v39_artifact"] = bool(
            artifact.get("artifact_sha256") == EXPECTED_V39_ARTIFACT_SHA == canonical_json_sha256(artifact_core)
            and validate_v39_artifact(artifact).get("valid") is True
        )
        decisions = artifact.get("decisions") or {}
        semantic_checks["v39_decision"] = bool(
            decisions.get("overall") == expected.get("expected_v39_decision")
            and decisions.get("budget_decision") == expected.get("required_v39_budget_decision")
            and decisions.get("next_falsifiable_gate") == expected.get("required_v39_next_gate")
        )
    except Exception as exc:
        semantic_checks["v39_artifact"] = False
        semantic_checks["v39_decision"] = False
        errors.append(f"V3.9 artifact validation failed: {exc}")

    try:
        parent_spec = _read_json_strict(paths["v39_spec"])
        parent_spec_core = {key: value for key, value in parent_spec.items() if key not in {"v39_spec_sha", "v39_spec_sha256"}}
        semantic_checks["v39_spec"] = parent_spec.get("v39_spec_sha256") == EXPECTED_V39_SPEC_SHA == canonical_json_sha256(parent_spec_core)
    except Exception as exc:
        semantic_checks["v39_spec"] = False
        errors.append(f"V3.9 spec validation failed: {exc}")

    try:
        freeze = _read_json_strict(paths["v39_freeze"])
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        semantic_checks["v39_freeze"] = freeze.get("freeze_contract_sha256") == EXPECTED_V39_FREEZE_SHA == canonical_json_sha256(freeze_core)
        frozen = freeze.get("frozen_files") or {}
        immutable_checks = {
            relative: raw_file_sha256(paths["root"] / relative) == digest
            for relative, digest in frozen.items()
            if relative not in V39_MUTABLE_SUCCESSOR_PATHS
        }
        semantic_checks["v39_immutable_files"] = len(immutable_checks) == 127 and all(immutable_checks.values())
    except Exception as exc:
        semantic_checks["v39_freeze"] = False
        semantic_checks["v39_immutable_files"] = False
        errors.append(f"V3.9 freeze validation failed: {exc}")

    try:
        v31 = _read_json_strict(paths["v31"])
        semantic_checks["v31_dyadic"] = v31.get("dyadic_oracle_sha") == EXPECTED_V31_SHA and len(v31.get("seed_certificates") or []) == 8
    except Exception as exc:
        semantic_checks["v31_dyadic"] = False
        errors.append(f"V3.1 dyadic validation failed: {exc}")

    for name, valid in semantic_checks.items():
        if not valid:
            errors.append(f"Parent semantic authentication failed: {name}")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "raw_checks": {
            name: {"actual": actual_raw.get(name), "expected": registered, "valid": actual_raw.get(name) == registered}
            for name, registered in expected_raw.items()
        },
        "semantic_checks": semantic_checks,
        "immutable_v39_files_checked": 127,
    }


def _certificates_and_witnesses(root: str | Path | None = None) -> tuple[dict[int, dict[str, Any]], dict[int, tuple[int, ...]]]:
    paths = _paths(root)
    dyadic = _read_json_strict(paths["v31"])
    witness_spec = _read_json_strict(paths["witness_spec"])
    certificates = {int(row["seed"]): row for row in dyadic["seed_certificates"]}
    raw_witnesses = (witness_spec.get("authenticated_v33_witnesses") or {}).get("bits_by_seed") or {}
    witnesses = {int(seed): tuple(int(value) for value in bits) for seed, bits in raw_witnesses.items()}
    if tuple(certificates) != SEEDS or set(witnesses) != set(SEEDS):
        raise ValueError("Frozen seed certificate or witness order mismatch.")
    for seed in SEEDS:
        if len(witnesses[seed]) != N or sum(witnesses[seed]) != K:
            raise ValueError(f"Invalid authenticated witness for seed {seed}.")
    return certificates, witnesses


def _engine_input(certificate: Mapping[str, Any], witness: Sequence[int]) -> str:
    witness_mask = sum(int(value) << index for index, value in enumerate(witness))
    lines = [f"QLV40 {int(certificate['seed'])} {witness_mask:x}"]
    for group in certificate.get("group_bands") or []:
        mask = sum(1 << int(index) for index in group["indices"])
        lines.append(f"{mask:x} {int(group['lower'])} {int(group['upper'])}")
    for factor in certificate.get("factor_bands") or []:
        values = [factor["lower_int"], factor["upper_int"], *factor["coefficients_int"]]
        lines.append(" ".join(str(int(value)) for value in values))
    return "\n".join(lines) + "\n"


def compile_connectivity_engine(
    destination: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    paths = _paths(root)
    if raw_file_sha256(paths["engine"]) != EXPECTED_ENGINE_RAW:
        raise ValueError("V4.0 connectivity engine source identity mismatch.")
    compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("No C++17 compiler is available for the confirmatory protocol.")
    target = Path(destination)
    command = [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic", str(paths["engine"]), "-o", str(target)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError(f"Connectivity engine compilation failed: {completed.stderr.strip()}")
    if completed.stderr.strip():
        raise RuntimeError(f"Connectivity engine compilation emitted diagnostics: {completed.stderr.strip()}")
    return {
        "compiler": Path(compiler).name,
        "command_flags": command[1:-2],
        "binary_sha256": raw_file_sha256(target),
    }


def _run_engine(binary: Path, mode: int, payload: str, *, timeout_seconds: int = 900) -> dict[str, Any]:
    completed = subprocess.run(
        [str(binary), str(mode)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Connectivity engine mode {mode} failed: {completed.stderr.strip()}")
    result = json.loads(completed.stdout, object_pairs_hook=_reject_duplicates, parse_constant=_reject_nonfinite)
    if not isinstance(result, dict) or int(result.get("seed", -1)) not in SEEDS:
        raise ValueError("Connectivity engine emitted an invalid result.")
    return result


def run_confirmatory_protocol(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v40_spec(root=base)
    parent = authenticate_parent_chain(root=base)
    if not parent["valid"]:
        raise ValueError(f"V3.9 parent authentication failed: {parent['errors']}")
    certificates, witnesses = _certificates_and_witnesses(base)
    equality_fields = tuple(spec["connectivity_protocol"]["replay_equality_fields"])
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="quantum-v40-connectivity-") as temporary:
        binary = Path(temporary) / "v40_connectivity_engine"
        build = compile_connectivity_engine(binary, root=base)
        for seed in SEEDS:
            if progress is not None:
                progress(f"V4.0 exact connectivity · seed {seed} · primary")
            engine_payload = _engine_input(certificates[seed], witnesses[seed])
            primary = _run_engine(binary, 0, engine_payload)
            if progress is not None:
                progress(f"V4.0 exact connectivity · seed {seed} · structural replay")
            replay = _run_engine(binary, 1, engine_payload)
            mismatches = [field for field in equality_fields if primary.get(field) != replay.get(field)]
            rows.append({"seed": seed, "primary": primary, "replay": replay, "replay_mismatches": mismatches})
    return {
        "protocol_version": V40_VERSION,
        "spec_sha256": spec["v40_spec_sha256"],
        "parent": parent,
        "engine_build": build,
        "rows": rows,
        "all_replays_match": all(not row["replay_mismatches"] for row in rows),
    }


def _constraint_rows(certificate: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for group in certificate.get("group_bands") or []:
        members = {int(index) for index in group["indices"]}
        rows.append({
            "name": str(group["name"]),
            "lower": int(group["lower"]),
            "upper": int(group["upper"]),
            "coefficients": tuple(1 if index in members else 0 for index in range(N)),
        })
    for factor in certificate.get("factor_bands") or []:
        rows.append({
            "name": str(factor["name"]),
            "lower": int(factor["lower_int"]),
            "upper": int(factor["upper_int"]),
            "coefficients": tuple(int(value) for value in factor["coefficients_int"]),
        })
    if len(rows) != 7:
        raise ValueError("Expected exactly seven constraint rows.")
    return tuple(rows)


def _mask_indices(mask: int) -> list[int]:
    return [index for index in range(N) if (mask >> index) & 1]


def _constraint_values(mask: int, rows: Sequence[Mapping[str, Any]]) -> list[int]:
    selected = _mask_indices(mask)
    return [sum(int(row["coefficients"][index]) for index in selected) for row in rows]


def build_isolated_counterexample(certificate: Mapping[str, Any], mask_hex: str) -> dict[str, Any]:
    mask = int(mask_hex, 16)
    rows = _constraint_rows(certificate)
    selected = _mask_indices(mask)
    unselected = [index for index in range(N) if index not in set(selected)]
    values = _constraint_values(mask, rows)
    feasible = len(selected) == K and all(int(row["lower"]) <= value <= int(row["upper"]) for row, value in zip(rows, values))
    ledger: list[dict[str, Any]] = []
    first_failure_counts = {str(row["name"]): 0 for row in rows}
    feasible_neighbors = 0
    for removed in selected:
        for added in unselected:
            candidate = mask ^ (1 << removed) ^ (1 << added)
            candidate_values = [
                values[index] - int(row["coefficients"][removed]) + int(row["coefficients"][added])
                for index, row in enumerate(rows)
            ]
            failures = [
                str(row["name"])
                for row, value in zip(rows, candidate_values)
                if value < int(row["lower"]) or value > int(row["upper"])
            ]
            if not failures:
                feasible_neighbors += 1
            else:
                first_failure_counts[failures[0]] += 1
            ledger.append({
                "added": added,
                "candidate_mask_hex": f"{candidate:010x}",
                "failing_rows": failures,
                "removed": removed,
            })
    core = {
        "all_neighbors_rejected": feasible_neighbors == 0,
        "audit_universe": K * (N - K),
        "exact_constraint_values": {str(row["name"]): value for row, value in zip(rows, values)},
        "feasible_neighbor_count": feasible_neighbors,
        "first_failure_counts": first_failure_counts,
        "mask_hex": f"{mask:010x}",
        "neighbor_ledger_sha256": canonical_json_sha256(ledger),
        "neighbors_audited": len(ledger),
        "selected_indices": selected,
        "vertex_exactly_feasible": feasible,
    }
    return {**core, "counterexample_sha256": canonical_json_sha256(core)}


def _certificate_by_seed(root: str | Path | None = None) -> dict[int, dict[str, Any]]:
    return _certificates_and_witnesses(root)[0]


def build_v40_artifact(
    protocol: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v40_spec(root=base)
    parent = authenticate_parent_chain(root=base)
    if not parent["valid"] or protocol.get("all_replays_match") is not True:
        raise ValueError("V4.0 confirmatory protocol is not admissible.")
    protocol_rows = list(protocol.get("rows") or [])
    if [int(row.get("seed", -1)) for row in protocol_rows] != list(SEEDS):
        raise ValueError("V4.0 protocol seed order is incomplete.")
    certificates = _certificate_by_seed(base)
    stable_fields = tuple(spec["connectivity_protocol"]["replay_equality_fields"])
    graph_definition_sha = canonical_json_sha256({
        "candidate_family": spec["candidate_family"],
        "connectivity_protocol": spec["connectivity_protocol"],
        "parent_dyadic_raw": EXPECTED_V31_RAW,
    })
    seed_rows: list[dict[str, Any]] = []
    for protocol_row in protocol_rows:
        seed = int(protocol_row["seed"])
        primary = dict(protocol_row["primary"])
        replay = dict(protocol_row["replay"])
        mismatches = [field for field in stable_fields if primary.get(field) != replay.get(field)]
        if mismatches:
            raise ValueError(f"Seed {seed} replay mismatch: {mismatches}")
        components = copy.deepcopy(primary["component_representatives"])
        isolated: list[dict[str, Any]] = []
        for component in components:
            mask = int(component["mask_hex"], 16)
            component["selected_indices"] = _mask_indices(mask)
            component["representative_sha256"] = canonical_json_sha256({
                "mask_hex": component["mask_hex"],
                "selected_indices": component["selected_indices"],
                "size": int(component["size"]),
            })
            if int(component["size"]) == 1:
                isolated.append(build_isolated_counterexample(certificates[seed], component["mask_hex"]))
        component_count = int(primary["component_count"])
        certificate_kind = "CONNECTED_CERTIFICATE" if component_count == 1 else "DISCONNECTED_COUNTEREXAMPLE"
        row_core = {
            "certificate_kind": certificate_kind,
            "component_assignment_sha256": primary["component_assignment_sha256"],
            "component_count": component_count,
            "component_representatives": components,
            "core_index_sha256": primary["core_index_sha256"],
            "coverage_complete": bool(primary["coverage_complete"]),
            "decision": "CONNECTED" if component_count == 1 else "DISCONNECTED",
            "distinct_nine_cores": int(primary["distinct_nine_cores"]),
            "enumeration_sha256": primary["enumeration_sha256"],
            "exact_state_graph_edge_count": int(primary["exact_state_graph_edge_count"]),
            "expected_nine_core_incidences": int(primary["feasible_vertex_count"]) * K,
            "feasible_vertex_count": int(primary["feasible_vertex_count"]),
            "forest_sha256": primary["forest_sha256"],
            "graph_definition_sha256": graph_definition_sha,
            "group_candidate_count": int(primary["group_candidate_count"]),
            "incidence_invariant_valid": bool(primary["incidence_invariant_valid"]),
            "instance_id": str(certificates[seed]["instance_id"]),
            "isolated_counterexamples": isolated,
            "largest_component_size": int(primary["largest_component_size"]),
            "method": primary["algorithm"],
            "observed_nine_core_incidences": int(primary["observed_nine_core_incidences"]),
            "parent_certificate_sha": str(certificates[seed]["certificate_sha"]),
            "primary_enumerator": {
                "group_order": list(primary["group_order"]),
                "primary_factor": int(primary["primary_factor"]),
                "primary_interval_candidate_count": int(primary["primary_interval_candidate_count"]),
            },
            "replay": {
                "all_stable_fields_match": not mismatches,
                "group_order": list(replay["group_order"]),
                "mismatched_fields": mismatches,
                "primary_factor": int(replay["primary_factor"]),
                "primary_interval_candidate_count": int(replay["primary_interval_candidate_count"]),
            },
            "seed": seed,
            "smallest_component_size": int(primary["smallest_component_size"]),
            "successful_unions": int(primary["successful_unions"]),
            "union_attempts": int(primary["union_attempts"]),
            "union_forest_invariant_valid": bool(primary["union_forest_invariant_valid"]),
            "witness_mask_hex": str(primary["witness_mask_hex"]),
        }
        seed_rows.append({**row_core, "seed_evidence_sha256": canonical_json_sha256(row_core)})

    disconnected = [row for row in seed_rows if row["decision"] == "DISCONNECTED"]
    complete = all(
        row["coverage_complete"]
        and row["incidence_invariant_valid"]
        and row["union_forest_invariant_valid"]
        and row["replay"]["all_stable_fields_match"]
        for row in seed_rows
    )
    if disconnected and complete:
        connectivity_decision = "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE"
        production = "REJECTED_CONNECTIVITY_AND_V39_RESOURCE_ARCHITECTURE"
        overall = "V40_GLOBAL_CONNECTIVITY_COUNTEREXAMPLE_RESOURCE_REDESIGN_PREREGISTERED"
        next_gate = "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE"
    elif complete:
        connectivity_decision = "GLOBAL_FEASIBLE_GRAPH_CONNECTED_ALL_SEEDS"
        production = "REJECTED_V39_RESOURCE_ARCHITECTURE"
        overall = "V40_GLOBAL_CONNECTIVITY_CERTIFIED_V39_RESOURCE_ARCHITECTURE_REJECTED"
        next_gate = "EXECUTE_PREREGISTERED_V41_RESOURCE_REDESIGN"
    else:
        connectivity_decision = "GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_INDETERMINATE"
        production = "BLOCKED_CONNECTIVITY_AND_REJECTED_V39_RESOURCE_ARCHITECTURE"
        overall = "V40_CONNECTIVITY_EVIDENCE_INCOMPLETE"
        next_gate = "COMPLETE_DUAL_CONNECTIVITY_REPLAY"

    aggregate = {
        "all_eight_seeds_complete": complete and len(seed_rows) == len(SEEDS),
        "connected_seed_count": len(seed_rows) - len(disconnected),
        "disconnected_seed_count": len(disconnected),
        "disconnected_seeds": [int(row["seed"]) for row in disconnected],
        "isolated_component_count": sum(len(row["isolated_counterexamples"]) for row in seed_rows),
        "maximum_component_count": max(int(row["component_count"]) for row in seed_rows),
        "total_distinct_nine_cores": sum(int(row["distinct_nine_cores"]) for row in seed_rows),
        "total_exact_state_graph_edges": sum(int(row["exact_state_graph_edge_count"]) for row in seed_rows),
        "total_feasible_vertices": sum(int(row["feasible_vertex_count"]) for row in seed_rows),
        "total_nine_core_incidences": sum(int(row["observed_nine_core_incidences"]) for row in seed_rows),
        "total_successful_unions": sum(int(row["successful_unions"]) for row in seed_rows),
    }
    counterexample_bundle = [
        {"counterexamples": row["isolated_counterexamples"], "seed": row["seed"]}
        for row in seed_rows if row["isolated_counterexamples"]
    ]
    artifact = {
        "aggregate_evidence": aggregate,
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "connectivity_evidence": {
            "certificate_kind": "DISCONNECTED_COUNTEREXAMPLE" if disconnected else "CONNECTED_CERTIFICATE",
            "counterexample_bundle_sha256": canonical_json_sha256(counterexample_bundle),
            "graph_definition": copy.deepcopy(spec["connectivity_protocol"]["graph_definition"]),
            "graph_definition_sha256": graph_definition_sha,
            "method": spec["connectivity_protocol"]["engine_algorithm"],
            "seed_rows": seed_rows,
        },
        "decisions": {
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "global_connectivity_decision": connectivity_decision,
            "next_falsifiable_gate": next_gate,
            "overall": overall,
            "production_admission": production,
            "resource_architecture_decision": "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED",
        },
        "engine_source_raw_file_sha256": raw_file_sha256(_paths(base)["engine"]),
        "parent": {
            "authentication": parent,
            "v31_dyadic_oracle_sha": EXPECTED_V31_SHA,
            "v31_raw_file_sha256": EXPECTED_V31_RAW,
            "v39_artifact_raw_file_sha256": EXPECTED_V39_ARTIFACT_RAW,
            "v39_artifact_sha256": EXPECTED_V39_ARTIFACT_SHA,
            "v39_freeze_raw_file_sha256": EXPECTED_V39_FREEZE_RAW,
            "v39_freeze_sha256": EXPECTED_V39_FREEZE_SHA,
        },
        "research_classification": "RESEARCH_ONLY",
        "resource_redesign": copy.deepcopy(spec["resource_redesign_preregistration"]),
        "source_sha256": source_sha256(),
        "spec_raw_file_sha256": raw_file_sha256(_paths(base)["spec"]),
        "spec_sha256": spec["v40_spec_sha256"],
        "v39_resource_rejection": {
            "budget_cnot": 2_500_000,
            "budget_decision": "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
            "maximum_selected_model_cnot": 781_332_180,
            "minimum_budget_margin_cnot": -778_832_180,
            "preserved": True,
        },
        "v40_version": V40_VERSION,
    }
    artifact["artifact_sha256"] = canonical_json_sha256(artifact)
    return artifact


def validate_v40_artifact(
    payload: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        spec = load_v40_spec(root=root)
    except Exception as exc:
        return {"valid": False, "errors": [str(exc)], "checks": {}}
    core = {key: copy.deepcopy(value) for key, value in payload.items() if key != "artifact_sha256"}
    checks: dict[str, bool] = {
        "artifact_self_hash": payload.get("artifact_sha256") == canonical_json_sha256(core),
        "artifact_version": payload.get("artifact_version") == ARTIFACT_VERSION,
        "spec_identity": payload.get("spec_sha256") == spec.get("v40_spec_sha256"),
        "engine_identity": payload.get("engine_source_raw_file_sha256") == EXPECTED_ENGINE_RAW,
        "research_only": payload.get("research_classification") == "RESEARCH_ONLY",
    }
    evidence = payload.get("connectivity_evidence") or {}
    rows = evidence.get("seed_rows") or []
    checks["seed_order"] = [row.get("seed") for row in rows] == list(SEEDS)
    checks["graph_definition_identity"] = evidence.get("graph_definition_sha256") == canonical_json_sha256({
        "candidate_family": spec["candidate_family"],
        "connectivity_protocol": spec["connectivity_protocol"],
        "parent_dyadic_raw": EXPECTED_V31_RAW,
    })
    row_checks: list[bool] = []
    counterexample_bundle: list[dict[str, Any]] = []
    try:
        certificates = _certificate_by_seed(root)
    except Exception as exc:
        certificates = {}
        errors.append(f"Unable to load certificates: {exc}")
    for row in rows:
        seed = int(row.get("seed", -1))
        row_core = {key: copy.deepcopy(value) for key, value in row.items() if key != "seed_evidence_sha256"}
        valid = row.get("seed_evidence_sha256") == canonical_json_sha256(row_core)
        vertices = int(row.get("feasible_vertex_count", -1))
        components = int(row.get("component_count", -1))
        valid = valid and vertices > 0 and components > 0
        valid = valid and row.get("coverage_complete") is True
        valid = valid and row.get("observed_nine_core_incidences") == vertices * K
        valid = valid and row.get("expected_nine_core_incidences") == vertices * K
        valid = valid and row.get("successful_unions") + components == vertices
        valid = valid and row.get("incidence_invariant_valid") is True and row.get("union_forest_invariant_valid") is True
        valid = valid and (row.get("replay") or {}).get("all_stable_fields_match") is True
        valid = valid and len(row.get("component_representatives") or []) == components
        expected_kind = "CONNECTED_CERTIFICATE" if components == 1 else "DISCONNECTED_COUNTEREXAMPLE"
        valid = valid and row.get("certificate_kind") == expected_kind
        rebuilt_counterexamples: list[dict[str, Any]] = []
        if seed in certificates:
            for component in row.get("component_representatives") or []:
                mask = int(str(component.get("mask_hex", "-1")), 16)
                component_core = {
                    "mask_hex": component.get("mask_hex"),
                    "selected_indices": _mask_indices(mask),
                    "size": int(component.get("size", -1)),
                }
                valid = valid and component.get("selected_indices") == component_core["selected_indices"]
                valid = valid and component.get("representative_sha256") == canonical_json_sha256(component_core)
                if int(component.get("size", -1)) == 1:
                    rebuilt_counterexamples.append(build_isolated_counterexample(certificates[seed], str(component["mask_hex"])))
            valid = valid and row.get("isolated_counterexamples") == rebuilt_counterexamples
        row_checks.append(bool(valid))
        if row.get("isolated_counterexamples"):
            counterexample_bundle.append({"counterexamples": row["isolated_counterexamples"], "seed": seed})
    checks["all_seed_certificates"] = len(row_checks) == len(SEEDS) and all(row_checks)
    checks["counterexample_bundle"] = evidence.get("counterexample_bundle_sha256") == canonical_json_sha256(counterexample_bundle)

    aggregate = payload.get("aggregate_evidence") or {}
    disconnected_rows = [row for row in rows if row.get("component_count", 0) > 1]
    expected_aggregate = {
        "all_eight_seeds_complete": len(rows) == len(SEEDS) and all(row.get("coverage_complete") is True for row in rows),
        "connected_seed_count": len(rows) - len(disconnected_rows),
        "disconnected_seed_count": len(disconnected_rows),
        "disconnected_seeds": [int(row["seed"]) for row in disconnected_rows],
        "isolated_component_count": sum(len(row.get("isolated_counterexamples") or []) for row in rows),
        "maximum_component_count": max((int(row.get("component_count", 0)) for row in rows), default=0),
        "total_distinct_nine_cores": sum(int(row.get("distinct_nine_cores", 0)) for row in rows),
        "total_exact_state_graph_edges": sum(int(row.get("exact_state_graph_edge_count", 0)) for row in rows),
        "total_feasible_vertices": sum(int(row.get("feasible_vertex_count", 0)) for row in rows),
        "total_nine_core_incidences": sum(int(row.get("observed_nine_core_incidences", 0)) for row in rows),
        "total_successful_unions": sum(int(row.get("successful_unions", 0)) for row in rows),
    }
    checks["aggregate_recomputed"] = aggregate == expected_aggregate
    decisions = payload.get("decisions") or {}
    expected_connectivity = (
        "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE"
        if disconnected_rows and expected_aggregate["all_eight_seeds_complete"]
        else "GLOBAL_FEASIBLE_GRAPH_CONNECTED_ALL_SEEDS"
        if expected_aggregate["all_eight_seeds_complete"]
        else "GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_INDETERMINATE"
    )
    checks["connectivity_decision_recomputed"] = decisions.get("global_connectivity_decision") == expected_connectivity
    checks["resource_redesign_not_evaluated"] = bool(
        decisions.get("resource_architecture_decision") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and (payload.get("resource_redesign") or {}).get("status") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED"
        and ((payload.get("resource_redesign") or {}).get("result_fields") or {}).get("cnot") == "NOT_EVALUATED"
    )
    v39 = payload.get("v39_resource_rejection") or {}
    checks["v39_rejection_preserved"] = bool(
        v39.get("preserved") is True
        and v39.get("budget_decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
        and v39.get("maximum_selected_model_cnot") == 781_332_180
    )
    boundary = payload.get("claim_boundary") or {}
    checks["provider_hardware_boundary"] = bool(
        boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    )
    if authenticate_parent:
        parent = authenticate_parent_chain(root=root)
        checks["parent_chain"] = parent.get("valid") is True and (payload.get("parent") or {}).get("authentication", {}).get("valid") is True
        if not parent.get("valid"):
            errors.extend(parent.get("errors") or [])
    failed = [name for name, value in checks.items() if value is not True]
    return {"valid": not failed and not errors, "checks": checks, "failed_checks": failed, "errors": list(dict.fromkeys(errors))}


def default_v40_artifact_path(*, root: str | Path | None = None) -> Path:
    return _root(root) / "outputs" / "quantum_phase3" / "v40_connectivity" / DEFAULT_ARTIFACT_NAME


def seal_v40_artifact(
    protocol: Mapping[str, Any],
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v40_artifact_path(root=root)
    payload = build_v40_artifact(protocol, root=root)
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V4.0 artifact: {target}")
        return {"created": False, "path": str(target), "artifact": payload}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded, encoding="utf-8")
    return {"created": True, "path": str(target), "artifact": payload}


def load_v40_artifact(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v40_artifact_path(root=root)
    payload = _read_json_strict(target)
    return payload, validate_v40_artifact(payload, root=root)


__all__ = [
    "ARTIFACT_VERSION",
    "DEFAULT_ARTIFACT_NAME",
    "K",
    "N",
    "SEEDS",
    "V40_VERSION",
    "authenticate_parent_chain",
    "build_isolated_counterexample",
    "build_v40_artifact",
    "canonical_json_sha256",
    "compile_connectivity_engine",
    "default_v40_artifact_path",
    "load_v40_artifact",
    "load_v40_spec",
    "run_confirmatory_protocol",
    "seal_v40_artifact",
    "validate_v40_artifact",
]
