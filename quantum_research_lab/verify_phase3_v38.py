"""Fail-closed release-chain verifier for Quantum Lab V3.8."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256, raw_file_sha256
from .phase3_v38_elementary_admission import (
    EXPECTED_V37_ARTIFACT_RAW_SHA256,
    EXPECTED_V37_ARTIFACT_SHA256,
    EXPECTED_V37_FREEZE_RAW_SHA256,
    EXPECTED_V37_FREEZE_SHA256,
    EXPECTED_V38_SPEC_RAW_SHA256,
    EXPECTED_V38_SPEC_SHA256,
    load_v38_artifact,
    load_v38_spec,
)
from .phase3_v38_validation import run_v38_validation


FREEZE_PATH = "FREEZE_CONTRACT_V3_8.json"
PARENT_FREEZE_PATH = "FREEZE_CONTRACT_V3_7.json"
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V38_PATHS = (
    "DEPLOY_V3_8.md",
    "app_v38_offline_harness.py",
    "install_quantum_lab_v38.py",
    "outputs/quantum_phase3/v38_elementary/SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json",
    "quantum_research_lab/PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json",
    "quantum_research_lab/QUANTUM_LAB_V3_8_ARCHITECTURE.md",
    "quantum_research_lab/phase3_v38_elementary_admission.py",
    "quantum_research_lab/phase3_v38_ui.py",
    "quantum_research_lab/phase3_v38_validation.py",
    "quantum_research_lab/test_phase3_v38.py",
    "quantum_research_lab/test_phase3_v38_release.py",
    "quantum_research_lab/verify_freeze_contract_v38.py",
    "quantum_research_lab/verify_phase3_v38.py",
    "quantum_research_lab/verify_phase3_v38_ui.py",
    README_PATH,
    UI_PATH,
)
EXPECTED_FROZEN_FILE_COUNT = 114
EXPECTED_V38_PATH_FINGERPRINT = "90df2180f9965d3721b91b215b2ac7da0eddcde38f890d374863b3079f1c2f19"


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _reject_non_finite(token: str) -> None:
    raise ValueError(f"Non-finite JSON number rejected: {token}")


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicates,
        parse_constant=_reject_non_finite,
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        {
            key: value
            for key, value in payload.items()
            if key not in {"v38_spec_sha", "v38_spec_sha256"}
        }
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


def verify_release_chain(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []
    try:
        freeze_path = _contained_regular(release_root, FREEZE_PATH)
        freeze = _read_json_strict(freeze_path)
    except Exception as exc:
        freeze = {}
        errors.append(f"V3.8 freeze unavailable: {exc}")
    frozen_files = freeze.get("frozen_files") or {}
    if not isinstance(frozen_files, dict):
        frozen_files = {}
        errors.append("V3.8 frozen_files must be an object.")
    path_fingerprint = hashlib.sha256(
        json.dumps(sorted(frozen_files), separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    frozen_rows: list[dict[str, Any]] = []
    for relative, expected in sorted(frozen_files.items()):
        try:
            actual = _sha256(_contained_regular(release_root, relative))
            valid = actual == expected
        except Exception as exc:
            actual = None
            valid = False
            errors.append(f"Frozen path {relative}: {exc}")
        frozen_rows.append({"path": relative, "actual": actual, "expected": expected, "valid": valid})
        if not valid:
            errors.append(f"Frozen file mismatch: {relative}")

    try:
        parent_freeze_path = _contained_regular(release_root, PARENT_FREEZE_PATH)
        parent_freeze = _read_json_strict(parent_freeze_path)
        parent_raw = _sha256(parent_freeze_path)
        parent_semantic = _freeze_semantic(parent_freeze)
    except Exception as exc:
        parent_freeze = {}
        parent_raw = parent_semantic = None
        errors.append(f"V3.7 freeze unavailable: {exc}")
    parent_files = parent_freeze.get("frozen_files") or {}
    immutable_parent_paths = sorted(set(parent_files) - {README_PATH, UI_PATH}) if isinstance(parent_files, dict) else []
    immutable_parent_exact = bool(
        len(immutable_parent_paths) == 97
        and all(frozen_files.get(path) == parent_files.get(path) for path in immutable_parent_paths)
    )

    try:
        spec_path = _contained_regular(
            release_root,
            "quantum_research_lab/PHASE_III_V3_8_ELEMENTARY_ADMISSION_SPEC_V1.json",
        )
        spec_payload = _read_json_strict(spec_path)
        spec_loaded = load_v38_spec(spec_path)
    except Exception as exc:
        spec_payload = spec_loaded = {}
        errors.append(f"V3.8 specification invalid: {exc}")
    try:
        artifact_path = _contained_regular(
            release_root,
            "outputs/quantum_phase3/v38_elementary/SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json",
        )
        artifact, artifact_integrity = load_v38_artifact(artifact_path)
    except Exception as exc:
        artifact = {}
        artifact_integrity = {"valid": False, "errors": [str(exc)]}
        errors.append(f"V3.8 artifact invalid: {exc}")
    try:
        validation = run_v38_validation()
    except Exception as exc:
        validation = {"overall_pass": False, "checks": {}, "error": str(exc)}
        errors.append(f"V3.8 scientific validation failed: {exc}")

    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    ledger = artifact.get("elementary_resource_ledger") or {}
    n40 = artifact.get("n40_admission") or {}
    coverage = n40.get("coverage_counts_out_of_8") or {}
    ui_text = ""
    readme_text = ""
    try:
        ui_text = _contained_regular(release_root, UI_PATH).read_text(encoding="utf-8")
        readme_text = _contained_regular(release_root, README_PATH).read_text(encoding="utf-8")
    except Exception as exc:
        errors.append(f"Integration surface unreadable: {exc}")
    checks = {
        "freeze_self_hash_is_exact": bool(
            freeze and freeze.get("freeze_contract_sha256") == _freeze_semantic(freeze)
        ),
        "frozen_inventory_count_and_path_fingerprint_are_exact": bool(
            freeze.get("frozen_file_count") == EXPECTED_FROZEN_FILE_COUNT
            and len(frozen_files) == EXPECTED_FROZEN_FILE_COUNT
            and path_fingerprint == EXPECTED_V38_PATH_FINGERPRINT
        ),
        "every_frozen_path_is_regular_contained_and_exact": bool(
            len(frozen_rows) == EXPECTED_FROZEN_FILE_COUNT and all(row["valid"] for row in frozen_rows)
        ),
        "all_v38_transition_paths_are_frozen": set(V38_PATHS).issubset(frozen_files),
        "v37_freeze_raw_and_semantic_identity_is_exact": bool(
            parent_raw == EXPECTED_V37_FREEZE_RAW_SHA256
            and parent_semantic == EXPECTED_V37_FREEZE_SHA256
            and parent_freeze.get("freeze_contract_sha256") == EXPECTED_V37_FREEZE_SHA256
        ),
        "all_97_immutable_v37_frozen_paths_are_preserved": immutable_parent_exact,
        "spec_raw_semantic_and_self_hash_are_exact": bool(
            spec_payload
            and raw_file_sha256(spec_path) == EXPECTED_V38_SPEC_RAW_SHA256
            and _spec_semantic(spec_payload) == EXPECTED_V38_SPEC_SHA256
            and spec_loaded.get("v38_spec_sha256") == EXPECTED_V38_SPEC_SHA256
        ),
        "artifact_raw_and_semantic_identity_match_freeze": bool(
            artifact_integrity.get("valid") is True
            and artifact.get("artifact_sha256")
            == canonical_json_sha256(
                {key: value for key, value in artifact.items() if key != "artifact_sha256"}
            )
            and _sha256(artifact_path)
            == frozen_files.get(
                "outputs/quantum_phase3/v38_elementary/SEALED_V3_8_ELEMENTARY_ADMISSION_ARTIFACT.json"
            )
        ),
        "artifact_parent_v37_raw_and_semantic_identity_is_exact": bool(
            (artifact.get("parent") or {}).get("v37_artifact_sha256") == EXPECTED_V37_ARTIFACT_SHA256
            and (artifact.get("parent") or {}).get("v37_artifact_raw_file_sha256") == EXPECTED_V37_ARTIFACT_RAW_SHA256
            and ((artifact.get("parent") or {}).get("authentication") or {}).get("valid") is True
        ),
        "scientific_validation_has_15_of_15_checks": bool(
            validation.get("overall_pass") is True
            and len(validation.get("checks") or {}) == 15
            and all((validation.get("checks") or {}).values())
        ),
        "selected_model_is_frozen_without_switching": bool(
            (artifact.get("decomposition_contract") or {}).get("selected_model")
            == "CLEAN_ANCILLA_TOFFOLI_LADDER_6CX_CCX_CRX2CX_V1"
            and (artifact.get("decomposition_contract") or {}).get("post_observation_candidate_switching")
            == "PROHIBITED"
        ),
        "prototype_elementary_ledger_is_exact": bool(
            ledger.get("logical_occurrence_count") == 40
            and ledger.get("one_qubit_gate_count") == 5_920
            and ledger.get("cnot_count") == 3_632
            and ledger.get("maximum_clean_ancilla_qubits") == 8
            and ledger.get("maximum_total_qubits") == 18
        ),
        "exhaustive_elementary_evidence_is_positive": bool(
            (artifact.get("elementary_validation") or {}).get("passed") is True
            and (artifact.get("elementary_validation") or {}).get("primitive_basis_beta_cases_checked") == 49_152
            and (artifact.get("elementary_validation") or {}).get("clean_ancilla_failures") == 0
        ),
        "n40_seed_and_seven_constraint_coverage_is_8_of_8": bool(
            len(n40.get("rows") or []) == 8
            and coverage.get("authenticated_seed_contract") == 8
            and coverage.get("seven_constraint_parent_evidence") == 8
            and coverage.get("classical_delta_equivalence") == 8
        ),
        "n40_missing_ir_cost_and_budget_fail_closed": bool(
            coverage.get("scalable_reversible_ir") == 0
            and coverage.get("selected_model_cnot_ledger") == 0
            and n40.get("maximum_selected_model_cnot") == "NOT_ESTIMATED"
            and n40.get("budget_gate") == "NOT_EVALUATED"
            and n40.get("admission_decision") == "BLOCKED_INCOMPLETE_REVERSIBLE_IR"
        ),
        "bounded_decision_and_next_gate_are_exact": bool(
            decisions.get("overall") == "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED"
            and decisions.get("next_falsifiable_gate")
            == "SCALABLE_N40_REVERSIBLE_ARITHMETIC_IR_AND_EIGHT_SEED_EQUIVALENCE"
        ),
        "provider_hardware_and_advantage_boundary_is_zero": bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v38_scientific_modules_have_provider_free_imports": all(
            _provider_free_imports(_contained_regular(release_root, relative))
            for relative in (
                "quantum_research_lab/phase3_v38_elementary_admission.py",
                "quantum_research_lab/phase3_v38_validation.py",
                "quantum_research_lab/phase3_v38_ui.py",
            )
        ),
        "ui_imports_and_renders_v38_after_v37": bool(
            "render_v38_elementary_admission_panel" in ui_text
            and ui_text.index("render_v38_elementary_admission_panel")
            > ui_text.index("render_v37_reversible_prototype_panel")
            and "load_v38_ui_artifact" in ui_text
        ),
        "readme_preserves_bounded_v38_decision": bool(
            "ELEMENTARY_PROTOTYPE_PASSED_N40_ADMISSION_BLOCKED" in readme_text
            and "N=40 selected-model CNOT: `NOT_ESTIMATED`" in readme_text
            and "quantum advantage are not claimed" in readme_text
        ),
        "deployment_contract_is_transactional_idempotent_and_rollback_capable": bool(
            (freeze.get("deployment_contract") or {}).get("idempotent_exact_reapply") == "NO_OP"
            and (freeze.get("deployment_contract") or {}).get("rollback_requires_preimage_hashes") is True
            and (freeze.get("deployment_contract") or {}).get("integration_surface_last") == UI_PATH
        ),
    }
    failed = [name for name, passed in checks.items() if passed is not True]
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
        "verifier": "QUANTUM LAB V3.8 RELEASE CHAIN · V1",
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.8 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_FROZEN_FILE_COUNT",
    "EXPECTED_V38_PATH_FINGERPRINT",
    "FREEZE_PATH",
    "V38_PATHS",
    "verify_release_chain",
]
