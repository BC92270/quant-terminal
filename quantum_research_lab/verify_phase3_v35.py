"""Independent release-chain verifier for Quantum Lab V3.5.

The verifier is deliberately provider-free. It authenticates the V3.4 parent,
the two declared UI/documentation successors, the V3.5
specification/source/artifact chain, the deterministic decision-logic ladder
and the zero-job negative result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_backend_admission import (
    BLOCKED,
    NOT_RUN,
    PASS,
    REJECTED,
    canonical_json_sha256,
    load_admission_artifact,
    load_v35_spec,
    source_sha256,
)
from .phase3_v35_validation import (
    run_backend_admission_validation,
    validation_source_sha256,
)
from .phase3_v34_validation import (
    verify_v33_freeze_snapshot,
    verify_v33_parent_chain,
)
from .verify_phase3_v34 import verify_release_chain as verify_v34_release_chain


VERIFY_VERSION = "QUANTUM LAB V3.5 RELEASE CHAIN VERIFIER · V1"
V34_FROZEN_FILE_COUNT = 29
V34_FROZEN_UI_PATH = "quantum_research_lab/ui.py"
V34_FROZEN_UI_SHA256 = (
    "2ab26702f0066574136eee0e93a46121a1273fee3d2d6a3c9354139e0aa27684"
)
V34_FROZEN_README_PATH = "quantum_research_lab/README.md"
V34_FROZEN_README_SHA256 = (
    "71fef3671ea39be013cba54ad263d7d58ff45485909357b3a463de16f67189ac"
)
V34_SUPERSEDED_FILES = (V34_FROZEN_README_PATH, V34_FROZEN_UI_PATH)
MODEL_CNOT_COUNT = 149_405_532_710
IBM_TWO_QUBIT_GATE_LIMIT = 5_000_000
MODEL_LIMIT_RATIO = 29_881.106542
IBM_JOB_LIMITS_URL = "https://quantum.cloud.ibm.com/docs/en/guides/job-limits"
IBM_SOURCE_CHECKED_UTC = "2026-09-05T09:50:26Z"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve(root: Path, value: str | Path | None, default: str) -> Path:
    path = Path(value) if value is not None else Path(default)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _validation_manifest_core(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "checks": payload.get("checks") or {},
        "spec_sha256": payload.get("spec_sha256"),
        "validation_source_sha256": payload.get("validation_source_sha256"),
        "validation_version": payload.get("validation_version"),
    }


def _v34_successor_report(root: Path, freeze_path: Path) -> dict[str, Any]:
    """Verify the frozen V3.4 inventory after its one authorized UI successor."""

    errors: list[str] = []
    try:
        freeze = _read_json(freeze_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "errors": [str(exc)],
            "file_results": {},
            "freeze": {},
            "immutable_files_exact": False,
            "inventory_exact": False,
            "self_hash_exact": False,
            "successor_transition_authorized": False,
        }

    freeze_core = {
        key: value for key, value in freeze.items() if key != "freeze_contract_sha256"
    }
    files = freeze.get("frozen_files") or {}
    file_results: dict[str, dict[str, Any]] = {}
    immutable_valid = True
    for relative, expected in sorted(files.items()):
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
            actual = _sha256(target)
        except (OSError, ValueError) as exc:
            actual = None
            errors.append(f"{relative}: {exc}")
        superseded = relative in V34_SUPERSEDED_FILES
        valid = bool(actual == expected) if not superseded else True
        if not superseded and not valid:
            immutable_valid = False
        file_results[relative] = {
            "actual_sha256": actual,
            "expected_sha256": expected,
            "superseded_by_v35": superseded,
            "valid_under_successor_policy": valid,
        }

    ui_row = file_results.get(V34_FROZEN_UI_PATH) or {}
    readme_row = file_results.get(V34_FROZEN_README_PATH) or {}
    current_ui_sha = ui_row.get("actual_sha256")
    current_readme_sha = readme_row.get("actual_sha256")
    successor_transition_authorized = bool(
        files.get(V34_FROZEN_UI_PATH) == V34_FROZEN_UI_SHA256
        and files.get(V34_FROZEN_README_PATH) == V34_FROZEN_README_SHA256
        and current_ui_sha
        and current_ui_sha != V34_FROZEN_UI_SHA256
        and current_readme_sha
        and current_readme_sha != V34_FROZEN_README_SHA256
        and (root / V34_FROZEN_UI_PATH).is_file()
        and (root / V34_FROZEN_README_PATH).is_file()
    )
    return {
        "errors": errors,
        "file_results": file_results,
        "freeze": freeze,
        "freeze_raw_file_sha256": _sha256(freeze_path),
        "immutable_files_exact": bool(immutable_valid and len(files) == V34_FROZEN_FILE_COUNT),
        "inventory_exact": bool(
            len(files) == V34_FROZEN_FILE_COUNT
            and all(relative in files for relative in V34_SUPERSEDED_FILES)
            and sum(relative not in V34_SUPERSEDED_FILES for relative in files) == 27
        ),
        "self_hash_exact": bool(
            freeze.get("freeze_contract_sha256") == canonical_json_sha256(freeze_core)
        ),
        "successor_transition_authorized": successor_transition_authorized,
    }


def verify_release_chain(
    root: str | Path,
    *,
    v35_artifact_path: str | Path | None = None,
    v34_freeze_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the complete V3.5 release-chain verification without provider access."""

    release_root = Path(root).resolve()
    artifact_path = _resolve(
        release_root,
        v35_artifact_path,
        "outputs/quantum_phase3/backend_admission/"
        "SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json",
    )
    freeze_path = _resolve(
        release_root, v34_freeze_path, "FREEZE_CONTRACT_V3_4.json"
    )
    errors: list[str] = []

    try:
        spec = load_v35_spec(
            release_root
            / "quantum_research_lab"
            / "PHASE_III_BACKEND_ADMISSION_SPEC_V1.json"
        )
    except Exception as exc:
        spec = {}
        errors.append(f"V3.5 specification: {exc}")
    try:
        artifact, artifact_integrity = load_admission_artifact(artifact_path)
    except Exception as exc:
        artifact = {}
        artifact_integrity = {"valid": False, "errors": [str(exc)]}
    try:
        live_validation = run_backend_admission_validation()
    except Exception as exc:
        live_validation = {"overall_pass": False, "checks": {}, "errors": [str(exc)]}
    try:
        v34_successor = _v34_successor_report(release_root, freeze_path)
    except Exception as exc:
        v34_successor = {
            "errors": [str(exc)],
            "freeze": {},
            "immutable_files_exact": False,
            "inventory_exact": False,
            "self_hash_exact": False,
            "successor_transition_authorized": False,
        }

    v34_freeze = v34_successor.get("freeze") or {}
    v34_paths = v34_freeze.get("release_paths") or {}
    try:
        v34_release = verify_v34_release_chain(
            release_root / v34_paths["v31_parent"],
            release_root / v34_paths["v32_parent"],
            release_root / v34_paths["v33_parent"],
            release_root / v34_paths["v33_freeze"],
            release_root / v34_paths["v34_artifact"],
        )
    except Exception as exc:
        v34_release = {"valid": False, "checks": {}, "errors": [str(exc)]}
    try:
        v33_parent = verify_v33_parent_chain(
            release_root / v34_paths["v31_parent"],
            release_root / v34_paths["v32_parent"],
            release_root / v34_paths["v33_parent"],
        )
        v33_successor_freeze = verify_v33_freeze_snapshot(
            release_root,
            release_root / v34_paths["v33_freeze"],
            parent_report=v33_parent,
            superseded_files=V34_SUPERSEDED_FILES,
        )
    except Exception as exc:
        v33_successor_freeze = {
            "valid": False,
            "checks": {},
            "errors": [str(exc)],
        }

    embedded_ladder = artifact.get("validation_ladder") or {}
    embedded_manifest_core = _validation_manifest_core(embedded_ladder)
    model_gate = (artifact.get("gates") or {}).get(
        "parent_provider_2q_gate_model_screen"
    ) or {}
    model_observed = model_gate.get("observed") or {}
    model_budget = model_gate.get("budget") or {}
    model_evidence = model_gate.get("evidence") or {}
    release_evidence = artifact.get("release_evidence") or {}
    input_commitments = artifact.get("input_commitments") or {}
    backend = artifact.get("backend") or {}
    calibration = artifact.get("calibration") or {}
    compilation = artifact.get("compilation") or {}
    decisions = artifact.get("decisions") or {}
    boundary = artifact.get("claim_boundary") or {}
    parents = artifact.get("parents") or {}
    gates = artifact.get("gates") or {}
    downstream = {
        name: gate
        for name, gate in gates.items()
        if name not in {"v34_parent_binding", "parent_provider_2q_gate_model_screen"}
    }
    parent_contract = spec.get("parent_contract") or {}
    provider_screen = spec.get("provider_execution_screen") or {}
    spec_core = {
        key: value
        for key, value in spec.items()
        if key not in {"v35_spec_sha", "v35_spec_sha256"}
    }

    core_source_path = release_root / "quantum_research_lab" / "phase3_backend_admission.py"
    try:
        source_text = core_source_path.read_text(encoding="utf-8")
    except OSError as exc:
        source_text = ""
        errors.append(f"V3.5 core source: {exc}")
    banned_runtime_actions = (
        "from qiskit",
        "import qiskit",
        "QiskitRuntimeService",
        "save_account(",
        "least_busy(",
    )

    checks = {
        "v35_spec_self_hash_live": bool(
            spec
            and spec.get("v35_spec_sha256") == canonical_json_sha256(spec_core)
            and spec.get("v35_spec_sha")
            == canonical_json_sha256(spec_core)[:20].upper()
        ),
        "v35_artifact_internal_integrity": bool(artifact_integrity.get("valid")),
        "v35_core_source_commitment_live": bool(
            (artifact.get("source_commitments") or {}).get(
                "backend_admission_source_sha256"
            )
            == source_sha256()
            == (_sha256(core_source_path) if core_source_path.is_file() else None)
        ),
        "v35_validation_source_commitment_live": bool(
            embedded_ladder.get("validation_source_sha256")
            == validation_source_sha256()
        ),
        "embedded_validation_manifest_self_hash": bool(
            embedded_ladder.get("validation_manifest_sha256")
            == canonical_json_sha256(embedded_manifest_core)
            == release_evidence.get("validation_manifest_sha256")
        ),
        "live_validation_manifest_reproduced": bool(
            live_validation.get("validation_manifest_sha256")
            == embedded_ladder.get("validation_manifest_sha256")
        ),
        "embedded_validation_ladder_16_of_16": bool(
            embedded_ladder.get("overall_pass") is True
            and len(embedded_ladder.get("checks") or {}) == 16
            and all(bool(value) for value in (embedded_ladder.get("checks") or {}).values())
        ),
        "live_validation_ladder_16_of_16": bool(
            live_validation.get("overall_pass") is True
            and len(live_validation.get("checks") or {}) == 16
            and all(bool(value) for value in (live_validation.get("checks") or {}).values())
        ),
        "v34_release_chain_18_of_18_successor_aware": bool(
            len(v34_release.get("checks") or {}) == 18
            and all(
                bool(value)
                for name, value in (v34_release.get("checks") or {}).items()
                if name != "v33_freeze_5_of_5"
            )
            and v33_successor_freeze.get("valid")
            and len(v33_successor_freeze.get("checks") or {}) == 5
            and all(
                bool(value)
                for value in (v33_successor_freeze.get("checks") or {}).values()
            )
        ),
        "v34_freeze_self_hash_exact": bool(v34_successor.get("self_hash_exact")),
        "v34_frozen_inventory_29_files": bool(v34_successor.get("inventory_exact")),
        "v34_immutable_parent_files_27_exact": bool(
            v34_successor.get("immutable_files_exact")
        ),
        "v34_to_v35_declared_transitions_authorized": bool(
            v34_successor.get("successor_transition_authorized")
        ),
        "v34_parent_identities_exact": bool(
            (gates.get("v34_parent_binding") or {}).get("state") == PASS
            and parents.get("v34_artifact_sha256")
            == parent_contract.get("expected_parent_v34_artifact_sha256")
            and parents.get("v34_freeze_sha256")
            == parent_contract.get("expected_parent_v34_freeze_sha256")
            and input_commitments.get("parent_v34_artifact_sha256")
            == parent_contract.get("expected_parent_v34_artifact_sha256")
        ),
        "provider_model_screen_exact": bool(
            model_gate.get("state") == REJECTED
            and model_gate.get("stage") == "PRETRANSPILATION_MODEL_SCREEN"
            and model_observed.get("selected_ccx_model_cnot_count")
            == MODEL_CNOT_COUNT
            and model_budget.get("maximum_two_qubit_gates_per_circuit")
            == IBM_TWO_QUBIT_GATE_LIMIT
            and provider_screen.get("canonical_parent_selected_ccx_model_cnot_count")
            == MODEL_CNOT_COUNT
            and provider_screen.get("max_provider_two_qubit_gates_per_circuit")
            == IBM_TWO_QUBIT_GATE_LIMIT
        ),
        "provider_model_ratio_exact": bool(
            math.isclose(
                float(model_observed.get("multiple_of_limit", -1)),
                MODEL_LIMIT_RATIO,
                rel_tol=0.0,
                abs_tol=5e-7,
            )
            and math.isclose(
                MODEL_CNOT_COUNT / IBM_TWO_QUBIT_GATE_LIMIT,
                MODEL_LIMIT_RATIO,
                rel_tol=0.0,
                abs_tol=5e-7,
            )
        ),
        "provider_source_provenance_exact": bool(
            model_evidence.get("source_url") == IBM_JOB_LIMITS_URL
            and model_evidence.get("source_checked_utc") == IBM_SOURCE_CHECKED_UTC
            and model_evidence.get("source_retrieved_utc") == IBM_SOURCE_CHECKED_UTC
            and model_evidence.get("source_document_publication_utc")
            == "NOT_REPORTED_ON_PAGE"
        ),
        "no_snapshot_or_candidate_in_scientific_artifact": bool(
            input_commitments.get("snapshot_payload_sha256") is None
            and input_commitments.get("out_of_band_snapshot_sha256") is None
            and input_commitments.get("candidate_manifest_sha256") is None
            and (artifact.get("evidence") or {}).get("mode") == "NONE"
            and release_evidence.get("real_backend_snapshot_included") is False
            and release_evidence.get("routed_candidate_included") is False
        ),
        "backend_target_and_calibration_explicitly_absent": bool(
            backend.get("provider_id") is None
            and backend.get("backend_name") is None
            and backend.get("backend_version") is None
            and backend.get("class") == "UNKNOWN"
            and calibration.get("calibration_id") == "NOT_RECORDED"
            and compilation.get("stage") == "PROVIDER_NEUTRAL"
            and not compilation.get("basis_gates")
            and compilation.get("coupling_map_edges") == 0
        ),
        "downstream_evidence_fail_closed": bool(
            len(downstream) == 13
            and (gates.get("snapshot_authentication") or {}).get("state") == BLOCKED
            and all(
                (gate or {}).get("state") in {BLOCKED, NOT_RUN}
                for gate in downstream.values()
            )
            and decisions.get("downstream_evidence") == "BLOCKED_OR_NOT_RUN"
        ),
        "negative_result_and_synthetic_boundary_retained": bool(
            decisions.get("pretranspilation_model_screen")
            == "REJECTED_MODEL_SCREEN"
            and str(decisions.get("offline_backend_admission", "")).startswith(
                "REJECTED_MODEL_SCREEN"
            )
            and release_evidence.get("model_screen_result")
            == "REJECTED_MODEL_SCREEN"
            and release_evidence.get("synthetic_fixture_in_scientific_artifact")
            is False
        ),
        "provider_free_source_boundary": bool(
            source_text
            and not any(token in source_text for token in banned_runtime_actions)
            and (spec.get("admission_scope") or {}).get("submission_code") == "ABSENT"
            and (spec.get("admission_scope") or {}).get("credential_access")
            == "PROHIBITED"
        ),
        "zero_job_hardware_and_advantage_boundary": bool(
            boundary.get("provider_session_opened") is False
            and boundary.get("credentials_read") is False
            and boundary.get("network_calls") == 0
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("hardware_executable") is False
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            and decisions.get("hardware_execution") == "BLOCKED · ZERO JOBS"
            and decisions.get("qpu_submission") == "DISABLED"
            and decisions.get("qpu_jobs_submitted") == 0
            and decisions.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }

    errors.extend(str(item) for item in artifact_integrity.get("errors", []))
    errors.extend(str(item) for item in live_validation.get("errors", []))
    errors.extend(str(item) for item in v34_successor.get("errors", []))
    errors.extend(str(item) for item in v34_release.get("errors", []))
    errors.extend(str(item) for item in v33_successor_freeze.get("errors", []))
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "artifact_raw_file_sha256": (
            _sha256(artifact_path) if artifact_path.is_file() else None
        ),
        "artifact_sha256": artifact.get("artifact_sha256"),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "model_limit_ratio": model_observed.get("multiple_of_limit"),
        "provider_limit_source": model_evidence.get("source_url"),
        "valid": bool(all(checks.values()) and not errors),
        "validation_manifest_sha256": embedded_ladder.get(
            "validation_manifest_sha256"
        ),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the complete Quantum Lab V3.5 release chain."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--v34-freeze", type=Path)
    args = parser.parse_args(argv)
    report = verify_release_chain(
        args.root,
        v35_artifact_path=args.artifact,
        v34_freeze_path=args.v34_freeze,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "VERIFY_VERSION",
    "V34_FROZEN_README_PATH",
    "V34_FROZEN_README_SHA256",
    "V34_FROZEN_UI_PATH",
    "V34_FROZEN_UI_SHA256",
    "V34_SUPERSEDED_FILES",
    "verify_release_chain",
]
