"""Institutional, fail-closed evidence surface for Quantum Lab V4.7.

V4.7 evaluates exact V4.6 streams against one pinned, historical
FakeMarrakesh properties snapshot.  Every number rendered here is masked unless
the sealed artifact, its compiler/checker identities, its complete predecessor
lineage, and the standard-library independent checker all authenticate.

The duration view is an offline integer-dt ASAP replay.  The reported error
mass is a descriptive sum over dated fields; it is deliberately never labelled
as fidelity, success probability, expected failures, or hardware performance.
"""

from __future__ import annotations

import copy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v47_dated_properties_optimizer import (
    ARTIFACT_VERSION,
    CANDIDATE_NAME,
    DEFAULT_ARTIFACT_NAME,
    EXPECTED_MODEL_RAW_SHA256,
    EXPECTED_MODEL_SHA256,
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
    EXPECTED_PROPERTIES_RAW_SHA256,
    EXPECTED_PROPERTIES_SHA256,
    EXPECTED_RAW_PROPERTIES_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    MODEL_FILENAME,
    PATH_ORACLE_FILENAME,
    PROPERTIES_FILENAME,
    RAW_PROPERTIES_FILENAME,
    SPEC_FILENAME,
    authenticate_v46_parent,
    canonical_json_sha256,
    load_candidate_path_oracle,
    load_model_contract,
    load_property_oracle,
    load_v47_spec,
    raw_file_sha256,
)
from .phase3_v47_independent_checker import (
    EXPECTED_CHECK_COUNT as EXPECTED_INDEPENDENT_CHECK_COUNT,
    validate_v47_artifact,
)


SectionHeader = Callable[[str, str, str], None]

# These four exact post-result identities bind the sealed artifact and the
# final optimizer/checker bytes.  Any mismatch makes the loader mask every
# V4.7 scientific result fail-closed.
EXPECTED_ARTIFACT_RAW_SHA256 = "ddb8dae96c1d5fe1040f92731c995315e04232da645fed0b2d34cf7575a06185"
EXPECTED_ARTIFACT_SHA256 = "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf"
EXPECTED_SOURCE_RAW_SHA256 = "e84737ff659cd245408abca072ba1578cbbfe3a0d26d40e964a98fc9dab8bb52"
EXPECTED_CHECKER_RAW_SHA256 = "72e007364e073b99ebf781424922600c69e1d31793092bfc348554a3318cd849"

EXPECTED_UI_AUTH_CHECK_COUNT = 21
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_OVERALL_REJECTION = (
    "V47_HISTORICAL_PROPERTIES_STRESS_SCREEN_REJECTS_FIXED_V46_ARCHITECTURE_"
    "NO_CURRENT_HARDWARE_INFERENCE"
)
EXPECTED_PRODUCTION = "OFFLINE_HISTORICAL_PROPERTIES_ONLY_HARDWARE_EXECUTION_REJECTED"
EXPECTED_NEXT_GATE = (
    "MULTI_SNAPSHOT_ROBUSTNESS_AND_ARCHITECTURE_LEVEL_CZ_REDUCTION_"
    "BEFORE_ANY_CURRENT_PROVIDER_DISCOVERY"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _decode_json_strict(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key rejected: {key}")
            result[key] = value
        return result

    payload = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"Non-finite JSON number rejected: {token}")
        ),
    )
    if not isinstance(payload, dict):
        raise ValueError("V4.7 evidence must be a JSON object.")
    return payload


