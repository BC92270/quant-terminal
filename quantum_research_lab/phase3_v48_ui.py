"""Institutional fail-closed evidence surface for Quantum Lab V4.8."""

from __future__ import annotations

import copy
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v48_independent_checker import (
    EXPECTED_CHECK_COUNT as EXPECTED_INDEPENDENT_CHECK_COUNT,
    canonical_json_sha256,
    raw_file_sha256,
    read_json_strict,
    validate_v48_artifact,
)


SectionHeader = Callable[[str, str, str], None]

EXPECTED_ARTIFACT_RAW_SHA256 = "f6fcce00b9ce95cd9e30eeb938e243c308b5408255dc98556e8be45a36691f76"
EXPECTED_ARTIFACT_SHA256 = "6df8440320e38e0bb73674f3ceb0f4bc179385d0d344c9521fa35f197504c55f"
EXPECTED_SOURCE_RAW_SHA256 = "0bef3609b7c535b13cd25254a8c322f7d1c207b4111549e5b86bd5ff2e9ea0e9"
EXPECTED_CHECKER_RAW_SHA256 = "1435e1c4efb61c30e884e87132ec39f30f1206c96332e3802c19dd0a42269f3c"
EXPECTED_SPEC_RAW_SHA256 = "93a1b8744323b1dfffa86c4019cc30c6e83dd696ee88eab2f8174c821b2707fd"
EXPECTED_SPEC_SHA256 = "2f5874030f433d1bd542804a20208d42276127d5e79851daf00d6d1d39db46b2"
EXPECTED_CATALOG_RAW_SHA256 = "7a5c8cf6a4a33f0f32ce5ea1ba0df7c45ee5c35d343eebc86ba174470a77be53"
EXPECTED_CATALOG_SHA256 = "9a585764e2de35edcd66695da7abfea9726785c06065133170917d8587341ef6"
EXPECTED_SNAPSHOTS_RAW_SHA256 = "54c5cf463ec0c2fa591864ed595fac26a7c0a9e279f47a41942ad4073da5af5e"
EXPECTED_SNAPSHOTS_SHA256 = "8364f86f0360fff5938eed57d926a8c5d6a960bc8639300a7f366f46bf940da5"
EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256 = "6fbe442d0ce00b88ee7f74113b51f5375b939ca34459e68e37d94e8da880a72d"
EXPECTED_ARCHITECTURE_ORACLE_SHA256 = "689c6b5ac55703ea869abc4087245bc6a13f1ab35cc5e5eab8c86dc49ffaac6a"
EXPECTED_MODEL_RAW_SHA256 = "a8fe16d0810aede0348bdb4010d9fbab5fa7736438df71782351436a54ad05cb"
EXPECTED_MODEL_SHA256 = "58f7e2c84ecf138ed26912950055a083202ce4e7f7e4407eaf2898ae6f6ee1b6"

EXPECTED_UI_AUTH_CHECK_COUNT = 24
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_OVERALL = (
    "V48_EXACT_ARCHITECTURE_CX_AND_BASICSWAP_CZ_REDUCTION_DEMONSTRATED_"
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_HARDWARE_REJECTED"
)
EXPECTED_PRODUCTION = "RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED"
EXPECTED_MULTI_SNAPSHOT = (
    "MULTI_SNAPSHOT_ROBUSTNESS_NOT_EVALUABLE_"
    "INSUFFICIENT_DISTINCT_AUTHENTIC_SNAPSHOT_IDENTITIES"
)
EXPECTED_NEXT_GATE = (
    "ACQUIRE_TWO_ADDITIONAL_AUTHENTIC_OFFLINE_SNAPSHOT_EPOCHS_AND_REDUCE_"
    "DIRECT_CX_BELOW_BOTH_HISTORICAL_NECESSARY_THRESHOLDS_BEFORE_ANY_"
    "CURRENT_PROVIDER_DISCOVERY"
)

