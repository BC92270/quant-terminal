"""Dependency-light validation ladder for V3.5 backend admission.

Every backend/calibration object in this file is a synthetic fixture.  It is
used to validate decision logic only and can never be sealed as provider
evidence or interpreted as a real backend observation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from .phase3_backend_admission import (
    BLOCKED,
    NOT_RUN,
    PASS,
    REJECTED,
    DEFAULT_ARTIFACT_NAME,
    admit_backend,
    attach_snapshot_digest,
    canonical_json_sha256,
    default_admission_root,
    load_v35_spec,
    validate_admission_artifact,
    verify_v34_parent,
)


VALIDATION_VERSION = "PHASE III · V3.5 BACKEND ADMISSION VALIDATION · V1"
FIXED_AS_OF = "2026-09-05T11:00:00+00:00"
SEALED_NEGATIVE_RESULT_AS_OF = "2026-09-05T09:52:00+00:00"


def validation_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def synthetic_snapshot_core() -> dict[str, Any]:
    """Return a clearly labelled non-provider test fixture."""

    return {
        "schema_version": "BACKEND_CALIBRATION_SNAPSHOT_V1",
        "backend": {
            "provider_id": "IBM_QUANTUM",
            "backend_name": "synthetic_qpu_127__NOT_A_REAL_BACKEND",
            "backend_version": "TEST_FIXTURE_ONLY",
            "operational": True,
            "status_msg": "active",
            "is_simulator": False,
            "num_qubits": 127,
            "basis_gates": ["rz", "sx", "x", "ecr"],
            "coupling_map": [[index, index + 1] for index in range(126)],
            "faulty_qubits": [],
            "faulty_edges": [],
        },
        "calibration": {
            "calibration_id": "SYNTHETIC_CALIBRATION_DO_NOT_SEAL",
            "captured_at_utc": "2026-09-05T10:00:00+00:00",
            "properties_last_update_utc": "2026-09-05T09:59:00+00:00",
            "two_qubit_gate_errors": [
                {"error": 0.00003, "gate": "ecr", "measured_at_utc": "2026-09-05T09:59:00+00:00", "qubits": [0, 1]},
                {"error": 0.00004, "gate": "ecr", "measured_at_utc": "2026-09-05T09:59:00+00:00", "qubits": [1, 2]},
                {"error": 0.00005, "gate": "ecr", "measured_at_utc": "2026-09-05T09:59:00+00:00", "qubits": [2, 3]},
            ],
        },
        "provenance": {
            "collector": "V3.5_SYNTHETIC_VALIDATION_FIXTURE",
            "evidence_class": "PROVIDER_EXPORT",
            "exported_at_utc": "2026-09-05T10:01:00+00:00",
            "source_record_id": "SYNTHETIC_TEST_VECTOR_DO_NOT_SEAL",
        },
        "test_fixture": True,
    }


def synthetic_snapshot() -> dict[str, Any]:
    return attach_snapshot_digest(synthetic_snapshot_core())


def synthetic_candidate() -> dict[str, Any]:
    parent = load_v35_spec()["parent_contract"][
        "expected_parent_v34_artifact_sha256"
    ]
    return {
        "candidate_id": "SYNTHETIC_ROUTED_CANDIDATE_DO_NOT_SEAL",
        "logical_qubits": 118,
        "parent_v34_artifact_sha256": parent,
        "rotations": {
            "aggregate_approximation_error": 1.56e-6,
            "continuous_rotation_count": 1560,
            "evidence_lane": "FAULT_TOLERANT_CLIFFORD_T",
            "max_approximation_error": 1e-9,
            "method": "SYNTHETIC_BOUNDED_APPROXIMATION_TEST_VECTOR",
            "status": "PASS",
            "synthesized_rotation_count": 1560,
        },
        "transpilation": {
            "backend_name": "synthetic_qpu_127__NOT_A_REAL_BACKEND",
            "input_artifact_sha256": parent,
            "approximation_degree": 1.0,
            "layout_method": "sabre",
            "optimization_level": 3,
            "routed_depth": 1000,
            "routed_two_qubit_gates": 100,
            "routed_width": 118,
            "routing_method": "sabre",
            "routing_seed": 11,
            "scheduling_method": "alap",
            "sdk_version": "SYNTHETIC_TEST_VECTOR",
            "status": "PASS",
            "target_basis_gates": ["rz", "sx", "x", "ecr"],
            "translation_method": "translator",
            "transpiler_version": "SYNTHETIC_TEST_VECTOR",
            "used_two_qubit_edges": [[0, 1], [1, 2]],
        },
    }


def _evaluate(
    snapshot: Mapping[str, Any] | None = None,
    candidate: Mapping[str, Any] | None = None,
    *,
    expected_digest: str | None = None,
) -> dict[str, Any]:
    snap = snapshot if snapshot is not None else synthetic_snapshot()
    routed = candidate if candidate is not None else synthetic_candidate()
    digest = (
        expected_digest
        if expected_digest is not None
        else (snap.get("snapshot_sha256") if isinstance(snap, Mapping) else None)
    )
    return admit_backend(
        snap,
        routed,
        expected_snapshot_sha256=digest,
        as_of_utc=FIXED_AS_OF,
    )


def run_backend_admission_validation() -> dict[str, Any]:
    spec = load_v35_spec()
    parent = verify_v34_parent(spec)
    nominal = _evaluate()
    nominal_states = {
        name: gate["state"] for name, gate in nominal["gates"].items()
    }
    expected_nominal_pass = {
        "v34_parent_binding",
        "snapshot_authentication",
        "backend_identity_and_provenance",
        "calibration_freshness",
        "candidate_parent_binding",
        "transpilation_metadata",
        "logical_width",
        "connected_capacity",
        "routed_width",
        "routed_depth",
        "routed_two_qubit_count",
        "calibration_two_qubit_error",
        "rotation_synthesis",
        "noise_aware_survival_proxy",
    }

    tampered_snapshot = synthetic_snapshot()
    tampered_snapshot["backend"]["num_qubits"] = 126
    tampered = _evaluate(tampered_snapshot)

    missing_pin = _evaluate(expected_digest="")

    stale_snapshot = synthetic_snapshot()
    stale_snapshot["calibration"]["captured_at_utc"] = "2026-09-01T10:00:00+00:00"
    stale_snapshot["calibration"]["properties_last_update_utc"] = "2026-09-01T09:59:00+00:00"
    for row in stale_snapshot["calibration"]["two_qubit_gate_errors"]:
        row["measured_at_utc"] = "2026-09-01T09:59:00+00:00"
    stale_snapshot["provenance"]["exported_at_utc"] = "2026-09-01T10:01:00+00:00"
    stale_snapshot = attach_snapshot_digest(stale_snapshot)
    stale = _evaluate(stale_snapshot)

    narrow_snapshot = synthetic_snapshot()
    narrow_snapshot["backend"]["num_qubits"] = 117
    narrow_snapshot["backend"]["coupling_map"] = [[0, 1], [1, 2], [2, 3]]
    narrow_snapshot = attach_snapshot_digest(narrow_snapshot)
    narrow = _evaluate(narrow_snapshot)

    deep_candidate = synthetic_candidate()
    deep_candidate["transpilation"]["routed_depth"] = 1_000_001
    deep = _evaluate(candidate=deep_candidate)

    large_candidate = synthetic_candidate()
    large_candidate["transpilation"]["routed_two_qubit_gates"] = 2_000_001
    large = _evaluate(candidate=large_candidate)

    noisy_snapshot = synthetic_snapshot()
    noisy_snapshot["calibration"]["two_qubit_gate_errors"][1]["error"] = 0.04
    noisy_snapshot = attach_snapshot_digest(noisy_snapshot)
    noisy = _evaluate(noisy_snapshot)

    missing_rotations = synthetic_candidate()
    missing_rotations["rotations"]["status"] = "NOT_RUN"
    rotations_not_run = _evaluate(candidate=missing_rotations)

    future_snapshot = synthetic_snapshot()
    future_snapshot["calibration"]["captured_at_utc"] = "2026-09-06T11:00:00+00:00"
    future_snapshot = attach_snapshot_digest(future_snapshot)
    future = _evaluate(future_snapshot)

    absent = admit_backend(
        None,
        None,
        expected_snapshot_sha256=None,
        as_of_utc=FIXED_AS_OF,
    )

    duplicate = _evaluate()
    integrity = validate_admission_artifact(nominal)
    modified = copy.deepcopy(nominal)
    modified["decisions"]["qpu_jobs_submitted"] = 1
    tamper_integrity = validate_admission_artifact(modified)

    provider_gate = nominal["gates"]["parent_provider_2q_gate_model_screen"]
    checks = {
        "spec_self_hash_and_research_boundary": bool(
            len(spec["v35_spec_sha256"]) == 64
            and spec["research_classification"] == "RESEARCH_ONLY"
            and spec["admission_scope"]["credential_access"] == "PROHIBITED"
            and spec["admission_scope"]["qpu_jobs_submitted"] == 0
        ),
        "frozen_v34_parent_exact": parent["state"] == PASS,
        "nominal_offline_metric_gates_pass": all(
            nominal_states.get(name) == PASS for name in expected_nominal_pass
        ),
        "provider_limit_is_independent_pretranspile_rejection": bool(
            provider_gate["state"] == REJECTED
            and provider_gate.get("stage") == "PRETRANSPILATION_MODEL_SCREEN"
            and provider_gate["observed"]["selected_ccx_model_cnot_count"]
            == 149_405_532_710
            and provider_gate["budget"]["maximum_two_qubit_gates_per_circuit"] == 5_000_000
            and nominal["decisions"]["offline_backend_admission"].startswith(
                "REJECTED"
            )
        ),
        "snapshot_tamper_blocks": tampered["gates"]["snapshot_authentication"]["state"]
        == BLOCKED,
        "missing_out_of_band_pin_blocks": missing_pin["gates"][
            "snapshot_authentication"
        ]["state"]
        == BLOCKED,
        "stale_calibration_rejected": stale["gates"]["calibration_freshness"]["state"]
        == REJECTED,
        "insufficient_width_rejected": narrow["gates"]["logical_width"]["state"]
        == REJECTED,
        "excess_depth_rejected": deep["gates"]["routed_depth"]["state"] == REJECTED,
        "excess_routed_2q_rejected": large["gates"]["routed_two_qubit_count"]["state"]
        == REJECTED,
        "excess_2q_error_rejected": noisy["gates"]["calibration_two_qubit_error"][
            "state"
        ]
        == REJECTED,
        "missing_rotation_synthesis_not_run": rotations_not_run["gates"][
            "rotation_synthesis"
        ]["state"]
        == NOT_RUN,
        "future_calibration_blocks": future["gates"]["calibration_freshness"]["state"]
        == BLOCKED,
        "absent_bundle_fails_closed_and_retains_provider_negative": bool(
            absent["gates"]["snapshot_authentication"]["state"] == BLOCKED
            and absent["gates"]["transpilation_metadata"]["state"] == NOT_RUN
            and absent["gates"]["parent_provider_2q_gate_model_screen"]["state"]
            == REJECTED
            and absent["decisions"]["hardware_execution"] == "BLOCKED · ZERO JOBS"
        ),
        "artifact_is_deterministic_and_self_authenticating": bool(
            nominal["artifact_sha256"] == duplicate["artifact_sha256"]
            and integrity["valid"]
            and not tamper_integrity["valid"]
        ),
        "zero_job_boundary_is_immutable": bool(
            nominal["claim_boundary"]["credentials_read"] is False
            and nominal["claim_boundary"]["provider_session_opened"] is False
            and nominal["claim_boundary"]["network_calls"] == 0
            and nominal["claim_boundary"]["qpu_submission_enabled"] is False
            and nominal["claim_boundary"]["qpu_jobs_submitted"] == 0
            and nominal["decisions"]["quantum_advantage"] == "NOT_CLAIMED"
        ),
    }
    detail = {
        "absent_bundle_decision": absent["decisions"],
        "nominal_artifact_sha256": nominal["artifact_sha256"],
        "nominal_decision": nominal["decisions"],
        "nominal_gate_states": nominal_states,
        "provider_pretranspile_gate": provider_gate,
        "runtime_inventory": nominal["runtime_inventory"],
    }
    # Only deterministic scientific logic is covered by this manifest. Runtime
    # inventory and the nominal artifact byte identity are diagnostics: they
    # legitimately differ between the release build and a Codespace replay.
    manifest_core = {
        "checks": checks,
        "spec_sha256": spec["v35_spec_sha256"],
        "validation_source_sha256": validation_source_sha256(),
        "validation_version": VALIDATION_VERSION,
    }
    return {
        **manifest_core,
        "detail": detail,
        "overall_pass": all(checks.values()),
        "validation_manifest_sha256": canonical_json_sha256(manifest_core),
    }


def build_sealed_negative_result(
    *, evaluated_at_utc: str = SEALED_NEGATIVE_RESULT_AS_OF
) -> dict[str, Any]:
    """Build the canonical no-snapshot V3.5 negative result.

    The scientific artifact contains no synthetic backend fixture. Synthetic
    inputs are confined to the decision-logic validation ladder embedded as
    software evidence.
    """

    artifact = admit_backend(
        None,
        None,
        expected_snapshot_sha256=None,
        as_of_utc=evaluated_at_utc,
    )
    core = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    ladder = run_backend_admission_validation()
    core["validation_ladder"] = ladder
    passed_checks = sum(bool(value) for value in ladder["checks"].values())
    total_checks = len(ladder["checks"])
    core["release_evidence"] = {
        "decision_logic_validation": f"{passed_checks} / {total_checks} PASS",
        "model_screen_result": "REJECTED_MODEL_SCREEN",
        "real_backend_snapshot_included": False,
        "routed_candidate_included": False,
        "synthetic_fixture_in_scientific_artifact": False,
        "validation_manifest_sha256": ladder["validation_manifest_sha256"],
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def seal_negative_result(
    root: str | Path | None = None,
    *,
    evaluated_at_utc: str = SEALED_NEGATIVE_RESULT_AS_OF,
) -> dict[str, Any]:
    """Atomically write the canonical V3.5 negative-result artifact."""

    output_root = Path(root) if root is not None else default_admission_root()
    output_root.mkdir(parents=True, exist_ok=True)
    target = output_root / DEFAULT_ARTIFACT_NAME
    artifact = build_sealed_negative_result(evaluated_at_utc=evaluated_at_utc)
    encoded = json.dumps(
        artifact,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=output_root
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    integrity = validate_admission_artifact(artifact)
    if not integrity.get("valid"):
        raise ValueError("; ".join(integrity.get("errors") or []))
    return {
        "artifact": artifact,
        "path": str(target),
        "raw_file_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "validation_manifest_sha256": artifact["validation_ladder"][
            "validation_manifest_sha256"
        ],
    }


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate V3.5 offline backend admission.")
    parser.parse_args(argv)
    report = run_backend_admission_validation()
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if report["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "FIXED_AS_OF",
    "SEALED_NEGATIVE_RESULT_AS_OF",
    "VALIDATION_VERSION",
    "build_sealed_negative_result",
    "run_backend_admission_validation",
    "seal_negative_result",
    "synthetic_candidate",
    "synthetic_snapshot",
    "synthetic_snapshot_core",
    "validation_source_sha256",
]
