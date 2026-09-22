"""Fail-closed institutional surface for Quantum Lab V4.3.

The panel authenticates and renders an already-sealed provider-neutral
elementary-circuit artifact.  It never rebuilds a stream, imports a provider
SDK, reads credentials, selects a backend, transpiles, or submits work.  The
accepted result is deliberately narrow: exact finite controls pass on the
registered promise subspace, while the mandatory off-promise counterexample is
retained as a rejection witness rather than hidden behind a global-cleanup
claim.
"""

from __future__ import annotations

import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st


SectionHeader = Callable[[str, str, str], None]

EXPECTED_V43_ARTIFACT_SHA256 = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"
EXPECTED_V43_ARTIFACT_RAW_SHA256 = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_V43_SPEC_SHA256 = "71f6d1f642a6d6a1e99d9d265e6cba914302ea9763a854a13cf4aa0b95d8cf5f"
EXPECTED_V43_SPEC_RAW_SHA256 = "ad8904557e850b8850e11ccc410fa3bb44cc15947cf06d7bdee7047f24563226"
EXPECTED_V43_SOURCE_RAW_SHA256 = "d4dc129721dd7a4429aa473658272fef26f5c90831ecb3d125a730246309838d"
EXPECTED_V43_SIMULATOR_RAW_SHA256 = "420761883ce82825c9a1d01ec55cf116d69f4a80f946dc6c5a8e6c002e61f7e7"

EXPECTED_V42_ARTIFACT_SHA256 = "f2f294f8f0a21804d7dd6a23d7695b161723fcc1efea48b2f9d1ce7bcbb3f5be"
EXPECTED_V42_ARTIFACT_RAW_SHA256 = "0952111064db57f6c1122e9a7b4d45ee997667e0d57137ea173be0009ba4feec"
EXPECTED_V42_SPEC_SHA256 = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_V42_SPEC_RAW_SHA256 = "11b9d7a86fc1617f7c313c2cda58c4b8874d33cb9e4fe11460a65b8920e40674"
EXPECTED_V42_FREEZE_SHA256 = "36ebd4acedb1563227324b56ab6731293d38935c2c888f37c33029858a0f3068"
EXPECTED_V42_FREEZE_RAW_SHA256 = "faf9250d6f76acdeb2644d52a45c7ae1d8930b3f4c7367ca6ba3861e063371c5"
EXPECTED_V42_PATH_FINGERPRINT = "cc3dd736d2475cfc1d143bc720fc37863d62ede26019a3aa99cd33e96643b166"
V42_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})