ARTIFACT_RELATIVE = (
    "outputs/quantum_phase3/v48_multi_snapshot_architecture/"
    "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"
)
SPEC_FILENAME = "PHASE_III_V4_8_MULTI_SNAPSHOT_CZ_REDUCTION_SPEC_V1.json"
CATALOG_FILENAME = "PHASE_III_V4_8_SNAPSHOT_CATALOG_V1.json"
SNAPSHOTS_FILENAME = "PHASE_III_V4_8_NORMALIZED_SNAPSHOTS_ORACLE_V1.json"
ARCHITECTURE_ORACLE_FILENAME = "PHASE_III_V4_8_ARCHITECTURE_CANDIDATE_ORACLE_V1.json"
MODEL_FILENAME = "PHASE_III_V4_8_ROBUSTNESS_COST_MODEL_V1.json"


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


def _self_hash(payload: Mapping[str, Any], field: str, *, short_field: str | None = None) -> bool:
    excluded = {field}
    if short_field:
        excluded.add(short_field)
    return payload.get(field) == canonical_json_sha256(
        {key: value for key, value in payload.items() if key not in excluded}
    )


def default_v48_ui_artifact_path() -> Path:
    return _root() / ARTIFACT_RELATIVE


def _load_exact(relative: str, raw_sha256: str) -> tuple[dict[str, Any], Path]:
    path = _root() / "quantum_research_lab" / relative
    if not path.is_file() or path.is_symlink() or raw_file_sha256(path) != raw_sha256:
        raise ValueError(f"Raw evidence identity mismatch: {relative}")
    return read_json_strict(path), path