def _is_sha(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _self_hash(payload: Mapping[str, Any], field: str) -> bool:
    return bool(
        _is_sha(payload.get(field))
        and payload.get(field)
        == canonical_json_sha256({key: value for key, value in payload.items() if key != field})
    )


def _short_sha(value: Any) -> str:
    text = str(value or "")
    return f"{text[:12]}…{text[-8:]}" if _is_sha(text) else "MASKED"


def _decimal(value: Any) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("NaN")
    return parsed if parsed.is_finite() else Decimal("NaN")


def _scientific(value: Any, digits: int = 5) -> str:
    parsed = _decimal(value)
    if not parsed.is_finite():
        return "MASKED"
    return f"{parsed:.{digits}E}"


def _milliseconds(seconds: Any) -> str:
    try:
        value = float(seconds) * 1_000
    except (TypeError, ValueError, OverflowError):
        return "MASKED"
    return f"{value:,.3f}"


def default_v47_ui_artifact_path() -> Path:
    return _root() / "outputs/quantum_phase3/v47_dated_properties" / DEFAULT_ARTIFACT_NAME


def _validate_v47_ui_artifact(
    raw: bytes,
    *,
    root: Path,
    artifact_path: Path | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    try:
        artifact = _decode_json_strict(raw)
        spec = load_v47_spec(root=root)
        properties = load_property_oracle(root=root)
        model = load_model_contract(root=root)
        path_oracle, _, component = load_candidate_path_oracle(root=root)
        parent = authenticate_v46_parent(root=root)
    except Exception as exc:
        return {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_authenticated_load"],
            "valid": False,
        }

    authenticated_artifact_path = (
        artifact_path if artifact_path is not None else default_v47_ui_artifact_path()
    )
    source_path = root / "quantum_research_lab/phase3_v47_dated_properties_optimizer.py"
    checker_path = root / "quantum_research_lab/phase3_v47_independent_checker.py"
    pins_sealed = all(
        _is_sha(value)
        for value in (
            EXPECTED_ARTIFACT_RAW_SHA256,
            EXPECTED_ARTIFACT_SHA256,
            EXPECTED_SOURCE_RAW_SHA256,
            EXPECTED_CHECKER_RAW_SHA256,
        )
    )
    if not pins_sealed:
        errors.append("V4.7 post-result artifact/compiler/checker identities are not pinned.")

    try:
        independent = validate_v47_artifact(
            artifact,
            root=root,
            authenticate_parent=True,
            expected_artifact_sha256=EXPECTED_ARTIFACT_SHA256,
            artifact_raw_file_sha256=hashlib.sha256(raw).hexdigest(),
            expected_artifact_raw_sha256=EXPECTED_ARTIFACT_RAW_SHA256,
        )
    except Exception as exc:
        independent = {
            "check_count": EXPECTED_INDEPENDENT_CHECK_COUNT,
            "errors": [str(exc)],
            "failed_checks": ["independent_checker_exception"],
            "valid": False,
        }
    errors.extend(parent.get("errors") or [])
    errors.extend(independent.get("errors") or [])

    seed_rows = _rows(artifact.get("seed_evaluations"))
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    snapshot = _mapping(artifact.get("properties_snapshot"))
    required_decisions = {
        "baseline_dated_properties",
        "candidate_research_routing",
        "fixed_architecture_historical_stress_screen",
        "next_falsifiable_gate",
        "overall",
        "pareto_safe_replacement",
        "production_admission",
    }
    checks: dict[str, bool] = {
        "post_result_pins_sealed": pins_sealed,
        "artifact_regular_file": authenticated_artifact_path.is_file()
        and not authenticated_artifact_path.is_symlink(),
        "artifact_raw_identity": hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": bool(
            artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256
            and _self_hash(artifact, "artifact_sha256")
            and artifact.get("artifact_version") == ARTIFACT_VERSION
        ),
        "optimizer_source_identity": source_path.is_file()
        and not source_path.is_symlink()
        and raw_file_sha256(source_path) == EXPECTED_SOURCE_RAW_SHA256,
        "independent_checker_identity": checker_path.is_file()
        and not checker_path.is_symlink()
        and raw_file_sha256(checker_path) == EXPECTED_CHECKER_RAW_SHA256,
        "artifact_optimizer_crosslink": artifact.get("source_raw_file_sha256")
        == EXPECTED_SOURCE_RAW_SHA256,
        "artifact_checker_crosslink": artifact.get("independent_checker_raw_file_sha256")
        == EXPECTED_CHECKER_RAW_SHA256,
        "spec_identity": bool(
            spec.get("v47_spec_sha256") == EXPECTED_SPEC_SHA256
            and artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256
            and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256
        ),
        "properties_identity": bool(
            properties.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
            and snapshot.get("properties_raw_file_sha256") == EXPECTED_RAW_PROPERTIES_SHA256
            and snapshot.get("properties_snapshot_raw_file_sha256")
            == EXPECTED_PROPERTIES_RAW_SHA256
            and snapshot.get("properties_snapshot_sha256") == EXPECTED_PROPERTIES_SHA256
        ),
        "candidate_path_identity": bool(
            path_oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256
            and _mapping(artifact.get("candidate_contract")).get("path_oracle_raw_file_sha256")
            == EXPECTED_PATH_ORACLE_RAW_SHA256
            and _mapping(artifact.get("candidate_contract")).get("path_oracle_sha256")
            == EXPECTED_PATH_ORACLE_SHA256
            and len(component) == 153
        ),
        "duration_error_model_identity": bool(
            model.get("model_contract_sha256") == EXPECTED_MODEL_SHA256
            and _mapping(artifact.get("model_contract")).get("model_contract_raw_file_sha256")
            == EXPECTED_MODEL_RAW_SHA256
            and _mapping(artifact.get("model_contract")).get("model_contract_sha256")
            == EXPECTED_MODEL_SHA256
        ),
        "v46_parent_authentication": parent.get("valid") is True
        and parent.get("immutable_files_exact") is True,
        "seed_order_exact": [row.get("seed") for row in seed_rows] == list(EXPECTED_SEEDS),
        "seed_rows_self_hashed": bool(
            seed_rows and all(_self_hash(row, "seed_evaluation_sha256") for row in seed_rows)
        ),
        "aggregate_self_hashed": _self_hash(aggregate, "aggregate_sha256")
        and aggregate.get("seed_count") == 8,
        "decision_surface_complete": required_decisions <= set(decisions)
        and decisions.get("production_admission") == EXPECTED_PRODUCTION
        and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "research_classification_exact": artifact.get("research_classification") == "RESEARCH_ONLY"
        and boundary.get("research_classification") == "RESEARCH_ONLY",
        "provider_network_job_zero": bool(
            boundary.get("provider_sdk_imported") is False
            and boundary.get("provider_credentials_read") is False
            and boundary.get("credential_reads") == 0
            and boundary.get("provider_calls") == 0
            and boundary.get("network_calls") == 0
            and boundary.get("backend_run_calls") == 0
            and boundary.get("local_simulator_jobs_submitted") == 0
            and boundary.get("qpu_jobs_submitted") == 0
        ),
        "hardware_and_snapshot_boundary": boundary.get("hardware_executable") is False
        and boundary.get("snapshot_is_current_hardware_evidence") is False
        and snapshot.get("snapshot_is_current_hardware_evidence") is False,
        "independent_checker_51_pass": independent.get("valid") is True
        and independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT
        and not independent.get("failed_checks")
        and not independent.get("errors"),
    }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        raise AssertionError(
            f"V4.7 UI authentication count drifted: {len(checks)} != {EXPECTED_UI_AUTH_CHECK_COUNT}"
        )
    failed = [name for name, passed in checks.items() if passed is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(str(item) for item in errors if item)),
        "failed_checks": failed,
        "independent_checker": independent,
        "valid": not failed and not errors,
    }


