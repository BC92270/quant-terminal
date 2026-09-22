"""Scientific validation and sealed replay evidence for Quantum Lab V4.8."""

from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v48_independent_checker import (
    EXPECTED_CHECK_COUNT as EXPECTED_INDEPENDENT_CHECK_COUNT,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
    validate_v48_artifact,
)
from .phase3_v48_reference_builder import validate_reference_bundle


EXPECTED_CHECK_COUNT = 96
ARTIFACT_PATH = (
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
)
VALIDATION_REPORT_PATH = (
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_VALIDATION_REPORT.json"
)
SOURCE_PATH = "quantum_research_lab/phase3_v48_multi_snapshot_architecture_optimizer.py"
CHECKER_PATH = "quantum_research_lab/phase3_v48_independent_checker.py"
SPEC_PATH = "quantum_research_lab/PHASE_III_V4_8_MULTI_SNAPSHOT_CZ_REDUCTION_SPEC_V1.json"
CATALOG_PATH = "quantum_research_lab/PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json"
SNAPSHOTS_PATH = "quantum_research_lab/PHASE_III_V4_8_NORMALIZED_SNAPSHOTS_ORACLE_V1.json"
MODEL_PATH = "quantum_research_lab/PHASE_III_V4_8_ROBUSTNESS_COST_MODEL_V1.json"
ORACLE_PATH = "quantum_research_lab/PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json"


def _root(root: str | Path | None = None) -> Path:
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return payload.get(field) == canonical_json_sha256(
        {key: value for key, value in payload.items() if key != field}
    )