def _validate_v48_ui_artifact(raw: bytes, artifact_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        artifact = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=lambda pairs: _strict_pairs(pairs),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
        if not isinstance(artifact, dict):
            raise ValueError("Artifact is not an object")
        spec, spec_path = _load_exact(SPEC_FILENAME, EXPECTED_SPEC_RAW_SHA256)
        catalog, catalog_path = _load_exact(CATALOG_FILENAME, EXPECTED_CATALOG_RAW_SHA256)
        snapshots, snapshots_path = _load_exact(SNAPSHOTS_FILENAME, EXPECTED_SNAPSHOTS_RAW_SHA256)
        model, model_path = _load_exact(MODEL_FILENAME, EXPECTED_MODEL_RAW_SHA256)
        architecture, architecture_path = _load_exact(
            ARCHITECTURE_ORACLE_FILENAME, EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256
        )
        independent = validate_v48_artifact(
            artifact,
            root=_root(),
            artifact_raw_file_sha256=hashlib.sha256(raw).hexdigest(),
            expected_artifact_raw_sha256=EXPECTED_ARTIFACT_RAW_SHA256,
            expected_artifact_sha256=EXPECTED_ARTIFACT_SHA256,
        )
    except Exception as exc:
        return {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_authenticated_load"],
            "valid": False,
        }

    source_path = _root() / "quantum_research_lab/phase3_v48_multi_snapshot_architecture_optimizer.py"
    checker_path = _root() / "quantum_research_lab/phase3_v48_independent_checker.py"
    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    boundary = _mapping(artifact.get("claim_boundary"))
    reference = _mapping(artifact.get("reference_contracts"))
    parent = _mapping(artifact.get("parent"))
    seeds = _rows(artifact.get("seed_evaluations"))
    checks: dict[str, bool] = {
        "artifact_regular": artifact_path.is_file() and not artifact_path.is_symlink(),
        "artifact_raw": hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and _self_hash(artifact, "artifact_sha256"),
        "artifact_version": artifact.get("artifact_version") == "PHASE III · V4.8 SEALED MULTI-SNAPSHOT / ARCHITECTURE ARTIFACT · V1",
        "optimizer_source": source_path.is_file() and not source_path.is_symlink() and raw_file_sha256(source_path) == EXPECTED_SOURCE_RAW_SHA256,
        "independent_checker_source": checker_path.is_file() and not checker_path.is_symlink() and raw_file_sha256(checker_path) == EXPECTED_CHECKER_RAW_SHA256,
        "artifact_optimizer_crosslink": artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256,
        "artifact_checker_crosslink": artifact.get("independent_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256,
        "spec_identity": _self_hash(spec, "v48_spec_sha256") and spec.get("v48_spec_sha256") == EXPECTED_SPEC_SHA256 and reference.get("multi_snapshot_spec_raw_file_sha256") == raw_file_sha256(spec_path),
        "catalog_identity": _self_hash(catalog, "snapshot_catalog_sha256") and catalog.get("snapshot_catalog_sha256") == EXPECTED_CATALOG_SHA256 and reference.get("snapshot_catalog_raw_file_sha256") == raw_file_sha256(catalog_path),
        "snapshots_identity": _self_hash(snapshots, "normalized_snapshots_oracle_sha256") and snapshots.get("normalized_snapshots_oracle_sha256") == EXPECTED_SNAPSHOTS_SHA256 and reference.get("normalized_snapshots_oracle_raw_file_sha256") == raw_file_sha256(snapshots_path),
        "model_identity": _self_hash(model, "robustness_cost_model_sha256") and model.get("robustness_cost_model_sha256") == EXPECTED_MODEL_SHA256 and reference.get("robustness_cost_model_raw_file_sha256") == raw_file_sha256(model_path),
        "architecture_oracle_identity": _self_hash(architecture, "v48_spec_sha256", short_field="v48_spec_sha") and architecture.get("v48_spec_sha256") == EXPECTED_ARCHITECTURE_ORACLE_SHA256 and reference.get("architecture_candidate_oracle_raw_file_sha256") == raw_file_sha256(architecture_path),
        "independent_checker_valid": independent.get("valid") is True,
        "independent_checker_65": independent.get("check_count") == EXPECTED_INDEPENDENT_CHECK_COUNT == 65,
        "parent_lineage": parent.get("v47_artifact_sha256") == "fa1b8a2be1471080134f34ada7ba8cff488c87077a4e5f271fd29828f1fffbaf" and parent.get("v47_freeze_sha256") == "3f870a5ff89368d2000a58533fba395b0d077cc377cdc830fdc4b362f6465858",
        "seed_order": tuple(int(row.get("seed", -1)) for row in seeds) == EXPECTED_SEEDS,
        "aggregate_commitment": _self_hash(aggregate, "aggregate_sha256") and aggregate.get("seed_count") == 8,
        "decisions_exact": decisions.get("overall") == EXPECTED_OVERALL and decisions.get("production_admission") == EXPECTED_PRODUCTION and decisions.get("multi_snapshot_robustness") == EXPECTED_MULTI_SNAPSHOT and decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "claim_boundary": boundary.get("research_classification") == "RESEARCH_ONLY" and boundary.get("hardware_executable") is False and boundary.get("snapshot_is_current_hardware_evidence") is False and all(boundary.get(key) == 0 for key in ("provider_calls", "network_calls", "backend_run_calls", "local_simulator_jobs_submitted", "qpu_jobs_submitted")),
        "single_snapshot": (catalog.get("counts") or {}).get("distinct_epoch_count") == 1 and aggregate.get("multi_snapshot_distinct_authentic_snapshot_count") == 1,
        "zero_aliases": catalog.get("aliases") == [] and (catalog.get("counts") or {}).get("admitted_alias_count") == 0,
        "reductions_exact": aggregate.get("aggregate_parent_v45_cx") == 19_251_104 and aggregate.get("aggregate_candidate_cx") == 6_474_096 and aggregate.get("aggregate_parent_v46_basic_swap_cz") == 119_029_964 and aggregate.get("aggregate_candidate_basic_swap_cz") == 59_565_732,
        "necessary_screens_retained": aggregate.get("all_eight_architecture_lower_bounds_pass_duration_screen") is False and aggregate.get("all_eight_architecture_lower_bounds_pass_reported_error_mass_screen") is False,
    }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        errors.append(f"UI authentication count drift: {len(checks)}")
    failed = [name for name, value in checks.items() if value is not True]
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": errors + list(independent.get("errors") or []),
        "failed_checks": failed + list(independent.get("failed_checks") or []),
        "independent_checker": independent,
        "valid": not errors and not failed and independent.get("valid") is True,
    }


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_v48_ui_artifact(
    path: str | Path | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v48_ui_artifact_path()
    if not target.is_absolute():
        target = _root() / target
    try:
        raw = target.read_bytes()
        report = _validate_v48_ui_artifact(raw, target)
        artifact = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_pairs)
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["artifact_load"],
            "valid": False,
        }
    return artifact if report.get("valid") else None, report


