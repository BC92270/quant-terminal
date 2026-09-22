"""Fail-closed, zero-job named-backend admission for Quantum Lab V3.5.

The module consumes files that were exported elsewhere.  It does not import a
provider client, read credentials, access the network, transpile a circuit, or
submit a job.  A snapshot is trusted only when its canonical SHA-256 digest is
also supplied out of band by the caller.  Passing admission therefore means
only that offline evidence satisfies the preregistered screening contract.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


BACKEND_ADMISSION_VERSION = "PHASE III · V3.5 NAMED BACKEND OFFLINE ADMISSION · V1"
ARTIFACT_VERSION = "PHASE III · V3.5 ZERO-JOB BACKEND ADMISSION ARTIFACT · V1"
SPEC_FILENAME = "PHASE_III_BACKEND_ADMISSION_SPEC_V1.json"
DEFAULT_ARTIFACT_NAME = "SEALED_BACKEND_ADMISSION_NEGATIVE_RESULT.json"

PASS = "PASS"
REJECTED = "REJECTED"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(payload: Any) -> bytes:
    """Strict deterministic JSON used by every V3.5 commitment."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def default_admission_root() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "quantum_phase3"
        / "backend_admission"
    )


def load_v35_spec(path: str | Path | None = None) -> dict[str, Any]:
    spec_path = Path(path) if path is not None else Path(__file__).with_name(SPEC_FILENAME)
    payload = json.loads(spec_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V3.5 specification must be a JSON object.")
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"v35_spec_sha", "v35_spec_sha256"}
    }
    digest = canonical_json_sha256(core)
    if payload.get("v35_spec_sha256") != digest:
        raise ValueError("V3.5 specification SHA-256 mismatch.")
    if payload.get("v35_spec_sha") != digest[:20].upper():
        raise ValueError("V3.5 specification short SHA mismatch.")
    scope = payload.get("admission_scope") or {}
    if payload.get("research_classification") != "RESEARCH_ONLY":
        raise ValueError("V3.5 specification must remain RESEARCH_ONLY.")
    if scope.get("credential_access") != "PROHIBITED":
        raise ValueError("V3.5 specification permits credential access.")
    if scope.get("hardware_execution") != "PROHIBITED":
        raise ValueError("V3.5 specification permits hardware execution.")
    if scope.get("qpu_jobs_submitted") != 0:
        raise ValueError("V3.5 specification reports a non-zero QPU job count.")
    return payload