def run_v48_validation(
    *,
    root: str | Path | None = None,
    expected_artifact_raw_sha256: str | None = None,
    expected_artifact_sha256: str | None = None,
) -> dict[str, Any]:
    base = _root(root)
    artifact_path = base / ARTIFACT_PATH
    errors: list[str] = []
    try:
        artifact = read_json_strict(artifact_path)
        artifact_raw = raw_file_sha256(artifact_path)
        independent = validate_v48_artifact(
            artifact,
            root=base,
            artifact_raw_file_sha256=artifact_raw,
            expected_artifact_raw_sha256=expected_artifact_raw_sha256,
            expected_artifact_sha256=expected_artifact_sha256,
        )
        references = validate_reference_bundle(base)
    except Exception as exc:
        return {
            "counts": {"checks_passed": 0, "checks_total": EXPECTED_CHECK_COUNT},
            "errors": [str(exc)],
            "failed_checks": ["strict_load"],
            "passed": False,
            "validation_version": "QUANTUM LAB V4.8 SCIENTIFIC VALIDATION · V1",
        }

    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    aggregate = artifact.get("aggregate") or {}
    references_map = artifact.get("reference_contracts") or {}
    parent = artifact.get("parent") or {}
    checks: dict[str, bool] = {
        "artifact_regular_file": artifact_path.is_file() and not artifact_path.is_symlink(),
        "artifact_raw_expected": expected_artifact_raw_sha256 in (None, artifact_raw),
        "artifact_semantic_expected": expected_artifact_sha256 in (None, artifact.get("artifact_sha256")),
        "artifact_self_hash": _self_hash(artifact, "artifact_sha256"),
        "independent_checker_valid": independent.get("valid") is True,
        "independent_checker_count": independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT == 65,
        "independent_checker_clean": not independent.get("errors") and not independent.get("failed_checks"),
        "reference_bundle_valid": references.get("passed") is True,
        "reference_bundle_count": (references.get("counts") or {}).get("checks_total") == 11,
        "optimizer_source_identity": artifact.get("source_raw_file_sha256") == raw_file_sha256(base / SOURCE_PATH),
        "independent_checker_crosslink": artifact.get("independent_checker_raw_file_sha256") == raw_file_sha256(base / CHECKER_PATH),
        "spec_raw_crosslink": references_map.get("multi_snapshot_spec_raw_file_sha256") == raw_file_sha256(base / SPEC_PATH),
        "catalog_raw_crosslink": references_map.get("snapshot_catalog_raw_file_sha256") == raw_file_sha256(base / CATALOG_PATH),
        "snapshots_raw_crosslink": references_map.get("normalized_snapshots_oracle_raw_file_sha256") == raw_file_sha256(base / SNAPSHOTS_PATH),
        "model_raw_crosslink": references_map.get("robustness_cost_model_raw_file_sha256") == raw_file_sha256(base / MODEL_PATH),
        "oracle_raw_crosslink": references_map.get("architecture_candidate_oracle_raw_file_sha256") == raw_file_sha256(base / ORACLE_PATH),
        "parent_v45_raw": parent.get("v45_artifact_raw_file_sha256") == "f28f2975b83d38e32b285cac8c2b7506a07f6341739f3153bde01d42e1219257",
        "parent_v46_raw": parent.get("v46_artifact_raw_file_sha256") == "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694",
        "parent_v47_raw": parent.get("v47_artifact_raw_file_sha256") == "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185",
        "parent_freeze_raw": parent.get("v47_freeze_raw_file_sha256") == "89dfc8f614955d4fe1c92cfd286ab04f4022d9eb69e566edf46a65e84aa81a3a",
        "research_only": artifact.get("research_classification") == boundary.get("research_classification") == "RESEARCH_ONLY",
        "hardware_false": boundary.get("hardware_executable") is False,
        "zero_calls_jobs": all(boundary.get(key) == 0 for key in ("provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted")),
        "zero_credentials": boundary.get("credential_reads") == 0 and boundary.get("provider_credentials_read") is False and boundary.get("provider_sdk_imported") is False,
        "not_current_hardware": boundary.get("snapshot_is_current_hardware_evidence") is False,
        "no_advantage": boundary.get("quantum_advantage") == "NOT_CLAIMED",
        "overall_exact": decisions.get("overall") == "V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED",
        "architecture_pass": decisions.get("architecture_candidate") == "PASS_EXACT_CONTROL_LOADED_CUCCARO_REDUCTION_ALL_EIGHT",
        "routing_pass": decisions.get("structural_routing") == "PASS_STRICT_BASICSWAP_CZ_REDUCTION_ALL_EIGHT",
        "multi_snapshot_blocked": decisions.get("multi_snapshot_robustness") == "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES",
        "production_rejected": decisions.get("production_admission") == "RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED",
        "aggregate_self_hash": _self_hash(aggregate, "aggregate_sha256"),
    }
    rows = artifact.get("seed_evaluations") or []
    for expected_seed, row in zip((1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807), rows):
        prefix = f"seed_{expected_seed}"
        manifest = row.get("candidate_stream_manifest") or {}
        routing = row.get("structural_routing") or {}
        routed = routing.get("routed_compilation") or {}
        native = routed.get("native_ledger") or {}
        comparison = row.get("comparison") or {}
        lower = row.get("architecture_lower_bound_v47_comparable") or {}
        adder = routing.get("adder_evidence") or {}
        checks.update(
            {
                f"{prefix}_commitments": int(row.get("seed", -1)) == expected_seed and _self_hash(row, "seed_evaluation_sha256") and _self_hash(comparison, "comparison_sha256"),
                f"{prefix}_manifest": row.get("candidate_stream_materialized") is True and _self_hash(manifest, "stream_manifest_sha256") and int(manifest.get("instruction_count", -1)) == sum(int(value) for value in (manifest.get("elementary_counts") or {}).values()),
                f"{prefix}_adder": _self_hash(adder, "adder_evidence_sha256") and int(adder.get("adder_cx_reduction", 0)) > 0 and int(adder.get("adder_invocation_count", 0)) > 0,
                f"{prefix}_routing": routed.get("input_manifest_exact_parent") is True and routed.get("input_stream_manifest") == manifest and native.get("coupling_violations") == native.get("isa_violations") == 0,
                f"{prefix}_cx_reduction": comparison.get("strict_logical_cx_reduction") is True and int(comparison.get("candidate_cx", -1)) < int(comparison.get("parent_v45_cx", -1)),
                f"{prefix}_cz_reduction": comparison.get("strict_routed_cz_reduction") is True and int(comparison.get("candidate_basic_swap_cz", -1)) < int(comparison.get("parent_v46_basic_swap_cz", -1)),
                f"{prefix}_error_screen_retained": lower.get("passes_reported_error_mass_screen") is False and Decimal(str(lower.get("optimistic_reported_error_mass_lower_bound"))) >= Decimal(1),
                f"{prefix}_duration_screen_retained": lower.get("passes_duration_screen") is False and float(lower.get("optimistic_cz_duration_over_maximum_snapshot_t2", 0)) > 1,
            }
        )
    if len(rows) != 8:
        errors.append(f"Expected eight seed evaluations, observed {len(rows)}")
    if len(checks) != EXPECTED_CHECK_COUNT:
        errors.append(f"Validation contract count drift: {len(checks)} != {EXPECTED_CHECK_COUNT}")
    failed = [name for name, passed in checks.items() if not passed]
    core = {
        "artifact_raw_file_sha256": artifact_raw,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "counts": {
            "checks_passed": len(checks) - len(failed),
            "checks_total": len(checks),
            "independent_checker_check_count": independent.get("check_count"),
        },
        "errors": errors,
        "failed_checks": failed,
        "independent_checker": independent,
        "passed": not errors and not failed,
        "reference_bundle_validation": references,
        "validation_version": "QUANTUM LAB V4.8 SCIENTIFIC VALIDATION · V1",
    }
    return {**core, "validation_evidence_sha256": canonical_json_sha256(core)}


