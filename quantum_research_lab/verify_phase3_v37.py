"""Independent fail-closed release verifier for Quantum Lab V3.7.

The transition is rooted in the exact raw and semantic V3.6 freeze.  It also
captures the historical support closure that was present in the live tree but
was omitted from the V3.6 institutional archive.  Capturing those bytes in
V3.7 is additive and is not represented as a retroactive V3.6 freeze.

Every V3.7 scientific and integration surface is pinned to a release-time raw
or semantic SHA-256.  Any unresolved or malformed identity fails closed.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_v36_algorithmic_reduction import canonical_json_sha256
from .phase3_v37_reversible_compiler import (
    ARTIFACT_VERSION,
    EXPECTED_V36_ARTIFACT_RAW_SHA256,
    EXPECTED_V36_ARTIFACT_SHA256,
    validate_v37_artifact,
)


VERIFY_VERSION = "QUANTUM LAB V3.7 RELEASE CHAIN VERIFIER · V1"

V36_FREEZE_PATH = "FREEZE_CONTRACT_V3_6.json"
V36_FREEZE_RAW_SHA256 = "a297a23a6a253d378022fecd3890dd3ef014e75f6a16bcc38b94fcbf2ee1cd56"
V36_FREEZE_SEMANTIC_SHA256 = "8e7ea17da37878f6cd363273ca1a44ae8005740f37fd736524da3126813bd04a"
V36_FROZEN_PATHS_FINGERPRINT = (
    "8d62db5c4afcdf278a100e603143032c8fc3d45c45bc9d3c36d16c75abe84986"
)
README_PATH = "quantum_research_lab/README.md"
UI_PATH = "quantum_research_lab/ui.py"
V36_README_SHA256 = "c3ee7ba2ae1f83269eb13201a33f7f445cd015a0748f26c5347a4a41b14adc10"
V36_UI_SHA256 = "1cbf2571fdefdc88377cae45c141878c61ceddcd30078ed3a0f6d3fe555c927d"

V37_SPEC_PATH = "quantum_research_lab/PHASE_III_V3_7_REVERSIBLE_PROTOTYPE_SPEC_V1.json"
V37_ARTIFACT_PATH = (
    "outputs/quantum_phase3/v37_reversible/"
    "SEALED_V3_7_REVERSIBLE_PROTOTYPE_ARTIFACT.json"
)
V37_CORE_PATH = "quantum_research_lab/phase3_v37_reversible_compiler.py"
V37_VALIDATION_PATH = "quantum_research_lab/phase3_v37_validation.py"
V37_UI_MODULE_PATH = "quantum_research_lab/phase3_v37_ui.py"

V37_SPEC_RAW_SHA256 = "dd90f5177a2183da202df5c1d9e6b8e3b6d26a3cf63afadfa02530d5bceb6e68"
V37_SPEC_SHA256 = "69fd43383554108709960b145436304cc8b687104fd68dc3ffd713e1bcd1cf2c"
V37_ARTIFACT_RAW_SHA256 = "93c207a6c0d6723277bf682a678740b330a6a3127d59d63ce28a244bdf606365"
V37_ARTIFACT_SHA256 = "5773b8f38bd1400f4eb1edf5a016ab69c85fc794aefe31fd1a742d08174bee36"
V37_CORE_SHA256 = "320725f516ae6b9aa7388340a15cc3f4888eebcd1d111dc91fa6bfe751af0ff5"
V37_VALIDATION_SHA256 = "49386bf99b94c4f988fdaa7df9e42c4b2d8efe836565a6b6fdb0b8bff845bc8a"
V37_VALIDATION_MANIFEST_SHA256 = "f5169f5c82854ba7bae24f8f8c37854f19c6d309c96d287798ae42e898b0466c"
V37_UI_MODULE_SHA256 = "b6a8dbc206fed9a9cbca96533cac2204903ec118be39ec23aad0e01114d58f44"
V37_README_SHA256 = "d72c5801b08401fbb1785bc905764de7ae4434899ed9ce63c44601a1eba432a8"
V37_UI_SHA256 = "b1faa89c878f87d5c443582f3adb4aa430873e7f3e07c5869bc6da948a27b0d1"


V36_FROZEN_PATHS = frozenset(
    {
        "DEPLOY_V3_4.md",
        "DEPLOY_V3_5.md",
        "DEPLOY_V3_6.md",
        "FREEZE_CONTRACT_V3_1.json",
        "FREEZE_CONTRACT_V3_2.json",
        "FREEZE_CONTRACT_V3_3.json",
        "FREEZE_CONTRACT_V3_5.json",
        "SEALED_EXACT_DYADIC_BANDS_ORACLE.json",
        "app_v35_offline_harness.py",
        "app_v36_offline_harness.py",
        "install_quantum_lab_v34.py",
        "install_quantum_lab_v35.py",
        "install_quantum_lab_v36.py",
        "outputs/quantum_phase3/algorithmic_contract/SEALED_FEASIBLE_SUBSPACE_MIXER_ARTIFACT.json",
        "outputs/quantum_phase3/backend_admission/SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
        "outputs/quantum_phase3/gate_compiler/SEALED_GATE_COMPILER_ARTIFACT.json",
        "outputs/quantum_phase3/optimized_native/SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json",
        "outputs/quantum_phase3/v36_reduction/SEALED_V3_6_ALGORITHMIC_REDUCTION_ARTIFACT.json",
        "quantum_research_lab/PHASE_III_ALGORITHMIC_CONTRACT_SPEC_V1.json",
        "quantum_research_lab/PHASE_III_BACKEND_ADMISSION_SPEC_V1.json",
        "quantum_research_lab/PHASE_III_OPTIMIZED_NATIVE_SPEC_V1.json",
        "quantum_research_lab/PHASE_III_V3_6_ALGORITHMIC_REDUCTION_SPEC_V1.json",
        "quantum_research_lab/QUANTUM_LAB_V3_3_ARCHITECTURE.md",
        "quantum_research_lab/QUANTUM_LAB_V3_4_ARCHITECTURE.md",
        "quantum_research_lab/QUANTUM_LAB_V3_5_ARCHITECTURE.md",
        "quantum_research_lab/QUANTUM_LAB_V3_6_ARCHITECTURE.md",
        README_PATH,
        "quantum_research_lab/phase3_algorithmic_contract.py",
        "quantum_research_lab/phase3_algorithmic_validation.py",
        "quantum_research_lab/phase3_backend_admission.py",
        "quantum_research_lab/phase3_native_mixer.py",
        "quantum_research_lab/phase3_optimized_oracle.py",
        "quantum_research_lab/phase3_v34_ui.py",
        "quantum_research_lab/phase3_v34_validation.py",
        "quantum_research_lab/phase3_v35_ui.py",
        "quantum_research_lab/phase3_v35_validation.py",
        "quantum_research_lab/phase3_v36_algorithmic_reduction.py",
        "quantum_research_lab/phase3_v36_ui.py",
        "quantum_research_lab/phase3_v36_validation.py",
        "quantum_research_lab/test_phase3_algorithmic_contract.py",
        "quantum_research_lab/test_phase3_v34.py",
        "quantum_research_lab/test_phase3_v35.py",
        "quantum_research_lab/test_phase3_v36.py",
        "quantum_research_lab/test_phase3_v36_release.py",
        UI_PATH,
        "quantum_research_lab/verify_freeze_contract_v33.py",
        "quantum_research_lab/verify_freeze_contract_v34.py",
        "quantum_research_lab/verify_freeze_contract_v35.py",
        "quantum_research_lab/verify_freeze_contract_v36.py",
        "quantum_research_lab/verify_phase3_v33.py",
        "quantum_research_lab/verify_phase3_v33_ui.py",
        "quantum_research_lab/verify_phase3_v34.py",
        "quantum_research_lab/verify_phase3_v34_ui.py",
        "quantum_research_lab/verify_phase3_v35.py",
        "quantum_research_lab/verify_phase3_v35_ui.py",
        "quantum_research_lab/verify_phase3_v36.py",
        "quantum_research_lab/verify_phase3_v36_ui.py",
    }
)

# These files existed in the authenticated V3.6 live/source tree, but were not
# covered by its 57-path freeze.  The fixed hashes below capture their V3.7
# support-closure identity without rewriting V3.6 history.
V37_LEGACY_SUPPORT_SHA256 = {
    "FREEZE_CONTRACT_V3_4.json": "a2309c3ae551e74970c1c405ac106045f6db85bb2ba5cb87107a88fbfc7ccb12",
    "NEXT_PHASE_V3_2_GATE_LEVEL_COMPILER.md": "e915b18b02118cb290b08ccdef64cdf34cc794ecaac5ece0a92639fe327d90a1",
    "app_v34_fast_harness.py": "467eac32f5a994db49ef04376f0ce2169f2642c73d5d05e6506d6c112d1ee11b",
    "app_v34_harness.py": "639876189b08cda1397b37b81c7a26426205fd842d3cdee512df2849c18fc424",
    "baseline_phase3_v31.png": "fd885ae90fe4b717e05bf0891b60db8d699bd36835b744f0e450470f9b97c7d3",
    "quantum_research_lab/PHASE_III_BANDS_ORACLE_SPEC_V1.json": "a344857690fe3819fead3629e611865761712f3add3c45afc5c03011f11822ef",
    "quantum_research_lab/PHASE_III_DYADIC_BANDS_ORACLE_SPEC_V1.json": "aa1893c226f6f8a557f3945c218501f28ddc3624b5bcc3b9104cf53143299851",
    "quantum_research_lab/PHASE_III_GATE_COMPILER_SPEC_V1.json": "6e190e5752440998d4b5c3e5050702d9c2b016b20f13a8ff93afa1d9e9487c6d",
    "quantum_research_lab/PHASE_III_QPU_PREPARATION_SPEC_V1.json": "b04196d41195177e86aaf042e06ffb669d20e4b8a2ecf0d953cedc9d3091925d",
    "quantum_research_lab/PHASE_II_PREREGISTRATION_V1.json": "3b46bffc8631834bea755d423ec24d3e17f417975cef3d096b58b4d5ded2e465",
    "quantum_research_lab/QPU_OPTIONAL_REQUIREMENTS.txt": "581c039a010cf398275ff1f388f289384d9d974d85275b232fb761a36c424c21",
    "quantum_research_lab/QUANTUM_LAB_V3_2_ARCHITECTURE.md": "681690e42c8962a72a392647b788d5e20c7b182b0be1d759a61b8c57cd244f7c",
    "quantum_research_lab/QUBO_PHASEII_EXECUTION_SPEC_V1.json": "4ed11a390a23c73dc65b761eed72f25c9a4738739f865ffc6ec42d2070688001",
    "quantum_research_lab/__init__.py": "868af06f227f9e1a70bae235503185f93dc6989101e0dce3d2979fb97117205b",
    "quantum_research_lab/data.py": "96b40e82fa938f2f2c25f89d4f4c75c85f1c981a5115f38f8cb6e7735ef02449",
    "quantum_research_lab/engine.py": "70726d2933c195edd89d94acdceb2d3fbb2fa114701b3210c309ddf0135f1e70",
    "quantum_research_lab/evidence.py": "aec17335d00dea42f96b7c06a95ece32759b61ce4f92fc8e223f08a89c7d5443",
    "quantum_research_lab/experiments.py": "0f426875098e117ad2b7458eadf55023e9ad04cf18867dd4fa3fbd88ddb5032f",
    "quantum_research_lab/phase2_qhardness.py": "30c2cb35444afeeff669b9772d5577e89f32dbead762a09fb90fde70c9b653ce",
    "quantum_research_lab/phase3_artifact_guard.py": "d151f01c26854b2b3742e88eed54fd8b1b5adfddcc932ad97c5012d6fe03a010",
    "quantum_research_lab/phase3_bands_oracle.py": "f870fc0a5b372f48abd1532370a25292f6ac9d6318afaae2b739d55dd1fd1827",
    "quantum_research_lab/phase3_circuit_validation.py": "363f532f8c155bac6e702ebbe9afc8d2a82c155e3d9c11e5515d6abe1cc71252",
    "quantum_research_lab/phase3_dyadic_oracle.py": "843db34f4bb140f9ed4066bb044b1754d12820521c8ee603389bf031bdd3b2e0",
    "quantum_research_lab/phase3_gate_compiler.py": "b76001c8502eec962dc998d1c8ffa37b2886432149fb193f26e52d82cd348c78",
    "quantum_research_lab/phase3_qpu.py": "31b94a26a88c9b7c79f22ff8426cfd5b597250ac2a642dfb9b54b56dda0fb2e3",
    "quantum_research_lab/test_phase3_gate_compiler.py": "bb90bd5e8f7cdb17046c357ad1fc07644703b29a68bf73a92c5e9a3ea93563a8",
    "quantum_research_lab/verify_phase3_v32.py": "1e5d3f7dade335947cb82ff79ebfa0778cefc546f8639629b6439b7dd77c7924",
}

V37_ADDITIONAL_FROZEN_PATHS = frozenset(
    {
        "DEPLOY_V3_7.md",
        "app_v37_offline_harness.py",
        "install_quantum_lab_v37.py",
        V37_ARTIFACT_PATH,
        V37_SPEC_PATH,
        "quantum_research_lab/QUANTUM_LAB_V3_7_ARCHITECTURE.md",
        V37_CORE_PATH,
        V37_UI_MODULE_PATH,
        V37_VALIDATION_PATH,
        "quantum_research_lab/test_phase3_v37.py",
        "quantum_research_lab/test_phase3_v37_release.py",
        "quantum_research_lab/verify_freeze_contract_v37.py",
        "quantum_research_lab/verify_phase3_v37.py",
        "quantum_research_lab/verify_phase3_v37_ui.py",
    }
)

EXPECTED_V37_FROZEN_PATHS = frozenset(
    V36_FROZEN_PATHS
    | {V36_FREEZE_PATH}
    | set(V37_LEGACY_SUPPORT_SHA256)
    | V37_ADDITIONAL_FROZEN_PATHS
)

EXPECTED_VALIDATION_CHECKS = frozenset(
    {
        "v36_parent_semantic_and_raw_identity_exact",
        "fixture_is_registered_synthetic_n4_k2_only",
        "exact_k_and_feasible_state_cardinalities_are_exact",
        "differential_delta_and_predicate_ladder_passes",
        "transition_pair_inventory_is_exact",
        "full_10_qubit_domain_action_is_exhaustive",
        "compiled_two_level_action_and_adjoint_pass",
        "gray_compute_rotate_uncompute_restores_off_target_domain",
        "coherent_superposition_updates_portfolio_and_caches_together",
        "complete_layer_gram_and_reference_action_are_exhaustive",
        "complete_layer_preserves_feasible_consistent_support",
        "logical_resource_ledger_is_exact_and_deterministic",
        "elementary_and_n40_resource_claims_remain_blocked",
        "prototype_decision_is_narrow_and_positive",
        "provider_hardware_and_advantage_boundaries_fail_closed",
        "artifact_is_self_authenticating_and_tamper_evident",
        "four_coherent_transition_proofs_are_sealed",
        "spec_self_hash_fixture_and_boundaries_are_exact",
    }
)

EXPECTED_RELEASE_CHECKS = frozenset(
    {
        "assembly_placeholders_resolved",
        "v37_spec_self_hash_and_identity_exact",
        "v37_spec_boundary_exact",
        "v37_artifact_internal_integrity",
        "v37_artifact_raw_identity_exact",
        "v37_core_source_commitment_exact",
        "v37_validation_source_commitment_exact",
        "v37_validation_manifest_self_hash_exact",
        "v37_live_validation_reproduced",
        "v37_validation_gate_set_exact",
        "v36_freeze_raw_and_semantic_identity_exact",
        "v36_frozen_inventory_57_paths_exact",
        "v36_immutable_parent_files_55_exact",
        "legacy_support_snapshot_27_files_exact",
        "v36_predecessor_83_immutable_files_exact",
        "v36_to_v37_successor_pair_exact",
        "v36_parent_artifact_identities_exact",
        "v37_parent_binding_exact",
        "v37_fixture_and_register_contract_exact",
        "v37_compiler_action_evidence_exact",
        "v37_logical_resource_ledger_exact",
        "v37_scientific_decision_exact",
        "v37_production_and_elementary_lanes_blocked",
        "v37_zero_job_boundary_exact",
        "v37_network_and_credential_scope_exact",
        "v37_ui_source_binding_exact",
        "v37_readme_successor_binding_exact",
        "v37_provider_free_core_policy_exact",
        "v37_output_schema_exact",
        "v37_expected_frozen_inventory_is_99_paths",
    }
)


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


def _regular_contained(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"Unsafe release path: {relative!r}")
    release_root = root.resolve(strict=True)
    cursor = release_root
    for part in relative_path.parts:
        cursor = cursor / part
        mode = cursor.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Symlinked release path rejected: {relative}")
    if not stat.S_ISREG(cursor.lstat().st_mode):
        raise ValueError(f"Release path is not a regular file: {relative}")
    resolved = cursor.resolve(strict=True)
    resolved.relative_to(release_root)
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
            if key not in {"v37_spec_sha", "v37_spec_sha256"}
        }
    )


def _valid_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _assembly_constants() -> tuple[str, ...]:
    return (
        V37_SPEC_RAW_SHA256,
        V37_SPEC_SHA256,
        V37_ARTIFACT_RAW_SHA256,
        V37_ARTIFACT_SHA256,
        V37_CORE_SHA256,
        V37_VALIDATION_SHA256,
        V37_VALIDATION_MANIFEST_SHA256,
        V37_UI_MODULE_SHA256,
        V37_README_SHA256,
        V37_UI_SHA256,
    )


def _only_provider_free_imports(path: Path) -> bool:
    banned = {
        "aiohttp",
        "httpx",
        "qiskit",
        "qiskit_aer",
        "qiskit_ibm_runtime",
        "requests",
        "socket",
        "subprocess",
        "urllib",
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
    return not bool(roots & banned)


def classify_successor_pair(readme_sha256: str | None, ui_sha256: str | None) -> str:
    pair = (readme_sha256, ui_sha256)
    if pair == (V36_README_SHA256, V36_UI_SHA256):
        return "V3.6"
    if _valid_sha256(V37_README_SHA256) and _valid_sha256(V37_UI_SHA256):
        if pair == (V37_README_SHA256, V37_UI_SHA256):
            return "V3.7"
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

    freeze_path, v36_freeze = load(V36_FREEZE_PATH)
    spec_path, spec = load(V37_SPEC_PATH)
    artifact_path, artifact = load(V37_ARTIFACT_PATH)
    v36_frozen = v36_freeze.get("frozen_files") or {}

    immutable_v36: dict[str, bool] = {}
    if isinstance(v36_frozen, dict):
        for relative in sorted(V36_FROZEN_PATHS - {README_PATH, UI_PATH}):
            try:
                immutable_v36[relative] = (
                    _sha256(_regular_contained(release_root, relative))
                    == v36_frozen.get(relative)
                )
            except Exception as exc:
                errors.append(f"{relative}: {exc}")
                immutable_v36[relative] = False

    support_results: dict[str, bool] = {}
    for relative, expected in sorted(V37_LEGACY_SUPPORT_SHA256.items()):
        try:
            support_results[relative] = (
                _sha256(_regular_contained(release_root, relative)) == expected
            )
        except Exception as exc:
            errors.append(f"{relative}: {exc}")
            support_results[relative] = False

    try:
        readme_path = _regular_contained(release_root, README_PATH)
        ui_path = _regular_contained(release_root, UI_PATH)
        readme_sha = _sha256(readme_path)
        ui_sha = _sha256(ui_path)
    except Exception as exc:
        errors.append(f"Successor README/UI: {exc}")
        readme_path = ui_path = None
        readme_sha = ui_sha = None

    try:
        core_path = _regular_contained(release_root, V37_CORE_PATH)
        validation_path = _regular_contained(release_root, V37_VALIDATION_PATH)
        ui_module_path = _regular_contained(release_root, V37_UI_MODULE_PATH)
        ui_source = ui_path.read_text(encoding="utf-8") if ui_path else ""
        ui_module_source = ui_module_path.read_text(encoding="utf-8")
        readme_source = readme_path.read_text(encoding="utf-8") if readme_path else ""
    except Exception as exc:
        errors.append(f"V3.7 source surface: {exc}")
        core_path = validation_path = ui_module_path = None
        ui_source = ui_module_source = readme_source = ""

    try:
        from .phase3_v37_validation import run_v37_validation

        live_validation = run_v37_validation()
    except Exception as exc:
        errors.append(f"V3.7 live validation: {exc}")
        live_validation = {"overall_pass": False, "checks": {}, "detail": {}}
    validation_checks = live_validation.get("checks") or {}
    validation_core = {
        "checks": validation_checks,
        "detail": live_validation.get("detail") or {},
        "validation_source_sha256": live_validation.get("validation_source_sha256"),
        "validation_version": live_validation.get("validation_version"),
    }

    try:
        artifact_integrity = validate_v37_artifact(artifact)
    except Exception as exc:
        artifact_integrity = {"valid": False, "errors": [str(exc)]}
        errors.append(f"V3.7 artifact integrity: {exc}")

    fixture = artifact.get("fixture") or {}
    registers = artifact.get("register_contract") or {}
    compiler = artifact.get("compiler_evidence") or {}
    differential = artifact.get("differential_evidence") or {}
    ledger = artifact.get("resource_ledger") or {}
    totals = ledger.get("complete_edge_scan") or {}
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    parent = artifact.get("parent") or {}
    parent_auth = parent.get("authentication") or {}
    artifact_keys = {
        "artifact_sha256",
        "artifact_version",
        "claim_boundary",
        "coherent_transition_ledger",
        "compiler_evidence",
        "decisions",
        "differential_evidence",
        "fixture",
        "parent",
        "prototype_classification",
        "register_contract",
        "research_classification",
        "resource_ledger",
        "source_sha256",
        "spec_raw_file_sha256",
        "spec_sha256",
        "v37_version",
    }
    parent_fingerprint = hashlib.sha256(
        json.dumps(sorted(v36_frozen), separators=(",", ":")).encode("utf-8")
    ).hexdigest() if isinstance(v36_frozen, dict) else None
    spec_boundary = spec.get("claim_boundary") or {}
    spec_parent = spec.get("parent_contract") or {}
    transitions = artifact.get("coherent_transition_ledger") or {}
    transition_rows = transitions.get("rows") or []
    transition_core = {
        key: value
        for key, value in transitions.items()
        if key != "coherent_transition_ledger_sha256"
    }

    checks = {
        "assembly_placeholders_resolved": all(_valid_sha256(value) for value in _assembly_constants()),
        "v37_spec_self_hash_and_identity_exact": bool(
            spec
            and spec_path is not None
            and _valid_sha256(V37_SPEC_SHA256)
            and _valid_sha256(V37_SPEC_RAW_SHA256)
            and spec.get("v37_spec_sha256") == V37_SPEC_SHA256 == _spec_semantic(spec)
            and spec.get("v37_spec_sha") == V37_SPEC_SHA256[:20].upper()
            and _sha256(spec_path) == V37_SPEC_RAW_SHA256
        ),
        "v37_spec_boundary_exact": bool(
            spec.get("spec_version")
            == "QUANTUM LAB V3.7 REVERSIBLE INCREMENTAL-EXPOSURE PROTOTYPE · V1"
            and spec_parent.get("expected_v36_artifact_sha256") == EXPECTED_V36_ARTIFACT_SHA256
            and spec_parent.get("expected_v36_artifact_raw_file_sha256")
            == EXPECTED_V36_ARTIFACT_RAW_SHA256
            and spec_boundary.get("scope") == "REGISTERED_SYNTHETIC_N4_K2_FIXTURE_ONLY"
            and spec_boundary.get("production_n40_equivalence") == "NOT_CLAIMED"
            and spec_boundary.get("hardware_executable") is False
            and spec_boundary.get("qpu_jobs_submitted") == 0
            and spec_boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v37_artifact_internal_integrity": bool(
            artifact_integrity.get("valid") is True
            and artifact.get("artifact_sha256") == V37_ARTIFACT_SHA256
            and artifact.get("spec_sha256") == V37_SPEC_SHA256
            and artifact.get("spec_raw_file_sha256") == V37_SPEC_RAW_SHA256
        ),
        "v37_artifact_raw_identity_exact": bool(
            artifact_path is not None
            and _valid_sha256(V37_ARTIFACT_RAW_SHA256)
            and _sha256(artifact_path) == V37_ARTIFACT_RAW_SHA256
        ),
        "v37_core_source_commitment_exact": bool(
            core_path is not None
            and _valid_sha256(V37_CORE_SHA256)
            and _sha256(core_path) == V37_CORE_SHA256
            and artifact.get("source_sha256") == V37_CORE_SHA256
        ),
        "v37_validation_source_commitment_exact": bool(
            validation_path is not None
            and _valid_sha256(V37_VALIDATION_SHA256)
            and _sha256(validation_path) == V37_VALIDATION_SHA256
            and live_validation.get("validation_source_sha256") == V37_VALIDATION_SHA256
        ),
        "v37_validation_manifest_self_hash_exact": bool(
            _valid_sha256(V37_VALIDATION_MANIFEST_SHA256)
            and live_validation.get("validation_manifest_sha256")
            == canonical_json_sha256(validation_core)
            == V37_VALIDATION_MANIFEST_SHA256
        ),
        "v37_live_validation_reproduced": bool(
            live_validation.get("overall_pass") is True
            and (live_validation.get("detail") or {}).get("artifact_sha256")
            == V37_ARTIFACT_SHA256
        ),
        "v37_validation_gate_set_exact": bool(
            set(validation_checks) == EXPECTED_VALIDATION_CHECKS
            and all(value is True for value in validation_checks.values())
        ),
        "v36_freeze_raw_and_semantic_identity_exact": bool(
            freeze_path is not None
            and _sha256(freeze_path) == V36_FREEZE_RAW_SHA256
            and _freeze_semantic(v36_freeze) == V36_FREEZE_SEMANTIC_SHA256
            and v36_freeze.get("freeze_contract_sha256") == V36_FREEZE_SEMANTIC_SHA256
        ),
        "v36_frozen_inventory_57_paths_exact": bool(
            isinstance(v36_frozen, dict)
            and v36_freeze.get("frozen_file_count") == 57
            and len(v36_frozen) == 57
            and set(v36_frozen) == V36_FROZEN_PATHS
            and parent_fingerprint == V36_FROZEN_PATHS_FINGERPRINT
        ),
        "v36_immutable_parent_files_55_exact": bool(
            len(immutable_v36) == 55 and all(immutable_v36.values())
        ),
        "legacy_support_snapshot_27_files_exact": bool(
            len(support_results) == 27 and all(support_results.values())
        ),
        "v36_predecessor_83_immutable_files_exact": bool(
            len(immutable_v36) + len(support_results) + 1 == 83
            and all(immutable_v36.values())
            and all(support_results.values())
            and freeze_path is not None
            and _sha256(freeze_path) == V36_FREEZE_RAW_SHA256
        ),
        "v36_to_v37_successor_pair_exact": classify_successor_pair(readme_sha, ui_sha) == "V3.7",
        "v36_parent_artifact_identities_exact": bool(
            parent.get("v36_artifact_sha256") == EXPECTED_V36_ARTIFACT_SHA256
            and parent.get("v36_artifact_raw_file_sha256") == EXPECTED_V36_ARTIFACT_RAW_SHA256
        ),
        "v37_parent_binding_exact": bool(
            parent_auth.get("valid") is True
            and all(
                row.get("valid") is True
                for row in (parent_auth.get("comparisons") or {}).values()
            )
        ),
        "v37_fixture_and_register_contract_exact": bool(
            fixture.get("fixture_id") == "V37_SYNTHETIC_EXACT_K_N4_K2_V1"
            and fixture.get("classification") == "SYNTHETIC_COMPILER_FIXTURE · PROTOTYPE_ONLY"
            and fixture.get("n") == 4
            and fixture.get("k") == 2
            and registers.get("data_qubits") == 10
            and registers.get("ancilla_qubits") == 0
            and registers.get("full_domain_basis_states") == 1024
        ),
        "v37_compiler_action_evidence_exact": bool(
            compiler.get("passed") is True
            and compiler.get("basis_columns_checked") == 18_432
            and compiler.get("two_level_pair_beta_checks") == 12
            and compiler.get("complete_layer_basis_columns_checked") == 3_072
            and compiler.get("complete_layer_gram_entries_checked") == 3_145_728
            and compiler.get("complete_layer_maximum_action_error") == 0.0
            and compiler.get("complete_layer_maximum_norm_error") == 0.0
            and compiler.get("complete_layer_maximum_roundtrip_error") == 0.0
            and isinstance(compiler.get("complete_layer_maximum_gram_error"), (int, float))
            and compiler.get("complete_layer_maximum_gram_error") <= 1e-12
            and differential.get("passed") is True
            and differential.get("portfolio_edge_cases") == 36
            and differential.get("constraint_row_cases") == 72
            and transitions.get("transition_count") == 4
            and len(transition_rows) == 4
            and all(
                row.get("reference_action_state") == "PASSED_ALL_REGISTERED_BETAS"
                and row.get("roundtrip_state")
                == "PASSED_ALL_1024_BASIS_COLUMNS_PER_BETA"
                and row.get("off_target_identity_state") == "PASSED"
                and row.get("clean_scratch_state")
                == "PASSED_ZERO_ANCILLA_ZERO_SCRATCH"
                for row in transition_rows
            )
            and transitions.get("coherent_transition_ledger_sha256")
            == canonical_json_sha256(transition_core)
        ),
        "v37_logical_resource_ledger_exact": bool(
            totals.get("edge_count") == 6
            and totals.get("two_level_pair_count") == 4
            and totals.get("pattern_mcx_count") == 36
            and totals.get("pattern_mcrx_count") == 4
            and totals.get("logical_gate_count") == 40
            and totals.get("maximum_control_count") == 9
            and ledger.get("elementary_basis_decomposition") == "NOT_IMPLEMENTED"
            and ledger.get("selected_model_cnot") == "NOT_ESTIMATED"
        ),
        "v37_scientific_decision_exact": bool(
            decisions.get("overall") == "SMALL_INSTANCE_REVERSIBLE_PROTOTYPE_PASSED"
            and decisions.get("incremental_exposure_prototype")
            == "PASSED_ON_REGISTERED_N4_K2_FIXTURE"
            and decisions.get("coherent_cache_update") == "PASSED_EXHAUSTIVE_SMALL_INSTANCE"
            and decisions.get("scratch_cleanup") == "PASSED_ZERO_ANCILLA_GRAY_UNCOMPUTE"
        ),
        "v37_production_and_elementary_lanes_blocked": bool(
            decisions.get("production_n40_compiler") == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions.get("n40_rewrite_admission") == "N40_REWRITE_ADMISSION_BLOCKED"
            and decisions.get("elementary_basis_decomposition") == "BLOCKED_NOT_BUILT"
            and decisions.get("selected_model_budget") == "NOT_EVALUATED"
            and decisions.get("backend_native") == "NOT_RUN_PROVIDER_FREE_PHASE"
            and decisions.get("next_falsifiable_gate")
            == "ELEMENTARY_BASIS_DECOMPOSITION_AND_N40_RESOURCE_LEDGER"
        ),
        "v37_zero_job_boundary_exact": bool(
            artifact.get("research_classification") == "RESEARCH_ONLY"
            and artifact.get("prototype_classification") == "PROTOTYPE_ONLY"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
        "v37_network_and_credential_scope_exact": bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("provider_calls") == 0
            and boundary.get("backend_transpilation") == "NOT_RUN"
        ),
        "v37_ui_source_binding_exact": bool(
            ui_module_path is not None
            and ui_path is not None
            and _valid_sha256(V37_UI_MODULE_SHA256)
            and _valid_sha256(V37_UI_SHA256)
            and _sha256(ui_module_path) == V37_UI_MODULE_SHA256
            and _sha256(ui_path) == V37_UI_SHA256
            and "render_v37_reversible_prototype_panel" in ui_module_source
            and "render_v37_reversible_prototype_panel" in ui_source
        ),
        "v37_readme_successor_binding_exact": bool(
            readme_path is not None
            and _valid_sha256(V37_README_SHA256)
            and _sha256(readme_path) == V37_README_SHA256
            and "V3.7" in readme_source
        ),
        "v37_provider_free_core_policy_exact": bool(
            core_path is not None
            and validation_path is not None
            and _only_provider_free_imports(core_path)
            and _only_provider_free_imports(validation_path)
        ),
        "v37_output_schema_exact": bool(
            set(artifact) == artifact_keys
            and artifact.get("artifact_version") == ARTIFACT_VERSION
        ),
        "v37_expected_frozen_inventory_is_99_paths": bool(
            len(V36_FROZEN_PATHS) == 57
            and len(V37_LEGACY_SUPPORT_SHA256) == 27
            and len(V37_ADDITIONAL_FROZEN_PATHS) == 14
            and len(EXPECTED_V37_FROZEN_PATHS) == 99
        ),
    }
    if set(checks) != EXPECTED_RELEASE_CHECKS:
        errors.append("Internal release-check inventory drifted from its hard-coded contract.")
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "artifact_raw_file_sha256": _sha256(artifact_path) if artifact_path else None,
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "legacy_support_file_count": len(support_results),
        "release_check_count": len(checks),
        "valid": not failed and not errors and set(checks) == EXPECTED_RELEASE_CHECKS,
        "validation_manifest_sha256": live_validation.get("validation_manifest_sha256"),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Quantum Lab V3.7 release chain.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    report = verify_release_chain(args.root)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "EXPECTED_RELEASE_CHECKS",
    "EXPECTED_V37_FROZEN_PATHS",
    "README_PATH",
    "UI_PATH",
    "V36_FREEZE_RAW_SHA256",
    "V36_FREEZE_SEMANTIC_SHA256",
    "V36_FROZEN_PATHS",
    "V36_README_SHA256",
    "V36_UI_SHA256",
    "V37_ADDITIONAL_FROZEN_PATHS",
    "V37_LEGACY_SUPPORT_SHA256",
    "V37_README_SHA256",
    "V37_UI_SHA256",
    "VERIFY_VERSION",
    "_read_json_strict",
    "_regular_contained",
    "classify_successor_pair",
    "verify_release_chain",
]