EXPECTED_SEEDS = [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
EXPECTED_BASIS = ["X", "H", "T", "TDG", "RY", "RZ", "CX"]
EXPECTED_TOTAL_INSTRUCTIONS = 21_925_902
EXPECTED_MAXIMUM_CX = 1_158_046
EXPECTED_MINIMUM_MARGIN = 1_341_954
EXPECTED_MAXIMUM_QUBITS = 339
EXPECTED_ARITHMETIC_CASES = 107_520
EXPECTED_PROMISE_CASES = 64
EXPECTED_PROMISE_ROUNDTRIPS = 64
EXPECTED_OFF_PROMISE_STATUS = "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS"
EXPECTED_OVERALL = "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED"
EXPECTED_PRODUCTION = "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED"
EXPECTED_PROMISE_SCOPE = "ACCEPTED_ONLY_FOR_EXACT_FEASIBLE_N40_DATA_AND_TWO_ONE_HOT_COIN_REGISTERS"
EXPECTED_NEXT_GATE = "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _fmt(value: Any, *, signed: bool = False) -> str:
    if isinstance(value, bool) or value is None:
        return "MASKED"
    try:
        numeric = int(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)
    prefix = "+" if signed and numeric >= 0 else ""
    return f"{prefix}{numeric:,}"


def _short_sha(value: Any) -> str:
    text = str(value or "")
    return f"{text[:12]}…{text[-8:]}" if len(text) == 64 else "MASKED"


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _strict_json(raw: bytes) -> dict[str, Any]:
    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError("V4.3 evidence must be a JSON object.")
    return payload


def _canonical_sha(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _path_fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def default_v43_ui_artifact_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "v43_reversible_circuit"
        / "SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json"
    )


def _scientific_validation_context() -> tuple[str, list[str]]:
    """Authenticate the V4.3 sources and V4.2's 175 immutable paths."""

    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []
    registered: dict[str, str] = {
        "quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json": EXPECTED_V43_SPEC_RAW_SHA256,
        "quantum_research_lab/phase3_v43_reversible_circuit_ir.py": EXPECTED_V43_SOURCE_RAW_SHA256,
        "quantum_research_lab/phase3_v43_reversible_simulator.cpp": EXPECTED_V43_SIMULATOR_RAW_SHA256,
        "FREEZE_CONTRACT_V4_2.json": EXPECTED_V42_FREEZE_RAW_SHA256,
    }
    freeze_path = root / "FREEZE_CONTRACT_V4_2.json"
    try:
        freeze_raw = freeze_path.read_bytes()
        if hashlib.sha256(freeze_raw).hexdigest() != EXPECTED_V42_FREEZE_RAW_SHA256:
            raise ValueError("V4.2 freeze raw identity mismatch.")
        freeze = _strict_json(freeze_raw)
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        frozen = freeze.get("frozen_files")
        if not isinstance(frozen, Mapping):
            raise ValueError("V4.2 frozen_files is not an object.")
        if not (
            len(frozen) == 177
            and freeze.get("frozen_file_count") == 177
            and freeze.get("freeze_contract_sha256") == EXPECTED_V42_FREEZE_SHA256
            and _canonical_sha(freeze_core) == EXPECTED_V42_FREEZE_SHA256
            and freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V42_PATH_FINGERPRINT
            and _path_fingerprint(frozen) == EXPECTED_V42_PATH_FINGERPRINT
        ):
            raise ValueError("V4.2 freeze semantic identity or 177-path inventory mismatch.")
        immutable = {
            str(relative): str(expected)
            for relative, expected in frozen.items()
            if str(relative) not in V42_SUCCESSOR_MUTABLE
        }
        if len(immutable) != 175:
            raise ValueError("V4.3 successor must authenticate exactly 175 V4.2 paths.")
        registered.update(immutable)
    except Exception as exc:
        errors.append(f"Unable to bind V4.3 UI to V4.2 freeze: {exc}")

    digest = hashlib.sha256()
    for relative, expected in sorted(registered.items()):
        digest.update(relative.encode("utf-8") + b"\0")
        try:
            unresolved = root / relative
            if unresolved.is_symlink():
                raise ValueError("symbolic link rejected")
            candidate = unresolved.resolve(strict=True)
            candidate.relative_to(root)
            if not candidate.is_file():
                raise ValueError("not a regular non-symlink file")
            actual = _raw_sha(candidate)
        except Exception as exc:
            actual = ""
            errors.append(f"Unable to authenticate {relative}: {exc}")
        if actual != expected:
            errors.append(f"Immutable scientific dependency mismatch: {relative}")
        digest.update(actual.encode("ascii") + b"\n")

    # Semantic checks keep a valid raw byte sequence from being mistaken for a
    # different registered scientific meaning.
    try:
        spec = _strict_json(
            (root / "quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json").read_bytes()
        )
        spec_core = {key: value for key, value in spec.items() if key not in {"v43_spec_sha", "v43_spec_sha256"}}
        if not (
            spec.get("v43_spec_sha256") == EXPECTED_V43_SPEC_SHA256
            and _canonical_sha(spec_core) == EXPECTED_V43_SPEC_SHA256
        ):
            errors.append("V4.3 specification semantic identity mismatch.")
    except Exception as exc:
        errors.append(f"Unable to authenticate V4.3 specification semantics: {exc}")
    try:
        parent_artifact = _strict_json(
            (root / "outputs/quantum_phase3/v42_coined_walk/SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json").read_bytes()
        )
        parent_core = {key: value for key, value in parent_artifact.items() if key != "artifact_sha256"}
        if not (
            parent_artifact.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA256
            and _canonical_sha(parent_core) == EXPECTED_V42_ARTIFACT_SHA256
        ):
            errors.append("V4.2 parent artifact semantic identity mismatch.")
    except Exception as exc:
        errors.append(f"Unable to authenticate V4.2 parent artifact semantics: {exc}")
    return digest.hexdigest(), list(dict.fromkeys(errors))


def _self_hashed(row: Mapping[str, Any], field: str) -> bool:
    return row.get(field) == _canonical_sha({key: value for key, value in row.items() if key != field})


@st.cache_data(show_spinner=False, max_entries=8)
def _cached_artifact_validation(raw_artifact: bytes, context_sha256: str) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        payload = _strict_json(raw_artifact)
        aggregate = _mapping(payload.get("aggregate"))
        boundary = _mapping(payload.get("claim_boundary"))
        decisions = _mapping(payload.get("decisions"))
        simulator = _mapping(payload.get("independent_cpp_simulator"))
        simulator_counts = _mapping(simulator.get("pass_counts"))
        simulator_negative = _mapping(simulator.get("negative_control"))
        negative = _mapping(payload.get("mandatory_off_promise_control"))
        parent = _mapping(payload.get("parent"))
        parameter = _mapping(payload.get("parameter_contract"))
        amendments = _mapping(payload.get("protocol_amendments"))
        rows = _rows(payload.get("seed_materializations"))
        stream_rows = [_mapping(row.get("stream_manifest")) for row in rows]
        register_rows = [_mapping(row.get("register_layout")) for row in rows]

        checks = {
            "artifact_raw_identity": hashlib.sha256(raw_artifact).hexdigest() == EXPECTED_V43_ARTIFACT_RAW_SHA256,
            "artifact_semantic_identity": bool(
                payload.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256
                and _self_hashed(payload, "artifact_sha256")
            ),
            "context_identity": len(context_sha256) == 64,
            "sealed_sources": bool(
                payload.get("spec_sha256") == EXPECTED_V43_SPEC_SHA256
                and payload.get("spec_raw_file_sha256") == EXPECTED_V43_SPEC_RAW_SHA256
                and payload.get("source_raw_file_sha256") == EXPECTED_V43_SOURCE_RAW_SHA256
                and payload.get("simulator_source_raw_file_sha256") == EXPECTED_V43_SIMULATOR_RAW_SHA256
            ),
            "parent_identity": bool(
                parent.get("artifact_sha256") == EXPECTED_V42_ARTIFACT_SHA256
                and parent.get("artifact_raw_file_sha256") == EXPECTED_V42_ARTIFACT_RAW_SHA256
                and parent.get("spec_sha256") == EXPECTED_V42_SPEC_SHA256
                and parent.get("spec_raw_file_sha256") == EXPECTED_V42_SPEC_RAW_SHA256
                and parent.get("freeze_sha256") == EXPECTED_V42_FREEZE_SHA256
                and parent.get("freeze_raw_file_sha256") == EXPECTED_V42_FREEZE_RAW_SHA256
                and parent.get("immutable_file_count") == 175
                and parent.get("immutable_files_exact") is True
                and parent.get("overall_decision") == "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED"
            ),
            "eight_seed_order": [row.get("seed") for row in rows] == EXPECTED_SEEDS,
            "stream_self_hashes": bool(rows) and all(
                _self_hashed(stream, "stream_manifest_sha256") for stream in stream_rows
            ),
            "seed_self_hashes": bool(rows) and all(
                _self_hashed(row, "seed_materialization_sha256") for row in rows
            ),
            "aggregate_self_hash": _self_hashed(aggregate, "aggregate_sha256"),
            "parameter_self_hash": _self_hashed(parameter, "parameter_contract_sha256"),
            "ordered_roots": bool(
                aggregate.get("ordered_stream_manifest_root_sha256")
                == _canonical_sha([stream.get("stream_manifest_sha256") for stream in stream_rows])
                and aggregate.get("register_map_root_sha256")
                == _canonical_sha([register.get("register_map_sha256") for register in register_rows])
            ),
            "elementary_stream_contract": bool(
                all(stream.get("basis") == EXPECTED_BASIS for stream in stream_rows)
                and all(stream.get("seed") == row.get("seed") for row, stream in zip(rows, stream_rows))
                and all(stream.get("chunk_instruction_limit") == 8192 for stream in stream_rows)
                and sum(int(stream.get("instruction_count", -1)) for stream in stream_rows)
                == EXPECTED_TOTAL_INSTRUCTIONS
                and aggregate.get("total_elementary_instructions") == EXPECTED_TOTAL_INSTRUCTIONS
            ),
            "resource_gate": bool(
                aggregate.get("seed_count") == 8
                and aggregate.get("budget_cnot") == 2_500_000
                and aggregate.get("maximum_materialized_cnot") == EXPECTED_MAXIMUM_CX
                and aggregate.get("minimum_budget_margin_cnot") == EXPECTED_MINIMUM_MARGIN
                and aggregate.get("maximum_logical_qubits_with_recycled_workspace") == EXPECTED_MAXIMUM_QUBITS
                and aggregate.get("all_eight_seeds_budget_admitted") is True
                and max(int(_mapping(stream.get("elementary_counts")).get("CX", -1)) for stream in stream_rows)
                == EXPECTED_MAXIMUM_CX
                and min(int(row.get("budget_margin_cnot", -1)) for row in rows) == EXPECTED_MINIMUM_MARGIN
                and max(int(register.get("total_qubits", -1)) for register in register_rows) == EXPECTED_MAXIMUM_QUBITS
                and all(row.get("decision") == "PASSED" for row in rows)
            ),
            "replay_and_liveness": bool(
                all(
                    _mapping(row.get("preregistered_cnot_replay")).get("match") is True
                    and _mapping(row.get("preregistered_cnot_replay")).get("actual")
                    == _mapping(stream.get("elementary_counts")).get("CX")
                    and _mapping(row.get("preregistered_qubit_replay")).get("match") is True
                    and _mapping(row.get("preregistered_qubit_replay")).get("actual") == register.get("total_qubits")
                    and _mapping(row.get("liveness")).get("liveness_decision")
                    == "PASSED_STATIC_DISJOINT_PHASE_AND_CLEAN_EXIT_CONTRACT"
                    and _mapping(row.get("real_n40_promise_select_witness")).get("promise_cleanup_passed") is True
                    and _mapping(row.get("real_n40_promise_select_witness")).get("retained_feasible_flag_after_reverse") == 0
                    for row, stream, register in zip(rows, stream_rows, register_rows)
                )
            ),
            "independent_simulator": bool(
                simulator.get("valid") is True
                and simulator.get("status") == "PASS"
                and simulator.get("failure_count") == 0
                and simulator_counts.get("arithmetic_cases") == EXPECTED_ARITHMETIC_CASES
                and simulator_counts.get("promise_select_cases") == EXPECTED_PROMISE_CASES
                and simulator_counts.get("promise_select_roundtrips") == EXPECTED_PROMISE_ROUNDTRIPS
            ),
            "off_promise_rejected": bool(
                negative.get("status") == EXPECTED_OFF_PROMISE_STATUS
                and negative.get("witness_detected") is True
                and negative.get("retained_feasible_flag_after_reverse") == 1
                and simulator_negative.get("status") == EXPECTED_OFF_PROMISE_STATUS
                and simulator_negative.get("cleanup_accepted") is False
                and simulator_negative.get("retained_feasibility_flag") == 1
            ),
            "append_only_amendments": bool(
                amendments.get("v42_bytes_rewritten") is False
                and amendments.get("v42_cnot_decision_rewritten") is False
                and amendments.get("v42_elementary_basis_omitted_h")
                == "DISCLOSED_AND_CORRECTED_APPEND_ONLY_IN_V43"
                and amendments.get("width_three_to_five")
                == "FOUR_GROUP_BANKS_ZERO_EXTENDED;_22784_CNOT_ADDED_PER_STEP"
                and amendments.get("interval_predicate")
                == "V42_COSTED_TWO_CCX_PER_ROW_ARE_NOT_NEEDED_BY_THE_EXACT_NESTED_GE_XOR_CIRCUIT;_168_CNOT_REMOVED_PER_STEP"
            ),
            "parameter_gate": bool(
                parameter.get("elementary_basis") == EXPECTED_BASIS
                and parameter.get("materialized_minimum_arithmetic_width") == 5
                and parameter.get("coin_theta_pi") == [1, 2]
                and parameter.get("coin_beta_pi") == [0, 1]
                and parameter.get("bridge_theta_pi") == [1, 2]
            ),
            "decision_gate": bool(
                decisions.get("overall") == EXPECTED_OVERALL
                and decisions.get("production_admission") == EXPECTED_PRODUCTION
                and decisions.get("promise_scope") == EXPECTED_PROMISE_SCOPE
                and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE
            ),
            "boundary_gate": bool(
                payload.get("research_classification") == "RESEARCH_ONLY"
                and boundary.get("research_classification") == "RESEARCH_ONLY"
                and boundary.get("provider_sdk_imported") is False
                and boundary.get("provider_credentials_read") is False
                and boundary.get("provider_calls") == 0
                and boundary.get("named_backend_selected") is False
                and boundary.get("qpu_submission_enabled") is False
                and boundary.get("qpu_jobs_submitted") == 0
                and boundary.get("hardware_executable") is False
                and boundary.get("backend_transpilation") == "NOT_RUN"
                and boundary.get("optimization_performance") == "NOT_TESTED"
                and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            ),
        }
    except Exception as exc:
        payload = {}
        errors.append(str(exc))
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "payload": payload,
        "valid": bool(checks) and not errors and not failed,
    }


