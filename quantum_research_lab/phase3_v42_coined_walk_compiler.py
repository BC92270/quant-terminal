"""Quantum Lab V4.2 one-hot coined walk and shared exact-arithmetic compiler.

V4.2 is a provider-free successor to the authenticated V4.1 release.  It does
not delete feasible exchange labels.  Instead, two persistent one-hot address
registers select an exchange while a single exact target-feasibility oracle is
shared across the complete address family.  The resulting promise-subspace
SELECT is an involution; cyclic coin mixers expose every ordered address pair;
and the three V4.1 data-only bridge transpositions preserve the certified
connectivity result.  This module only emits selected-model research evidence.
It imports no provider SDK and performs no backend or hardware work.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Mapping, Sequence

from .phase3_v39_scalable_reversible_ir import Cost
from .phase3_v41_certified_bridge_compiler import (
    _cache_preparation_cost,
    _certificate_by_seed,
    _gate_cost,
    _guarded_rows,
    _ripple_comparator_cost,
    validate_v41_artifact,
)


V42_VERSION = "PHASE III · V4.2 ONE-HOT COINED WALK + SHARED EXACT ARITHMETIC · V1"
ARTIFACT_VERSION = "PHASE III · V4.2 CONNECTED COINED-WALK RESOURCE ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V4_2_COINED_WALK_COMPILER_SPEC_V1.json"
ENGINE_FILENAME = "phase3_v42_selector_engine.cpp"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_2_COINED_WALK_COMPILER_ARTIFACT.json"
SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
N = 40
K = 10
PAIR_POSITION_COUNT = N * (N - 1) // 2
ORDERED_COIN_BASIS_COUNT = N * N
BUDGET_CNOT = 2_500_000
SELECTED_MODEL = "CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1"

EXPECTED_SPEC_SHA = "acf640c11d3dc575ebcc1358919095cf68673583a8c628c7131e664f7859801e"
EXPECTED_ENGINE_RAW = "3d73cddfc7c06cf6e0e5bc22a3ad29c3ea79ac22d7c1e5a8b1ca1044789c65ab"
EXPECTED_V41_SPEC_RAW = "0bbe903e7520213f8effcd592051420ac54502934a1840b6052e3b4865950c35"
EXPECTED_V41_SPEC_SHA = "a5977ce4dda24d2fe6e8308e299b8a6b9097cf4fdf7e2835ca8e2fdc6aa99c89"
EXPECTED_V41_ENGINE_RAW = "6b065ac1fb834e9ff226954984fe466901314c9b556c2c253a0ace873f2bf26e"
EXPECTED_V41_SOURCE_RAW = "5565ce436034183228d27e37b249afc56f19121a5a8c2638533d4480762c62d1"
EXPECTED_V41_ARTIFACT_RAW = "42a5d7caf4e9fab18e771b2bd55fc38c9a77f7fac42f2599feb4fe789cf88c07"
EXPECTED_V41_ARTIFACT_SHA = "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e"
EXPECTED_V41_FREEZE_RAW = "43d3bd4e9cdcb54e9a7c1649430f6bd10cae9ef51ac5d77319a7630639b0c34f"
EXPECTED_V41_FREEZE_SHA = "b9ec84e2110e40cf1c77fb90b18794ff80e26ddf12233d5193eb18ca5aa6c201"
EXPECTED_V41_FROZEN_FINGERPRINT = "27bb43b53f3c6847d1ef80518c595755c1e606015b423c194c8a2e61f3f76ea8"
V41_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})

_PARENT_CACHE: dict[str, dict[str, Any]] = {}


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
        "v41_spec": base / "quantum_research_lab" / "PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json",
        "v41_engine": base / "quantum_research_lab" / "phase3_v41_bridge_engine.cpp",
        "v41_source": base / "quantum_research_lab" / "phase3_v41_certified_bridge_compiler.py",
        "v41_artifact": base / "outputs" / "quantum_phase3" / "v41_certified_bridge" / "SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
        "v41_freeze": base / "FREEZE_CONTRACT_V4_1.json",
    }


def load_v42_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["spec"]
    payload = _read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v42_spec_sha", "v42_spec_sha256"}}
    digest = canonical_json_sha256(core)
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    compiler = payload.get("resource_compiler_contract") or {}
    selector = payload.get("coin_and_selector_contract") or {}
    if not (
        digest == EXPECTED_SPEC_SHA
        and payload.get("v42_spec_sha256") == digest
        and payload.get("v42_spec_sha") == digest[:20].upper()
        and boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("circuit_materialization") == "NOT_RUN_NEXT_GATE"
        and chronology.get("resource_ledger_state_at_seal") == "NOT_EVALUATED"
        and compiler.get("selected_decomposition_model") == SELECTED_MODEL
        and selector.get("selector_engine_source_raw_file_sha256") == EXPECTED_ENGINE_RAW
    ):
        raise ValueError("V4.2 specification identity or scientific boundary mismatch.")
    return payload


def authenticate_v41_parent(
    *,
    root: str | Path | None = None,
    deep: bool = True,
) -> dict[str, Any]:
    """Authenticate the exact V4.1 parent and all 159 immutable paths."""

    global _PARENT_CACHE
    base = _root(root)
    cache_key = str(base)
    if deep and cache_key in _PARENT_CACHE:
        return copy.deepcopy(_PARENT_CACHE[cache_key])
    paths = _paths(base)
    spec = load_v42_spec(root=base)
    expected = spec["parent_contract"]
    errors: list[str] = []
    expected_raw = {
        "v41_spec": EXPECTED_V41_SPEC_RAW,
        "v41_engine": EXPECTED_V41_ENGINE_RAW,
        "v41_source": EXPECTED_V41_SOURCE_RAW,
        "v41_artifact": EXPECTED_V41_ARTIFACT_RAW,
        "v41_freeze": EXPECTED_V41_FREEZE_RAW,
        "engine": EXPECTED_ENGINE_RAW,
    }
    raw_checks: dict[str, dict[str, Any]] = {}
    for name, registered in expected_raw.items():
        try:
            actual = raw_file_sha256(paths[name])
        except Exception as exc:
            actual = ""
            errors.append(f"Unable to hash {name}: {exc}")
        valid = actual == registered
        raw_checks[name] = {"actual": actual, "expected": registered, "valid": valid}
        if not valid:
            errors.append(f"V4.1 parent raw identity mismatch: {name}")
    if not (
        expected.get("expected_v41_spec_raw_file_sha256") == EXPECTED_V41_SPEC_RAW
        and expected.get("expected_v41_engine_raw_file_sha256") == EXPECTED_V41_ENGINE_RAW
        and expected.get("expected_v41_source_raw_file_sha256") == EXPECTED_V41_SOURCE_RAW
        and expected.get("expected_v41_artifact_raw_file_sha256") == EXPECTED_V41_ARTIFACT_RAW
        and expected.get("expected_v41_freeze_raw_file_sha256") == EXPECTED_V41_FREEZE_RAW
    ):
        errors.append("V4.2 specification parent constants drift.")

    semantic_checks: dict[str, bool] = {}
    immutable_mismatches: list[str] = []
    try:
        parent_spec = _read_json_strict(paths["v41_spec"])
        parent_spec_core = {
            key: value for key, value in parent_spec.items()
            if key not in {"v41_spec_sha", "v41_spec_sha256"}
        }
        semantic_checks["v41_spec"] = bool(
            parent_spec.get("v41_spec_sha256") == EXPECTED_V41_SPEC_SHA
            == canonical_json_sha256(parent_spec_core)
        )
    except Exception as exc:
        semantic_checks["v41_spec"] = False
        errors.append(f"V4.1 specification authentication failed: {exc}")
    try:
        artifact = _read_json_strict(paths["v41_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        artifact_valid = artifact.get("artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA == canonical_json_sha256(artifact_core)
        validation: Mapping[str, Any] = {"valid": True}
        if deep:
            validation = validate_v41_artifact(artifact, root=base, authenticate_parent=True)
        semantic_checks["v41_artifact"] = bool(
            artifact_valid
            and validation.get("valid") is True
            and (artifact.get("decisions") or {}).get("overall") == expected.get("expected_v41_decision")
            and (artifact.get("decisions") or {}).get("next_falsifiable_gate") == expected.get("required_v41_next_gate")
            and (artifact.get("decisions") or {}).get("augmented_connectivity_decision")
            == expected.get("required_v41_connectivity_decision")
        )
    except Exception as exc:
        artifact = {}
        semantic_checks["v41_artifact"] = False
        errors.append(f"V4.1 artifact authentication failed: {exc}")
    try:
        freeze = _read_json_strict(paths["v41_freeze"])
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        frozen_files = freeze.get("frozen_files") or {}
        immutable = {
            relative: registered for relative, registered in frozen_files.items()
            if relative not in V41_SUCCESSOR_MUTABLE
        }
        immutable_mismatches = [
            relative for relative, registered in immutable.items()
            if not (base / relative).is_file()
            or raw_file_sha256(base / relative) != registered
        ]
        semantic_checks["v41_freeze"] = bool(
            freeze.get("freeze_contract_sha256") == EXPECTED_V41_FREEZE_SHA
            == canonical_json_sha256(freeze_core)
            and freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V41_FROZEN_FINGERPRINT
            and len(frozen_files) == 161
            and len(immutable) == 159
            and not immutable_mismatches
        )
    except Exception as exc:
        immutable = {}
        semantic_checks["v41_freeze"] = False
        errors.append(f"V4.1 freeze authentication failed: {exc}")
    for name, valid in semantic_checks.items():
        if not valid:
            errors.append(f"V4.1 parent semantic authentication failed: {name}")
    if immutable_mismatches:
        errors.append(f"V4.1 immutable-path mismatches: {immutable_mismatches[:5]}")
    result = {
        "artifact": artifact,
        "deep_validation": bool(deep),
        "errors": list(dict.fromkeys(errors)),
        "immutable_v41_file_count": len(immutable),
        "immutable_v41_files_exact": not immutable_mismatches and len(immutable) == 159,
        "raw_checks": raw_checks,
        "semantic_checks": semantic_checks,
        "valid": not errors and all(semantic_checks.values()),
    }
    if deep:
        _PARENT_CACHE[cache_key] = copy.deepcopy(result)
    return result


def compile_selector_engine(
    destination: str | Path,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    paths = _paths(root)
    if raw_file_sha256(paths["engine"]) != EXPECTED_ENGINE_RAW:
        raise ValueError("V4.2 selector engine source identity mismatch.")
    compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("No C++17 compiler is available for V4.2 validation.")
    target = Path(destination)
    command = [
        compiler,
        "-std=c++17",
        "-O3",
        "-DNDEBUG",
        "-Wall",
        "-Wextra",
        "-pedantic",
        str(paths["engine"]),
        "-o",
        str(target),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError(f"V4.2 selector engine compilation failed: {completed.stderr.strip()}")
    if completed.stderr.strip():
        raise RuntimeError(f"V4.2 selector engine emitted diagnostics: {completed.stderr.strip()}")
    return {
        "binary_sha256": raw_file_sha256(target),
        "command_flags": ["-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic"],
        "compiler": Path(compiler).name,
        "diagnostics_clean": not completed.stderr.strip(),
    }


def _run_selector_engine(binary: Path, mode: int) -> dict[str, Any]:
    completed = subprocess.run(
        [str(binary), str(mode)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"V4.2 selector engine mode {mode} failed: {completed.stderr.strip()}")
    payload = json.loads(
        completed.stdout,
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict) or payload.get("valid") is not True:
        raise ValueError("V4.2 selector engine did not return a valid result.")
    return payload


def run_selector_control(*, root: str | Path | None = None) -> dict[str, Any]:
    stable_fields = (
        "algorithm",
        "arbitrary_supports",
        "bridge_cases",
        "cleanup_cases",
        "cleanup_failures",
        "full_domain_joint_cases",
        "full_domain_joint_failures",
        "joint_component_cases",
        "joint_component_failures",
        "selector_cases",
        "selector_failures",
        "valid",
    )
    with tempfile.TemporaryDirectory(prefix="quantum-v42-selector-") as temporary:
        binary = Path(temporary) / "v42_selector_engine"
        runtime_build = compile_selector_engine(binary, root=root)
        forward = _run_selector_engine(binary, 0)
        reverse = _run_selector_engine(binary, 1)
    stable_forward = {field: forward.get(field) for field in stable_fields}
    stable_reverse = {field: reverse.get(field) for field in stable_fields}
    core = {
        # The executable digest and compiler identity are intentionally excluded:
        # they are environment evidence, not portable scientific identity.  The
        # sealed artifact authenticates the source, flags, clean compilation and
        # exhaustive output so macOS and Linux rebuild the same canonical JSON.
        "build_contract": {
            "command_flags": runtime_build["command_flags"],
            "diagnostics_clean": runtime_build["diagnostics_clean"],
            "engine_source_raw_file_sha256": EXPECTED_ENGINE_RAW,
            "language_standard": "C++17",
        },
        "forward": forward,
        "reverse": reverse,
        "stable_fields": list(stable_fields),
        "stable_replay_match": stable_forward == stable_reverse,
    }
    if not core["stable_replay_match"]:
        raise ValueError("V4.2 selector engine traversal replay mismatch.")
    return {**core, "selector_control_sha256": canonical_json_sha256(core)}


def _cost_from_dict(payload: Mapping[str, Any]) -> Cost:
    return Cost(
        cnot=int(payload.get("selected_model_cnot", 0)),
        one_qubit=int(payload.get("selected_model_one_qubit_gates", 0)),
        abstract_gates=int(payload.get("abstract_gate_count", 0)),
        x=int(payload.get("abstract_x", 0)),
        cx=int(payload.get("abstract_cx", 0)),
        ccx=int(payload.get("abstract_ccx", 0)),
        mcx=int(payload.get("abstract_mcx", 0)),
        clean_decomposition_ancillas=int(payload.get("clean_decomposition_ancillas", 0)),
    )


def _merge_histogram(target: dict[str, int], source: Mapping[str, Any], scale: int = 1) -> None:
    for key, value in source.items():
        target[str(key)] = target.get(str(key), 0) + scale * int(value)


def compile_feasibility_oracle(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compile one target-feasibility toggle and erase all internal work."""

    preparation, preparation_macros = _cache_preparation_cost(rows)
    total = preparation.scale(2)
    comparator_by_width: dict[str, int] = {}
    controlled_add_by_width: dict[str, int] = {}
    _merge_histogram(
        controlled_add_by_width,
        preparation_macros["controlled_add_by_width"],
        scale=2,
    )
    row_ledger: list[dict[str, Any]] = []
    for row in rows:
        width = int(row["width"])
        lower = int(row["guard"])
        upper = lower + int(row["span"])
        maximum = (1 << width) - 1
        if not (0 < lower <= upper < maximum):
            raise ValueError("V4.2 requires explicit nontrivial guarded lower and upper checks.")
        ge = _ripple_comparator_cost(width, lower, relation="GE")
        le = _ripple_comparator_cost(width, upper, relation="LE")
        row_cost = ge.scale(2) + le.scale(2) + _gate_cost(2).scale(2)
        total += row_cost
        comparator_by_width[str(width)] = comparator_by_width.get(str(width), 0) + 4
        row_core = {
            "guarded_lower": lower,
            "guarded_upper": upper,
            "kind": str(row["kind"]),
            "name": str(row["name"]),
            "resources": row_cost.as_dict(),
            "width": width,
        }
        row_ledger.append({**row_core, "row_oracle_sha256": canonical_json_sha256(row_core)})
    aggregate = _gate_cost(len(rows))
    total += aggregate
    terms = {
        "comparator_by_width": comparator_by_width,
        "controlled_add_by_width": controlled_add_by_width,
        "direct_cnot": 0,
        "mcx_by_controls": {
            "2": 2 * len(rows),
            str(len(rows)): 1,
        },
    }
    replay = selected_model_cnot_from_terms(terms)
    if replay != total.cnot:
        raise AssertionError("V4.2 feasibility-oracle formula replay mismatch.")
    core = {
        "cache_offset_initialization_x": int(preparation_macros["constant_initialization_x"]) * 2,
        "constraint_row_count": len(rows),
        "independent_cnot_formula_replay": replay,
        "macro_terms": terms,
        "resources": total.as_dict(),
        "row_ledger": row_ledger,
        "sum_build_invocations": 2,
        "sum_build_macros_per_invocation": copy.deepcopy(preparation_macros),
    }
    return {**core, "feasibility_oracle_sha256": canonical_json_sha256(core)}