def load_v47_ui_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v47_ui_artifact_path()
    try:
        if not target.is_file() or target.is_symlink():
            raise FileNotFoundError(f"Missing or non-regular V4.7 sealed artifact: {target}")
        raw = target.read_bytes()
        artifact = _decode_json_strict(raw)
        report = _validate_v47_ui_artifact(raw, root=_root(), artifact_path=target)
        return artifact, report
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["artifact_available"],
            "valid": False,
        }


def normalize_v47_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    integrity: bool | None,
) -> dict[str, Any]:
    boundary = _mapping(artifact.get("claim_boundary")) if isinstance(artifact, Mapping) else {}
    if (
        not isinstance(artifact, Mapping)
        or integrity is not True
        or artifact.get("research_classification") != "RESEARCH_ONLY"
        or boundary.get("hardware_executable") is not False
    ):
        return {
            "authenticated": False,
            "decision": "MASKED_FAIL_CLOSED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
        }
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    return {
        "authenticated": True,
        "all_eight_architecture_lower_bounds_fail_both_screens": aggregate.get(
            "all_eight_architecture_lower_bounds_fail_both_screens"
        ),
        "all_eight_candidate_research_feasible": aggregate.get(
            "all_eight_candidate_research_feasible"
        ),
        "all_eight_pareto_safe": aggregate.get("all_eight_pareto_safe"),
        "baseline_total_unit_error_gate_occurrences": aggregate.get(
            "baseline_total_unit_error_gate_occurrences"
        ),
        "candidate_total_unit_error_gate_occurrences": aggregate.get(
            "candidate_total_unit_error_gate_occurrences"
        ),
        "decision": decisions.get("overall"),
        "hardware_executable": False,
        "production_admission": decisions.get("production_admission"),
        "research_classification": "RESEARCH_ONLY",
        "seed_count": aggregate.get("seed_count"),
    }


def _routed(row: Mapping[str, Any], side: str) -> Mapping[str, Any]:
    return _mapping(_mapping(row.get(side)).get("routed_compilation"))


def _duration_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_evaluations")):
        baseline = _mapping(_routed(seed_row, "baseline_v46").get("timing_ledger"))
        candidate = _mapping(_routed(seed_row, "candidate").get("timing_ledger"))
        lower = _mapping(seed_row.get("architecture_lower_bound"))
        rows.append(
            {
                "Seed": seed_row.get("seed"),
                "Baseline ticks": baseline.get("makespan_ticks"),
                "Baseline ms": _milliseconds(baseline.get("makespan_seconds")),
                "Candidate ticks": candidate.get("makespan_ticks"),
                "Candidate ms": _milliseconds(candidate.get("makespan_seconds")),
                "Candidate Δ ticks": int(candidate.get("makespan_ticks", 0))
                - int(baseline.get("makespan_ticks", 0)),
                "Optimistic lower bound ticks": lower.get(
                    "optimistic_cz_duration_lower_bound_ticks"
                ),
                "Lower bound / max dated T2": f"{float(lower.get('optimistic_cz_duration_over_maximum_snapshot_t2', 0)):.2f}×",
                "Duration screen": "PASS"
                if lower.get("passes_duration_screen") is True
                else "FAIL",
            }
        )
    return pd.DataFrame(rows)


