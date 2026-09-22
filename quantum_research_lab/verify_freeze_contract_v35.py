"""Verify the Quantum Lab V3.5 immutable release freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from .phase3_backend_admission import canonical_json_sha256
from .verify_phase3_v35 import (
    IBM_JOB_LIMITS_URL,
    IBM_TWO_QUBIT_GATE_LIMIT,
    MODEL_CNOT_COUNT,
    MODEL_LIMIT_RATIO,
    V34_FROZEN_README_PATH,
    V34_FROZEN_README_SHA256,
    V34_FROZEN_UI_PATH,
    V34_FROZEN_UI_SHA256,
    V34_SUPERSEDED_FILES,
    verify_release_chain,
)


VERIFY_VERSION = "QUANTUM LAB V3.5 FREEZE CONTRACT VERIFIER · V1"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freeze_contract(
    root: str | Path,
    contract_path: str | Path,
) -> dict[str, Any]:
    release_root = Path(root).resolve()
    freeze_path = Path(contract_path)
    if not freeze_path.is_absolute():
        freeze_path = (release_root / freeze_path).resolve()
    try:
        payload = _read_json(freeze_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "checks": {"freeze_readable": False},
            "errors": [str(exc)],
            "failed_checks": ["freeze_readable"],
            "valid": False,
            "verifier_version": VERIFY_VERSION,
        }

    errors: list[str] = []
    core = {
        key: value for key, value in payload.items() if key != "freeze_contract_sha256"
    }
    computed_self_hash = canonical_json_sha256(core)
    frozen_files = payload.get("frozen_files") or {}
    file_results: dict[str, dict[str, Any]] = {}
    for relative, expected in sorted(frozen_files.items()):
        target = (release_root / relative).resolve()
        try:
            target.relative_to(release_root)
            actual = _sha256(target)
        except (OSError, ValueError) as exc:
            actual = None
            errors.append(f"{relative}: {exc}")
        file_results[relative] = {
            "actual_sha256": actual,
            "expected_sha256": expected,
            "valid": actual == expected,
        }

    paths = payload.get("release_paths") or {}
    try:
        release_report = verify_release_chain(
            release_root,
            v35_artifact_path=paths.get("v35_artifact"),
            v34_freeze_path=paths.get("v34_freeze"),
        )
    except Exception as exc:
        release_report = {"valid": False, "checks": {}, "errors": [str(exc)]}

    try:
        artifact_path = (release_root / paths["v35_artifact"]).resolve()
        artifact = _read_json(artifact_path)
        v34_freeze_path = (release_root / paths["v34_freeze"]).resolve()
        v34_freeze = _read_json(v34_freeze_path)
        spec_path = (
            release_root
            / "quantum_research_lab"
            / "PHASE_III_BACKEND_ADMISSION_SPEC_V1.json"
        )
        spec = _read_json(spec_path)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        artifact = {}
        v34_freeze = {}
        spec = {}
        artifact_path = release_root / "__missing_v35_artifact__"
        v34_freeze_path = release_root / "__missing_v34_freeze__"
        errors.append(str(exc))

    lineage = payload.get("lineage") or {}
    policy = payload.get("successor_policy") or {}
    boundary = payload.get("claim_boundary") or {}
    decisions = payload.get("scientific_decisions") or {}
    release_evidence = artifact.get("release_evidence") or {}
    model_gate = (artifact.get("gates") or {}).get(
        "parent_provider_2q_gate_model_screen"
    ) or {}
    model_observed = model_gate.get("observed") or {}
    model_budget = model_gate.get("budget") or {}
    model_evidence = model_gate.get("evidence") or {}
    artifact_boundary = artifact.get("claim_boundary") or {}
    input_commitments = artifact.get("input_commitments") or {}
    backend = artifact.get("backend") or {}
    validation_ladder = artifact.get("validation_ladder") or {}
    current_ui_sha = (
        _sha256(release_root / V34_FROZEN_UI_PATH)
        if (release_root / V34_FROZEN_UI_PATH).is_file()
        else None
    )
    current_readme_sha = (
        _sha256(release_root / V34_FROZEN_README_PATH)
        if (release_root / V34_FROZEN_README_PATH).is_file()
        else None
    )
    expected_release_checks = int(
        (payload.get("validation_targets") or {}).get("release_chain_checks", 0)
    )

    checks = {
        "freeze_self_hash": payload.get("freeze_contract_sha256")
        == computed_self_hash,
        "all_v35_frozen_files_present_and_exact": bool(file_results)
        and all(row["valid"] for row in file_results.values()),
        "release_chain_target_passes": bool(
            expected_release_checks > 0
            and release_report.get("valid")
            and len(release_report.get("checks") or {}) == expected_release_checks
            and all(bool(value) for value in (release_report.get("checks") or {}).values())
        ),
        "lineage_identities_exact": bool(
            lineage.get("v34_freeze_sha256")
            == v34_freeze.get("freeze_contract_sha256")
            and lineage.get("v34_freeze_raw_file_sha256")
            == (_sha256(v34_freeze_path) if v34_freeze_path.is_file() else None)
            and lineage.get("v34_artifact_sha256")
            == (artifact.get("parents") or {}).get("v34_artifact_sha256")
            and lineage.get("v35_spec_sha256") == spec.get("v35_spec_sha256")
            and lineage.get("v35_artifact_sha256") == artifact.get("artifact_sha256")
            and lineage.get("v35_artifact_raw_file_sha256")
            == (_sha256(artifact_path) if artifact_path.is_file() else None)
            and lineage.get("v35_validation_manifest_sha256")
            == validation_ladder.get("validation_manifest_sha256")
        ),
        "declared_successor_policy_exact": bool(
            policy.get("allowed_v34_superseded_files") == list(V34_SUPERSEDED_FILES)
            and policy.get("v34_frozen_ui_sha256") == V34_FROZEN_UI_SHA256
            and policy.get("v35_successor_ui_sha256") == current_ui_sha
            and policy.get("v34_frozen_readme_sha256")
            == V34_FROZEN_README_SHA256
            and policy.get("v35_successor_readme_sha256") == current_readme_sha
            and current_ui_sha
            and current_ui_sha != V34_FROZEN_UI_SHA256
            and current_readme_sha
            and current_readme_sha != V34_FROZEN_README_SHA256
        ),
        "provider_negative_result_exact": bool(
            decisions.get("backend_admission") == "REJECTED_MODEL_SCREEN"
            and decisions.get("provider_limit_source") == IBM_JOB_LIMITS_URL
            and decisions.get("selected_ccx_model_cnot_count") == MODEL_CNOT_COUNT
            and decisions.get("max_two_qubit_gates_per_circuit")
            == IBM_TWO_QUBIT_GATE_LIMIT
            and abs(float(decisions.get("multiple_of_limit", -1)) - MODEL_LIMIT_RATIO)
            <= 5e-7
            and model_gate.get("state") == "REJECTED"
            and model_observed.get("selected_ccx_model_cnot_count")
            == MODEL_CNOT_COUNT
            and model_budget.get("maximum_two_qubit_gates_per_circuit")
            == IBM_TWO_QUBIT_GATE_LIMIT
            and model_evidence.get("source_url") == IBM_JOB_LIMITS_URL
        ),
        "no_backend_snapshot_candidate_or_synthetic_evidence": bool(
            input_commitments.get("snapshot_payload_sha256") is None
            and input_commitments.get("candidate_manifest_sha256") is None
            and backend.get("backend_name") is None
            and release_evidence.get("real_backend_snapshot_included") is False
            and release_evidence.get("routed_candidate_included") is False
            and release_evidence.get("synthetic_fixture_in_scientific_artifact")
            is False
        ),
        "research_zero_job_boundary": bool(
            boundary.get("research_classification") == "RESEARCH_ONLY"
            and boundary.get("hardware_executable") is False
            and boundary.get("qpu_submission_enabled") is False
            and boundary.get("qpu_jobs_submitted") == 0
            and boundary.get("quantum_advantage") == "NOT_CLAIMED"
            and artifact_boundary.get("provider_session_opened") is False
            and artifact_boundary.get("credentials_read") is False
            and artifact_boundary.get("network_calls") == 0
            and artifact_boundary.get("qpu_submission_enabled") is False
            and artifact_boundary.get("qpu_jobs_submitted") == 0
            and artifact_boundary.get("hardware_executable") is False
            and artifact_boundary.get("quantum_advantage") == "NOT_CLAIMED"
        ),
    }
    errors.extend(str(item) for item in release_report.get("errors", []))
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "file_count": len(file_results),
        "file_results": file_results,
        "freeze_contract_sha256_computed": computed_self_hash,
        "freeze_contract_sha256_stored": payload.get("freeze_contract_sha256"),
        "release_checks": release_report.get("checks"),
        "valid": bool(all(checks.values()) and not errors),
        "verifier_version": VERIFY_VERSION,
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the V3.5 freeze contract.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--contract", type=Path, default=Path("FREEZE_CONTRACT_V3_5.json")
    )
    args = parser.parse_args(argv)
    report = verify_freeze_contract(args.root, args.contract)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["VERIFY_VERSION", "verify_freeze_contract"]
