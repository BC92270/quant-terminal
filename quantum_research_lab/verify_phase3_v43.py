"""Fail-closed release-chain verifier for Quantum Lab V4.3.

Identity-only mode authenticates the frozen validation commitment and never
executes the scientific engines.  Deep mode runs the independent 31-check
validation, including the C++17 replay, but deliberately does not rebuild the
21.9 million-instruction circuit streams.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence

from .phase3_v43_reversible_circuit_ir import (
    canonical_json_sha256,
    load_v43_spec,
    raw_file_sha256,
)
from .phase3_v43_validation import run_v43_validation


FREEZE_PATH = "FREEZE_CONTRACT_V4_3.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_2.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V43_PATHS = (
    "DEPLOY_V4_3.md",
    "app_v43_offline_harness.py",
    "install_quantum_lab_v43.py",
    "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_3_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v43_reversible_circuit_ir.py",
    "quantum_research_lab/phase3_v43_reversible_simulator.cpp",
    "quantum_research_lab/phase3_v43_ui.py",
    "quantum_research_lab/phase3_v43_validation.py",
    "quantum_research_lab/test_phase3_v43.py",
    "quantum_research_lab/test_phase3_v43_release.py",
    "quantum_research_lab/verify_freeze_contract_v43.py",
    "quantum_research_lab/verify_phase3_v43.py",
    "quantum_research_lab/verify_phase3_v43_ui.py",
    README_PATH,
    UI_PATH,
)

EXPECTED_FROZEN_FILE_COUNT = 193
EXPECTED_V43_PATH_FINGERPRINT = "3bc4c8805cf38d5e55c8cc4d1c99cfc3950f9b7faa2cb85fa891fb42987467fc"
EXPECTED_V42_FREEZE_RAW = "faf9250d6f76acdeb2644d52a45c7ae1d8930b3f4c7367ca6ba3861e063371c5"
EXPECTED_V42_FREEZE_SHA = "36ebd4acedb1563227324b56ab6731293d38935c2c888f37c33029858a0f3068"
EXPECTED_V42_PATH_FINGERPRINT = "cc3dd736d2475cfc1d143bc720fc37863d62ede26019a3aa99cd33e96643b166"
EXPECTED_V43_SPEC_RAW = "ad8904557e850b8850e11ccc410fa3bb44cc15947cf06d7bdee7047f24563226"
EXPECTED_V43_SPEC_SHA = "71f6d1f642a6d6a1e99d9d265e6cba914302ea9763a854a13cf4aa0b95d8cf5f"
EXPECTED_V43_SOURCE_RAW = "d4dc129721dd7a4429aa473658272fef26f5c90831ecb3d125a730246309838d"
EXPECTED_V43_SIMULATOR_RAW = "420761883ce82825c9a1d01ec55cf116d69f4a80f946dc6c5a8e6c002e61f7e7"
EXPECTED_V43_VALIDATION_RAW = "071d6b8a552d630820bb654a8257ce7669f1aa39a61e3267741dfefb59d52938"
EXPECTED_V43_ARTIFACT_RAW = "626123fda2ee6561fe74cbb073a03f9987ccbd4e3d01c84b4f2815023e8271e3"
EXPECTED_V43_ARTIFACT_SHA = "36a7a63410da87ce7f98bb10e6d3af3c3d784d9f8e520a6771e42cda9ee593ce"
EXPECTED_VALIDATION_EVIDENCE_SHA = "90effe2631c36be1461475f7964cd3c32b163f9b88851b664de077841cc502a9"
EXPECTED_SCIENTIFIC_CHECK_COUNT = 31
EXPECTED_RELEASE_CHECK_COUNT = 32
EXPECTED_FREEZE_CHECK_COUNT = 18
EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT = 18
# Seal-time patch point: keep synchronized with verify_phase3_v43_ui.py.
EXPECTED_UI_CHECK_COUNT = 20


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_nonfinite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _contained_regular(root: Path, relative: str) -> Path:
    item = Path(relative)
    if not relative or item.is_absolute() or any(part in {"", ".", ".."} for part in item.parts):
        raise ValueError(f"Unsafe release path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in item.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked release path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Release path is not a regular file: {relative}")
    cursor.resolve(strict=True).relative_to(release_root)
    return cursor


def _semantic(payload: Mapping[str, Any], *excluded: str) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key not in set(excluded)})


def _fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")).hexdigest()


def _provider_free_imports(path: Path) -> bool:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name.split(".")[0] in forbidden for name in names):
            return False
    return True


def _identity_validation(freeze: Mapping[str, Any]) -> dict[str, Any]:
    identities = freeze.get("v43_identities") or {}
    exact = identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA
    checks = {"frozen_validation_evidence_identity": exact}
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "checks": checks,
        "counts": {
            "checks_passed": EXPECTED_SCIENTIFIC_CHECK_COUNT if exact else 0,
            "checks_total": EXPECTED_SCIENTIFIC_CHECK_COUNT,
        },
        "deep_stream_rebuild": False,
        "errors": [] if exact else ["Frozen V4.3 scientific-validation identity mismatch."],
        "failed_checks": failed,
        "passed": exact,
        "validation_evidence_sha256": identities.get("validation_evidence_sha256"),
        "validation_version": "IDENTITY_ONLY · SCIENTIFIC ENGINES NOT RUN IN THIS INVOCATION",
    }


def verify_release_chain(root: str | Path, *, deep: bool = True) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.3 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.3 frozen_files must be an object.")

    frozen_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen.items()):
        try:
            actual = raw_file_sha256(_contained_regular(release_root, str(relative)))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        frozen_rows.append({"actual": actual, "expected": expected, "path": relative, "valid": valid})
        if not valid:
            errors.append(f"Frozen file mismatch: {relative}")

    try:
        parent_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent = _read_json_strict(parent_path)
        parent_raw = raw_file_sha256(parent_path)
        parent_semantic = _semantic(parent, "freeze_contract_sha256")
    except Exception as exc:
        parent = {}
        parent_raw = parent_semantic = None
        errors.append(f"V4.2 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent_paths = (
        sorted(set(parent_files) - {README_PATH, UI_PATH}) if isinstance(parent_files, dict) else []
    )
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 175
        and all(frozen.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    spec_relative = "quantum_research_lab/PHASE_III_V4_3_REVERSIBLE_CIRCUIT_MATERIALIZATION_SPEC_V1.json"
    source_relative = "quantum_research_lab/phase3_v43_reversible_circuit_ir.py"
    simulator_relative = "quantum_research_lab/phase3_v43_reversible_simulator.cpp"
    validation_relative = "quantum_research_lab/phase3_v43_validation.py"
    artifact_relative = "outputs/quantum_phase3/v43_reversible_circuit/SEALED_V4_3_REVERSIBLE_CIRCUIT_ARTIFACT.json"

    def guarded(relative: str) -> Path:
        try:
            return _contained_regular(release_root, relative)
        except Exception as exc:
            errors.append(f"V4.3 release path unavailable ({relative}): {exc}")
            return release_root / relative

    spec_path = guarded(spec_relative)
    source_path = guarded(source_relative)
    simulator_path = guarded(simulator_relative)
    validation_path = guarded(validation_relative)
    artifact_path = guarded(artifact_relative)
    try:
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v43_spec(spec_path, root=release_root)
    except Exception as exc:
        spec_payload = spec_loaded = {}
        errors.append(f"V4.3 specification unavailable: {exc}")
    try:
        artifact = _read_json_strict(artifact_path)
    except Exception as exc:
        artifact = {}
        errors.append(f"V4.3 artifact unavailable: {exc}")

    if deep:
        try:
            validation = run_v43_validation(root=release_root, rebuild_streams=False)
        except Exception as exc:
            validation = {
                "counts": {}, "deep_stream_rebuild": False, "errors": [str(exc)],
                "failed_checks": ["exception"], "passed": False,
            }
            errors.append(f"Deep V4.3 scientific validation failed: {exc}")
    else:
        validation = _identity_validation(freeze)

    aggregate = artifact.get("aggregate") or {}
    boundary = artifact.get("claim_boundary") or {}
    decisions = artifact.get("decisions") or {}
    simulator = artifact.get("independent_cpp_simulator") or {}
    negative = artifact.get("mandatory_off_promise_control") or {}
    rows = artifact.get("seed_materializations") or []
    identities = freeze.get("v43_identities") or {}
    lineage = freeze.get("lineage") or {}
    deployment = freeze.get("deployment_contract") or {}
    targets = freeze.get("validation_targets") or {}

    stream_integrity = bool(
        len(rows) == 8
        and all(
            (row.get("stream_manifest") or {}).get("stream_manifest_sha256")
            == _semantic(row.get("stream_manifest") or {}, "stream_manifest_sha256")
            and row.get("seed_materialization_sha256")
            == _semantic(row, "seed_materialization_sha256")
            for row in rows
        )
    )
    checks: dict[str, bool] = {
        "freeze_contract_version_exact": freeze.get("freeze_contract_version") == "QUANTUM LAB V4.3 FREEZE CONTRACT · V1",
        "freeze_self_hash_exact": freeze.get("freeze_contract_sha256") == _semantic(freeze, "freeze_contract_sha256"),
        "frozen_file_count_193": freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT == len(frozen),
        "frozen_path_fingerprint_exact": _fingerprint(frozen) == freeze.get("frozen_paths_fingerprint_sha256") == EXPECTED_V43_PATH_FINGERPRINT,
        "all_frozen_files_regular_contained_exact": len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in frozen_rows),
        "all_v43_release_paths_frozen": set(V43_PATHS).issubset(frozen),
        "v42_freeze_raw_identity": parent_raw == EXPECTED_V42_FREEZE_RAW,
        "v42_freeze_semantic_identity": parent_semantic == parent.get("freeze_contract_sha256") == EXPECTED_V42_FREEZE_SHA,
        "v42_freeze_inventory_identity": bool(isinstance(parent_files, dict) and len(parent_files) == 177 and _fingerprint(parent_files) == EXPECTED_V42_PATH_FINGERPRINT),
        "all_175_v42_immutable_paths_preserved": immutable_parent_exact,
        "v43_spec_raw_identity": spec_path.is_file() and raw_file_sha256(spec_path) == EXPECTED_V43_SPEC_RAW,
        "v43_spec_semantic_identity": _semantic(spec_payload, "v43_spec_sha", "v43_spec_sha256") == spec_loaded.get("v43_spec_sha256") == EXPECTED_V43_SPEC_SHA,
        "v43_source_raw_identity": source_path.is_file() and raw_file_sha256(source_path) == EXPECTED_V43_SOURCE_RAW,
        "v43_simulator_raw_identity": simulator_path.is_file() and raw_file_sha256(simulator_path) == EXPECTED_V43_SIMULATOR_RAW,
        "v43_validation_source_raw_identity": validation_path.is_file() and raw_file_sha256(validation_path) == EXPECTED_V43_VALIDATION_RAW,
        "v43_artifact_raw_identity": artifact_path.is_file() and raw_file_sha256(artifact_path) == EXPECTED_V43_ARTIFACT_RAW,
        "v43_artifact_semantic_identity": _semantic(artifact, "artifact_sha256") == artifact.get("artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA,
        "artifact_source_spec_simulator_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_V43_SOURCE_RAW and artifact.get("simulator_source_raw_file_sha256") == EXPECTED_V43_SIMULATOR_RAW and artifact.get("spec_sha256") == EXPECTED_V43_SPEC_SHA and artifact.get("spec_raw_file_sha256") == EXPECTED_V43_SPEC_RAW),
        "artifact_v42_parent_crosslinks": bool((artifact.get("parent") or {}).get("freeze_raw_file_sha256") == EXPECTED_V42_FREEZE_RAW and (artifact.get("parent") or {}).get("freeze_sha256") == EXPECTED_V42_FREEZE_SHA and (artifact.get("parent") or {}).get("immutable_file_count") == 175 and (artifact.get("parent") or {}).get("immutable_files_exact") is True),
        "independent_cpp_control_exact": bool(simulator.get("valid") is True and simulator.get("status") == "PASS" and (simulator.get("pass_counts") or {}).get("arithmetic_cases") == 107_520 and (simulator.get("pass_counts") or {}).get("promise_select_cases") == 64 and (simulator.get("pass_counts") or {}).get("promise_select_roundtrips") == 64),
        "eight_stream_manifests_and_self_hashes_exact": stream_integrity,
        "materialized_resource_gate_exact": bool(aggregate.get("seed_count") == 8 and aggregate.get("all_eight_seeds_budget_admitted") is True and aggregate.get("maximum_materialized_cnot") == 1_158_046 and aggregate.get("minimum_budget_margin_cnot") == 1_341_954 and aggregate.get("maximum_logical_qubits_with_recycled_workspace") == 339 and aggregate.get("total_elementary_instructions") == 21_925_902),
        "promise_and_off_promise_boundaries_exact": bool(all((row.get("real_n40_promise_select_witness") or {}).get("retained_feasible_flag_after_reverse") == 0 for row in rows) and negative.get("status") == "OFF_PROMISE_CLEANUP_REJECTED_WITH_WITNESS" and negative.get("retained_feasible_flag_after_reverse") == 1 and (simulator.get("negative_control") or {}).get("retained_feasibility_flag") == 1),
        "bounded_decisions_exact": bool(decisions.get("overall") == "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED" and decisions.get("production_admission") == "PROVIDER_NEUTRAL_RESEARCH_CIRCUIT_IR_ADMITTED_BACKEND_AND_HARDWARE_NOT_AUTHORIZED" and decisions.get("next_falsifiable_gate") == "NAMED_BACKEND_ZERO_JOB_TRANSPILATION_AND_ROUTING_PROTOCOL"),
        "provider_backend_hardware_advantage_boundary_exact": bool(artifact.get("research_classification") == "RESEARCH_ONLY" and boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("hardware_executable") is False and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "compiler_validation_ui_and_installer_provider_free": all(_provider_free_imports(guarded(path)) for path in (source_relative, validation_relative, "quantum_research_lab/phase3_v43_ui.py", "install_quantum_lab_v43.py")),
        "scientific_validation_commitment_exact": identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA,
        "scientific_validation_passed_or_identity_verified": validation.get("passed") is True and validation.get("deep_stream_rebuild") is False,
        "scientific_validation_has_31_checks": (validation.get("counts") or {}).get("checks_total") == EXPECTED_SCIENTIFIC_CHECK_COUNT,
        "readme_declares_bounded_v43_decision": "V43_BACKEND_AGNOSTIC_CIRCUIT_MATERIALIZED_PROMISE_SIMULATION_PASSED" in guarded(README_PATH).read_text(encoding="utf-8"),
        "deployment_contract_is_transactional_idempotent": bool(deployment.get("overlay_file_count") == 18 and deployment.get("candidate_stage_validation") == "REQUIRED" and deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH),
        "route_targets_and_identity_block_exact": bool(deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12 and targets.get("scientific_validation_checks") == EXPECTED_SCIENTIFIC_CHECK_COUNT and targets.get("scientific_unit_tests") == EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT and targets.get("release_chain_checks") == EXPECTED_RELEASE_CHECK_COUNT and targets.get("freeze_contract_checks") == EXPECTED_FREEZE_CHECK_COUNT and targets.get("streamlit_ui_checks") == EXPECTED_UI_CHECK_COUNT and targets.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and lineage.get("v42_freeze_raw_file_sha256") == EXPECTED_V42_FREEZE_RAW and lineage.get("v42_freeze_sha256") == EXPECTED_V42_FREEZE_SHA and lineage.get("v42_frozen_file_count") == 177 and lineage.get("v42_immutable_file_count") == 175 and identities.get("v43_spec_raw_file_sha256") == EXPECTED_V43_SPEC_RAW and identities.get("v43_spec_sha256") == EXPECTED_V43_SPEC_SHA and identities.get("v43_source_raw_file_sha256") == EXPECTED_V43_SOURCE_RAW and identities.get("v43_simulator_raw_file_sha256") == EXPECTED_V43_SIMULATOR_RAW and identities.get("validation_source_raw_file_sha256") == EXPECTED_V43_VALIDATION_RAW and identities.get("v43_artifact_raw_file_sha256") == EXPECTED_V43_ARTIFACT_RAW and identities.get("v43_artifact_sha256") == EXPECTED_V43_ARTIFACT_SHA),
    }
    if len(checks) != EXPECTED_RELEASE_CHECK_COUNT:
        raise AssertionError(f"V4.3 release verifier check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    merged_errors = list(dict.fromkeys(errors + list(validation.get("errors") or [])))
    return {
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_replay": bool(deep),
        "deep_stream_rebuild": False,
        "errors": merged_errors,
        "failed_checks": failed,
        "freeze_contract_sha256": freeze.get("freeze_contract_sha256"),
        "frozen_file_count": len(frozen_rows),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "verifier": "QUANTUM LAB V4.3 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root_positional", nargs="?", type=Path, help="Release root (default: current directory).")
    parser.add_argument("--root", dest="root_option", type=Path, help="Release root (explicit option form).")
    parser.add_argument("--identity-only", action="store_true", help="Authenticate frozen evidence without running scientific engines.")
    args = parser.parse_args(argv)
    if args.root_positional is not None and args.root_option is not None:
        parser.error("Pass the release root either positionally or with --root, not both.")
    root = args.root_option or args.root_positional or Path(".")
    try:
        report = verify_release_chain(root, deep=not args.identity_only)
    except Exception as exc:
        report = {
            "check_count": EXPECTED_RELEASE_CHECK_COUNT,
            "checks": {},
            "deep_scientific_replay": not args.identity_only,
            "deep_stream_rebuild": False,
            "errors": [str(exc)],
            "failed_checks": ["unhandled_exception"],
            "root": str(root),
            "valid": False,
            "verifier": "QUANTUM LAB V4.3 RELEASE CHAIN · V1",
        }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FREEZE_CHECK_COUNT",
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_RELEASE_CHECK_COUNT",
    "EXPECTED_SCIENTIFIC_CHECK_COUNT",
    "EXPECTED_SCIENTIFIC_UNIT_TEST_COUNT",
    "EXPECTED_UI_CHECK_COUNT",
    "EXPECTED_V42_FREEZE_RAW",
    "EXPECTED_V42_FREEZE_SHA",
    "EXPECTED_V43_ARTIFACT_RAW",
    "EXPECTED_V43_ARTIFACT_SHA",
    "EXPECTED_V43_PATH_FINGERPRINT",
    "EXPECTED_V43_SIMULATOR_RAW",
    "EXPECTED_V43_SOURCE_RAW",
    "EXPECTED_V43_SPEC_RAW",
    "EXPECTED_V43_SPEC_SHA",
    "EXPECTED_V43_VALIDATION_RAW",
    "EXPECTED_VALIDATION_EVIDENCE_SHA",
    "FREEZE_PATH",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V43_PATHS",
    "verify_release_chain",
]