def _error_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_evaluations")):
        baseline = _mapping(_routed(seed_row, "baseline_v46").get("error_screen"))
        candidate = _mapping(_routed(seed_row, "candidate").get("error_screen"))
        lower = _mapping(seed_row.get("architecture_lower_bound"))
        rows.append(
            {
                "Seed": seed_row.get("seed"),
                "Baseline error mass": _scientific(baseline.get("reported_gate_error_mass")),
                "Candidate error mass": _scientific(candidate.get("reported_gate_error_mass")),
                "Candidate Δ mass": _scientific(
                    _decimal(candidate.get("reported_gate_error_mass"))
                    - _decimal(baseline.get("reported_gate_error_mass"))
                ),
                "Baseline unit-error uses": baseline.get("unit_error_gate_occurrences"),
                "Candidate unit-error uses": candidate.get("unit_error_gate_occurrences"),
                "Optimistic mass lower bound": _scientific(
                    lower.get("optimistic_reported_error_mass_lower_bound")
                ),
                "Error-mass screen": "PASS"
                if lower.get("passes_reported_error_mass_screen") is True
                else "FAIL",
            }
        )
    return pd.DataFrame(rows)


def _gate_error_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    totals = {
        side: {gate: Decimal(0) for gate in ("cz", "id", "rz", "sx", "x")}
        for side in ("baseline_v46", "candidate")
    }
    with localcontext() as decimal_context:
        decimal_context.prec = 50
        for seed_row in _rows(artifact.get("seed_evaluations")):
            for side in totals:
                by_gate = _mapping(_mapping(_routed(seed_row, side).get("error_screen")).get(
                    "reported_gate_error_mass_by_gate"
                ))
                for gate in totals[side]:
                    value = _decimal(by_gate.get(gate, "0"))
                    if value.is_finite():
                        totals[side][gate] += value
    return pd.DataFrame(
        [
            {
                "Native gate": gate.upper(),
                "Baseline aggregate mass": _scientific(totals["baseline_v46"][gate]),
                "Candidate aggregate mass": _scientific(totals["candidate"][gate]),
                "Candidate Δ mass": _scientific(
                    totals["candidate"][gate] - totals["baseline_v46"][gate]
                ),
            }
            for gate in ("cz", "sx", "x", "id", "rz")
        ]
    )


def _optimization_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_evaluations")):
        baseline_wrapper = _mapping(seed_row.get("baseline_v46"))
        candidate_wrapper = _mapping(seed_row.get("candidate"))
        baseline = _routed(seed_row, "baseline_v46")
        candidate = _routed(seed_row, "candidate")
        baseline_native = _mapping(_mapping(baseline.get("native_ledger")).get(
            "native_operation_counts"
        ))
        candidate_native = _mapping(_mapping(candidate.get("native_ledger")).get(
            "native_operation_counts"
        ))
        comparison = _mapping(seed_row.get("comparison"))
        rows.append(
            {
                "Seed": seed_row.get("seed"),
                "Logical Q": seed_row.get("logical_qubits"),
                "Baseline CZ": baseline_native.get("cz"),
                "Candidate CZ": candidate_native.get("cz"),
                "Δ CZ": comparison.get("candidate_minus_baseline_native_cz"),
                "Δ makespan ticks": comparison.get("candidate_minus_baseline_makespan_ticks"),
                "Δ error mass": _scientific(
                    comparison.get("candidate_minus_baseline_reported_error_mass")
                ),
                "Candidate feasibility": candidate_wrapper.get("status"),
                "Baseline property status": baseline_wrapper.get("status"),
                "Pareto": "PASS"
                if comparison.get("pareto_safe_for_seed") is True
                else "NOT DEMONSTRATED",
            }
        )
    return pd.DataFrame(rows)


def _properties_gate_ledger(properties: Mapping[str, Any]) -> pd.DataFrame:
    gate_stats = _mapping(_mapping(properties.get("statistics")).get("gate_properties"))
    rows: list[dict[str, Any]] = []
    for gate in ("cz", "id", "rz", "sx", "x"):
        stats = _mapping(gate_stats.get(gate))
        errors = _mapping(stats.get("gate_error"))
        durations = _mapping(stats.get("duration_seconds"))
        rows.append(
            {
                "Gate": gate.upper(),
                "Tuples": stats.get("count"),
                "Error min": f"{float(errors.get('minimum', 0)):.6g}",
                "Error median": f"{float(errors.get('median', 0)):.6g}",
                "Error max": f"{float(errors.get('maximum', 0)):.6g}",
                "Duration min ns": f"{float(durations.get('minimum', 0)) * 1e9:.1f}",
                "Duration median ns": f"{float(durations.get('median', 0)) * 1e9:.1f}",
                "Duration max ns": f"{float(durations.get('maximum', 0)) * 1e9:.1f}",
                "Unit-error tuples": stats.get("unit_error_tuple_count"),
            }
        )
    return pd.DataFrame(rows)


