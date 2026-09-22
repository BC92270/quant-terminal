"""Quantum Lab V4.1 certified bridges and proof-carrying resource compiler.

The release is deliberately provider-free.  It authenticates the immutable
V4.0 graph result, exhausts every registered two-out/two-in candidate incident
to its singleton components with three independent implementations, selects a
deterministic component bridge forest, and evaluates the preregistered guarded
slack resource architecture.  Hardware execution and backend transpilation
remain outside the scientific claim.
"""

from __future__ import annotations

from bisect import bisect_left
import copy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence

from .phase3_v39_scalable_reversible_ir import Cost, comparator_cost, controlled_add_cost
from .phase3_v40_global_connectivity import validate_v40_artifact


V41_VERSION = "PHASE III · V4.1 CERTIFIED BRIDGE + PROOF-CARRYING RESOURCE COMPILER · V1"
ARTIFACT_VERSION = "PHASE III · V4.1 AUGMENTED CONNECTIVITY + RESOURCE ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json"
ENGINE_FILENAME = "phase3_v41_bridge_engine.cpp"
DEFAULT_ARTIFACT_NAME = "SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json"
SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
N = 40
K = 10
EDGE_COUNT = N * (N - 1) // 2
BUDGET_CNOT = 2_500_000
SELECTED_MODEL = "CONTROLLED_CUCCARO_RIPPLE_CLEAN_LADDER_6CX_CCX_CRX2CX_V1"
ELEMENTARY_BASIS = ("X", "H", "T", "TDG", "RY", "RZ", "CX")

EXPECTED_SPEC_SHA = "a5977ce4dda24d2fe6e8308e299b8a6b9097cf4fdf7e2835ca8e2fdc6aa99c89"
EXPECTED_ENGINE_RAW = "6b065ac1fb834e9ff226954984fe466901314c9b556c2c253a0ace873f2bf26e"
EXPECTED_V40_SPEC_RAW = "c86e73ebc4e7852407972dfcab89000e68dbeac4e9d635093a31eadc835109e2"
EXPECTED_V40_SPEC_SHA = "3ab75513efc7014157ef74633ef5c4d9bd4f23b22390f341dbfd033cb8a9694e"
EXPECTED_V40_ENGINE_RAW = "16cdfffe8dde853f534349d0531f52c4026271f6f03de53ade77af4ec6726944"
EXPECTED_V40_SOURCE_RAW = "4ad9704cf4007a447195c6c9544ba38caa02316c32c1c0d7032b6a0cb6755afc"
EXPECTED_V40_ARTIFACT_RAW = "3e2918c31ff01d0545125fb641c850af6429a1f8db11709f419c38a2d9f619f2"
EXPECTED_V40_ARTIFACT_SHA = "0fbbddcdf73dde6708814521cc3df741acb53c079e25b6c8829965de56778f01"
EXPECTED_V40_FREEZE_RAW = "748829b2153611ffba0751ea5da9d0785ca44ce4f12a02546436d4a1e79a94b4"
EXPECTED_V40_FREEZE_SHA = "c6d380e5541182b6cc2096c3d2a6de6f129cb92c80288a43dae6f924314cff1e"
EXPECTED_V40_FROZEN_FINGERPRINT = "43e80508152726db7fb8b255ba5642301abaadb6a562783fd235367475000fe3"
V40_SUCCESSOR_MUTABLE = frozenset({"quantum_research_lab/README.md", "quantum_research_lab/ui.py"})

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
        "v40_spec": base / "quantum_research_lab" / "PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json",
        "v40_engine": base / "quantum_research_lab" / "phase3_v40_connectivity_engine.cpp",
        "v40_source": base / "quantum_research_lab" / "phase3_v40_global_connectivity.py",
        "v40_artifact": base / "outputs" / "quantum_phase3" / "v40_connectivity" / "SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json",
        "v40_freeze": base / "FREEZE_CONTRACT_V4_0.json",
        "v31": base / "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
    }


