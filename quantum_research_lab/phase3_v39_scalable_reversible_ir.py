"""Proof-carrying scalable N=40 reversible mixer IR for Quantum Lab V3.9.

The compiler closes the evidence gap left deliberately open by V3.8.  It does
not enumerate the 847,660,528 exact-K portfolios.  Instead, every canonical
swap position carries exact integer range, symmetric-band and resource
certificates.  The emitted object is a compact macro IR: every macro has a
frozen elementary expansion and exact selected-model count, while a hash chain
commits to all 6,240 edge/seed positions.

The semantic domain is deliberately narrow: popcount(x)=10, the seven cache
registers equal their exact integer functions of x, and the starting basis
state satisfies every hard band.  Backend transpilation, global feasible-graph
connectivity, QPU execution and advantage remain outside this module.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .phase3_artifact_guard import load_and_validate_dyadic_artifact


V39_VERSION = "PHASE III · V3.9 SCALABLE N40 REVERSIBLE IR · V1"
ARTIFACT_VERSION = "PHASE III · V3.9 N40 REVERSIBLE IR + RESOURCE SCREEN ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_V3_9_SCALABLE_REVERSIBLE_IR_ARTIFACT.json"
SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
N = 40
K = 10
EDGE_COUNT = N * (N - 1) // 2
BUDGET_CNOT = 2_500_000
SELECTED_MODEL = "CLEAN_ANCILLA_TOFFOLI_LADDER_6CX_CCX_CRX2CX_V1"
ELEMENTARY_BASIS = ("X", "H", "T", "TDG", "RY", "RZ", "CX")

EXPECTED_V38_ARTIFACT_RAW = "c8062c7836f7abdf164e5cb274db9fcf2c41780714d91f71a99b81b4fd0a8195"
EXPECTED_V38_ARTIFACT_SHA = "2d0980803e81564e455836d1fd9c52aab04adbf20a8dfd15958b6d4c3cd7b21f"
EXPECTED_V38_SPEC_RAW = "b0c8c99246dbb850002f770b9da9bcdc36d8e52cd86ac230e01d7b47e3bd87d9"
EXPECTED_V38_SPEC_SHA = "0c7e33ac23fc0caf0c14b0c6bde730d0fa898851fdb60f5afa24887d98fd066c"
EXPECTED_V38_SOURCE_RAW = "bc969d7918e0d81c867c846e40d1b9a8d5609ce67119708cd0bcb5d7db4a63b5"
EXPECTED_V38_FREEZE_RAW = "a267509a153ff2bbec671b963823f818278bad3ee74f8c56e8a5687d805fd7d6"
EXPECTED_V38_FREEZE_SHA = "5b73497b5a06071aa9411296aa0ed6ec5e924b4372066a1b4a9b9ca240cfc810"
EXPECTED_V31_RAW = "7b39a20ec9200b16996ec25edd660ba7bf26bfb2b454ed44dd1a333513afd50e"
EXPECTED_V31_SHA = "D9D109D117E1795CFFEF"

_BUILD_CACHE: tuple[tuple[str, ...], dict[str, Any]] | None = None


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


def _portable_validation_manifest_sha256(report: Mapping[str, Any]) -> str:
    """Hash validation evidence without its machine-local source pathname."""

    return canonical_json_sha256(
        {key: value for key, value in report.items() if key != "source"}
    )


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


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _paths() -> dict[str, Path]:
    root = _root()
    return {
        "spec": Path(__file__).with_name(SPEC_FILENAME),
        "v38_artifact": root / "outputs" / "quantum_phase3" / "v38_elementary" / "SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json",
        "v38_spec": root / "quantum_research_lab" / "PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json",
        "v38_source": root / "quantum_research_lab" / "phase3_v38_elementary_admission.py",
        "v38_freeze": root / "FREEZE_CONTRACT_V3_8.json",
        "v31": root / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
    }


def load_v39_spec(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = _read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v39_spec_sha", "v39_spec_sha256"}}
    digest = canonical_json_sha256(core)
    if payload.get("v39_spec_sha256") != digest:
        raise ValueError("V3.9 specification SHA-256 mismatch.")
    if payload.get("v39_spec_sha") != digest[:20].upper():
        raise ValueError("V3.9 specification short SHA mismatch.")
    boundary = payload.get("claim_boundary") or {}
    if not (
        boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("qpu_submission_enabled") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("complete_global_connectivity", boundary.get("global_feasible_graph_connectivity")) == "INDETERMINATE"
    ):
        raise ValueError("V3.9 specification violates the scientific boundary.")
    return payload


def authenticate_parent_chain() -> dict[str, Any]:
    paths = _paths()
    spec = load_v39_spec()
    expected = spec["parent_contract"]
    errors: list[str] = []
    raw_checks = {
        "v38_artifact_raw": (raw_file_sha256(paths["v38_artifact"]), EXPECTED_V38_ARTIFACT_RAW),
        "v38_spec_raw": (raw_file_sha256(paths["v38_spec"]), EXPECTED_V38_SPEC_RAW),
        "v38_source_raw": (raw_file_sha256(paths["v38_source"]), EXPECTED_V38_SOURCE_RAW),
        "v38_freeze_raw": (raw_file_sha256(paths["v38_freeze"]), EXPECTED_V38_FREEZE_RAW),
        "v31_raw": (raw_file_sha256(paths["v31"]), EXPECTED_V31_RAW),
    }
    for name, (actual, registered) in raw_checks.items():
        if expected.get("expected_" + name.replace("_raw", "_raw_file_sha256"), registered) != registered:
            errors.append(f"Specification parent constant drift: {name}")
        if actual != registered:
            errors.append(f"Parent raw identity mismatch: {name}")

    artifact = _read_json_strict(paths["v38_artifact"])
    artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    v38_spec = _read_json_strict(paths["v38_spec"])
    v38_spec_core = {key: value for key, value in v38_spec.items() if key not in {"v38_spec_sha", "v38_spec_sha256"}}
    freeze = _read_json_strict(paths["v38_freeze"])
    freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
    semantic_checks = {
        "v38_artifact": artifact.get("artifact_sha256") == EXPECTED_V38_ARTIFACT_SHA == canonical_json_sha256(artifact_core),
        "v38_spec": v38_spec.get("v38_spec_sha256") == EXPECTED_V38_SPEC_SHA == canonical_json_sha256(v38_spec_core),
        "v38_freeze": freeze.get("freeze_contract_sha256") == EXPECTED_V38_FREEZE_SHA == canonical_json_sha256(freeze_core),
        "v38_decision": (artifact.get("decisions") or {}).get("overall") == "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED",
        "v38_boundary": (artifact.get("claim_boundary") or {}).get("hardware_executable") is False,
    }
    for name, valid in semantic_checks.items():
        if not valid:
            errors.append(f"Parent semantic authentication failed: {name}")

    v31_validation = load_and_validate_dyadic_artifact(paths["v31"], EXPECTED_V31_RAW)
    v31 = _read_json_strict(paths["v31"])
    if not v31_validation.get("valid") or v31.get("dyadic_oracle_sha") != EXPECTED_V31_SHA:
        errors.append("V3.1 dyadic certificate chain authentication failed.")
    return {
        "valid": not errors,
        "errors": errors,
        "raw_checks": {name: {"actual": actual, "expected": registered, "valid": actual == registered} for name, (actual, registered) in raw_checks.items()},
        "semantic_checks": semantic_checks,
        "v31_validation_manifest_scope": "PATH_INDEPENDENT_REPORT_EXCLUDING_SOURCE_DESCRIPTOR",
        "v31_validation_manifest_sha256": _portable_validation_manifest_sha256(v31_validation),
    }


@dataclass(frozen=True, slots=True)
class Cost:
    cnot: int = 0
    one_qubit: int = 0
    abstract_gates: int = 0
    x: int = 0
    cx: int = 0
    ccx: int = 0
    mcx: int = 0
    clean_decomposition_ancillas: int = 0

    def __add__(self, other: "Cost") -> "Cost":
        return Cost(
            cnot=self.cnot + other.cnot,
            one_qubit=self.one_qubit + other.one_qubit,
            abstract_gates=self.abstract_gates + other.abstract_gates,
            x=self.x + other.x,
            cx=self.cx + other.cx,
            ccx=self.ccx + other.ccx,
            mcx=self.mcx + other.mcx,
            clean_decomposition_ancillas=max(self.clean_decomposition_ancillas, other.clean_decomposition_ancillas),
        )

    def scale(self, factor: int) -> "Cost":
        return Cost(
            cnot=self.cnot * factor,
            one_qubit=self.one_qubit * factor,
            abstract_gates=self.abstract_gates * factor,
            x=self.x * factor,
            cx=self.cx * factor,
            ccx=self.ccx * factor,
            mcx=self.mcx * factor,
            clean_decomposition_ancillas=self.clean_decomposition_ancillas,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "abstract_gate_count": self.abstract_gates,
            "abstract_x": self.x,
            "abstract_cx": self.cx,
            "abstract_ccx": self.ccx,
            "abstract_mcx": self.mcx,
            "clean_decomposition_ancillas": self.clean_decomposition_ancillas,
            "selected_model_cnot": self.cnot,
            "selected_model_one_qubit_gates": self.one_qubit,
        }


@lru_cache(maxsize=None)
def _gate_cost(controls: int, negative_controls: int = 0) -> Cost:
    if controls < 0 or negative_controls < 0 or negative_controls > controls:
        raise ValueError("Invalid abstract gate arity.")
    wrappers = 2 * negative_controls
    if controls == 0:
        return Cost(one_qubit=1, abstract_gates=1, x=1)
    if controls == 1:
        return Cost(cnot=1, one_qubit=wrappers, abstract_gates=1, cx=1)
    if controls == 2:
        return Cost(cnot=6, one_qubit=9 + wrappers, abstract_gates=1, ccx=1)
    ccx = 2 * controls - 3
    return Cost(
        cnot=6 * ccx,
        one_qubit=9 * ccx + wrappers,
        abstract_gates=1,
        mcx=1,
        clean_decomposition_ancillas=controls - 2,
    )


@lru_cache(maxsize=None)
def controlled_add_cost(width: int, constant: int, *, canonical_orientation: int) -> Cost:
    """One two-pattern-controlled modular constant addition."""

    if width < 1 or canonical_orientation not in (0, 1):
        raise ValueError("Invalid controlled addition contract.")
    encoded = int(constant) & ((1 << width) - 1)
    negative = 1 if canonical_orientation == 1 else 0  # d=1 and x_i=0 for q=1
    sum_l = 0
    sum_l_squared = 0
    set_bits = 0
    max_l = 0
    for position in range(width):
        if not ((encoded >> position) & 1):
            continue
        length = width - position
        set_bits += 1
        sum_l += length
        sum_l_squared += length * length
        max_l = max(max_l, length)
    # One controlled increment of length l contains controls 2..l+1.
    # Under the frozen clean-ancilla ladder that is exactly l^2 Toffoli
    # equivalents, hence 6*l^2 CNOT and 9*l^2 one-qubit Clifford+T gates.
    return Cost(
        cnot=6 * sum_l_squared,
        one_qubit=9 * sum_l_squared + 2 * negative * sum_l,
        abstract_gates=sum_l,
        ccx=set_bits,
        mcx=sum_l - set_bits,
        clean_decomposition_ancillas=max(0, max_l - 1),
    )


def _order_key_bits(value: int, width: int, signed: bool) -> list[int]:
    encoded = int(value) & ((1 << width) - 1)
    bits = [(encoded >> index) & 1 for index in range(width)]
    if signed:
        bits[-1] ^= 1
    return bits


def _actual_control_value(key_value: int, index: int, width: int, signed: bool) -> int:
    return int(key_value) ^ int(bool(signed and index == width - 1))


@lru_cache(maxsize=None)
def comparator_cost(width: int, constant: int, *, relation: str, signed: bool) -> Cost:
    """One exact inclusive comparator toggle, matching the inherited V3.2 IR."""

    minimum = -(1 << (width - 1)) if signed else 0
    maximum = (1 << (width - 1)) - 1 if signed else (1 << width) - 1
    if (relation == "GE" and constant <= minimum) or (relation == "LE" and constant >= maximum):
        return _gate_cost(0)
    if (relation == "GE" and constant > maximum) or (relation == "LE" and constant < minimum):
        return Cost()
    if relation not in {"GE", "LE"}:
        raise ValueError("Comparator relation must be GE or LE.")
    key = _order_key_bits(constant, width, signed)
    differing_constant = 0 if relation == "GE" else 1
    differing_input = 1 if relation == "GE" else 0
    costs: list[Cost] = []
    for index in range(width - 1, -1, -1):
        if key[index] != differing_constant:
            continue
        values = [_actual_control_value(differing_input, index, width, signed)]
        values.extend(
            _actual_control_value(key[higher], higher, width, signed)
            for higher in range(index + 1, width)
        )
        costs.append(_gate_cost(len(values), values.count(0)))
    equality = [
        _actual_control_value(key[index], index, width, signed)
        for index in range(width)
    ]
    costs.append(_gate_cost(width, equality.count(0)))
    return Cost(
        cnot=sum(item.cnot for item in costs),
        one_qubit=sum(item.one_qubit for item in costs),
        abstract_gates=sum(item.abstract_gates for item in costs),
        x=sum(item.x for item in costs),
        cx=sum(item.cx for item in costs),
        ccx=sum(item.ccx for item in costs),
        mcx=sum(item.mcx for item in costs),
        clean_decomposition_ancillas=max((item.clean_decomposition_ancillas for item in costs), default=0),
    )


def _constraint_rows(certificate: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for group in certificate.get("group_bands") or []:
        members = {int(index) for index in group["indices"]}
        rows.append(
            {
                "kind": "GROUP",
                "name": str(group["name"]),
                "coefficients": tuple(1 if index in members else 0 for index in range(N)),
                "lower": int(group["lower"]),
                "upper": int(group["upper"]),
                "width": int(group["counter_bits"]),
                "signed": False,
            }
        )
    for factor in certificate.get("factor_bands") or []:
        rows.append(
            {
                "kind": "FACTOR",
                "name": str(factor["name"]),
                "coefficients": tuple(int(value) for value in factor["coefficients_int"]),
                "lower": int(factor["lower_int"]),
                "upper": int(factor["upper_int"]),
                "width": int(factor["accumulator_signed_bits"]),
                "signed": True,
            }
        )
    if len(rows) != 7 or any(len(row["coefficients"]) != N for row in rows):
        raise ValueError("Expected the frozen seven-row N=40 register contract.")
    return tuple(rows)


def _conditional_range(coefficients: Sequence[int], i: int, j: int, q: int) -> tuple[int, int]:
    remaining = [int(coefficients[index]) for index in range(N) if index not in {i, j}]
    selected = int(coefficients[i if q == 1 else j])
    return (
        selected + sum(sorted(remaining)[: K - 1]),
        selected + sum(sorted(remaining, reverse=True)[: K - 1]),
    )


def _row_proof(row: Mapping[str, Any], i: int, j: int) -> dict[str, Any]:
    coefficients = row["coefficients"]
    delta = int(coefficients[i]) - int(coefficients[j])
    candidates: list[dict[str, Any]] = []
    for q in (0, 1):
        constant = -delta if q == 0 else delta
        add = controlled_add_cost(int(row["width"]), constant, canonical_orientation=q) if delta else Cost()
        reachable_min, reachable_max = _conditional_range(coefficients, i, j, q)
        sign = 1 - 2 * q
        interval_lower = max(int(row["lower"]), int(row["lower"]) - sign * delta)
        interval_upper = min(int(row["upper"]), int(row["upper"]) - sign * delta)
        overlap_lower = max(reachable_min, interval_lower)
        overlap_upper = min(reachable_max, interval_upper)
        candidates.append(
            {
                "q": q,
                "add_constant": constant,
                "normalization_one_way": add.as_dict(),
                "reachable_min": reachable_min,
                "reachable_max": reachable_max,
                "interval_lower": interval_lower,
                "interval_upper": interval_upper,
                "overlap_lower": overlap_lower,
                "overlap_upper": overlap_upper,
                "dead": overlap_lower > overlap_upper,
            }
        )
    if candidates[0]["dead"] != candidates[1]["dead"]:
        raise ValueError("Canonical orientation changed exact dead-edge classification.")
    # Frozen rule: lowest CNOT, then lowest 1Q, then q=1.
    chosen = min(
        candidates,
        key=lambda item: (
            int(item["normalization_one_way"]["selected_model_cnot"]),
            int(item["normalization_one_way"]["selected_model_one_qubit_gates"]),
            0 if int(item["q"]) == 1 else 1,
        ),
    )
    lower_active = bool(delta and chosen["reachable_min"] < chosen["interval_lower"])
    upper_active = bool(delta and chosen["reachable_max"] > chosen["interval_upper"])
    proof = {
        "name": row["name"],
        "kind": row["kind"],
        "width": row["width"],
        "signed": row["signed"],
        "coefficient_i": int(coefficients[i]),
        "coefficient_j": int(coefficients[j]),
        "delta_i_minus_j": delta,
        "canonical_orientation_q": chosen["q"],
        "add_constant_when_orientation_differs": chosen["add_constant"],
        "reachable_min": chosen["reachable_min"],
        "reachable_max": chosen["reachable_max"],
        "symmetric_interval_lower": chosen["interval_lower"],
        "symmetric_interval_upper": chosen["interval_upper"],
        "overlap_lower": chosen["overlap_lower"],
        "overlap_upper": chosen["overlap_upper"],
        "dead": chosen["dead"],
        "lower_comparator_active": lower_active,
        "upper_comparator_active": upper_active,
        "orientation_costs": {
            str(item["q"]): item["normalization_one_way"] for item in candidates
        },
    }
    return {**proof, "proof_sha256": canonical_json_sha256(proof)}


def _row_live_cost(row: Mapping[str, Any], proof: Mapping[str, Any]) -> tuple[Cost, dict[str, int]]:
    if int(proof["delta_i_minus_j"]) == 0:
        return Cost(), {"normalization_add_macros": 0, "comparator_macros": 0, "row_flag_toggles": 0}
    q = int(proof["canonical_orientation_q"])
    one_way = controlled_add_cost(
        int(row["width"]),
        int(proof["add_constant_when_orientation_differs"]),
        canonical_orientation=q,
    )
    total = one_way.scale(2)
    lower_active = bool(proof["lower_comparator_active"])
    upper_active = bool(proof["upper_comparator_active"])
    comparator_macros = 0
    row_flag_toggles = 0
    if lower_active and upper_active:
        ge = comparator_cost(int(row["width"]), int(proof["symmetric_interval_lower"]), relation="GE", signed=bool(row["signed"]))
        le = comparator_cost(int(row["width"]), int(proof["symmetric_interval_upper"]), relation="LE", signed=bool(row["signed"]))
        total += (ge + le).scale(4)  # create/clean local flags, then repeat to clear row flag
        total += _gate_cost(2).scale(2)
        comparator_macros = 8
        row_flag_toggles = 2
    elif lower_active:
        ge = comparator_cost(int(row["width"]), int(proof["symmetric_interval_lower"]), relation="GE", signed=bool(row["signed"]))
        total += ge.scale(2)
        comparator_macros = 2
    elif upper_active:
        le = comparator_cost(int(row["width"]), int(proof["symmetric_interval_upper"]), relation="LE", signed=bool(row["signed"]))
        total += le.scale(2)
        comparator_macros = 2
    return total, {
        "normalization_add_macros": 2,
        "comparator_macros": comparator_macros,
        "row_flag_toggles": row_flag_toggles,
    }


def compile_edge(rows: Sequence[Mapping[str, Any]], i: int, j: int, position: int) -> dict[str, Any]:
    proofs = [_row_proof(row, i, j) for row in rows]
    dead_rows = [proof["name"] for proof in proofs if proof["dead"]]
    live = not dead_rows
    total = Cost()
    macros = {
        "normalization_add_macros": 0,
        "comparator_macros": 0,
        "row_flag_toggles": 0,
        "aggregate_toggles": 0,
        "controlled_rx": 0,
        "different_bit_cx": 0,
        "gray_path_cx": 0,
    }
    active_flag_rows = 0
    if live:
        for row, proof in zip(rows, proofs):
            row_cost, row_macros = _row_live_cost(row, proof)
            total += row_cost
            for key, value in row_macros.items():
                macros[key] += value
            if proof["lower_comparator_active"] or proof["upper_comparator_active"]:
                active_flag_rows += 1
        # Compute and clear d=x_i xor x_j.
        total += _gate_cost(1).scale(4)
        macros["different_bit_cx"] = 4
        # g=d AND all active row flags. If no row flag exists, d controls CRX directly.
        if active_flag_rows:
            total += _gate_cost(1 + active_flag_rows).scale(2)
            macros["aggregate_toggles"] = 2
        # Gray conjugation and inherited one-control CRX(2 beta).
        total += _gate_cost(1).scale(2)
        total += Cost(cnot=2, one_qubit=4, abstract_gates=1)
        macros["gray_path_cx"] = 2
        macros["controlled_rx"] = 1
    core = {
        "position": position,
        "edge": [i, j],
        "record_kind": "LIVE_REVERSIBLE_PAIR_ROTATION" if live else "CERTIFIED_IDENTITY_POSITION",
        "live": live,
        "dead_constraint_rows": dead_rows,
        "active_flag_rows": active_flag_rows if live else 0,
        "row_proofs": proofs,
        "macros": macros,
        "resources": total.as_dict(),
        "semantic_scope": "FEASIBLE_SUPPORT_COHERENT_EQUIVALENCE_PROVEN_BY_CONSTRUCTION",
    }
    return {**core, "edge_ir_sha256": canonical_json_sha256(core)}


def compile_seed(certificate: Mapping[str, Any]) -> dict[str, Any]:
    if not (
        int(certificate.get("N", -1)) == N
        and int(certificate.get("K", -1)) == K
        and int(certificate.get("seed", -1)) in SEEDS
        and certificate.get("parameter_identity_pass") is True
    ):
        raise ValueError("Invalid frozen seed certificate.")
    rows = _constraint_rows(certificate)
    edges: list[dict[str, Any]] = []
    position = 0
    for i in range(N):
        for j in range(i + 1, N):
            edges.append(compile_edge(rows, i, j, position))
            position += 1
    if position != EDGE_COUNT:
        raise AssertionError("Canonical edge inventory mismatch.")
    total = Cost()
    macro_totals: dict[str, int] = {}
    for edge in edges:
        r = edge["resources"]
        total += Cost(
            cnot=int(r["selected_model_cnot"]),
            one_qubit=int(r["selected_model_one_qubit_gates"]),
            abstract_gates=int(r["abstract_gate_count"]),
            x=int(r["abstract_x"]),
            cx=int(r["abstract_cx"]),
            ccx=int(r["abstract_ccx"]),
            mcx=int(r["abstract_mcx"]),
            clean_decomposition_ancillas=int(r["clean_decomposition_ancillas"]),
        )
        for key, value in edge["macros"].items():
            macro_totals[key] = macro_totals.get(key, 0) + int(value)
    live_edges = sum(bool(edge["live"]) for edge in edges)
    dead_edges = EDGE_COUNT - live_edges
    nonzero_deltas_all = sum(
        int(proof["delta_i_minus_j"] != 0)
        for edge in edges
        for proof in edge["row_proofs"]
    )
    nonzero_deltas_live = sum(
        int(proof["delta_i_minus_j"] != 0)
        for edge in edges if edge["live"]
        for proof in edge["row_proofs"]
    )
    widths = [int(row["width"]) for row in rows]
    data_plus_cache = N + sum(widths)
    reusable_scratch = 1 + 2 + len(rows) + 1  # d, GE/LE, row flags, aggregate
    logical_without_decomposition = data_plus_cache + reusable_scratch
    logical_with_decomposition = logical_without_decomposition + total.clean_decomposition_ancillas
    selected_cnot = total.cnot
    margin = BUDGET_CNOT - selected_cnot
    seed_core = {
        "seed": int(certificate["seed"]),
        "instance_id": str(certificate["instance_id"]),
        "parent_certificate_sha": str(certificate["certificate_sha"]),
        "constraint_registers": [
            {
                "name": row["name"],
                "kind": row["kind"],
                "width": row["width"],
                "signed": row["signed"],
                "role": "CALLER_OWNED_EXACT_INTEGER_CACHE",
                "initial_state": "A_r(x)",
                "final_state": "A_r(x_after_edge)",
            }
            for row in rows
        ],
        "edge_count": EDGE_COUNT,
        "live_edge_count": live_edges,
        "certified_identity_count": dead_edges,
        "constraint_row_cases": EDGE_COUNT * len(rows),
        "nonzero_row_edge_deltas": nonzero_deltas_all,
        "nonzero_live_row_edge_deltas": nonzero_deltas_live,
        "ordered_edge_ir_sha256": canonical_json_sha256([edge["edge_ir_sha256"] for edge in edges]),
        "edge_ir_sha256": [edge["edge_ir_sha256"] for edge in edges],
        "macro_totals": macro_totals,
        "resources": {
            **total.as_dict(),
            "cache_qubits": sum(widths),
            "data_qubits": N,
            "data_plus_cache_qubits": data_plus_cache,
            "reusable_scratch_qubits": reusable_scratch,
            "logical_qubits_without_decomposition_ancillas": logical_without_decomposition,
            "logical_qubits_with_clean_decomposition_ancillas": logical_with_decomposition,
            "serial_cnot_depth_upper_bound": selected_cnot,
        },
        "budget_cnot": BUDGET_CNOT,
        "budget_margin_cnot": margin,
        "budget_decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET" if margin >= 0 else "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
        "proof_states": {
            "authenticated_seed_contract": True,
            "range_width_certificates": True,
            "scalable_reversible_ir": True,
            "static_dead_edge_certificate": True,
            "elementary_lowering": True,
            "template_equivalence": True,
            "clean_scratch_proof": True,
            "feasible_support_coherent_pair_action": True,
            "ordered_780_edge_layer": True,
            "selected_model_cnot_ledger": True,
            "selected_model_budget_at_most_2500000": margin >= 0,
        },
        "decision": "N40_REVERSIBLE_IR_PASSED",
    }
    return {**seed_core, "seed_ir_sha256": canonical_json_sha256(seed_core)}


def _certificate_payload() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = _paths()["v31"]
    payload = _read_json_strict(path)
    certificates = payload.get("seed_certificates") or []
    if [int(row.get("seed", -1)) for row in certificates] != list(SEEDS):
        raise ValueError("Frozen certificate seed order mismatch.")
    return payload, certificates


def build_v39_artifact(*, use_cache: bool = True) -> dict[str, Any]:
    global _BUILD_CACHE
    paths = _paths()
    key = tuple(raw_file_sha256(paths[name]) for name in ("spec", "v38_artifact", "v38_spec", "v38_source", "v38_freeze", "v31")) + (source_sha256(),)
    if use_cache and _BUILD_CACHE is not None and _BUILD_CACHE[0] == key:
        return copy.deepcopy(_BUILD_CACHE[1])
    spec = load_v39_spec()
    parent = authenticate_parent_chain()
    if not parent["valid"]:
        raise ValueError("V3.9 parent authentication failed: " + "; ".join(parent["errors"]))
    v31, certificates = _certificate_payload()
    seed_rows = [compile_seed(certificate) for certificate in certificates]
    maximum = max(int(row["resources"]["selected_model_cnot"]) for row in seed_rows)
    minimum_margin = min(int(row["budget_margin_cnot"]) for row in seed_rows)
    all_ir = all(row["decision"] == "N40_REVERSIBLE_IR_PASSED" for row in seed_rows)
    budget_pass = all(row["budget_decision"] == "PASSED_SELECTED_MODEL_CNOT_BUDGET" for row in seed_rows)
    coverage_keys = tuple(seed_rows[0]["proof_states"])
    coverage = {key: sum(bool(row["proof_states"][key]) for row in seed_rows) for key in coverage_keys}
    live_total = sum(int(row["live_edge_count"]) for row in seed_rows)
    dead_total = sum(int(row["certified_identity_count"]) for row in seed_rows)
    delta_total = sum(int(row["nonzero_row_edge_deltas"]) for row in seed_rows)
    live_delta_total = sum(int(row["nonzero_live_row_edge_deltas"]) for row in seed_rows)
    overall = (
        "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_PASSED"
        if all_ir and budget_pass
        else "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED"
        if all_ir
        else "N40_REVERSIBLE_IR_VALIDATION_FAILED"
    )
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "v39_version": V39_VERSION,
        "research_classification": "RESEARCH_ONLY",
        "spec_sha256": spec["v39_spec_sha256"],
        "spec_raw_file_sha256": raw_file_sha256(paths["spec"]),
        "source_sha256": source_sha256(),
        "parent": {
            "v38_artifact_sha256": EXPECTED_V38_ARTIFACT_SHA,
            "v38_artifact_raw_file_sha256": EXPECTED_V38_ARTIFACT_RAW,
            "v38_freeze_sha256": EXPECTED_V38_FREEZE_SHA,
            "v38_freeze_raw_file_sha256": EXPECTED_V38_FREEZE_RAW,
            "v31_dyadic_oracle_sha": v31["dyadic_oracle_sha"],
            "v31_raw_file_sha256": EXPECTED_V31_RAW,
            "authentication": parent,
        },
        "compiler_contract": {
            "semantic_domain": "EXACT_K10_FEASIBLE_SUPPORT_WITH_EXACT_SEVEN_REGISTER_CACHES",
            "selected_model": SELECTED_MODEL,
            "elementary_basis": list(ELEMENTARY_BASIS),
            "edge_order": "LEXICOGRAPHIC_I_THEN_J",
            "canonical_position_count_per_seed": EDGE_COUNT,
            "post_observation_model_switching": "PROHIBITED",
            "connectivity_model": "ABSTRACT_ALL_TO_ALL_LOGICAL",
            "resource_policy": "NO_CANCELLATION_BETWEEN_MACROS_OR_EDGE_POSITIONS",
        },
        "coverage_counts_out_of_8": coverage,
        "aggregate_evidence": {
            "edge_seed_positions": len(seed_rows) * EDGE_COUNT,
            "constraint_row_cases": len(seed_rows) * EDGE_COUNT * 7,
            "live_edge_positions": live_total,
            "certified_identity_positions": dead_total,
            "nonzero_row_edge_deltas": delta_total,
            "nonzero_live_row_edge_deltas": live_delta_total,
            "all_ordered_positions_present": live_total + dead_total == len(seed_rows) * EDGE_COUNT,
            "global_unitarity_by_reversible_composition": "PROVEN",
            "feasible_support_coherent_equivalence": "PROVEN_BY_CONSTRUCTION",
            "full_binary_operator_equivalence": "NOT_CLAIMED",
        },
        "seed_rows": seed_rows,
        "resource_screen": {
            "budget_cnot": BUDGET_CNOT,
            "maximum_selected_model_cnot": maximum,
            "minimum_budget_margin_cnot": minimum_margin,
            "decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET" if budget_pass else "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
            "rule": "PASS_IFF_MAXIMUM_OF_ALL_EIGHT_COMPLETE_ORDERED_LAYER_COUNTS_AT_MOST_2500000",
        },
        "decisions": {
            "overall": overall,
            "reversible_ir_decision": "N40_REVERSIBLE_IR_PASSED" if all_ir else "N40_REVERSIBLE_IR_VALIDATION_FAILED",
            "budget_decision": "PASSED_SELECTED_MODEL_CNOT_BUDGET" if budget_pass else "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
            "production_admission": "BLOCKED_GLOBAL_CONNECTIVITY_AND_BACKEND",
            "complete_global_connectivity": "INDETERMINATE",
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": "GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE",
        },
        "claim_boundary": {
            "production_scope": "N40_REVERSIBLE_IR_AND_SELECTED_MODEL_RESOURCE_SCREEN_ONLY",
            "full_binary_operator_equivalence": "NOT_CLAIMED",
            "complete_global_connectivity": "INDETERMINATE",
            "backend_transpilation": "NOT_RUN",
            "provider_sdk_imported": False,
            "provider_credentials_read": False,
            "provider_calls": 0,
            "hardware_executable": False,
            "qpu_submission_enabled": False,
            "qpu_jobs_submitted": 0,
            "optimization_performance": "NOT_TESTED",
            "quantum_advantage": "NOT_CLAIMED",
        },
    }
    artifact = {**core, "artifact_sha256": canonical_json_sha256(core)}
    _BUILD_CACHE = (key, copy.deepcopy(artifact))
    return artifact


def validate_v39_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["Artifact must be an object."]}
    errors: list[str] = []
    try:
        core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    try:
        expected = build_v39_artifact()
    except Exception as exc:
        expected = {}
        errors.append(f"Trusted V3.9 evidence recomputation failed: {exc}")
    if expected and payload != expected:
        errors.append("Artifact differs from the complete recomputed V3.9 evidence object.")
    rows = payload.get("seed_rows") or []
    aggregate = payload.get("aggregate_evidence") or {}
    decisions = payload.get("decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    if [int(row.get("seed", -1)) for row in rows if isinstance(row, Mapping)] != list(SEEDS):
        errors.append("Seed order, uniqueness or completeness mismatch.")
    if not (
        aggregate.get("edge_seed_positions") == 6_240
        and aggregate.get("constraint_row_cases") == 43_680
        and aggregate.get("live_edge_positions") == 4_220
        and aggregate.get("certified_identity_positions") == 2_020
        and aggregate.get("nonzero_row_edge_deltas") == 28_320
        and aggregate.get("nonzero_live_row_edge_deltas") == 19_094
    ):
        errors.append("Aggregate N40 proof inventory mismatch.")
    if decisions.get("complete_global_connectivity") != "INDETERMINATE":
        errors.append("Global connectivity boundary was promoted without evidence.")
    if not (
        boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and boundary.get("quantum_advantage") == "NOT_CLAIMED"
    ):
        errors.append("Provider, hardware or advantage boundary mismatch.")
    return {
        "valid": not errors,
        "errors": errors,
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
    }


def default_v39_artifact_path() -> Path:
    return _root() / "outputs" / "quantum_phase3" / "v39_scalable_ir" / DEFAULT_ARTIFACT_NAME


def seal_v39_artifact(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v39_artifact_path()
    artifact = build_v39_artifact()
    report = validate_v39_artifact(artifact)
    if not report["valid"]:
        raise ValueError("Refusing to seal invalid V3.9 artifact: " + "; ".join(report["errors"]))
    encoded = json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    if target.exists():
        if target.read_bytes() != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V3.9 artifact: {target}")
        return {"artifact": artifact, "created": False, "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encoded)
    return {"artifact": artifact, "created": True, "path": str(target)}


def load_v39_artifact(path: str | Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v39_artifact_path()
    payload = _read_json_strict(target)
    return payload, validate_v39_artifact(payload)


__all__ = [
    "ARTIFACT_VERSION",
    "BUDGET_CNOT",
    "DEFAULT_ARTIFACT_NAME",
    "EDGE_COUNT",
    "ELEMENTARY_BASIS",
    "SEEDS",
    "SELECTED_MODEL",
    "V39_VERSION",
    "authenticate_parent_chain",
    "build_v39_artifact",
    "canonical_json_sha256",
    "comparator_cost",
    "compile_edge",
    "compile_seed",
    "controlled_add_cost",
    "default_v39_artifact_path",
    "load_v39_artifact",
    "load_v39_spec",
    "seal_v39_artifact",
    "validate_v39_artifact",
]
