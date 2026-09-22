"""Fail-closed institutional evidence surface for Quantum Lab V4.6."""

from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
from html import escape
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd
import streamlit as st

from .phase3_v46_full_stream_routing import (
    EXPECTED_PATH_ORACLE_RAW_SHA256,
    EXPECTED_PATH_ORACLE_SHA256,
    EXPECTED_SPEC_RAW_SHA256,
    EXPECTED_SPEC_SHA256,
    EXPECTED_TRANSLATION_RAW_SHA256,
    EXPECTED_TRANSLATION_SHA256,
    SPEC_FILENAME,
    authenticate_v45_parent,
    canonical_json_sha256,
    load_path_oracle,
    load_translation_contract,
    load_v46_spec,
    raw_file_sha256,
)
from .phase3_v46_independent_checker import validate_v46_artifact


SectionHeader = Callable[[str, str, str], None]

EXPECTED_ARTIFACT_RAW_SHA256 = "24a55be0ea90242318642b3db7fd00997a71bd8ce896a73e7118f12e65ce6694"
EXPECTED_ARTIFACT_SHA256 = "cbf478af42b35502d4788f70aa96df836145d8e34dadf0c14f2426c241323832"
EXPECTED_SOURCE_RAW_SHA256 = "3e3ab6162fc42e9581adb0510a0385c3b9e7a1c87691e01017a763e0afae1885"
EXPECTED_CHECKER_RAW_SHA256 = "87aa13cc0ea534bdf784bd53663477983cb4cabd02c1c1ed8ea84eb55c1024b7"
EXPECTED_UI_AUTH_CHECK_COUNT = 30
EXPECTED_SEEDS = (1103, 2207, 3301, 4409, 5501, 6607, 7703, 8807)
EXPECTED_WIDTHS = (135, 137, 133, 135, 137, 137, 145, 139)
EXPECTED_INPUT_COUNTS = (6077566, 6086776, 5969118, 5969230, 5969310, 6077382, 6312490, 6185342)
EXPECTED_SWAPS = (4144702, 4169221, 4072600, 4067511, 4080645, 4149075, 4342669, 4233197)
EXPECTED_NATIVE_CZ = (14839144, 14916301, 14579062, 14563795, 14603197, 14852263, 15527797, 15148405)
EXPECTED_DEPTHS = (23878539, 23925669, 23449597, 23416448, 23436098, 23876346, 24893376, 24375938)
EXPECTED_NATIVE_INSTRUCTIONS = (59482464, 59736353, 58434154, 58388465, 58506751, 59521637, 62128995, 60677639)
EXPECTED_OVERALL = "V46_FAKEMARRAKESH_FULL_STREAM_ROUTING_PASSED_STRUCTURAL_AND_PREREGISTERED_RESOURCE_GATES"
EXPECTED_PRODUCTION = "OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED"
EXPECTED_NEXT_GATE = "PINNED_DATED_PROPERTIES_DURATION_ERROR_AND_OPTIMIZATION_FEASIBILITY_OF_V46_ROUTED_STREAMS"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        return []
    return [dict(row) for row in value]


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
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError(f"Non-finite JSON number: {token}")),
    )
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
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


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_v46_ui_artifact_path() -> Path:
    return _root() / "outputs/quantum_phase3/v46_full_stream_routing/SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json"


