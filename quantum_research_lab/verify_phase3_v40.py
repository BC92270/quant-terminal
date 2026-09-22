"""Fail-closed release-chain verifier for Quantum Lab V4.0."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v40_global_connectivity import (
    canonical_json_sha256,
    load_v40_artifact,
    load_v40_spec,
    raw_file_sha256,
)
from .phase3_v40_validation import run_v40_validation


FREEZE_PATH = "FREEZE_CONTRACT_V4_0.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V3_9.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V40_PATHS = (
    "DEPLOY_V4_0.md",
    "app_v40_offline_harness.py",
    "install_quantum_lab_v40.py",
    "outputs/quantum_phase3/v40_connectivity/SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V4_0_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v40_connectivity_engine.cpp",
    "quantum_research_lab/phase3_v40_global_connectivity.py",
    "quantum_research_lab/phase3_v40_ui.py",
    "quantum_research_lab/phase3_v40_validation.py",
    "quantum_research_lab/test_phase3_v40.py",
    "quantum_research_lab/test_phase3_v40_release.py",
    "quantum_research_lab/verify_freeze_contract_v40.py",
    "quantum_research_lab/verify_phase3_v40.py",
    "quantum_research_lab/verify_phase3_v40_ui.py",
    README_PATH,
    UI_PATH,
)

EXPECTED_FROZEN_FILE_COUNT = 145
EXPECTED_V40_PATH_FINGERPRINT = "43e80508152726db7fb8b255ba5642301abaadb6a562783fd235367475000fe3"
EXPECTED_V39_FREEZE_RAW = "e44295aaab7689be7090ff6022a67e2e7d96cc40fcdaedf0328aa50294880c59"
EXPECTED_V39_FREEZE_SHA = "510790b4682e09376feb226b9d0b8b0046477ea456abf0a38e0cadb2410300ac"
EXPECTED_V40_SPEC_RAW = "c86e73ebc4e7852407972dfcab89000e68dbeac4e9d635093a31eadc835109e2"
EXPECTED_V40_SPEC_SHA = "3ab75513efc7014157ef74633ef5c4d9bd4f23b22390f341dbfd033cb8a9694e"
EXPECTED_V40_ARTIFACT_RAW = "3e2918c31ff01d0545125fb641c850af6429a1f8db11709f419c38a2d9f619f2"
EXPECTED_V40_ARTIFACT_SHA = "0fbbddcdf73dde6708814521cc3df741acb53c079e25b6c8829965de56778f01"
EXPECTED_V40_ENGINE_RAW = "16cdfffe8dde853f534349d0531f52c4026271f6f03de53ade77af4ec6726944"
EXPECTED_V40_SOURCE_RAW = "4ad9704cf4007a447195c6c9544ba38caa02316c32c1c0d7032b6a0cb6755afc"
EXPECTED_VALIDATION_EVIDENCE_SHA = "0e451e26f246148ad99d4592904fc7569d75e75d2f5f35139e4cfd4d019fb9ac"


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


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _spec_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in {"v40_spec_sha", "v40_spec_sha256"}}
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


def verify_release_chain(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V4.0 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V4.0 frozen_files must be an object.")
    frozen_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen.items()):
        try:
            actual = raw_file_sha256(_contained_regular(release_root, relative))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        frozen_rows.append({"path": relative, "actual": actual, "expected": expected, "valid": valid})
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
        errors.append(f"V3.9 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent_paths = (
        sorted(set(parent_files) - {README_PATH, UI_PATH})
        if isinstance(parent_files, dict)
        else []
    )
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 127
        and all(frozen.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    spec_path = release_root / "quantum_research_lab/PHASE_III_V4_0_GLOBAL_CONNECTIVITY_SPEC_V1.json"
    try:
        spec_path = _contained_regular(release_root, str(spec_path.relative_to(release_root)))
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v40_spec(spec_path, root=release_root)
    except Exception as exc:
        spec_payload = spec_loaded = {}
        errors.append(f"V4.0 specification invalid: {exc}")
    artifact_path = release_root / "outputs/quantum_phase3/v40_connectivity/SEALED_V4_0_GLOBAL_CONNECTIVITY_ARTIFACT.json"
    try:
        artifact_path = _contained_regular(release_root, str(artifact_path.relative_to(release_root)))
        artifact, artifact_integrity = load_v40_artifact(artifact_path, root=release_root)
    except Exception as exc:
        artifact = {}
        artifact_integrity = {"valid": False, "errors": [str(exc)]}
        errors.append(f"V4.0 artifact invalid: {exc}")
    try:
        validation = run_v40_validation(root=release_root)
    except Exception as exc:
        validation = {"passed": False, "checks": {}, "error": str(exc)}
        errors.append(f"V4.0 scientific validation failed: {exc}")
    try:
        ui_text = _contained_regular(release_root, UI_PATH).read_text(encoding="utf-8")
        readme_text = _contained_regular(release_root, README_PATH).read_text(encoding="utf-8")
        installer_text = _contained_regular(release_root, "install_quantum_lab_v40.py").read_text(encoding="utf-8")
        v40_ui_text = _contained_regular(release_root, "quantum_research_lab/phase3_v40_ui.py").read_text(encoding="utf-8")
    except Exception as exc:
        ui_text = readme_text = installer_text = v40_ui_text = ""
        errors.append(f"Release surface unreadable: {exc}")

    aggregate = artifact.get("aggregate_evidence") or {}
    evidence = artifact.get("connectivity_evidence") or {}
    seed_rows = evidence.get("seed_rows") or []
    decisions = artifact.get("decisions") or {}
    redesign = artifact.get("resource_redesign") or {}
    v39_rejection = artifact.get("v39_resource_rejection") or {}
    boundary = artifact.get("claim_boundary") or {}
    deployment = freeze.get("deployment_contract") or {}
    successor = freeze.get("successor_policy") or {}
    targets = freeze.get("validation_targets") or {}
    isolated = [item for row in seed_rows for item in row.get("isolated_counterexamples", [])]

    checks = {
        "freeze_self_hash_is_exact": bool(freeze and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)),
        "frozen_inventory_count_and_path_fingerprint_are_exact": bool(freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and len(frozen) == EXPECTED_FROZEN_FILE_COUNT and _fingerprint(frozen) == EXPECTED_V40_PATH_FINGERPRINT),
        "every_frozen_path_is_regular_contained_and_exact": len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in frozen_rows),
        "all_v40_transition_paths_are_frozen": set(V40_PATHS).issubset(frozen),
        "v39_freeze_raw_semantic_and_self_hash_are_exact": bool(parent_raw == EXPECTED_V39_FREEZE_RAW and parent_semantic == EXPECTED_V39_FREEZE_SHA and parent.get("freeze_contract_sha256") == EXPECTED_V39_FREEZE_SHA),
        "all_127_immutable_v39_paths_are_preserved": immutable_parent_exact,
        "v39_freeze_itself_is_captured": frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V39_FREEZE_RAW,
        "spec_raw_semantic_and_self_hash_are_exact": bool(spec_payload and raw_file_sha256(spec_path) == EXPECTED_V40_SPEC_RAW and _spec_semantic(spec_payload) == EXPECTED_V40_SPEC_SHA and spec_loaded.get("v40_spec_sha256") == EXPECTED_V40_SPEC_SHA),
        "engine_and_builder_source_identities_are_exact": bool(frozen.get("quantum_research_lab/phase3_v40_connectivity_engine.cpp") == EXPECTED_V40_ENGINE_RAW and frozen.get("quantum_research_lab/phase3_v40_global_connectivity.py") == EXPECTED_V40_SOURCE_RAW),
        "artifact_raw_semantic_and_nested_identity_are_exact": bool(artifact_integrity.get("valid") is True and raw_file_sha256(artifact_path) == EXPECTED_V40_ARTIFACT_RAW and artifact.get("artifact_sha256") == EXPECTED_V40_ARTIFACT_SHA),
        "artifact_parent_chain_is_authenticated": bool(((artifact.get("parent") or {}).get("authentication") or {}).get("valid") is True),
        "scientific_validation_has_21_of_21_checks": bool(validation.get("passed") is True and len(validation.get("checks") or {}) == 21 and all((validation.get("checks") or {}).values()) and validation.get("validation_evidence_sha256") == EXPECTED_VALIDATION_EVIDENCE_SHA),
        "complete_exact_state_graph_aggregate_is_exact": bool(aggregate.get("total_feasible_vertices") == 21_655_776 and aggregate.get("total_exact_state_graph_edges") == 337_710_603 and aggregate.get("total_nine_core_incidences") == 216_557_760 and aggregate.get("total_distinct_nine_cores") == 91_534_251),
        "seed_component_adjudication_is_exact": bool([row.get("seed") for row in seed_rows] == [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807] and [row.get("component_count") for row in seed_rows] == [1, 2, 1, 1, 1, 1, 3, 1]),
        "all_900_neighbor_counterexample_audits_are_exact": bool(len(isolated) == 3 and sum(item.get("neighbors_audited", 0) for item in isolated) == 900 and all(item.get("vertex_exactly_feasible") is True and item.get("all_neighbors_rejected") is True and item.get("feasible_neighbor_count") == 0 for item in isolated)),
        "nine_core_and_union_forest_identities_hold": bool(seed_rows and all(row.get("observed_nine_core_incidences") == 10 * row.get("feasible_vertex_count") and row.get("successful_unions") + row.get("component_count") == row.get("feasible_vertex_count") for row in seed_rows)),
        "connectivity_decision_and_next_gate_are_exact": bool(decisions.get("global_connectivity_decision") == "GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE" and decisions.get("next_falsifiable_gate") == "AUGMENTED_1_2_EXCHANGE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE" and decisions.get("production_admission") == "REJECTED_CONNECTIVITY_AND_V39_RESOURCE_ARCHITECTURE"),
        "resource_redesign_is_preregistered_not_evaluated": bool(redesign.get("status") == "RESOURCE_ARCHITECTURE_PREREGISTERED_NOT_EVALUATED" and (redesign.get("result_fields") or {}).get("cnot") == "NOT_EVALUATED" and (redesign.get("result_fields") or {}).get("budget_margin") == "NOT_COMPUTED" and len(redesign.get("candidate_set") or []) == 2),
        "v39_resource_rejection_is_preserved": bool(v39_rejection.get("preserved") is True and v39_rejection.get("maximum_selected_model_cnot") == 781_332_180 and v39_rejection.get("budget_cnot") == 2_500_000),
        "provider_hardware_and_advantage_boundary_is_zero": bool(boundary.get("provider_calls") == 0 and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("hardware_executable") is False and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "v40_scientific_modules_have_provider_free_imports": all(_provider_free_imports(_contained_regular(release_root, relative)) for relative in ("quantum_research_lab/phase3_v40_global_connectivity.py", "quantum_research_lab/phase3_v40_validation.py", "quantum_research_lab/phase3_v40_ui.py")),
        "ui_imports_and_renders_v40_after_v39": bool("render_v40_connectivity_redesign_panel" in ui_text and ui_text.index("render_v40_connectivity_redesign_panel") > ui_text.index("render_v39_scalable_ir_panel") and "load_v40_ui_artifact" in ui_text),
        "ui_fails_provider_and_hardware_controls_closed": bool('disabled=is_bands_candidate' in ui_text and 'data-qv40-provider-calls="0"' in v40_ui_text and 'data-qv40-hardware="false"' in v40_ui_text and 'if ok:' in v40_ui_text),
        "readme_preserves_bounded_v40_decision": bool("GLOBAL_FEASIBLE_GRAPH_DISCONNECTED_COUNTEREXAMPLE" in readme_text and "21,655,776" in readme_text and "V4.1" in readme_text and "NOT_EVALUATED" in readme_text),
        "installer_contains_owned_lock_private_stage_and_rollback": bool("lock_owned" in installer_text and "stage" in installer_text.lower() and "PREIMAGE" in installer_text and "NO_OP" in installer_text),
        "successor_policy_accepts_only_v39_or_exact_v40": bool(successor.get("accepted_target_states") == ["V3.9", "V4.0"] and successor.get("allowed_v39_superseded_files") == [README_PATH, UI_PATH] and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_route_are_exact": bool(deployment.get("overlay_file_count") == 18 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12),
        "deployment_is_staged_idempotent_and_rollback_capable": bool(deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("lock_release_requires_owned_token") is True),
        "release_records_validation_targets": bool(targets.get("scientific_validation_checks") == 21 and targets.get("release_chain_checks") == 29 and targets.get("streamlit_ui_checks") == 33),
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "root": str(release_root),
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": failed,
        "errors": list(dict.fromkeys(errors + list(artifact_integrity.get("errors") or []))),
        "frozen_path_count": len(frozen_rows),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "validation_evidence_sha256": validation.get("validation_evidence_sha256"),
        "valid": not failed and not errors and artifact_integrity.get("valid") is True,
        "verifier": "QUANTUM LAB V4.0 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V4.0 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_V40_PATH_FINGERPRINT",
    "FREEZE_PATH",
    "README_PATH",
    "UI_PATH",
    "V40_PATHS",
    "verify_release_chain",
]
