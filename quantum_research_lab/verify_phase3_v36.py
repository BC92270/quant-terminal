"""Independent, fail-closed release-chain verifier for Quantum Lab V3.6.

Trust begins with the exact raw V3.5 freeze, not with a predecessor verifier's
interpretation of successor files. JSON duplicate keys, paths outside the
release root, symlinks and mixed README/UI transition states are rejected.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import (
    canonical_json_sha256,
    validate_v36_artifact,
)
from .phase3_v36_validation import run_v36_validation
from .verify_phase3_v35 import verify_release_chain as verify_v35_release_chain


VERIFY_VERSION = "QUANTUM LAB V3.6 RELEASE CHAIN VERIFIER · V1"
V35_FREEZE_PATH = "FREEZE_CONTRACT_V3_5.json"
V35_FREEZE_RAW_SHA256 = "8d0a5ca3f37cf4c7a755537d55eb7b2a202bb72603527ec9f4f8fb7d1ba21f52"
V35_FREEZE_SEMANTIC_SHA256 = "efda21e201cd9ecc7b4fab7544c4c024a96b925dc39f977c17331a5278c994d2"
V35_README_PATH = "quantum_research_lab/README.md"
V35_UI_PATH = "quantum_research_lab/ui.py"
V35_README_SHA256 = "17e623716e33cb3ee7f862bcb52e1d772655db69b0182e9ea08537f43bef9db9"
V35_UI_SHA256 = "0f6cc9930f3b9ca7003b662e84e83ea78fbd6c79ecb6676c7fa0dc032a72b6eb"
V36_README_SHA256 = "c3ee7ba2ae1f83269eb13201a33f7f445cd015a0748f26c5347a4a41b14adc10"
V36_UI_SHA256 = "1cbf2571fdefdc88377cae45c141878c61ceddcd30078ed3a0f6d3fe555c927d"
V36_SPEC_PATH = "quantum_research_lab/PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json"
V36_SPEC_RAW_SHA256 = "44c308d468ab90c229be94b9d85a7fd8a0c0056beedde7982ffc5ce713f2016e"
V36_SPEC_SHA256 = "c13750ace7903d164db6ecef295414a3ad62e2e29d4c9f75b5d4a7be06c8cbdc"
V36_ARTIFACT_PATH = "outputs/quantum_phase3/v36_reduction/SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json"
V36_ARTIFACT_RAW_SHA256 = "147e81ebb891f61ec47dd9b46ab0adfc6a7a73e2e21f5b91e42d99b25de7c26c"
V36_ARTIFACT_SHA256 = "52b9b98a36bf8f6d661b42cdc63f3cc0f6476c207f273a171dcc0516c4c0a54d"
V36_CORE_PATH = "quantum_research_lab/phase3_v36_algorithmic_reduction.py"
V36_CORE_SHA256 = "bb97684465ceea1e45a62619dd3eb56e38e939d5254331f8355415a0528d76ac"
V36_VALIDATION_PATH = "quantum_research_lab/phase3_v36_validation.py"
V36_VALIDATION_SHA256 = "e2e4db70199dd626042c9c0e304fa0465ac64156289af8e38388bbe00b6764c0"
V36_VALIDATION_MANIFEST_SHA256 = "f7cedcc858862bd3ae83e683b256685e16f5958f34cd36b6a2cdbb0b52854364"
V36_UI_MODULE_PATH = "quantum_research_lab/phase3_v36_ui.py"
V36_UI_MODULE_SHA256 = "0483df7ba1c3972dd84272c5bab866f879fefa7e061f6bd94af211d47602c7cc"

V35_FROZEN_PATHS = frozenset(
    {
        "DEPLOY_V3_4.md",
        "DEPLOY_V3_5.md",
        "FREEZE_CONTRACT_V3_1.json",
        "FREEZE_CONTRACT_V3_2.json",
        "FREEZE_CONTRACT_V3_3.json",
        "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        "install_quantum_lab_v34.py",
        "install_quantum_lab_v35.py",
        "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json",
        "outputs/quantum_phase3/backend_admission/SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
        "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json",
        "outputs/quantum_phase3/optimized_native/SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json",
        "quantum_research_lab/PHASE_III_ALGORITHMIC_CONTRACT_SPEC_V1.json",
        "quantum_research_lab/PHASE_III_BACKEND_ADMISSION_SPEC_V1.json",
        "quantum_research_lab/PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
        "quantum_research_lab/QUANTUM_LAB_V3_3_ARCHITECTURE.md",
        "quantum_research_lab/QUANTUM_LAB_V3_4_ARCHITECTURE.md",
        "quantum_research_lab/QUANTUM_LAB_V3_5_ARCHITECTURE.md",
        V35_README_PATH,
        "quantum_research_lab/phase3_algorithmic_contract.py",
        "quantum_research_lab/phase3_algorithmic_validation.py",
        "quantum_research_lab/phase3_backend_admission.py",
        "quantum_research_lab/phase3_native_mixer.py",
        "quantum_research_lab/phase3_optimized_oracle.py",
        "quantum_research_lab/phase3_v34_ui.py",
        "quantum_research_lab/phase3_v34_validation.py",
        "quantum_research_lab/phase3_v35_ui.py",
        "quantum_research_lab/phase3_v35_validation.py",
        "quantum_research_lab/test_phase3_algorithmic_contract.py",
        "quantum_research_lab/test_phase3_v34.py",
        "quantum_research_lab/test_phase3_v35.py",
        V35_UI_PATH,
        "quantum_research_lab/verify_freeze_contract_v33.py",
        "quantum_research_lab/verify_freeze_contract_v34.py",
        "quantum_research_lab/verify_freeze_contract_v35.py",
        "quantum_research_lab/verify_phase3_v33.py",
        "quantum_research_lab/verify_phase3_v33_ui.py",
        "quantum_research_lab/verify_phase3_v34.py",
        "quantum_research_lab/verify_phase3_v34_ui.py",
        "quantum_research_lab/verify_phase3_v35.py",
        "quantum_research_lab/verify_phase3_v35_ui.py",
    }
)

EXPECTED_VALIDATION_CHECKS = frozenset(
    {
        "spec_self_hash_and_provider_free_boundary",
        "v31_v34_v35_parent_chain_exact",
        "all_eight_cnot_equations_exact",
        "per_oracle_cnot_identities_exact",
        "oracle_range_and_pair_floor_exact",
        "provider_neutral_headroom_budget_rejects_pair_floor",
        "single_guard_scope_is_exactly_bounded",
        "incremental_delta_all_43680_rows_exact",
        "incremental_lane_remains_unadmitted",
        "changed_semantics_lanes_are_explicit",
        "topology_only_negative_result_retained",
        "artifact_deterministic_and_tamper_evident",
        "backend_hardware_advantage_fail_closed",
    }
)

EXPECTED_V35_RELEASE_CHECKS = frozenset(
    {
        "v35_spec_self_hash_live",
        "v35_artifact_internal_integrity",
        "v35_core_source_commitment_live",
        "v35_validation_source_commitment_live",
        "embedded_validation_manifest_self_hash",
        "live_validation_manifest_reproduced",
        "embedded_validation_ladder_16_of_16",
        "live_validation_ladder_16_of_16",
        "v34_release_chain_18_of_18_successor_aware",
        "v34_freeze_self_hash_exact",
        "v34_frozen_inventory_29_files",
        "v34_immutable_parent_files_27_exact",
        "v34_to_v35_declared_transitions_authorized",
        "v34_parent_identities_exact",
        "provider_model_screen_exact",
        "provider_model_ratio_exact",
        "provider_source_provenance_exact",
        "no_snapshot_or_candidate_in_scientific_artifact",
        "backend_target_and_calibration_explicitly_absent",
        "downstream_evidence_fail_closed",
        "negative_result_and_synthetic_boundary_retained",
        "provider_free_source_boundary",
        "zero_job_hardware_and_advantage_boundary",
    }
)

EXPECTED_RELEASE_CHECKS = frozenset(
    {
        "v36_spec_self_hash_exact",
        "v36_spec_schema_exact",
        "v36_artifact_internal_integrity",
        "v36_artifact_raw_identity_exact",
        "v36_core_source_commitment_exact",
        "v36_validation_source_commitment_exact",
        "v36_validation_manifest_self_hash_exact",
        "v36_live_validation_reproduced",
        "v36_validation_gate_set_exact",
        "v35_freeze_raw_and_semantic_identity_exact",
        "v35_frozen_inventory_41_paths_exact",
        "v35_immutable_parent_files_39_exact",
        "v35_to_v36_successor_pair_exact",
        "v35_release_chain_successor_aware_exact",
        "v35_parent_artifact_identities_exact",
        "v36_parent_binding_exact",
        "v36_scientific_decision_exact",
        "v36_gate_inventory_and_states_exact",
        "v36_decision_precedence_exact",
        "v36_input_commitments_exact",
        "v36_evidence_provenance_exact",
        "v36_no_synthetic_scientific_evidence",
        "v36_zero_job_boundary_exact",
        "v36_network_and_credential_claim_scope_exact",
        "v36_ui_source_binding_exact",
        "v36_readme_successor_binding_exact",
        "v36_provider_free_core_policy_exact",
        "v36_output_schema_exact",
    }
)


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key rejected: {key}")
        result[key] = value
    return result


def _read_json_strict(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicates
    )
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _regular_contained(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError(f"Absolute/empty release path rejected: {relative!r}")
    lexical = root / relative
    mode = lexical.lstat().st_mode
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ValueError(f"Release path is not a regular non-symlink file: {relative}")
    resolved = lexical.resolve(strict=True)
    resolved.relative_to(root.resolve(strict=True))
    return resolved


def _freeze_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {key: value for key, value in payload.items() if key != "freeze_contract_sha256"}
    )


def _spec_semantic(payload: Mapping[str, Any]) -> str:
    return canonical_json_sha256(
        {
            key: value
            for key, value in payload.items()
            if key not in {"v36_spec_sha", "v36_spec_sha256"}
        }
    )


def _only_provider_free_imports(path: Path) -> bool:
    banned_roots = {
        "qiskit",
        "qiskit_ibm_runtime",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "aiohttp",
    }
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return False
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return not bool(roots & banned_roots)


def classify_successor_pair(readme_sha256: str | None, ui_sha256: str | None) -> str:
    """Accept only the two coherent README/UI states in the transition graph."""

    pair = (readme_sha256, ui_sha256)
    if pair == (V35_README_SHA256, V35_UI_SHA256):
        return "V3.5"
    if pair == (V36_README_SHA256, V36_UI_SHA256):
        return "V3.6"
    return "INVALID"


def verify_release_chain(root: str | Path) -> dict[str, Any]:
    release_root = Path(root).resolve(strict=True)
    errors: list[str] = []

    def load(relative: str) -> tuple[Path | None, dict[str, Any]]:
        try:
            path = _regular_contained(release_root, relative)
            return path, _read_json_strict(path)
        except Exception as exc:
            errors.append(f"{relative}: {exc}")
            return None, {}

    freeze_path, v35_freeze = load(V35_FREEZE_PATH)
    spec_path, spec = load(V36_SPEC_PATH)
    artifact_path, artifact = load(V36_ARTIFACT_PATH)
    frozen_files = v35_freeze.get("frozen_files") or {}

    immutable_results: dict[str, bool] = {}
    if isinstance(frozen_files, dict):
        for relative in sorted(V35_FROZEN_PATHS - {V35_README_PATH, V35_UI_PATH}):
            try:
                immutable_results[relative] = (
                    _sha256(_regular_contained(release_root, relative))
                    == frozen_files.get(relative)
                )
            except Exception as exc:
                errors.append(f"{relative}: {exc}")
                immutable_results[relative] = False

    try:
        readme_sha = _sha256(_regular_contained(release_root, V35_README_PATH))
        ui_sha = _sha256(_regular_contained(release_root, V35_UI_PATH))
    except Exception as exc:
        errors.append(f"V3.6 successor surface: {exc}")
        readme_sha = ui_sha = None

    try:
        live_validation = run_v36_validation()
    except Exception as exc:
        errors.append(f"V3.6 live validation: {exc}")
        live_validation = {"overall_pass": False, "checks": {}}
    validation_checks = live_validation.get("checks") or {}
    validation_core = {
        "checks": validation_checks,
        "detail": live_validation.get("detail") or {},
        "spec_sha256": live_validation.get("spec_sha256"),
        "validation_source_sha256": live_validation.get("validation_source_sha256"),
        "validation_version": live_validation.get("validation_version"),
    }

    try:
        v35_release = verify_v35_release_chain(release_root)
    except Exception as exc:
        errors.append(f"V3.5 predecessor release: {exc}")
        v35_release = {"valid": False, "checks": {}}
    v35_release_checks = v35_release.get("checks") or {}

    spec_core_keys = {
        "acceptance_contract",
        "claim_boundary",
        "incremental_exposure_contract",
        "lane_contracts",
        "parent_contract",
        "phase",
        "preregistered_checks",
        "semantic_taxonomy",
        "self_hash_contract",
        "spec_version",
        "structural_cost_contract",
        "v36_spec_sha",
        "v36_spec_sha256",
    }
    artifact_keys = {
        "artifact_sha256",
        "artifact_version",
        "claim_boundary",
        "decisions",
        "guard_scope_proof",
        "incremental_exposure_audit",
        "parent_authentication",
        "parents",
        "research_classification",
        "rewrite_admission",
        "spec_sha256",
        "structural_cost_attribution",
        "v36_version",
    }
    artifact_integrity = validate_v36_artifact(artifact) if artifact else {"valid": False}
    parent_contract = spec.get("parent_contract") or {}
    parents = artifact.get("parents") or {}
    parent_auth = artifact.get("parent_authentication") or {}
    attribution = artifact.get("structural_cost_attribution") or {}
    summary = attribution.get("summary") or {}
    rows = attribution.get("rows") or []
    incremental = artifact.get("incremental_exposure_audit") or {}
    rewrite = artifact.get("rewrite_admission") or {}
    lanes = rewrite.get("lanes") or {}
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}

    expected_lanes = {
        "BACKEND_NATIVE",
        "BLOCK_COORDINATE",
        "FEASIBLE_SUPPORT_SINGLE_GUARD",
        "FROZEN_V34_IDENTITY",
        "INCREMENTAL_EXPOSURE_GUARD",
        "TOPOLOGY_ONLY_PRESERVE_OPERATOR",
        "TOPOLOGY_ONLY_PRUNED",
    }
    expected_parent_pairs = {
        "v31_raw_file_sha256": "expected_parent_v31_raw_file_sha256",
        "v34_artifact_sha256": "expected_parent_v34_artifact_sha256",
        "v34_artifact_raw_file_sha256": "expected_parent_v34_artifact_raw_file_sha256",
        "v35_artifact_sha256": "expected_parent_v35_artifact_sha256",
        "v35_artifact_raw_file_sha256": "expected_parent_v35_artifact_raw_file_sha256",
        "v35_freeze_sha256": "expected_parent_v35_freeze_sha256",
    }
    parent_pairs_exact = all(
        parents.get(artifact_key) == parent_contract.get(spec_key)
        for artifact_key, spec_key in expected_parent_pairs.items()
    )
    v35_artifact_relative = (
        "outputs/quantum_phase3/backend_admission/"
        "SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json"
    )
    try:
        v35_artifact_path = _regular_contained(release_root, v35_artifact_relative)
        v35_artifact = _read_json_strict(v35_artifact_path)
    except Exception as exc:
        errors.append(f"{v35_artifact_relative}: {exc}")
        v35_artifact_path = None
        v35_artifact = {}

    artifact_text_upper = json.dumps(artifact, sort_keys=True).upper()
    try:
        core_path = _regular_contained(release_root, V36_CORE_PATH)
        validation_path = _regular_contained(release_root, V36_VALIDATION_PATH)
        ui_module_path = _regular_contained(release_root, V36_UI_MODULE_PATH)
        main_ui_path = _regular_contained(release_root, V35_UI_PATH)
        readme_path = _regular_contained(release_root, V35_README_PATH)
        ui_source = main_ui_path.read_text(encoding="utf-8")
        v36_ui_source = ui_module_path.read_text(encoding="utf-8")
    except Exception as exc:
        errors.append(f"V3.6 source surface: {exc}")
        core_path = validation_path = ui_module_path = main_ui_path = readme_path = None
        ui_source = v36_ui_source = ""

    checks = {
        "v36_spec_self_hash_exact": bool(
            spec
            and spec.get("v36_spec_sha256") == V36_SPEC_SHA256 == _spec_semantic(spec)
            and spec.get("v36_spec_sha") == V36_SPEC_SHA256[:20].upper()
            and spec_path is not None
            and _sha256(spec_path) == V36_SPEC_RAW_SHA256
        ),
        "v36_spec_schema_exact": bool(set(spec) == spec_core_keys),
        "v36_artifact_internal_integrity": bool(
            artifact_integrity.get("valid") is True
            and artifact.get("artifact_sha256") == V36_ARTIFACT_SHA256
        ),
        "v36_artifact_raw_identity_exact": bool(
            artifact_path is not None and _sha256(artifact_path) == V36_ARTIFACT_RAW_SHA256
        ),
        "v36_core_source_commitment_exact": bool(
            core_path is not None and _sha256(core_path) == V36_CORE_SHA256
        ),
        "v36_validation_source_commitment_exact": bool(
            validation_path is not None
            and _sha256(validation_path) == V36_VALIDATION_SHA256
            and live_validation.get("validation_source_sha256") == V36_VALIDATION_SHA256
        ),
        "v36_validation_manifest_self_hash_exact": bool(
            live_validation.get("validation_manifest_sha256")
            == canonical_json_sha256(validation_core)
            == V36_VALIDATION_MANIFEST_SHA256
        ),
        "v36_live_validation_reproduced": bool(
            live_validation.get("overall_pass") is True
            and live_validation.get("detail", {}).get("artifact_sha256") == V36_ARTIFACT_SHA256
        ),
        "v36_validation_gate_set_exact": bool(
            set(validation_checks) == EXPECTED_VALIDATION_CHECKS
            and all(value is True for value in validation_checks.values())
        ),
        "v35_freeze_raw_and_semantic_identity_exact": bool(
            freeze_path is not None
            and _sha256(freeze_path) == V35_FREEZE_RAW_SHA256
            and _freeze_semantic(v35_freeze) == V35_FREEZE_SEMANTIC_SHA256
            and v35_freeze.get("freeze_contract_sha256") == V35_FREEZE_SEMANTIC_SHA256
        ),
        "v35_frozen_inventory_41_paths_exact": bool(
            isinstance(frozen_files, dict)
            and v35_freeze.get("frozen_file_count") == 41
            and len(frozen_files) == 41
            and set(frozen_files) == V35_FROZEN_PATHS
        ),
        "v35_immutable_parent_files_39_exact": bool(
            len(immutable_results) == 39
            and all(value is True for value in immutable_results.values())
        ),
        "v35_to_v36_successor_pair_exact": bool(
            classify_successor_pair(readme_sha, ui_sha) == "V3.6"
        ),
        "v35_release_chain_successor_aware_exact": bool(
            v35_release.get("valid") is True
            and set(v35_release_checks) == EXPECTED_V35_RELEASE_CHECKS
            and all(value is True for value in v35_release_checks.values())
        ),
        "v35_parent_artifact_identities_exact": bool(
            v35_artifact_path is not None
            and _sha256(v35_artifact_path)
            == parent_contract.get("expected_parent_v35_artifact_raw_file_sha256")
            and v35_artifact.get("artifact_sha256")
            == parent_contract.get("expected_parent_v35_artifact_sha256")
            and (v35_artifact.get("decisions") or {}).get("pretranspilation_model_screen")
            == "REJECTED_MODEL_SCREEN"
        ),
        "v36_parent_binding_exact": bool(
            parent_pairs_exact
            and parent_contract.get("expected_parent_v35_freeze_raw_file_sha256")
            == V35_FREEZE_RAW_SHA256
            and parent_contract.get("expected_parent_v35_freeze_sha256")
            == V35_FREEZE_SEMANTIC_SHA256
            and parent_auth.get("valid") is True
            and len(parent_auth.get("comparisons") or {}) == 15
            and all(
                row.get("valid") is True
                for row in (parent_auth.get("comparisons") or {}).values()
            )
        ),
        "v36_scientific_decision_exact": bool(
            decisions.get("overall") == "ARCHITECTURE_REWRITE_REQUIRED"
            and decisions.get("topology_only")
            == "REJECTED_WITHIN_FROZEN_V34_ARCHITECTURE"
            and decisions.get("incremental_exposure_guard")
            == "BLOCKED_PENDING_REVERSIBLE_COMPILER"
        ),
        "v36_gate_inventory_and_states_exact": bool(
            set(lanes) == expected_lanes
            and lanes.get("BACKEND_NATIVE", {}).get("admission_decision") == "NOT_RUN"
            and lanes.get("INCREMENTAL_EXPOSURE_GUARD", {}).get("admission_decision")
            == "BLOCKED"
            and lanes.get("INCREMENTAL_EXPOSURE_GUARD", {}).get("selected_model_cnot")
            == "NOT_ESTIMATED"
            and lanes.get("TOPOLOGY_ONLY_PRESERVE_OPERATOR", {}).get("admission_decision")
            == "REJECTED"
            and lanes.get("TOPOLOGY_ONLY_PRUNED", {}).get("semantic_classification")
            == "CHANGED_SEMANTICS"
            and lanes.get("BLOCK_COORDINATE", {}).get("inherit_v34_equivalence") is False
        ),
        "v36_decision_precedence_exact": bool(
            decisions.get("frozen_v34_architecture") == "REJECTED_SELECTED_MODEL_BUDGET"
            and decisions.get("backend_native") == "NOT_RUN_PROVIDER_FREE_PHASE"
            and decisions.get("global_impossibility") == "NOT_CLAIMED"
            and decisions.get("next_falsifiable_gate")
            == "CLEAN_REVERSIBLE_INCREMENTAL_EXPOSURE_COMPILER"
        ),
        "v36_input_commitments_exact": bool(
            artifact.get("spec_sha256") == V36_SPEC_SHA256
            and attribution.get("edge_count") == 780
            and attribution.get("oracle_calls") == 1562
            and attribution.get("per_edge_selected_model_cnot") == 28
            and len(rows) == 8
            and [row.get("seed") for row in rows]
            == [1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807]
            and all(row.get("reconstruction_exact") is True for row in rows)
        ),
        "v36_evidence_provenance_exact": bool(
            summary.get("required_compute_uncompute_pair_cnot_floor") == 184_191_414
            and summary.get("selected_model_budget_cnot") == 2_500_000
            and summary.get("pair_floor_multiple_of_budget") == 73.6765656
            and summary.get("pair_floor_exceeds_budget") is True
            and incremental.get("total_constraint_row_cases") == 43_680
            and incremental.get("total_swap_cases") == 6_240
            and incremental.get("passed") is True
        ),
        "v36_no_synthetic_scientific_evidence": bool(
            "SYNTHETIC" not in artifact_text_upper
            and "TEST_ONLY" not in artifact_text_upper
            and "FIXTURE" not in artifact_text_upper
            and "FAKE_BACKEND" not in artifact_text_upper
        ),
        "v36_zero_job_boundary_exact": bool(
            artifact.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v36_network_and_credential_claim_scope_exact": bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
            and lanes.get("BACKEND_NATIVE", {}).get("provider_calls") == 0
            and lanes.get("BACKEND_NATIVE", {}).get("qpu_jobs_submitted") == 0
        ),
        "v36_ui_source_binding_exact": bool(
            ui_module_path is not None
            and main_ui_path is not None
            and _sha256(ui_module_path) == V36_UI_MODULE_SHA256
            and _sha256(main_ui_path) == V36_UI_SHA256
            and "render_v36_algorithmic_reduction_panel" in ui_source
            and "Open named-backend transpilation lane" in v36_ui_source
            and "disabled=True" in v36_ui_source
        ),
        "v36_readme_successor_binding_exact": bool(
            readme_path is not None and _sha256(readme_path) == V36_README_SHA256
        ),
        "v36_provider_free_core_policy_exact": bool(
            core_path is not None
            and validation_path is not None
            and _only_provider_free_imports(core_path)
            and _only_provider_free_imports(validation_path)
        ),
        "v36_output_schema_exact": bool(
            set(artifact) == artifact_keys
            and artifact.get("artifact_version")
            == "PHASE III · V3.6 STRUCTURAL COST + REWRITE ADMISSION ARTIFACT · V1"
            and rewrite.get("budget_cnot") == 2_500_000
        ),
    }
    if set(checks) != EXPECTED_RELEASE_CHECKS:
        errors.append("Internal release-check inventory drifted from the hard-coded contract.")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(str(item) for item in v35_release.get("errors") or [])
    return {
        "artifact_raw_file_sha256": _sha256(artifact_path) if artifact_path else None,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "release_check_count": len(checks),
        "valid": not failed and not errors and set(checks) == EXPECTED_RELEASE_CHECKS,
        "validation_manifest_sha256": live_validation.get("validation_manifest_sha256"),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.6 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_RELEASE_CHECKS",
    "V35_FREEZE_RAW_SHA256",
    "V35_FREEZE_SEMANTIC_SHA256",
    "V35_FROZEN_PATHS",
    "V35_README_SHA256",
    "V35_UI_SHA256",
    "V36_README_SHA256",
    "V36_UI_SHA256",
    "VERIFY_VERSION",
    "classify_successor_pair",
    "verify_release_chain",
]