def normalize_v48_artifact(
    artifact: Mapping[str, Any] | None,
    *,
    integrity: bool | None,
) -> dict[str, Any]:
    if integrity is not True or not isinstance(artifact, Mapping):
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
        "aggregate_candidate_basic_swap_cz": aggregate.get("aggregate_candidate_basic_swap_cz"),
        "aggregate_candidate_cx": aggregate.get("aggregate_candidate_cx"),
        "decision": decisions.get("overall"),
        "hardware_executable": False,
        "multi_snapshot_robustness": decisions.get("multi_snapshot_robustness"),
        "production_admission": decisions.get("production_admission"),
        "research_classification": "RESEARCH_ONLY",
        "seed_count": aggregate.get("seed_count"),
    }


def apply_v48_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(encoding or {}))
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        return projected
    decisions = _mapping(artifact.get("decisions"))
    aggregate = _mapping(artifact.get("aggregate"))
    projected.update(
        {
            "encoding_status": "V4.8 EXACT ARCHITECTURE REDUCTION · MULTI-SNAPSHOT BLOCKED · HARDWARE BLOCKED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
            "v48_artifact_sha256": artifact.get("artifact_sha256"),
            "v48_architecture_status": decisions.get("architecture_candidate"),
            "v48_dated_properties_status": decisions.get("overall"),
            "v48_multi_snapshot_status": decisions.get("multi_snapshot_robustness"),
            "v48_candidate_cx": aggregate.get("aggregate_candidate_cx"),
            "v48_candidate_basic_swap_cz": aggregate.get("aggregate_candidate_basic_swap_cz"),
        }
    )
    return projected