def _validate_v46_ui_artifact(raw: bytes, *, root: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        artifact = _decode_json_strict(raw)
        spec = load_v46_spec(root=root)
        oracle, _ = load_path_oracle(root=root)
        translation = load_translation_contract(root=root)
        parent = authenticate_v45_parent(root=root)
        independent = validate_v46_artifact(artifact, root=root)
    except Exception as exc:
        return {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["strict_authenticated_load"],
            "valid": False,
        }
    rows = _rows(artifact.get("seed_routings"))
    decisions = _mapping(artifact.get("decisions"))
    aggregate = _mapping(artifact.get("aggregate"))
    boundary = _mapping(artifact.get("claim_boundary"))
    references = _mapping(artifact.get("reference_contracts"))
    input_manifests = [_mapping((_mapping(row.get("routed_compilation"))).get("input_stream_manifest")) for row in rows]
    native_ledgers = [_mapping((_mapping(row.get("routed_compilation"))).get("native_ledger")) for row in rows]
    route_ledgers = [_mapping((_mapping(row.get("routed_compilation"))).get("route_ir")) for row in rows]
    layouts = [_mapping((_mapping(row.get("routed_compilation"))).get("layout")) for row in rows]
    resources = [_mapping(row.get("resource_gate")) for row in rows]
    native_cz = [int((_mapping(row.get("native_operation_counts"))).get("cz", -1)) for row in native_ledgers]
    source = root / "quantum_research_lab/phase3_v46_full_stream_routing.py"
    checker = root / "quantum_research_lab/phase3_v46_independent_checker.py"
    spec_path = root / "quantum_research_lab" / SPEC_FILENAME
    oracle_path = root / "quantum_research_lab/PHASE_III_V4_6_FAKEMARRAKESH_BASIC_PATH_ORACLE_V1.json"
    translation_path = root / "quantum_research_lab/PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json"
    checks: dict[str, bool] = {
        "artifact_raw_identity": hashlib.sha256(raw).hexdigest() == EXPECTED_ARTIFACT_RAW_SHA256,
        "artifact_semantic_identity": artifact.get("artifact_sha256") == EXPECTED_ARTIFACT_SHA256 and _self_hash(artifact, "artifact_sha256"),
        "source_identity": source.is_file() and raw_file_sha256(source) == EXPECTED_SOURCE_RAW_SHA256,
        "checker_identity": checker.is_file() and raw_file_sha256(checker) == EXPECTED_CHECKER_RAW_SHA256,
        "spec_raw_semantic_identity": spec_path.is_file() and raw_file_sha256(spec_path) == EXPECTED_SPEC_RAW_SHA256 and spec.get("v46_spec_sha256") == EXPECTED_SPEC_SHA256,
        "oracle_raw_semantic_identity": oracle_path.is_file() and raw_file_sha256(oracle_path) == EXPECTED_PATH_ORACLE_RAW_SHA256 and oracle.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256,
        "translation_raw_semantic_identity": translation_path.is_file() and raw_file_sha256(translation_path) == EXPECTED_TRANSLATION_RAW_SHA256 and translation.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256,
        "parent_227_immutable_paths": parent.get("valid") is True and parent.get("immutable_file_count") == 227 and parent.get("immutable_files_exact") is True,
        "artifact_crosslinks": bool(artifact.get("source_raw_file_sha256") == EXPECTED_SOURCE_RAW_SHA256 and artifact.get("independent_checker_raw_file_sha256") == EXPECTED_CHECKER_RAW_SHA256 and artifact.get("spec_raw_file_sha256") == EXPECTED_SPEC_RAW_SHA256 and artifact.get("spec_sha256") == EXPECTED_SPEC_SHA256 and references.get("path_oracle_sha256") == EXPECTED_PATH_ORACLE_SHA256 and references.get("translation_contract_sha256") == EXPECTED_TRANSLATION_SHA256),
        "seed_order_exact": [row.get("seed") for row in rows] == list(EXPECTED_SEEDS),
        "widths_exact": [row.get("logical_qubits") for row in rows] == list(EXPECTED_WIDTHS),
        "input_instruction_counts_exact": [row.get("instruction_count") for row in input_manifests] == list(EXPECTED_INPUT_COUNTS),
        "input_manifests_exact_parent": bool(rows and all((_mapping(row.get("routed_compilation"))).get("input_manifest_exact_parent") is True for row in rows)),
        "seed_statuses_pass": bool(rows and all(row.get("status") == "PASS_FULL_STREAM_STRUCTURAL_AND_RESOURCE_ROUTING" for row in rows)),
        "isa_violations_zero": bool(native_ledgers and all(row.get("isa_violations") == 0 for row in native_ledgers)),
        "coupling_violations_zero": bool(native_ledgers and all(row.get("coupling_violations") == 0 for row in native_ledgers)),
        "layout_bijections_self_hashed": bool(layouts and all(_self_hash(row, "layout_sha256") and len(row.get("final_logical_to_physical") or []) == width for row, width in zip(layouts, EXPECTED_WIDTHS))),
        "route_commitments_self_hashed": bool(route_ledgers and all(_self_hash(row, "route_ir_sha256") and row.get("input_instruction_count") == expected for row, expected in zip(route_ledgers, EXPECTED_INPUT_COUNTS))),
        "resource_rows_pass": bool(resources and all(row.get("status") == "PASS_PREREGISTERED_V45_ROUTING_RESOURCE_GATE" and _self_hash(row, "resource_gate_sha256") for row in resources)),
        "aggregate_self_hash": _self_hash(aggregate, "aggregate_sha256"),
        "aggregate_totals_exact": bool(aggregate.get("total_input_instructions") == 48647214 and aggregate.get("aggregate_swaps") == 33259620 and aggregate.get("aggregate_native_cz") == 119029964 and aggregate.get("aggregate_native_instructions") == 476876458),
        "aggregate_maxima_exact": bool(aggregate.get("maximum_logical_qubits") == 145 and aggregate.get("minimum_logical_capacity_margin") == 11 and aggregate.get("maximum_native_cz") == 15527797 and aggregate.get("maximum_routed_depth") == 24893376),
        "per_seed_native_metrics_exact": bool([row.get("swap_count") for row in native_ledgers] == list(EXPECTED_SWAPS) and native_cz == list(EXPECTED_NATIVE_CZ) and [row.get("asap_structural_depth") for row in native_ledgers] == list(EXPECTED_DEPTHS) and [row.get("native_instruction_count") for row in native_ledgers] == list(EXPECTED_NATIVE_INSTRUCTIONS)),
        "decision_exact": decisions.get("overall") == EXPECTED_OVERALL,
        "production_boundary_exact": decisions.get("production_admission") == EXPECTED_PRODUCTION,
        "next_gate_exact": decisions.get("next_falsifiable_gate") == EXPECTED_NEXT_GATE,
        "provider_network_job_zero": bool(boundary.get("provider_sdk_imported") is False and boundary.get("provider_credentials_read") is False and boundary.get("credential_reads") == 0 and boundary.get("provider_calls") == 0 and boundary.get("network_calls") == 0 and boundary.get("backend_run_calls") == 0 and boundary.get("local_simulator_jobs_submitted") == 0 and boundary.get("qpu_jobs_submitted") == 0),
        "hardware_false": boundary.get("hardware_executable") is False,
        "calibration_performance_advantage_boundary": bool(boundary.get("snapshot_is_current_hardware_evidence") is False and boundary.get("calibration_aware_fidelity") == "NOT_TESTED" and boundary.get("optimization_performance") == "NOT_TESTED" and boundary.get("quantum_advantage") == "NOT_CLAIMED"),
        "independent_checker_36_pass": independent.get("valid") is True and independent.get("check_count") == 36 and not independent.get("failed_checks") and not independent.get("errors"),
    }
    if len(checks) != EXPECTED_UI_AUTH_CHECK_COUNT:
        raise AssertionError(f"V4.6 UI authentication check count drifted: {len(checks)}")
    failed = [name for name, passed in checks.items() if passed is not True]
    errors.extend(parent.get("errors") or [])
    errors.extend(independent.get("errors") or [])
    return {
        "check_count": len(checks),
        "checks": checks,
        "errors": list(dict.fromkeys(errors)),
        "failed_checks": failed,
        "valid": not failed and not errors,
    }


def load_v46_ui_artifact(path: str | Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    target = Path(path) if path is not None else default_v46_ui_artifact_path()
    try:
        raw = target.read_bytes()
        artifact = _decode_json_strict(raw)
        report = _validate_v46_ui_artifact(raw, root=_root())
        return artifact, report
    except Exception as exc:
        return None, {
            "check_count": EXPECTED_UI_AUTH_CHECK_COUNT,
            "checks": {},
            "errors": [str(exc)],
            "failed_checks": ["artifact_available"],
            "valid": False,
        }


def normalize_v46_artifact(artifact: Mapping[str, Any] | None, *, integrity: bool | None) -> dict[str, Any]:
    authenticated = bool(isinstance(artifact, Mapping) and integrity is True)
    if not authenticated:
        return {
            "authenticated": False,
            "decision": "MASKED_FAIL_CLOSED",
            "hardware_executable": False,
            "research_classification": "RESEARCH_ONLY",
        }
    aggregate = _mapping(artifact.get("aggregate"))
    return {
        "authenticated": True,
        "decision": (_mapping(artifact.get("decisions"))).get("overall"),
        "hardware_executable": False,
        "maximum_logical_qubits": aggregate.get("maximum_logical_qubits"),
        "maximum_native_cz": aggregate.get("maximum_native_cz"),
        "maximum_routed_depth": aggregate.get("maximum_routed_depth"),
        "minimum_logical_capacity_margin": aggregate.get("minimum_logical_capacity_margin"),
        "research_classification": "RESEARCH_ONLY",
        "seed_count": aggregate.get("seed_count"),
        "total_input_instructions": aggregate.get("total_input_instructions"),
    }


def _seed_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_routings")):
        routed = _mapping(seed_row.get("routed_compilation"))
        manifest = _mapping(routed.get("input_stream_manifest"))
        native = _mapping(routed.get("native_ledger"))
        counts = _mapping(native.get("native_operation_counts"))
        resource = _mapping(seed_row.get("resource_gate"))
        rows.append({
            "Seed": seed_row.get("seed"),
            "Logical Q": seed_row.get("logical_qubits"),
            "Input instructions": manifest.get("instruction_count"),
            "SWAP": native.get("swap_count"),
            "Native CZ": counts.get("cz"),
            "Native instructions": native.get("native_instruction_count"),
            "ASAP structural depth": native.get("asap_structural_depth"),
            "CZ / input CX": resource.get("cz_expansion_ratio_exact"),
            "CZ margin": resource.get("routed_cz_margin"),
            "Depth margin": resource.get("depth_margin"),
            "Status": seed_row.get("status"),
        })
    return pd.DataFrame(rows)


def _native_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for seed_row in _rows(artifact.get("seed_routings")):
        native = _mapping((_mapping(seed_row.get("routed_compilation"))).get("native_ledger"))
        counts = _mapping(native.get("native_operation_counts"))
        rows.append({"Seed": seed_row.get("seed"), **{name.upper(): counts.get(name, 0) for name in ("cz", "id", "rz", "sx", "x")}, "Global phase π mod 2": native.get("global_phase_pi_mod_2")})
    return pd.DataFrame(rows)


def _threshold_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    maximum_cz = max(EXPECTED_NATIVE_CZ)
    maximum_depth = max(EXPECTED_DEPTHS)
    ratios = [Fraction(cz, int(((_mapping((_mapping(row.get("routed_compilation"))).get("input_stream_manifest"))).get("elementary_counts") or {}).get("CX", 1))) for row, cz in zip(_rows(artifact.get("seed_routings")), EXPECTED_NATIVE_CZ)]
    return pd.DataFrame([
        {"Gate": "Logical capacity", "Observed worst": "145 qubits", "Preregistered maximum": "156 qubits", "Margin": "+11 qubits", "Decision": "PASS"},
        {"Gate": "Native CZ / seed", "Observed worst": f"{maximum_cz:,}", "Preregistered maximum": "250,000,000", "Margin": f"+{250000000 - maximum_cz:,}", "Decision": "PASS"},
        {"Gate": "ASAP structural depth / seed", "Observed worst": f"{maximum_depth:,}", "Preregistered maximum": "250,000,000", "Margin": f"+{250000000 - maximum_depth:,}", "Decision": "PASS"},
        {"Gate": "CZ expansion / V4.5 CX", "Observed worst": f"{float(max(ratios)):.3f}×", "Preregistered maximum": "100×", "Margin": f"{100-float(max(ratios)):.3f}×", "Decision": "PASS"},
        {"Gate": "ISA violations", "Observed worst": "0", "Preregistered maximum": "0", "Margin": "0", "Decision": "PASS"},
        {"Gate": "Coupling violations", "Observed worst": "0", "Preregistered maximum": "0", "Margin": "0", "Decision": "PASS"},
    ])


def _provenance_ledger(artifact: Mapping[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {"Evidence": "V4.6 artifact raw", "SHA-256": EXPECTED_ARTIFACT_RAW_SHA256},
        {"Evidence": "V4.6 artifact semantic", "SHA-256": artifact.get("artifact_sha256")},
        {"Evidence": "V4.6 preregistration raw", "SHA-256": EXPECTED_SPEC_RAW_SHA256},
        {"Evidence": "V4.6 preregistration semantic", "SHA-256": EXPECTED_SPEC_SHA256},
        {"Evidence": "Qiskit path oracle raw", "SHA-256": EXPECTED_PATH_ORACLE_RAW_SHA256},
        {"Evidence": "Qiskit path oracle semantic", "SHA-256": EXPECTED_PATH_ORACLE_SHA256},
        {"Evidence": "Native translation contract raw", "SHA-256": EXPECTED_TRANSLATION_RAW_SHA256},
        {"Evidence": "Native translation contract semantic", "SHA-256": EXPECTED_TRANSLATION_SHA256},
        {"Evidence": "Compiler source raw", "SHA-256": EXPECTED_SOURCE_RAW_SHA256},
        {"Evidence": "Independent checker raw", "SHA-256": EXPECTED_CHECKER_RAW_SHA256},
    ])


def apply_v46_encoding_state(
    encoding: Mapping[str, Any] | None,
    *,
    regime: str,
    state: Mapping[str, Any],
    artifact: Mapping[str, Any] | None,
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(encoding or {}))
    if str(regime).upper() != "BANDS" or state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        return projected
    aggregate = _mapping(artifact.get("aggregate"))
    projected.update({
        "encoding_status": "V4.6 FULL-STREAM ROUTING PASS · HARDWARE BLOCKED",
        "hardware_executable": False,
        "logical_qubits_min": aggregate.get("maximum_logical_qubits"),
        "native_cz_max": aggregate.get("maximum_native_cz"),
        "routed_depth_max": aggregate.get("maximum_routed_depth"),
        "routing_status": "8/8 STRUCTURAL + PREREGISTERED RESOURCE PASS",
        "research_classification": "RESEARCH_ONLY",
        "v46_artifact_sha256": artifact.get("artifact_sha256"),
    })
    return projected


def render_v46_full_stream_routing_panel(
    section_header: SectionHeader,
    *,
    artifact: Mapping[str, Any] | None,
    integrity: bool,
    key_prefix: str,
) -> dict[str, Any]:
    state = normalize_v46_artifact(artifact, integrity=integrity)
    section_header(
        "V4.6 · Full-Stream FakeMarrakesh Routing",
        "48.6M INPUT INSTRUCTIONS → EXACT NATIVE MACRO IR → 24,180 PINNED PATHS → 8/8 STRUCTURAL + RESOURCE PASS",
        "Every V4.5 instruction is reconstructed and committed. BasicSwap routing and the preregistered limits pass, while current calibration, duration, fidelity, utility and hardware execution remain outside the evidence boundary.",
    )
    if state.get("authenticated") is not True or not isinstance(artifact, Mapping):
        st.error("V4.6 authentication failed. All routing, native-count and depth outcomes are masked fail-closed.")
        return state

    aggregate = _mapping(artifact.get("aggregate"))
    st.markdown(
        f'''<div class="qv46-hero"><div class="qv46-k">AUTHENTICATED · RESEARCH_ONLY · ZERO PROVIDER / ZERO JOB</div>
        <div class="qv46-t">Full structural routing passes; hardware execution remains rejected.</div>
        <div class="qv46-s">The sealed compiler consumed {int(aggregate.get("total_input_instructions", 0)):,} V4.5 instructions, inserted {int(aggregate.get("aggregate_swaps", 0)):,} SWAP and produced an exactly reconstructible {int(aggregate.get("aggregate_native_instructions", 0)):,}-instruction native IR. This is topology evidence against a dated fake-backend snapshot—not calibrated hardware evidence.</div></div>
        <style>
        .qv46-hero{{border:1px solid rgba(88,236,255,.26);border-radius:18px;padding:18px 20px;margin:8px 0 15px;background:linear-gradient(120deg,rgba(3,24,38,.97),rgba(19,15,47,.96));box-shadow:0 0 42px rgba(57,218,255,.08)}}
        .qv46-k{{font-size:.62rem;letter-spacing:.17em;color:#65ebff;font-weight:850}}.qv46-t{{font-size:1.16rem;color:#f7f8ff;font-weight:850;margin:7px 0}}.qv46-s{{font-size:.76rem;line-height:1.5;color:#9eb0c5}}
        </style>''',
        unsafe_allow_html=True,
    )
    columns = st.columns(5)
    columns[0].metric("Routed seeds", "8 / 8", "PASS")
    columns[1].metric("Input instructions", f"{int(aggregate.get('total_input_instructions', 0)) / 1e6:.2f}M", "exact parent")
    columns[2].metric("Native CZ total", f"{int(aggregate.get('aggregate_native_cz', 0)) / 1e6:.2f}M", "0 violations")
    columns[3].metric("Worst CZ / seed", f"{int(aggregate.get('maximum_native_cz', 0)) / 1e6:.2f}M", "limit 250M")
    columns[4].metric("Worst ASAP depth", f"{int(aggregate.get('maximum_routed_depth', 0)) / 1e6:.2f}M", "limit 250M")
    st.warning("Structural PASS is not hardware readiness: the snapshot is not current calibration evidence, depth has no duration model, fidelity and optimization performance are not tested, and hardware_executable remains false.")

    executive, seeds_tab, native_tab, topology_tab, provenance_tab, governance_tab = st.tabs([
        "EXECUTIVE GATES", "SEED ROUTING", "NATIVE ISA", "TOPOLOGY", "PROVENANCE", "GOVERNANCE"
    ])
    with executive:
        st.dataframe(_threshold_ledger(artifact), width="stretch", hide_index=True)
        st.success("All six preregistered structural/resource gates pass across all eight seeds.")
        st.caption("The 250M CZ, 250M depth and 100× expansion ceilings originated in the sealed V4.5 protocol, before V4.6 exploration.")
    with seeds_tab:
        seed_frame = _seed_ledger(artifact)
        st.dataframe(seed_frame, width="stretch", hide_index=True)
        st.download_button("Download V4.6 seed routing ledger CSV", data=seed_frame.to_csv(index=False).encode("utf-8"), file_name="QUANTUM_LAB_V4_6_SEED_ROUTING_LEDGER.csv", mime="text/csv", key=f"{key_prefix}_v46_seed_csv")
    with native_tab:
        native_frame = _native_ledger(artifact)
        st.dataframe(native_frame, width="stretch", hide_index=True)
        st.caption("Counts expand every exact macro algebraically. No monolithic Qiskit circuit or pulse schedule is claimed.")
        st.download_button("Download V4.6 native ISA ledger CSV", data=native_frame.to_csv(index=False).encode("utf-8"), file_name="QUANTUM_LAB_V4_6_NATIVE_ISA_LEDGER.csv", mime="text/csv", key=f"{key_prefix}_v46_native_csv")
    with topology_tab:
        st.markdown("**Pinned route oracle**")
        st.write("24,180 ordered Qiskit 2.5.2 shortest paths · 156 physical qubits · BasicSwap · seed 4505 · bidirectional CZ coupling")
        route_rows = []
        for row in _rows(artifact.get("seed_routings")):
            routing = _mapping((_mapping(row.get("routed_compilation"))).get("routing_ledger"))
            layout = _mapping((_mapping(row.get("routed_compilation"))).get("layout"))
            route_rows.append({"Seed": row.get("seed"), "Max pre-route distance": routing.get("maximum_distance_before_routing"), "Used physical qubits": len(layout.get("used_physical_qubits") or []), "Final layout SHA-256": layout.get("layout_sha256")})
        st.dataframe(pd.DataFrame(route_rows), width="stretch", hide_index=True)
        st.caption("Ordered paths are frozen because tied shortest-path choices can differ by direction. Every final layout is sealed as a complete bijection.")
    with provenance_tab:
        provenance = _provenance_ledger(artifact)
        st.dataframe(provenance, width="stretch", hide_index=True)
        st.download_button("Download sealed V4.6 artifact", data=json.dumps(artifact, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"), file_name="SEALED_V4_6_FULL_STREAM_FAKEMARRAKESH_ROUTING_ARTIFACT.json", mime="application/json", key=f"{key_prefix}_v46_artifact")
        for label, filename in (("Download V4.6 preregistration", SPEC_FILENAME), ("Download V4.6 native translation contract", "PHASE_III_V4_6_NATIVE_TRANSLATION_CONTRACT_V1.json")):
            path = _root() / "quantum_research_lab" / filename
            st.download_button(label, data=path.read_bytes(), file_name=filename, mime="application/json", key=f"{key_prefix}_{filename}")
        st.caption(f"Artifact {_short_sha(artifact.get('artifact_sha256'))} · 30/30 UI authentication gates · 36/36 independent scientific checks")
    with governance_tab:
        st.markdown("**Forbidden from this surface**")
        for index, label in enumerate((
            "Rebuild or mutate the sealed V4.6 artifact",
            "Change the frozen V4.5 lineage",
            "Replace the ordered Qiskit path oracle",
            "Override a preregistered resource threshold",
            "Treat compact native IR as a submitted circuit",
            "Treat structural depth as calibrated duration",
            "Read provider credentials or discover live backends",
            "Submit a simulator or QPU job",
            "Claim hardware readiness, utility or quantum advantage",
        )):
            st.button(label, disabled=True, key=f"{key_prefix}_v46_forbidden_{index}")
        st.error("Production admission: OFFLINE_STRUCTURAL_COMPILATION_ONLY_HARDWARE_EXECUTION_REJECTED")
        st.info(f"Next falsifiable gate: {EXPECTED_NEXT_GATE}.")
    return state


__all__ = [
    "EXPECTED_UI_AUTH_CHECK_COUNT",
    "apply_v46_encoding_state",
    "load_v46_ui_artifact",
    "normalize_v46_artifact",
    "render_v46_full_stream_routing_panel",
]