def load_v43_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load V4.3 evidence without regenerating it or touching any provider."""

    target = Path(path) if path is not None else default_v43_ui_artifact_path()
    try:
        raw = target.read_bytes()
    except OSError as exc:
        return {}, {"valid": False, "errors": [str(exc)], "failed_checks": ["artifact_read"]}
    context_sha, context_errors = _scientific_validation_context()
    report = _cached_artifact_validation(raw, context_sha)
    errors = list(context_errors) + list(report.get("errors") or [])
    failed = list(report.get("failed_checks") or [])
    if context_errors:
        failed.append("immutable_scientific_context")
    return dict(_mapping(report.get("payload"))), {
        "checks": dict(_mapping(report.get("checks"))),
        "context_sha256": context_sha,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": list(dict.fromkeys(failed)),
        "valid": report.get("valid") is True and not context_errors,
    }


def normalize_v43_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
) -> dict[str, Any]:
    source = _mapping(artifact)
    authenticated = bool(
        source
        and artifact_integrity is True
        and spec_integrity is True
        and parent_integrity is True
        and source.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA256
    )
    if not authenticated:
        return {
            "aggregate": {},
            "amendments": {},
            "artifact": {},
            "artifact_sha256": "MASKED",
            "authenticated": False,
            "boundary": {},
            "decisions": {},
            "negative_control": {},
            "next_gate": "V43_EVIDENCE_AUTHENTICATION_REQUIRED",
            "overall": "V43_EVIDENCE_UNAVAILABLE_FAIL_CLOSED",
            "parameter_contract": {},
            "seed_rows": [],
            "simulator": {},
        }
    decisions = _mapping(source.get("decisions"))
    return {
        "aggregate": dict(_mapping(source.get("aggregate"))),
        "amendments": dict(_mapping(source.get("protocol_amendments"))),
        "artifact": dict(source),
        "artifact_sha256": str(source.get("artifact_sha256", "")),
        "authenticated": True,
        "boundary": dict(_mapping(source.get("claim_boundary"))),
        "decisions": dict(decisions),
        "negative_control": dict(_mapping(source.get("mandatory_off_promise_control"))),
        "next_gate": str(decisions.get("next_falsifiable_gate", "")),
        "overall": str(decisions.get("overall", "")),
        "parameter_contract": dict(_mapping(source.get("parameter_contract"))),
        "seed_rows": _rows(source.get("seed_materializations")),
        "simulator": dict(_mapping(source.get("independent_cpp_simulator"))),
    }


def _materialization_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in state.get("seed_rows") or []:
        stream = _mapping(row.get("stream_manifest"))
        counts = _mapping(stream.get("elementary_counts"))
        register = _mapping(row.get("register_layout"))
        chunks = stream.get("chunk_sha256")
        rows.append(
            {
                "Seed": row.get("seed"),
                "Elementary instructions": stream.get("instruction_count"),
                "CX": counts.get("CX"),
                "Budget margin": row.get("budget_margin_cnot"),
                "Peak qubits": register.get("total_qubits"),
                "V4.2 widths": " / ".join(str(value) for value in row.get("parent_v42_widths") or []),
                "V4.3 widths": " / ".join(str(value) for value in row.get("materialized_widths") or []),
                "Bridges": row.get("certified_bridge_count"),
                "Chunks": len(chunks) if isinstance(chunks, list) else None,
                "Stream root": stream.get("stream_manifest_sha256"),
                "Register root": register.get("register_map_sha256"),
                "Decision": row.get("decision"),
            }
        )
    return pd.DataFrame(rows)


def _basis_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    if state.get("authenticated") is not True:
        return pd.DataFrame(columns=["Elementary opcode", "All eight streams"])
    totals = {gate: 0 for gate in EXPECTED_BASIS}
    for row in state.get("seed_rows") or []:
        counts = _mapping(_mapping(row.get("stream_manifest")).get("elementary_counts"))
        for gate in EXPECTED_BASIS:
            totals[gate] += int(counts.get(gate, 0))
    return pd.DataFrame(
        [{"Elementary opcode": gate, "All eight streams": totals[gate]} for gate in EXPECTED_BASIS]
    )


def _register_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    rows = state.get("seed_rows") or []
    if not rows:
        return pd.DataFrame()
    worst = max(rows, key=lambda row: int(_mapping(row.get("register_layout")).get("total_qubits", -1)))
    registers = _rows(_mapping(worst.get("register_layout")).get("registers"))
    return pd.DataFrame(
        [
            {
                "Register": register.get("name"),
                "Start": register.get("start"),
                "Width": register.get("width"),
                "Role / liveness": register.get("role"),
            }
            for register in registers
        ]
    )


def _simulator_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    if state.get("authenticated") is not True:
        return pd.DataFrame(columns=["Independent C++ control", "Cases", "State"])
    counts = _mapping(_mapping(state.get("simulator")).get("pass_counts"))
    labels = (
        ("Cuccaro full adders", "cuccaro_full_adder_cases"),
        ("Cuccaro modular adders", "cuccaro_modular_adder_cases"),
        ("High-bit comparators", "high_bit_comparator_cases"),
        ("Arithmetic cases", "arithmetic_cases"),
        ("Promise SELECT cases", "promise_select_cases"),
        ("Promise SELECT roundtrips", "promise_select_roundtrips"),
        ("Off-promise negative controls", "off_promise_negative_controls"),
        ("Gate-count contracts", "gate_count_contracts"),
        ("Total primary cases", "total_primary_cases"),
    )
    return pd.DataFrame(
        [{"Independent C++ control": label, "Cases": counts.get(key), "State": "PASS"} for label, key in labels]
    )


def _correction_ledger(state: Mapping[str, Any]) -> pd.DataFrame:
    if state.get("authenticated") is not True:
        return pd.DataFrame(columns=["Append-only correction", "V4.3 disposition", "Quantitative effect"])
    amendments = _mapping(state.get("amendments"))
    return pd.DataFrame(
        [
            {
                "Append-only correction": "Elementary basis",
                "V4.3 disposition": amendments.get("v42_elementary_basis_omitted_h"),
                "Quantitative effect": "H explicitly admitted; parent bytes unchanged",
            },
            {
                "Append-only correction": "Arithmetic width 3 → 5",
                "V4.3 disposition": amendments.get("width_three_to_five"),
                "Quantitative effect": "+22,784 CX / complete step",
            },
            {
                "Append-only correction": "Nested interval predicate",
                "V4.3 disposition": amendments.get("interval_predicate"),
                "Quantitative effect": "−168 CX / complete step",
            },
            {
                "Append-only correction": "Net materialization delta",
                "V4.3 disposition": "EXPLICIT_REPLAY_AGAINST_EACH_V42_SEED_LEDGER",
                "Quantitative effect": "+22,616 CX / complete step",
            },
        ]
    )


def render_v43_reversible_circuit_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    spec: Mapping[str, Any] | None,
    artifact_integrity: bool | None,
    spec_integrity: bool | None,
    parent_integrity: bool | None,
    key_prefix: str = "quantum_phase3",
) -> dict[str, Any]:
    """Render sealed V4.3 evidence; return the normalized fail-closed state."""

    state = normalize_v43_artifact(
        artifact,
        artifact_integrity=artifact_integrity,
        spec_integrity=spec_integrity,
        parent_integrity=parent_integrity,
    )
    ok = bool(state["authenticated"])
    aggregate = _mapping(state.get("aggregate"))
    simulator = _mapping(state.get("simulator"))
    negative = _mapping(state.get("negative_control"))
    decisions = _mapping(state.get("decisions"))

    section_header(
        "V4.3 Reversible Circuit Materialization & Independent Simulation",
        (
            "V4.2 RESOURCE SCREEN → 21.926M ORDERED ELEMENTARY INSTRUCTIONS → 8 SEALED STREAMS → PROMISE-ONLY PASS → BACKEND STILL BLOCKED"
            if ok
            else "V4.3 EVIDENCE AUTHENTICATION FAILED → METRICS MASKED → BACKEND AND HARDWARE BLOCKED"
        ),
        "V4.3 materializes one complete provider-neutral circuit stream for every frozen seed, binds register liveness and ordered chunk roots, and independently exercises exact reversible controls. The acceptance is restricted to feasible N=40 data with two one-hot coin registers; a mandatory off-promise witness remains explicitly rejected.",
    )
    st.markdown(
        """<style>
        .qv43-shell{position:relative;overflow:hidden;border:1px solid rgba(83,240,222,.44);border-radius:26px;padding:24px 25px;margin:10px 0 15px;background:radial-gradient(circle at 88% 8%,rgba(31,231,178,.22),transparent 29%),radial-gradient(circle at 7% 100%,rgba(96,86,255,.23),transparent 35%),linear-gradient(132deg,rgba(1,17,28,.99),rgba(8,19,47,.99) 55%,rgba(35,10,50,.98));box-shadow:0 0 72px rgba(67,235,211,.13)}
        .qv43-shell:after{content:"";position:absolute;inset:0;background:linear-gradient(105deg,transparent 32%,rgba(161,255,238,.055) 49%,transparent 66%);transform:translateX(-100%);animation:qv43scan 13s linear infinite;pointer-events:none}@keyframes qv43scan{to{transform:translateX(100%)}}
        .qv43-k{font-size:.61rem;letter-spacing:.19em;color:#79ffe4;font-weight:950}.qv43-title{font-size:1.22rem;color:#f7fbff;font-weight:950;margin:7px 0;overflow-wrap:anywhere}.qv43-copy{font-size:.75rem;color:#b1c2d3;line-height:1.54}.qv43-tags{font-size:.59rem;color:#a4b7ca;letter-spacing:.10em;margin-top:12px}.qv43-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:11px 0 16px}.qv43-card{border:1px solid rgba(107,239,218,.20);background:rgba(2,16,29,.84);border-radius:15px;padding:12px;min-height:91px}.qv43-label{font-size:.49rem;color:#839cb4;letter-spacing:.115em;font-weight:900}.qv43-value{font-size:.88rem;color:#f5faff;font-weight:950;margin:5px 0;overflow-wrap:anywhere}.qv43-pass{color:#7af0ba}.qv43-warn{color:#ffd18a}.qv43-block{color:#ff9ca8}.qv43-note{font-size:.60rem;color:#91a8bc;line-height:1.39}.qv43-flow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:7px;margin:12px 0 17px}.qv43-node{border:1px solid rgba(115,237,215,.18);border-radius:12px;padding:10px;background:rgba(5,18,31,.78);font-size:.61rem;color:#aabbd0;line-height:1.37}.qv43-node b{display:block;color:#eaf8ff;margin-bottom:4px}.qv43-proof{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:9px 0}.qv43-root{border:1px solid rgba(127,164,255,.22);border-radius:13px;padding:11px;background:rgba(10,16,37,.76);font-size:.61rem;color:#9fb2c7;overflow-wrap:anywhere}.qv43-root b{display:block;color:#dfeaff;margin-bottom:5px}@media(max-width:1120px){.qv43-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.qv43-flow{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:620px){.qv43-grid,.qv43-flow,.qv43-proof{grid-template-columns:1fr}}
        </style>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div class="qv43-shell" data-qv43-surface="reversible-circuit-materialization" data-qv43-release="4.3" data-qv43-auth="{'pass' if ok else 'fail'}" data-qv43-materialization="{'SEALED' if ok else 'INDETERMINATE'}" data-qv43-promise="{'EXACT_FEASIBLE_N40_X_TWO_ONE_HOT_COINS_ONLY' if ok else 'INDETERMINATE'}" data-qv43-off-promise="{'REJECTED_WITH_WITNESS' if ok else 'INDETERMINATE'}" data-qv43-backend="{'NOT_RUN' if ok else 'INDETERMINATE'}" data-qv43-hardware="{'false' if ok else 'indeterminate'}" data-qv43-jobs="{'0' if ok else 'MASKED'}" data-qv43-provider-calls="{'0' if ok else 'MASKED'}">
        <div class="qv43-k">V4.3 · SEALED ELEMENTARY CIRCUIT MANIFEST · INSTITUTIONAL EVIDENCE SURFACE</div>
        <div class="qv43-title">{escape(state['overall'])}</div>
        <div class="qv43-copy">Artifact {'AUTHENTICATED' if ok else 'INVALID / ABSENT / UNPINNED'} · SHA {escape(state['artifact_sha256'])}<br>Admission: {escape(str(decisions.get('production_admission', 'MASKED')))}<br>Promise: {escape(str(decisions.get('promise_scope', 'MASKED')))}</div>
        <div class="qv43-tags">RESEARCH_ONLY · BACKEND-AGNOSTIC CIRCUIT IR · PROMISE-ONLY PASS · OFF-PROMISE REJECTION RETAINED · HARDWARE FALSE · ADVANTAGE NOT CLAIMED</div></div>""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""<div class="qv43-grid">
        <div class="qv43-card"><div class="qv43-label">EVIDENCE AUTH</div><div class="qv43-value {'qv43-pass' if ok else 'qv43-block'}">{'PASS' if ok else 'NOT AUTHENTICATED'}</div><div class="qv43-note">raw + semantic + 175 immutable parent paths</div></div>
        <div class="qv43-card"><div class="qv43-label">ELEMENTARY STREAM</div><div class="qv43-value qv43-pass">{escape(_fmt(aggregate.get('total_elementary_instructions')))}</div><div class="qv43-note">ordered instructions across eight seeds</div></div>
        <div class="qv43-card"><div class="qv43-label">MAX CX / STEP</div><div class="qv43-value qv43-pass">{escape(_fmt(aggregate.get('maximum_materialized_cnot')))}</div><div class="qv43-note">maximum, not average</div></div>
        <div class="qv43-card"><div class="qv43-label">MIN CX MARGIN</div><div class="qv43-value qv43-pass">{escape(_fmt(aggregate.get('minimum_budget_margin_cnot'), signed=True))}</div><div class="qv43-note">against immutable 2,500,000 budget</div></div>
        <div class="qv43-card"><div class="qv43-label">PEAK LOGICAL QUBITS</div><div class="qv43-value">{escape(_fmt(aggregate.get('maximum_logical_qubits_with_recycled_workspace')))}</div><div class="qv43-note">static liveness + clean reuse contract</div></div>
        <div class="qv43-card"><div class="qv43-label">SEALED SEEDS</div><div class="qv43-value qv43-pass">{'8 / 8' if ok else 'MASKED'}</div><div class="qv43-note">one complete V4.2 generator step each</div></div>
        <div class="qv43-card"><div class="qv43-label">C++ ARITHMETIC CASES</div><div class="qv43-value">{escape(_fmt(_mapping(simulator.get('pass_counts')).get('arithmetic_cases')))}</div><div class="qv43-note">independent, zero external dependencies</div></div>
        <div class="qv43-card"><div class="qv43-label">PROMISE SELECT</div><div class="qv43-value qv43-pass">{'64 + 64 PASS' if ok else 'MASKED'}</div><div class="qv43-note">cases + exact roundtrips</div></div>
        <div class="qv43-card"><div class="qv43-label">OFF-PROMISE CONTROL</div><div class="qv43-value qv43-warn">{'REJECTED' if ok else 'MASKED'}</div><div class="qv43-note">retained feasibility flag = {escape(_fmt(negative.get('retained_feasible_flag_after_reverse')))}</div></div>
        <div class="qv43-card"><div class="qv43-label">BACKEND / HARDWARE</div><div class="qv43-value qv43-block">{'NOT RUN / FALSE' if ok else 'MASKED'}</div><div class="qv43-note">provider calls {'0 · QPU jobs 0' if ok else 'MASKED'}</div></div></div>""",
        unsafe_allow_html=True,
    )

    st.markdown(
        """<div class="qv43-flow">
        <div class="qv43-node"><b>1 · Frozen V4.2</b>177-file contract · 175 immutable successor paths</div>
        <div class="qv43-node"><b>2 · Explicit registers</b>Data, two one-hot coins, target, sums and clean work</div>
        <div class="qv43-node"><b>3 · Elementary IR</b>X · H · T · TDG · RY · RZ · CX</div>
        <div class="qv43-node"><b>4 · Ordered sealing</b>8,192-instruction chunks + stage and stream roots</div>
        <div class="qv43-node"><b>5 · Finite controls</b>Promise PASS · off-promise witness rejected</div>
        <div class="qv43-node"><b>6 · Next gate</b>Named-backend zero-job transpilation + routing</div>
        </div>""",
        unsafe_allow_html=True,
    )

    if ok:
        st.success(
            "MATERIALIZATION · PASS — 21,925,902 ordered elementary instructions are sealed across eight deterministic manifests; every CX numerator remains below 2,500,000."
        )
        st.success(
            "PROMISE-SUBSPACE REVERSIBILITY · PASS — all eight real N=40 witnesses clear retained feasibility state, and the independent C++ harness passes 107,520 arithmetic cases."
        )
        st.warning(
            "OFF-PROMISE NEGATIVE CONTROL · REJECTED WITH WITNESS — the N=2 start 10 → target 01 retains a feasibility flag on reverse cleanup. V4.3 therefore does not claim global cleanup."
        )
        st.warning(
            "CIRCUIT MATERIALIZED ≠ BACKEND EXECUTABLE — no named backend, transpilation, routing, calibration, noise study, provider call, QPU job, performance result, or quantum advantage is established."
        )
    else:
        st.error(
            "V4.3 evidence is absent, invalid, or unpinned. Instruction, CX, qubit, simulator, promise, and boundary metrics remain masked fail-closed."
        )

    stream_root = aggregate.get("ordered_stream_manifest_root_sha256") if ok else None
    register_root = aggregate.get("register_map_root_sha256") if ok else None
    st.markdown(
        f"""<div class="qv43-proof">
        <div class="qv43-root"><b>ORDERED STREAM-MANIFEST ROOT</b>{escape(str(stream_root or 'MASKED'))}</div>
        <div class="qv43-root"><b>ORDERED REGISTER-MAP ROOT</b>{escape(str(register_root or 'MASKED'))}</div>
        </div>""",
        unsafe_allow_html=True,
    )

    materialization = _materialization_ledger(state)
    st.markdown("**Eight-seed materialization ledger · complete ordered generator step**")
    st.dataframe(materialization, width="stretch", hide_index=True)
    if ok and not materialization.empty:
        st.markdown("**CX numerator and remaining frozen budget by seed**")
        st.bar_chart(
            materialization[["Seed", "CX", "Budget margin"]].set_index("Seed"),
            width="stretch",
        )

    basis = _basis_ledger(state)
    st.markdown("**Frozen elementary basis · aggregate opcode ledger**")
    st.dataframe(basis, width="stretch", hide_index=True)

    simulator_ledger = _simulator_ledger(state)
    st.markdown("**Independent C++ reversible-control ledger**")
    st.dataframe(simulator_ledger, width="stretch", hide_index=True)

    correction_ledger = _correction_ledger(state)
    st.markdown("**Append-only V4.2 → V4.3 correction ledger**")
    st.dataframe(correction_ledger, width="stretch", hide_index=True)
    if ok:
        st.caption(
            "The four three-bit group banks are zero-extended to five bits (+22,784 CX), while the exact nested GE-XOR interval circuit removes two unnecessary row CCX (−168 CX). Net replay: +22,616 CX per seed. V4.2 bytes and its accepted resource-screen decision remain unchanged."
        )

    register_ledger = _register_ledger(state)
    st.markdown("**Peak register and liveness map · worst-case seed 7703**")
    st.dataframe(register_ledger, width="stretch", hide_index=True)

    unauthenticated_state = "NOT AUTHENTICATED"
    obligations = pd.DataFrame(
        [
            ("V4.2 immutable lineage", "Freeze raw + semantic identity; 175 successor-immutable paths", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Full elementary streams", "Eight ordered manifests; chunk, stage, stream and aggregate roots", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Register liveness", "Disjoint phase reuse + named clean-exit registers", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Exact arithmetic controls", "107,520 independent C++ exhaustive cases", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Promise SELECT cleanup", "Feasible N=40 data × two one-hot coin registers only", "PASS" if ok else "NOT AUTHENTICATED"),
            ("Off-promise cleanup", "Mandatory N=2 counterexample retained", "REJECTED WITH WITNESS" if ok else "NOT AUTHENTICATED"),
            ("Append-only corrections", "H basis + width lift + interval predicate; no parent rewrite", "DISCLOSED" if ok else "NOT AUTHENTICATED"),
            ("Named backend", "Backend identity and native target", "NOT SELECTED" if ok else unauthenticated_state),
            ("Transpilation / routing", "Zero-job target-specific compiler protocol", "NEXT GATE · NOT RUN" if ok else unauthenticated_state),
            ("Hardware execution", "Provider credentials, calls and QPU jobs", "BLOCKED · 0 JOBS" if ok else unauthenticated_state),
            ("Optimization / advantage", "Objective quality and quantum-classical comparison", "NOT TESTED / NOT CLAIMED" if ok else unauthenticated_state),
        ],
        columns=["Evidence obligation", "Method / scope", "State"],
    )
    st.markdown("**Admission matrix · materialization does not substitute for backend evidence**")
    st.dataframe(obligations, width="stretch", hide_index=True)

    with st.expander("Circuit contract · ordered provider-neutral materialization", expanded=False):
        st.markdown("**CANONICAL INSTRUCTION · INDEX | STAGE | OPCODE | QUBITS | SIGNED RATIONAL π**")
        st.markdown(
            "Every complete seed stream is serialized in deterministic order and sealed by 8,192-instruction chunk hashes, stage hashes, one stream hash and one self-hashed stream manifest. The release stores manifests rather than multi-million-gate side files."
        )
        st.markdown("**ELEMENTARY BASIS · X · H · T · TDG · RY · RZ · CX**")
        st.markdown("**ANGLES · coin θ = π/2 · coin β = 0 · bridge θ = π/2**")

    with st.expander("Promise boundary · accepted domain and mandatory rejection", expanded=True):
        st.markdown(
            "The PASS applies only when DATA begins in the registered exact-feasible N=40 set and REMOVE_COIN and ADD_COIN are each one-hot. The off-promise N=2 witness starts at 10 with feasible set {01}, addresses remove bit 1 and add bit 0, reaches 01, but reconstructs infeasible 10 and leaves the feasibility flag set. That observed failure is part of the sealed evidence."
        )
        if ok:
            st.code(
                f"status={negative.get('status')}\n"
                f"start={negative.get('start_mask_hex')} target={negative.get('target_mask_hex')} "
                f"reverse_target={negative.get('reverse_target_mask_hex')}\n"
                f"retained_feasible_flag={negative.get('retained_feasible_flag_after_reverse')}",
                language="text",
            )

    with st.expander("Scientific boundary · what V4.3 does not establish", expanded=True):
        st.markdown(
            "V4.3 establishes deterministic backend-agnostic circuit manifests and finite reversible-control evidence under a stated promise. It does not establish native-gate validity for a device, routing feasibility, physical depth, calibration stability, error mitigation, runtime, portfolio benefit, hardware execution, production readiness, or quantum advantage."
        )

    for label, suffix, help_text in (
        ("Rebuild sealed V4.3 streams", "rebuild", "This UI serves immutable manifests only."),
        ("Relax the feasible-data promise", "promise", "The off-promise counterexample is mandatory evidence."),
        ("Suppress the negative control", "negative", "Failed controls cannot be removed from the sealed result."),
        ("Rewrite the V4.2 decision", "parent", "V4.2 lineage remains byte-exact and immutable."),
        ("Override the 2,500,000 CX gate", "budget", "The acceptance budget is frozen."),
        ("Select a named backend · V4.3 next gate", "backend", "Backend selection belongs to the next protocol."),
        ("Run transpilation or routing", "routing", "No backend compiler is called from this surface."),
        ("Read provider credentials · V4.3 prohibited", "credentials", "No credential may be read."),
        ("Submit a QPU job · V4.3 prohibited", "qpu", "Hardware execution is not authorized."),
        ("Claim quantum advantage", "advantage", "No advantage study has been run."),
    ):
        st.button(label, disabled=True, key=f"{key_prefix}_v43_{suffix}", help=help_text)

    if ok:
        artifact_bytes = (
            json.dumps(dict(state["artifact"]), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        st.download_button(
            "Download sealed V4.3 reversible-circuit artifact",
            data=artifact_bytes,
            file_name="SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json",
            mime="application/json",
            key=f"{key_prefix}_v43_artifact_download",
        )
        if spec:
            st.download_button(
                "Download V4.3 frozen materialization specification",
                data=(json.dumps(dict(spec), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
                file_name="PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json",
                mime="application/json",
                key=f"{key_prefix}_v43_spec_download",
            )
        for label, frame, filename, suffix in (
            ("Download V4.3 materialization ledger CSV", materialization, "QUANTUM_LAB_V4_3_MATERIALIZATION_LEDGER.csv", "materialization"),
            ("Download V4.3 elementary-basis ledger CSV", basis, "QUANTUM_LAB_V4_3_BASIS_LEDGER.csv", "basis"),
            ("Download V4.3 simulator ledger CSV", simulator_ledger, "QUANTUM_LAB_V4_3_SIMULATOR_LEDGER.csv", "simulator"),
            ("Download V4.3 correction ledger CSV", correction_ledger, "QUANTUM_LAB_V4_3_CORRECTION_LEDGER.csv", "corrections"),
            ("Download V4.3 register ledger CSV", register_ledger, "QUANTUM_LAB_V4_3_REGISTER_LEDGER.csv", "registers"),
        ):
            st.download_button(
                label,
                data=frame.to_csv(index=False).encode("utf-8"),
                file_name=filename,
                mime="text/csv",
                key=f"{key_prefix}_v43_{suffix}_download",
            )

    st.warning(
        "V4.3 CLAIM BOUNDARY · BACKEND-AGNOSTIC ELEMENTARY CIRCUIT MATERIALIZATION + FINITE PROMISE-SUBSPACE REVERSIBLE CONTROLS ONLY. OFF-PROMISE GLOBAL CLEANUP IS REJECTED."
    )
    st.markdown(f"**NEXT FALSIFIABLE GATE · {escape(state['next_gate'])}**")
    if ok:
        st.markdown("**NAMED BACKEND · FALSE · TRANSPILATION / ROUTING · NOT RUN**")
        st.markdown("**HARDWARE EXECUTABLE · FALSE · QPU JOBS · 0 · PROVIDER CALLS · 0**")
        st.markdown("**OPTIMIZATION PERFORMANCE · NOT TESTED · QUANTUM ADVANTAGE · NOT CLAIMED**")
    else:
        st.markdown("**BACKEND · HARDWARE · JOB · PROVIDER · PERFORMANCE · ADVANTAGE EVIDENCE · MASKED**")
    return state


def apply_v43_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Project authenticated V4.3 evidence into the legacy encoding state."""

    if encoding is None:
        return None
    projected = dict(encoding)
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True:
        return projected
    source = _mapping(state.get("artifact")) or _mapping(artifact)
    decisions = _mapping(source.get("decisions"))
    aggregate = _mapping(source.get("aggregate"))
    simulator = _mapping(source.get("independent_cpp_simulator"))
    negative = _mapping(source.get("mandatory_off_promise_control"))
    projected.update(
        {
            "v43_artifact_sha": source.get("artifact_sha256"),
            "v43_overall_decision": decisions.get("overall"),
            "v43_production_admission": decisions.get("production_admission"),
            "v43_promise_scope": decisions.get("promise_scope"),
            "v43_next_falsifiable_gate": decisions.get("next_falsifiable_gate"),
            "v43_total_elementary_instructions": aggregate.get("total_elementary_instructions"),
            "v43_maximum_materialized_cnot": aggregate.get("maximum_materialized_cnot"),
            "v43_minimum_budget_margin_cnot": aggregate.get("minimum_budget_margin_cnot"),
            "v43_maximum_logical_qubits": aggregate.get("maximum_logical_qubits_with_recycled_workspace"),
            "v43_ordered_stream_manifest_root_sha256": aggregate.get("ordered_stream_manifest_root_sha256"),
            "v43_register_map_root_sha256": aggregate.get("register_map_root_sha256"),
            "v43_independent_cpp_simulation": simulator.get("decision"),
            "v43_off_promise_status": negative.get("status"),
            "logical_qubits_min": aggregate.get("maximum_logical_qubits_with_recycled_workspace"),
            "encoding_status": "V4.3 PROVIDER-NEUTRAL CIRCUIT IR ADMITTED · PROMISE-ONLY · BACKEND AND HARDWARE BLOCKED",
            "research_classification": "RESEARCH_ONLY",
            "circuit_materialization": "BACKEND_AGNOSTIC_ELEMENTARY_STREAM_MANIFEST_SEALED",
            "promise_subspace_only": True,
            "off_promise_global_cleanup": "REJECTED_WITH_WITNESS",
            "named_backend_selected": False,
            "hardware_executable": False,
            "backend_transpilation": "NOT_RUN",
            "provider_calls": 0,
            "qpu_jobs_submitted": 0,
            "optimization_performance": "NOT_TESTED",
            "quantum_advantage": "NOT_CLAIMED",
        }
    )
    return projected


__all__ = [
    "EXPECTED_V43_ARTIFACT_RAW_SHA256",
    "EXPECTED_V43_ARTIFACT_SHA256",
    "EXPECTED_V43_SIMULATOR_RAW_SHA256",
    "EXPECTED_V43_SOURCE_RAW_SHA256",
    "EXPECTED_V43_SPEC_RAW_SHA256",
    "EXPECTED_V43_SPEC_SHA256",
    "apply_v43_encoding_state",
    "default_v43_ui_artifact_path",
    "load_v43_ui_artifact",
    "normalize_v43_artifact",
    "render_v43_reversible_circuit_panel",
]