def _qubit_property_ledger(properties: Mapping[str, Any]) -> pd.DataFrame:
    stats = _mapping(_mapping(properties.get("statistics")).get("qubits"))
    rows: list[dict[str, Any]] = []
    for key, label, scale, unit in (
        ("t1_seconds", "T1", 1e6, "µs"),
        ("t2_seconds", "T2", 1e6, "µs"),
        ("readout_error", "Readout error", 1.0, "fraction"),
    ):
        values = _mapping(stats.get(key))
        rows.append(
            {
                "Property": label,
                "Unit": unit,
                "Minimum": f"{float(values.get('minimum', 0)) * scale:.6g}",
                "Median": f"{float(values.get('median', 0)) * scale:.6g}",
                "Maximum": f"{float(values.get('maximum', 0)) * scale:.6g}",
                "Acceptance role": "CONTEXT ONLY",
            }
        )
    return pd.DataFrame(rows)


def _provenance_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Evidence": "V4.7 artifact raw", "SHA-256": EXPECTED_ARTIFACT_RAW_SHA256},
            {"Evidence": "V4.7 artifact semantic", "SHA-256": artifact.get("artifact_sha256")},
            {"Evidence": "V4.7 preregistration raw", "SHA-256": EXPECTED_SPEC_RAW_SHA256},
            {"Evidence": "V4.7 preregistration semantic", "SHA-256": EXPECTED_SPEC_SHA256},
            {"Evidence": "Raw dated properties", "SHA-256": EXPECTED_RAW_PROPERTIES_SHA256},
            {"Evidence": "Normalized properties raw", "SHA-256": EXPECTED_PROPERTIES_RAW_SHA256},
            {"Evidence": "Normalized properties semantic", "SHA-256": EXPECTED_PROPERTIES_SHA256},
            {"Evidence": "Fault-excluded path oracle raw", "SHA-256": EXPECTED_PATH_ORACLE_RAW_SHA256},
            {"Evidence": "Fault-excluded path oracle semantic", "SHA-256": EXPECTED_PATH_ORACLE_SHA256},
            {"Evidence": "Duration/error model raw", "SHA-256": EXPECTED_MODEL_RAW_SHA256},
            {"Evidence": "Duration/error model semantic", "SHA-256": EXPECTED_MODEL_SHA256},
            {"Evidence": "Optimizer source raw", "SHA-256": EXPECTED_SOURCE_RAW_SHA256},
            {"Evidence": "Independent checker raw", "SHA-256": EXPECTED_CHECKER_RAW_SHA256},
            {
                "Evidence": "V4.6 parent artifact semantic",
                "SHA-256": _mapping(artifact.get("parent")).get("artifact_sha256"),
            },
            {
                "Evidence": "V4.6 parent freeze semantic",
                "SHA-256": _mapping(artifact.get("parent")).get("freeze_sha256"),
            },
        ]
    )


def _sealed_download_bytes(path: Path, expected_raw_sha256: str) -> bytes | None:
    """Read a downloadable evidence file only when its exact raw identity still holds."""

    try:
        if not path.is_file() or path.is_symlink() or not _is_sha(expected_raw_sha256):
            return None
        payload = path.read_bytes()
    except OSError:
        return None
    return payload if hashlib.sha256(payload).hexdigest() == expected_raw_sha256 else None


