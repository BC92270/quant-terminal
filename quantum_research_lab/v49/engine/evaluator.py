"""Deterministic V4.9 offline pre-hardware admission evaluator."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .compiler import build_seed_admission_row


PARENT_FREEZE_RELATIVE_PATH = Path("FREEZE_CONTRACT_V4_8.json")
PARENT_ARTIFACT_RELATIVE_PATH = Path(
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
)
PROTOCOL_RELATIVE_PATH = Path("quantum_research_lab/v49/PROTOCOL.json")
CATALOG_RELATIVE_PATH = Path("quantum_research_lab/v49/snapshots/catalog.json")
NORMALIZED_RELATIVE_PATH = Path("quantum_research_lab/v49/snapshots/normalized.json")
ARTIFACT_RELATIVE_PATH = Path(
    "outputs/quantum_phase3/v49_pre_hardware_admission/"
    "SEALED_V4_9_ADMISSION_ARTIFACT.json"
)

EXPECTED_PARENT_FREEZE_RAW_SHA256 = "6d51bb5496bfdc412154ed84cf4e4a038b76d85b69ef3329f515db6cb969e5c8"
EXPECTED_PARENT_FREEZE_SHA256 = "6f6639f5f8ac3965f49b1107996718c6d8819637e6a65986013d5304cea6f2fa"
EXPECTED_PARENT_ARTIFACT_RAW_SHA256 = "f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76"
EXPECTED_PARENT_ARTIFACT_SHA256 = "6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f"
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)


def default_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_strict_pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def semantic_sha256(
    payload: Mapping[str, Any], *, exclude_top_level: Iterable[str] = ()
) -> str:
    excluded = set(exclude_top_level)
    body = {key: value for key, value in payload.items() if key not in excluded}
    return hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def raw_file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_file(root: Path, relative: Path) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Evidence must be a regular file: {relative}")
    return path


def authenticate_parent(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze_path = _regular_file(root, PARENT_FREEZE_RELATIVE_PATH)
    artifact_path = _regular_file(root, PARENT_ARTIFACT_RELATIVE_PATH)
    if raw_file_sha256(freeze_path) != EXPECTED_PARENT_FREEZE_RAW_SHA256:
        raise ValueError("V4.8 freeze raw identity mismatch")
    if raw_file_sha256(artifact_path) != EXPECTED_PARENT_ARTIFACT_RAW_SHA256:
        raise ValueError("V4.8 artifact raw identity mismatch")

    freeze = read_json_strict(freeze_path)
    artifact = read_json_strict(artifact_path)
    if freeze.get("freeze_contract_sha256") != EXPECTED_PARENT_FREEZE_SHA256:
        raise ValueError("V4.8 freeze embedded semantic identity mismatch")
    if semantic_sha256(
        freeze, exclude_top_level=("freeze_contract_sha256",)
    ) != EXPECTED_PARENT_FREEZE_SHA256:
        raise ValueError("V4.8 freeze semantic identity mismatch")
    if artifact.get("artifact_sha256") != EXPECTED_PARENT_ARTIFACT_SHA256:
        raise ValueError("V4.8 artifact embedded semantic identity mismatch")
    if semantic_sha256(
        artifact, exclude_top_level=("artifact_sha256",)
    ) != EXPECTED_PARENT_ARTIFACT_SHA256:
        raise ValueError("V4.8 artifact semantic identity mismatch")
    return freeze, artifact


def build_admission_artifact(root: str | Path | None = None) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    parent_freeze, parent_artifact = authenticate_parent(project_root)
    protocol_path = _regular_file(project_root, PROTOCOL_RELATIVE_PATH)
    catalog_path = _regular_file(project_root, CATALOG_RELATIVE_PATH)
    normalized_path = _regular_file(project_root, NORMALIZED_RELATIVE_PATH)
    protocol = read_json_strict(protocol_path)
    catalog = read_json_strict(catalog_path)
    normalized = read_json_strict(normalized_path)

    protocol_parent = protocol.get("parent_v48")
    if not isinstance(protocol_parent, Mapping):
        raise ValueError("V4.9 protocol parent contract is absent")
    expected_parent = {
        "freeze_raw_sha256": EXPECTED_PARENT_FREEZE_RAW_SHA256,
        "freeze_semantic_sha256": EXPECTED_PARENT_FREEZE_SHA256,
        "artifact_raw_sha256": EXPECTED_PARENT_ARTIFACT_RAW_SHA256,
        "artifact_semantic_sha256": EXPECTED_PARENT_ARTIFACT_SHA256,
    }
    if any(protocol_parent.get(key) != value for key, value in expected_parent.items()):
        raise ValueError("V4.9 protocol does not bind the exact V4.8 parent")

    seeds = parent_artifact.get("seed_evaluations")
    if not isinstance(seeds, list) or not all(isinstance(row, Mapping) for row in seeds):
        raise ValueError("V4.8 seed evaluations are unavailable")
    if tuple(int(row["seed"]) for row in seeds) != EXPECTED_SEEDS:
        raise ValueError("V4.8 seed order mismatch")

    architecture_gate = protocol.get("architecture_gate")
    if not isinstance(architecture_gate, Mapping):
        raise ValueError("V4.9 architecture gate is unavailable")
    observations = catalog.get("observed")
    if not isinstance(observations, list) or not all(
        isinstance(row, Mapping) for row in observations
    ):
        raise ValueError("V4.9 snapshot registry is malformed")

    seed_rows = [
        build_seed_admission_row(
            row,
            error_ceiling_exclusive=int(
                architecture_gate["direct_cx_error_ceiling_exclusive"]
            ),
            duration_ceiling_exclusive=int(
                architecture_gate["direct_cx_duration_ceiling_exclusive"]
            ),
            maximum_healthy_qubits=int(
                normalized["observations"][0]["num_qubits"]
            ),
        )
        for row in seeds
    ]
    cells = [
        {
            "snapshot_id": observation["snapshot_id"],
            "seed": row["seed"],
            "direct_cx": row["direct_cx"],
            "logical_qubits": row["logical_qubits"],
            "capacity_pass": row["capacity_pass"],
            "route_replay_pass": row["route_replay_pass"],
            "error_screen_pass": row["error_screen_pass"],
            "duration_screen_pass": row["duration_screen_pass"],
            "cell_admission_pass": row["seed_admission_pass"],
            "status": row["status"],
        }
        for observation in observations
        for row in seed_rows
    ]

    observed_epochs = int(catalog["observed_distinct_epochs"])
    required_epochs = int(catalog["minimum_distinct_epochs"])
    snapshot_gate_pass = observed_epochs >= required_epochs
    architecture_gate_pass = all(row["seed_admission_pass"] for row in seed_rows)
    if not snapshot_gate_pass:
        overall = "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS"
    elif not architecture_gate_pass:
        overall = "V49_TERMINAL_EXACT_ARCHITECTURE_NO_GO"
    else:
        overall = "V49_OFFLINE_PRE_HARDWARE_ADMISSION_PASSED_PROVIDER_DISCOVERY_ONLY"

    direct_values = [int(row["direct_cx"]) for row in seed_rows]
    artifact: dict[str, Any] = {
        "artifact_version": "PHASE III · V4.9 SEALED OFFLINE PRE-HARDWARE ADMISSION ARTIFACT · V1",
        "v49_version": "4.9.0",
        "chronology": {
            "protocol_sealed_before_evaluation": True,
            "known_v48_development_snapshot_not_relabelled_as_holdout": True,
            "negative_and_not_evaluable_results_admissible": True,
        },
        "parent": {
            "authenticated": True,
            "v48_freeze_raw_sha256": raw_file_sha256(project_root / PARENT_FREEZE_RELATIVE_PATH),
            "v48_freeze_sha256": parent_freeze["freeze_contract_sha256"],
            "v48_artifact_raw_sha256": raw_file_sha256(project_root / PARENT_ARTIFACT_RELATIVE_PATH),
            "v48_artifact_sha256": parent_artifact["artifact_sha256"],
        },
        "evidence_identities": {
            "protocol_raw_sha256": raw_file_sha256(protocol_path),
            "protocol_semantic_sha256": semantic_sha256(protocol),
            "catalog_raw_sha256": raw_file_sha256(catalog_path),
            "catalog_semantic_sha256": semantic_sha256(catalog),
            "normalized_cohort_raw_sha256": raw_file_sha256(normalized_path),
            "normalized_cohort_semantic_sha256": semantic_sha256(normalized),
        },
        "snapshot_gate": {
            "required_distinct_authentic_epochs": required_epochs,
            "observed_distinct_authentic_epochs": observed_epochs,
            "missing_distinct_authentic_epochs": max(0, required_epochs - observed_epochs),
            "observed_snapshot_ids": [row["snapshot_id"] for row in observations],
            "registry_complete": bool(catalog.get("registry_complete")),
            "synthetic_substitution_allowed": False,
            "pass": snapshot_gate_pass,
            "status": "PASS" if snapshot_gate_pass else "NOT_EVALUABLE",
        },
        "architecture_gate": {
            "reference_architecture_id": parent_artifact["candidate_contract"]["architecture_id"],
            "candidate_is_v48_frozen_reference_not_new_v49_claim": True,
            "strict_error_ceiling_exclusive": int(architecture_gate["direct_cx_error_ceiling_exclusive"]),
            "strict_duration_ceiling_exclusive": int(architecture_gate["direct_cx_duration_ceiling_exclusive"]),
            "required_maximum_direct_cx": int(architecture_gate["required_maximum_direct_cx"]),
            "observed_minimum_direct_cx": min(direct_values),
            "observed_maximum_direct_cx": max(direct_values),
            "minimum_additional_cx_reduction_required": min(direct_values) - int(architecture_gate["required_maximum_direct_cx"]),
            "maximum_additional_cx_reduction_required": max(direct_values) - int(architecture_gate["required_maximum_direct_cx"]),
            "all_seeds_capacity_pass": all(row["capacity_pass"] for row in seed_rows),
            "all_seeds_route_replay_pass": all(row["route_replay_pass"] for row in seed_rows),
            "all_seeds_error_screen_pass": all(row["error_screen_pass"] for row in seed_rows),
            "all_seeds_duration_screen_pass": all(row["duration_screen_pass"] for row in seed_rows),
            "pass": architecture_gate_pass,
            "status": "PASS" if architecture_gate_pass else "FAIL",
        },
        "seed_admission": seed_rows,
        "snapshot_seed_matrix": cells,
        "decisions": {
            "snapshot_gate": "PASS" if snapshot_gate_pass else "V49_NOT_EVALUABLE_INSUFFICIENT_AUTHENTIC_EPOCHS",
            "architecture_gate": "PASS" if architecture_gate_pass else "V49_REFERENCE_ARCHITECTURE_FAILS_STRICT_NECESSARY_SCREENS_ALL_EIGHT",
            "overall": overall,
            "provider_discovery": "AUTHORIZED_BY_V49_PROTOCOL_ONLY" if overall.endswith("PROVIDER_DISCOVERY_ONLY") else "DENIED",
            "v5_hardware_protocol_entry": "OPEN" if overall.endswith("PROVIDER_DISCOVERY_ONLY") else "CLOSED",
            "next_permissible_test": "ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_EPOCHS_AND_PRODUCE_AN_EXACT_ARCHITECTURE_WITH_MAX_DIRECT_CX_AT_MOST_963",
        },
        "claim_boundary": copy.deepcopy(protocol["execution_boundary"]),
    }
    artifact["claim_boundary"]["snapshot_is_current_hardware_evidence"] = False
    artifact["claim_boundary"]["hardware_readiness"] = "NOT_DEMONSTRATED"
    artifact["artifact_sha256"] = semantic_sha256(artifact)
    return artifact


def evaluate_and_write(
    root: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    project_root = Path(root).resolve() if root is not None else default_root()
    artifact = build_admission_artifact(project_root)
    target = Path(output) if output is not None else project_root / ARTIFACT_RELATIVE_PATH
    if not target.is_absolute():
        target = project_root / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=default_root())
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = evaluate_and_write(args.root, args.output)
    print(json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