def load_v41_spec(path: str | Path | None = None, *, root: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else _paths(root)["spec"]
    payload = _read_json_strict(target)
    core = {key: value for key, value in payload.items() if key not in {"v41_spec_sha", "v41_spec_sha256"}}
    digest = canonical_json_sha256(core)
    if not (
        digest == EXPECTED_SPEC_SHA
        and payload.get("v41_spec_sha256") == digest
        and payload.get("v41_spec_sha") == digest[:20].upper()
    ):
        raise ValueError("V4.1 specification self-hash mismatch.")
    boundary = payload.get("claim_boundary") or {}
    chronology = payload.get("chronology") or {}
    compiler = payload.get("resource_compiler_contract") or {}
    if not (
        boundary.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("hardware_executable") is False
        and boundary.get("provider_calls") == 0
        and boundary.get("qpu_jobs_submitted") == 0
        and chronology.get("resource_ledger_state_at_seal") == "NOT_EVALUATED"
        and compiler.get("selected_decomposition_model") == SELECTED_MODEL
        and (payload.get("bridge_protocol") or {}).get("engine_source_raw_file_sha256") == EXPECTED_ENGINE_RAW
    ):
        raise ValueError("V4.1 specification violates the sealed scientific boundary.")
    return payload


def authenticate_parent_chain(*, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    spec = load_v41_spec(root=paths["root"])
    expected = spec["parent_contract"]
    errors: list[str] = []
    raw_expected = {
        "v40_spec": EXPECTED_V40_SPEC_RAW,
        "v40_engine": EXPECTED_V40_ENGINE_RAW,
        "v40_source": EXPECTED_V40_SOURCE_RAW,
        "v40_artifact": EXPECTED_V40_ARTIFACT_RAW,
        "v40_freeze": EXPECTED_V40_FREEZE_RAW,
        "engine": EXPECTED_ENGINE_RAW,
    }
    raw_checks: dict[str, dict[str, Any]] = {}
    for name, registered in raw_expected.items():
        try:
            actual = raw_file_sha256(paths[name])
        except Exception as exc:
            actual = ""
            errors.append(f"Unable to hash {name}: {exc}")
        valid = actual == registered
        raw_checks[name] = {"actual": actual, "expected": registered, "valid": valid}
        if not valid:
            errors.append(f"Parent raw identity mismatch: {name}")

    if not (
        expected.get("expected_v40_spec_raw_file_sha256") == EXPECTED_V40_SPEC_RAW
        and expected.get("expected_v40_engine_raw_file_sha256") == EXPECTED_V40_ENGINE_RAW
        and expected.get("expected_v40_source_raw_file_sha256") == EXPECTED_V40_SOURCE_RAW
        and expected.get("expected_v40_artifact_raw_file_sha256") == EXPECTED_V40_ARTIFACT_RAW
        and expected.get("expected_v40_freeze_raw_file_sha256") == EXPECTED_V40_FREEZE_RAW
    ):
        errors.append("V4.1 parent constants drift from the sealed specification.")

    semantic_checks: dict[str, bool] = {}
    try:
        v40_spec = _read_json_strict(paths["v40_spec"])
        v40_spec_core = {key: value for key, value in v40_spec.items() if key not in {"v40_spec_sha", "v40_spec_sha256"}}
        semantic_checks["v40_spec"] = bool(
            v40_spec.get("v40_spec_sha256") == EXPECTED_V40_SPEC_SHA == canonical_json_sha256(v40_spec_core)
        )
    except Exception as exc:
        semantic_checks["v40_spec"] = False
        errors.append(f"V4.0 spec authentication error: {exc}")
    try:
        artifact = _read_json_strict(paths["v40_artifact"])
        artifact_core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
        validation = validate_v40_artifact(artifact, root=paths["root"], authenticate_parent=True)
        semantic_checks["v40_artifact"] = bool(
            artifact.get("artifact_sha256") == EXPECTED_V40_ARTIFACT_SHA == canonical_json_sha256(artifact_core)
            and validation.get("valid") is True
            and (artifact.get("decisions") or {}).get("global_connectivity_decision") == expected.get("expected_v40_decision")
            and (artifact.get("decisions") or {}).get("next_falsifiable_gate") == expected.get("required_v40_next_gate")
        )
    except Exception as exc:
        semantic_checks["v40_artifact"] = False
        errors.append(f"V4.0 artifact authentication error: {exc}")
    try:
        freeze = _read_json_strict(paths["v40_freeze"])
        freeze_core = {key: value for key, value in freeze.items() if key != "freeze_contract_sha256"}
        frozen_files = freeze.get("frozen_files") or {}
        immutable = {key: value for key, value in frozen_files.items() if key not in V40_SUCCESSOR_MUTABLE}
        immutable_mismatches = [
            relative for relative, registered in immutable.items()
            if not (paths["root"] / relative).is_file() or raw_file_sha256(paths["root"] / relative) != registered
        ]
        semantic_checks["v40_freeze"] = bool(
            freeze.get("freeze_contract_sha256") == EXPECTED_V40_FREEZE_SHA == canonical_json_sha256(freeze_core)
            and freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V40_FROZEN_FINGERPRINT
            and len(frozen_files) == 145
            and len(immutable) == 143
            and not immutable_mismatches
        )
    except Exception as exc:
        immutable = {}
        immutable_mismatches = [str(exc)]
        semantic_checks["v40_freeze"] = False
        errors.append(f"V4.0 freeze authentication error: {exc}")
    for name, valid in semantic_checks.items():
        if not valid:
            errors.append(f"Parent semantic authentication failed: {name}")
    if immutable_mismatches:
        errors.append(f"V4.0 immutable-path mismatches: {immutable_mismatches[:5]}")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "immutable_v40_paths_authenticated": len(immutable) if not immutable_mismatches else 0,
        "raw_checks": raw_checks,
        "semantic_checks": semantic_checks,
        "v40_frozen_paths_fingerprint_sha256": EXPECTED_V40_FROZEN_FINGERPRINT,
    }


def _certificate_by_seed(root: str | Path | None = None) -> dict[int, dict[str, Any]]:
    payload = _read_json_strict(_paths(root)["v31"])
    certificates = payload.get("seed_certificates") or []
    if [int(row.get("seed", -1)) for row in certificates] != list(SEEDS):
        raise ValueError("Frozen V3.1 certificate seed order mismatch.")
    return {int(row["seed"]): row for row in certificates}


def _v40_artifact(root: str | Path | None = None) -> dict[str, Any]:
    payload = _read_json_strict(_paths(root)["v40_artifact"])
    validation = validate_v40_artifact(payload, root=_root(root), authenticate_parent=True)
    if validation.get("valid") is not True:
        raise ValueError(f"Authenticated V4.0 artifact validation failed: {validation}")
    return payload


def _constraint_rows(certificate: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for group in certificate.get("group_bands") or []:
        members = {int(index) for index in group["indices"]}
        rows.append({
            "kind": "GROUP",
            "name": str(group["name"]),
            "lower": int(group["lower"]),
            "upper": int(group["upper"]),
            "coefficients": tuple(1 if index in members else 0 for index in range(N)),
        })
    for factor in certificate.get("factor_bands") or []:
        rows.append({
            "kind": "FACTOR",
            "name": str(factor["name"]),
            "lower": int(factor["lower_int"]),
            "upper": int(factor["upper_int"]),
            "coefficients": tuple(int(value) for value in factor["coefficients_int"]),
        })
    if len(rows) != 7 or any(len(row["coefficients"]) != N for row in rows):
        raise ValueError("Expected the frozen seven-row N=40 contract.")
    return tuple(rows)


def _mask_indices(mask: int) -> list[int]:
    return [index for index in range(N) if (mask >> index) & 1]


def _values_for(mask: int, rows: Sequence[Mapping[str, Any]]) -> list[int]:
    selected = _mask_indices(mask)
    return [sum(int(row["coefficients"][index]) for index in selected) for row in rows]


def _is_feasible(mask: int, values: Sequence[int], rows: Sequence[Mapping[str, Any]]) -> bool:
    return bool(
        mask >> N == 0
        and mask.bit_count() == K
        and all(int(row["lower"]) <= int(value) <= int(row["upper"]) for row, value in zip(rows, values))
    )


def _ledger_line(source: int, record: Mapping[str, Any], feasible: bool) -> str:
    values = ",".join(str(int(value)) for value in record["exact_values"])
    removed = ",".join(str(int(value)) for value in record["removed"])
    added = ",".join(str(int(value)) for value in record["added"])
    return f"{source:010x}|{removed}|{added}|{int(record['target_mask_hex'], 16):010x}|{values}|{int(feasible)}\n"


def _audit_python_delta(certificate: Mapping[str, Any], source_hex: str) -> dict[str, Any]:
    rows = _constraint_rows(certificate)
    source = int(source_hex, 16)
    selected = _mask_indices(source)
    unselected = [index for index in range(N) if index not in set(selected)]
    source_values = _values_for(source, rows)
    if not _is_feasible(source, source_values, rows):
        raise ValueError("Registered V4.0 singleton is not exactly feasible.")
    classification = hashlib.sha256()
    feasible_digest = hashlib.sha256()
    feasible_records: list[dict[str, Any]] = []
    audited = 0
    for removed in combinations(selected, 2):
        for added in combinations(unselected, 2):
            target = source
            for index in (*removed, *added):
                target ^= 1 << index
            values = [
                source_values[row_index]
                - int(row["coefficients"][removed[0]])
                - int(row["coefficients"][removed[1]])
                + int(row["coefficients"][added[0]])
                + int(row["coefficients"][added[1]])
                for row_index, row in enumerate(rows)
            ]
            record = {
                "added": list(added),
                "exact_values": values,
                "removed": list(removed),
                "target_mask_hex": f"{target:010x}",
            }
            accepted = _is_feasible(target, values, rows)
            line = _ledger_line(source, record, accepted).encode("utf-8")
            classification.update(line)
            if accepted:
                feasible_digest.update(line)
                feasible_records.append(record)
            audited += 1
    if audited != math.comb(K, 2) * math.comb(N - K, 2):
        raise AssertionError("Two-swap audit universe mismatch.")
    return {
        "algorithm": "PYTHON_EXACT_DELTA_CANONICAL_ORDER_V1",
        "audit_universe": audited,
        "candidates_audited": audited,
        "classification_ledger_sha256": classification.hexdigest(),
        "feasible_neighbor_count": len(feasible_records),
        "feasible_record_sha256": feasible_digest.hexdigest(),
        "feasible_records": feasible_records,
        "seed": int(certificate["seed"]),
        "source_mask_hex": f"{source:010x}",
    }


def _audit_python_full(certificate: Mapping[str, Any], source_hex: str) -> dict[str, Any]:
    rows = _constraint_rows(certificate)
    source = int(source_hex, 16)
    selected = _mask_indices(source)
    unselected = [index for index in range(N) if not ((source >> index) & 1)]
    candidate_rows: list[tuple[tuple[int, int], tuple[int, int], dict[str, Any], bool]] = []
    for added in reversed(list(combinations(unselected, 2))):
        for removed in reversed(list(combinations(selected, 2))):
            target = source
            for index in (*removed, *added):
                target ^= 1 << index
            values = _values_for(target, rows)
            record = {
                "added": list(added),
                "exact_values": values,
                "removed": list(removed),
                "target_mask_hex": f"{target:010x}",
            }
            candidate_rows.append((removed, added, record, _is_feasible(target, values, rows)))
    candidate_rows.sort(key=lambda item: (item[0], item[1]))
    classification = hashlib.sha256()
    feasible_digest = hashlib.sha256()
    feasible_records: list[dict[str, Any]] = []
    for _, _, record, accepted in candidate_rows:
        line = _ledger_line(source, record, accepted).encode("utf-8")
        classification.update(line)
        if accepted:
            feasible_digest.update(line)
            feasible_records.append(record)
    return {
        "algorithm": "PYTHON_EXACT_FULL_RECOMPUTE_REVERSED_ENUMERATION_V1",
        "audit_universe": len(candidate_rows),
        "candidates_audited": len(candidate_rows),
        "classification_ledger_sha256": classification.hexdigest(),
        "feasible_neighbor_count": len(feasible_records),
        "feasible_record_sha256": feasible_digest.hexdigest(),
        "feasible_records": feasible_records,
        "seed": int(certificate["seed"]),
        "source_mask_hex": f"{source:010x}",
    }


def _bridge_engine_input(certificate: Mapping[str, Any], source_hex: str) -> str:
    rows = _constraint_rows(certificate)
    lines = ["QLV41", f"{int(certificate['seed'])} {int(source_hex, 16):010x}", str(len(rows))]
    for row in rows:
        coefficients = " ".join(str(int(value)) for value in row["coefficients"])
        lines.append(f"{row['name']} {int(row['lower'])} {int(row['upper'])}")
        lines.append(coefficients)
    return "\n".join(lines) + "\n"


def compile_bridge_engine(destination: str | Path, *, root: str | Path | None = None) -> dict[str, Any]:
    paths = _paths(root)
    if raw_file_sha256(paths["engine"]) != EXPECTED_ENGINE_RAW:
        raise ValueError("V4.1 bridge engine source identity mismatch.")
    compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if not compiler:
        raise RuntimeError("No C++17 compiler is available.")
    target = Path(destination)
    command = [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra", "-pedantic", str(paths["engine"]), "-o", str(target)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180, check=False)
    if completed.returncode != 0 or not target.is_file():
        raise RuntimeError(f"Bridge engine compilation failed: {completed.stderr.strip()}")
    if completed.stderr.strip():
        raise RuntimeError(f"Bridge engine compilation emitted diagnostics: {completed.stderr.strip()}")
    return {"compiler": Path(compiler).name, "source_sha256": EXPECTED_ENGINE_RAW}


def _audit_cpp(binary: Path, certificate: Mapping[str, Any], source_hex: str) -> dict[str, Any]:
    completed = subprocess.run(
        [str(binary)],
        input=_bridge_engine_input(certificate, source_hex),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"V4.1 bridge engine failed: {completed.stderr.strip()}")
    result = json.loads(completed.stdout, object_pairs_hook=_reject_duplicates, parse_constant=_reject_nonfinite)
    for record in result.get("feasible_records") or []:
        record["exact_values"] = [int(value) for value in record["exact_values"]]
    return result


def _stable_bridge_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(value) for key, value in result.items() if key != "algorithm"}


def _audit_one_isolate(
    binary: Path,
    certificate: Mapping[str, Any],
    source_hex: str,
) -> dict[str, Any]:
    method_a = _audit_python_delta(certificate, source_hex)
    method_b = _audit_python_full(certificate, source_hex)
    method_c = _audit_cpp(binary, certificate, source_hex)
    stable_a = _stable_bridge_result(method_a)
    stable_b = _stable_bridge_result(method_b)
    stable_c = _stable_bridge_result(method_c)
    if not (stable_a == stable_b == stable_c):
        raise ValueError(f"Independent two-swap audit mismatch for seed {certificate['seed']} source {source_hex}.")
    core = {
        **stable_a,
        "independent_methods": [method_a["algorithm"], method_b["algorithm"], method_c["algorithm"]],
        "triple_replay_match": True,
    }
    return {**core, "isolate_audit_sha256": canonical_json_sha256(core)}


class _Dsu:
    def __init__(self, labels: Iterable[str]) -> None:
        self.parent = {label: label for label in labels}

    def find(self, label: str) -> str:
        root = label
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[label] != label:
            next_label = self.parent[label]
            self.parent[label] = root
            label = next_label
        return root

    def unite(self, left: str, right: str) -> bool:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return False
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        return True


def run_bridge_confirmatory_protocol(
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    base = _root(root)
    spec = load_v41_spec(root=base)
    parent = authenticate_parent_chain(root=base)
    if not parent["valid"]:
        raise ValueError(f"V4.0 parent authentication failed: {parent['errors']}")
    certificates = _certificate_by_seed(base)
    v40 = _v40_artifact(base)
    v40_rows = v40["connectivity_evidence"]["seed_rows"]
    audit_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="quantum-v41-bridge-") as temporary:
        binary = Path(temporary) / "v41_bridge_engine"
        engine_build = compile_bridge_engine(binary, root=base)
        for seed_row in v40_rows:
            seed = int(seed_row["seed"])
            for isolate in seed_row.get("isolated_counterexamples") or []:
                source_hex = str(isolate["mask_hex"])
                if progress is not None:
                    progress(f"V4.1 exact 2-out/2-in audit · seed {seed} · {source_hex}")
                audit_rows.append(_audit_one_isolate(binary, certificates[seed], source_hex))
    expected_sources = [
        (int(row["seed"]), str(isolate["mask_hex"]))
        for row in v40_rows for isolate in row.get("isolated_counterexamples") or []
    ]
    observed_sources = [(int(row["seed"]), str(row["source_mask_hex"])) for row in audit_rows]
    if observed_sources != expected_sources:
        raise ValueError("Confirmatory audit did not cover the authenticated V4.0 singleton inventory exactly.")
    return {
        "protocol_version": V41_VERSION,
        "spec_sha256": spec["v41_spec_sha256"],
        "parent": parent,
        "engine_build": engine_build,
        "audit_rows": audit_rows,
        "all_triple_replays_match": all(row["triple_replay_match"] for row in audit_rows),
    }


@dataclass(frozen=True, slots=True)
class _Subset:
    count: int
    value: int
    mask: int


@dataclass(frozen=True, slots=True)
class _DualSubset:
    count: int
    original: int
    compressed: int
    mask: int


class _RangeExtrema:
    """Exact static primary-range min/max index over a secondary integer."""

    def __init__(self, points: Sequence[tuple[int, int, int]]) -> None:
        ordered = sorted(points)
        self.primary = [row[0] for row in ordered]
        length = 1
        while length < len(ordered):
            length <<= 1
        self.length = length
        infinity = 1 << 256
        self.minimum = [infinity] * (2 * length)
        self.maximum = [-infinity] * (2 * length)
        for index, (_, secondary, _) in enumerate(ordered):
            self.minimum[length + index] = secondary
            self.maximum[length + index] = secondary
        for index in range(length - 1, 0, -1):
            self.minimum[index] = min(self.minimum[2 * index], self.minimum[2 * index + 1])
            self.maximum[index] = max(self.maximum[2 * index], self.maximum[2 * index + 1])

    def query(self, lower: int, upper: int) -> tuple[int, int] | None:
        from bisect import bisect_right

        left = bisect_left(self.primary, lower)
        right = bisect_right(self.primary, upper)
        if left >= right:
            return None
        left += self.length
        right += self.length
        minimum = 1 << 256
        maximum = -(1 << 256)
        while left < right:
            if left & 1:
                minimum = min(minimum, self.minimum[left])
                maximum = max(maximum, self.maximum[left])
                left += 1
            if right & 1:
                right -= 1
                minimum = min(minimum, self.minimum[right])
                maximum = max(maximum, self.maximum[right])
            left >>= 1
            right >>= 1
        return minimum, maximum


def _local_group_subsets(
    certificate: Mapping[str, Any],
    coefficients: Sequence[int],
) -> tuple[tuple[_Subset, ...], ...]:
    result: list[tuple[_Subset, ...]] = []
    for group in certificate.get("group_bands") or []:
        indices = [int(index) for index in group["indices"]]
        rows: list[_Subset] = []
        for local_mask in range(1 << len(indices)):
            count = local_mask.bit_count()
            if count < int(group["lower"]) or count > int(group["upper"]):
                continue
            mask = 0
            value = 0
            for position, index in enumerate(indices):
                if (local_mask >> position) & 1:
                    mask |= 1 << index
                    value += int(coefficients[index])
            rows.append(_Subset(count, value, mask))
        result.append(tuple(rows))
    if len(result) != 4:
        raise ValueError("Expected four authenticated groups.")
    return tuple(result)


def _local_dual_group_subsets(
    certificate: Mapping[str, Any],
    original: Sequence[int],
    compressed: Sequence[int],
) -> tuple[tuple[_DualSubset, ...], ...]:
    result: list[tuple[_DualSubset, ...]] = []
    for group in certificate.get("group_bands") or []:
        indices = [int(index) for index in group["indices"]]
        rows: list[_DualSubset] = []
        for local_mask in range(1 << len(indices)):
            count = local_mask.bit_count()
            if count < int(group["lower"]) or count > int(group["upper"]):
                continue
            mask = 0
            original_sum = 0
            compressed_sum = 0
            for position, index in enumerate(indices):
                if (local_mask >> position) & 1:
                    mask |= 1 << index
                    original_sum += int(original[index])
                    compressed_sum += int(compressed[index])
            rows.append(_DualSubset(count, original_sum, compressed_sum, mask))
        result.append(tuple(rows))
    if len(result) != 4:
        raise ValueError("Expected four authenticated groups.")
    return tuple(result)


def _combine_dual_buckets(
    left: Sequence[_DualSubset],
    right: Sequence[_DualSubset],
) -> tuple[tuple[_DualSubset, ...], ...]:
    buckets: list[list[_DualSubset]] = [[] for _ in range(K + 1)]
    for lhs in left:
        for rhs in right:
            count = lhs.count + rhs.count
            if count <= K:
                buckets[count].append(_DualSubset(
                    count,
                    lhs.original + rhs.original,
                    lhs.compressed + rhs.compressed,
                    lhs.mask | rhs.mask,
                ))
    return tuple(tuple(bucket) for bucket in buckets)


def _predicate_parity_partition(
    certificate: Mapping[str, Any],
    original: Sequence[int],
    compressed: Sequence[int],
    original_lower: int,
    original_upper: int,
    compressed_lower: int,
    compressed_upper: int,
    partition: tuple[tuple[int, int], tuple[int, int]],
) -> dict[str, Any]:
    local = _local_dual_group_subsets(certificate, original, compressed)
    halves = (
        _combine_dual_buckets(local[partition[0][0]], local[partition[0][1]]),
        _combine_dual_buckets(local[partition[1][0]], local[partition[1][1]]),
    )
    # Query the smaller half. Swapping sides preserves both interval predicates.
    if sum(len(bucket) for bucket in halves[0]) <= sum(len(bucket) for bucket in halves[1]):
        query_half, indexed_half = halves
        effective_partition = partition
    else:
        indexed_half, query_half = halves
        effective_partition = (partition[1], partition[0])
    domain_count = 0
    equivalence_classes_queried = 0
    mismatch = False
    for query_count in range(K + 1):
        indexed_count = K - query_count
        query_rows = query_half[query_count]
        indexed_rows = indexed_half[indexed_count]
        domain_count += len(query_rows) * len(indexed_rows)
        if not query_rows or not indexed_rows:
            continue
        # Equal (original, compressed) pairs are classification-equivalent; one
        # representative covers all masks in that exact sum class.
        point_masks: dict[tuple[int, int], int] = {}
        for row in indexed_rows:
            key = (row.original, row.compressed)
            point_masks[key] = min(row.mask, point_masks.get(key, row.mask))
        unique_points = [(key[0], key[1], mask) for key, mask in point_masks.items()]
        original_index = _RangeExtrema(unique_points)
        compressed_index = _RangeExtrema([(row[1], row[0], row[2]) for row in unique_points])
        for left in query_rows:
            original_interval = (original_lower - left.original, original_upper - left.original)
            compressed_interval = (compressed_lower - left.compressed, compressed_upper - left.compressed)
            original_true = original_index.query(*original_interval)
            if original_true is not None and (
                original_true[0] < compressed_interval[0] or original_true[1] > compressed_interval[1]
            ):
                mismatch = True
                break
            compressed_true = compressed_index.query(*compressed_interval)
            if compressed_true is not None and (
                compressed_true[0] < original_interval[0] or compressed_true[1] > original_interval[1]
            ):
                mismatch = True
                break
            equivalence_classes_queried += 1
        if mismatch:
            break
    core = {
        "classification_disagreement_found": mismatch,
        "complete_domain_count": domain_count,
        "effective_query_partition": [list(effective_partition[0]), list(effective_partition[1])],
        "equivalence_class_queries": equivalence_classes_queried,
        "partition": [list(partition[0]), list(partition[1])],
        "status": "EXACT_COMPLETE_DOMAIN_PREDICATE_PARITY" if not mismatch else "PREDICATE_MISMATCH",
    }
    return {**core, "parity_replay_sha256": canonical_json_sha256(core)}


def _group_valid_universe_count(local: Sequence[Sequence[_Subset]]) -> int:
    counts = [1] + [0] * K
    for group_rows in local:
        by_count: dict[int, int] = {}
        for row in group_rows:
            by_count[row.count] = by_count.get(row.count, 0) + 1
        next_counts = [0] * (K + 1)
        for existing, multiplicity in enumerate(counts):
            if not multiplicity:
                continue
            for group_count, group_multiplicity in by_count.items():
                if existing + group_count <= K:
                    next_counts[existing + group_count] += multiplicity * group_multiplicity
        counts = next_counts
    return counts[K]


def _combine_value_buckets(
    left: Sequence[_Subset],
    right: Sequence[_Subset],
) -> tuple[tuple[tuple[int, int], ...], ...]:
    buckets: list[list[tuple[int, int]]] = [[] for _ in range(K + 1)]
    for lhs in left:
        for rhs in right:
            count = lhs.count + rhs.count
            if count <= K:
                buckets[count].append((lhs.value + rhs.value, lhs.mask | rhs.mask))
    compressed: list[tuple[tuple[int, int], ...]] = []
    for bucket in buckets:
        bucket.sort()
        unique: list[tuple[int, int]] = []
        previous_value: int | None = None
        minimum_mask = 0
        for value, mask in bucket:
            if previous_value is None or value != previous_value:
                if previous_value is not None:
                    unique.append((previous_value, minimum_mask))
                previous_value = value
                minimum_mask = mask
            elif mask < minimum_mask:
                minimum_mask = mask
        if previous_value is not None:
            unique.append((previous_value, minimum_mask))
        compressed.append(tuple(unique))
    return tuple(compressed)


def _closest_to_target(
    left: Sequence[tuple[int, int]],
    right: Sequence[tuple[int, int]],
    target: int,
) -> tuple[int, int, int]:
    if not left or not right:
        raise ValueError("Empty MITM count bucket.")
    right_values = [row[0] for row in right]
    best: tuple[int, int, int] | None = None
    for left_value, left_mask in left:
        position = bisect_left(right_values, target - left_value)
        for right_index in (position - 1, position):
            if 0 <= right_index < len(right):
                right_value, right_mask = right[right_index]
                total = left_value + right_value
                candidate = (abs(total - target), left_mask | right_mask, total)
                if best is None or candidate < best:
                    best = candidate
    if best is None:
        raise AssertionError("MITM closest-value search emitted no candidate.")
    return best


def _margin_partition(
    local: Sequence[Sequence[_Subset]],
    partition: tuple[tuple[int, int], tuple[int, int]],
    lower: int,
    upper: int,
) -> dict[str, Any]:
    left = _combine_value_buckets(local[partition[0][0]], local[partition[0][1]])
    right = _combine_value_buckets(local[partition[1][0]], local[partition[1][1]])
    best: tuple[int, int, int, int] | None = None
    for left_count in range(K + 1):
        right_count = K - left_count
        if not left[left_count] or not right[right_count]:
            continue
        for threshold_tag, threshold in enumerate((lower, upper)):
            distance, mask, total = _closest_to_target(left[left_count], right[right_count], threshold)
            candidate = (distance, mask, threshold_tag, total)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise ValueError("No group-valid exact-K portfolio exists.")
    return {
        "distance": best[0],
        "portfolio_mask_hex": f"{best[1]:010x}",
        "threshold": "LOWER" if best[2] == 0 else "UPPER",
        "exact_sum": best[3],
        "partition": [list(partition[0]), list(partition[1])],
    }


def _extreme_by_count(rows: Sequence[_Subset]) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    minima: dict[int, tuple[int, int]] = {}
    maxima: dict[int, tuple[int, int]] = {}
    for row in rows:
        minimum = minima.get(row.count)
        maximum = maxima.get(row.count)
        if minimum is None or (row.value, row.mask) < minimum:
            minima[row.count] = (row.value, row.mask)
        if maximum is None or (-row.value, row.mask) < (-maximum[0], maximum[1]):
            maxima[row.count] = (row.value, row.mask)
    return minima, maxima


def _combine_extrema(
    left: Sequence[_Subset],
    right: Sequence[_Subset],
) -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    left_min, left_max = _extreme_by_count(left)
    right_min, right_max = _extreme_by_count(right)
    minima: dict[int, tuple[int, int]] = {}
    maxima: dict[int, tuple[int, int]] = {}
    for left_count, left_row in left_min.items():
        for right_count, right_row in right_min.items():
            count = left_count + right_count
            if count > K:
                continue
            candidate = (left_row[0] + right_row[0], left_row[1] | right_row[1])
            if count not in minima or candidate < minima[count]:
                minima[count] = candidate
    for left_count, left_row in left_max.items():
        for right_count, right_row in right_max.items():
            count = left_count + right_count
            if count > K:
                continue
            candidate = (left_row[0] + right_row[0], left_row[1] | right_row[1])
            if count not in maxima or (-candidate[0], candidate[1]) < (-maxima[count][0], maxima[count][1]):
                maxima[count] = candidate
    return minima, maxima


def _residual_extrema_partition(
    local: Sequence[Sequence[_Subset]],
    partition: tuple[tuple[int, int], tuple[int, int]],
) -> dict[str, Any]:
    left_min, left_max = _combine_extrema(local[partition[0][0]], local[partition[0][1]])
    right_min, right_max = _combine_extrema(local[partition[1][0]], local[partition[1][1]])
    minimum_candidates: list[tuple[int, int]] = []
    maximum_candidates: list[tuple[int, int]] = []
    for count, left_row in left_min.items():
        if K - count in right_min:
            right_row = right_min[K - count]
            minimum_candidates.append((left_row[0] + right_row[0], left_row[1] | right_row[1]))
    for count, left_row in left_max.items():
        if K - count in right_max:
            right_row = right_max[K - count]
            maximum_candidates.append((left_row[0] + right_row[0], left_row[1] | right_row[1]))
    minimum = min(minimum_candidates)
    maximum = min(maximum_candidates, key=lambda row: (-row[0], row[1]))
    error_witness = min((minimum, maximum), key=lambda row: (-abs(row[0]), row[1], row[0]))
    return {
        "minimum_residual": minimum[0],
        "minimum_residual_mask_hex": f"{minimum[1]:010x}",
        "maximum_residual": maximum[0],
        "maximum_residual_mask_hex": f"{maximum[1]:010x}",
        "exact_error_bound": abs(error_witness[0]),
        "error_witness_mask_hex": f"{error_witness[1]:010x}",
        "error_witness_residual": error_witness[0],
        "partition": [list(partition[0]), list(partition[1])],
    }


def _round_nearest_even(value: int, scale: int) -> int:
    quotient, remainder = divmod(value, scale)
    doubled = 2 * remainder
    if doubled < scale:
        return quotient
    if doubled > scale:
        return quotient + 1
    return quotient if quotient % 2 == 0 else quotient + 1


def _ceil_div(value: int, divisor: int) -> int:
    return -((-value) // divisor)


def _factor_compression_certificate(
    certificate: Mapping[str, Any],
    factor: Mapping[str, Any],
) -> dict[str, Any]:
    coefficients = tuple(int(value) for value in factor["coefficients_int"])
    lower = int(factor["lower_int"])
    upper = int(factor["upper_int"])
    partitions = (((0, 1), (2, 3)), ((0, 2), (1, 3)))
    local_original = _local_group_subsets(certificate, coefficients)
    universe_count = _group_valid_universe_count(local_original)
    margin_replays = [_margin_partition(local_original, partition, lower, upper) for partition in partitions]
    stable_margin_fields = ("distance", "portfolio_mask_hex", "threshold", "exact_sum")
    if any(
        any(replay[field] != margin_replays[0][field] for field in stable_margin_fields)
        for replay in margin_replays[1:]
    ):
        raise ValueError(f"Dual MITM threshold-margin replay mismatch for seed {certificate['seed']} {factor['name']}.")
    minimum_margin = int(margin_replays[0]["distance"])
    maximum_shift = max(abs(value).bit_length() for value in coefficients) + 2
    shift_rows: list[dict[str, Any]] = []
    selected: dict[str, Any] | None = None
    for shift in range(maximum_shift + 1):
        scale = 1 << shift
        compressed = tuple(_round_nearest_even(value, scale) for value in coefficients)
        residuals = tuple(value - scale * reduced for value, reduced in zip(coefficients, compressed))
        local_residual = _local_group_subsets(certificate, residuals)
        error_replays = [_residual_extrema_partition(local_residual, partition) for partition in partitions]
        stable_error_fields = (
            "minimum_residual",
            "minimum_residual_mask_hex",
            "maximum_residual",
            "maximum_residual_mask_hex",
            "exact_error_bound",
            "error_witness_mask_hex",
            "error_witness_residual",
        )
        replay_match = all(
            all(replay[field] == error_replays[0][field] for field in stable_error_fields)
            for replay in error_replays[1:]
        )
        compressed_lower = _ceil_div(lower, scale)
        compressed_upper = upper // scale
        interval_nonempty = compressed_lower <= compressed_upper
        strict_certificate = shift == 0 or int(error_replays[0]["exact_error_bound"]) < minimum_margin
        accepted = bool(replay_match and interval_nonempty and strict_certificate)
        row = {
            "accepted": accepted,
            "compressed_lower": compressed_lower,
            "compressed_upper": compressed_upper,
            "exact_error_bound": int(error_replays[0]["exact_error_bound"]),
            "error_replay_match": replay_match,
            "interval_nonempty": interval_nonempty,
            "scale": scale,
            "shift": shift,
            "strict_margin_certificate": strict_certificate,
        }
        shift_rows.append(row)
        if accepted:
            selected = {
                **row,
                "compressed_coefficients": list(compressed),
                "error_replays": error_replays,
            }
    if selected is None:
        raise AssertionError("Identity compression shift was unexpectedly rejected.")
    parity_replays = [
        _predicate_parity_partition(
            certificate,
            coefficients,
            selected["compressed_coefficients"],
            lower,
            upper,
            int(selected["compressed_lower"]),
            int(selected["compressed_upper"]),
            partition,
        )
        for partition in partitions
    ]
    if any(
        replay["classification_disagreement_found"]
        or int(replay["complete_domain_count"]) != universe_count
        for replay in parity_replays
    ):
        raise ValueError(f"Explicit complete-domain compression parity failed for seed {certificate['seed']} {factor['name']}.")
    core = {
        "classification_domain_count": universe_count,
        "compressed_coefficients_int": selected["compressed_coefficients"],
        "compressed_lower_int": selected["compressed_lower"],
        "compressed_upper_int": selected["compressed_upper"],
        "dual_error_replays": selected["error_replays"],
        "dual_margin_replays": margin_replays,
        "exact_error_bound": selected["exact_error_bound"],
        "exact_minimum_threshold_distance": minimum_margin,
        "factor": str(factor["name"]),
        "identity_or_strict_margin_parity_proof": True,
        "maximum_search_shift": maximum_shift,
        "original_lower_int": lower,
        "original_upper_int": upper,
        "predicate_parity_complete_domain": "DUAL_MITM_EXPLICIT_ZERO_DISAGREEMENT_AND_EXACT_ERROR_LT_THRESHOLD_DISTANCE",
        "predicate_parity_replays": parity_replays,
        "rounding": "NEAREST_INTEGER_HALF_TO_EVEN_EXACT_DIVMOD",
        "scale": selected["scale"],
        "selected_shift": selected["shift"],
        "shift_search_ledger_sha256": canonical_json_sha256(shift_rows),
        "shift_search_rows": shift_rows,
    }
    return {**core, "compression_certificate_sha256": canonical_json_sha256(core)}


def build_seed_compression_certificate(certificate: Mapping[str, Any]) -> dict[str, Any]:
    factors = [_factor_compression_certificate(certificate, factor) for factor in certificate.get("factor_bands") or []]
    if len(factors) != 3:
        raise ValueError("Expected three frozen factor bands.")
    core = {
        "all_factor_predicates_exact": all(row["identity_or_strict_margin_parity_proof"] for row in factors),
        "factor_rows": factors,
        "instance_id": str(certificate["instance_id"]),
        "parent_certificate_sha": str(certificate["certificate_sha"]),
        "seed": int(certificate["seed"]),
    }
    return {**core, "seed_compression_sha256": canonical_json_sha256(core)}


def _gate_cost(controls: int, negative_controls: int = 0) -> Cost:
    if controls < 0 or negative_controls < 0 or negative_controls > controls:
        raise ValueError("Invalid gate arity.")
    wrappers = 2 * negative_controls
    if controls == 0:
        return Cost(one_qubit=1, abstract_gates=1, x=1)
    if controls == 1:
        return Cost(
            cnot=1,
            one_qubit=wrappers,
            abstract_gates=1 + wrappers,
            x=wrappers,
            cx=1,
        )
    if controls == 2:
        return Cost(
            cnot=6,
            one_qubit=9 + wrappers,
            abstract_gates=1 + wrappers,
            x=wrappers,
            ccx=1,
        )
    ccx = 2 * controls - 3
    return Cost(
        cnot=6 * ccx,
        one_qubit=9 * ccx + wrappers,
        abstract_gates=1 + wrappers,
        x=wrappers,
        mcx=1,
        clean_decomposition_ancillas=controls - 2,
    )


def _controlled_ripple_add_cost(width: int, constant: int) -> Cost:
    """One-predicate-controlled Cuccaro modulo-2^w constant addition."""

    if width < 3:
        raise ValueError("The sealed ripple model requires width at least three.")
    base_toffoli = 2 * width - 3
    base_cnot = 5 * width - 7
    base_x = 2 * width - 6
    selected_cnot = 18 * base_toffoli + 6 * base_cnot + base_x
    encoded = int(constant) & ((1 << width) - 1)
    constant_load_x = 2 * encoded.bit_count()
    return Cost(
        cnot=selected_cnot,
        one_qubit=27 * base_toffoli + 9 * base_cnot + constant_load_x,
        abstract_gates=base_toffoli + base_cnot + base_x + constant_load_x,
        x=constant_load_x,
        cx=base_x,
        ccx=base_cnot,
        mcx=base_toffoli,
        clean_decomposition_ancillas=1,
    )


def _comparator_encoding(width: int, constant: int, relation: str) -> tuple[int, int, str]:
    """Return the constant register, output inversion and exact predicate.

    The Cuccaro high-bit primitive toggles its output iff ``a < b``.  For an
    unsigned cache ``z`` we implement ``z >= c`` as ``NOT(z < c)`` and
    ``z <= c`` as ``z < c + 1``.  The active guarded intervals guarantee
    ``0 < c`` for GE and ``c < 2**width - 1`` for LE, so both encodings fit in
    the registered width without a hidden carry bit.
    """

    if width < 3:
        raise ValueError("The sealed comparator model requires width at least three.")
    maximum = (1 << width) - 1
    value = int(constant)
    if relation == "GE":
        if not 0 < value <= maximum:
            raise ValueError("Active unsigned GE comparator constant is outside (0, 2**w-1].")
        return value, 1, "NOT(Z_LT_C)"
    if relation == "LE":
        if not 0 <= value < maximum:
            raise ValueError("Active unsigned LE comparator constant is outside [0, 2**w-1).")
        return value + 1, 0, "Z_LT_C_PLUS_ONE"
    raise ValueError("Comparator relation must be GE or LE.")


def _ripple_comparator_cost(width: int, constant: int, *, relation: str = "GE") -> Cost:
    """One exact inclusive Cuccaro comparator toggle, inputs restored."""

    toffoli = 2 * width - 1
    cnot = 4 * width - 3
    encoded, output_inversion_x, _ = _comparator_encoding(width, constant, relation)
    constant_load_x = 2 * encoded.bit_count()
    abstract_x = constant_load_x + output_inversion_x
    return Cost(
        cnot=6 * toffoli + cnot,
        one_qubit=9 * toffoli + abstract_x,
        abstract_gates=toffoli + cnot + abstract_x,
        x=abstract_x,
        cx=cnot,
        ccx=toffoli,
    )


def _guarded_rows(
    certificate: Mapping[str, Any],
    compression: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    compressed_by_name = {str(row["factor"]): row for row in compression["factor_rows"]}
    rows: list[dict[str, Any]] = []
    for original in _constraint_rows(certificate):
        if original["kind"] == "GROUP":
            coefficients = tuple(int(value) for value in original["coefficients"])
            lower = int(original["lower"])
            upper = int(original["upper"])
            compression_sha = "IDENTITY_GROUP_ROW"
            shift = 0
            scale = 1
        else:
            reduced = compressed_by_name[str(original["name"])]
            coefficients = tuple(int(value) for value in reduced["compressed_coefficients_int"])
            lower = int(reduced["compressed_lower_int"])
            upper = int(reduced["compressed_upper_int"])
            compression_sha = str(reduced["compression_certificate_sha256"])
            shift = int(reduced["selected_shift"])
            scale = int(reduced["scale"])
        guard = max(coefficients) - min(coefficients)
        span = upper - lower
        maximum_normalized = 2 * guard + span
        width = max(3, max(0, maximum_normalized).bit_length())
        row = {
            "cache_offset": -lower + guard,
            "coefficients": coefficients,
            "compression_certificate_sha256": compression_sha,
            "guard": guard,
            "kind": str(original["kind"]),
            "lower": lower,
            "name": str(original["name"]),
            "scale": scale,
            "shift": shift,
            "span": span,
            "upper": upper,
            "width": width,
        }
        if not (span >= 0 and 0 <= guard <= (1 << width) - 1 and maximum_normalized <= (1 << width) - 1):
            raise ValueError("Guarded slack register does not satisfy the no-wrap bound.")
        rows.append(row)
    if len(rows) != 7:
        raise ValueError("Guarded compiler expected seven rows.")
    return tuple(rows)


def _conditional_guarded_range(row: Mapping[str, Any], i: int, j: int, q: int) -> tuple[int, int]:
    coefficients = row["coefficients"]
    remaining = [int(coefficients[index]) for index in range(N) if index not in {i, j}]
    selected = int(coefficients[i if q == 1 else j])
    minimum_sum = selected + sum(sorted(remaining)[: K - 1])
    maximum_sum = selected + sum(sorted(remaining, reverse=True)[: K - 1])
    offset = int(row["cache_offset"])
    return minimum_sum + offset, maximum_sum + offset


def _guarded_row_proof(row: Mapping[str, Any], i: int, j: int) -> dict[str, Any]:
    coefficients = row["coefficients"]
    delta = int(coefficients[i]) - int(coefficients[j])
    candidates: list[dict[str, Any]] = []
    for q in (0, 1):
        add_constant = -delta if q == 0 else delta
        add_cost = _controlled_ripple_add_cost(int(row["width"]), add_constant) if delta else Cost()
        reachable_min, reachable_max = _conditional_guarded_range(row, i, j, q)
        central_lower = int(row["guard"])
        central_upper = central_lower + int(row["span"])
        sign = 1 - 2 * q
        interval_lower = max(central_lower, central_lower - sign * delta)
        interval_upper = min(central_upper, central_upper - sign * delta)
        overlap_lower = max(reachable_min, interval_lower)
        overlap_upper = min(reachable_max, interval_upper)
        candidates.append({
            "add_constant": add_constant,
            "dead": overlap_lower > overlap_upper,
            "interval_lower": interval_lower,
            "interval_upper": interval_upper,
            "normalization_one_way": add_cost.as_dict(),
            "overlap_lower": overlap_lower,
            "overlap_upper": overlap_upper,
            "q": q,
            "reachable_max": reachable_max,
            "reachable_min": reachable_min,
        })
    if candidates[0]["dead"] != candidates[1]["dead"]:
        raise ValueError("Guarded orientation changed exact dead-position classification.")
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
    core = {
        "add_constant_when_orientation_differs": int(chosen["add_constant"]),
        "canonical_orientation_q": int(chosen["q"]),
        "coefficient_i": int(coefficients[i]),
        "coefficient_j": int(coefficients[j]),
        "dead": bool(chosen["dead"]),
        "delta_i_minus_j": delta,
        "guarded_interval_lower": int(chosen["interval_lower"]),
        "guarded_interval_upper": int(chosen["interval_upper"]),
        "kind": str(row["kind"]),
        "lower_comparator_active": lower_active,
        "name": str(row["name"]),
        "no_wrap_max": 2 * int(row["guard"]) + int(row["span"]),
        "no_wrap_proven": 2 * int(row["guard"]) + int(row["span"]) < (1 << int(row["width"])),
        "orientation_costs": {str(item["q"]): item["normalization_one_way"] for item in candidates},
        "overlap_lower": int(chosen["overlap_lower"]),
        "overlap_upper": int(chosen["overlap_upper"]),
        "reachable_max": int(chosen["reachable_max"]),
        "reachable_min": int(chosen["reachable_min"]),
        "upper_comparator_active": upper_active,
        "width": int(row["width"]),
    }
    return {**core, "proof_sha256": canonical_json_sha256(core)}


def _guarded_row_live_cost(
    row: Mapping[str, Any],
    proof: Mapping[str, Any],
) -> tuple[Cost, dict[str, int], dict[str, dict[str, int]]]:
    if int(proof["delta_i_minus_j"]) == 0:
        return (
            Cost(),
            {"comparator_macros": 0, "normalization_add_macros": 0, "orientation_predicate_toggles": 0, "row_flag_toggles": 0},
            {"comparator_by_width": {}, "controlled_add_by_width": {}, "mcx_by_controls": {}},
        )
    width = int(row["width"])
    one_way = _controlled_ripple_add_cost(width, int(proof["add_constant_when_orientation_differs"]))
    total = one_way.scale(2)
    # A fresh orientation predicate is computed and cleared for normalization
    # and again for denormalization after the coherent exchange.
    total += _gate_cost(2).scale(4)
    macros = {
        "comparator_macros": 0,
        "normalization_add_macros": 2,
        "orientation_predicate_toggles": 4,
        "row_flag_toggles": 0,
    }
    replay_terms: dict[str, dict[str, int]] = {
        "comparator_by_width": {},
        "controlled_add_by_width": {str(width): 2},
        "mcx_by_controls": {"2": 4},
    }
    lower_active = bool(proof["lower_comparator_active"])
    upper_active = bool(proof["upper_comparator_active"])
    if lower_active and upper_active:
        ge = _ripple_comparator_cost(width, int(proof["guarded_interval_lower"]), relation="GE")
        le = _ripple_comparator_cost(width, int(proof["guarded_interval_upper"]), relation="LE")
        total += (ge + le).scale(4)
        total += _gate_cost(2).scale(2)
        macros["comparator_macros"] = 8
        macros["row_flag_toggles"] = 2
        replay_terms["comparator_by_width"][str(width)] = 8
        replay_terms["mcx_by_controls"]["2"] += 2
    elif lower_active:
        total += _ripple_comparator_cost(
            width,
            int(proof["guarded_interval_lower"]),
            relation="GE",
        ).scale(2)
        macros["comparator_macros"] = 2
        replay_terms["comparator_by_width"][str(width)] = 2
    elif upper_active:
        total += _ripple_comparator_cost(
            width,
            int(proof["guarded_interval_upper"]),
            relation="LE",
        ).scale(2)
        macros["comparator_macros"] = 2
        replay_terms["comparator_by_width"][str(width)] = 2
    return total, macros, replay_terms


def _compile_one_swap_position(rows: Sequence[Mapping[str, Any]], i: int, j: int, position: int) -> dict[str, Any]:
    proofs = [_guarded_row_proof(row, i, j) for row in rows]
    dead_rows = [str(proof["name"]) for proof in proofs if proof["dead"]]
    live = not dead_rows
    total = Cost()
    macro_totals = {
        "aggregate_toggles": 0,
        "comparator_macros": 0,
        "controlled_ry": 0,
        "different_bit_cx": 0,
        "gray_path_cx": 0,
        "normalization_add_macros": 0,
        "orientation_predicate_toggles": 0,
        "row_flag_toggles": 0,
    }
    active_flags = 0
    replay_terms: dict[str, Any] = {
        "comparator_by_width": {},
        "controlled_add_by_width": {},
        "direct_cnot": 0,
        "mcx_by_controls": {},
    }
    if live:
        for row, proof in zip(rows, proofs):
            row_cost, row_macros, row_terms = _guarded_row_live_cost(row, proof)
            total += row_cost
            for name, value in row_macros.items():
                macro_totals[name] += int(value)
            for family in ("comparator_by_width", "controlled_add_by_width", "mcx_by_controls"):
                for key, value in row_terms[family].items():
                    replay_terms[family][key] = replay_terms[family].get(key, 0) + int(value)
            if proof["lower_comparator_active"] or proof["upper_comparator_active"]:
                active_flags += 1
        total += _gate_cost(1).scale(4)
        macro_totals["different_bit_cx"] = 4
        if active_flags:
            total += _gate_cost(1 + active_flags).scale(2)
            macro_totals["aggregate_toggles"] = 2
            controls = str(1 + active_flags)
            replay_terms["mcx_by_controls"][controls] = replay_terms["mcx_by_controls"].get(controls, 0) + 2
        total += _gate_cost(1).scale(2)
        total += Cost(cnot=2, one_qubit=4, abstract_gates=1)
        macro_totals["gray_path_cx"] = 2
        macro_totals["controlled_ry"] = 1
        replay_terms["direct_cnot"] = 8
    core = {
        "active_flag_rows": active_flags if live else 0,
        "dead_constraint_rows": dead_rows,
        "edge": [i, j],
        "live": live,
        "macros": macro_totals,
        "position": position,
        "record_kind": "LIVE_GUARDED_SLACK_PAIR_ROTATION" if live else "CERTIFIED_IDENTITY_POSITION",
        "resources": total.as_dict(),
        "cnot_replay_terms": replay_terms,
        "row_proof_sha256": [proof["proof_sha256"] for proof in proofs],
    }
    return {**core, "position_ir_sha256": canonical_json_sha256(core)}


def _cache_value(mask: int, row: Mapping[str, Any]) -> int:
    value = sum(int(row["coefficients"][index]) for index in _mask_indices(mask)) + int(row["cache_offset"])
    if not (int(row["guard"]) <= value <= int(row["guard"]) + int(row["span"])):
        raise ValueError("Certified bridge endpoint is outside guarded feasible support.")
    return value


def _cache_preparation_cost(rows: Sequence[Mapping[str, Any]]) -> tuple[Cost, dict[str, Any]]:
    total = Cost()
    controlled_adds = 0
    controlled_add_by_width: dict[str, int] = {}
    constant_initialization_x = 0
    for row in rows:
        width = int(row["width"])
        offset = int(row["cache_offset"]) & ((1 << width) - 1)
        constant_initialization_x += offset.bit_count()
        for coefficient in row["coefficients"]:
            if int(coefficient) != 0:
                total += _controlled_ripple_add_cost(width, int(coefficient))
                controlled_adds += 1
                controlled_add_by_width[str(width)] = controlled_add_by_width.get(str(width), 0) + 1
    total += Cost(one_qubit=constant_initialization_x, abstract_gates=constant_initialization_x, x=constant_initialization_x)
    return total, {
        "constant_initialization_x": constant_initialization_x,
        "controlled_add_macros": controlled_adds,
        "controlled_add_by_width": controlled_add_by_width,
        "scope": "COHERENT_CACHE_PREPARATION_REPORTED_OUTSIDE_MIXER_NUMERATOR",
    }


def compile_seed_one_swap_layer(
    certificate: Mapping[str, Any],
    compression: Mapping[str, Any],
) -> dict[str, Any]:
    rows = _guarded_rows(certificate, compression)
    positions: list[dict[str, Any]] = []
    position = 0
    for i in range(N):
        for j in range(i + 1, N):
            positions.append(_compile_one_swap_position(rows, i, j, position))
            position += 1
    if position != EDGE_COUNT:
        raise AssertionError("Ordered one-swap inventory mismatch.")
    total = Cost()
    macro_totals: dict[str, int] = {}
    replay_terms: dict[str, Any] = {
        "comparator_by_width": {},
        "controlled_add_by_width": {},
        "direct_cnot": 0,
        "mcx_by_controls": {},
    }
    for row in positions:
        resource = row["resources"]
        total += Cost(
            cnot=int(resource["selected_model_cnot"]),
            one_qubit=int(resource["selected_model_one_qubit_gates"]),
            abstract_gates=int(resource["abstract_gate_count"]),
            x=int(resource["abstract_x"]),
            cx=int(resource["abstract_cx"]),
            ccx=int(resource["abstract_ccx"]),
            mcx=int(resource["abstract_mcx"]),
            clean_decomposition_ancillas=int(resource["clean_decomposition_ancillas"]),
        )
        for name, value in row["macros"].items():
            macro_totals[name] = macro_totals.get(name, 0) + int(value)
        terms = row["cnot_replay_terms"]
        replay_terms["direct_cnot"] += int(terms["direct_cnot"])
        for family in ("comparator_by_width", "controlled_add_by_width", "mcx_by_controls"):
            for key, value in terms[family].items():
                replay_terms[family][key] = replay_terms[family].get(key, 0) + int(value)
    preparation, preparation_macros = _cache_preparation_cost(rows)
    widths = [int(row["width"]) for row in rows]
    maximum_width = max(widths)
    reusable_algorithm_scratch = maximum_width + 1 + 1 + 1 + 2 + len(rows) + 1
    replay_cnot = (
        sum(int(count) * (68 * int(width) - 102) for width, count in replay_terms["controlled_add_by_width"].items())
        + sum(int(count) * (16 * int(width) - 9) for width, count in replay_terms["comparator_by_width"].items())
        + sum(int(count) * _gate_cost(int(controls)).cnot for controls, count in replay_terms["mcx_by_controls"].items())
        + int(replay_terms["direct_cnot"])
    )
    if replay_cnot != total.cnot:
        raise AssertionError("Independent one-swap CNOT formula replay mismatch.")
    preparation_replay_cnot = sum(
        int(count) * (68 * int(width) - 102)
        for width, count in preparation_macros["controlled_add_by_width"].items()
    )
    if preparation_replay_cnot != preparation.cnot:
        raise AssertionError("Independent cache-preparation CNOT formula replay mismatch.")
    core = {
        "budget_cnot": BUDGET_CNOT,
        "cache_preparation_outside_numerator": {
            "macros": preparation_macros,
            "resources": preparation.as_dict(),
        },
        "cache_qubits": sum(widths),
        "certified_identity_positions": sum(not row["live"] for row in positions),
        "constraint_registers": [
            {
                "guard": int(row["guard"]),
                "kind": str(row["kind"]),
                "name": str(row["name"]),
                "no_wrap_max": 2 * int(row["guard"]) + int(row["span"]),
                "scale": int(row["scale"]),
                "shift": int(row["shift"]),
                "span": int(row["span"]),
                "width": int(row["width"]),
            }
            for row in rows
        ],
        "data_qubits": N,
        "instance_id": str(certificate["instance_id"]),
        "live_positions": sum(bool(row["live"]) for row in positions),
        "logical_qubits_with_clean_decomposition_ancillas": N + sum(widths) + reusable_algorithm_scratch + total.clean_decomposition_ancillas,
        "macro_totals": macro_totals,
        "independent_cnot_formula_replay": {
            "match": True,
            "replay_selected_model_cnot": replay_cnot,
            "terms": replay_terms,
        },
        "ordered_position_ir_sha256": canonical_json_sha256([row["position_ir_sha256"] for row in positions]),
        "ordered_positions": EDGE_COUNT,
        "parent_certificate_sha": str(certificate["certificate_sha"]),
        "reusable_algorithm_scratch_qubits": reusable_algorithm_scratch,
        "row_proof_manifest_sha256": canonical_json_sha256([row["row_proof_sha256"] for row in positions]),
        "seed": int(certificate["seed"]),
        "selected_model": SELECTED_MODEL,
        "selected_model_layer_resources": total.as_dict(),
    }
    return {**core, "one_swap_layer_sha256": canonical_json_sha256(core)}


def _joint_endpoint_bits(mask: int, rows: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    bits = mask
    offset = N
    for row in rows:
        value = _cache_value(mask, row)
        bits |= value << offset
        offset += int(row["width"])
    return bits, offset


def compile_bridge_rotation(
    bridge: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    source = int(str(bridge["source_mask_hex"]), 16)
    target = int(str(bridge["target_mask_hex"]), 16)
    source_bits, width = _joint_endpoint_bits(source, rows)
    target_bits, replay_width = _joint_endpoint_bits(target, rows)
    if width != replay_width:
        raise AssertionError("Joint register width mismatch.")
    differing = [index for index in range(width) if ((source_bits ^ target_bits) >> index) & 1]
    if len(differing) < 1:
        raise ValueError("Bridge endpoints are identical in the joint register.")
    path = [source_bits]
    current = source_bits
    for index in differing:
        current ^= 1 << index
        path.append(current)
    if path[-1] != target_bits:
        raise AssertionError("Gray bridge path failed to reach target.")
    total = Cost()
    negative_control_sum = 0
    # Forward path omits the final differing bit; the same gates are inverted.
    for state, target_bit in zip(path[:-2], differing[:-1]):
        negative = (width - 1) - (state & ~(1 << target_bit)).bit_count()
        gate = _gate_cost(width - 1, negative)
        total += gate.scale(2)
        negative_control_sum += 2 * negative
    central_state = path[-2]
    central_target = differing[-1]
    central_negative = (width - 1) - (central_state & ~(1 << central_target)).bit_count()
    total += _gate_cost(width - 1, central_negative).scale(2)
    total += Cost(one_qubit=2, abstract_gates=2)
    negative_control_sum += 2 * central_negative
    expected_mcx = 2 * len(differing)
    core = {
        "bridge_sha256": str(bridge["bridge_sha256"]),
        "data_hamming_distance": (source ^ target).bit_count(),
        "differing_joint_bit_indices": differing,
        "gray_path_sha256": canonical_json_sha256([f"{state:0{(width + 3) // 4}x}" for state in path]),
        "joint_endpoint_hamming_distance": len(differing),
        "joint_register_qubits": width,
        "logical_qubits_with_clean_decomposition_ancillas": (
            width + total.clean_decomposition_ancillas
        ),
        "negative_control_wrapper_count": 2 * negative_control_sum,
        "selected_model_mcx_occurrences": expected_mcx,
        "selected_model_resources": total.as_dict(),
        "source_mask_hex": f"{source:010x}",
        "target_mask_hex": f"{target:010x}",
    }
    if total.cnot != expected_mcx * (6 * (2 * (width - 1) - 3)):
        raise AssertionError("Two-level bridge CNOT formula mismatch.")
    return {**core, "bridge_ir_sha256": canonical_json_sha256(core)}


def build_augmented_connectivity_certificate(
    protocol: Mapping[str, Any],
    *,
    root: str | Path | None = None,
) -> dict[str, Any]:
    if protocol.get("all_triple_replays_match") is not True:
        raise ValueError("The triple bridge replay is incomplete.")
    v40 = _v40_artifact(root)
    audits = list(protocol.get("audit_rows") or [])
    audit_by_source = {
        (int(row["seed"]), str(row["source_mask_hex"])): row
        for row in audits
    }
    seed_rows: list[dict[str, Any]] = []
    for parent_row in v40["connectivity_evidence"]["seed_rows"]:
        seed = int(parent_row["seed"])
        components = list(parent_row["component_representatives"])
        representatives = [str(row["mask_hex"]) for row in components]
        non_singletons = [str(row["mask_hex"]) for row in components if int(row["size"]) > 1]
        singletons = [str(row["mask_hex"]) for row in components if int(row["size"]) == 1]
        if len(non_singletons) != 1:
            raise ValueError(f"Seed {seed} does not have exactly one authenticated non-singleton component.")
        giant = non_singletons[0]
        candidates: dict[tuple[int, int], dict[str, Any]] = {}
        for source_hex in singletons:
            audit = audit_by_source.get((seed, source_hex))
            if audit is None or audit.get("triple_replay_match") is not True:
                raise ValueError(f"Missing exact bridge audit for seed {seed} source {source_hex}.")
            for record in audit["feasible_records"]:
                target_hex = str(record["target_mask_hex"])
                target_component = target_hex if target_hex in singletons else giant
                source_component = source_hex
                endpoint_pair = tuple(sorted((int(source_hex, 16), int(target_hex, 16))))
                component_pair = tuple(sorted((source_component, target_component)))
                candidate_core = {
                    "added": [int(value) for value in record["added"]],
                    "component_pair": list(component_pair),
                    "exact_values": [int(value) for value in record["exact_values"]],
                    "removed": [int(value) for value in record["removed"]],
                    "seed": seed,
                    "source_component_representative": source_component,
                    "source_mask_hex": source_hex,
                    "target_component_representative": target_component,
                    "target_mask_hex": target_hex,
                }
                candidate = {**candidate_core, "bridge_candidate_sha256": canonical_json_sha256(candidate_core)}
                existing = candidates.get(endpoint_pair)
                candidate_key = (tuple(candidate["component_pair"]), endpoint_pair, tuple(candidate["removed"]), tuple(candidate["added"]))
                existing_key = None if existing is None else (
                    tuple(existing["component_pair"]), endpoint_pair, tuple(existing["removed"]), tuple(existing["added"])
                )
                if existing_key is None or candidate_key < existing_key:
                    candidates[endpoint_pair] = candidate
        ordered = sorted(
            candidates.items(),
            key=lambda item: (
                tuple(item[1]["component_pair"]),
                item[0],
                tuple(item[1]["removed"]),
                tuple(item[1]["added"]),
            ),
        )
        dsu = _Dsu(representatives)
        selected: list[dict[str, Any]] = []
        for endpoint_pair, candidate in ordered:
            left, right = candidate["component_pair"]
            if dsu.unite(str(left), str(right)):
                bridge_core = {
                    **candidate,
                    "endpoint_pair_hex": [f"{endpoint_pair[0]:010x}", f"{endpoint_pair[1]:010x}"],
                    "hamming_distance": (endpoint_pair[0] ^ endpoint_pair[1]).bit_count(),
                    "selection_rank": len(selected),
                }
                selected.append({**bridge_core, "bridge_sha256": canonical_json_sha256(bridge_core)})
            if len({dsu.find(label) for label in representatives}) == 1:
                break
        final_components = len({dsu.find(label) for label in representatives})
        if any(int(row["hamming_distance"]) != 4 for row in selected):
            raise AssertionError("Selected bridge is not a two-out/two-in move.")
        core = {
            "all_incident_candidates_audited": all(
                (seed, source) in audit_by_source and int(audit_by_source[(seed, source)]["candidates_audited"]) == 19_575
                for source in singletons
            ),
            "authenticated_v40_component_count": int(parent_row["component_count"]),
            "authenticated_v40_component_representatives": copy.deepcopy(components),
            "authenticated_v40_exact_one_swap_edges": int(parent_row["exact_state_graph_edge_count"]),
            "authenticated_v40_feasible_vertices": int(parent_row["feasible_vertex_count"]),
            "candidate_bridge_count": len(ordered),
            "connected_by_certified_subgraph": final_components == 1,
            "final_component_count": final_components,
            "seed": seed,
            "selected_bridge_count": len(selected),
            "selected_bridges": selected,
            "selected_spanning_subgraph_edges": int(parent_row["exact_state_graph_edge_count"]) + len(selected),
            "singleton_component_count": len(singletons),
        }
        seed_rows.append({**core, "seed_connectivity_sha256": canonical_json_sha256(core)})
    all_connected = all(row["connected_by_certified_subgraph"] for row in seed_rows)
    aggregate = {
        "all_eight_seeds_connected_by_certified_subgraph": all_connected and len(seed_rows) == len(SEEDS),
        "authenticated_v40_components_before_bridges": sum(int(row["authenticated_v40_component_count"]) for row in seed_rows),
        "audited_incident_two_swap_candidates": sum(int(row["candidates_audited"]) for row in audits),
        "complete_augmented_edge_count": "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE",
        "feasible_incident_two_swap_candidates": sum(int(row["feasible_neighbor_count"]) for row in audits),
        "final_components_across_seeds": sum(int(row["final_component_count"]) for row in seed_rows),
        "selected_bridge_count": sum(int(row["selected_bridge_count"]) for row in seed_rows),
        "selected_spanning_subgraph_edges": sum(int(row["selected_spanning_subgraph_edges"]) for row in seed_rows),
        "v40_exact_one_swap_edges": sum(int(row["authenticated_v40_exact_one_swap_edges"]) for row in seed_rows),
        "v40_feasible_vertices": sum(int(row["authenticated_v40_feasible_vertices"]) for row in seed_rows),
    }
    decision = (
        "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
        if aggregate["all_eight_seeds_connected_by_certified_subgraph"]
        else "AUGMENTED_1_2_EXCHANGE_GRAPH_DISCONNECTED_COUNTEREXAMPLE"
    )
    core = {
        "aggregate": aggregate,
        "connectivity_decision": decision,
        "proof_scope": "AUTHENTICATED_COMPLETE_V40_ONE_SWAP_COMPONENT_FOREST_PLUS_SELECTED_EXACT_TWO_SWAP_BRIDGES",
        "seed_rows": seed_rows,
    }
    return {**core, "augmented_connectivity_sha256": canonical_json_sha256(core)}


def _cost_from_dict(resource: Mapping[str, Any]) -> Cost:
    return Cost(
        cnot=int(resource["selected_model_cnot"]),
        one_qubit=int(resource["selected_model_one_qubit_gates"]),
        abstract_gates=int(resource["abstract_gate_count"]),
        x=int(resource["abstract_x"]),
        cx=int(resource["abstract_cx"]),
        ccx=int(resource["abstract_ccx"]),
        mcx=int(resource["abstract_mcx"]),
        clean_decomposition_ancillas=int(resource["clean_decomposition_ancillas"]),
    )


def _independent_seed_resource_replay(
    certificate: Mapping[str, Any],
    compression: Mapping[str, Any],
    selected_bridges: Sequence[Mapping[str, Any]],
    *,
    r1_connected: bool,
    r2_connected: bool,
) -> dict[str, Any]:
    """Second complete ledger from closed formulas, without primary IR costs."""

    def gate_formula(controls: int, negative_controls: int = 0) -> Cost:
        wrappers = 2 * negative_controls
        if controls == 0:
            return Cost(one_qubit=1, abstract_gates=1, x=1)
        if controls == 1:
            return Cost(cnot=1, one_qubit=wrappers, abstract_gates=1 + wrappers, x=wrappers, cx=1)
        if controls == 2:
            return Cost(cnot=6, one_qubit=9 + wrappers, abstract_gates=1 + wrappers, x=wrappers, ccx=1)
        ladder_toffoli = 2 * controls - 3
        return Cost(
            cnot=6 * ladder_toffoli,
            one_qubit=9 * ladder_toffoli + wrappers,
            abstract_gates=1 + wrappers,
            x=wrappers,
            mcx=1,
            clean_decomposition_ancillas=controls - 2,
        )

    def add_formula(width: int, constant: int) -> Cost:
        base_toffoli = 2 * width - 3
        base_cnot = 5 * width - 7
        base_x = 2 * width - 6
        constant_x = 2 * (int(constant) & ((1 << width) - 1)).bit_count()
        return Cost(
            cnot=18 * base_toffoli + 6 * base_cnot + base_x,
            one_qubit=27 * base_toffoli + 9 * base_cnot + constant_x,
            abstract_gates=base_toffoli + base_cnot + base_x + constant_x,
            x=constant_x,
            cx=base_x,
            ccx=base_cnot,
            mcx=base_toffoli,
            clean_decomposition_ancillas=1,
        )

    def comparator_formula(width: int, constant: int, relation: str) -> Cost:
        maximum = (1 << width) - 1
        if relation == "GE":
            if not 0 < int(constant) <= maximum:
                raise ValueError("Independent GE encoding is outside the unsigned register.")
            encoded = int(constant)
            output_x = 1
        elif relation == "LE":
            if not 0 <= int(constant) < maximum:
                raise ValueError("Independent LE encoding is outside the unsigned register.")
            encoded = int(constant) + 1
            output_x = 0
        else:
            raise ValueError("Independent comparator relation must be GE or LE.")
        toffoli = 2 * width - 1
        cnot = 4 * width - 3
        abstract_x = 2 * encoded.bit_count() + output_x
        return Cost(
            cnot=6 * toffoli + cnot,
            one_qubit=9 * toffoli + abstract_x,
            abstract_gates=toffoli + cnot + abstract_x,
            x=abstract_x,
            cx=cnot,
            ccx=toffoli,
        )

    # Rebuild guarded rows directly from the frozen certificate and compression
    # witnesses instead of consuming the primary compiler's guarded-row IR.
    compressed_by_name = {str(row["factor"]): row for row in compression["factor_rows"]}
    independent_rows: list[dict[str, Any]] = []
    for group in certificate.get("group_bands") or []:
        members = {int(index) for index in group["indices"]}
        coefficients = tuple(1 if index in members else 0 for index in range(N))
        lower = int(group["lower"])
        upper = int(group["upper"])
        independent_rows.append({
            "cache_offset": -lower + 1,
            "coefficients": coefficients,
            "compression_certificate_sha256": "IDENTITY_GROUP_ROW",
            "guard": 1,
            "kind": "GROUP",
            "lower": lower,
            "name": str(group["name"]),
            "scale": 1,
            "shift": 0,
            "span": upper - lower,
            "upper": upper,
            "width": max(3, (2 + upper - lower).bit_length()),
        })
    for factor in certificate.get("factor_bands") or []:
        reduced = compressed_by_name[str(factor["name"])]
        coefficients = tuple(int(value) for value in reduced["compressed_coefficients_int"])
        lower = int(reduced["compressed_lower_int"])
        upper = int(reduced["compressed_upper_int"])
        guard = max(coefficients) - min(coefficients)
        span = upper - lower
        independent_rows.append({
            "cache_offset": -lower + guard,
            "coefficients": coefficients,
            "compression_certificate_sha256": str(reduced["compression_certificate_sha256"]),
            "guard": guard,
            "kind": "FACTOR",
            "lower": lower,
            "name": str(factor["name"]),
            "scale": int(reduced["scale"]),
            "shift": int(reduced["selected_shift"]),
            "span": span,
            "upper": upper,
            "width": max(3, (2 * guard + span).bit_length()),
        })
    rows = tuple(independent_rows)
    if len(rows) != 7 or canonical_json_sha256(rows) != canonical_json_sha256(_guarded_rows(certificate, compression)):
        raise AssertionError("Independent guarded-row reconstruction mismatch.")

    one_swap = Cost()
    live_positions = 0
    macro_totals = {
        "aggregate_toggles": 0,
        "comparator_macros": 0,
        "controlled_ry": 0,
        "different_bit_cx": 0,
        "gray_path_cx": 0,
        "normalization_add_macros": 0,
        "orientation_predicate_toggles": 0,
        "row_flag_toggles": 0,
    }
    for i in range(N):
        for j in range(i + 1, N):
            position_cost = Cost()
            position_macros = {name: 0 for name in macro_totals}
            active_flags = 0
            dead = False
            for row in rows:
                coefficients = row["coefficients"]
                delta = int(coefficients[i]) - int(coefficients[j])
                if delta == 0:
                    continue
                width = int(row["width"])
                orientation_candidates: list[tuple[int, int, int, int, int, int]] = []
                for q in (0, 1):
                    constant = -delta if q == 0 else delta
                    encoded = constant & ((1 << width) - 1)
                    one_qubit_tie_break = 2 * encoded.bit_count()
                    remaining = [int(coefficients[index]) for index in range(N) if index not in {i, j}]
                    selected = int(coefficients[i if q == 1 else j])
                    reachable_min = selected + sum(sorted(remaining)[: K - 1]) + int(row["cache_offset"])
                    reachable_max = selected + sum(sorted(remaining, reverse=True)[: K - 1]) + int(row["cache_offset"])
                    central_lower = int(row["guard"])
                    central_upper = central_lower + int(row["span"])
                    sign = 1 - 2 * q
                    interval_lower = max(central_lower, central_lower - sign * delta)
                    interval_upper = min(central_upper, central_upper - sign * delta)
                    orientation_candidates.append((
                        one_qubit_tie_break,
                        0 if q == 1 else 1,
                        reachable_min,
                        reachable_max,
                        interval_lower,
                        interval_upper,
                    ))
                tie_break, q_tie, reachable_min, reachable_max, interval_lower, interval_upper = min(orientation_candidates)
                chosen_q = 1 if q_tie == 0 else 0
                chosen_constant = delta if chosen_q == 1 else -delta
                if max(reachable_min, interval_lower) > min(reachable_max, interval_upper):
                    dead = True
                    break
                lower_active = reachable_min < interval_lower
                upper_active = reachable_max > interval_upper
                if tie_break != 2 * (chosen_constant & ((1 << width) - 1)).bit_count():
                    raise AssertionError("Independent orientation tie-break mismatch.")
                position_cost += add_formula(width, chosen_constant).scale(2)
                position_cost += gate_formula(2).scale(4)
                position_macros["normalization_add_macros"] += 2
                position_macros["orientation_predicate_toggles"] += 4
                if lower_active and upper_active:
                    position_cost += (
                        comparator_formula(width, interval_lower, "GE")
                        + comparator_formula(width, interval_upper, "LE")
                    ).scale(4)
                    position_cost += gate_formula(2).scale(2)
                    position_macros["comparator_macros"] += 8
                    position_macros["row_flag_toggles"] += 2
                    active_flags += 1
                elif lower_active or upper_active:
                    relation = "GE" if lower_active else "LE"
                    constant = interval_lower if lower_active else interval_upper
                    position_cost += comparator_formula(width, constant, relation).scale(2)
                    position_macros["comparator_macros"] += 2
                    active_flags += 1
            if dead:
                continue
            live_positions += 1
            position_cost += gate_formula(1).scale(4)
            position_macros["different_bit_cx"] = 4
            if active_flags:
                controls = 1 + active_flags
                position_cost += gate_formula(controls).scale(2)
                position_macros["aggregate_toggles"] = 2
            position_cost += gate_formula(1).scale(2)
            position_cost += Cost(cnot=2, one_qubit=4, abstract_gates=1)
            position_macros["gray_path_cx"] = 2
            position_macros["controlled_ry"] = 1
            one_swap += position_cost
            for name, value in position_macros.items():
                macro_totals[name] += value

    bridge_cost = Cost()
    bridge_terms: list[dict[str, Any]] = []

    def joint_endpoint(mask: int) -> tuple[int, int]:
        bits = mask
        offset = N
        selected = _mask_indices(mask)
        for row in rows:
            value = sum(int(row["coefficients"][index]) for index in selected) + int(row["cache_offset"])
            if not int(row["guard"]) <= value <= int(row["guard"]) + int(row["span"]):
                raise ValueError("Independent bridge endpoint is outside guarded feasible support.")
            bits |= value << offset
            offset += int(row["width"])
        return bits, offset

    for bridge in selected_bridges:
        source = int(str(bridge["source_mask_hex"]), 16)
        target = int(str(bridge["target_mask_hex"]), 16)
        source_joint, width = joint_endpoint(source)
        target_joint, replay_width = joint_endpoint(target)
        if width != replay_width:
            raise AssertionError("Independent bridge width mismatch.")
        differing = [index for index in range(width) if ((source_joint ^ target_joint) >> index) & 1]
        path = [source_joint]
        current = source_joint
        for index in differing:
            current ^= 1 << index
            path.append(current)
        current_bridge = Cost()
        for state, target_bit in zip(path[:-2], differing[:-1]):
            negative = (width - 1) - (state & ~(1 << target_bit)).bit_count()
            current_bridge += gate_formula(width - 1, negative).scale(2)
        central_state = path[-2]
        central_target = differing[-1]
        central_negative = (width - 1) - (central_state & ~(1 << central_target)).bit_count()
        current_bridge += gate_formula(width - 1, central_negative).scale(2)
        current_bridge += Cost(one_qubit=2, abstract_gates=2)
        bridge_cost += current_bridge
        bridge_terms.append({
            "bridge_sha256": str(bridge["bridge_sha256"]),
            "joint_hamming_distance": len(differing),
            "joint_register_qubits": width,
            "logical_qubits_with_clean_decomposition_ancillas": (
                width + current_bridge.clean_decomposition_ancillas
            ),
            "resources": current_bridge.as_dict(),
            "source_mask_hex": f"{source:010x}",
            "target_mask_hex": f"{target:010x}",
        })

    cache_preparation = Cost()
    cache_adds = 0
    cache_adds_by_width: dict[str, int] = {}
    offset_x = 0
    for row in rows:
        width = int(row["width"])
        encoded_offset = int(row["cache_offset"]) & ((1 << width) - 1)
        offset_x += encoded_offset.bit_count()
        for coefficient in row["coefficients"]:
            if int(coefficient) == 0:
                continue
            cache_preparation += add_formula(width, int(coefficient))
            cache_adds += 1
            cache_adds_by_width[str(width)] = cache_adds_by_width.get(str(width), 0) + 1
    cache_preparation += Cost(one_qubit=offset_x, abstract_gates=offset_x, x=offset_x)
    r2_cost = one_swap + bridge_cost
    base_register_qubits = N + sum(int(row["width"]) for row in rows)
    reusable_algorithm_scratch = max(int(row["width"]) for row in rows) + 1 + 1 + 1 + 2 + len(rows) + 1
    r1_work_qubits = reusable_algorithm_scratch + one_swap.clean_decomposition_ancillas
    r2_work_qubits = max(r1_work_qubits, bridge_cost.clean_decomposition_ancillas)

    def candidate_decision(connected: bool, cost: Cost) -> str:
        if not connected:
            return "REJECTED_CONNECTIVITY"
        return "PASSED" if cost.cnot <= BUDGET_CNOT else "REJECTED_SELECTED_MODEL_CNOT_BUDGET"

    core = {
        "bridge_cnot": bridge_cost.cnot,
        "bridge_resources": bridge_cost.as_dict(),
        "bridge_terms": bridge_terms,
        "cache_preparation_cnot_outside_numerator": cache_preparation.cnot,
        "cache_preparation_macros": {
            "constant_initialization_x": offset_x,
            "controlled_add_by_width": cache_adds_by_width,
            "controlled_add_macros": cache_adds,
            "scope": "COHERENT_CACHE_PREPARATION_REPORTED_OUTSIDE_MIXER_NUMERATOR",
        },
        "cache_preparation_resources": cache_preparation.as_dict(),
        "compression_sha256": str(compression["seed_compression_sha256"]),
        "guarded_rows_sha256": canonical_json_sha256(rows),
        "live_one_swap_positions": live_positions,
        "certified_identity_positions": EDGE_COUNT - live_positions,
        "method": "INDEPENDENT_COMPLETE_CLOSED_FORMULA_HIGH_LEVEL_TOPOLOGY_REPLAY_V2",
        "one_swap_cnot": one_swap.cnot,
        "one_swap_macro_totals": macro_totals,
        "one_swap_resources": one_swap.as_dict(),
        "ordered_positions": EDGE_COUNT,
        "r1": {
            "budget_margin_cnot": BUDGET_CNOT - one_swap.cnot,
            "connectivity_pass": bool(r1_connected),
            "decision": candidate_decision(r1_connected, one_swap),
            "logical_qubits_with_clean_decomposition_ancillas": (
                base_register_qubits + r1_work_qubits
            ),
        },
        "r2": {
            "budget_margin_cnot": BUDGET_CNOT - r2_cost.cnot,
            "connectivity_pass": bool(r2_connected),
            "decision": candidate_decision(r2_connected, r2_cost),
            "logical_qubits_with_clean_decomposition_ancillas": (
                base_register_qubits + r2_work_qubits
            ),
        },
        "r2_cnot": r2_cost.cnot,
        "r2_resources": r2_cost.as_dict(),
        "seed": int(certificate["seed"]),
        "selected_bridge_sha256": [str(bridge["bridge_sha256"]) for bridge in selected_bridges],
        "selected_model": SELECTED_MODEL,
    }
    return {**core, "independent_resource_replay_sha256": canonical_json_sha256(core)}


def build_resource_evidence(
    certificates: Mapping[int, Mapping[str, Any]],
    compressions: Sequence[Mapping[str, Any]],
    connectivity: Mapping[str, Any],
    *,
    progress: Any | None = None,
) -> dict[str, Any]:
    compression_by_seed = {int(row["seed"]): row for row in compressions}
    connectivity_by_seed = {int(row["seed"]): row for row in connectivity["seed_rows"]}
    seed_rows: list[dict[str, Any]] = []
    for seed in SEEDS:
        if progress is not None:
            progress(f"V4.1 guarded-slack resource ledger · seed {seed}")
        certificate = certificates[seed]
        compression = compression_by_seed[seed]
        one_swap = compile_seed_one_swap_layer(certificate, compression)
        guarded_rows = _guarded_rows(certificate, compression)
        bridge_ir = [compile_bridge_rotation(bridge, guarded_rows) for bridge in connectivity_by_seed[seed]["selected_bridges"]]
        one_swap_cost = _cost_from_dict(one_swap["selected_model_layer_resources"])
        bridge_cost = Cost()
        for bridge in bridge_ir:
            bridge_cost += _cost_from_dict(bridge["selected_model_resources"])
        r2_cost = one_swap_cost + bridge_cost
        r1_connected = int(connectivity_by_seed[seed]["authenticated_v40_component_count"]) == 1
        r2_connected = bool(connectivity_by_seed[seed]["connected_by_certified_subgraph"])
        r1_core = {
            "budget_cnot": BUDGET_CNOT,
            "budget_margin_cnot": BUDGET_CNOT - one_swap_cost.cnot,
            "candidate_id": "R1_LINEAR_SLACK_ALL_ONE_SWAP",
            "connectivity_pass": r1_connected,
            "decision": (
                "REJECTED_CONNECTIVITY"
                if not r1_connected
                else "PASSED" if one_swap_cost.cnot <= BUDGET_CNOT else "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            ),
            "logical_qubits_with_clean_decomposition_ancillas": int(
                one_swap["logical_qubits_with_clean_decomposition_ancillas"]
            ),
            "selected_model_layer_resources": one_swap_cost.as_dict(),
        }
        base_register_qubits = N + int(one_swap["cache_qubits"])
        r1_work_qubits = (
            int(one_swap["reusable_algorithm_scratch_qubits"])
            + one_swap_cost.clean_decomposition_ancillas
        )
        r2_work_qubits = max(
            r1_work_qubits,
            bridge_cost.clean_decomposition_ancillas,
        )
        r2_core = {
            "bridge_resources": bridge_cost.as_dict(),
            "budget_cnot": BUDGET_CNOT,
            "budget_margin_cnot": BUDGET_CNOT - r2_cost.cnot,
            "candidate_id": "R2_LINEAR_SLACK_ONE_SWAP_PLUS_TWO_SWAP_BRIDGES",
            "connectivity_pass": r2_connected,
            "decision": (
                "REJECTED_CONNECTIVITY"
                if not r2_connected
                else "PASSED" if r2_cost.cnot <= BUDGET_CNOT else "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            ),
            "logical_qubits_with_clean_decomposition_ancillas": (
                base_register_qubits + r2_work_qubits
            ),
            "selected_bridge_ir": bridge_ir,
            "selected_model_layer_resources": r2_cost.as_dict(),
        }
        independent_replay = _independent_seed_resource_replay(
            certificate,
            compression,
            connectivity_by_seed[seed]["selected_bridges"],
            r1_connected=r1_connected,
            r2_connected=r2_connected,
        )
        expected_bridge_sha = [
            str(bridge["bridge_sha256"])
            for bridge in connectivity_by_seed[seed]["selected_bridges"]
        ]
        expected_guarded_rows_sha = canonical_json_sha256(guarded_rows)
        expected_cache = one_swap["cache_preparation_outside_numerator"]
        if not (
            independent_replay["selected_model"] == SELECTED_MODEL
            and independent_replay["compression_sha256"] == str(compression["seed_compression_sha256"])
            and independent_replay["guarded_rows_sha256"] == expected_guarded_rows_sha
            and independent_replay["selected_bridge_sha256"] == expected_bridge_sha
            and independent_replay["ordered_positions"] == EDGE_COUNT == int(one_swap["ordered_positions"])
            and independent_replay["live_one_swap_positions"] == int(one_swap["live_positions"])
            and independent_replay["certified_identity_positions"] == int(one_swap["certified_identity_positions"])
            and independent_replay["one_swap_macro_totals"] == one_swap["macro_totals"]
            and independent_replay["one_swap_resources"] == one_swap_cost.as_dict()
            and independent_replay["one_swap_cnot"] == one_swap_cost.cnot
            and independent_replay["bridge_resources"] == bridge_cost.as_dict()
            and independent_replay["bridge_cnot"] == bridge_cost.cnot
            and independent_replay["r2_resources"] == r2_cost.as_dict()
            and independent_replay["r2_cnot"] == r2_cost.cnot
            and independent_replay["cache_preparation_macros"] == expected_cache["macros"]
            and independent_replay["cache_preparation_resources"] == expected_cache["resources"]
            and independent_replay["cache_preparation_cnot_outside_numerator"]
            == int(expected_cache["resources"]["selected_model_cnot"])
            and independent_replay["r1"]
            == {
                "budget_margin_cnot": r1_core["budget_margin_cnot"],
                "connectivity_pass": r1_core["connectivity_pass"],
                "decision": r1_core["decision"],
                "logical_qubits_with_clean_decomposition_ancillas": r1_core[
                    "logical_qubits_with_clean_decomposition_ancillas"
                ],
            }
            and independent_replay["r2"]
            == {
                "budget_margin_cnot": r2_core["budget_margin_cnot"],
                "connectivity_pass": r2_core["connectivity_pass"],
                "decision": r2_core["decision"],
                "logical_qubits_with_clean_decomposition_ancillas": r2_core[
                    "logical_qubits_with_clean_decomposition_ancillas"
                ],
            }
            and [term["resources"] for term in independent_replay["bridge_terms"]]
            == [bridge["selected_model_resources"] for bridge in bridge_ir]
            and [
                term["logical_qubits_with_clean_decomposition_ancillas"]
                for term in independent_replay["bridge_terms"]
            ]
            == [
                bridge["logical_qubits_with_clean_decomposition_ancillas"]
                for bridge in bridge_ir
            ]
        ):
            raise AssertionError(f"Independent complete resource replay mismatch for seed {seed}.")
        row_core = {
            "cache_preparation_outside_numerator": copy.deepcopy(one_swap["cache_preparation_outside_numerator"]),
            "compression_sha256": str(compression["seed_compression_sha256"]),
            "independent_resource_replay": independent_replay,
            "one_swap_layer": one_swap,
            "r1": {**r1_core, "candidate_sha256": canonical_json_sha256(r1_core)},
            "r2": {**r2_core, "candidate_sha256": canonical_json_sha256(r2_core)},
            "seed": seed,
        }
        seed_rows.append({**row_core, "seed_resource_sha256": canonical_json_sha256(row_core)})
    r1_maximum = max(int(row["r1"]["selected_model_layer_resources"]["selected_model_cnot"]) for row in seed_rows)
    r2_maximum = max(int(row["r2"]["selected_model_layer_resources"]["selected_model_cnot"]) for row in seed_rows)
    r1_all_pass = all(row["r1"]["decision"] == "PASSED" for row in seed_rows)
    r2_all_pass = all(row["r2"]["decision"] == "PASSED" for row in seed_rows)
    aggregate = {
        "budget_cnot": BUDGET_CNOT,
        "cache_preparation_excluded_from_numerator": True,
        "r1_all_seeds_pass": r1_all_pass,
        "r1_decision": "PASSED" if r1_all_pass else "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET",
        "r1_maximum_selected_model_cnot": r1_maximum,
        "r2_all_seeds_pass": r2_all_pass,
        "r2_decision": "PASSED" if r2_all_pass else "REJECTED_CONNECTIVITY_OR_RESOURCE_BUDGET",
        "r2_maximum_selected_model_cnot": r2_maximum,
        "r2_minimum_budget_margin_cnot": min(int(row["r2"]["budget_margin_cnot"]) for row in seed_rows),
        "selected_model": SELECTED_MODEL,
        "independent_resource_replay_all_seeds": True,
        "v39_maximum_selected_model_cnot": 781_332_180,
        "v39_to_v41_r2_maximum_reduction_basis_points": (781_332_180 - r2_maximum) * 10_000 // 781_332_180,
    }
    core = {
        "aggregate": aggregate,
        "architecture_id": "EXACT_COMPRESSED_UNSIGNED_SLACK_LINEAR_ARITHMETIC_WITH_CERTIFIED_BRIDGES_V1",
        "seed_rows": seed_rows,
    }
    return {**core, "resource_evidence_sha256": canonical_json_sha256(core)}


def build_v41_artifact(
    protocol: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    global _BUILD_CACHE
    base = _root(root)
    paths = _paths(base)
    key = tuple(
        raw_file_sha256(paths[name])
        for name in (
            "spec",
            "engine",
            "v40_spec",
            "v40_engine",
            "v40_source",
            "v40_artifact",
            "v40_freeze",
            "v31",
        )
    ) + (source_sha256(), canonical_json_sha256(protocol))
    if use_cache and _BUILD_CACHE is not None and _BUILD_CACHE[0] == key:
        return copy.deepcopy(_BUILD_CACHE[1])
    spec = load_v41_spec(root=base)
    parent = authenticate_parent_chain(root=base)
    if not parent["valid"]:
        raise ValueError(f"V4.0 parent authentication failed: {parent['errors']}")
    if protocol.get("spec_sha256") != spec["v41_spec_sha256"] or protocol.get("all_triple_replays_match") is not True:
        raise ValueError("V4.1 bridge protocol is not admissible under the sealed specification.")
    connectivity = build_augmented_connectivity_certificate(protocol, root=base)
    certificates = _certificate_by_seed(base)
    compressions: list[dict[str, Any]] = []
    for seed in SEEDS:
        if progress is not None:
            progress(f"V4.1 dual-MITM exact compression · seed {seed}")
        compressions.append(build_seed_compression_certificate(certificates[seed]))
    resources = build_resource_evidence(certificates, compressions, connectivity, progress=progress)
    connectivity_pass = connectivity["connectivity_decision"] == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
    resource_pass = resources["aggregate"]["r2_all_seeds_pass"] is True
    if connectivity_pass and resource_pass:
        overall = "V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_PASSED"
        production = "PROVIDER_NEUTRAL_RESEARCH_ARCHITECTURE_ADMITTED_HARDWARE_NOT_AUTHORIZED"
        next_gate = "INDEPENDENT_REVERSIBLE_SIMULATION_AND_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZATION"
        resource_decision = "PASSED_SELECTED_MODEL_CNOT_BUDGET"
    elif connectivity_pass:
        overall = "V41_AUGMENTED_CONNECTIVITY_CERTIFIED_RESOURCE_SCREEN_REJECTED"
        production = "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED"
        next_gate = "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION"
        resource_decision = "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
    else:
        overall = "V41_AUGMENTED_CONNECTIVITY_INCOMPLETE_RESOURCE_ADMISSION_BLOCKED"
        production = "BLOCKED_CONNECTIVITY_HARDWARE_NOT_AUTHORIZED"
        next_gate = "COMPLETE_OR_REVISE_REGISTERED_BRIDGE_FAMILY"
        resource_decision = "BLOCKED_BY_CONNECTIVITY"
    audit_rows = copy.deepcopy(list(protocol["audit_rows"]))
    artifact = {
        "artifact_version": ARTIFACT_VERSION,
        "bridge_audits": {
            "all_triple_replays_match": True,
            "audit_bundle_sha256": canonical_json_sha256(audit_rows),
            "rows": audit_rows,
        },
        "claim_boundary": copy.deepcopy(spec["claim_boundary"]),
        "compression_evidence": {
            "all_factor_predicates_exact": all(row["all_factor_predicates_exact"] for row in compressions),
            "seed_rows": compressions,
            "seed_rows_sha256": canonical_json_sha256(compressions),
        },
        "connectivity_evidence": connectivity,
        "decisions": {
            "augmented_connectivity_decision": connectivity["connectivity_decision"],
            "backend_native": "NOT_RUN_PROVIDER_FREE_PHASE",
            "next_falsifiable_gate": next_gate,
            "overall": overall,
            "production_admission": production,
            "resource_architecture_decision": resource_decision,
        },
        "engine_source_raw_file_sha256": EXPECTED_ENGINE_RAW,
        "parent": {
            "authentication": parent,
            "v40_artifact_raw_file_sha256": EXPECTED_V40_ARTIFACT_RAW,
            "v40_artifact_sha256": EXPECTED_V40_ARTIFACT_SHA,
            "v40_freeze_raw_file_sha256": EXPECTED_V40_FREEZE_RAW,
            "v40_freeze_sha256": EXPECTED_V40_FREEZE_SHA,
            "v40_spec_sha256": EXPECTED_V40_SPEC_SHA,
        },
        "research_classification": "RESEARCH_ONLY",
        "resource_evidence": resources,
        "source_sha256": source_sha256(),
        "spec_raw_file_sha256": raw_file_sha256(paths["spec"]),
        "spec_sha256": spec["v41_spec_sha256"],
        "v39_resource_rejection": {
            "budget_cnot": BUDGET_CNOT,
            "budget_decision": "REJECTED_SELECTED_MODEL_CNOT_BUDGET",
            "maximum_selected_model_cnot": 781_332_180,
            "preserved": True,
        },
        "v41_version": V41_VERSION,
    }
    artifact["artifact_sha256"] = canonical_json_sha256(artifact)
    _BUILD_CACHE = (key, copy.deepcopy(artifact))
    return artifact


def validate_v41_artifact(
    payload: Mapping[str, Any],
    *,
    root: str | Path | None = None,
    authenticate_parent: bool = True,
) -> dict[str, Any]:
    """Rebuild every derived layer and reject any non-canonical artifact.

    SHA-256 fields remain integrity commitments, not scientific evidence by
    themselves. The validator replays both Python bridge enumerators,
    reconstructs all complete-domain compression certificates, rebuilds
    augmented connectivity and both resource ledgers, derives every decision,
    and requires structural equality with the supplied payload.
    """

    errors: list[str] = []
    checks: dict[str, bool] = {
        "artifact_self_hash": False,
        "artifact_version": False,
        "source_and_engine_identity": False,
        "spec_identity": False,
        "research_boundary_exact": False,
        "bridge_source_order_exact": False,
        "bridge_row_hashes_exact": False,
        "bridge_dual_python_replay_exact": False,
        "bridge_method_attestations_exact": False,
        "parent_chain_exact": False,
        "compression_evidence_exact_rebuild": False,
        "connectivity_evidence_exact_rebuild": False,
        "resource_evidence_exact_rebuild": False,
        "decisions_exact_rebuild": False,
        "v39_rejection_exact": False,
        "complete_artifact_exact_rebuild": False,
    }
    if not isinstance(payload, Mapping):
        return {
            "valid": False,
            "checks": checks,
            "failed_checks": list(checks),
            "errors": ["V4.1 artifact payload must be a mapping."],
        }

    try:
        base = _root(root)
        spec = load_v41_spec(root=base)
        artifact_core = {
            key: copy.deepcopy(value)
            for key, value in payload.items()
            if key != "artifact_sha256"
        }
        checks["artifact_self_hash"] = (
            payload.get("artifact_sha256") == canonical_json_sha256(artifact_core)
        )
        checks["artifact_version"] = bool(
            payload.get("artifact_version") == ARTIFACT_VERSION
            and payload.get("v41_version") == V41_VERSION
        )
        checks["source_and_engine_identity"] = bool(
            payload.get("source_sha256") == source_sha256()
            and payload.get("engine_source_raw_file_sha256") == EXPECTED_ENGINE_RAW
            and raw_file_sha256(_paths(base)["engine"]) == EXPECTED_ENGINE_RAW
        )
        checks["spec_identity"] = bool(
            payload.get("spec_sha256") == spec["v41_spec_sha256"]
            and payload.get("spec_raw_file_sha256")
            == raw_file_sha256(_paths(base)["spec"])
        )
        checks["research_boundary_exact"] = bool(
            payload.get("research_classification") == "RESEARCH_ONLY"
            and payload.get("claim_boundary") == spec["claim_boundary"]
        )

        bridge = payload.get("bridge_audits")
        if not isinstance(bridge, Mapping):
            raise ValueError("V4.1 bridge_audits must be a mapping.")
        audit_rows = bridge.get("rows")
        if not isinstance(audit_rows, list) or not all(
            isinstance(row, Mapping) for row in audit_rows
        ):
            raise ValueError("V4.1 bridge audit rows must be a list of mappings.")

        expected_sources = [
            (2207, "08b4208484"),
            (7703, "a8180000ec"),
            (7703, "e2008a4082"),
        ]
        observed_sources = [
            (int(row.get("seed", -1)), str(row.get("source_mask_hex", "")))
            for row in audit_rows
        ]
        checks["bridge_source_order_exact"] = observed_sources == expected_sources
        expected_methods = [
            "PYTHON_EXACT_DELTA_CANONICAL_ORDER_V1",
            "PYTHON_EXACT_FULL_RECOMPUTE_REVERSED_ENUMERATION_V1",
            "INDEPENDENT_CPP_INT128_FULL_TWO_SWAP_AUDIT_V1",
        ]
        certificates = _certificate_by_seed(base)
        row_hashes_valid = True
        dual_replays_valid = True
        methods_valid = True
        for row in audit_rows:
            row_core = {
                key: copy.deepcopy(value)
                for key, value in row.items()
                if key != "isolate_audit_sha256"
            }
            row_hashes_valid = bool(
                row_hashes_valid
                and row.get("isolate_audit_sha256")
                == canonical_json_sha256(row_core)
            )
            methods_valid = bool(
                methods_valid
                and row.get("independent_methods") == expected_methods
                and row.get("triple_replay_match") is True
            )
            try:
                certificate = certificates[int(row["seed"])]
                delta = _audit_python_delta(
                    certificate, str(row["source_mask_hex"])
                )
                full = _audit_python_full(
                    certificate, str(row["source_mask_hex"])
                )
                stable_row = {
                    key: copy.deepcopy(value)
                    for key, value in row.items()
                    if key
                    not in {
                        "independent_methods",
                        "isolate_audit_sha256",
                        "triple_replay_match",
                    }
                }
                stable_delta = {
                    key: copy.deepcopy(value)
                    for key, value in delta.items()
                    if key != "algorithm"
                }
                stable_full = {
                    key: copy.deepcopy(value)
                    for key, value in full.items()
                    if key != "algorithm"
                }
                dual_replays_valid = bool(
                    dual_replays_valid
                    and stable_row == stable_delta == stable_full
                )
            except Exception as exc:
                dual_replays_valid = False
                errors.append(f"Bridge audit replay failed: {exc}")
        checks["bridge_row_hashes_exact"] = bool(
            len(audit_rows) == 3
            and row_hashes_valid
            and bridge.get("audit_bundle_sha256")
            == canonical_json_sha256(audit_rows)
            and sum(int(row.get("candidates_audited", 0)) for row in audit_rows)
            == 58_725
        )
        checks["bridge_dual_python_replay_exact"] = bool(
            len(audit_rows) == 3 and dual_replays_valid
        )
        checks["bridge_method_attestations_exact"] = bool(
            bridge.get("all_triple_replays_match") is True and methods_valid
        )

        parent = authenticate_parent_chain(root=base)
        expected_parent = {
            "authentication": parent,
            "v40_artifact_raw_file_sha256": EXPECTED_V40_ARTIFACT_RAW,
            "v40_artifact_sha256": EXPECTED_V40_ARTIFACT_SHA,
            "v40_freeze_raw_file_sha256": EXPECTED_V40_FREEZE_RAW,
            "v40_freeze_sha256": EXPECTED_V40_FREEZE_SHA,
            "v40_spec_sha256": EXPECTED_V40_SPEC_SHA,
        }
        checks["parent_chain_exact"] = bool(
            (not authenticate_parent or parent.get("valid") is True)
            and payload.get("parent") == expected_parent
        )
        if authenticate_parent and parent.get("valid") is not True:
            errors.extend(str(value) for value in parent.get("errors") or [])

        prerequisite_checks = bool(
            checks["bridge_source_order_exact"]
            and checks["bridge_row_hashes_exact"]
            and checks["bridge_dual_python_replay_exact"]
            and checks["bridge_method_attestations_exact"]
            and checks["parent_chain_exact"]
        )
        if prerequisite_checks:
            protocol = {
                "all_triple_replays_match": True,
                "audit_rows": copy.deepcopy(audit_rows),
                "spec_sha256": spec["v41_spec_sha256"],
            }
            expected_artifact = build_v41_artifact(
                protocol,
                root=base,
                use_cache=False,
            )
            checks["compression_evidence_exact_rebuild"] = (
                payload.get("compression_evidence")
                == expected_artifact["compression_evidence"]
            )
            checks["connectivity_evidence_exact_rebuild"] = (
                payload.get("connectivity_evidence")
                == expected_artifact["connectivity_evidence"]
            )
            checks["resource_evidence_exact_rebuild"] = (
                payload.get("resource_evidence")
                == expected_artifact["resource_evidence"]
            )
            checks["decisions_exact_rebuild"] = (
                payload.get("decisions") == expected_artifact["decisions"]
            )
            checks["v39_rejection_exact"] = (
                payload.get("v39_resource_rejection")
                == expected_artifact["v39_resource_rejection"]
            )
            checks["complete_artifact_exact_rebuild"] = (
                dict(payload) == expected_artifact
            )
    except Exception as exc:
        errors.append(f"V4.1 exact artifact reconstruction failed: {exc}")

    failed = [name for name, value in checks.items() if value is not True]
    return {
        "valid": not failed and not errors,
        "checks": checks,
        "failed_checks": failed,
        "errors": list(dict.fromkeys(errors)),
    }

def default_v41_artifact_path(*, root: str | Path | None = None) -> Path:
    return _root(root) / "outputs" / "quantum_phase3" / "v41_certified_bridge" / DEFAULT_ARTIFACT_NAME


def seal_v41_artifact(
    protocol: Mapping[str, Any],
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
    progress: Any | None = None,
) -> dict[str, Any]:
    target = Path(path) if path is not None else default_v41_artifact_path(root=root)
    payload = build_v41_artifact(protocol, root=root, progress=progress, use_cache=False)
    validation = validate_v41_artifact(payload, root=root, authenticate_parent=True)
    if validation.get("valid") is not True:
        raise ValueError(f"Refusing to seal invalid V4.1 artifact: {validation}")
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    if target.exists():
        if target.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"Refusing to overwrite non-identical V4.1 artifact: {target}")
        return {"created": False, "path": str(target), "artifact": payload, "validation": validation}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(encoded, encoding="utf-8")
    return {"created": True, "path": str(target), "artifact": payload, "validation": validation}


def load_v41_artifact(
    path: str | Path | None = None,
    *,
    root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(path) if path is not None else default_v41_artifact_path(root=root)
    payload = _read_json_strict(target)
    return payload, validate_v41_artifact(payload, root=root, authenticate_parent=True)


__all__ = [
    "ARTIFACT_VERSION",
    "BUDGET_CNOT",
    "DEFAULT_ARTIFACT_NAME",
    "K",
    "N",
    "SEEDS",
    "V41_VERSION",
    "authenticate_parent_chain",
    "build_augmented_connectivity_certificate",
    "build_resource_evidence",
    "build_seed_compression_certificate",
    "build_v41_artifact",
    "canonical_json_sha256",
    "compile_bridge_engine",
    "compile_bridge_rotation",
    "compile_seed_one_swap_layer",
    "default_v41_artifact_path",
    "load_v41_artifact",
    "load_v41_spec",
    "run_bridge_confirmatory_protocol",
    "seal_v41_artifact",
    "validate_v41_artifact",
]