def selected_model_cnot_from_terms(terms: Mapping[str, Any]) -> int:
    return (
        sum(
            int(count) * (68 * int(width) - 102)
            for width, count in (terms.get("controlled_add_by_width") or {}).items()
        )
        + sum(
            int(count) * (16 * int(width) - 9)
            for width, count in (terms.get("comparator_by_width") or {}).items()
        )
        + sum(
            int(count) * _gate_cost(int(controls)).cnot
            for controls, count in (terms.get("mcx_by_controls") or {}).items()
        )
        + int(terms.get("direct_cnot", 0))
    )


def _data_only_bridge(bridge: Mapping[str, Any]) -> dict[str, Any]:
    source = int(str(bridge["source_mask_hex"]), 16)
    target = int(str(bridge["target_mask_hex"]), 16)
    differing = [index for index in range(N) if ((source ^ target) >> index) & 1]
    if len(differing) != 4:
        raise ValueError("V4.2 accepts only authenticated Hamming-distance-four bridges.")
    path = [source]
    current = source
    for index in differing:
        current ^= 1 << index
        path.append(current)
    total = Cost()
    negative_control_sum = 0
    for state, target_bit in zip(path[:-1], differing):
        negative = (N - 1) - (state & ~(1 << target_bit)).bit_count()
        total += _gate_cost(N - 1, negative).scale(2)
        negative_control_sum += 2 * negative
    total += Cost(one_qubit=2, abstract_gates=2)
    expected_cnot = 2 * len(differing) * _gate_cost(N - 1).cnot
    if total.cnot != expected_cnot or expected_cnot != 3_600:
        raise AssertionError("V4.2 data-only bridge formula mismatch.")
    core = {
        "bridge_sha256": str(bridge["bridge_sha256"]),
        "data_hamming_distance": len(differing),
        "differing_data_indices": differing,
        "gray_path_sha256": canonical_json_sha256([f"{state:010x}" for state in path]),
        "negative_control_wrapper_count": 2 * negative_control_sum,
        "resources": total.as_dict(),
        "selected_model_mcx_occurrences": 2 * len(differing),
        "source_mask_hex": f"{source:010x}",
        "target_mask_hex": f"{target:010x}",
    }
    return {**core, "bridge_ir_sha256": canonical_json_sha256(core)}