def snapshot_payload(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact snapshot payload covered by the offline digest."""

    return {
        key: value
        for key, value in snapshot.items()
        if key not in {"authentication", "snapshot_sha256"}
    }


def snapshot_payload_sha256(snapshot: Mapping[str, Any]) -> str:
    return canonical_json_sha256(snapshot_payload(snapshot))


def attach_snapshot_digest(snapshot_core: Mapping[str, Any]) -> dict[str, Any]:
    """Attach a digest for export; this does not create out-of-band trust.

    The returned digest must still be pinned through an independent channel and
    passed as ``expected_snapshot_sha256`` during admission.
    """

    core = snapshot_payload(dict(snapshot_core))
    digest = canonical_json_sha256(core)
    return {
        **core,
        "authentication": {
            "method": "SHA256_PINNED_OUT_OF_BAND",
            "payload_sha256": digest,
        },
        "snapshot_sha256": digest,
    }


def _gate(
    state: str,
    reason: str,
    *,
    observed: Any = None,
    budget: Any = None,
    evidence: Any = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"state": state, "reason": reason}
    if observed is not None:
        result["observed"] = observed
    if budget is not None:
        result["budget"] = budget
    if evidence is not None:
        result["evidence"] = evidence
    return result


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def _as_of(value: str | datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware")
        return value.astimezone(timezone.utc)
    return _parse_utc(value)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _normalize_edge(value: Any, num_qubits: int | None = None) -> tuple[int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    left, right = value
    if isinstance(left, bool) or isinstance(right, bool):
        return None
    if not isinstance(left, int) or not isinstance(right, int) or left == right:
        return None
    if left < 0 or right < 0:
        return None
    if num_qubits is not None and (left >= num_qubits or right >= num_qubits):
        return None
    return (min(left, right), max(left, right))


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def _runtime_inventory() -> dict[str, Any]:
    """Inventory importability only; no provider package is imported."""

    qiskit = bool(importlib.util.find_spec("qiskit"))
    runtime = bool(importlib.util.find_spec("qiskit_ibm_runtime"))
    return {
        "inventory_scope": "CURRENT_PYTHON_PROCESS_BUILD_RUNTIME",
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "qiskit_available": qiskit,
        "qiskit_ibm_runtime_available": runtime,
        "credential_lookup": "NOT_PERFORMED",
        "provider_network_call": "NOT_PERFORMED",
        "backend_resolution": "NOT_RUN · OFFLINE SNAPSHOT ONLY",
        "local_transpilation_reproduction": (
            "AVAILABLE · NOT_INVOKED" if qiskit else "NOT_RUN · QISKIT ABSENT"
        ),
    }


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def verify_v34_parent(
    spec: Mapping[str, Any],
    *,
    artifact_path: str | Path | None = None,
    freeze_path: str | Path | None = None,
) -> dict[str, Any]:
    """Authenticate the frozen V3.4 parent without importing its heavy ladder."""

    root = Path(__file__).resolve().parents[1]
    artifact_file = (
        Path(artifact_path)
        if artifact_path is not None
        else root
        / "outputs"
        / "quantum_phase3"
        / "optimized_native"
        / "SEALED_OPTIMIZED_NATIVE_MIXER_ARTIFACT.json"
    )
    freeze_file = Path(freeze_path) if freeze_path is not None else root / "FREEZE_CONTRACT_V3_4.json"
    expected = spec.get("parent_contract") or {}
    errors: list[str] = []
    try:
        artifact_raw = hashlib.sha256(artifact_file.read_bytes()).hexdigest()
        artifact = _read_json_object(artifact_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _gate(BLOCKED, f"V3.4 artifact unavailable or invalid: {exc}")
    try:
        freeze_raw = hashlib.sha256(freeze_file.read_bytes()).hexdigest()
        freeze = _read_json_object(freeze_file)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _gate(BLOCKED, f"V3.4 freeze unavailable or invalid: {exc}")

    artifact_core = {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_sha256", "created_utc"}
    }
    artifact_semantic = canonical_json_sha256(artifact_core)
    freeze_core = {
        key: value for key, value in freeze.items() if key != "freeze_contract_sha256"
    }
    freeze_semantic = canonical_json_sha256(freeze_core)
    resources = artifact.get("resource_envelopes") or {}
    validation = artifact.get("validation") or {}
    construction = artifact.get("construction") or {}
    boundary = artifact.get("claim_boundary") or {}
    comparisons = {
        "artifact_raw": (
            artifact_raw,
            expected.get("expected_parent_v34_artifact_raw_file_sha256"),
        ),
        "artifact_semantic": (
            artifact.get("artifact_sha256"),
            expected.get("expected_parent_v34_artifact_sha256"),
        ),
        "artifact_semantic_recomputed": (
            artifact_semantic,
            expected.get("expected_parent_v34_artifact_sha256"),
        ),
        "freeze_raw": (
            freeze_raw,
            expected.get("expected_parent_v34_freeze_raw_file_sha256"),
        ),
        "freeze_semantic": (
            freeze.get("freeze_contract_sha256"),
            expected.get("expected_parent_v34_freeze_sha256"),
        ),
        "freeze_semantic_recomputed": (
            freeze_semantic,
            expected.get("expected_parent_v34_freeze_sha256"),
        ),
        "resource_manifest": (
            resources.get("resource_manifest_sha256"),
            expected.get("expected_parent_v34_resource_manifest_sha256"),
        ),
        "validation_manifest": (
            validation.get("validation_manifest_sha256"),
            expected.get("expected_parent_v34_validation_manifest_sha256"),
        ),
        "schedule": (
            construction.get("controlled_xy_schedule_sha256"),
            expected.get("expected_parent_v34_schedule_sha256"),
        ),
    }
    for label, (actual, wanted) in comparisons.items():
        if actual != wanted:
            errors.append(f"{label} mismatch")
    if boundary.get("hardware_executable") is not False:
        errors.append("V3.4 hardware boundary is not false")
    if boundary.get("qpu_submission_enabled") is not False:
        errors.append("V3.4 submission boundary is not false")
    if boundary.get("qpu_jobs_submitted") != 0:
        errors.append("V3.4 QPU job count is not zero")
    if validation.get("overall_pass") is not True:
        errors.append("V3.4 validation ladder is not passing")
    return _gate(
        PASS if not errors else BLOCKED,
        "Frozen V3.4 artifact and freeze are byte/semantic exact."
        if not errors
        else "; ".join(errors),
        observed={label: actual for label, (actual, _) in comparisons.items()},
    )


def _snapshot_authentication(
    snapshot: Mapping[str, Any] | None,
    expected_snapshot_sha256: str | None,
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(snapshot, Mapping):
        return _gate(BLOCKED, "No offline backend snapshot was supplied."), None
    try:
        computed = snapshot_payload_sha256(snapshot)
    except (TypeError, ValueError, OverflowError) as exc:
        return _gate(BLOCKED, f"Snapshot canonicalization failed: {exc}"), None
    auth = snapshot.get("authentication") or {}
    embedded = auth.get("payload_sha256")
    duplicate = snapshot.get("snapshot_sha256")
    expected = str(expected_snapshot_sha256 or "").lower()
    method = auth.get("method")
    if method != "SHA256_PINNED_OUT_OF_BAND":
        return _gate(
            BLOCKED,
            "Snapshot authentication method is absent or unsupported; no signature is inferred.",
            observed=method,
            budget="SHA256_PINNED_OUT_OF_BAND",
        ), computed
    if not _HEX_64.fullmatch(expected):
        return _gate(
            BLOCKED,
            "A valid caller-supplied out-of-band SHA-256 digest is required.",
            observed=expected_snapshot_sha256,
        ), computed
    if embedded != computed or duplicate != computed or expected != computed:
        return _gate(
            BLOCKED,
            "Snapshot digest does not match embedded and out-of-band commitments.",
            observed={
                "computed": computed,
                "embedded": embedded,
                "snapshot_sha256": duplicate,
                "out_of_band": expected,
            },
        ), computed
    return _gate(
        PASS,
        "Canonical snapshot digest matches both embedded and out-of-band commitments.",
        observed=computed,
    ), computed


def _identity_gate(
    snapshot: Mapping[str, Any] | None, spec: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Backend identity cannot be evaluated without a snapshot.")
    backend = snapshot.get("backend") or {}
    provenance = snapshot.get("provenance") or {}
    provider = _nonempty_string(backend.get("provider_id"))
    name = _nonempty_string(backend.get("backend_name"))
    version = _nonempty_string(backend.get("backend_version"))
    evidence_class = provenance.get("evidence_class")
    allowed = set((spec.get("admission_scope") or {}).get("allowed_evidence_classes") or [])
    allowed_providers = set(
        (spec.get("admission_scope") or {}).get("allowed_provider_ids") or []
    )
    required_strings = {
        "provider_id": provider,
        "backend_name": name,
        "backend_version": version,
        "status_msg": _nonempty_string(backend.get("status_msg")),
        "source_record_id": _nonempty_string(provenance.get("source_record_id")),
        "collector": _nonempty_string(provenance.get("collector")),
    }
    missing = sorted(key for key, value in required_strings.items() if value is None)
    if missing:
        return _gate(BLOCKED, f"Missing backend/provenance fields: {', '.join(missing)}.")
    if evidence_class not in allowed:
        return _gate(
            BLOCKED,
            "Snapshot evidence class is not allowed.",
            observed=evidence_class,
            budget=sorted(allowed),
        )
    if provider not in allowed_providers:
        return _gate(
            REJECTED,
            "Snapshot provider is outside this preregistered admission protocol.",
            observed=provider,
            budget=sorted(allowed_providers),
        )
    try:
        _parse_utc(provenance.get("exported_at_utc"))
    except (TypeError, ValueError) as exc:
        return _gate(BLOCKED, f"Invalid provenance export timestamp: {exc}")
    if backend.get("is_simulator") is not False:
        return _gate(REJECTED, "Named target must be a non-simulator backend.")
    if backend.get("operational") is not True:
        return _gate(REJECTED, "Snapshot reports that the named backend is not operational.")
    if str(backend.get("status_msg", "")).strip().lower() != "active":
        return _gate(
            REJECTED,
            "Snapshot backend status is not the preregistered active state.",
            observed=backend.get("status_msg"),
            budget="active",
        )
    num_qubits = _positive_int(backend.get("num_qubits"))
    basis = backend.get("basis_gates")
    coupling = backend.get("coupling_map")
    if num_qubits is None or not isinstance(basis, list) or not basis:
        return _gate(BLOCKED, "Backend qubit count or basis-gate inventory is invalid.")
    if not all(_nonempty_string(gate) is not None for gate in basis):
        return _gate(BLOCKED, "Backend basis-gate inventory contains invalid entries.")
    if not isinstance(coupling, list) or not coupling:
        return _gate(BLOCKED, "Backend coupling map is absent or empty.")
    edges = [_normalize_edge(edge, num_qubits) for edge in coupling]
    if any(edge is None for edge in edges):
        return _gate(BLOCKED, "Backend coupling map contains invalid qubit edges.")
    return _gate(
        PASS,
        "Named non-simulator backend identity and offline provenance are complete.",
        observed={
            "backend_name": name,
            "backend_version": version,
            "evidence_class": evidence_class,
            "num_qubits": num_qubits,
            "provider_id": provider,
        },
    )


def _parent_provider_gate_model_screen(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the frozen V3.4 CNOT model with IBM's 2Q gate limit.

    The V3.4 numerator is neither a lower bound nor a backend-native count.
    The comparison is an early model screen and must not be promoted to a
    transpiler measurement, runtime result or hardware-fidelity conclusion.
    """

    screen = spec.get("provider_execution_screen") or {}
    count = _positive_int(
        screen.get("canonical_parent_selected_ccx_model_cnot_count")
    )
    limit = _positive_int(screen.get("max_provider_two_qubit_gates_per_circuit"))
    evidence = {
        "comparison_rule": screen.get("comparison_rule"),
        "interpretation_boundary": screen.get("interpretation_boundary"),
        "provider_id": screen.get("provider_id"),
        "source_checked_utc": screen.get("source_checked_utc"),
        "source_document_publication_utc": screen.get(
            "source_document_publication_utc"
        ),
        "source_page_title": screen.get("source_page_title"),
        "source_retrieved_utc": screen.get("source_retrieved_utc"),
        "source_url": screen.get("source_url"),
    }
    if count is None or limit is None:
        return _gate(
            BLOCKED,
            "Provider two-qubit gate model screen is malformed.",
            evidence=evidence,
        )
    ratio = count / limit
    if count > limit:
        result = _gate(
            REJECTED,
            "PRETRANSPILATION MODEL SCREEN: frozen V3.4 selected-CCX CNOT accounting exceeds the documented IBM two-qubit gate limit per circuit.",
            observed={
                "selected_ccx_model_cnot_count": count,
                "multiple_of_limit": ratio,
            },
            budget={"maximum_two_qubit_gates_per_circuit": limit},
            evidence=evidence,
        )
        result["stage"] = "PRETRANSPILATION_MODEL_SCREEN"
        return result
    result = _gate(
        PASS,
        "Frozen V3.4 selected-CCX CNOT accounting is within the provider screen.",
        observed={
            "selected_ccx_model_cnot_count": count,
            "multiple_of_limit": ratio,
        },
        budget={"maximum_two_qubit_gates_per_circuit": limit},
        evidence=evidence,
    )
    result["stage"] = "PRETRANSPILATION_MODEL_SCREEN"
    return result


def _freshness_gate(
    snapshot: Mapping[str, Any] | None,
    as_of: datetime,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Calibration freshness cannot be evaluated without a snapshot.")
    calibration = snapshot.get("calibration") or {}
    provenance = snapshot.get("provenance") or {}
    if "calibration_id" not in calibration:
        return _gate(
            BLOCKED,
            "Calibration identity field is absent; a null value must still be explicit.",
        )
    try:
        captured = _parse_utc(calibration.get("captured_at_utc"))
        properties_updated = _parse_utc(
            calibration.get("properties_last_update_utc")
        )
        exported = _parse_utc(provenance.get("exported_at_utc"))
    except (TypeError, ValueError) as exc:
        return _gate(BLOCKED, f"Invalid calibration timestamp: {exc}")
    rows = calibration.get("two_qubit_gate_errors")
    if not isinstance(rows, list) or not rows:
        return _gate(NOT_RUN, "Calibration metric timestamps are unavailable.")
    try:
        metric_times = [_parse_utc(row.get("measured_at_utc")) for row in rows]
    except (AttributeError, TypeError, ValueError) as exc:
        return _gate(BLOCKED, f"Invalid per-metric calibration timestamp: {exc}")
    skew = float(budgets["future_clock_skew_seconds"])
    max_age = float(budgets["max_calibration_age_hours"])
    capture_to_export = (exported - captured).total_seconds()
    maximum_export_delay = float(budgets["max_snapshot_capture_to_export_seconds"])
    if capture_to_export < -skew or capture_to_export > maximum_export_delay:
        return _gate(
            BLOCKED,
            "Snapshot capture-to-export interval violates the preregistered window.",
            observed=capture_to_export,
            budget={"minimum_seconds": -skew, "maximum_seconds": maximum_export_delay},
        )
    timestamps = {
        "snapshot_capture": captured,
        "properties_last_update": properties_updated,
        **{f"metric_{index}": value for index, value in enumerate(metric_times)},
    }
    ages = {name: (as_of - value).total_seconds() for name, value in timestamps.items()}
    future = {name: age for name, age in ages.items() if age < -skew}
    if future:
        return _gate(
            BLOCKED,
            "Calibration evidence contains timestamps implausibly in the future.",
            observed=future,
            budget={"minimum_age_seconds": -skew},
        )
    ages_hours = {name: max(0.0, age / 3600.0) for name, age in ages.items()}
    oldest = max(ages_hours.values())
    if oldest > max_age:
        return _gate(
            REJECTED,
            "At least one used calibration timestamp is older than the preregistered limit.",
            observed={"oldest_age_hours": oldest, "ages_hours": ages_hours},
            budget={"max_age_hours": max_age},
        )
    return _gate(
        PASS,
        "Snapshot, properties and metric timestamps are within preregistered windows.",
        observed={
            "oldest_age_hours": oldest,
            "capture_to_export_seconds": capture_to_export,
            "calibration_id": calibration.get("calibration_id"),
        },
        budget={
            "max_age_hours": max_age,
            "max_capture_to_export_seconds": maximum_export_delay,
        },
    )


def _transpilation_status(candidate: Mapping[str, Any] | None) -> tuple[str, Mapping[str, Any]]:
    if not isinstance(candidate, Mapping):
        return NOT_RUN, {}
    transpilation = candidate.get("transpilation")
    if not isinstance(transpilation, Mapping):
        return NOT_RUN, {}
    status = str(transpilation.get("status", NOT_RUN)).upper()
    return status, transpilation


def _candidate_parent_gate(
    candidate: Mapping[str, Any] | None, spec: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return _gate(NOT_RUN, "No routed candidate manifest was supplied.")
    expected = (spec.get("parent_contract") or {}).get(
        "expected_parent_v34_artifact_sha256"
    )
    candidate_parent = candidate.get("parent_v34_artifact_sha256")
    transpilation = candidate.get("transpilation") or {}
    input_parent = transpilation.get("input_artifact_sha256")
    if candidate_parent != expected or input_parent != expected:
        return _gate(
            BLOCKED,
            "Candidate is not bound twice to the frozen V3.4 semantic identity.",
            observed={"candidate_parent": candidate_parent, "transpiler_input": input_parent},
            budget=expected,
        )
    candidate_id = _nonempty_string(candidate.get("candidate_id"))
    if candidate_id is None:
        return _gate(BLOCKED, "Candidate ID is missing.")
    return _gate(PASS, "Candidate and transpiler input are bound to frozen V3.4.", observed=candidate_id)


def _logical_width_gate(
    snapshot: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    required = int(budgets["required_logical_qubits"])
    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Logical width cannot be evaluated without a snapshot.")
    available = _positive_int((snapshot.get("backend") or {}).get("num_qubits"))
    claimed = _positive_int((candidate or {}).get("logical_qubits")) if isinstance(candidate, Mapping) else None
    if available is None:
        return _gate(BLOCKED, "Backend qubit capacity is invalid.")
    if claimed is None:
        return _gate(NOT_RUN, "Candidate logical width is missing.", observed=available, budget=required)
    if claimed != required:
        return _gate(
            BLOCKED,
            "Candidate logical width does not equal the frozen V3.4 maximum.",
            observed=claimed,
            budget=required,
        )
    if available < required:
        return _gate(
            REJECTED,
            "Backend has fewer physical qubits than the logical-width lower bound.",
            observed=available,
            budget={"minimum": required},
        )
    return _gate(
        PASS,
        "Raw backend width covers the frozen logical-width lower bound only.",
        observed=available,
        budget={"minimum": required},
    )


def _connected_capacity_gate(
    snapshot: Mapping[str, Any] | None,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    """Require one non-faulty connected component large enough for the circuit."""

    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Connected capacity cannot be evaluated without a snapshot.")
    backend = snapshot.get("backend") or {}
    num_qubits = _positive_int(backend.get("num_qubits"))
    coupling = backend.get("coupling_map")
    faulty_qubits = backend.get("faulty_qubits", [])
    faulty_edges = backend.get("faulty_edges", [])
    if num_qubits is None or not isinstance(coupling, list) or not coupling:
        return _gate(BLOCKED, "Connected-capacity topology is missing or invalid.")
    if not isinstance(faulty_qubits, list) or any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value >= num_qubits
        for value in faulty_qubits
    ):
        return _gate(BLOCKED, "Faulty-qubit inventory is invalid.")
    normalized_faulty_edges = {
        _normalize_edge(edge, num_qubits) for edge in faulty_edges
    } if isinstance(faulty_edges, list) else {None}
    if None in normalized_faulty_edges:
        return _gate(BLOCKED, "Faulty-edge inventory is invalid.")
    normalized_edges = [_normalize_edge(edge, num_qubits) for edge in coupling]
    if any(edge is None for edge in normalized_edges):
        return _gate(BLOCKED, "Coupling map contains invalid edges.")
    faulty = set(faulty_qubits)
    adjacency: dict[int, set[int]] = {
        qubit: set() for qubit in range(num_qubits) if qubit not in faulty
    }
    for edge in normalized_edges:
        assert edge is not None
        left, right = edge
        if edge in normalized_faulty_edges or left in faulty or right in faulty:
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)
    largest = 0
    unseen = set(adjacency)
    while unseen:
        stack = [unseen.pop()]
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            neighbors = adjacency[node].intersection(unseen)
            unseen.difference_update(neighbors)
            stack.extend(neighbors)
        largest = max(largest, size)
    required = int(budgets["required_logical_qubits"])
    if largest < required:
        return _gate(
            REJECTED,
            "Largest non-faulty connected component is below the logical-width requirement.",
            observed=largest,
            budget={"minimum_connected_qubits": required},
        )
    return _gate(
        PASS,
        "A non-faulty connected component covers the frozen logical width.",
        observed=largest,
        budget={"minimum_connected_qubits": required},
    )


def _routed_metric_gate(
    candidate: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
    *,
    field: str,
    label: str,
    maximum: int | None = None,
    minimum: int | None = None,
) -> dict[str, Any]:
    status, transpilation = _transpilation_status(candidate)
    if status == NOT_RUN:
        return _gate(NOT_RUN, f"{label} is unavailable because transpilation was not run.")
    if status != PASS:
        return _gate(BLOCKED, f"Transpilation status is {status}; {label} is not admissible.")
    value = _positive_int(transpilation.get(field))
    if value is None:
        return _gate(BLOCKED, f"{label} is missing or invalid.")
    if field == "routed_width" and isinstance(snapshot, Mapping):
        capacity = _positive_int((snapshot.get("backend") or {}).get("num_qubits"))
        if capacity is None:
            return _gate(BLOCKED, "Backend width is invalid.")
        if value > capacity:
            return _gate(
                REJECTED,
                "Routed width exceeds backend capacity.",
                observed=value,
                budget={"maximum_backend_width": capacity},
            )
    if minimum is not None and value < minimum:
        return _gate(
            BLOCKED,
            f"{label} is below the logical lower bound and is internally inconsistent.",
            observed=value,
            budget={"minimum": minimum},
        )
    if maximum is not None and value > maximum:
        return _gate(
            REJECTED,
            f"{label} exceeds the preregistered budget.",
            observed=value,
            budget={"maximum": maximum},
        )
    return _gate(
        PASS,
        f"{label} is within the preregistered budget.",
        observed=value,
        budget={
            **({"minimum": minimum} if minimum is not None else {}),
            **({"maximum": maximum} if maximum is not None else {}),
        },
    )


def _transpilation_metadata_gate(
    snapshot: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    status, transpilation = _transpilation_status(candidate)
    if status == NOT_RUN:
        return _gate(NOT_RUN, "Backend-native transpilation metadata is absent.")
    if status != PASS:
        return _gate(BLOCKED, f"Backend-native transpilation status is {status}.")
    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Transpilation target cannot be matched without a snapshot.")
    backend = snapshot.get("backend") or {}
    required_strings = ["backend_name", "input_artifact_sha256", "sdk_version", "transpiler_version"]
    missing = [field for field in required_strings if _nonempty_string(transpilation.get(field)) is None]
    if missing:
        return _gate(BLOCKED, f"Missing transpilation metadata: {', '.join(missing)}.")
    if transpilation.get("backend_name") != backend.get("backend_name"):
        return _gate(BLOCKED, "Transpilation target name differs from snapshot backend name.")
    protocol = (spec.get("confirmatory_protocol") or {}).get("transpilation") or {}
    optimization_level = _nonnegative_int(transpilation.get("optimization_level"))
    routing_seed = _nonnegative_int(transpilation.get("routing_seed"))
    approximation_degree = _finite_float(transpilation.get("approximation_degree"))
    if optimization_level is None or optimization_level > 3:
        return _gate(BLOCKED, "Transpilation optimization level is invalid.")
    if optimization_level != protocol.get("optimization_level"):
        return _gate(
            REJECTED,
            "Transpilation optimization level differs from the preregistration.",
            observed=optimization_level,
            budget=protocol.get("optimization_level"),
        )
    if routing_seed is None:
        return _gate(BLOCKED, "Transpilation routing seed is invalid.")
    if routing_seed not in set(protocol.get("routing_seeds") or []):
        return _gate(
            REJECTED,
            "Routing seed was not preregistered.",
            observed=routing_seed,
            budget=protocol.get("routing_seeds"),
        )
    if approximation_degree is None or not 0.0 <= approximation_degree <= 1.0:
        return _gate(BLOCKED, "Transpilation approximation degree is invalid.")
    if approximation_degree != float(protocol.get("approximation_degree", 1.0)):
        return _gate(
            REJECTED,
            "Transpilation approximation degree differs from the exact preregistration.",
            observed=approximation_degree,
            budget=protocol.get("approximation_degree"),
        )
    for field in (
        "layout_method",
        "routing_method",
        "translation_method",
        "scheduling_method",
    ):
        actual = _nonempty_string(transpilation.get(field))
        expected = protocol.get(field)
        if actual is None:
            return _gate(BLOCKED, f"Transpilation {field} is missing.")
        if actual != expected:
            return _gate(
                REJECTED,
                f"Transpilation {field} differs from the preregistration.",
                observed=actual,
                budget=expected,
            )
    target_basis = transpilation.get("target_basis_gates")
    backend_basis = set(backend.get("basis_gates") or [])
    if not isinstance(target_basis, list) or not target_basis:
        return _gate(BLOCKED, "Transpilation target basis is absent.")
    missing_basis = sorted(set(target_basis) - backend_basis)
    if missing_basis:
        return _gate(
            REJECTED,
            "Transpiled candidate uses gates outside the snapshot basis.",
            observed=missing_basis,
            budget=sorted(backend_basis),
        )
    used_edges = transpilation.get("used_two_qubit_edges")
    num_qubits = _positive_int(backend.get("num_qubits"))
    if not isinstance(used_edges, list) or not used_edges:
        return _gate(BLOCKED, "Transpilation used-edge inventory is absent.")
    normalized = [_normalize_edge(edge, num_qubits) for edge in used_edges]
    if any(edge is None for edge in normalized):
        return _gate(BLOCKED, "Transpilation used-edge inventory is invalid.")
    coupling = {_normalize_edge(edge, num_qubits) for edge in backend.get("coupling_map") or []}
    outside = sorted(edge for edge in set(normalized) if edge not in coupling)
    if outside:
        return _gate(REJECTED, "Transpilation uses edges outside the snapshot coupling map.", observed=outside)
    return _gate(
        PASS,
        "Transpiler version, seed, basis and used coupling edges are fully recorded.",
        observed={
            "approximation_degree": approximation_degree,
            "layout_method": transpilation.get("layout_method"),
            "optimization_level": optimization_level,
            "routing_method": transpilation.get("routing_method"),
            "routing_seed": routing_seed,
            "scheduling_method": transpilation.get("scheduling_method"),
            "translation_method": transpilation.get("translation_method"),
            "used_edge_count": len(set(normalized)),
        },
    )


def _two_qubit_calibration_gate(
    snapshot: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    budgets: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, float] | None]:
    status, transpilation = _transpilation_status(candidate)
    if not isinstance(snapshot, Mapping):
        return _gate(NOT_RUN, "Two-qubit calibration cannot be evaluated without a snapshot."), None
    if status == NOT_RUN:
        return _gate(NOT_RUN, "Route-specific two-qubit calibration requires a routed candidate."), None
    if status != PASS:
        return _gate(BLOCKED, f"Transpilation status is {status}; route-specific calibration is blocked."), None
    backend = snapshot.get("backend") or {}
    calibration = snapshot.get("calibration") or {}
    num_qubits = _positive_int(backend.get("num_qubits"))
    used_raw = transpilation.get("used_two_qubit_edges")
    rows = calibration.get("two_qubit_gate_errors")
    if not isinstance(used_raw, list) or not used_raw:
        return _gate(BLOCKED, "Routed candidate has no used-edge inventory."), None
    if not isinstance(rows, list) or not rows:
        return _gate(NOT_RUN, "Snapshot has no two-qubit gate-error observations."), None
    used = {_normalize_edge(edge, num_qubits) for edge in used_raw}
    if None in used:
        return _gate(BLOCKED, "Routed used-edge inventory is invalid."), None
    errors_by_edge: dict[tuple[int, int], list[float]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            return _gate(BLOCKED, "Two-qubit calibration row is not an object."), None
        edge = _normalize_edge(row.get("qubits"), num_qubits)
        error = _finite_float(row.get("error"))
        if edge is None or error is None or error < 0.0 or error >= 1.0:
            return _gate(BLOCKED, "Two-qubit calibration row has an invalid edge or error."), None
        errors_by_edge.setdefault(edge, []).append(error)
    calibrated = used.intersection(errors_by_edge)
    coverage = len(calibrated) / max(len(used), 1)
    route_errors = [max(errors_by_edge[edge]) for edge in calibrated]
    min_coverage = float(budgets["min_calibration_edge_coverage"])
    if coverage < min_coverage or not route_errors:
        return _gate(
            REJECTED,
            "Calibration does not cover enough routed two-qubit edges.",
            observed=coverage,
            budget={"minimum_coverage": min_coverage},
        ), None
    maximum = max(route_errors)
    p95 = _nearest_rank(route_errors, 0.95)
    metrics = {"coverage": coverage, "maximum": maximum, "p95": p95}
    error_limit = float(budgets["max_two_qubit_error"])
    p95_limit = float(budgets["max_two_qubit_error_p95"])
    if maximum > error_limit or p95 > p95_limit:
        return _gate(
            REJECTED,
            "Route-specific two-qubit error exceeds the preregistered budget.",
            observed=metrics,
            budget={"maximum": error_limit, "p95": p95_limit},
        ), metrics
    return _gate(
        PASS,
        "Route-specific two-qubit error and edge coverage pass screening.",
        observed=metrics,
        budget={"maximum": error_limit, "p95": p95_limit, "minimum_coverage": min_coverage},
    ), metrics


def _rotation_gate(
    snapshot: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(candidate, Mapping):
        return _gate(NOT_RUN, "No rotation-synthesis manifest was supplied.")
    rotations = candidate.get("rotations")
    if not isinstance(rotations, Mapping):
        return _gate(NOT_RUN, "Rotation synthesis was not run.")
    status = str(rotations.get("status", NOT_RUN)).upper()
    if status == NOT_RUN:
        return _gate(NOT_RUN, "Continuous-rotation synthesis was not run.")
    if status != PASS:
        return _gate(BLOCKED, f"Rotation-synthesis status is {status}.")
    expected = int(budgets["expected_continuous_rotation_count"])
    continuous = _nonnegative_int(rotations.get("continuous_rotation_count"))
    synthesized = _nonnegative_int(rotations.get("synthesized_rotation_count"))
    maximum_error = _finite_float(rotations.get("max_approximation_error"))
    aggregate_error = _finite_float(rotations.get("aggregate_approximation_error"))
    method = _nonempty_string(rotations.get("method"))
    lane = _nonempty_string(rotations.get("evidence_lane"))
    allowed_lanes = {"NISQ_TARGET_ISA", "FAULT_TOLERANT_CLIFFORD_T"}
    if (
        continuous is None
        or synthesized is None
        or maximum_error is None
        or maximum_error < 0
        or aggregate_error is None
        or aggregate_error < 0
        or method is None
        or lane not in allowed_lanes
    ):
        return _gate(BLOCKED, "Rotation-synthesis manifest is incomplete or invalid.")
    if continuous != expected or synthesized != continuous:
        return _gate(
            BLOCKED,
            "Rotation inventory does not cover every V3.4 continuous rotation.",
            observed={"continuous": continuous, "synthesized": synthesized},
            budget={"expected": expected},
        )
    per_rotation_limit = float(budgets["max_rotation_approximation_error"])
    aggregate_limit = float(budgets["max_rotation_aggregate_error"])
    if aggregate_error > maximum_error * synthesized + 1e-15:
        return _gate(
            BLOCKED,
            "Aggregate rotation error exceeds the bound implied by the recorded maximum.",
            observed={
                "aggregate_error": aggregate_error,
                "maximum_times_count": maximum_error * synthesized,
            },
        )
    if maximum_error > per_rotation_limit or aggregate_error > aggregate_limit:
        return _gate(
            REJECTED,
            "Rotation approximation error exceeds a preregistered budget.",
            observed={
                "aggregate_error": aggregate_error,
                "maximum_per_occurrence_error": maximum_error,
            },
            budget={
                "maximum_aggregate_error": aggregate_limit,
                "maximum_per_occurrence_error": per_rotation_limit,
            },
        )
    return _gate(
        PASS,
        "Every continuous rotation has lane-specific bounded-error evidence.",
        observed={
            "aggregate_error": aggregate_error,
            "count": synthesized,
            "evidence_lane": lane,
            "maximum_error": maximum_error,
            "method": method,
        },
        budget={
            "maximum_aggregate_error": aggregate_limit,
            "maximum_per_occurrence_error": per_rotation_limit,
        },
    )


def _noise_proxy_gate(
    routed_two_qubit: Mapping[str, Any],
    error_metrics: Mapping[str, float] | None,
    budgets: Mapping[str, Any],
) -> dict[str, Any]:
    if routed_two_qubit.get("state") != PASS or not error_metrics:
        return _gate(NOT_RUN, "Noise proxy requires passing routed 2Q count and calibration gates.")
    count = int(routed_two_qubit["observed"])
    p95 = float(error_metrics["p95"])
    log_survival = count * math.log1p(-p95) if p95 < 1.0 else float("-inf")
    minimum = float(budgets["min_log_independent_two_qubit_survival_proxy"])
    evidence = "Heuristic independence proxy only; not a circuit fidelity estimate or hardware result."
    if log_survival < minimum:
        return _gate(
            REJECTED,
            "Conservative route-level 2Q survival proxy is below budget.",
            observed=log_survival,
            budget={"minimum_log_survival": minimum},
            evidence=evidence,
        )
    return _gate(
        PASS,
        "Route-level 2Q survival proxy passes the preregistered screening floor.",
        observed=log_survival,
        budget={"minimum_log_survival": minimum},
        evidence=evidence,
    )


def _overall_state(gates: Mapping[str, Mapping[str, Any]]) -> str:
    parent_state = (gates.get("v34_parent_binding") or {}).get("state")
    model_state = (gates.get("parent_provider_2q_gate_model_screen") or {}).get(
        "state"
    )
    downstream_states = [
        gate.get("state")
        for name, gate in gates.items()
        if name not in {"v34_parent_binding", "parent_provider_2q_gate_model_screen"}
    ]
    if parent_state != PASS:
        return "INVALID_EVIDENCE_CHAIN · V3.4 PARENT NOT AUTHENTICATED"
    if model_state == REJECTED:
        if BLOCKED in downstream_states:
            return "REJECTED_MODEL_SCREEN · DOWNSTREAM EVIDENCE BLOCKED"
        if NOT_RUN in downstream_states:
            return "REJECTED_MODEL_SCREEN · DOWNSTREAM EVALUATION NOT RUN"
        return "REJECTED_MODEL_SCREEN · DOCUMENTED PROVIDER LIMIT"
    states = [gate.get("state") for gate in gates.values()]
    if BLOCKED in states:
        return "INVALID_EVIDENCE_CHAIN · OFFLINE BUNDLE BLOCKED"
    if NOT_RUN in states:
        return "INDETERMINATE_TRANSPILE_RESOURCE · REQUIRED EVALUATION NOT RUN"
    if REJECTED in states:
        return "REJECTED_BACKEND_SCREEN · PREREGISTERED BUDGET"
    if states and all(state == PASS for state in states):
        return "PASS · ZERO-JOB OFFLINE ADMISSION ONLY"
    return "BLOCKED · EMPTY ADMISSION EVIDENCE"


def admit_backend(
    snapshot: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None,
    *,
    expected_snapshot_sha256: str | None,
    as_of_utc: str | datetime | None = None,
    spec: Mapping[str, Any] | None = None,
    v34_artifact_path: str | Path | None = None,
    v34_freeze_path: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate an offline named-backend bundle without provider access.

    ``candidate`` is an already-exported transpilation/rotation manifest.  This
    function audits it; it never creates it.  The result cannot authorize a QPU
    job, even when every offline gate passes.
    """

    loaded_spec = dict(spec) if spec is not None else load_v35_spec()
    if spec is not None:
        # Round-trip through the same immutable contract checks for injected specs.
        core = {
            key: value
            for key, value in loaded_spec.items()
            if key not in {"v35_spec_sha", "v35_spec_sha256"}
        }
        digest = canonical_json_sha256(core)
        if loaded_spec.get("v35_spec_sha256") != digest:
            raise ValueError("Injected V3.5 specification SHA-256 mismatch.")
    as_of = _as_of(as_of_utc)
    budgets = loaded_spec["acceptance_budgets"]
    authentication, snapshot_digest = _snapshot_authentication(
        snapshot, expected_snapshot_sha256
    )
    parent = verify_v34_parent(
        loaded_spec,
        artifact_path=v34_artifact_path,
        freeze_path=v34_freeze_path,
    )
    logical_width = _logical_width_gate(snapshot, candidate, budgets)
    connected_capacity = _connected_capacity_gate(snapshot, budgets)
    routed_width = _routed_metric_gate(
        candidate,
        snapshot,
        field="routed_width",
        label="Routed width",
        minimum=int(budgets["required_logical_qubits"]),
    )
    routed_depth = _routed_metric_gate(
        candidate,
        snapshot,
        field="routed_depth",
        label="Routed depth",
        maximum=int(budgets["max_routed_depth"]),
    )
    routed_two_qubit = _routed_metric_gate(
        candidate,
        snapshot,
        field="routed_two_qubit_gates",
        label="Routed two-qubit count",
        maximum=int(budgets["max_routed_two_qubit_gates"]),
    )
    calibration_gate, error_metrics = _two_qubit_calibration_gate(
        snapshot, candidate, budgets
    )
    model_screen = _parent_provider_gate_model_screen(loaded_spec)
    gates: dict[str, dict[str, Any]] = {
        "v34_parent_binding": parent,
        "parent_provider_2q_gate_model_screen": model_screen,
        "snapshot_authentication": authentication,
        "backend_identity_and_provenance": _identity_gate(snapshot, loaded_spec),
        "calibration_freshness": _freshness_gate(snapshot, as_of, budgets),
        "candidate_parent_binding": _candidate_parent_gate(candidate, loaded_spec),
        "transpilation_metadata": _transpilation_metadata_gate(
            snapshot, candidate, loaded_spec
        ),
        "logical_width": logical_width,
        "connected_capacity": connected_capacity,
        "routed_width": routed_width,
        "routed_depth": routed_depth,
        "routed_two_qubit_count": routed_two_qubit,
        "calibration_two_qubit_error": calibration_gate,
        "rotation_synthesis": _rotation_gate(snapshot, candidate, budgets),
        "noise_aware_survival_proxy": _noise_proxy_gate(
            routed_two_qubit, error_metrics, budgets
        ),
    }
    runtime = _runtime_inventory()
    offline_state = _overall_state(gates)
    candidate_digest = (
        canonical_json_sha256(candidate) if isinstance(candidate, Mapping) else None
    )
    snapshot_backend = (snapshot or {}).get("backend") if isinstance(snapshot, Mapping) else {}
    snapshot_backend = snapshot_backend if isinstance(snapshot_backend, Mapping) else {}
    calibration = (snapshot or {}).get("calibration") if isinstance(snapshot, Mapping) else {}
    calibration = calibration if isinstance(calibration, Mapping) else {}
    transpilation = (candidate or {}).get("transpilation") if isinstance(candidate, Mapping) else {}
    transpilation = transpilation if isinstance(transpilation, Mapping) else {}
    model_observed = model_screen.get("observed") or {}
    model_budget = model_screen.get("budget") or {}
    model_evidence = model_screen.get("evidence") or {}
    downstream_states = {
        name: gate.get("state")
        for name, gate in gates.items()
        if name not in {"v34_parent_binding", "parent_provider_2q_gate_model_screen"}
    }
    veto_reasons = [
        f"{name}: {gate.get('state')} · {gate.get('reason')}"
        for name, gate in gates.items()
        if gate.get("state") != PASS
    ]
    circuit_stage = "ROUTED" if transpilation.get("status") == PASS else "PROVIDER_NEUTRAL"
    core = {
        "artifact_version": ARTIFACT_VERSION,
        "backend_admission_version": BACKEND_ADMISSION_VERSION,
        "spec_sha256": loaded_spec["v35_spec_sha256"],
        "source_commitments": {
            "backend_admission_source_sha256": source_sha256(),
        },
        "evaluated_at_utc": as_of.isoformat(),
        "research_classification": "RESEARCH_ONLY",
        "input_commitments": {
            "snapshot_payload_sha256": snapshot_digest,
            "out_of_band_snapshot_sha256": (
                str(expected_snapshot_sha256).lower()
                if expected_snapshot_sha256 is not None
                else None
            ),
            "candidate_manifest_sha256": candidate_digest,
            "parent_v34_artifact_sha256": (
                loaded_spec.get("parent_contract") or {}
            ).get("expected_parent_v34_artifact_sha256"),
        },
        "parents": {
            "v34_artifact_sha256": (
                loaded_spec.get("parent_contract") or {}
            ).get("expected_parent_v34_artifact_sha256"),
            "v34_freeze_sha256": (
                loaded_spec.get("parent_contract") or {}
            ).get("expected_parent_v34_freeze_sha256"),
        },
        "evidence": {
            "mode": "SNAPSHOT" if isinstance(snapshot, Mapping) else "NONE",
            "captured_at_utc": calibration.get("captured_at_utc") or "NOT_RECORDED",
            "live_provider_probe": "NOT_RUN",
        },
        "backend": {
            "provider_id": snapshot_backend.get("provider_id"),
            "backend_name": snapshot_backend.get("backend_name"),
            "backend_version": snapshot_backend.get("backend_version"),
            "class": (
                "SIMULATOR"
                if snapshot_backend.get("is_simulator") is True
                else ("HARDWARE" if snapshot_backend.get("is_simulator") is False else "UNKNOWN")
            ),
            "basis_gates": snapshot_backend.get("basis_gates") or [],
            "coupling_map_edges": len(snapshot_backend.get("coupling_map") or []),
            "status_msg": snapshot_backend.get("status_msg"),
        },
        "calibration": {
            "calibration_id": calibration.get("calibration_id") or "NOT_RECORDED",
            "captured_at_utc": calibration.get("captured_at_utc") or "NOT_RECORDED",
            "properties_last_update_utc": calibration.get("properties_last_update_utc") or "NOT_RECORDED",
        },
        "compilation": {
            "stage": circuit_stage,
            "basis_gates": transpilation.get("target_basis_gates") or [],
            "coupling_map_edges": len(snapshot_backend.get("coupling_map") or []),
            "optimization_level": transpilation.get("optimization_level") or "NOT_RECORDED",
            "seed_transpiler": transpilation.get("routing_seed") or "NOT_RECORDED",
        },
        "resources": {
            "input_depth": 628_414_456,
            "input_two_qubit_gates": model_observed.get("selected_ccx_model_cnot_count", 0),
            "output_depth": transpilation.get("routed_depth") or 0,
            "output_two_qubit_gates": transpilation.get("routed_two_qubit_gates") or 0,
            "output_total_gates": transpilation.get("routed_total_gates") or 0,
            "swap_count": transpilation.get("swap_count") or 0,
        },
        "provider_limits": {
            "limit_name": "IBM documented maximum two-qubit gates per circuit",
            "max_two_qubit_gates_per_circuit": model_budget.get(
                "maximum_two_qubit_gates_per_circuit", 0
            ),
            "source_url": model_evidence.get("source_url"),
            "observed_at_utc": model_evidence.get("source_checked_utc"),
        },
        "pre_transpile_provider_limit": {
            "decision": model_screen.get("state"),
            "selected_ccx_model_cnot_count": model_observed.get(
                "selected_ccx_model_cnot_count", 0
            ),
            "multiple_of_limit": model_observed.get("multiple_of_limit"),
        },
        "validation": {
            "checks": {name: state == PASS for name, state in downstream_states.items()},
            "gate_states": downstream_states,
            "overall_pass": all(state == PASS for state in downstream_states.values()),
        },
        "gates": gates,
        "veto": {"active": bool(veto_reasons), "reasons": veto_reasons},
        "runtime_inventory": runtime,
        "decisions": {
            "offline_backend_admission": offline_state,
            "pretranspilation_model_screen": (
                "REJECTED_MODEL_SCREEN"
                if model_screen.get("state") == REJECTED
                else model_screen.get("state")
            ),
            "downstream_evidence": (
                "BLOCKED_OR_NOT_RUN"
                if any(state in {BLOCKED, NOT_RUN} for state in downstream_states.values())
                else "COMPLETE"
            ),
            "online_backend_resolution": "NOT_RUN · OFFLINE SNAPSHOT ONLY",
            "local_transpilation_reproduction": runtime[
                "local_transpilation_reproduction"
            ],
            "provider_authentication": "NOT_RUN · CREDENTIAL ACCESS PROHIBITED",
            "hardware_execution": "BLOCKED · ZERO JOBS",
            "qpu_submission": "DISABLED",
            "qpu_jobs_submitted": 0,
            "hardware_executable": False,
            "quantum_advantage": "NOT_CLAIMED",
        },
        "claim_boundary": {
            "offline_admission_authorizes_transpilation_audit_only": True,
            "backend_native_reproduction_verified_here": False,
            "provider_session_opened": False,
            "credentials_read": False,
            "network_calls": 0,
            "qpu_submission_enabled": False,
            "qpu_jobs_submitted": 0,
            "hardware_executable": False,
            "quantum_advantage": "NOT_CLAIMED",
        },
    }
    return {**core, "artifact_sha256": canonical_json_sha256(core)}


def validate_admission_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, Mapping):
        return {"valid": False, "errors": ["Artifact must be an object."]}
    core = {key: value for key, value in payload.items() if key != "artifact_sha256"}
    try:
        computed = canonical_json_sha256(core)
    except (TypeError, ValueError, OverflowError) as exc:
        return {"valid": False, "errors": [str(exc)]}
    if payload.get("artifact_sha256") != computed:
        errors.append("Artifact SHA-256 mismatch.")
    if payload.get("artifact_version") != ARTIFACT_VERSION:
        errors.append("Artifact version mismatch.")
    try:
        expected_spec_sha256 = load_v35_spec().get("v35_spec_sha256")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        expected_spec_sha256 = None
        errors.append(f"Live V3.5 specification is invalid: {exc}")
    if payload.get("spec_sha256") != expected_spec_sha256:
        errors.append("Artifact V3.5 specification identity mismatch.")
    if (
        (payload.get("source_commitments") or {}).get(
            "backend_admission_source_sha256"
        )
        != source_sha256()
    ):
        errors.append("Artifact backend-admission source identity mismatch.")
    if payload.get("research_classification") != "RESEARCH_ONLY":
        errors.append("Research classification boundary violated.")
    decisions = payload.get("decisions") or {}
    boundary = payload.get("claim_boundary") or {}
    gates = payload.get("gates") or {}
    model_screen = gates.get("parent_provider_2q_gate_model_screen") or {}
    parent_gate = gates.get("v34_parent_binding") or {}
    if parent_gate.get("state") != PASS:
        errors.append("Frozen V3.4 parent gate is not passing.")
    if model_screen.get("state") != REJECTED:
        errors.append("Required V3.5 pretranspilation model rejection is missing.")
    if decisions.get("pretranspilation_model_screen") != "REJECTED_MODEL_SCREEN":
        errors.append("V3.5 negative-result decision is not retained.")
    if decisions.get("qpu_jobs_submitted") != 0:
        errors.append("Decision QPU job count is non-zero.")
    if decisions.get("qpu_submission") != "DISABLED":
        errors.append("Decision QPU submission is not disabled.")
    if decisions.get("hardware_executable") is not False:
        errors.append("Decision hardware-executable flag is not false.")
    if decisions.get("quantum_advantage") != "NOT_CLAIMED":
        errors.append("Decision advantage boundary violated.")
    if boundary.get("provider_session_opened") is not False:
        errors.append("Provider-session boundary violated.")
    if boundary.get("credentials_read") is not False:
        errors.append("Credential boundary violated.")
    if boundary.get("network_calls") != 0:
        errors.append("Network-call boundary violated.")
    if boundary.get("qpu_submission_enabled") is not False:
        errors.append("Submission boundary violated.")
    if boundary.get("qpu_jobs_submitted") != 0:
        errors.append("Boundary QPU job count is non-zero.")
    return {
        "artifact_sha256_computed": computed,
        "artifact_sha256_stored": payload.get("artifact_sha256"),
        "errors": errors,
        "valid": not errors,
    }


def load_admission_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and authenticate the sealed V3.5 negative-result artifact."""

    artifact_path = (
        Path(path)
        if path is not None
        else default_admission_root() / DEFAULT_ARTIFACT_NAME
    )
    payload = _read_json_object(artifact_path)
    report = validate_admission_artifact(payload)
    if not report.get("valid"):
        raise ValueError("; ".join(str(item) for item in report.get("errors", [])))
    return payload, report


__all__ = [
    "ARTIFACT_VERSION",
    "BACKEND_ADMISSION_VERSION",
    "BLOCKED",
    "DEFAULT_ARTIFACT_NAME",
    "NOT_RUN",
    "PASS",
    "REJECTED",
    "admit_backend",
    "attach_snapshot_digest",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "default_admission_root",
    "load_admission_artifact",
    "load_v35_spec",
    "snapshot_payload",
    "snapshot_payload_sha256",
    "source_sha256",
    "validate_admission_artifact",
    "verify_v34_parent",
]
