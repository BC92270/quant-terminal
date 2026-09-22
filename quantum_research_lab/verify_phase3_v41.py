"""Fail-closed release-chain verifier for Quantum Lab V4.1."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .phase3_v41_certified_bridge_compiler import (
    canonical_json_sha256,
    load_v41_spec,
    raw_file_sha256,
)
from .phase3_v41_validation import run_v41_validation


FREEZE_PATH = "FREEZE_CONTRACT_V4_1.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V4_0.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V41_PATHS = (
    "DEPLOY_V4_1.md",
    "app_v41_offline_harness.py",
    "install_quantum_lab_v41.py",
    "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_1_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v41_bridge_engine.cpp",
    "quantum_research_lab/phase3_v41_certified_bridge_compiler.py",
    "quantum_research_lab/phase3_v41_ui.py",
    "quantum_research_lab/phase3_v41_validation.py",
    "quantum_research_lab/test_phase3_v41.py",
    "quantum_research_lab/test_phase3_v41_release.py",
    "quantum_research_lab/verify_freeze_contract_v41.py",
    "quantum_research_lab/verify_phase3_v41.py",
    "quantum_research_lab/verify_phase3_v41_ui.py",
    README_PATH,
    UI_PATH,
)

EXPECTED_FROZEN_FILE_COUNT = 161
EXPECTED_V41_PATH_FINGERPRINT = "27bb43b53f3c6847d1ef80518c595755c1e606015b423c194c8a2e61f3f76ea8"
EXPECTED_V40_FREEZE_RAW = "748829b2153611ffba0751ea5da9d0785ca44ce4f12a02546436d4a1e79a94b4"
EXPECTED_V40_FREEZE_SHA = "c6d380e5541182b6cc2096c3d2a6de6f129cb92c80288a43dae6f924314cff1e"
EXPECTED_V41_SPEC_RAW = "0bbe903e7520213f8effcd592051420ac54502934a1840b6052e3b4865950c35"
EXPECTED_V41_SPEC_SHA = "a5977ce4dda24d2fe6e8308e299b8a6b9097cf4fdf7e2835ca8e2fdc6aa99c89"
EXPECTED_V41_ARTIFACT_RAW = "42a5d7caf4e9fab18e771b2bd55fc38c9a77f7fac42f2599feb4fe789cf88c07"
EXPECTED_V41_ARTIFACT_SHA = "7260336e3a3c6bd2adbd6397d9bed569b91c2da2a7942a17b8090fdcac739e4e"
EXPECTED_V41_ENGINE_RAW = "6b065ac1fb834e9ff226954984fe466901314c9b556c2c253a0ace873f2bf26e"
EXPECTED_V41_SOURCE_RAW = "5565ce436034183228d27e37b249afc56f19121a5a8c2638533d4480762c62d1"
EXPECTED_VALIDATION_EVIDENCE_SHA = "be7b47a74a6da02af9867f531f47a5c72b473da13c6eb872e7dce1ddede9ff06"
EXPECTED_SEEDS = [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]


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
    if not relative or item.is_absolute() or any(
        part in {"", ".", ".."} for part in item.parts
    ):
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


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _spec_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"v41_spec_sha", "v41_spec_sha256"}
        }
    )


def _artifact_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "artifact_sha256"}
    )


def _provider_free_imports(path: Path) -> bool:
    forbidden = {"qiskit", "cirq", "braket", "pennylane", "qbraid"}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        if any(name.split(".")[0] in forbidden for name in names):
            return False
    return True


def _fingerprint(paths: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(sorted(paths), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fast_validation_commitment(freeze: Mapping[str, Any]) -> dict[str, Any]:
    identities = freeze.get("v41_identities") or {}
    exact = identities.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA
    return {
        "checks": {"frozen_validation_evidence_identity": exact},
        "counts": {"checks_passed": 28 if exact else 0, "checks_total": 28},
        "errors": [] if exact else ["Frozen scientific-validation identity mismatch."],
        "failed_checks": [] if exact else ["frozen_validation_evidence_identity"],
        "passed": exact,
        "validation_evidence_sha256": identities.get("validation_evidence_sha256"),
        "validation_version": "IDENTITY_ONLY · DEEP REPLAY NOT RUN IN THIS INVOCATION",
    }


def verify_release_chain(
    root: str | Path,
    *,
    deep: bool = True,
) -> dict[str, Any]:
    """Verify V4.1; ``deep=False`` is an explicitly labelled identity audit."""

    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.1 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.1 frozen_files must be an object.")

    frozen_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen.items()):
        try:
            actual = raw_file_sha256(_contained_regular(release_root, relative))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        frozen_rows.append(
            {"path": relative, "actual": actual, "expected": expected, "valid": valid}
        )
        if not valid:
            errors.append(f"Frozen file mismatch: {relative}")

    try:
        parent_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent = _read_json_strict(parent_path)
        parent_raw = raw_file_sha256(parent_path)
        parent_semantic = _freeze_semantic(parent)
    except Exception as exc:
        parent = {}
        parent_raw = parent_semantic = None
        errors.append(f"V4.0 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent_paths = (
        sorted(set(parent_files) - {README_PATH, UI_PATH})
        if isinstance(parent_files, dict)
        else []
    )
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 143
        and all(frozen.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    spec_relative = "quantum_research_lab/PHASE_III_V4_1_CERTIFIED_BRIDGE_COMPILER_SPEC_V1.json"
    try:
        spec_path = _contained_regular(release_root, spec_relative)
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v41_spec(spec_path, root=release_root)
    except Exception as exc:
        spec_path = release_root / spec_relative
        spec_payload = spec_loaded = {}
        errors.append(f"V4.1 specification invalid: {exc}")

    artifact_relative = "outputs/quantum_phase3/v41_certified_bridge/SEALED_V4_1_CERTIFIED_BRIDGE_COMPILER_ARTIFACT.json"
    try:
        artifact_path = _contained_regular(release_root, artifact_relative)
        artifact = _read_json_strict(artifact_path)
        artifact_raw = raw_file_sha256(artifact_path)
        artifact_semantic = _artifact_semantic(artifact)
    except Exception as exc:
        artifact_path = release_root / artifact_relative
        artifact = {}
        artifact_raw = artifact_semantic = None
        errors.append(f"V4.1 artifact invalid: {exc}")

    try:
        validation = (
            run_v41_validation(root=str(release_root))
            if deep
            else _fast_validation_commitment(freeze)
        )
    except Exception as exc:
        validation = {"passed": False, "checks": {}, "errors": [str(exc)]}
        errors.append(f"V4.1 scientific validation failed: {exc}")

    try:
        ui_text = _contained_regular(release_root, UI_PATH).read_text(encoding="utf-8")
        readme_text = _contained_regular(release_root, README_PATH).read_text(encoding="utf-8")
        installer_text = _contained_regular(release_root, "install_quantum_lab_v41.py").read_text(encoding="utf-8")
        v41_ui_text = _contained_regular(
            release_root, "quantum_research_lab/phase3_v41_ui.py"
        ).read_text(encoding="utf-8")
    except Exception as exc:
        ui_text = readme_text = installer_text = v41_ui_text = ""
        errors.append(f"Release surface unreadable: {exc}")

    bridge_audits = artifact.get("bridge_audits") or {}
    audit_rows = bridge_audits.get("rows") or []
    connectivity = artifact.get("connectivity_evidence") or {}
    connectivity_aggregate = connectivity.get("aggregate") or {}
    connectivity_rows = connectivity.get("seed_rows") or []
    compression = artifact.get("compression_evidence") or {}
    compression_rows = compression.get("seed_rows") or []
    resources = artifact.get("resource_evidence") or {}
    resource_aggregate = resources.get("aggregate") or {}
    resource_rows = resources.get("seed_rows") or []
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    v39_rejection = artifact.get("v39_resource_rejection") or {}
    artifact_parent = ((artifact.get("parent") or {}).get("authentication") or {})
    deployment = freeze.get("deployment_contract") or {}
    successor = freeze.get("successor_policy") or {}
    targets = freeze.get("validation_targets") or {}
    identities = freeze.get("v41_identities") or {}

    required_methods = {
        "PYTHON_EXACT_DELTA_CANONICAL_ORDER_V1",
        "PYTHON_EXACT_FULL_RECOMPUTE_REVERSED_ENUMERATION_V1",
        "INDEPENDENT_CPP_INT128_FULL_TWO_SWAP_AUDIT_V1",
    }
    checks = {
        "freeze_self_hash_is_exact": bool(
            freeze and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
        ),
        "frozen_inventory_count_and_path_fingerprint_are_exact": bool(
            freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT
            and len(frozen) == EXPECTED_FROZEN_FILE_COUNT
            and _fingerprint(frozen) == EXPECTED_V41_PATH_FINGERPRINT
        ),
        "every_frozen_path_is_regular_contained_and_exact": bool(
            len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT
            and all(row["valid"] for row in frozen_rows)
        ),
        "all_v41_transition_paths_are_frozen": set(V41_PATHS).issubset(frozen),
        "v40_freeze_raw_semantic_and_self_hash_are_exact": bool(
            parent_raw == EXPECTED_V40_FREEZE_RAW
            and parent_semantic == EXPECTED_V40_FREEZE_SHA
            and parent.get("freeze_contract_sha256") == EXPECTED_V40_FREEZE_SHA
        ),
        "all_143_immutable_v40_paths_are_preserved": immutable_parent_exact,
        "v40_freeze_itself_is_captured": frozen.get(PARENT_FREEZE_PATH)
        == EXPECTED_V40_FREEZE_RAW,
        "spec_raw_semantic_and_self_hash_are_exact": bool(
            spec_payload
            and raw_file_sha256(spec_path) == EXPECTED_V41_SPEC_RAW
            and _spec_semantic(spec_payload) == EXPECTED_V41_SPEC_SHA
            and spec_loaded.get("v41_spec_sha256") == EXPECTED_V41_SPEC_SHA
        ),
        "engine_and_compiler_source_identities_are_exact": bool(
            frozen.get("quantum_research_lab/phase3_v41_bridge_engine.cpp")
            == EXPECTED_V41_ENGINE_RAW
            and frozen.get("quantum_research_lab/phase3_v41_certified_bridge_compiler.py")
            == EXPECTED_V41_SOURCE_RAW
            and artifact.get("source_sha256") == EXPECTED_V41_SOURCE_RAW
            and artifact.get("engine_source_raw_file_sha256") == EXPECTED_V41_ENGINE_RAW
        ),
        "artifact_raw_semantic_and_nested_identity_are_exact": bool(
            artifact_raw == EXPECTED_V41_ARTIFACT_RAW
            and artifact_semantic == EXPECTED_V41_ARTIFACT_SHA
            and artifact.get("artifact_sha256") == EXPECTED_V41_ARTIFACT_SHA
            and artifact.get("spec_sha256") == EXPECTED_V41_SPEC_SHA
        ),
        "artifact_parent_chain_is_authenticated": bool(
            artifact_parent.get("valid") is True
            and artifact_parent.get("immutable_v40_paths_authenticated") == 143
            and not artifact_parent.get("errors")
        ),
        "scientific_validation_has_28_of_28_checks": bool(
            validation.get("passed") is True
            and validation.get("counts", {}).get("checks_total") == 28
            and validation.get("counts", {}).get("checks_passed") == 28
            and validation.get("validation_evidence_sha256")
            == EXPECTED_VALIDATION_EVIDENCE_SHA
            and identities.get("validation_evidence_sha256")
            == EXPECTED_VALIDATION_EVIDENCE_SHA
        ),
        "complete_incident_bridge_universe_is_exact": bool(
            len(audit_rows) == 3
            and sum(row.get("candidates_audited", 0) for row in audit_rows) == 58_725
            and sum(row.get("feasible_neighbor_count", 0) for row in audit_rows) == 787
            and bridge_audits.get("all_triple_replays_match") is True
        ),
        "three_independent_bridge_methods_are_exact": bool(
            audit_rows
            and all(
                set(row.get("independent_methods") or []) == required_methods
                and row.get("triple_replay_match") is True
                for row in audit_rows
            )
        ),
        "augmented_connectivity_certificate_is_exact": bool(
            connectivity_aggregate.get("all_eight_seeds_connected_by_certified_subgraph")
            is True
            and connectivity_aggregate.get("selected_bridge_count") == 3
            and connectivity_aggregate.get("final_components_across_seeds") == 8
            and connectivity_aggregate.get("selected_spanning_subgraph_edges")
            == 337_710_606
        ),
        "selected_bridges_and_seed_order_are_exact": bool(
            [row.get("seed") for row in connectivity_rows] == EXPECTED_SEEDS
            and sum(len(row.get("selected_bridges") or []) for row in connectivity_rows)
            == 3
            and all(
                bridge.get("hamming_distance") == 4
                for row in connectivity_rows
                for bridge in row.get("selected_bridges") or []
            )
        ),
        "complete_augmented_edge_count_is_not_overclaimed": (
            connectivity_aggregate.get("complete_augmented_edge_count")
            == "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE"
        ),
        "all_24_compression_certificates_are_exact": bool(
            compression.get("all_factor_predicates_exact") is True
            and len(compression_rows) == 8
            and sum(len(row.get("factor_rows") or []) for row in compression_rows) == 24
            and all(row.get("all_factor_predicates_exact") is True for row in compression_rows)
        ),
        "r1_r2_resource_rejection_is_exact": bool(
            [row.get("seed") for row in resource_rows] == EXPECTED_SEEDS
            and resource_aggregate.get("r1_maximum_selected_model_cnot") == 15_256_056
            and resource_aggregate.get("r2_maximum_selected_model_cnot") == 15_663_936
            and resource_aggregate.get("r2_minimum_budget_margin_cnot") == -13_163_936
            and resource_aggregate.get("budget_cnot") == 2_500_000
            and resource_aggregate.get("r1_all_seeds_pass") is False
            and resource_aggregate.get("r2_all_seeds_pass") is False
        ),
        "logical_qubit_and_cache_scope_are_exact": bool(
            resource_aggregate.get("cache_preparation_excluded_from_numerator") is True
            and max(
                (
                    (row.get("r2") or {}).get(
                        "logical_qubits_with_clean_decomposition_ancillas", -1
                    )
                    for row in resource_rows
                ),
                default=-1,
            )
            == 311
        ),
        "decisions_and_next_gate_are_exact": bool(
            decisions.get("augmented_connectivity_decision")
            == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
            and decisions.get("resource_architecture_decision")
            == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"
            and decisions.get("production_admission")
            == "REJECTED_RESOURCE_BUDGET_HARDWARE_NOT_AUTHORIZED"
            and decisions.get("next_falsifiable_gate")
            == "SPARSE_CONNECTED_GENERATOR_COMPILER_OR_STRONGER_EXACT_ARITHMETIC_REDUCTION"
        ),
        "v39_resource_rejection_is_preserved": bool(
            v39_rejection.get("preserved") is True
            and v39_rejection.get("maximum_selected_model_cnot") == 781_332_180
            and v39_rejection.get("budget_cnot") == 2_500_000
        ),
        "provider_hardware_and_advantage_boundary_is_zero": bool(
            artifact.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("hardware_executable") is False
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v41_scientific_modules_have_provider_free_imports": all(
            _provider_free_imports(_contained_regular(release_root, relative))
            for relative in (
                "quantum_research_lab/phase3_v41_certified_bridge_compiler.py",
                "quantum_research_lab/phase3_v41_validation.py",
                "quantum_research_lab/phase3_v41_ui.py",
            )
        ),
        "ui_imports_and_renders_v41_after_v40": bool(
            "render_v41_certified_bridge_compiler_panel" in ui_text
            and ui_text.index("render_v41_certified_bridge_compiler_panel")
            > ui_text.index("render_v40_connectivity_redesign_panel")
            and "load_v41_ui_artifact" in ui_text
        ),
        "ui_fails_provider_and_hardware_controls_closed": bool(
            'data-qv41-hardware="false"' in v41_ui_text
            and 'data-qv41-jobs="0"' in v41_ui_text
            and "PROVIDER CALLS · 0 · CREDENTIALS READ · FALSE · SDK IMPORTED · FALSE"
            in v41_ui_text
            and "if ok:" in v41_ui_text
            and "disabled=is_bands_candidate" in ui_text
        ),
        "readme_preserves_bounded_v41_decision": bool(
            "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTED_ALL_SEEDS_BY_CERTIFIED_SUBGRAPH"
            in readme_text
            and "58,725 / 58,725" in readme_text
            and "15,663,936" in readme_text
            and "NOT_ENUMERATED_NOT_REQUIRED_FOR_CONNECTIVITY_CERTIFICATE"
            in readme_text
        ),
        "installer_and_successor_policy_are_fail_closed": bool(
            "lock_owned" in installer_text
            and "PREIMAGE" in installer_text
            and "NO_OP" in installer_text
            and successor.get("accepted_target_states") == ["V4.0", "V4.1"]
            and successor.get("allowed_v40_superseded_files")
            == [README_PATH, UI_PATH]
            and successor.get("mixed_or_third_state") == "REJECT"
        ),
        "deployment_order_route_and_validation_targets_are_exact": bool(
            deployment.get("overlay_file_count") == 18
            and deployment.get("readme_surface_penultimate") == README_PATH
            and deployment.get("integration_surface_last") == UI_PATH
            and deployment.get("route") == "?workspace=quantum-research"
            and deployment.get("streamlit_tab_count") == 12
            and deployment.get("source_snapshot_rehashed_before_commit") is True
            and deployment.get("idempotent_exact_reapply") == "NO_OP"
            and deployment.get("rollback_requires_preimage_hashes") is True
            and deployment.get("lock_release_requires_owned_token") is True
            and targets.get("scientific_validation_checks") == 28
            and targets.get("artifact_reconstruction_checks") == 16
            and targets.get("release_chain_checks") == 29
            and targets.get("freeze_contract_checks") == 18
            and targets.get("streamlit_ui_checks") == 31
        ),
    }
    failed = [name for name, value in checks.items() if value is not True]
    merged_errors = list(dict.fromkeys(errors + list(validation.get("errors") or [])))
    return {
        "artifact_sha256": artifact.get("artifact_sha256"),
        "check_count": len(checks),
        "checks": checks,
        "deep_scientific_replay": deep,
        "errors": merged_errors,
        "failed_checks": failed,
        "frozen_path_count": len(frozen_rows),
        "root": str(release_root),
        "valid": not failed and not merged_errors,
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "verifier": "QUANTUM LAB V4.1 RELEASE CHAIN · V1",
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            + "\n",
            encoding="utf-8",
        )
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V4.1 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    parser.add_argument(
        "--identity-only",
        action="store_true",
        help="Authenticate frozen evidence without repeating the deep scientific replay.",
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root, deep=not args.identity_only)
    if args.output is not None:
        _atomic_write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_VALIDATION_EVIDENCE_SHA",
    "EXPECTED_V41_ARTIFACT_RAW",
    "EXPECTED_V41_ARTIFACT_SHA",
    "EXPECTED_V41_ENGINE_RAW",
    "EXPECTED_V41_PATH_FINGERPRINT",
    "EXPECTED_V41_SOURCE_RAW",
    "EXPECTED_V41_SPEC_RAW",
    "EXPECTED_V41_SPEC_SHA",
    "EXPECTED_V40_FREEZE_RAW",
    "EXPECTED_V40_FREEZE_SHA",
    "FREEZE_PATH",
    "PARENT_FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V41_PATHS",
    "verify_release_chain",
]