def compile_seed_walk(
    certificate: Mapping[str, Any],
    compression: Mapping[str, Any],
    connectivity: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _guarded_rows(certificate, compression)
    oracle = compile_feasibility_oracle(rows)
    oracle_cost = _cost_from_dict(oracle["resources"]).scale(2)
    scaffold = _gate_cost(2).scale(562) + Cost(
        cnot=326,
        one_qubit=320,
        abstract_gates=406,
        cx=326,
    )
    bridge_rows = [_data_only_bridge(row) for row in connectivity.get("selected_bridges") or []]
    bridge_cost = Cost()
    for row in bridge_rows:
        bridge_cost += _cost_from_dict(row["resources"])
    total = oracle_cost + scaffold + bridge_cost
    widths = [int(row["width"]) for row in rows]
    maximum_width = max(widths)
    logical_qubits = (
        N
        + 2 * N
        + N
        + sum(widths)
        + maximum_width
        + 1
        + 2
        + len(rows)
        + 5
    )
    terms = {
        "comparator_by_width": {
            width: 2 * count
            for width, count in oracle["macro_terms"]["comparator_by_width"].items()
        },
        "controlled_add_by_width": {
            width: 2 * count
            for width, count in oracle["macro_terms"]["controlled_add_by_width"].items()
        },
        "direct_cnot": 326,
        "mcx_by_controls": {
            controls: 2 * count
            for controls, count in oracle["macro_terms"]["mcx_by_controls"].items()
        },
    }
    terms["mcx_by_controls"]["2"] = terms["mcx_by_controls"].get("2", 0) + 562
    replay_without_bridges = selected_model_cnot_from_terms(terms)
    bridge_replay = sum(3_600 for _ in bridge_rows)
    replay_total = replay_without_bridges + bridge_replay
    if replay_total != total.cnot:
        raise AssertionError("V4.2 complete-step formula replay mismatch.")
    budget_margin = BUDGET_CNOT - total.cnot
    core = {
        "addressed_pair_positions_preserved": PAIR_POSITION_COUNT,
        "bridge_ir": bridge_rows,
        "bridge_selected_model_cnot": bridge_cost.cnot,
        "budget_cnot": BUDGET_CNOT,
        "budget_margin_cnot": budget_margin,
        "coin_basis_states": ORDERED_COIN_BASIS_COUNT,
        "coin_qubits": 2 * N,
        "compression_sha256": str(compression["seed_compression_sha256"]),
        "constraint_register_widths": widths,
        "data_qubits": N,
        "decision": "PASSED" if budget_margin >= 0 else "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
        "feasibility_oracle": oracle,
        "feasibility_oracle_invocations": 2,
        "independent_cnot_formula_replay": {
            "bridge_cnot": bridge_replay,
            "match": True,
            "replay_selected_model_cnot": replay_total,
            "terms": terms,
        },
        "instance_id": str(certificate["instance_id"]),
        "logical_qubits_with_recycled_workspace": logical_qubits,
        "parent_connectivity_sha256": str(connectivity["seed_connectivity_sha256"]),
        "promise_scope": "EXACT_FEASIBLE_DATA_X_TWO_ONE_HOT_COIN_REGISTERS",
        "seed": int(certificate["seed"]),
        "select_scaffold": {
            "ccx_count": 562,
            "coin_ring_cnot": 160,
            "direct_cnot_count_including_coin_rings": 326,
            "resources": scaffold.as_dict(),
        },
        "selected_model": SELECTED_MODEL,
        "selected_model_step_resources": total.as_dict(),
        "target_scratch_qubits": N,
    }
    return {**core, "seed_walk_sha256": canonical_json_sha256(core)}


def build_support_evidence(parent_artifact: Mapping[str, Any]) -> dict[str, Any]:
    parent = parent_artifact["connectivity_evidence"]
    rows: list[dict[str, Any]] = []
    for source in parent["seed_rows"]:
        vertices = int(source["authenticated_v40_feasible_vertices"])
        one_swap_edges = int(source["authenticated_v40_exact_one_swap_edges"])
        bridges = int(source["selected_bridge_count"])
        coin_edges = 2 * N * N * vertices
        selector_edges = 2 * one_swap_edges
        replicated_bridge_edges = ORDERED_COIN_BASIS_COUNT * bridges
        core = {
            "addressed_pair_positions_preserved": PAIR_POSITION_COUNT,
            "authenticated_feasible_data_vertices": vertices,
            "authenticated_one_swap_edges": one_swap_edges,
            "coin_basis_states": ORDERED_COIN_BASIS_COUNT,
            "coin_ring_support_edges": coin_edges,
            "connected": bool(source["connected_by_certified_subgraph"]),
            "joint_component_count": 1 if source["connected_by_certified_subgraph"] else "INDETERMINATE",
            "joint_promise_vertices": vertices * ORDERED_COIN_BASIS_COUNT,
            "joint_support_edges": coin_edges + selector_edges + replicated_bridge_edges,
            "replicated_bridge_support_edges": replicated_bridge_edges,
            "seed": int(source["seed"]),
            "selected_bridge_count": bridges,
            "selected_bridge_sha256": [
                str(bridge["bridge_sha256"])
                for bridge in source.get("selected_bridges") or []
            ],
            "selector_one_swap_support_edges": selector_edges,
            "support_correspondence": "EXACT_V41_ONE_SWAP_SUPPORT_PLUS_AUTHENTICATED_DATA_ONLY_BRIDGES",
        }
        rows.append({**core, "seed_support_sha256": canonical_json_sha256(core)})
    aggregate_core = {
        "all_pair_positions_preserved": all(row["addressed_pair_positions_preserved"] == 780 for row in rows),
        "all_seeds_connected": all(row["connected"] is True and row["joint_component_count"] == 1 for row in rows),
        "coin_basis_states_per_data_vertex": ORDERED_COIN_BASIS_COUNT,
        "joint_promise_vertices": sum(int(row["joint_promise_vertices"]) for row in rows),
        "joint_support_edges": sum(int(row["joint_support_edges"]) for row in rows),
        "parent_selected_bridge_count": sum(int(row["selected_bridge_count"]) for row in rows),
        "seed_count": len(rows),
    }
    aggregate = {**aggregate_core, "aggregate_support_sha256": canonical_json_sha256(aggregate_core)}
    core = {
        "aggregate": aggregate,
        "joint_connectivity_theorem": "CONNECTED_COIN_CARTESIAN_SUPPORT_PLUS_EXACT_V41_DATA_SUPPORT",
        "seed_rows": rows,
    }
    return {**core, "support_evidence_sha256": canonical_json_sha256(core)}


def build_resource_evidence(
    parent_artifact: Mapping[str, Any],
    certificates: Mapping[int, Mapping[str, Any]],
    *,
    progress: Any | None = None,
) -> dict[str, Any]:
    compression = {
        int(row["seed"]): row
        for row in parent_artifact["compression_evidence"]["seed_rows"]
    }
    connectivity = {
        int(row["seed"]): row
        for row in parent_artifact["connectivity_evidence"]["seed_rows"]
    }
    seed_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        if progress is not None:
            progress(f"V4.2 coined-walk resource compiler · seed {seed}")
        seed_rows.append(
            compile_seed_walk(certificates[seed], compression[seed], connectivity[seed])
        )
    maximum = max(int(row["selected_model_step_resources"]["selected_model_cnot"]) for row in seed_rows)
    minimum_margin = min(int(row["budget_margin_cnot"]) for row in seed_rows)
    max_qubits = max(int(row["logical_qubits_with_recycled_workspace"]) for row in seed_rows)
    all_pass = all(row["decision"] == "PASSED" for row in seed_rows)
    parent_maximum = int(parent_artifact["resource_evidence"]["aggregate"]["r2_maximum_selected_model_cnot"])
    reduction_bps = (10_000 * (parent_maximum - maximum)) // parent_maximum
    aggregate_core = {
        "all_eight_seeds_pass": all_pass,
        "budget_cnot": BUDGET_CNOT,
        "maximum_logical_qubits_with_recycled_workspace": max_qubits,
        "maximum_selected_model_cnot": maximum,
        "minimum_budget_margin_cnot": minimum_margin,
        "parent_v41_r2_maximum_selected_model_cnot": parent_maximum,
        "selected_model": SELECTED_MODEL,
        "v41_to_v42_maximum_reduction_basis_points": reduction_bps,
    }
    aggregate = {**aggregate_core, "aggregate_resource_sha256": canonical_json_sha256(aggregate_core)}
    core = {
        "aggregate": aggregate,
        "architecture_id": "EXACT_ONE_HOT_COINED_TARGET_RECOMPUTE_ARITHMETIC_WITH_DATA_ONLY_BRIDGES_V1",
        "seed_rows": seed_rows,
    }
    return {**core, "resource_evidence_sha256": canonical_json_sha256(core)}


def _decisions(support: Mapping[str, Any], resources: Mapping[str, Any]) -> dict[str, str]:
    connected = bool((support.get("aggregate") or {}).get("all_seeds_connected"))
    admitted = bool((resources.get("aggregate") or {}).get("all_eight_seeds_pass"))
    if connected and admitted:
        return {
            "generator_support_decision": "CONNECTED_ALL_SEEDS_EXACT_V41_SUPPORT_PRESERVED",
            "next_falsifiable_gate": "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION",
            "overall": "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_PASSED",
            "production_admission": "PROVIDER_NEUTRAL_RESEARCH_GENERATOR_ADMITTED_HARDWARE_NOT_AUTHORIZED",
            "resource_architecture_decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET",
        }
    if connected:
        return {
            "generator_support_decision": "CONNECTED_ALL_SEEDS_EXACT_V41_SUPPORT_PRESERVED",
            "next_falsifiable_gate": "STRONGER_EXACT_ARITHMETIC_OR_NEW_PREREGISTERED_PROBLEM_REFORMULATION",
            "overall": "V42_INDEXED_COINED_WALK_CONNECTED_RESOURCE_SCREEN_REJECTED",
            "production_admission": "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED",
            "resource_architecture_decision": "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
        }
    return {
        "generator_support_decision": "INDETERMINATE",
        "next_falsifiable_gate": "REPAIR_OR_REJECT_COINED_GENERATOR_SUPPORT",
        "overall": "V42_COINED_WALK_INDETERMINATE",
        "production_admission": "BLOCKED_CONNECTIVITY_HARDWARE_NOT_AUTHORIZED",
        "resource_architecture_decision": "BLOCKED_BY_CONNECTIVITY",
    }


def build_v42_artifact(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
    deep_parent: bool = True,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v42_spec(root=base)
    parent = authenticate_v41_parent(root=base, deep=deep_parent)
    if not parent["valid"]:
        raise ValueError(f"V4.1 parent authentication failed: {parent['errors']}")
    parent_artifact = parent["artifact"]
    selector = run_selector_control(root=base)
    support = build_support_evidence(parent_artifact)
    certificates = _certificate_by_seed(base)
    resources = build_resource_evidence(
        parent_artifact,
        certificates,
        progress=progress,
    )
    decisions = _decisions(support, resources)
    artifact: dict[str, Any] = {
        "artifact_version": ARTIFACT_VERSION,
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "decisions": decisions,
        "engine_source_raw_file_sha256": raw_file_sha256(_paths(base)["engine"]),
        "parent": {
            "artifact_raw_file_sha256": EXPECTED_V41_ARTIFACT_RAW,
            "artifact_sha256": EXPECTED_V41_ARTIFACT_SHA,
            "freeze_raw_file_sha256": EXPECTED_V41_FREEZE_RAW,
            "freeze_sha256": EXPECTED_V41_FREEZE_SHA,
            "immutable_file_count": int(parent["immutable_v41_file_count"]),
            "immutable_files_exact": bool(parent["immutable_v41_files_exact"]),
            "overall_decision": str(parent_artifact["decisions"]["overall"]),
            "spec_raw_file_sha256": EXPECTED_V41_SPEC_RAW,
            "spec_sha256": EXPECTED_V41_SPEC_SHA,
        },
        "research_classification": "RESEARCH_ONLY",
        "resource_evidence": resources,
        "selector_control": selector,
        "source_sha256": source_sha256(),
        "spec_raw_file_sha256": raw_file_sha256(_paths(base)["spec"]),
        "spec_sha256": spec["v42_spec_sha256"],
        "support_evidence": support,
        "v42_version": V42_VERSION,
    }
    artifact["artifact_sha256"] = canonical_json_sha256(artifact)
    return artifact


def validate_v42_artifact(
    payload: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    checks: dict[str, bool] = {
        "artifact_self_hash": False,
        "artifact_version": False,
        "spec_source_engine_identity": False,
        "claim_boundary_exact": False,
        "parent_exact": False,
        "selector_control_exact": False,
        "support_evidence_exact": False,
        "resource_evidence_exact": False,
        "decisions_exact": False,
        "all_pair_positions_preserved": False,
        "joint_support_connected_all_seeds": False,
        "promise_selector_exhaustive_controls_pass": False,
        "independent_resource_replay_all_seeds": False,
        "maximum_budget_gate_exact": False,
        "provider_hardware_advantage_zero": False,
        "complete_artifact_exact_rebuild": False,
    }
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return {"checks": checks, "errors": ["V4.2 artifact must be a mapping."], "failed_checks": list(checks), "valid": False}
    try:
        base = _root(root)
        spec = load_v42_spec(root=base)
        core = {key: copy.deepcopy(value) for key, value in payload.items() if key != "artifact_sha256"}
        checks["artifact_self_hash"] = payload.get("artifact_sha256") == canonical_json_sha256(core)
        checks["artifact_version"] = bool(
            payload.get("artifact_version") == ARTIFACT_VERSION
            and payload.get("v42_version") == V42_VERSION
        )
        checks["spec_source_engine_identity"] = bool(
            payload.get("spec_sha256") == EXPECTED_SPEC_SHA
            and payload.get("spec_raw_file_sha256") == raw_file_sha256(_paths(base)["spec"])
            and payload.get("source_sha256") == source_sha256()
            and payload.get("engine_source_raw_file_sha256") == EXPECTED_ENGINE_RAW
            and raw_file_sha256(_paths(base)["engine"]) == EXPECTED_ENGINE_RAW
        )
        checks["claim_boundary_exact"] = bool(
            payload.get("research_classification") == "RESEARCH_ONLY"
            and payload.get("claim_boundary") == spec["claim_boundary"]
        )
        parent = authenticate_v41_parent(root=base, deep=authenticate_parent)
        checks["parent_exact"] = bool(
            parent["valid"]
            and payload.get("parent", {}).get("artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA
            and payload.get("parent", {}).get("immutable_file_count") == 159
            and payload.get("parent", {}).get("immutable_files_exact") is True
        )
        if not parent["valid"]:
            errors.extend(parent["errors"])
        parent_artifact = parent["artifact"]
        selector = run_selector_control(root=base)
        support = build_support_evidence(parent_artifact)
        resources = build_resource_evidence(parent_artifact, _certificate_by_seed(base))
        decisions = _decisions(support, resources)
        checks["selector_control_exact"] = payload.get("selector_control") == selector
        checks["support_evidence_exact"] = payload.get("support_evidence") == support
        checks["resource_evidence_exact"] = payload.get("resource_evidence") == resources
        checks["decisions_exact"] = payload.get("decisions") == decisions
        sealed_support = payload.get("support_evidence") or {}
        support_rows = sealed_support.get("seed_rows") or []
        support_aggregate = sealed_support.get("aggregate") or {}
        checks["all_pair_positions_preserved"] = bool(
            len(support_rows) == 8
            and support_aggregate.get("all_pair_positions_preserved") is True
            and all(row.get("addressed_pair_positions_preserved") == 780 for row in support_rows)
        )
        checks["joint_support_connected_all_seeds"] = bool(
            support_aggregate.get("all_seeds_connected") is True
            and all(row.get("joint_component_count") == 1 for row in support_rows)
        )
        control = payload.get("selector_control") or {}
        forward = control.get("forward") or {}
        checks["promise_selector_exhaustive_controls_pass"] = bool(
            control.get("stable_replay_match") is True
            and forward.get("valid") is True
            and forward.get("selector_failures") == 0
            and forward.get("cleanup_failures") == 0
            and forward.get("joint_component_failures") == 0
            and forward.get("full_domain_joint_failures") == 0
        )
        resource_rows = (payload.get("resource_evidence") or {}).get("seed_rows") or []
        checks["independent_resource_replay_all_seeds"] = bool(
            len(resource_rows) == 8
            and all(
                row.get("independent_cnot_formula_replay", {}).get("match") is True
                and row.get("independent_cnot_formula_replay", {}).get("replay_selected_model_cnot")
                == row.get("selected_model_step_resources", {}).get("selected_model_cnot")
                for row in resource_rows
            )
        )
        aggregate = (payload.get("resource_evidence") or {}).get("aggregate") or {}
        checks["maximum_budget_gate_exact"] = bool(
            aggregate.get("maximum_selected_model_cnot") == 1_135_430
            and aggregate.get("minimum_budget_margin_cnot") == 1_364_570
            and aggregate.get("all_eight_seeds_pass") is True
            and decisions["resource_architecture_decision"] == "PASSED_SELECTED_MODEL_CNOT_BUDGET"
        )
        boundary = payload.get("claim_boundary") or {}
        checks["provider_hardware_advantage_zero"] = bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("hardware_executable") is False
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        )
        rebuilt = build_v42_artifact(root=base, deep_parent=authenticate_parent)
        checks["complete_artifact_exact_rebuild"] = payload == rebuilt
    except Exception as exc:
        errors.append(str(exc))
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "checks": checks,
        "checks_passed": len(checks) - len(failed),
        "checks_total": len(checks),
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": not errors and not failed,
        "validator": "QUANTUM LAB V4.2 ARTIFACT VALIDATOR · V1",
    }


def default_v42_artifact_path(*, root: str | Path | None = None) -> Path:
    return _root(root) / "outputs" / "quantum_phase3" / "v42_coined_walk" / DEFAULT_ARTIFACT_NAME


def seal_v42_artifact(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v42_artifact_path(root=root)
    payload = build_v42_artifact(root=root, deep_parent=True)
    validation = validate_v42_artifact(payload, root=root, authenticate_parent=True)
    if not validation["valid"]:
        raise ValueError(f"Refusing to seal invalid V4.2 artifact: {validation}")
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V4.2 artifact: {target}")
        return {"artifact": payload, "created": False, "path": str(target), "validation": validation}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded, encoding="utf-8")
    return {"artifact": payload, "created": True, "path": str(target), "validation": validation}


def load_v42_artifact(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
    authenticate_parent: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v42_artifact_path(root=root)
    payload = _read_json_strict(target)
    return payload, validate_v42_artifact(
        payload,
        root=root,
        authenticate_parent=authenticate_parent,
    )


__all__ = [
    "ARTIFACT_VERSION",
    "BUDGET_CNOT",
    "DEFAULT_ARTIFACT_NAME",
    "K",
    "N",
    "SEEDS",
    "V42_VERSION",
    "authenticate_v41_parent",
    "build_resource_evidence",
    "build_support_evidence",
    "build_v42_artifact",
    "canonical_json_sha256",
    "compile_feasibility_oracle",
    "compile_seed_walk",
    "compile_selector_engine",
    "default_v42_artifact_path",
    "load_v42_artifact",
    "load_v42_spec",
    "run_selector_control",
    "seal_v42_artifact",
    "selected_model_cnot_from_terms",
    "validate_v42_artifact",
]