def _architecture_table(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in _rows(artifact.get("seed_evaluations")):
        comparison = _mapping(row.get("comparison"))
        native = _mapping(_mapping(_mapping(row.get("structural_routing")).get("routed_compilation")).get("native_ledger"))
        rows.append(
            {
                "Seed": row.get("seed"),
                "Logical Q": row.get("logical_qubits"),
                "Parent CX": comparison.get("parent_v45_cx"),
                "V4.8 CX": comparison.get("candidate_cx"),
                "CX reduction": f"{int(comparison.get('cx_reduction_basis_points', 0)) / 100:.2f}%",
                "Parent CZ": comparison.get("parent_v46_basic_swap_cz"),
                "V4.8 CZ": comparison.get("candidate_basic_swap_cz"),
                "CZ reduction": f"{int(comparison.get('basic_swap_cz_reduction_basis_points', 0)) / 100:.2f}%",
                "Structural depth": native.get("asap_structural_depth"),
            }
        )
    return pd.DataFrame(rows)


def _frontier_table(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in _rows(artifact.get("seed_evaluations")):
        lower = _mapping(row.get("architecture_lower_bound_v47_comparable"))
        rows.append(
            {
                "Seed": row.get("seed"),
                "Direct CX": lower.get("direct_translated_cx"),
                "Optimistic error mass": lower.get("optimistic_reported_error_mass_lower_bound"),
                "Error screen": "PASS" if lower.get("passes_reported_error_mass_screen") else "FAIL",
                "Optimistic duration ticks": lower.get("optimistic_cz_duration_lower_bound_ticks"),
                "Duration / max T2": f"{float(lower.get('optimistic_cz_duration_over_maximum_snapshot_t2', 0)):.3f}×",
                "Duration screen": "PASS" if lower.get("passes_duration_screen") else "FAIL",
            }
        )
    return pd.DataFrame(rows)


def _download(path: Path, expected: str) -> bytes | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return raw if path.is_file() and not path.is_symlink() and hashlib.sha256(raw).hexdigest() == expected else None


def render_v48_multi_snapshot_architecture_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    state = normalize_v48_artifact(artifact, integrity=integrity)
    section_header(
        "V4.8 · Architecture Reduction & Snapshot Governance",
        "EXACT CONTROL-LOADED ADDER → 8 MATERIALIZED STREAMS → FROZEN BASICSWAP REPLAY → FAIL-CLOSED ROBUSTNESS",
        "A proof-carrying architecture reduction with a strict distinction between one historical development snapshot and genuine multi-epoch robustness.",
    )
    if state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        st.error("V4.8 authentication failed. Every architecture, robustness and frontier result is masked fail-closed.")
        return state

    aggregate = _mapping(artifact.get("aggregate"))
    decisions = _mapping(artifact.get("decisions"))
    equivalence = _mapping(artifact.get("equivalence_evidence"))
    catalog = read_json_strict(_root() / "quantum_research_lab" / CATALOG_FILENAME)
    snapshots = _mapping(catalog.get("snapshots"))
    cx_before = int(aggregate.get("aggregate_parent_v45_cx", 0))
    cx_after = int(aggregate.get("aggregate_candidate_cx", 0))
    cz_before = int(aggregate.get("aggregate_parent_v46_basic_swap_cz", 0))
    cz_after = int(aggregate.get("aggregate_candidate_basic_swap_cz", 0))

    st.markdown(
        f'''<div class="qv48-hero">
        <div class="qv48-k">AUTHENTICATED · RESEARCH_ONLY · EXACT STREAMS 8/8 · ZERO PROVIDER / ZERO JOB</div>
        <div class="qv48-t">Architecture cost falls sharply; hardware admission still remains rejected.</div>
        <div class="qv48-s">The exact control-loaded Cuccaro candidate reduces logical CX from <b>{cx_before:,}</b> to <b>{cx_after:,}</b> and frozen-BasicSwap CZ from <b>{cz_before:,}</b> to <b>{cz_after:,}</b>. Only one authentic historical snapshot identity exists, and both optimistic V4.7-comparable necessary screens still fail on all eight seeds.</div>
        <div class="qv48-strip"><span>ARCHITECTURE · 8/8 PASS</span><span>ROUTING · 8/8 PASS</span><span>MULTI-SNAPSHOT · NOT EVALUABLE</span><span>HARDWARE · BLOCKED</span></div>
        </div>
        <style>
        .qv48-hero{{border:1px solid rgba(45,212,191,.30);border-radius:21px;padding:20px 22px;margin:8px 0 16px;background:radial-gradient(circle at 88% 12%,rgba(8,145,178,.20),transparent 36%),linear-gradient(125deg,rgba(3,22,28,.99),rgba(13,18,39,.98));box-shadow:0 0 52px rgba(45,212,191,.08)}}
        .qv48-k{{font-size:.61rem;letter-spacing:.16em;color:#5eead4;font-weight:850}}.qv48-t{{font-size:1.2rem;line-height:1.3;color:#f8fafc;font-weight:850;margin:8px 0}}.qv48-s{{font-size:.78rem;line-height:1.58;color:#aec4d6;max-width:1140px}}.qv48-strip{{display:flex;gap:8px;flex-wrap:wrap;margin-top:13px}}.qv48-strip span{{border:1px solid rgba(148,163,184,.2);border-radius:999px;padding:5px 9px;background:rgba(15,23,42,.58);font-size:.58rem;letter-spacing:.075em;color:#d7e5ed;font-weight:780}}
        </style>''',
        unsafe_allow_html=True,
    )
    metrics = st.columns(6)
    metrics[0].metric("Exact streams", "8 / 8", "materialized")
    metrics[1].metric("CX total", f"{cx_after:,}", f"−{(cx_before-cx_after)/cx_before:.2%}")
    metrics[2].metric("BasicSwap CZ", f"{cz_after:,}", f"−{(cz_before-cz_after)/cz_before:.2%}")
    metrics[3].metric("Max depth", f"{int(aggregate.get('maximum_candidate_structural_depth', 0)):,}", "structural · not runtime")
    metrics[4].metric("Authentic epochs", "1 / 3", "robustness blocked")
    metrics[5].metric("Equivalence", f"{int(equivalence.get('case_count', 0)):,}", "all exact")
    st.warning(
        "A lower gate count is not hardware readiness. The single dated fake-backend snapshot is not current calibration; the additive error-mass and integer-dt duration screens are model diagnostics, not fidelity or runtime."
    )

    registry_tab, robustness_tab, architecture_tab, frontier_tab, provenance_tab, governance_tab = st.tabs(
        ["SNAPSHOT REGISTRY", "ROBUSTNESS", "ARCHITECTURE / CZ", "FRONTIER", "PROVENANCE", "GOVERNANCE"]
    )
    with registry_tab:
        st.markdown("**Authenticated snapshot identity registry**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Snapshot ID": row.get("snapshot_id"),
                        "Backend": row.get("backend_name"),
                        "Global date": row.get("global_last_update_date"),
                        "Raw SHA-256": row.get("raw_properties_raw_file_sha256"),
                        "Role": row.get("role"),
                        "Current evidence": "NO",
                    }
                    for row in _rows(catalog.get("snapshots"))
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        st.error("Only one distinct authentic epoch is available. Copies, normalized representations, archive members and synthetic perturbations do not increase the sample size.")

    with robustness_tab:
        st.markdown("**Fail-closed robustness admission**")
        st.error(EXPECTED_MULTI_SNAPSHOT)
        st.write(
            "The sealed protocol requires at least three distinct raw identities, property-vector identities and epochs from the same target family. Every admitted snapshot × seed cell must pass; averaging cannot rescue a failed cell."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"Requirement": "Distinct authentic epochs", "Required": 3, "Observed": 1, "Status": "BLOCKED"},
                    {"Requirement": "Admitted aliases", "Required": 0, "Observed": 0, "Status": "PASS"},
                    {"Requirement": "Synthetic substitutions", "Required": 0, "Observed": 0, "Status": "PASS"},
                    {"Requirement": "Current-provider calls", "Required": 0, "Observed": 0, "Status": "PASS"},
                ]
            ),
            width="stretch",
            hide_index=True,
        )

    with architecture_tab:
        st.markdown("**Materialized logical and routed resource ledger**")
        st.dataframe(_architecture_table(artifact), width="stretch", hide_index=True)
        st.success("Every seed strictly reduces both logical CX and frozen-BasicSwap native CZ with zero ISA or coupling violations.")
        st.caption("Changed primitive only: controlled constant addition. Width, coin rings, Bennett SELECT structure, certified bridges and routing path oracle remain inherited and authenticated.")

    with frontier_tab:
        st.markdown("**V4.7-comparable optimistic necessary-condition frontier**")
        st.dataframe(_frontier_table(artifact), width="stretch", hide_index=True)
        st.error("Despite the large reduction, the impossible-best-case zero-SWAP/zero-1Q lower bound still fails the optimistic duration screen and the optimistic error screen for all eight seeds. A deeper architecture reduction remains necessary.")
        st.code(decisions.get("next_falsifiable_gate", "MASKED"))

    with provenance_tab:
        st.markdown("**Sealed identities and gated downloads**")
        provenance = pd.DataFrame(
            [
                {"Evidence": "Artifact raw", "SHA-256": EXPECTED_ARTIFACT_RAW_SHA256},
                {"Evidence": "Artifact semantic", "SHA-256": EXPECTED_ARTIFACT_SHA256},
                {"Evidence": "Optimizer source", "SHA-256": EXPECTED_SOURCE_RAW_SHA256},
                {"Evidence": "Independent checker", "SHA-256": EXPECTED_CHECKER_RAW_SHA256},
                {"Evidence": "Protocol", "SHA-256": EXPECTED_SPEC_RAW_SHA256},
                {"Evidence": "Snapshot catalog", "SHA-256": EXPECTED_CATALOG_RAW_SHA256},
                {"Evidence": "Normalized cohort", "SHA-256": EXPECTED_SNAPSHOTS_RAW_SHA256},
                {"Evidence": "Architecture oracle", "SHA-256": EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256},
                {"Evidence": "Robustness model", "SHA-256": EXPECTED_MODEL_RAW_SHA256},
            ]
        )
        st.dataframe(provenance, width="stretch", hide_index=True)
        downloads = [
            ("Download sealed V4.8 artifact", default_v48_ui_artifact_path(), EXPECTED_ARTIFACT_RAW_SHA256, "SEALED_V4_8_MULTI_SNAPSHOT_ARCHITECTURE_ARTIFACT.json"),
            ("Download V4.8 protocol", _root() / "quantum_research_lab" / SPEC_FILENAME, EXPECTED_SPEC_RAW_SHA256, SPEC_FILENAME),
            ("Download snapshot registry", _root() / "quantum_research_lab" / CATALOG_FILENAME, EXPECTED_CATALOG_RAW_SHA256, CATALOG_FILENAME),
            ("Download normalized snapshot cohort", _root() / "quantum_research_lab" / SNAPSHOTS_FILENAME, EXPECTED_SNAPSHOTS_RAW_SHA256, SNAPSHOTS_FILENAME),
            ("Download architecture candidate oracle", _root() / "quantum_research_lab" / ARCHITECTURE_ORACLE_FILENAME, EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256, ARCHITECTURE_ORACLE_FILENAME),
            ("Download robustness cost model", _root() / "quantum_research_lab" / MODEL_FILENAME, EXPECTED_MODEL_RAW_SHA256, MODEL_FILENAME),
        ]
        columns = st.columns(2)
        for index, (label, path, expected, filename) in enumerate(downloads):
            payload = _download(path, expected)
            columns[index % 2].download_button(
                label,
                data=payload or b"",
                file_name=filename,
                mime="application/json",
                disabled=payload is None,
                key=f"{key_prefix}_v48_download_{index}",
            )

    with governance_tab:
        st.markdown("**Immutable decision and execution controls**")
        actions = (
            "Rebuild or mutate the sealed V4.8 artifact",
            "Count a copied snapshot as a new calibration epoch",
            "Substitute synthetic stress data for an authentic snapshot",
            "Relabel the historical development snapshot as a holdout",
            "Change the preregistered architecture after observing results",
            "Interpret additive error mass as circuit fidelity",
            "Interpret structural or integer-dt depth as wall-clock runtime",
            "Read provider credentials or discover a live backend",
            "Submit a simulator, backend, or QPU job",
            "Claim hardware readiness, utility, or quantum advantage",
        )
        for index, label in enumerate(actions):
            st.button(label, disabled=True, key=f"{key_prefix}_v48_governance_{index}")
        st.error("Production admission: RESEARCH_ONLY_HARDWARE_EXECUTION_REJECTED")
        st.caption("Provider SDK imports, credential reads, provider/network/backend calls, simulator jobs and QPU jobs are all zero.")
    return state


