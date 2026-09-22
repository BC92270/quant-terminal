"""Fail-closed release-chain verifier for Quantum Lab V3.9."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v39_scalable_reversible_ir import (
    canonical_json_sha256,
    load_v39_artifact,
    load_v39_spec,
    raw_file_sha256,
)
from .phase3_v39_validation import run_v39_validation


FREEZE_PATH = "FREEZE_CONTRACT_V3_9.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V3_8.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V39_PATHS = (
    "DEPLOY_V3_9.md",
    "app_v39_offline_harness.py",
    "install_quantum_lab_v39.py",
    "outputs/quantum_phase3/v39_scalable_ir/SEALED_V3_9_SCALABLE_REVERSIBLE_IR_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_9_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v39_scalable_reversible_ir.py",
    "quantum_research_lab/phase3_v39_ui.py",
    "quantum_research_lab/phase3_v39_validation.py",
    "quantum_research_lab/test_phase3_v39.py",
    "quantum_research_lab/test_phase3_v39_release.py",
    "quantum_research_lab/verify_freeze_contract_v39.py",
    "quantum_research_lab/verify_phase3_v39.py",
    "quantum_research_lab/verify_phase3_v39_ui.py",
    README_PATH,
    UI_PATH,
)
EXPECTED_FROZEN_FILE_COUNT = 129
EXPECTED_V39_PATH_FINGERPRINT = "ed2f8d6027b7b00c4ad68ed48f72e73b81dd240238849daba4c79ea050f72ce7"
EXPECTED_V38_FREEZE_RAW = "a267509a153ff2bbec671b963823f818278bad3ee74f8c56e8a5687d805fd7d6"
EXPECTED_V38_FREEZE_SHA = "5b73497b5a06071aa9411296aa0ed6ec5e924b4372066a1b4a9b9ca240cfc810"
EXPECTED_V39_SPEC_RAW = "b710e884216a765118c6309b59b0a30adf284ba89163ac34151e26d4629d1b7d"
EXPECTED_V39_SPEC_SHA = "a3845e1b553f25eaebb4a80cb697c28dae2da07e1193ecf6cd03158de428ec5c"
EXPECTED_V39_ARTIFACT_RAW = "38d2d16856f1930f1f86848929a4341cab18e02edf387208debc6cd5213aed29"
EXPECTED_V39_ARTIFACT_SHA = "26856f1e26bed5dc5b9a6d6af7bb25c53ef0b25188d8c787276afbeb08027775"


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
    payload = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates, parse_constant=_reject_nonfinite)
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
    return canonical_json_sha256({key: value for key, value in payload.items() if key != "freeze_contract_sha256"})


def _spec_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256({key: value for key, value in payload.items() if key not in {"v39_spec_sha", "v39_spec_sha256"}})


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


def verify_release_chain(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V3.9 freeze unavailable: {exc}")
    frozen = freeze.get("frozen_files") or {}
    if not isinstance(frozen, dict):
        frozen = {}
        errors.append("V3.9 frozen_files must be an object.")
    fingerprint = hashlib.sha256(json.dumps(sorted(frozen), separators=(",", ":")).encode("utf-8")).hexdigest()
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
        errors.append(f"V3.8 freeze unavailable: {exc}")
    parent_files = parent.get("frozen_files") or {}
    immutable_parent_paths = sorted(set(parent_files) - {README_PATH, UI_PATH}) if isinstance(parent_files, dict) else []
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 112
        and all(frozen.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    try:
        spec_path = _contained_regular(release_root, "quantum_research_lab/PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json")
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v39_spec(spec_path)
    except Exception as exc:
        spec_path = release_root / "quantum_research_lab/PHASE_III_V3_9_SCALABLE_REVERSIBLE_IR_SPEC_V1.json"
        spec_payload = spec_loaded = {}
        errors.append(f"V3.9 specification invalid: {exc}")
    try:
        artifact_path = _contained_regular(release_root, "outputs/quantum_phase3/v39_scalable_ir/SEALED_V3_9_SCALABLE_REVERSIBLE_IR_ARTIFACT.json")
        artifact, artifact_integrity = load_v39_artifact(artifact_path)
    except Exception as exc:
        artifact = {}
        artifact_integrity = {"valid": False, "errors": [str(exc)]}
        errors.append(f"V3.9 artifact invalid: {exc}")
    try:
        validation = run_v39_validation()
    except Exception as exc:
        validation = {"passed": False, "checks": {}, "error": str(exc)}
        errors.append(f"V3.9 scientific validation failed: {exc}")
    try:
        ui_text = _contained_regular(release_root, UI_PATH).read_text(encoding="utf-8")
        readme_text = _contained_regular(release_root, README_PATH).read_text(encoding="utf-8")
        installer_text = _contained_regular(release_root, "install_quantum_lab_v39.py").read_text(encoding="utf-8")
        v39_ui_text = _contained_regular(release_root, "quantum_research_lab/phase3_v39_ui.py").read_text(encoding="utf-8")
    except Exception as exc:
        ui_text = readme_text = installer_text = v39_ui_text = ""
        errors.append(f"Release surface unreadable: {exc}")
    aggregate = artifact.get("aggregate_evidence") or {}
    screen = artifact.get("resource_screen") or {}
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    deployment = freeze.get("deployment_contract") or {}
    successor = freeze.get("successor_policy") or {}
    checks = {
        "freeze_self_hash_is_exact": bool(freeze and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)),
        "frozen_inventory_count_and_path_fingerprint_are_exact": bool(freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT and len(frozen) == EXPECTED_FROZEN_FILE_COUNT and fingerprint == EXPECTED_V39_PATH_FINGERPRINT),
        "every_frozen_path_is_regular_contained_and_exact": len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in frozen_rows),
        "all_v39_transition_paths_are_frozen": set(V39_PATHS).issubset(frozen),
        "v38_freeze_raw_semantic_and_self_hash_are_exact": bool(parent_raw == EXPECTED_V38_FREEZE_RAW and parent_semantic == EXPECTED_V38_FREEZE_SHA and parent.get("freeze_contract_sha256") == EXPECTED_V38_FREEZE_SHA),
        "all_112_immutable_v38_paths_are_preserved": immutable_parent_exact,
        "v38_freeze_itself_is_captured": frozen.get(PARENT_FREEZE_PATH) == EXPECTED_V38_FREEZE_RAW,
        "spec_raw_semantic_and_self_hash_are_exact": bool(spec_payload and raw_file_sha256(spec_path) == EXPECTED_V39_SPEC_RAW and _spec_semantic(spec_payload) == EXPECTED_V39_SPEC_SHA and spec_loaded.get("v39_spec_sha256") == EXPECTED_V39_SPEC_SHA),
        "artifact_raw_semantic_and_nested_identity_are_exact": bool(artifact_integrity.get("valid") is True and raw_file_sha256(artifact_path) == EXPECTED_V39_ARTIFACT_RAW and artifact.get("artifact_sha256") == EXPECTED_V39_ARTIFACT_SHA),
        "artifact_parent_chain_is_authenticated": bool(((artifact.get("parent") or {}).get("authentication") or {}).get("valid") is True),
        "scientific_validation_has_18_of_18_checks": bool(validation.get("passed") is True and len(validation.get("checks") or {}) == 18 and all((validation.get("checks") or {}).values())),
        "complete_n40_proof_inventory_is_exact": bool(aggregate.get("edge_seed_positions") == 6_240 and aggregate.get("constraint_row_cases") == 43_680 and aggregate.get("live_edge_positions") == 4_220 and aggregate.get("certified_identity_positions") == 2_020),
        "selected_model_resource_screen_is_exact": bool(screen.get("budget_cnot") == 2_500_000 and screen.get("maximum_selected_model_cnot") == 781_332_180 and screen.get("minimum_budget_margin_cnot") == -778_832_180 and screen.get("decision") == "REJECTED_SELECTED_MODEL_CNOT_BUDGET"),
        "bounded_decisions_and_next_gate_are_exact": bool(decisions.get("overall") == "N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED" and decisions.get("reversible_ir_decision") == "N40_REVERSIBLE_IR_PASSED" and decisions.get("complete_global_connectivity") == "INDETERMINATE" and decisions.get("next_falsifiable_gate") == "GLOBAL_FEASIBLE_GRAPH_CONNECTIVITY_OR_COUNTEREXAMPLE"),
        "provider_hardware_and_advantage_boundary_is_zero": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("provider_calls") == 0 and boundary.get("backend_transpilation") == "NOT_RUN" and boundary.get("hardware_executable") is False and boundary.get("qpu_jobs_submitted") == 0 and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "v39_scientific_modules_have_provider_free_imports": all(_provider_free_imports(_contained_regular(release_root, relative)) for relative in ("quantum_research_lab/phase3_v39_scalable_reversible_ir.py", "quantum_research_lab/phase3_v39_validation.py", "quantum_research_lab/phase3_v39_ui.py")),
        "ui_imports_and_renders_v39_after_v38": bool("render_v39_scalable_ir_panel" in ui_text and ui_text.index("render_v39_scalable_ir_panel") > ui_text.index("render_v38_elementary_admission_panel") and "load_v39_ui_artifact" in ui_text),
        "ui_fails_provider_controls_closed_for_bands": bool('disabled=bool(is_bands_candidate and v38_integrity)' not in ui_text and 'disabled=bool(is_bands_candidate)' not in ui_text and 'disabled=is_bands_candidate' in ui_text and 'data-qv39-provider-calls="0"' in v39_ui_text),
        "readme_preserves_bounded_v39_decision": bool("N40_REVERSIBLE_IR_PASSED_RESOURCE_SCREEN_REJECTED" in readme_text and "781,332,180" in readme_text and "Full-binary operator equivalence and complete feasible-graph connectivity are not claimed" in readme_text),
        "installer_contains_owned_lock_and_private_stage_controls": bool("lock_owned" in installer_text and "stage" in installer_text.lower() and "PREIMAGE" in installer_text and "NO_OP" in installer_text),
        "successor_policy_accepts_only_v38_or_exact_v39": bool(successor.get("accepted_target_states") == ["V3.8", "V3.9"] and successor.get("allowed_v38_superseded_files") == [README_PATH, UI_PATH] and successor.get("mixed_or_third_state") == "REJECT"),
        "deployment_overlay_order_and_route_are_exact": bool(deployment.get("overlay_file_count") == 17 and deployment.get("readme_surface_penultimate") == README_PATH and deployment.get("integration_surface_last") == UI_PATH and deployment.get("route") == "?workspace=quantum-research" and deployment.get("streamlit_tab_count") == 12),
        "deployment_is_staged_idempotent_and_rollback_capable": bool(deployment.get("source_snapshot_rehashed_before_commit") is True and deployment.get("idempotent_exact_reapply") == "NO_OP" and deployment.get("rollback_requires_preimage_hashes") is True and deployment.get("lock_release_requires_owned_token") is True),
        "release_records_validation_targets": bool((freeze.get("validation_targets") or {}).get("scientific_validation_checks") == 18 and (freeze.get("validation_targets") or {}).get("streamlit_ui_checks") == 23),
    }
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "root": str(release_root),
        "checks": checks,
        "check_count": len(checks),
        "failed_checks": failed,
        "errors": list(dict.fromkeys(errors)),
        "frozen_path_count": len(frozen_rows),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "validation_manifest_sha256": validation.get("validation_manifest_sha256"),
        "valid": not failed and not errors,
        "verifier": "QUANTUM LAB V3.9 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.9 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["EXPECTED_FROZEN_FILE_COUNT", "EXPECTED_V39_PATH_FINGERPRINT", "FREEZE_PATH", "V39_PATHS", "verify_release_chain"]