def seal_validation_report(
    *,
    root: str | Path | None = None,
    replay_artifact: str | Path,
    output: str | Path | None = None,
) -> dict[str, Any]:
    base = _root(root)
    artifact_path = base / ARTIFACT_PATH
    artifact = read_json_strict(artifact_path)
    raw_sha = raw_file_sha256(artifact_path)
    validation = run_v48_validation(
        root=base,
        expected_artifact_raw_sha256=raw_sha,
        expected_artifact_sha256=artifact["artifact_sha256"],
    )
    if validation.get("passed") is not True:
        raise RuntimeError(f"Cannot seal failed V4.8 validation: {validation}")
    replay_path = Path(replay_artifact)
    if not replay_path.is_absolute():
        replay_path = base / replay_path
    replay = read_json_strict(replay_path)
    replay_raw = raw_file_sha256(replay_path)
    replay_core = {key: value for key, value in replay.items() if key != "artifact_sha256"}
    replay_evidence = {
        "artifact_raw_file_sha256": replay_raw,
        "artifact_sha256": replay.get("artifact_sha256"),
        "byte_for_byte_equal_to_sealed_artifact": replay_path.read_bytes() == artifact_path.read_bytes(),
        "performed": True,
        "semantic_self_hash_valid": replay.get("artifact_sha256") == canonical_json_sha256(replay_core),
    }
    scientific = {
        "checks": validation["checks"],
        "checks_passed": validation["counts"]["checks_passed"],
        "checks_total": validation["counts"]["checks_total"],
        "errors": validation["errors"],
        "failed_checks": validation["failed_checks"],
        "independent_checker_check_count": EXPECTED_INDEPENDENT_CHECK_COUNT,
        "passed": validation["passed"],
        "validation_evidence_sha256": validation["validation_evidence_sha256"],
    }
    boundary = artifact["claim_boundary"]
    core = {
        "artifact_raw_file_sha256": raw_sha,
        "artifact_sha256": artifact["artifact_sha256"],
        "claim_boundary": boundary,
        "clean_process_replay": replay_evidence,
        "scientific_validation": scientific,
        "validation_evidence_version": "QUANTUM LAB V4.8 VALIDATION EVIDENCE · V1",
    }
    report = {**core, "sealed_validation_evidence_sha256": canonical_json_sha256(core)}
    target = Path(output) if output is not None else base / VALIDATION_REPORT_PATH
    if not target.is_absolute():
        target = base / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=None)
    parser.add_argument("--artifact-raw-sha256", default=None)
    parser.add_argument("--artifact-sha256", default=None)
    parser.add_argument("--seal-report", action="store_true")
    parser.add_argument("--replay-artifact", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    if args.seal_report:
        if not args.replay_artifact:
            parser.error("--seal-report requires --replay-artifact")
        result = seal_validation_report(
            root=args.root,
            replay_artifact=args.replay_artifact,
            output=args.output,
        )
    else:
        result = run_v48_validation(
            root=args.root,
            expected_artifact_raw_sha256=args.artifact_raw_sha256,
            expected_artifact_sha256=args.artifact_sha256,
        )
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if result.get("passed", result.get("scientific_validation", {}).get("passed")) else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "ARTIFACT_PATH",
    "EXPECTED_CHECK_COUNT",
    "VALIDATION_REPORT_PATH",
    "canonical_json_sha256",
    "read_json_strict",
    "run_v48_validation",
    "seal_validation_report",
]