def apply_v47_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Project authenticated V4.7 evidence only into the BANDS regime."""

    projected = copy.deepcopy(dict(encoding or {}))
    if (
        str(regime).upper() != "BANDS"
        or state.get("authenticated") is not True
        or not isinstance(artifact, Mapping)
    ):
        return projected
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    projected.update(
        {
            "encoding_status": "V4.7 HISTORICAL PROPERTIES STRESS SCREEN · HARDWARE BLOCKED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
            "v47_artifact_sha256": artifact.get("artifact_sha256"),
            "v47_candidate_routing_status": decisions.get("candidate_research_routing"),
            "v47_dated_properties_status": decisions.get("overall"),
            "v47_pareto_status": decisions.get("pareto_safe_replacement"),
            "v47_architecture_lower_bound_status": (
                "8/8 FAIL BOTH OPTIMISTIC SCREENS"
                if aggregate.get("all_eight_architecture_lower_bounds_fail_both_screens") is True
                else "NOT UNIFORMLY REJECTED"
            ),
        }
    )
    return projected


def render_v47_dated_properties_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    """Render the six-tab V4.7 evidence terminal without Vega charts."""

    state = normalize_v47_artifact(artifact, integrity=integrity)
    section_header(
        "V4.7 · Dated Properties & Fault-Excluded Routing",
        "EXACT V4.6 STREAMS → HISTORICAL PROPERTY REPLAY → ONE PREREGISTERED ROUTING CANDIDATE",
        "A fail-closed offline stress screen over pinned 2025-02-26 fake-backend properties. Duration is modeled, error mass is descriptive, and no current-backend or hardware claim is authorized.",
    )
    if state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        st.error(
            "V4.7 authentication failed. Property-conditioned duration, error-mass, "
            "optimization, Pareto, and decision outputs are masked fail-closed."
        )
        st.caption(
            "The V4.6 evidence surface remains authoritative until the V4.7 artifact and all "
            "post-result source identities are sealed and independently authenticated."
        )
        return state

    try:
        properties = load_property_oracle(root=_root())
    except Exception as exc:
        st.error(f"Authenticated artifact loaded, but property oracle display failed closed: {exc}")
        return {**state, "authenticated": False, "decision": "MASKED_FAIL_CLOSED"}

    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    snapshot = _mapping(artifact.get("properties_snapshot"))
    coverage = _mapping(properties.get("coverage"))
    fault_screen = _mapping(properties.get("fault_screen"))
    overall = str(decisions.get("overall") or "MASKED")
    architecture_rejected = bool(
        overall == EXPECTED_OVERALL_REJECTION
        and aggregate.get("all_eight_architecture_lower_bounds_fail_both_screens") is True
    )
    candidate_feasible = aggregate.get("all_eight_candidate_research_feasible") is True
    pareto_safe = aggregate.get("all_eight_pareto_safe") is True
    baseline_units = int(aggregate.get("baseline_total_unit_error_gate_occurrences", 0))
    candidate_units = int(aggregate.get("candidate_total_unit_error_gate_occurrences", 0))
    snapshot_date = str(snapshot.get("global_last_update_date") or "UNKNOWN")
    snapshot_day = snapshot_date[:10] if len(snapshot_date) >= 10 else snapshot_date
    native_tuple_count = int(coverage.get("native_gate_tuple_count", 0))
    expected_tuple_count = sum(
        int(value) for value in _mapping(coverage.get("expected_gate_counts")).values()
    )
    component_size = int(fault_screen.get("largest_component_size", 0))
    width_margin = int(fault_screen.get("width_margin", 0))

    st.markdown(
        f'''<div class="qv47-hero">
        <div class="qv47-k">AUTHENTICATED · RESEARCH_ONLY · HISTORICAL SNAPSHOT · ZERO PROVIDER / ZERO JOB</div>
        <div class="qv47-t">{'Architecture-level redesign required by this stress screen.' if architecture_rejected else 'Historical properties audit complete; hardware remains blocked.'}</div>
        <div class="qv47-s">The exact eight V4.6 streams were replayed against dated properties from <b>{escape(snapshot_date)}</b>. The baseline uses <b>{baseline_units:,}</b> occurrences on tuples reported with unit error; the fault-excluded candidate uses <b>{candidate_units:,}</b>. Neither result describes a current backend.</div>
        <div class="qv47-strip"><span>FIXED V4.6 · {'REJECTED BY SCREEN' if architecture_rejected else 'SCREEN COMPLETE'}</span><span>CANDIDATE · {'8/8 RESEARCH FEASIBLE' if candidate_feasible else 'NOT 8/8 FEASIBLE'}</span><span>PARETO · {'8/8' if pareto_safe else 'NOT DEMONSTRATED'}</span><span>HARDWARE · BLOCKED</span></div>
        </div>
        <style>
        .qv47-hero{{border:1px solid rgba(103,232,249,.27);border-radius:20px;padding:19px 21px;margin:8px 0 16px;background:radial-gradient(circle at 92% 8%,rgba(91,33,182,.19),transparent 37%),linear-gradient(122deg,rgba(3,21,34,.98),rgba(20,14,43,.97));box-shadow:0 0 46px rgba(34,211,238,.08)}}
        .qv47-k{{font-size:.61rem;letter-spacing:.16em;color:#67e8f9;font-weight:850}}.qv47-t{{font-size:1.18rem;line-height:1.28;color:#f8fafc;font-weight:850;margin:8px 0}}.qv47-s{{font-size:.77rem;line-height:1.55;color:#aabbd0;max-width:1120px}}.qv47-strip{{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}}.qv47-strip span{{border:1px solid rgba(148,163,184,.2);border-radius:999px;padding:5px 9px;background:rgba(15,23,42,.56);font-size:.58rem;letter-spacing:.075em;color:#cbd5e1;font-weight:760}}
        </style>''',
        unsafe_allow_html=True,
    )

    metric_columns = st.columns(6)
    metric_columns[0].metric("Snapshot", snapshot_day, "historical · not current")
    metric_columns[1].metric(
        "Native tuples",
        f"{native_tuple_count:,} / {expected_tuple_count:,}",
        "authenticated census",
    )
    metric_columns[2].metric(
        "Healthy component",
        f"{component_size} / 156",
        f"+{width_margin} vs max width",
    )
    metric_columns[3].metric(
        "Baseline unit-error uses",
        f"{baseline_units:,}",
        "rejected" if baseline_units else "none observed",
    )
    metric_columns[4].metric(
        "Candidate unit-error uses",
        f"{candidate_units:,}",
        "research gate requires 0",
    )
    metric_columns[5].metric(
        "Architecture screen",
        "8 / 8 FAIL" if architecture_rejected else "NOT UNIFORM",
        "optimistic lower bound",
    )
    st.warning(
        "Evidence boundary: the 2025 properties snapshot is historical; modeled makespan is not a "
        "pulse schedule; reported gate-error mass is not fidelity, success probability, expected "
        "failures, logical error, or solution quality; hardware_executable remains false."
    )

    properties_tab, duration_tab, error_tab, optimization_tab, provenance_tab, governance_tab = st.tabs(
        [
            "PROPERTIES",
            "DURATION MODEL",
            "ERROR MASS",
            "OPTIMIZATION / PARETO",
            "PROVENANCE",
            "GOVERNANCE",
        ]
    )

    with properties_tab:
        property_dates = _mapping(properties.get("property_time_range"))
        fault = _mapping(properties.get("fault_screen"))
        st.markdown("**Pinned historical property census**")
        st.caption(
            f"Global record date {property_dates.get('global_last_update_date')} · embedded field range "
            f"{property_dates.get('minimum_embedded_property_date')} → {property_dates.get('maximum_embedded_property_date')} · "
            "the global timestamp is not asserted as a cutoff for every field."
        )
        st.dataframe(_properties_gate_ledger(properties), width="stretch", hide_index=True)
        st.markdown("**Qubit-property context — not used as an acceptance model**")
        st.dataframe(_qubit_property_ledger(properties), width="stretch", hide_index=True)
        fault_columns = st.columns(4)
        fault_columns[0].metric("Directed CZ excluded", fault.get("excluded_directed_cz_edge_count"), "reported error = 1")
        fault_columns[1].metric(
            "Undirected links excluded",
            fault.get("excluded_undirected_cz_edge_count"),
            "both directed tuples excluded",
        )
        fault_columns[2].metric("Healthy component", fault.get("largest_component_size"), "of 156 qubits")
        fault_columns[3].metric("Isolated qubits", ", ".join(str(value) for value in fault.get("isolated_qubits") or []), "historical file")
        st.info(
            "Readout, T1 and T2 are retained for context. Readout is not applied because the V4.6 "
            "route IR contains no measurement operations. No missing tuple is imputed and no reverse-edge fallback is permitted."
        )

    with duration_tab:
        st.markdown("**Properties-conditioned integer-dt ASAP replay**")
        st.dataframe(_duration_ledger(artifact), width="stretch", hide_index=True)
        st.caption(
            "Each physical qubit has an integer clock at dt=4 ns. Native operations retain exact "
            "macro order; two-qubit CZ synchronizes both endpoint clocks. The model excludes pulses, "
            "crosstalk, concurrent-drive restrictions beyond shared qubits, dynamical decoupling, queue time and drift."
        )
        architecture_message = (
            "The optimistic architecture screen removes every SWAP and every one-qubit gate, gives "
            "each remaining CX the globally shortest CZ duration, and assumes 78-way CZ parallelism. "
            "Failure of that lower bound is a redesign signal for this fixed workload/model—not a theorem of impossibility."
        )
        if architecture_rejected:
            st.error(architecture_message)
        else:
            st.warning(architecture_message)

    with error_tab:
        st.markdown("**Exact occurrence-weighted reported gate-error mass**")
        st.error(
            "NON-FIDELITY METRIC — error mass is Σ occurrence_count × reported gate_error. It is not "
            "circuit fidelity, success probability, an expected number of failures, a logical error rate, or solution quality."
        )
        st.dataframe(_error_ledger(artifact), width="stretch", hide_index=True)
        st.markdown("**Aggregate attribution by native gate across all eight streams**")
        st.dataframe(_gate_error_ledger(artifact), width="stretch", hide_index=True)
        st.caption(
            "The baseline is fail-closed when even one exact used tuple carries reported error ≥1. "
            "The candidate is screened against zero such occurrences; that does not make it hardware-ready."
        )

    with optimization_tab:
        st.markdown(f"**Single preregistered candidate · {CANDIDATE_NAME}**")
        st.dataframe(_optimization_ledger(artifact), width="stretch", hide_index=True)
        decision_columns = st.columns(3)
        decision_columns[0].metric(
            "Candidate feasibility",
            "8 / 8 PASS" if candidate_feasible else "NOT 8 / 8",
            "research gate only",
        )
        decision_columns[1].metric(
            "Pareto-safe replacement",
            "8 / 8 PASS" if pareto_safe else "NOT DEMONSTRATED",
            "model-scoped",
        )
        decision_columns[2].metric(
            "Architecture lower bound",
            "8 / 8 FAIL" if architecture_rejected else "NOT UNIFORM",
            "both screens",
        )
        if pareto_safe:
            st.success(
                "The candidate is Pareto-safe across all eight seeds within the frozen V4.7 model: "
                "strictly lower descriptive error mass, no longer modeled makespan, and no more native CZ."
            )
        else:
            st.warning(
                "A Pareto-safe replacement was not demonstrated across all eight seeds. Local path "
                "tie-breaking has no global-optimality claim."
            )
        st.error(
            "Even a feasible or Pareto-safe routing candidate cannot override the architecture-level "
            "necessary-condition screen and never authorizes current provider discovery or execution."
        )

    with provenance_tab:
        provenance = _provenance_ledger(artifact)
        st.dataframe(provenance, width="stretch", hide_index=True)
        artifact_bytes = _sealed_download_bytes(
            default_v47_ui_artifact_path(), EXPECTED_ARTIFACT_RAW_SHA256
        )
        if artifact_bytes is None:
            st.error("Exact artifact download was suppressed because its raw identity changed.")
        else:
            st.download_button(
                "Download sealed V4.7 artifact",
                data=artifact_bytes,
                file_name=DEFAULT_ARTIFACT_NAME,
                mime="application/json",
                key=f"{key_prefix}_v47_artifact",
            )
        for label, filename, expected_raw_sha256 in (
            ("Download V4.7 preregistration", SPEC_FILENAME, EXPECTED_SPEC_RAW_SHA256),
            (
                "Download normalized dated properties",
                PROPERTIES_FILENAME,
                EXPECTED_PROPERTIES_RAW_SHA256,
            ),
            (
                "Download duration/error model contract",
                MODEL_FILENAME,
                EXPECTED_MODEL_RAW_SHA256,
            ),
            (
                "Download fault-excluded path oracle",
                PATH_ORACLE_FILENAME,
                EXPECTED_PATH_ORACLE_RAW_SHA256,
            ),
            (
                "Download raw dated properties",
                RAW_PROPERTIES_FILENAME,
                EXPECTED_RAW_PROPERTIES_SHA256,
            ),
        ):
            path = _root() / "quantum_research_lab" / filename
            evidence_bytes = _sealed_download_bytes(path, expected_raw_sha256)
            if evidence_bytes is None:
                st.error(f"{label} suppressed: raw identity mismatch.")
            else:
                st.download_button(
                    label,
                    data=evidence_bytes,
                    file_name=filename,
                    mime="application/json",
                    key=f"{key_prefix}_v47_{filename}",
                )
        st.caption(
            f"Artifact {_short_sha(artifact.get('artifact_sha256'))} · "
            f"{EXPECTED_UI_AUTH_CHECK_COUNT}/{EXPECTED_UI_AUTH_CHECK_COUNT} UI authentication gates · "
            f"{EXPECTED_INDEPENDENT_CHECK_COUNT}/{EXPECTED_INDEPENDENT_CHECK_COUNT} independent scientific checks"
        )

    with governance_tab:
        st.markdown("**Decision ledger**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Decision": label, "Value": decisions.get(field)}
                    for label, field in (
                        ("Overall", "overall"),
                        ("Fixed architecture", "fixed_architecture_historical_stress_screen"),
                        ("V4.6 baseline", "baseline_dated_properties"),
                        ("Candidate", "candidate_research_routing"),
                        ("Pareto", "pareto_safe_replacement"),
                        ("Production", "production_admission"),
                        ("Next falsifiable gate", "next_falsifiable_gate"),
                    )
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.markdown("**Forbidden from this surface**")
        for index, label in enumerate(
            (
                "Rebuild or mutate the sealed V4.7 artifact",
                "Replace the exact V4.6 baseline commitments",
                "Select a post-result routing candidate",
                "Impute a missing property or reverse a directed CZ tuple",
                "Interpret additive error mass as fidelity or success probability",
                "Interpret integer-dt ASAP makespan as pulse or wall-clock runtime",
                "Treat dated fake-backend properties as current calibration",
                "Read provider credentials or discover live backends",
                "Submit a simulator, backend, or QPU job",
                "Claim hardware readiness, utility, or quantum advantage",
            )
        ):
            st.button(label, disabled=True, key=f"{key_prefix}_v47_forbidden_{index}")
        st.error(f"Production admission: {decisions.get('production_admission')}")
        st.info(f"Next falsifiable gate: {decisions.get('next_falsifiable_gate')}")

    return state


__all__ = [
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CHECKER_RAW_SHA256",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "apply_v47_encoding_state",
    "default_v47_ui_artifact_path",
    "load_v47_ui_artifact",
    "normalize_v47_artifact",
    "render_v47_dated_properties_panel",
]