__all__ = [
    "ARCHITECTURE_ORACLE_FILENAME",
    "CATALOG_FILENAME",
    "EXPECTED_ARCHITECTURE_ORACLE_RAW_SHA256",
    "EXPECTED_ARTIFACT_RAW_SHA256",
    "EXPECTED_ARTIFACT_SHA256",
    "EXPECTED_CATALOG_RAW_SHA256",
    "EXPECTED_CHECKER_RAW_SHA256",
    "EXPECTED_INDEPENDENT_CHECK_COUNT",
    "EXPECTED_MODEL_RAW_SHA256",
    "EXPECTED_MULTI_SNAPSHOT",
    "EXPECTED_NEXT_GATE",
    "EXPECTED_OVERALL",
    "EXPECTED_PRODUCTION",
    "EXPECTED_SNAPSHOTS_RAW_SHA256",
    "EXPECTED_SOURCE_RAW_SHA256",
    "EXPECTED_SPEC_RAW_SHA256",
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "MODEL_FILENAME",
    "SNAPSHOTS_FILENAME",
    "SPEC_FILENAME",
    "apply_v48_encoding_state",
    "default_v48_ui_artifact_path",
    "load_v48_ui_artifact",
    "normalize_v48_artifact",
    "render_v48_multi_snapshot_architecture_panel",
]
