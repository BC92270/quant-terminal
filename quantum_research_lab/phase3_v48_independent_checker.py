"""Standard-library independent checker for the sealed Quantum Lab V4.8 artifact.

This module deliberately does not import the V4.8 optimizer.  It authenticates
the predecessor bytes, recomputes every JSON commitment and aggregate, checks
the compact routing invariants, and independently replays the adder's
computational-basis permutation tests.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import random
from typing import Any, Mapping, Sequence


EXPECTED_CHECK_COUNT = 65
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_OVERALL = (
    "V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_"
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED"
)
EXPECTED_MULTI_SNAPSHOT = (
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_"
    "INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES"
)
EXPECTED_PRODUCTION = "RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED"

V45_PATH = "outputs/quantum_phase3/v45_width_reduction/SEALED_V4_5_PROOF_CARRYING_WIDTH_REDUCTION_ARTIFACT.json"
V46_PATH = "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"
V47_PATH = "outputs/quantum_phase3/v47_dated_properties/SEALED_V4_7_DATED_PROPERTIES_OPTIMIZATION_ARTIFACT.json"
FREEZE_PATH = "FREEZE_CONTRACT_V4_7.json"
CATALOG_PATH = "quantum_research_lab/PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json"
SNAPSHOTS_PATH = "quantum_research_lab/PHASE_III_V4_8_NORMALIZED_SNAPSHOTS_ORACLE_V1.json"
MODEL_PATH = "quantum_research_lab/PHASE_III_V4_8_ROBUSTNESS_COST_MODEL_V1.json"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_8_MULTI_SNAPSHOT_CZ_REDUCTION_SPEC_V1.json"
ORACLE_PATH = "quantum_research_lab/PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json"
NORMALIZED_V47_PATH = "quantum_research_lab/PHASE_III_V4_7_NORMALIZED_PROPERTIES_ORACLE_V1.json"

EXPECTED_RAW = {
    V45_PATH: "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257",
    V46_PATH: "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694",
    V47_PATH: "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185",
    FREEZE_PATH: "89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a",
}
EXPECTED_SEMANTIC = {
    V45_PATH: ("artifact_sha256", "9ab980071cc247cdbc70e8f964ccfbb09c48997d1d14cc26148c39518facda45"),
    V46_PATH: ("artifact_sha256", "cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832"),
    V47_PATH: ("artifact_sha256", "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf"),
    FREEZE_PATH: ("freeze_contract_sha256", "3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858"),
}


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


def _duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_strict(path: str | Path) -> dict[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected object: {path}")
    return payload


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return payload.get(field) == canonical_json_sha256(
        {key: value for key, value in payload.items() if key != field}
    )


def _load_parent(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    for relative, expected_raw in EXPECTED_RAW.items():
        path = root / relative
        if not path.is_file() or path.is_symlink() or raw_file_sha256(path) != expected_raw:
            raise ValueError(f"Parent raw identity mismatch: {relative}")
        payload = read_json_strict(path)
        field, expected_semantic = EXPECTED_SEMANTIC[relative]
        if payload.get(field) != expected_semantic or not _self_hash(payload, field):
            raise ValueError(f"Parent semantic identity mismatch: {relative}")
        loaded[relative] = payload
    return (
        loaded[V45_PATH],
        loaded[V46_PATH],
        loaded[V47_PATH],
        loaded[FREEZE_PATH],
    )


def _full_adder_ops(width: int) -> tuple[tuple[str, tuple[int, ...]], ...]:
    # The V4.8 macro uses the V4.3 Figure-5 adder over width-1 A/B bits,
    # with B[width-1] as z, then one final CX(A[width-1], B[width-1]).
    n = width - 1
    a = tuple(1 + index for index in range(width))
    b = tuple(1 + width + index for index in range(width))
    carry = 1 + 2 * width
    aa, bb, z = a[:-1], b[:-1], b[-1]
    ops: list[tuple[str, tuple[int, ...]]] = []
    for index in range(1, n):
        ops.append(("CX", (aa[index], bb[index])))
    ops.extend((("CX", (aa[1], carry)), ("CCX", (aa[0], bb[0], carry)), ("CX", (aa[2], aa[1])), ("CCX", (carry, bb[1], aa[1])), ("CX", (aa[3], aa[2]))))
    for index in range(2, n - 2):
        ops.extend((("CCX", (aa[index - 1], bb[index], aa[index])), ("CX", (aa[index + 2], aa[index + 1]))))
    ops.extend((("CCX", (aa[n - 3], bb[n - 2], aa[n - 2])), ("CX", (aa[n - 1], z)), ("CCX", (aa[n - 2], bb[n - 1], z))))
    for index in range(1, n - 1):
        ops.append(("X", (bb[index],)))
    ops.append(("CX", (carry, bb[1])))
    for index in range(2, n):
        ops.append(("CX", (aa[index - 1], bb[index])))
    ops.append(("CCX", (aa[n - 3], bb[n - 2], aa[n - 2])))
    for index in range(n - 3, 1, -1):
        ops.extend((("CCX", (aa[index - 1], bb[index], aa[index])), ("CX", (aa[index + 2], aa[index + 1])), ("X", (bb[index + 1],))))
    ops.extend((("CCX", (carry, bb[1], aa[1])), ("CX", (aa[3], aa[2])), ("X", (bb[2],)), ("CCX", (aa[0], bb[0], carry)), ("CX", (aa[2], aa[1])), ("X", (bb[1],)), ("CX", (aa[1], carry))))
    for index in range(n):
        ops.append(("CX", (aa[index], bb[index])))
    ops.append(("CX", (a[-1], b[-1])))
    return tuple(ops)


def _simulate(width: int, control: int, work: int, value: int, candidate: bool) -> tuple[int, int, int]:
    encoded = value & ((1 << width) - 1)
    a0, b0, carry = 1, 1 + width, 1 + 2 * width
    bits = [0] * (carry + 1)
    bits[0] = control
    for index in range(width):
        bits[b0 + index] = (work >> index) & 1

    def x(q: int) -> None:
        bits[q] ^= 1

    def cx(a: int, b: int) -> None:
        bits[b] ^= bits[a]

    def ccx(a: int, b: int, c: int) -> None:
        bits[c] ^= bits[a] & bits[b]

    def c3x(a: int, b: int, c: int, d: int) -> None:
        bits[d] ^= bits[a] & bits[b] & bits[c]

    for index in range(width):
        if (encoded >> index) & 1:
            (cx(0, a0 + index) if candidate else x(a0 + index))
    for name, q in _full_adder_ops(width):
        if candidate:
            {"X": lambda: x(q[0]), "CX": lambda: cx(q[0], q[1]), "CCX": lambda: ccx(q[0], q[1], q[2])}[name]()
        else:
            {"X": lambda: cx(0, q[0]), "CX": lambda: ccx(0, q[0], q[1]), "CCX": lambda: c3x(0, q[0], q[1], q[2])}[name]()
    for index in range(width - 1, -1, -1):
        if (encoded >> index) & 1:
            (cx(0, a0 + index) if candidate else x(a0 + index))
    return (
        sum(bits[b0 + index] << index for index in range(width)),
        sum(bits[a0 + index] << index for index in range(width)),
        bits[carry],
    )


def _independent_equivalence() -> dict[str, Any]:
    rng = random.Random(480_048)
    cases: list[tuple[int, int, int, int]] = []
    for width in (5, 6):
        for control in (0, 1):
            for work in range(1 << width):
                for value in range(1 << width):
                    cases.append((width, control, work, value))
    for width in (7, 8, 16, 31, 33, 34, 35, 36, 39):
        for _ in range(2_000):
            cases.append((width, rng.randrange(2), rng.randrange(1 << width), rng.randrange(-(1 << width), 1 << width)))
    transcript = hashlib.sha256()
    valid = True
    for width, control, work, value in cases:
        legacy = _simulate(width, control, work, value, False)
        candidate = _simulate(width, control, work, value, True)
        expected = ((work + control * value) & ((1 << width) - 1), 0, 0)
        transcript.update(f"{width}|{control}|{work}|{value}|{candidate}\n".encode("ascii"))
        valid &= legacy == candidate == expected
    return {"case_count": len(cases), "transcript_sha256": transcript.hexdigest(), "valid": valid}


def _bijection(layout: Mapping[str, Any]) -> bool:
    logical_to_physical = layout.get("final_logical_to_physical") or []
    physical_to_logical = layout.get("final_physical_to_logical") or []
    logical_qubits = int(layout.get("logical_qubits", -1))
    if len(logical_to_physical) != logical_qubits or len(set(logical_to_physical)) != logical_qubits:
        return False
    return all(
        0 <= int(physical) < len(physical_to_logical)
        and physical_to_logical[int(physical)] == logical
        for logical, physical in enumerate(logical_to_physical)
    )


def validate_v48_artifact(
    artifact: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    artifact_raw_file_sha256: str | None = None,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    base = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    checks: dict[str, bool] = {}
    errors: list[str] = []
    try:
        v45, v46, v47, freeze = _load_parent(base)
        catalog = read_json_strict(base / CATALOG_PATH)
        snapshots = read_json_strict(base / SNAPSHOTS_PATH)
        model = read_json_strict(base / MODEL_PATH)
        spec = read_json_strict(base / SPEC_PATH)
        oracle = read_json_strict(base / ORACLE_PATH)
        normalized = read_json_strict(base / NORMALIZED_V47_PATH)
    except Exception as exc:
        return {
            "check_count": EXPECTED_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["authenticated_inputs"],
            "valid": False,
        }

    semantic = canonical_json_sha256({key: value for key, value in artifact.items() if key != "artifact_sha256"})
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    aggregate = artifact.get("aggregate") or {}
    rows = artifact.get("seed_evaluations") or []
    checks.update(
        {
            "artifact_self_hash": artifact.get("artifact_sha256") == semantic,
            "artifact_expected_semantic_pin": expected_artifact_sha256 in (None, artifact.get("artifact_sha256")),
            "artifact_expected_raw_pin": expected_artifact_raw_sha256 in (None, artifact_raw_file_sha256),
            "artifact_version": artifact.get("artifact_version") == "PHASE III · V4.8 SEALED MULTI-SNAPSHOT / ARCHITECTURE ARTIFACT · V1",
            "research_classification": artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("research_classification") == "RESEARCH_ONLY",
            "hardware_false": boundary.get("hardware_executable") is False,
            "zero_external_operations": all(boundary.get(key) == 0 for key in ("provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted", "credential_reads")),
            "provider_sdk_not_imported": boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False,
            "no_current_snapshot_claim": boundary.get("snapshot_is_current_hardware_evidence") is False,
            "no_advantage_claim": boundary.get("quantum_advantage") == "NOT_CLAIMED",
            "overall_decision": decisions.get("overall") == EXPECTED_OVERALL,
            "production_decision": decisions.get("production_admission") == EXPECTED_PRODUCTION,
            "multi_snapshot_decision": decisions.get("multi_snapshot_robustness") == EXPECTED_MULTI_SNAPSHOT,
            "architecture_decision": decisions.get("architecture_candidate") == "PASS_EXACT_CONTROL_LOADED_CUCCARO_REDUCTION_ALL_EIGHT",
            "routing_decision": decisions.get("structural_routing") == "PASS_STRICT_BASICSWAP_CZ_REDUCTION_ALL_EIGHT",
            "lower_bound_decision": decisions.get("v47_comparable_lower_bound") == "FAIL_BOTH_NECESSARY_SCREENS_ALL_EIGHT",
            "parent_v45_exact": artifact.get("parent", {}).get("v45_artifact_sha256") == v45.get("artifact_sha256"),
            "parent_v46_exact": artifact.get("parent", {}).get("v46_artifact_sha256") == v46.get("artifact_sha256"),
            "parent_v47_exact": artifact.get("parent", {}).get("v47_artifact_sha256") == v47.get("artifact_sha256"),
            "parent_freeze_exact": artifact.get("parent", {}).get("v47_freeze_sha256") == freeze.get("freeze_contract_sha256") and freeze.get("frozen_file_count") == 272,
            "catalog_self_hash": _self_hash(catalog, "snapshot_catalog_sha256"),
            "snapshots_self_hash": _self_hash(snapshots, "normalized_snapshots_oracle_sha256"),
            "model_self_hash": _self_hash(model, "robustness_cost_model_sha256"),
            "spec_self_hash": _self_hash(spec, "v48_spec_sha256"),
            "architecture_oracle_self_hash": oracle.get("v48_spec_sha256") == canonical_json_sha256({key: value for key, value in oracle.items() if key not in {"v48_spec_sha", "v48_spec_sha256"}}),
            "single_snapshot_identity": (catalog.get("counts") or {}).get("distinct_epoch_count") == 1 and (catalog.get("counts") or {}).get("unique_raw_snapshot_identity_count") == 1,
            "zero_snapshot_aliases": catalog.get("aliases") == [] and (catalog.get("counts") or {}).get("admitted_alias_count") == 0,
            "multi_snapshot_ineligible": (snapshots.get("cohort") or {}).get("multi_snapshot_eligible") is False,
            "reference_crosslinks": (artifact.get("reference_contracts") or {}).get("snapshot_catalog_sha256") == catalog.get("snapshot_catalog_sha256") and (artifact.get("reference_contracts") or {}).get("normalized_snapshots_oracle_sha256") == snapshots.get("normalized_snapshots_oracle_sha256") and (artifact.get("reference_contracts") or {}).get("robustness_cost_model_sha256") == model.get("robustness_cost_model_sha256") and artifact.get("spec_sha256") == spec.get("v48_spec_sha256"),
            "eight_seed_order": tuple(int(row.get("seed", -1)) for row in rows) == EXPECTED_SEEDS,
            "eight_width_order": tuple(int(row.get("logical_qubits", -1)) for row in rows) == EXPECTED_WIDTHS,
        }
    )

    independent_equivalence = _independent_equivalence()
    sealed_equivalence = artifact.get("equivalence_evidence") or {}
    checks.update(
        {
            "independent_equivalence_28240": independent_equivalence["valid"] is True and independent_equivalence["case_count"] == 28_240,
            "equivalence_transcript_exact": independent_equivalence["transcript_sha256"] == sealed_equivalence.get("transcript_sha256"),
            "sealed_equivalence_self_hash": _self_hash(sealed_equivalence, "equivalence_evidence_sha256"),
            "sealed_equivalence_clean_exit": sealed_equivalence.get("all_cases_exact") is True and sealed_equivalence.get("clean_carry_and_constant_exit_all_cases") is True,
        }
    )

    v45_rows = {int(row["seed"]): row for row in v45.get("seed_materializations") or []}
    v46_rows = {int(row["seed"]): row for row in v46.get("seed_routings") or []}
    min_error = Decimal(str(normalized["statistics"]["gate_properties"]["cz"]["gate_error"]["minimum"]))
    min_duration = int(normalized["statistics"]["gate_properties"]["cz"]["duration_ticks"]["minimum"])
    max_t2_ticks = math.floor(Decimal(str(normalized["statistics"]["qubits"]["t2_seconds"]["maximum"])) / Decimal(str(normalized["backend"]["dt_seconds"])))
    row_flags: Counter[str] = Counter()
    recalculated: list[dict[str, int]] = []
    for row in rows:
        seed = int(row.get("seed", -1))
        manifest = row.get("candidate_stream_manifest") or {}
        routing = row.get("structural_routing") or {}
        routed = routing.get("routed_compilation") or {}
        native = routed.get("native_ledger") or {}
        layout = routed.get("layout") or {}
        route_ir = routed.get("route_ir") or {}
        routing_ledger = routed.get("routing_ledger") or {}
        comparison = row.get("comparison") or {}
        adder = routing.get("adder_evidence") or {}
        lower = row.get("architecture_lower_bound_v47_comparable") or {}
        parent45 = v45_rows.get(seed, {})
        parent46 = v46_rows.get(seed, {})
        candidate_cx = int((manifest.get("elementary_counts") or {}).get("CX", -1))
        candidate_cz = int((native.get("native_operation_counts") or {}).get("cz", -1))
        parent_cx = int(((parent45.get("stream_manifest") or {}).get("elementary_counts") or {}).get("CX", -2))
        parent_cz = int((((parent46.get("routed_compilation") or {}).get("native_ledger") or {}).get("native_operation_counts") or {}).get("cz", -2))
        row_flags["seed_self_hash"] += _self_hash(row, "seed_evaluation_sha256")
        row_flags["manifest_self_hash"] += _self_hash(manifest, "stream_manifest_sha256")
        row_flags["manifest_count_sum"] += int(manifest.get("instruction_count", -1)) == sum(int(value) for value in (manifest.get("elementary_counts") or {}).values())
        row_flags["routing_input_exact"] += routed.get("input_manifest_exact_parent") is True and routed.get("input_stream_manifest") == manifest
        row_flags["native_self_hash"] += _self_hash(native, "native_ledger_sha256")
        row_flags["layout_self_hash"] += _self_hash(layout, "layout_sha256") and _bijection(layout)
        row_flags["route_ir_self_hash"] += _self_hash(route_ir, "route_ir_sha256")
        row_flags["routing_ledger_self_hash"] += _self_hash(routing_ledger, "routing_ledger_sha256")
        row_flags["structural_self_hash"] += _self_hash(routing, "structural_routing_sha256")
        row_flags["comparison_self_hash"] += _self_hash(comparison, "comparison_sha256")
        row_flags["adder_self_hash"] += _self_hash(adder, "adder_evidence_sha256")
        row_flags["no_route_violations"] += native.get("coupling_violations") == native.get("isa_violations") == 0
        row_flags["cx_native_consistency"] += native.get("direct_translated_cx_count") == candidate_cx
        row_flags["cz_swap_identity"] += candidate_cz == candidate_cx + 3 * int(native.get("swap_count", -1))
        row_flags["parent_counts_exact"] += comparison.get("parent_v45_cx") == parent_cx and comparison.get("parent_v46_basic_swap_cz") == parent_cz
        row_flags["strict_reductions"] += comparison.get("candidate_cx") == candidate_cx < parent_cx and comparison.get("candidate_basic_swap_cz") == candidate_cz < parent_cz
        row_flags["adder_explains_cx_delta"] += parent_cx - candidate_cx == adder.get("adder_cx_reduction") == int(adder.get("legacy_adder_cx", -1)) - int(adder.get("candidate_adder_cx", -2))
        expected_mass = Decimal(candidate_cx) * min_error
        expected_duration = math.ceil(candidate_cx / 78) * min_duration
        row_flags["lower_self_hash"] += _self_hash(lower, "architecture_lower_bound_sha256")
        row_flags["lower_exact"] += lower.get("optimistic_reported_error_mass_lower_bound") == format(expected_mass, "f") and lower.get("optimistic_cz_duration_lower_bound_ticks") == expected_duration and lower.get("passes_reported_error_mass_screen") is (expected_mass < Decimal(1)) and lower.get("passes_duration_screen") is (expected_duration <= max_t2_ticks)
        recalculated.append({"candidate_cx": candidate_cx, "candidate_cz": candidate_cz, "parent_cx": parent_cx, "parent_cz": parent_cz, "depth": int(native.get("asap_structural_depth", 0)), "cx_bp": (10_000 * (parent_cx - candidate_cx)) // parent_cx, "cz_bp": (10_000 * (parent_cz - candidate_cz)) // parent_cz})
    for name in (
        "seed_self_hash", "manifest_self_hash", "manifest_count_sum", "routing_input_exact",
        "native_self_hash", "layout_self_hash", "route_ir_self_hash", "routing_ledger_self_hash",
        "structural_self_hash", "comparison_self_hash", "adder_self_hash", "no_route_violations",
        "cx_native_consistency", "cz_swap_identity", "parent_counts_exact", "strict_reductions",
        "adder_explains_cx_delta", "lower_self_hash", "lower_exact",
    ):
        checks[f"all_eight_{name}"] = row_flags[name] == 8

    aggregate_core = {key: value for key, value in aggregate.items() if key != "aggregate_sha256"}
    checks.update(
        {
            "aggregate_self_hash": aggregate.get("aggregate_sha256") == canonical_json_sha256(aggregate_core),
            "aggregate_seed_count": aggregate.get("seed_count") == len(recalculated) == 8,
            "aggregate_cx_exact": aggregate.get("aggregate_parent_v45_cx") == sum(row["parent_cx"] for row in recalculated) and aggregate.get("aggregate_candidate_cx") == sum(row["candidate_cx"] for row in recalculated),
            "aggregate_cz_exact": aggregate.get("aggregate_parent_v46_basic_swap_cz") == sum(row["parent_cz"] for row in recalculated) and aggregate.get("aggregate_candidate_basic_swap_cz") == sum(row["candidate_cz"] for row in recalculated),
            "aggregate_reductions_exact": aggregate.get("aggregate_cx_reduction") == sum(row["parent_cx"] - row["candidate_cx"] for row in recalculated) and aggregate.get("aggregate_basic_swap_cz_reduction") == sum(row["parent_cz"] - row["candidate_cz"] for row in recalculated),
            "aggregate_extrema_exact": aggregate.get("maximum_candidate_cx") == max(row["candidate_cx"] for row in recalculated) and aggregate.get("minimum_candidate_cx") == min(row["candidate_cx"] for row in recalculated) and aggregate.get("maximum_candidate_basic_swap_cz") == max(row["candidate_cz"] for row in recalculated) and aggregate.get("maximum_candidate_structural_depth") == max(row["depth"] for row in recalculated),
            "aggregate_minimum_reductions_exact": aggregate.get("minimum_cx_reduction_basis_points") == min(row["cx_bp"] for row in recalculated) and aggregate.get("minimum_basic_swap_cz_reduction_basis_points") == min(row["cz_bp"] for row in recalculated),
            "aggregate_architecture_pass": aggregate.get("all_eight_candidate_streams_materialized") is True and aggregate.get("all_eight_logical_cx_reduced") is True and aggregate.get("all_eight_basic_swap_routes_materialized") is True,
            "aggregate_multi_snapshot_blocked": aggregate.get("multi_snapshot_distinct_authentic_snapshot_count") == 1 and aggregate.get("multi_snapshot_robustness_evaluable") is False,
            "aggregate_lower_bounds_fail": aggregate.get("all_eight_architecture_lower_bounds_pass_duration_screen") is False and aggregate.get("all_eight_architecture_lower_bounds_pass_reported_error_mass_screen") is False and row_flags["lower_exact"] == 8,
            "ordered_seed_root_exact": aggregate.get("ordered_seed_evaluation_root_sha256") == canonical_json_sha256([row.get("seed_evaluation_sha256") for row in rows]),
        }
    )
    if EXPECTED_CHECK_COUNT and len(checks) != EXPECTED_CHECK_COUNT:
        errors.append(f"Checker contract count drift: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": errors,
        "failed_checks": failed,
        "independent_equivalence": independent_equivalence,
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V4.8 STANDARD-LIBRARY INDEPENDENT CHECKER · V1",
    }


__all__ = [
    "EXPECTED_CHECK_COUNT",
    "canonical_json_sha256",
    "raw_file_sha256",
    "read_json_strict",
    "validate_v48_artifact",
]
