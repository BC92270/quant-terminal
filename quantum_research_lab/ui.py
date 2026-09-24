from __future__ import annotations

from html import escape
import json
from math import comb
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .data import fetch_multi_asset_returns, fetch_regime_research_frame
from .evidence import (
    build_cross_engine_event_monitor,
    claim_governance,
    evidence_ladder,
    frozen_evidence_registry,
    build_evidence_provenance,
    live_regime_evidence,
    promotion_rules,
)
from .experiments import (
    PHASE_II_VERSION,
    PREREGISTRATION_DATE,
    PROTOCOLS,
    QUBO_SUITE,
    QMC_CANONICAL,
    build_phase2_registry,
    phase2_manifest,
    phase2_readiness,
    protocol_by_key,
)
from .phase2_qhardness import (
    EXECUTION_SPEC_SHA,
    EXECUTION_SPEC_VERSION,
    PROTOCOL_SHA as QUBO_PHASE2_PROTOCOL_SHA,
    artifact_zip_bytes as qhardness_artifact_zip_bytes,
    default_results_root as qhardness_results_root,
    execution_spec_payload as qhardness_execution_spec,
    initialize_run as qhardness_initialize_run,
    launch_background_worker as qhardness_launch_worker,
    load_run_status as qhardness_run_status,
    planned_instances as qhardness_planned_instances,
)
from .phase3_qpu import (
    PHASE3_VERSION,
    PREPARATION_SPEC_SHA as QPU_PREP_SPEC_SHA,
    preparation_spec_payload as qpu_preparation_spec,
    sdk_inventory as qpu_sdk_inventory,
    phase2_hardness_gate as qpu_phase2_gate,
    family_encoding_audit as qpu_family_encoding_audit,
    family_seed_audits as qpu_family_seed_audits,
    backend_capacity_assessment as qpu_backend_capacity,
    discover_ibm_backends as qpu_discover_ibm_backends,
    transpile_probe as qpu_transpile_probe,
    phase3_protocol_draft as qpu_protocol_draft,
    seal_phase3_protocol as qpu_seal_protocol,
    phase3_output_root as qpu_output_root,
    runtime_fingerprint as qpu_runtime_fingerprint,
)
from .phase3_bands_oracle import (
    ORACLE_VERSION as BANDS_ORACLE_VERSION,
    ORACLE_SPEC_SHA as BANDS_ORACLE_SPEC_SHA,
    oracle_spec_payload as bands_oracle_spec_payload,
    default_oracle_root as bands_oracle_root,
    family_audit_summary as bands_family_audit_summary,
    run_family_ladder as bands_run_family_ladder,
    oracle_worker_status as bands_oracle_worker_status,
    launch_oracle_worker as bands_launch_oracle_worker,
    build_family_oracle_blueprint as bands_build_blueprint,
    seal_family_oracle as bands_seal_family_oracle,
    load_sealed_oracle as bands_load_sealed_oracle,
    promote_bands_encoding as bands_promote_encoding,
)
from .phase3_dyadic_oracle import (
    DYADIC_ORACLE_VERSION,
    DYADIC_SPEC_SHA,
    dyadic_spec_payload,
    default_dyadic_root,
    family_dyadic_summary,
    seal_dyadic_oracle,
    load_sealed_dyadic_oracle,
    promote_dyadic_encoding,
    sealed_dyadic_oracle_path,
)
from .phase3_artifact_guard import (
    EXPECTED_PARENT_RAW_SHA256,
    load_and_validate_dyadic_artifact,
)
from .phase3_gate_compiler import (
    DOMAIN_EXACT_K,
    DOMAIN_FULL_BINARY,
    compiler_source_sha256,
    load_compiler_spec,
)
from .phase3_circuit_validation import (
    DEFAULT_SEAL_NAME as GATE_COMPILER_SEAL_NAME,
    compiler_worker_status,
    default_compiler_root,
    launch_compiler_worker,
    load_compiler_artifact,
)
from .phase3_algorithmic_contract import (
    PROFILE_DUAL_GUARD,
    TOPOLOGY_COMPLETE,
    TOPOLOGY_RING,
    algorithm_source_sha256,
    load_algorithm_spec,
    raw_file_sha256,
)
from .phase3_algorithmic_validation import (
    DEFAULT_SEAL_NAME as ALGORITHMIC_SEAL_NAME,
    default_algorithmic_root,
    load_algorithmic_artifact,
    validation_source_sha256,
    verifier_source_sha256,
)
from .phase3_v34_ui import render_v34_evidence_panel
from .phase3_backend_admission import load_admission_artifact
from .phase3_v35_ui import render_v35_backend_evidence_panel
from .phase3_v36_algorithmic_reduction import (
    authenticate_parent_chain as authenticate_v36_parent_chain,
    load_v36_artifact,
    load_v36_spec,
)
from .phase3_v36_ui import render_v36_algorithmic_reduction_panel
from .phase3_v37_reversible_compiler import (
    authenticate_v36_parent as authenticate_v37_parent_chain,
    load_v37_artifact,
    load_v37_spec,
)
from .phase3_v37_ui import (
    apply_v37_encoding_state,
    render_v37_reversible_prototype_panel,
)
from .phase3_v38_elementary_admission import load_v38_spec
from .phase3_v38_ui import (
    apply_v38_encoding_state,
    load_v38_ui_artifact,
    render_v38_elementary_admission_panel,
)
from .phase3_v39_scalable_reversible_ir import load_v39_spec
from .phase3_v39_ui import (
    apply_v39_encoding_state,
    load_v39_ui_artifact,
    render_v39_scalable_ir_panel,
)
from .phase3_v40_global_connectivity import load_v40_spec
from .phase3_v40_ui import (
    EXPECTED_V40_SPEC_SHA256,
    apply_v40_encoding_state,
    load_v40_ui_artifact,
    render_v40_connectivity_redesign_panel,
)
from .phase3_v41_certified_bridge_compiler import load_v41_spec
from .phase3_v41_ui import (
    EXPECTED_V41_SPEC_SHA256,
    apply_v41_encoding_state,
    load_v41_ui_artifact,
    render_v41_certified_bridge_compiler_panel,
)
from .phase3_v42_coined_walk_compiler import load_v42_spec
from .phase3_v42_ui import (
    EXPECTED_V42_SPEC_SHA256,
    apply_v42_encoding_state,
    load_v42_ui_artifact,
    render_v42_coined_walk_compiler_panel,
)
from .phase3_v43_reversible_circuit_ir import (
    EXPECTED_SPEC_SHA256 as EXPECTED_V43_SPEC_SHA256,
    load_v43_spec,
)
from .phase3_v43_ui import (
    apply_v43_encoding_state,
    load_v43_ui_artifact,
    render_v43_reversible_circuit_panel,
)
from .phase3_v44_named_backend_routing import (
    EXPECTED_SNAPSHOT_SHA256 as EXPECTED_V44_SNAPSHOT_SHA256,
    EXPECTED_SPEC_SHA256 as EXPECTED_V44_SPEC_SHA256,
    EXPECTED_TOOLCHAIN_SHA256 as EXPECTED_V44_TOOLCHAIN_SHA256,
    load_v44_snapshot,
    load_v44_spec,
    load_v44_toolchain,
)
from .phase3_v44_ui import (
    apply_v44_encoding_state,
    load_v44_ui_artifact,
    render_v44_named_backend_panel,
)
from .phase3_v45_proof_carrying_width_reduction import (
    EXPECTED_SPEC_SHA256 as EXPECTED_V45_SPEC_SHA256,
    load_v45_spec,
)
from .phase3_v45_ui import (
    apply_v45_encoding_state,
    load_v45_ui_artifact,
    load_v45_ui_supporting_evidence,
    render_v45_width_reduction_panel,
)
from .phase3_v46_full_stream_routing import (
    EXPECTED_SPEC_SHA256 as EXPECTED_V46_SPEC_SHA256,
    load_v46_spec,
)
from .phase3_v46_ui import (
    apply_v46_encoding_state,
    load_v46_ui_artifact,
    render_v46_full_stream_routing_panel,
)
from .phase3_v47_ui import (
    EXPECTED_UI_AUTH_CHECK_COUNT as EXPECTED_V47_UI_AUTH_CHECK_COUNT,
    apply_v47_encoding_state,
    load_v47_ui_artifact,
    render_v47_dated_properties_panel,
)
from .phase3_v48_ui import (
    EXPECTED_UI_AUTH_CHECK_COUNT as EXPECTED_V48_UI_AUTH_CHECK_COUNT,
    apply_v48_encoding_state,
    load_v48_ui_artifact,
    render_v48_multi_snapshot_architecture_panel,
)
from .v49.ui import (
    EXPECTED_UI_AUTH_CHECK_COUNT as EXPECTED_V49_UI_AUTH_CHECK_COUNT,
    apply_v49_encoding_state,
    load_v49_ui_artifact,
    render_v49_admission_panel,
)
from .engine import (
    REGIME_LABELS,
    annualized_moments,
    black_scholes_call,
    black_scholes_price,
    black_scholes_greeks,
    build_qubo,
    build_portfolio_qubo_components,
    qubo_component_energies,
    qubo_to_ising,
    qubo_penalty_audit,
    qubo_solver_arena,
    qubo_complexity_profile,
    presolve_portfolio_qubo,
    lift_presolved_solution,
    qubo_penalty_frontier,
    qubo_coefficient_diagnostics,
    constraint_preserving_qaoa_study,
    qaoa_p1_landscape,
    classical_hardness_benchmark,
    density_matrix_from_asset_returns,
    quantum_information_v2,
    market_features,
    monte_carlo_call_price,
    monte_carlo_option_price,
    classical_reference_price,
    monte_carlo_method_benchmark,
    monte_carlo_convergence_study,
    finite_difference_greeks,
    option_market_risk,
    delta_gamma_market_risk,
    exposure_cva_profile,
    qae_resource_projection,
    qae_algorithm_projection,
    quantum_resource_estimate,
    qae_error_budget,
    qae_total_error_feasibility,
    advantage_frontier,
    randomized_sobol_study,
    classical_convergence_models,
    qae_payoff_normalization,
    product_resource_profile,
    quantum_resource_estimate_product,
    product_advantage_frontier,
    qae_scaling_curve,
    quantum_regime_snapshot,
    regime_timeline,
    research_registry,
    runtime_status,
    solve_cardinality_portfolio_exact,
    run_regime_benchmark,
    target_integrity_grid,
    multi_horizon_regime_stack,
)


PREFIX = "qrl_v221"


@st.cache_data(ttl=900, show_spinner=False)
def _load_returns_cached(symbol_tuple: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    return fetch_multi_asset_returns(symbol_tuple, period="2y", interval="1d")


@st.cache_data(ttl=900, show_spinner=False)
def _load_regime_cached(primary_symbol: str) -> tuple[pd.DataFrame, str]:
    return fetch_regime_research_frame(primary_symbol=primary_symbol, period="5y", interval="1d")


@st.cache_data(ttl=900, show_spinner=False)
def _run_regime_cached(
    regime_frame: pd.DataFrame,
    horizon: int,
    train_fraction: float,
    retrain_every: int,
    decoherence: float,
    coupling: float,
    evolution_dt: float,
    scaler: str,
    winsor_z: float,
    target_mode: str,
    confirmation_days: int,
    min_dwell: int,
    transaction_cost_bps: float,
    economic_gamma: float,
) -> dict[str, Any]:
    return run_regime_benchmark(
        regime_frame,
        horizon=int(horizon),
        train_fraction=float(train_fraction),
        retrain_every=int(retrain_every),
        decoherence=float(decoherence),
        coupling=float(coupling),
        evolution_dt=float(evolution_dt),
        max_hmm_iter=12,
        scaler=str(scaler),
        winsor_z=float(winsor_z),
        target_mode=str(target_mode),
        confirmation_days=int(confirmation_days),
        min_dwell=int(min_dwell),
        transaction_cost_bps=float(transaction_cost_bps),
        economic_gamma=float(economic_gamma),
    )


@st.cache_data(ttl=900, show_spinner=False)
def _target_integrity_cached(regime_frame: pd.DataFrame, confirmation_days: int, min_dwell: int) -> pd.DataFrame:
    return target_integrity_grid(regime_frame, horizons=(5, 10, 20, 63), confirmation_days=int(confirmation_days), min_dwell=int(min_dwell))


@st.cache_data(ttl=900, show_spinner=False)
def _multi_horizon_cached(
    regime_frame: pd.DataFrame, target_mode: str, confirmation_days: int, min_dwell: int,
    scaler: str, winsor_z: float, decoherence: float, coupling: float, evolution_dt: float,
) -> tuple[pd.DataFrame, dict[int, np.ndarray]]:
    return multi_horizon_regime_stack(
        regime_frame, horizons=(5, 20, 63), target_mode=str(target_mode), confirmation_days=int(confirmation_days), min_dwell=int(min_dwell),
        scaler=str(scaler), winsor_z=float(winsor_z), decoherence=float(decoherence), coupling=float(coupling), evolution_dt=float(evolution_dt),
    )



@st.cache_data(ttl=900, show_spinner=False)
def _qmc_pricing_suite_cached(
    s0: float, strike: float, maturity: float, rate: float, vol: float,
    product: str, option_type: str, model: str, paths: int, steps: int, method: str,
    barrier_level: float, barrier_direction: str, basket_assets: int, basket_corr: float,
    heston_kappa: float, heston_theta: float, heston_xi: float, heston_rho: float, heston_v0: float,
    rqmc_scrambles: int,
) -> dict[str, Any]:
    """Canonical QMC snapshot: each visible artifact derives from one deterministic run set."""
    kwargs = dict(
        s0=float(s0), strike=float(strike), maturity=float(maturity), rate=float(rate), vol=float(vol),
        product=str(product), option_type=str(option_type), model=str(model), paths=int(paths), steps=int(steps), seed=17,
        barrier_level=float(barrier_level), barrier_direction=str(barrier_direction), basket_assets=int(basket_assets), basket_corr=float(basket_corr),
        heston_kappa=float(heston_kappa), heston_theta=float(heston_theta), heston_xi=float(heston_xi), heston_rho=float(heston_rho), heston_v0=float(heston_v0),
    )
    reference = classical_reference_price(**kwargs)
    methods = ("Pseudo-random", "Antithetic", "Control variate", "Sobol QMC")
    seed_map = {m: 17 + i * 997 for i, m in enumerate(methods)}
    canonical: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for m in methods:
        run_kwargs = dict(kwargs); run_kwargs["seed"] = seed_map[m]
        res = monte_carlo_option_price(**run_kwargs, method=m, return_sample=(m == str(method)))
        canonical[m] = res
        err = float(res["price"] - float(reference["price"]))
        rows.append({
            "Method": m, "Executed": res["method_executed"], "Price": float(res["price"]),
            "Abs Error": abs(err), "Signed Error": err, "Std Error": float(res["stderr"]),
            "CI Width": float(2.0 * 1.96 * res["stderr"]), "Runtime ms": float(res["runtime_ms"]),
            "Paths": int(res["paths"]), "Control Beta": float(res["control_beta"]), "SE Basis": str(res.get("stderr_basis", "")),
        })
    selected = canonical[str(method)]
    benchmark = pd.DataFrame(rows)

    base_grid = [1000, 2500, 5000, 10000, 25000, 50000]
    # Path-dependent/Heston replicated studies are intentionally capped to keep the lab interactive.
    hard_cap = 10000 if (str(model).startswith("Heston") or str(product) in {"Asian Arithmetic", "Barrier"}) else 50000
    max_n = int(max(5000, min(int(paths), hard_cap)))
    grid = tuple(n for n in base_grid if n <= max_n)
    if max_n not in grid:
        grid = tuple(sorted(set(grid + (max_n,))))
    convergence = monte_carlo_convergence_study(methods, grid, float(reference["price"]), **kwargs)
    rqmc = randomized_sobol_study(grid, float(reference["price"]), int(rqmc_scrambles), **kwargs)
    models = classical_convergence_models(convergence, rqmc)

    # Robust error metric: Sobol uses randomized-scramble RMSE, others use executed SE.
    robust_errors: dict[str, float] = {}
    for m in methods:
        if m == "Sobol QMC" and not rqmc.empty:
            ridx = (rqmc["Paths"] - int(paths)).abs().idxmin()
            robust_errors[m] = float(rqmc.loc[ridx, "RMSE"])
        else:
            robust_errors[m] = float(canonical[m]["stderr"])
    benchmark["Robust Error"] = benchmark["Method"].map(robust_errors)
    benchmark["Robust Error-Time"] = (benchmark["Robust Error"] ** 2 + 1e-12) * benchmark["Runtime ms"].clip(lower=1e-9)
    benchmark = benchmark.sort_values(["Robust Error-Time", "Robust Error"], ascending=True).reset_index(drop=True)
    return {
        "kwargs": kwargs, "reference": reference, "selected": selected, "benchmark": benchmark,
        "convergence": convergence, "rqmc": rqmc, "convergence_models": models,
        "snapshot_seed": int(seed_map[str(method)]), "grid": grid,
    }


@st.cache_data(ttl=900, show_spinner=False)
def _qmc_greeks_cached(
    s0: float, strike: float, maturity: float, rate: float, vol: float,
    product: str, option_type: str, model: str, steps: int, barrier_level: float,
    barrier_direction: str, basket_assets: int, basket_corr: float,
    heston_kappa: float, heston_theta: float, heston_xi: float, heston_rho: float, heston_v0: float,
) -> dict[str, float]:
    if str(product) == "European" and str(model).startswith("GBM"):
        return black_scholes_greeks(float(s0), float(strike), float(maturity), float(rate), float(vol), str(option_type))
    kwargs = dict(
        s0=float(s0), strike=float(strike), maturity=float(maturity), rate=float(rate), vol=float(vol),
        product=str(product), option_type=str(option_type), model=str(model), steps=int(steps),
        barrier_level=float(barrier_level), barrier_direction=str(barrier_direction), basket_assets=int(basket_assets), basket_corr=float(basket_corr),
        heston_kappa=float(heston_kappa), heston_theta=float(heston_theta), heston_xi=float(heston_xi), heston_rho=float(heston_rho), heston_v0=float(heston_v0),
    )
    return finite_difference_greeks(kwargs, paths=16_000)


@st.cache_data(ttl=900, show_spinner=False)
def _qmc_risk_cached(
    s0: float, strike: float, maturity: float, rate: float, vol: float, option_type: str,
    current_price: float, horizon_days: int, scenarios: int, drift: float,
    delta: float, gamma: float, use_full_revaluation: bool,
    exposure_paths: int, exposure_points: int, hazard_rate: float, recovery: float,
) -> dict[str, Any]:
    if bool(use_full_revaluation):
        risk = option_market_risk(
            float(s0), float(strike), float(maturity), float(rate), float(vol), str(option_type),
            current_price=float(current_price), horizon_days=int(horizon_days), scenarios=int(scenarios), drift=float(drift), seed=8128,
        )
        risk_mode = "FULL BLACK-SCHOLES REVALUATION"
    else:
        risk = delta_gamma_market_risk(
            float(s0), float(delta), float(gamma), float(vol), horizon_days=int(horizon_days), scenarios=int(scenarios), drift=float(drift), seed=8128,
        )
        risk_mode = "DELTA-GAMMA APPROXIMATION"
    exposure = exposure_cva_profile(
        float(s0), float(strike), float(maturity), float(rate), float(vol), str(option_type),
        paths=int(exposure_paths), exposure_points=int(exposure_points), pfe_quantile=0.95,
        hazard_rate=float(hazard_rate), recovery=float(recovery), seed=65537,
    )
    return {"risk": risk, "risk_mode": risk_mode, "exposure": exposure}


def _regime_params_from_state() -> dict[str, Any]:
    return {
        "horizon": int(st.session_state.get(f"{PREFIX}_reg_horizon", 5)),
        "train_fraction": float(st.session_state.get(f"{PREFIX}_reg_train", 0.65)),
        "retrain_every": int(st.session_state.get(f"{PREFIX}_reg_refit", 63)),
        "scaler": str(st.session_state.get(f"{PREFIX}_reg_scaler", "standard")),
        "winsor_z": float(st.session_state.get(f"{PREFIX}_reg_winsor", 5.0)),
        "decoherence": float(st.session_state.get(f"{PREFIX}_reg_decoherence", 0.12)),
        "coupling": float(st.session_state.get(f"{PREFIX}_reg_coupling", 0.35)),
        "evolution_dt": float(st.session_state.get(f"{PREFIX}_reg_dt", 0.30)),
        "target_mode": str(st.session_state.get(f"{PREFIX}_target_mode", "persistent")),
        "confirmation_days": int(st.session_state.get(f"{PREFIX}_confirmation", 3)),
        "min_dwell": int(st.session_state.get(f"{PREFIX}_min_dwell", 5)),
        "transaction_cost_bps": float(st.session_state.get(f"{PREFIX}_tcost", 5.0)),
        "economic_gamma": float(st.session_state.get(f"{PREFIX}_gamma", 5.0)),
    }


def _snapshot_from_benchmark(result: dict[str, Any] | None, price_data: pd.DataFrame | None) -> dict[str, Any]:
    if isinstance(result, dict) and result.get("available"):
        rho = np.asarray(result["current_rho"], dtype=complex)
        probs = np.asarray(result["current_probabilities"], dtype=float)
        return {
            "features": market_features(price_data),
            "labels": list(REGIME_LABELS),
            "probabilities": probs,
            "rho": rho,
            "dominant_regime": str(result["current_dominant"]),
            "dominant_probability": float(result["current_probability"]),
            "entropy": float(result["current_entropy"]),
            "purity": float(result["current_purity"]),
            "coherence": float(result["current_coherence"]),
            "effective_dimension": float(result["current_effective_dimension"]),
            "source": "V2.2.1 research-freeze calibrated engine",
        }
    snap = quantum_regime_snapshot(price_data, decoherence=0.12, evolve=True, evolution_dt=0.25)
    snap["source"] = "legacy fallback encoder"
    return snap


def _fmt(value: Any, digits: int = 2) -> str:
    try:
        x = float(value)
        if not np.isfinite(x):
            return "N/A"
        return f"{x:,.{digits}f}"
    except Exception:
        return "N/A"


def _ratio_fmt(value: Any) -> str:
    try:
        x = float(value)
        if not np.isfinite(x):
            return "N/A"
        if x == 0:
            return "0x"
        if abs(x) < 0.001 or abs(x) >= 1000:
            return f"{x:.2e}x"
        return f"{x:.4f}x"
    except Exception:
        return "N/A"


def _pct(value: Any, digits: int = 1) -> str:
    try:
        x = float(value)
        if not np.isfinite(x):
            return "N/A"
        return f"{x * 100:.{digits}f}%"
    except Exception:
        return "N/A"


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        @keyframes qrlPulse {0%,100%{opacity:.62;transform:scale(1)}50%{opacity:1;transform:scale(1.035)}}
        @keyframes qrlScan {0%{transform:translateY(-120%)}100%{transform:translateY(720%)}}
        @keyframes qrlSpin {from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
        @keyframes qrlFlow {0%{background-position:0% 50%}50%{background-position:100% 50%}100%{background-position:0% 50%}}
        @keyframes qrlBar {0%,100%{opacity:.40}50%{opacity:.95}}

        .qrl-shell {
            position:relative; overflow:hidden; border:1px solid rgba(75,231,255,.24);
            background:
                linear-gradient(rgba(49,170,255,.025) 1px, transparent 1px),
                linear-gradient(90deg, rgba(49,170,255,.025) 1px, transparent 1px),
                radial-gradient(circle at 14% 4%, rgba(0,242,255,.14), transparent 30%),
                radial-gradient(circle at 86% 0%, rgba(91,79,255,.12), transparent 28%),
                linear-gradient(180deg, rgba(2,11,25,.98), rgba(1,6,17,.99));
            background-size:28px 28px,28px 28px,auto,auto,auto;
            border-radius:24px; padding:21px 24px 20px 24px; margin:2px 0 14px 0;
            box-shadow:0 0 48px rgba(0,202,255,.10), inset 0 0 40px rgba(0,202,255,.025);
        }
        .qrl-shell:after {content:""; position:absolute; left:0; right:0; top:0; height:2px;
            background:linear-gradient(90deg,transparent,#55efff,transparent); opacity:.65; animation:qrlScan 7s linear infinite;}
        .qrl-kicker {font-size:.70rem;font-weight:950;letter-spacing:.24em;color:#62efff;text-transform:uppercase}
        .qrl-title {font-size:2.2rem;font-weight:950;color:#f7fbff;line-height:1.04;margin-top:6px}
        .qrl-sub {font-size:.88rem;color:rgba(224,239,251,.70);max-width:1120px;line-height:1.45;margin-top:8px}
        .qrl-status-row {display:grid;grid-template-columns:repeat(5,1fr);gap:9px;margin-top:15px}
        .qrl-status {border:1px solid rgba(84,219,255,.16);border-radius:13px;padding:9px 11px;background:rgba(3,17,35,.70);animation:qrlPulse 4.2s ease-in-out infinite}
        .qrl-status:nth-child(2){animation-delay:.35s}.qrl-status:nth-child(3){animation-delay:.7s}.qrl-status:nth-child(4){animation-delay:1.05s}.qrl-status:nth-child(5){animation-delay:1.4s}
        .qrl-status-label {font-size:.61rem;letter-spacing:.13em;color:rgba(192,219,237,.58);font-weight:900;text-transform:uppercase}
        .qrl-status-value {font-size:.84rem;color:#f5fbff;font-weight:900;margin-top:4px}
        .qrl-orb-wrap {display:flex;justify-content:center;align-items:center;min-height:230px;position:relative}
        .qrl-orb {width:165px;height:165px;border-radius:50%;position:relative;
            background:radial-gradient(circle at 40% 38%,rgba(132,252,255,.38),rgba(10,124,255,.08) 36%,rgba(3,13,33,.10) 65%);
            box-shadow:0 0 36px rgba(78,229,255,.30), inset 0 0 28px rgba(91,239,255,.20);animation:qrlPulse 3.4s ease-in-out infinite;}
        .qrl-orb:before,.qrl-orb:after {content:"";position:absolute;inset:-18px;border:1px solid rgba(91,232,255,.36);border-radius:50%;animation:qrlSpin 9s linear infinite}
        .qrl-orb:after {inset:-34px;border-style:dashed;opacity:.55;animation-duration:15s;animation-direction:reverse}
        .qrl-core {position:absolute;inset:53px;border-radius:50%;background:#70f4ff;box-shadow:0 0 30px #3feeff,0 0 70px rgba(62,164,255,.65)}
        .qrl-core-text {position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);color:#001422;font-size:.63rem;font-weight:1000;letter-spacing:.12em;z-index:5;text-align:center}
        .qrl-card {border:1px solid rgba(85,220,255,.15);border-radius:16px;padding:13px 14px;background:linear-gradient(180deg,rgba(4,18,38,.78),rgba(2,10,24,.82));min-height:115px}
        .qrl-card-title {font-size:.68rem;color:#61eaff;font-weight:950;letter-spacing:.16em;text-transform:uppercase}
        .qrl-card-main {font-size:1.08rem;color:#f6fbff;font-weight:950;margin-top:7px}
        .qrl-card-note {font-size:.71rem;color:rgba(211,230,244,.58);margin-top:5px;line-height:1.35}
        .qrl-warning {border-left:2px solid #ffcf66;background:rgba(255,194,74,.055);padding:9px 11px;color:rgba(244,235,215,.82);font-size:.75rem;border-radius:5px;margin:6px 0 10px 0}
        .qrl-flow {height:3px;border-radius:999px;background:linear-gradient(90deg,rgba(62,235,255,.1),#58f2ff,rgba(100,93,255,.75),rgba(62,235,255,.1));background-size:200% 100%;animation:qrlFlow 3.5s ease infinite;margin:5px 0 13px 0}
        .qrl-node-line {display:flex;gap:5px;align-items:center;margin-top:9px}
        .qrl-node {height:6px;flex:1;border-radius:99px;background:rgba(76,227,255,.35);animation:qrlBar 1.7s ease-in-out infinite}
        .qrl-node:nth-child(2){animation-delay:.15s}.qrl-node:nth-child(3){animation-delay:.3s}.qrl-node:nth-child(4){animation-delay:.45s}.qrl-node:nth-child(5){animation-delay:.6s}

        @keyframes qrlSweepX {0%{transform:translateX(-130%)}100%{transform:translateX(430%)}}
        @keyframes qrlGlow {0%,100%{box-shadow:0 0 0 rgba(80,235,255,0)}50%{box-shadow:0 0 28px rgba(80,235,255,.10)}}
        @keyframes qrlFloat {0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
        @keyframes qrlDot {0%,100%{opacity:.3}50%{opacity:1}}
        .qrl-section {
            position:relative; overflow:hidden; margin:22px 0 12px 0; padding:15px 17px 14px 17px;
            border:1px solid rgba(82,224,255,.18); border-radius:16px;
            background:
              linear-gradient(90deg,rgba(15,77,113,.14),rgba(14,22,53,.28) 48%,rgba(69,41,131,.12)),
              rgba(2,10,23,.66);
            box-shadow:inset 0 0 28px rgba(52,194,255,.025);
            animation:qrlGlow 7s ease-in-out infinite;
        }
        .qrl-section:after {content:"";position:absolute;top:0;bottom:0;width:28%;pointer-events:none;
            background:linear-gradient(90deg,transparent,rgba(96,239,255,.08),transparent);animation:qrlSweepX 8s linear infinite;}
        .qrl-section-kicker {display:flex;align-items:center;gap:8px;font-size:.60rem;font-weight:950;letter-spacing:.19em;text-transform:uppercase;color:#63eaff}
        .qrl-section-kicker:before {content:"";width:7px;height:7px;border-radius:50%;background:#68f2ff;box-shadow:0 0 14px rgba(104,242,255,.75);animation:qrlDot 1.8s ease-in-out infinite}
        .qrl-section-title {font-size:1.18rem;font-weight:950;color:#f5fbff;letter-spacing:-.025em;margin-top:5px}
        .qrl-section-desc {font-size:.73rem;color:rgba(210,229,244,.62);margin-top:4px;line-height:1.42;max-width:1120px}
        .qrl-method-grid {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:9px 0 15px 0}
        .qrl-method-card {position:relative;overflow:hidden;border:1px solid rgba(88,218,255,.14);border-radius:14px;padding:11px 12px;
            background:linear-gradient(180deg,rgba(5,21,42,.75),rgba(2,9,22,.85));animation:qrlFloat 5s ease-in-out infinite}
        .qrl-method-card:nth-child(2){animation-delay:.4s}.qrl-method-card:nth-child(3){animation-delay:.8s}.qrl-method-card:nth-child(4){animation-delay:1.2s}
        .qrl-method-label {font-size:.56rem;letter-spacing:.14em;text-transform:uppercase;color:rgba(154,211,239,.62);font-weight:900}
        .qrl-method-value {font-size:.89rem;color:#f4fbff;font-weight:950;margin-top:5px}
        .qrl-method-note {font-size:.64rem;color:rgba(197,219,237,.51);margin-top:3px}
        .qrl-pass {color:#70f7c3}.qrl-warn {color:#ffd36d}.qrl-fail {color:#ff7a89}

        @keyframes qmcOrbit {from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
        @keyframes qmcSignal {0%{left:-30%;opacity:0}15%{opacity:.8}85%{opacity:.8}100%{left:110%;opacity:0}}
        @keyframes qmcBreath {0%,100%{border-color:rgba(74,229,255,.13)}50%{border-color:rgba(95,232,255,.32)}}
        .qmc-command-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:10px 0 15px 0}
        .qmc-command-card{position:relative;overflow:hidden;min-height:94px;padding:12px 13px;border-radius:15px;border:1px solid rgba(75,224,255,.15);background:linear-gradient(180deg,rgba(4,20,41,.84),rgba(2,9,22,.90));animation:qmcBreath 5.4s ease-in-out infinite}
        .qmc-command-card:after{content:"";position:absolute;top:0;bottom:0;width:25%;background:linear-gradient(90deg,transparent,rgba(92,238,255,.07),transparent);animation:qmcSignal 6.4s linear infinite}
        .qmc-command-card:nth-child(2){animation-delay:.5s}.qmc-command-card:nth-child(3){animation-delay:1s}.qmc-command-card:nth-child(4){animation-delay:1.5s}
        .qmc-command-label{font-size:.57rem;letter-spacing:.15em;text-transform:uppercase;color:rgba(151,214,239,.62);font-weight:950}
        .qmc-command-value{font-size:1rem;color:#f6fbff;font-weight:950;margin-top:7px}
        .qmc-command-note{font-size:.64rem;color:rgba(202,224,240,.52);margin-top:4px;line-height:1.3}
        .qmc-pipeline{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;align-items:center;margin:12px 0 16px 0;position:relative}
        .qmc-pipeline:before{content:"";position:absolute;left:6%;right:6%;top:50%;height:1px;background:linear-gradient(90deg,rgba(74,235,255,.08),rgba(74,235,255,.55),rgba(100,83,255,.55),rgba(74,235,255,.08));z-index:0}
        .qmc-node{z-index:1;position:relative;text-align:center;padding:11px 7px;border-radius:12px;border:1px solid rgba(80,225,255,.18);background:rgba(3,14,30,.94);box-shadow:0 0 18px rgba(57,215,255,.04)}
        .qmc-node:before{content:"";display:block;width:8px;height:8px;border-radius:50%;background:#6cf3ff;box-shadow:0 0 13px rgba(108,243,255,.8);margin:0 auto 7px auto;animation:qrlDot 1.5s ease-in-out infinite}
        .qmc-node-title{font-size:.56rem;letter-spacing:.12em;color:#ccecff;font-weight:950;text-transform:uppercase}
        .qmc-node-sub{font-size:.58rem;color:rgba(183,210,228,.50);margin-top:3px}
        .qmc-frontier{border:1px solid rgba(96,229,255,.15);border-radius:17px;padding:14px 15px;background:radial-gradient(circle at 8% 0%,rgba(40,205,255,.08),transparent 35%),linear-gradient(180deg,rgba(4,18,37,.72),rgba(2,8,20,.88));margin:8px 0 14px 0}
        .qmc-frontier-title{font-size:.63rem;letter-spacing:.16em;text-transform:uppercase;color:#66efff;font-weight:950}
        .qmc-frontier-main{font-size:1.15rem;color:#f8fcff;font-weight:950;margin-top:5px}
        .qmc-frontier-note{font-size:.68rem;color:rgba(207,228,243,.56);margin-top:4px;line-height:1.35}
        @media(max-width:900px){.qmc-command-grid{grid-template-columns:1fr 1fr}.qmc-pipeline{grid-template-columns:1fr}.qmc-pipeline:before{display:none}}
        @media(max-width:900px){.qrl-status-row,.qrl-method-grid{grid-template-columns:1fr 1fr}}

        </style>
        """,
        unsafe_allow_html=True,
    )



def _section_header(title: str, kicker: str, description: str = "") -> None:
    st.markdown(
        f"""
        <div class="qrl-section">
          <div class="qrl-section-kicker">{escape(kicker)}</div>
          <div class="qrl-section-title">{escape(title)}</div>
          <div class="qrl-section-desc">{escape(description)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _method_strip(result: dict[str, Any]) -> None:
    audit = result.get("purge_audit", pd.DataFrame())
    purge_ok = bool(result.get("purge_pass", False))
    ess = result.get("effective_sample_size", {})
    boot = result.get("bootstrap", {})
    cards = [
        ("LABEL PURGE", "PASS" if purge_ok else "FAIL", f"{int(result.get('purge_gap', 0))}d embargo", "qrl-pass" if purge_ok else "qrl-fail"),
        ("DEPENDENCY BOOTSTRAP", f"{int(boot.get('block_length', 0) or 0)}d weakest block", f"p={_fmt(boot.get('p_value'),3)}", "qrl-pass" if float(boot.get("p_value", 1.0) or 1.0) < .05 else "qrl-warn"),
        ("EFFECTIVE SAMPLE", _fmt(ess.get("effective_n"), 0), f"nominal {int(ess.get('nominal_n', 0) or 0)}", ""),
        ("OOS CHRONOLOGY", "CLEAN" if purge_ok else "REVIEW", f"{len(audit)} refit blocks", "qrl-pass" if purge_ok else "qrl-fail"),
    ]
    html = '<div class="qrl-method-grid">'
    for label, value, note, cls in cards:
        html += f'<div class="qrl-method-card"><div class="qrl-method-label">{escape(label)}</div><div class="qrl-method-value {cls}">{escape(str(value))}</div><div class="qrl-method-note">{escape(str(note))}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def _hero(ticker: str, snapshot: dict[str, Any]) -> None:
    rt = runtime_status()
    st.markdown(
        f"""
        <div class="qrl-shell">
            <div class="qrl-kicker">QUANTUM RESEARCH & COMPUTATION LAB · V4.9 · TERMINAL OFFLINE ADMISSION & EVIDENCE GOVERNANCE</div>
            <div class="qrl-title">Institutional Quantum Intelligence Workspace</div>
            <div class="qrl-sub">
                Quantum regime inference, calibration diagnostics, density-matrix explainability, controlled OOS benchmarking, Monte Carlo / QAE resource benchmarking,
                QUBO-Ising portfolio research and quantum-information / tensor-network structure. Classical controls are mandatory;
                no hardware advantage is claimed unless explicitly measured.
            </div>
            <div class="qrl-status-row">
                <div class="qrl-status"><div class="qrl-status-label">Runtime</div><div class="qrl-status-value">{escape(rt.execution_mode)}</div></div>
                <div class="qrl-status"><div class="qrl-status-label">Context</div><div class="qrl-status-value">{escape(ticker or 'RESEARCH')}</div></div>
                <div class="qrl-status"><div class="qrl-status-label">Dominant State</div><div class="qrl-status-value">{escape(snapshot['dominant_regime'])}</div></div>
                <div class="qrl-status"><div class="qrl-status-label">State Entropy</div><div class="qrl-status-value">{snapshot['entropy']:.3f}</div></div>
                <div class="qrl-status"><div class="qrl-status-label">Protocol</div><div class="qrl-status-value">CONTROLLED BENCHMARK</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _density_heatmap(rho: np.ndarray, labels: list[str], title: str) -> go.Figure:
    z = np.abs(np.asarray(rho, dtype=complex))
    fig = go.Figure(go.Heatmap(z=z, x=labels, y=labels, colorbar=dict(title="|ρᵢⱼ|")))
    fig.update_layout(template="plotly_dark", height=410, title=title, margin=dict(l=20, r=20, t=55, b=20))
    return fig


def _regime_radar(snapshot: dict[str, Any]) -> go.Figure:
    labels = list(snapshot["labels"])
    probs = list(snapshot["probabilities"])
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=probs + [probs[0]], theta=labels + [labels[0]], fill="toself", name="ρ diagonal"))
    fig.update_layout(
        template="plotly_dark",
        height=365,
        margin=dict(l=35, r=35, t=35, b=35),
        polar=dict(radialaxis=dict(range=[0, max(0.55, max(probs) * 1.15)], tickformat=".0%")),
        showlegend=False,
    )
    return fig


def _mission_control(snapshot: dict[str, Any], ticker: str, price_data: pd.DataFrame | None) -> None:
    left, mid, right = st.columns([1.0, 1.35, 1.0])

    with left:
        st.markdown(
            f"""
            <div class="qrl-orb-wrap"><div class="qrl-orb"><div class="qrl-core"></div><div class="qrl-core-text">ρ STATE<br>{escape(snapshot['dominant_regime'])}</div></div></div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Animated research-state visualisation. The underlying state is computed from the density matrix shown in the adjacent panels.")

    with mid:
        st.plotly_chart(_regime_radar(snapshot), width="stretch", key=f"{PREFIX}_mission_radar")

    with right:
        features = snapshot["features"]
        cards = [
            ("Dominant probability", _pct(snapshot["dominant_probability"]), "Diagonal mass of the current density matrix."),
            ("Purity", _fmt(snapshot["purity"], 3), "1 = pure state; lower values indicate a more mixed representation."),
            ("Effective dimension", _fmt(snapshot["effective_dimension"], 2), "Inverse purity; compact measure of state dispersion."),
            ("20D momentum", _pct(features.get("momentum_20")), "Current market input used by the experimental state encoder."),
        ]
        for title, main, note in cards:
            st.markdown(
                f'<div class="qrl-card"><div class="qrl-card-title">{escape(title)}</div><div class="qrl-card-main">{escape(main)}</div><div class="qrl-card-note">{escape(note)}</div><div class="qrl-node-line"><div class="qrl-node"></div><div class="qrl-node"></div><div class="qrl-node"></div><div class="qrl-node"></div><div class="qrl-node"></div></div></div>',
                unsafe_allow_html=True,
            )
            st.write("")

    st.markdown('<div class="qrl-flow"></div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Annualised return", _pct(snapshot["features"].get("ann_return")))
    c2.metric("Annualised vol", _pct(snapshot["features"].get("ann_vol")))
    c3.metric("Current drawdown", _pct(snapshot["features"].get("drawdown")))
    c4.metric("60D momentum", _pct(snapshot["features"].get("momentum_60")))
    c5.metric("Observations", str(int(snapshot["features"].get("observations", 0))))

    st.markdown(
        '<div class="qrl-warning"><b>Research discipline:</b> the live state shown here is the same calibrated V2.2.1 research-freeze state used in REGIME / DENSITY. It does not assert that financial markets are physical quantum systems; point-in-time naive and learned classical controls remain mandatory.</div>',
        unsafe_allow_html=True,
    )


def _regime_lab(
    ticker: str,
    regime_frame: pd.DataFrame,
    regime_source: str,
    result: dict[str, Any] | None = None,
) -> None:
    st.subheader("Quantum Regime Engine · V2.2.1")
    st.caption(
        "Purged OOS & Dependency-Aware Validation: label-boundary embargo, block-bootstrap robustness, target integrity, multi-horizon tactical/cyclical/structural states, "
        "matched Classical→Quantum explainability and a net-of-cost allocation benchmark. "
        "Forward regime labels remain evaluation constructs only."
    )

    # Research configuration. Persistent is the default when we use the word
    # 'regime'; RAW remains visible as a diagnostic and can be selected.
    c1, c2, c3, c4 = st.columns(4)
    horizon = c1.select_slider("Forward regime horizon", options=[3, 5, 10, 20, 63], value=5, key=f"{PREFIX}_reg_horizon")
    train_fraction = c2.slider("Initial train fraction", 0.50, 0.80, 0.65, 0.05, key=f"{PREFIX}_reg_train")
    retrain_every = c3.select_slider("Expanding refit", options=[21, 42, 63, 126], value=63, key=f"{PREFIX}_reg_refit")
    scaler = c4.selectbox("Feature scaler", ["standard", "robust"], index=0, key=f"{PREFIX}_reg_scaler", format_func=lambda x: "Standard z-score" if x == "standard" else "Robust median / IQR")

    c5, c6, c7, c8 = st.columns(4)
    target_mode = c5.selectbox("Evaluation target", ["persistent", "raw"], index=0, key=f"{PREFIX}_target_mode", format_func=lambda x: "Persistent regime proxy" if x == "persistent" else "Raw tactical proxy")
    confirmation_days = c6.slider("Transition confirmation", 1, 7, 3, 1, key=f"{PREFIX}_confirmation")
    min_dwell = c7.slider("Minimum regime dwell", 1, 20, 5, 1, key=f"{PREFIX}_min_dwell")
    winsor_z = c8.slider("Standardized winsor cap", 2.5, 10.0, 5.0, 0.5, key=f"{PREFIX}_reg_winsor")

    c9, c10, c11, c12 = st.columns(4)
    decoherence = c9.slider("Decoherence", 0.00, 0.50, 0.12, 0.01, key=f"{PREFIX}_reg_decoherence")
    coupling = c10.slider("Hamiltonian coupling", 0.00, 0.90, 0.35, 0.05, key=f"{PREFIX}_reg_coupling")
    dt = c11.slider("Evolution Δt", 0.05, 0.80, 0.30, 0.05, key=f"{PREFIX}_reg_dt")
    transaction_cost_bps = c12.slider("Strategy cost / turnover", 0.0, 25.0, 5.0, 0.5, key=f"{PREFIX}_tcost", help="Basis points applied to one-way portfolio turnover in the economic-utility benchmark.")

    c13, _ = st.columns([1, 3])
    economic_gamma = c13.slider("Economic risk aversion γ", 1.0, 10.0, 5.0, 0.5, key=f"{PREFIX}_gamma")

    if regime_frame is None or regime_frame.empty:
        st.error("Cross-asset regime panel unavailable.")
        return

    if not isinstance(result, dict) or not result.get("available"):
        with st.spinner("Running controlled expanding-window regime benchmark…"):
            result = run_regime_benchmark(
                regime_frame, horizon=int(horizon), train_fraction=float(train_fraction), retrain_every=int(retrain_every),
                decoherence=float(decoherence), coupling=float(coupling), evolution_dt=float(dt), max_hmm_iter=12,
                scaler=str(scaler), winsor_z=float(winsor_z), target_mode=str(target_mode), confirmation_days=int(confirmation_days),
                min_dwell=int(min_dwell), transaction_cost_bps=float(transaction_cost_bps), economic_gamma=float(economic_gamma),
            )

    if not result.get("available"):
        st.warning(str(result.get("reason", "Regime benchmark unavailable.")))
        st.caption(f"Data source: {regime_source}")
        return

    probs = np.asarray(result["current_probabilities"], dtype=float)
    classical_probs = np.asarray(result["current_classical_probabilities"], dtype=float)
    dominant = str(result["current_dominant"])
    boot = result["bootstrap"]
    boot_matched = result.get("bootstrap_matched", {})
    best_classical = str(result["best_classical"])
    best_baseline = str(result.get("best_baseline", "Historical Prior"))
    metrics = result["metrics"].copy()
    validation = result.get("validation_level", {"level": 0, "label": "UNRATED", "detail": "Validation state unavailable."})

    st.markdown('<div class="qrl-flow"></div>', unsafe_allow_html=True)
    s1, s2, s3, s4, s5, s6 = st.columns(6)
    s1.metric("LIVE REGIME", dominant)
    s2.metric("Dominant probability", _pct(result["current_probability"]))
    s3.metric("State entropy", _fmt(result["current_entropy"], 3))
    s4.metric("Purity", _fmt(result["current_purity"], 3))
    s5.metric("OOS observations", f"{int(result['oos_observations']):,}")
    s6.metric("Validation level", f"L{int(validation['level'])}")

    _method_strip(result)

    left, right = st.columns([0.92, 1.08])
    with left:
        fig = go.Figure(go.Bar(x=list(REGIME_LABELS), y=probs, text=[_pct(x) for x in probs], textposition="outside"))
        fig.update_layout(template="plotly_dark", height=390, yaxis_tickformat=".0%", yaxis_range=[0, max(0.55, float(probs.max()) * 1.25)], title="Live calibrated quantum-regime probability mass")
        st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_live_probs")
    with right:
        st.plotly_chart(_density_heatmap(result["current_rho"], list(REGIME_LABELS), "Live density matrix magnitude |ρ|"), width="stretch", key=f"{PREFIX}_live_rho")

    # ------------------------------------------------------------------
    # Target Integrity Lab — the new scientific gate before model ranking.
    # ------------------------------------------------------------------
    _section_header("Target Integrity Lab", "TARGET QUALITY GATE", "RAW vs persistent proxy stability, dwell, overlap and regime-claim eligibility.")
    raw_int = result.get("target_integrity_raw", {})
    pers_int = result.get("target_integrity_persistent", {})
    selected_int = result.get("target_integrity_selected", {})
    ti1, ti2, ti3, ti4, ti5, ti6 = st.columns(6)
    ti1.metric("Selected target", "PERSISTENT" if str(result.get("target_mode", target_mode)).lower().startswith("persist") else "RAW")
    ti2.metric("Target quality", str(selected_int.get("status", "N/A")))
    ti3.metric("Transition rate", _pct(selected_int.get("transition_rate")))
    ti4.metric("Median dwell", f"{_fmt(selected_int.get('median_dwell'), 1)}d")
    ti5.metric("Class entropy", _fmt(selected_int.get("class_entropy"), 3))
    ti6.metric("Forward overlap", _pct(selected_int.get("forward_window_overlap")))

    comp = pd.DataFrame([
        {"Target": "RAW", **raw_int},
        {"Target": "PERSISTENT", **pers_int},
    ])
    keep = ["Target", "status", "transitions", "transition_rate", "persistence", "mean_dwell", "median_dwell", "class_entropy", "dominant_share", "low_margin_share", "forward_window_overlap", "independent_window_fraction"]
    comp = comp[[c for c in keep if c in comp.columns]]
    for col in ["transition_rate", "persistence", "dominant_share", "low_margin_share", "forward_window_overlap", "independent_window_fraction"]:
        if col in comp: comp[col] = comp[col].map(lambda x: _pct(x) if pd.notna(x) else "N/A")
    for col in ["mean_dwell", "median_dwell", "class_entropy"]:
        if col in comp: comp[col] = comp[col].map(lambda x: _fmt(x, 2))
    st.dataframe(comp, width="stretch", hide_index=True)

    with st.spinner("Auditing target stability across horizons…"):
        integrity_grid = _target_integrity_cached(regime_frame, int(confirmation_days), int(min_dwell))
    if not integrity_grid.empty:
        iv = integrity_grid.copy()
        cols = ["Horizon", "Target", "status", "transition_rate", "median_dwell", "mean_dwell", "class_entropy", "dominant_share", "low_margin_share", "forward_window_overlap"]
        iv = iv[[c for c in cols if c in iv.columns]]
        for col in ["transition_rate", "dominant_share", "low_margin_share", "forward_window_overlap"]:
            if col in iv: iv[col] = iv[col].map(lambda x: _pct(x) if pd.notna(x) else "N/A")
        for col in ["median_dwell", "mean_dwell", "class_entropy"]:
            if col in iv: iv[col] = iv[col].map(lambda x: _fmt(x, 2))
        st.dataframe(iv, width="stretch", hide_index=True)

    if str(selected_int.get("status", "")).upper() == "FAIL":
        st.markdown('<div class="qrl-warning"><b>TARGET QUALITY · FAIL</b><br>The selected proxy changes too frequently and/or lacks sufficient dwell or separation for a strong regime claim. Treat model scores as tactical-label research until the target gate clears.</div>', unsafe_allow_html=True)
    elif str(selected_int.get("status", "")).upper() == "WARN":
        st.markdown('<div class="qrl-warning"><b>TARGET QUALITY · WARN</b><br>The target is usable for research, but persistence/separation remains borderline. Compare RAW and PERSISTENT results before interpreting model superiority.</div>', unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # Multi-horizon stack: tactical / cyclical / structural are not forced to agree.
    # ------------------------------------------------------------------
    _section_header("Multi-Horizon Regime Stack", "TACTICAL · CYCLICAL · STRUCTURAL", "Independent 5D / 20D / 63D live states; disagreement is preserved rather than forced away.")
    with st.spinner("Calibrating multi-horizon live states…"):
        stack, stack_probs = _multi_horizon_cached(regime_frame, str(target_mode), int(confirmation_days), int(min_dwell), str(scaler), float(winsor_z), float(decoherence), float(coupling), float(dt))
    if not stack.empty:
        sv = stack.copy()
        sv["Dominant Probability"] = sv["Dominant Probability"].map(_pct)
        for col in ["Entropy", "Purity", "Spectral Gap"]: sv[col] = sv[col].map(lambda x: _fmt(x, 3))
        mh1, mh2 = st.columns([0.88, 1.12])
        with mh1:
            st.dataframe(sv, width="stretch", hide_index=True)
        with mh2:
            fig = go.Figure()
            for h, p in stack_probs.items():
                layer = stack.loc[stack["Horizon"] == h, "Layer"].iloc[0] if (stack["Horizon"] == h).any() else f"{h}D"
                fig.add_trace(go.Bar(name=f"{layer} · {h}D", x=list(REGIME_LABELS), y=p))
            fig.update_layout(template="plotly_dark", barmode="group", height=355, yaxis_tickformat=".0%", title="Live probability mass by horizon")
            st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_mh_stack")
        if len(set(stack["Dominant Regime"].astype(str))) > 1:
            st.caption("Cross-horizon disagreement is retained, not forced away: tactical, cyclical and structural states can legitimately differ.")

    # ------------------------------------------------------------------
    # Predictive Validation Ladder.
    # ------------------------------------------------------------------
    _section_header("Validation Ladder · Out-of-Sample", "PURGED EXPANDING WINDOW", "Predictive ranking after horizon purge; Level 3 now requires dependence-aware block-bootstrap evidence.")
    display_metrics = metrics.copy()
    percent_cols = ["Accuracy", "Balanced Accuracy", "Macro F1", "Transition Accuracy", "Risk-Off Recall", "Mean Confidence", "ECE"]
    for col in percent_cols: display_metrics[col] = display_metrics[col].map(lambda x: _pct(x) if pd.notna(x) else "N/A")
    display_metrics["MCC"] = display_metrics["MCC"].map(lambda x: _fmt(x, 3))
    display_metrics["OOS Log Loss"] = display_metrics["OOS Log Loss"].map(lambda x: _fmt(x, 4))
    display_metrics["Brier Score"] = display_metrics["Brier Score"].map(lambda x: _fmt(x, 4))
    display_metrics["Start"] = pd.to_datetime(display_metrics["Start"]).dt.strftime("%Y-%m-%d")
    display_metrics["End"] = pd.to_datetime(display_metrics["End"]).dt.strftime("%Y-%m-%d")
    st.dataframe(display_metrics, width="stretch", hide_index=True)

    qrow = metrics.loc[metrics["Model"] == "Quantum Density"].iloc[0]
    crow = metrics.loc[metrics["Model"] == best_classical].iloc[0]
    prow = metrics.loc[metrics["Model"] == "Historical Prior"].iloc[0]
    delta_ll = float(crow["OOS Log Loss"] - qrow["OOS Log Loss"]); delta_prior = float(prow["OOS Log Loss"] - qrow["OOS Log Loss"])
    b1, b2, b3, b4, b5, b6 = st.columns(6)
    b1.metric("Validation status", f"L{validation['level']} · {validation['label']}")
    b2.metric("Best naive baseline", best_baseline); b3.metric("Best learned control", best_classical)
    b4.metric("Prior − Quantum LL", f"{delta_prior:+.4f}", help="Positive means Quantum has lower OOS log loss.")
    b5.metric("Control − Quantum LL", f"{delta_ll:+.4f}", help="Positive means Quantum has lower OOS log loss.")
    b6.metric("Bootstrap p-value", _fmt(boot.get("p_value"), 3))
    st.markdown(f'<div class="qrl-warning"><b>RESEARCH VERDICT · LEVEL {int(validation["level"])} — {escape(str(validation["label"]))}</b><br>{escape(str(validation["detail"]))} <b>Quantum advantage: NOT ESTABLISHED.</b> Level 4 additionally requires a robust net economic-value test; Level 5 requires end-to-end hardware advantage.</div>', unsafe_allow_html=True)

    _section_header("Chronology & Dependence Audit", "METHOD VALIDATION", "Every refit purges the forward label horizon; block bootstrap tests whether the log-loss edge survives serial dependence.")
    audit = result.get("purge_audit", pd.DataFrame()).copy()
    bt = result.get("bootstrap_table", pd.DataFrame()).copy()
    ess = result.get("effective_sample_size", {})
    ma1, ma2, ma3, ma4 = st.columns(4)
    ma1.metric("Purge gap", f"{int(result.get('purge_gap', 0))}d")
    ma2.metric("Chronology audit", "PASS" if result.get("purge_pass") else "FAIL")
    ma3.metric("Effective OOS N", _fmt(ess.get("effective_n"), 0))
    ma4.metric("Nominal OOS N", f"{int(ess.get('nominal_n', result.get('oos_observations', 0)) or 0):,}")
    if not bt.empty:
        btv = bt.copy()
        for col in ["Delta LL", "CI Low", "CI High", "p-value"]:
            btv[col] = btv[col].map(lambda x: _fmt(x, 4 if col != "p-value" else 3))
        btv["Block Length"] = btv["Block Length"].map(lambda x: f"{int(float(x))}d")
        st.dataframe(btv, width="stretch", hide_index=True)
    if not audit.empty:
        av = audit.copy()
        for c in ["Last Training Feature Date", "Last Training Label Realization Date", "First Test Date", "Test End Date"]:
            if c in av:
                av[c] = pd.to_datetime(av[c]).dt.strftime("%Y-%m-%d")
        st.dataframe(av, width="stretch", hide_index=True, height=min(300, 42 + 36 * len(av)))
    st.caption("L3 is based on the most conservative block-bootstrap result across 5/10/20/40-day blocks, not on an IID resample.")

    # ------------------------------------------------------------------
    # Economic utility — convert probabilities into the same regime-policy map.
    # ------------------------------------------------------------------
    _section_header("Economic Utility Benchmark", "NET OF TURNOVER COSTS", "Common probability-to-allocation map, next-day execution, CEQ and circular-block economic bootstrap.")
    econ = result.get("economic_utility", {})
    egate = result.get("economic_gate", {})
    if econ.get("available"):
        em = econ["metrics"].copy()
        ev = em.copy()
        for col in ["CAGR", "Ann Vol", "Max Drawdown", "CVaR 95", "Ann Turnover", "CEQ"]:
            ev[col] = ev[col].map(lambda x: _pct(x) if pd.notna(x) else "N/A")
        for col in ["Sharpe", "Sortino"]: ev[col] = ev[col].map(lambda x: _fmt(x, 2))
        ev["Total Cost bps"] = ev["Total Cost bps"].map(lambda x: _fmt(x, 1))
        st.dataframe(ev, width="stretch", hide_index=True)
        best_econ = str(econ.get("best_control") or "N/A")
        q_econ = em.loc[em["Model"] == "Quantum Density"]
        c_econ = em.loc[em["Model"] == best_econ] if best_econ in em["Model"].values else pd.DataFrame()
        q_ceq = float(q_econ.iloc[0]["CEQ"]) if not q_econ.empty else np.nan
        c_ceq = float(c_econ.iloc[0]["CEQ"]) if not c_econ.empty else np.nan
        eb = econ.get("bootstrap", {})
        e1, e2, e3, e4, e5 = st.columns(5)
        e1.metric("Economic gate", str(egate.get("label", "N/A")))
        e2.metric("Best economic control", best_econ)
        e3.metric("Quantum − Control CEQ", _pct(q_ceq - c_ceq) if np.isfinite(q_ceq) and np.isfinite(c_ceq) else "N/A")
        e4.metric("Δ annual return bootstrap", _pct(eb.get("delta_ann_return")))
        e5.metric("Economic bootstrap p", _fmt(eb.get("p_value"), 3))
        fig = go.Figure()
        show_models = [m for m in ["Quantum Density", "Classical Centroid", "Historical Prior", best_econ, "60/40 Equity-Bond", "1/N Cross-Asset"] if m in econ.get("wealth", {})]
        seen = set()
        for name in show_models:
            if name in seen: continue
            seen.add(name)
            w = econ["wealth"][name]
            fig.add_trace(go.Scatter(x=w.index, y=w.values, mode="lines", name=name))
        fig.update_layout(template="plotly_dark", height=430, title=f"Net wealth index · {float(econ.get('transaction_cost_bps', transaction_cost_bps)):.1f} bps / turnover", yaxis_title="Growth of 1")
        st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_economic_wealth")
        st.caption("Common policy map: each model's regime probabilities are converted into the same Equity/TLT/Gold/HYG allocation matrix. Signals at t are applied to next-day returns; costs are charged on one-way turnover. This tests economic usefulness, not physical quantum behavior.")
    else:
        st.info(str(econ.get("reason", "Economic benchmark unavailable.")))

    # ------------------------------------------------------------------
    # Matched classical encoder → quantum layer decomposition.
    # ------------------------------------------------------------------
    _section_header("Matched Encoder · Classical → Quantum", "EXPLAINABILITY LAYER", "The encoder is held fixed so the probability delta isolates phase / density / Hamiltonian transformation.")
    delta = probs - classical_probs
    transform = pd.DataFrame({"Regime": list(REGIME_LABELS), "Classical Encoder": classical_probs, "Quantum Density": probs, "Quantum − Classical": delta})
    tc1, tc2 = st.columns([1.10, 0.90])
    with tc1:
        fig = go.Figure(); fig.add_trace(go.Bar(name="Classical Encoder", x=list(REGIME_LABELS), y=classical_probs)); fig.add_trace(go.Bar(name="Quantum Density", x=list(REGIME_LABELS), y=probs))
        fig.update_layout(template="plotly_dark", barmode="group", height=390, yaxis_tickformat=".0%", title="Probability mass before vs after phase / density / Hamiltonian layer")
        st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_transform")
    with tc2:
        tview = transform.copy()
        for col in ["Classical Encoder", "Quantum Density", "Quantum − Classical"]: tview[col] = tview[col].map(lambda x: _pct(x, 2))
        st.dataframe(tview, width="stretch", hide_index=True)
        st.caption(f"Matched-layer bootstrap: ΔLL={_fmt(boot_matched.get('delta'), 4)} · 95% CI [{_fmt(boot_matched.get('ci_low'), 4)}, {_fmt(boot_matched.get('ci_high'), 4)}] · p={_fmt(boot_matched.get('p_value'), 3)}")

    pred = result["predictions"]
    st.markdown("### OOS Regime Probability · Model-vs-Model")
    models = ["Quantum Density", "Classical Centroid", "Historical Prior", "HMM · Multivariate", "Markov Switching · Return/Vol"]
    tm1, tm2, tm3 = st.columns([1, 1, 1])
    model_a = tm1.selectbox("Model A", models, index=0, key=f"{PREFIX}_model_a"); model_b = tm2.selectbox("Model B", models, index=1, key=f"{PREFIX}_model_b"); regime_focus = tm3.selectbox("Regime focus", list(REGIME_LABELS), index=1, key=f"{PREFIX}_regime_focus")
    fig = go.Figure(); fig.add_trace(go.Scatter(x=pred.index, y=pred[f"{model_a} · {regime_focus}"], mode="lines", name=f"{model_a} · {regime_focus}")); fig.add_trace(go.Scatter(x=pred.index, y=pred[f"{model_b} · {regime_focus}"], mode="lines", name=f"{model_b} · {regime_focus}")); realized = (pred["Target"] == regime_focus).astype(float); fig.add_trace(go.Scatter(x=pred.index, y=realized, mode="lines", name="Realized forward proxy", line=dict(dash="dot"), opacity=0.55))
    fig.update_layout(template="plotly_dark", height=450, yaxis_range=[0, 1], yaxis_tickformat=".0%", title=f"{regime_focus} probability comparison", legend_orientation="h")
    st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_compare_timeline")

    lead = result.get("transition_lead_summary", pd.DataFrame()).copy(); events = result.get("transition_lead_events", pd.DataFrame()).copy()
    if not lead.empty:
        st.markdown("#### Proxy Transition Timing Diagnostic · ±20 Trading Days")
        lead_view = lead.copy()
        for col in ["Detection Rate", "Early Share", "On-Time Share", "Late Share", "Miss Share"]: lead_view[col] = lead_view[col].map(lambda x: _pct(x))
        for col in ["Mean Lead Days", "Median Lead Days"]: lead_view[col] = lead_view[col].map(lambda x: _fmt(x, 2))
        l1, l2 = st.columns([1.15, 0.85])
        with l1: st.dataframe(lead_view, width="stretch", hide_index=True)
        with l2:
            if not events.empty:
                ev = events.tail(14).copy(); ev["Transition Date"] = pd.to_datetime(ev["Transition Date"]).dt.strftime("%Y-%m-%d"); ev["Probability at Transition"] = ev["Probability at Transition"].map(lambda x: _pct(x)); st.dataframe(ev, width="stretch", hide_index=True)
        st.caption("Lead > 0 means early, near 0 means on-time, lead < 0 means late. The diagnostic uses proxy-regime changes, not official macro turning-point dates.")

    _section_header("Hamiltonian / Transition Structure", "SPECTRAL STATE ENGINE", "Transition-derived Hamiltonian, calibrated transition matrix and eigen-spectrum diagnostics.")
    hcol, tcol = st.columns(2)
    with hcol:
        h = np.real(np.asarray(result["current_hamiltonian"], dtype=complex)); fig = go.Figure(go.Heatmap(z=h, x=list(REGIME_LABELS), y=list(REGIME_LABELS), colorbar=dict(title="Hᵢⱼ"))); fig.update_layout(template="plotly_dark", height=405, title="Current transition-derived Hamiltonian · Re(H)"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_hamiltonian")
    with tcol:
        fig = go.Figure(go.Heatmap(z=np.asarray(result["transition_matrix"], dtype=float), x=list(REGIME_LABELS), y=list(REGIME_LABELS), colorbar=dict(title="P"))); fig.update_layout(template="plotly_dark", height=405, title="Calibrated regime transition matrix"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_transition")
    hdiag = result.get("hamiltonian_diagnostics", {}); eig = np.asarray(hdiag.get("eigenvalues", []), dtype=float)
    hc1, hc2, hc3, hc4 = st.columns(4); hc1.metric("Spectral gap λ₂−λ₁", _fmt(hdiag.get("spectral_gap"), 4)); hc2.metric("Minimum level spacing", _fmt(hdiag.get("minimum_gap"), 4)); hc3.metric("Operator norm", _fmt(hdiag.get("operator_norm"), 4)); hc4.metric("Frobenius norm", _fmt(hdiag.get("frobenius_norm"), 4))
    if len(eig):
        fig = go.Figure(go.Bar(x=[f"λ{i+1}" for i in range(len(eig))], y=eig, text=[_fmt(x, 4) for x in eig], textposition="outside")); fig.update_layout(template="plotly_dark", height=340, title="Hamiltonian eigen-spectrum"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_h_spectrum")

    _section_header("Market State Encoder · Attribution & Ablation", "FACTOR STABILITY", "Contribution concentration and leave-one-factor-out live-state sensitivity.")
    attribution = result["factor_attribution"].copy(); concentration = result.get("factor_concentration", {})
    fc1, fc2, fc3 = st.columns(3); fc1.metric("Contribution HHI", _fmt(concentration.get("hhi"), 3)); fc2.metric("Effective factor count", _fmt(concentration.get("effective_factors"), 2)); fc3.metric("Largest contribution share", _pct(concentration.get("top_share")))
    fleft, fright = st.columns([1.10, 0.90])
    with fleft:
        fig = go.Figure(go.Bar(x=attribution["Dominant-State Contribution"], y=attribution["Factor"], orientation="h")); fig.update_layout(template="plotly_dark", height=455, title=f"Contribution toward current dominant state · {dominant}", yaxis_autorange="reversed"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_attribution")
    with fright:
        view = attribution.copy(); view["Standardized Input"] = view["Standardized Input"].map(lambda x: _fmt(x, 3)); view["Dominant-State Contribution"] = view["Dominant-State Contribution"].map(lambda x: _fmt(x, 4)); st.dataframe(view, width="stretch", hide_index=True, height=420)
    ablation = result.get("factor_ablation", pd.DataFrame()).copy()
    if not ablation.empty:
        st.markdown("#### Leave-One-Factor-Out · Live State Sensitivity"); av = ablation.copy(); av["Δ Dominant Probability"] = av["Δ Dominant Probability"].map(lambda x: _pct(x, 2)); av["L1 Probability Shift"] = av["L1 Probability Shift"].map(lambda x: _pct(x, 2)); st.dataframe(av, width="stretch", hide_index=True)

    _section_header("Validation Diagnostics", "CALIBRATION · CLASS BALANCE", "Confusion structure, classwise metrics, ECE/Brier calibration and imbalance diagnostics.")
    v1, v2 = st.columns([1.0, 1.0])
    with v1:
        conf = np.asarray(result["confusion"], dtype=int); fig = go.Figure(go.Heatmap(z=conf, x=list(REGIME_LABELS), y=list(REGIME_LABELS), colorbar=dict(title="count"), text=conf, texttemplate="%{text}")); fig.update_layout(template="plotly_dark", height=390, title="Quantum Density · OOS confusion matrix", xaxis_title="Predicted", yaxis_title="Forward proxy target"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_confusion")
    with v2:
        cls = result["per_class_metrics"]["Quantum Density"].copy()
        for col in ["Prevalence", "Precision", "Recall", "F1", "Predicted Share"]: cls[col] = cls[col].map(lambda x: _pct(x) if pd.notna(x) else "N/A")
        st.dataframe(cls, width="stretch", hide_index=True, height=390)

    cal = result["calibration"]["Quantum Density"].copy(); imbalance = result.get("class_imbalance", pd.DataFrame()).copy()
    cc1, cc2 = st.columns([1.05, 0.95])
    with cc1:
        fig = go.Figure()
        if not cal.empty: fig.add_trace(go.Scatter(x=cal["Mean Confidence"], y=cal["Empirical Accuracy"], mode="lines+markers", name="Top-label ECE"))
        fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="Perfect calibration", line=dict(dash="dash"))); fig.update_layout(template="plotly_dark", height=370, xaxis_range=[0, 1], yaxis_range=[0, 1], xaxis_tickformat=".0%", yaxis_tickformat=".0%", title="Confidence calibration · reliability curve"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_calibration")
    with cc2:
        if not imbalance.empty:
            iv = imbalance.copy(); iv["Prevalence"] = iv["Prevalence"].map(lambda x: _pct(x)); iv["Imbalance Ratio"] = iv["Imbalance Ratio"].map(lambda x: _fmt(x, 2)); iv["Normalized Class Entropy"] = iv["Normalized Class Entropy"].map(lambda x: _fmt(x, 3)); st.dataframe(iv, width="stretch", hide_index=True)
        st.caption(f"Quantum top-label ECE: {_pct(float(qrow['ECE']))} · Scaler: {result.get('scaler', scaler)} · standardized cap: ±{_fmt(result.get('winsor_z', winsor_z), 1)}σ")

    cs = result.get("classwise_calibration", {}).get("Quantum Density", pd.DataFrame()).copy()
    if not cs.empty:
        st.markdown("#### Classwise Calibration · Brier / ECE by Regime")
        csv = cs.copy()
        for col in ["Classwise ECE", "Mean Probability", "Observed Prevalence"]: csv[col] = csv[col].map(_pct)
        csv["Classwise Brier"] = csv["Classwise Brier"].map(lambda x: _fmt(x, 4))
        st.dataframe(csv, width="stretch", hide_index=True)

    diag = pd.DataFrame({"Diagnostic": ["Data source", "Aligned research sample", "OOS sample", "Forward proxy horizon", "Target mode", "Confirmation days", "Minimum dwell", "Initial training observations", "Expanding refit cadence", "Scaler", "Winsor cap", "Decoherence", "Hamiltonian coupling", "Strategy transaction cost", "Economic risk aversion γ"], "Value": [regime_source, f"{int(result['sample_observations']):,}", f"{int(result['oos_observations']):,}", f"{int(result['horizon'])} trading days", str(result.get("target_mode", target_mode)), f"{int(result.get('confirmation_days', confirmation_days))}d", f"{int(result.get('min_dwell', min_dwell))}d", f"{int(result['train_start_observations']):,}", f"{int(result['retrain_every'])} trading days", str(result.get("scaler", scaler)), f"±{_fmt(result.get('winsor_z', winsor_z), 1)} standardized units", _fmt(result["decoherence"], 2), _fmt(result["coupling"], 2), f"{_fmt(result.get('transaction_cost_bps', transaction_cost_bps), 1)} bps / turnover", _fmt(result.get("economic_gamma", economic_gamma), 1)]})
    st.dataframe(diag, width="stretch", hide_index=True)
    purge_diag = pd.DataFrame({"Diagnostic": ["Purged label gap", "Chronology audit", "Effective OOS observations", "Bootstrap dependence blocks"], "Value": [f"{int(result.get('purge_gap', 0))} trading days", "PASS" if result.get("purge_pass") else "FAIL", _fmt(result.get("effective_sample_size", {}).get("effective_n"), 0), "5 / 10 / 20 / 40 trading days"]})
    st.dataframe(purge_diag, width="stretch", hide_index=True)
    st.markdown('<div class="qrl-warning"><b>Methodological boundary:</b> RISK-ON / RISK-OFF / INFLATION / DEFLATION are forward cross-asset evaluation proxies, not official macro regimes. RAW and PERSISTENT targets are shown separately. Persistence filtering acts only on the evaluation-label timeline. Historical Prior and Majority Class remain train-only at each expanding refit. Each refit purges the full forward-label horizon before the OOS block, and Level 3 uses dependence-aware block bootstrap.</div>', unsafe_allow_html=True)

    with st.expander("Feature dictionary / no-look-ahead audit", expanded=False):
        dictionary = pd.DataFrame([
            ("eq_ret_1", "1D return of selected instrument", "t only"), ("eq_mom_20", "20D momentum", "through t"), ("eq_mom_60", "60D momentum", "through t"), ("rv_20", "20D annualized realized volatility", "through t"), ("drawdown_60", "distance to 60D rolling high", "through t"), ("vix_level / vix_change_5", "VIX state and 5D change", "through t"), ("TLT / GLD / HYG factors", "cross-asset momentum / credit relative state", "through t"), ("target_regime_raw", "forward score argmax", "evaluation only; never X_t"), ("target_regime_persistent", "causal confirmation + minimum dwell applied to raw target sequence", "evaluation only; never X_t"), ("economic return", "probability-based weights at t applied to t+1 return", "strictly forward execution"),
        ], columns=["Field", "Meaning", "Chronology"])
        st.dataframe(dictionary, width="stretch", hide_index=True)


def _qmc_lab(price_data: pd.DataFrame | None) -> None:
    _section_header(
        "Quantum Monte Carlo / Risk Command Deck · V2.3.2",
        "AMPLITUDE ESTIMATION CORE",
        "Canonical classical snapshots, randomized-QMC validation, bounded-payoff amplitude normalisation, product-aware resource envelopes and a total-error-feasible classical↔quantum break-even frontier.",
    )

    feat = market_features(price_data)
    default_s0 = float(max(feat.get("last", 100.0), 1.0))
    raw_default_vol = float(np.clip(feat.get("ann_vol", 0.25), 0.05, 1.50))
    default_vol = float(
        round(0.05 + round((raw_default_vol - 0.05) / 0.01) * 0.01, 2)
    )

    c1, c2, c3, c4 = st.columns(4)
    product = c1.selectbox("Payoff", ["European", "Asian Arithmetic", "Barrier", "Basket"], key=f"{PREFIX}_qmc_product")
    option_type = c2.selectbox("Option side", ["Call", "Put"], key=f"{PREFIX}_qmc_side")
    model_options = ["GBM / Black-Scholes"] if product == "Basket" else ["GBM / Black-Scholes", "Heston"]
    model = c3.selectbox("Underlying model", model_options, key=f"{PREFIX}_qmc_model")
    method = c4.selectbox("Primary classical method", ["Control variate", "Antithetic", "Sobol QMC", "Pseudo-random"], key=f"{PREFIX}_qmc_method")

    a, b, c, d, e = st.columns(5)
    s0 = a.number_input("Spot", min_value=0.01, value=round(default_s0, 2), step=max(default_s0 * 0.01, 0.1), key=f"{PREFIX}_qmc_s0")
    strike = b.number_input("Strike", min_value=0.01, value=round(default_s0, 2), step=max(default_s0 * 0.01, 0.1), key=f"{PREFIX}_qmc_k")
    maturity = c.slider("Maturity (years)", 0.05, 3.0, 1.0, 0.05, key=f"{PREFIX}_qmc_t")
    rate = d.slider("Risk-free rate", -0.02, 0.15, 0.03, 0.005, key=f"{PREFIX}_qmc_r")
    vol = e.slider("Volatility", 0.05, 1.50, default_vol, 0.01, key=f"{PREFIX}_qmc_vol")

    f, g, h, i = st.columns(4)
    paths = f.select_slider("Primary MC paths", options=[1000, 5000, 10000, 25000, 50000, 100000], value=25000, key=f"{PREFIX}_qmc_paths")
    steps = g.select_slider("Time steps", options=[16, 32, 64, 96, 128, 252], value=64, key=f"{PREFIX}_qmc_steps")
    confidence = h.slider("Confidence", 0.80, 0.999, 0.95, 0.005, key=f"{PREFIX}_qmc_conf")
    rqmc_scrambles = i.select_slider("RQMC scrambles", options=[8, 16, 32], value=16, key=f"{PREFIX}_rqmc_scrambles")

    barrier_level = 0.80 * float(s0)
    barrier_direction = "Down-and-Out"
    basket_assets = 4
    basket_corr = 0.35
    raw_heston_variance = float(np.clip(vol * vol, 0.0025, 0.50))
    heston_variance_default = float(
        round(
            0.0025
            + round((raw_heston_variance - 0.0025) / 0.0025) * 0.0025,
            4,
        )
    )
    heston_kappa, heston_theta, heston_xi, heston_rho, heston_v0 = 1.8, heston_variance_default, 0.45, -0.65, heston_variance_default

    if product == "Barrier":
        bc1, bc2 = st.columns(2)
        barrier_direction = bc1.selectbox("Barrier structure", ["Down-and-Out", "Up-and-Out"], key=f"{PREFIX}_barrier_direction")
        default_barrier = 0.80 * float(s0) if barrier_direction.startswith("Down") else 1.20 * float(s0)
        barrier_level = bc2.number_input("Barrier level", min_value=0.01, value=round(default_barrier, 2), step=max(float(s0) * 0.01, 0.1), key=f"{PREFIX}_barrier_level")
    elif product == "Basket":
        bc1, bc2 = st.columns(2)
        basket_assets = bc1.slider("Basket assets", 2, 10, 4, 1, key=f"{PREFIX}_basket_n")
        basket_corr = bc2.slider("Equicorrelation ρ", -0.10, 0.90, 0.35, 0.05, key=f"{PREFIX}_basket_corr")

    if model == "Heston":
        with st.expander("Heston stochastic-volatility parameters", expanded=False):
            hc1, hc2, hc3, hc4, hc5 = st.columns(5)
            heston_kappa = hc1.slider("κ", 0.10, 6.0, 1.80, 0.10, key=f"{PREFIX}_hes_kappa")
            heston_theta = hc2.slider("θ variance", 0.0025, 0.50, heston_variance_default, 0.0025, key=f"{PREFIX}_hes_theta")
            heston_xi = hc3.slider("ξ vol-of-vol", 0.05, 2.0, 0.45, 0.05, key=f"{PREFIX}_hes_xi")
            heston_rho = hc4.slider("ρ spot/vol", -0.95, 0.95, -0.65, 0.05, key=f"{PREFIX}_hes_rho")
            heston_v0 = hc5.slider("v₀", 0.0025, 0.50, heston_variance_default, 0.0025, key=f"{PREFIX}_hes_v0")

    with st.spinner("Building canonical pricing snapshot + randomized-QMC diagnostics…"):
        suite = _qmc_pricing_suite_cached(
            float(s0), float(strike), float(maturity), float(rate), float(vol), str(product), str(option_type), str(model), int(paths), int(steps), str(method),
            float(barrier_level), str(barrier_direction), int(basket_assets), float(basket_corr),
            float(heston_kappa), float(heston_theta), float(heston_xi), float(heston_rho), float(heston_v0), int(rqmc_scrambles),
        )

    reference = suite["reference"]
    selected = suite["selected"]
    bench = suite["benchmark"].copy()
    conv = suite["convergence"].copy()
    rqmc = suite["rqmc"].copy()
    convergence_models = suite["convergence_models"].copy()
    best_classical = bench.iloc[0] if not bench.empty else pd.Series({"Method": method, "Runtime ms": selected["runtime_ms"], "Paths": selected["paths"], "Robust Error": selected["stderr"]})

    reference_label = str(reference.get("kind", "Classical reference"))
    error = float(selected["price"] - float(reference["price"]))
    if str(method) == "Sobol QMC" and not rqmc.empty:
        ridx = (rqmc["Paths"] - int(paths)).abs().idxmin()
        primary_precision = float(rqmc.loc[ridx, "RMSE"])
        precision_label = f"RQMC RMSE {primary_precision:.5f}"
        precision_note = f"{int(rqmc_scrambles)} independent scrambles · err {error:+.4f}"
    else:
        primary_precision = float(selected["stderr"])
        precision_label = f"SE {primary_precision:.5f}"
        precision_note = f"{selected.get('stderr_basis', 'SE diagnostic')} · err {error:+.4f}"

    command_cards = [
        ("REFERENCE CONTROL", reference_label, f"{float(reference['price']):.4f}"),
        ("CANONICAL SNAPSHOT", str(selected["method_executed"]), f"seed {int(suite['snapshot_seed'])} · {float(selected['runtime_ms']):.1f} ms"),
        ("ROBUST PRECISION", precision_label, precision_note),
        ("MODEL / PAYOFF", str(model).replace(" / Black-Scholes", ""), f"{product} · {option_type}"),
    ]
    html = '<div class="qmc-command-grid">'
    for label, value, note in command_cards:
        html += f'<div class="qmc-command-card"><div class="qmc-command-label">{escape(label)}</div><div class="qmc-command-value">{escape(value)}</div><div class="qmc-command-note">{escape(note)}</div></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

    pricing_tab, risk_tab, resource_tab, frontier_tab = st.tabs(["PRICING & CONVERGENCE", "TAIL RISK / EXPOSURE", "QAE RESOURCE INTELLIGENCE", "ADVANTAGE FRONTIER"])

    with pricing_tab:
        _section_header("Classical Monte Carlo Control Stack", "CANONICAL CLASSICAL SNAPSHOT", "Cards, tables and charts share the same deterministic run set. Pseudo-random, antithetic, control-variate and Sobol controls are not independently re-simulated for display.")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric(reference_label, _fmt(reference["price"], 4))
        m2.metric("Primary MC price", _fmt(selected["price"], 4), delta=f"{error:+.4f} vs ref")
        m3.metric("Robust precision", _fmt(primary_precision, 5))
        m4.metric("Snapshot runtime", f"{float(selected['runtime_ms']):.2f} ms")
        m5.metric("Best robust error-time", str(best_classical.get("Method", "N/A")))

        bv = bench.copy()
        for col in ["Price", "Abs Error", "Signed Error", "Std Error", "CI Width", "Control Beta", "Robust Error", "Robust Error-Time"]:
            if col in bv.columns: bv[col] = bv[col].map(lambda x: _fmt(x, 6 if col in {"Std Error", "Abs Error", "Robust Error"} else 4))
        if "Runtime ms" in bv.columns: bv["Runtime ms"] = bv["Runtime ms"].map(lambda x: _fmt(x, 2))
        st.dataframe(bv, width="stretch", hide_index=True)

        _section_header("Randomized Sobol Validation", "RANDOMIZED QMC", "Sobol precision is evaluated across independent randomized scrambles. RMSE across scrambles replaces the misleading single-scramble IID-SE interpretation.")
        if not rqmc.empty:
            rq = rqmc.copy()
            slope = float(rq["Empirical RMSE slope"].dropna().iloc[0]) if rq["Empirical RMSE slope"].notna().any() else float("nan")
            r1, r2, r3, r4 = st.columns(4)
            nearest = rq.loc[(rq["Paths"] - int(paths)).abs().idxmin()]
            r1.metric("Independent scrambles", f"{int(rqmc_scrambles)}")
            r2.metric("RQMC RMSE", _fmt(nearest["RMSE"], 6))
            r3.metric("Scramble SD", _fmt(nearest["Scramble SD"], 6))
            r4.metric("Empirical slope", _fmt(slope, 3), help="Slope of log(RMSE) vs log(paths); more negative indicates faster empirical convergence.")
            rqv = rq[["Paths", "Scrambles", "Mean Price", "RMSE", "Mean Abs Error", "Scramble SD", "SE of Scramble Mean", "Mean Runtime ms"]].copy()
            for col in ["Mean Price", "RMSE", "Mean Abs Error", "Scramble SD", "SE of Scramble Mean", "Mean Runtime ms"]:
                rqv[col] = rqv[col].map(lambda x: _fmt(x, 6 if col != "Mean Runtime ms" else 2))
            st.dataframe(rqv, width="stretch", hide_index=True)

        pc1, pc2 = st.columns([1.05, 0.95])
        with pc1:
            fig = go.Figure()
            for meth, sub in conv.groupby("Method"):
                if str(meth) == "Sobol QMC" and not rqmc.empty:
                    continue
                fig.add_trace(go.Scatter(x=sub["Paths"], y=sub["Std Error"].clip(lower=1e-8), mode="lines+markers", name=f"{meth} · SE"))
            if not rqmc.empty:
                fig.add_trace(go.Scatter(x=rqmc["Paths"], y=rqmc["RMSE"].clip(lower=1e-8), mode="lines+markers", name=f"Sobol · {int(rqmc_scrambles)}-scramble RMSE"))
            fig.update_layout(template="plotly_dark", height=410, xaxis_type="log", yaxis_type="log", xaxis_title="Paths", yaxis_title="Precision proxy", title="Empirical precision scaling")
            st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_qmc_conv_error")
        with pc2:
            fig = go.Figure()
            for meth, sub in conv.groupby("Method"):
                fig.add_trace(go.Scatter(x=sub["Paths"], y=sub["Runtime ms"].clip(lower=1e-6), mode="lines+markers", name=str(meth)))
            fig.update_layout(template="plotly_dark", height=410, xaxis_type="log", yaxis_type="log", xaxis_title="Paths", yaxis_title="Executed runtime (ms)", title="Executed classical runtime scaling")
            st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_qmc_conv_runtime")

        if not convergence_models.empty:
            _section_header("Empirical Scaling Fits", "CLASSICAL SCALING MODEL", "Precision and runtime are fit separately. These fits drive the break-even frontier instead of assuming a constant milliseconds-per-sample cost.")
            cm = convergence_models.copy()
            for col in ["Precision c", "Precision beta", "Precision R2", "Runtime c", "Runtime gamma", "Runtime R2"]:
                cm[col] = cm[col].map(lambda x: _fmt(x, 4))
            st.dataframe(cm, width="stretch", hide_index=True)

        sample = np.asarray(selected.get("raw_discounted_payoff_sample", selected.get("discounted_payoff_sample", [])), dtype=float)
        if len(sample):
            fig = go.Figure(go.Histogram(x=sample, nbinsx=70, name="raw discounted payoff"))
            fig.update_layout(template="plotly_dark", height=330, title="Raw discounted payoff distribution · canonical snapshot", xaxis_title="Discounted payoff", yaxis_title="Count")
            st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_qmc_payoff_hist")

        if reference_label != "Analytic Black-Scholes":
            st.markdown('<div class="qrl-warning"><b>Reference boundary:</b> this payoff/model has no analytic control implemented in the lab. The displayed reference is a higher-path classical control, not ground truth.</div>', unsafe_allow_html=True)
        if selected["method_executed"] != method:
            st.markdown(f'<div class="qrl-warning"><b>Execution fallback:</b> requested {escape(method)}, executed {escape(str(selected["method_executed"]))}. The fallback is shown explicitly and is not labelled Sobol.</div>', unsafe_allow_html=True)

        _section_header("Greeks & Sensitivity Control", "DERIVATIVE SENSITIVITY", "Analytic Black-Scholes Greeks are used only for European/GBM. Other contracts use common-seed finite-difference classical controls.")
        greeks = _qmc_greeks_cached(
            float(s0), float(strike), float(maturity), float(rate), float(vol), str(product), str(option_type), str(model), int(steps),
            float(barrier_level), str(barrier_direction), int(basket_assets), float(basket_corr),
            float(heston_kappa), float(heston_theta), float(heston_xi), float(heston_rho), float(heston_v0),
        )
        gc1, gc2, gc3, gc4, gc5 = st.columns(5)
        gc1.metric("Delta", _fmt(greeks.get("delta"), 4)); gc2.metric("Gamma", _fmt(greeks.get("gamma"), 6)); gc3.metric("Vega / 1.00 vol", _fmt(greeks.get("vega"), 4)); gc4.metric("Theta / year", _fmt(greeks.get("theta"), 4)); gc5.metric("Rho / 1.00 rate", _fmt(greeks.get("rho"), 4))

    with risk_tab:
        _section_header("Tail-Risk Computation", "P / Q MEASURE SEPARATION", "Market VaR/CVaR is simulated under a user-controlled physical-measure drift P. Counterparty EE/PFE/CVA remains a risk-neutral Q exposure control using the pricing rate.")
        rc1, rc2, rc3, rc4 = st.columns(4)
        horizon_days = rc1.select_slider("Risk horizon (days)", options=[1, 5, 10, 20, 63], value=10, key=f"{PREFIX}_risk_horizon")
        scenarios = rc2.select_slider("Risk scenarios", options=[5000, 10000, 25000, 50000, 100000], value=25000, key=f"{PREFIX}_risk_scenarios")
        drift = rc3.slider("Physical drift μP", -0.50, 0.50, 0.0, 0.01, key=f"{PREFIX}_risk_drift")
        hazard = rc4.slider("Counterparty hazard λQ", 0.001, 0.20, 0.02, 0.001, key=f"{PREFIX}_hazard")
        rc5, rc6, rc7 = st.columns(3)
        recovery = rc5.slider("Recovery", 0.0, 0.90, 0.40, 0.05, key=f"{PREFIX}_recovery")
        exposure_paths = rc6.select_slider("Exposure paths", options=[5000, 10000, 15000, 25000, 50000], value=15000, key=f"{PREFIX}_exp_paths")
        exposure_points = rc7.slider("Exposure dates", 4, 24, 12, 1, key=f"{PREFIX}_exp_dates")
        full_reval = product == "European" and model.startswith("GBM")
        rb = _qmc_risk_cached(
            float(s0), float(strike), float(maturity), float(rate), float(vol), str(option_type), float(selected["price"]), int(horizon_days), int(scenarios), float(drift),
            float(greeks.get("delta", 0.0) or 0.0), float(greeks.get("gamma", 0.0) or 0.0), full_reval,
            int(exposure_paths), int(exposure_points), float(hazard), float(recovery),
        )
        risk = rb["risk"]; exposure = rb["exposure"]
        st.markdown(
            '<div class="qmc-command-grid">'
            f'<div class="qmc-command-card"><div class="qmc-command-label">MARKET RISK MEASURE</div><div class="qmc-command-value">P · PHYSICAL</div><div class="qmc-command-note">μP={float(drift):+.2%} · {int(horizon_days)}d</div></div>'
            f'<div class="qmc-command-card"><div class="qmc-command-label">EXPOSURE MEASURE</div><div class="qmc-command-value">Q · RISK-NEUTRAL</div><div class="qmc-command-note">drift r={float(rate):.2%} · unilateral exposure</div></div>'
            f'<div class="qmc-command-card"><div class="qmc-command-label">VaR / CVaR ENGINE</div><div class="qmc-command-value">{escape(rb["risk_mode"])}</div><div class="qmc-command-note">{int(scenarios):,} scenarios</div></div>'
            f'<div class="qmc-command-card"><div class="qmc-command-label">CVA CONTROL</div><div class="qmc-command-value">{_fmt(exposure["cva"],4)}</div><div class="qmc-command-note">λQ={float(hazard):.2%} · R={float(recovery):.0%}</div></div>'
            '</div>', unsafe_allow_html=True,
        )
        rm1, rm2, rm3, rm4, rm5, rm6 = st.columns(6)
        rm1.metric("VaR 95", _fmt(risk["var_95"], 4)); rm2.metric("CVaR 95", _fmt(risk["cvar_95"], 4)); rm3.metric("VaR 99", _fmt(risk["var_99"], 4)); rm4.metric("CVaR 99", _fmt(risk["cvar_99"], 4)); rm5.metric("Peak PFE 95", _fmt(exposure["peak_pfe"], 4)); rm6.metric("Peak EE", _fmt(exposure["peak_ee"], 4))
        rl, rr = st.columns([1.0, 1.0])
        with rl:
            pnl = np.asarray(risk["pnl"], dtype=float)
            fig = go.Figure(go.Histogram(x=pnl, nbinsx=80, name="P&L")); fig.update_layout(template="plotly_dark", height=390, title="P-measure scenario P&L distribution", xaxis_title="P&L", yaxis_title="Count"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_risk_hist")
        with rr:
            ep = exposure["profile"]
            fig = go.Figure(); fig.add_trace(go.Scatter(x=ep["Time"], y=ep["EE"], mode="lines+markers", name="Expected Exposure")); pfe_col = [x for x in ep.columns if str(x).startswith("PFE")][0]; fig.add_trace(go.Scatter(x=ep["Time"], y=ep[pfe_col], mode="lines+markers", name=pfe_col)); fig.update_layout(template="plotly_dark", height=390, title="Q-measure exposure term structure", xaxis_title="Years", yaxis_title="Exposure"); st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_exposure")
        if not full_reval:
            st.markdown('<div class="qrl-warning"><b>Risk-model boundary:</b> selected contract uses delta-gamma VaR/CVaR. PFE/CVA is shown as a European-equivalent GBM Q-measure exposure control at the same S/K/T/vol; nested path-dependent repricing is not fabricated.</div>', unsafe_allow_html=True)

    with resource_tab:
        _section_header("Bounded Payoff Encoding", "AMPLITUDE NORMALISATION", "Amplitude estimation requires a bounded [0,1] random variable. The lab therefore exposes the payoff cap, truncation tail and the conversion from normalized epsilon to absolute price error.")
        n1, n2, n3 = st.columns(3)
        eps = n1.slider("Target normalized amplitude error ε", 0.0002, 0.05, 0.002, 0.0002, format="%.4f", key=f"{PREFIX}_qae_eps")
        tail_text = n2.selectbox("Truncation tail probability", ["1e-2", "1e-3", "1e-4", "1e-5", "1e-6"], index=2, key=f"{PREFIX}_tail_prob")
        tail_probability = float(tail_text)
        algorithm = n3.selectbox("Amplitude-estimation family", ["Canonical QAE", "Iterative QAE", "Maximum-Likelihood QAE"], index=1, key=f"{PREFIX}_qae_algo")
        raw_sample = np.asarray(selected.get("raw_discounted_payoff_sample", []), dtype=float)
        norm_info = qae_payoff_normalization(
            float(s0), float(strike), float(maturity), float(rate), float(vol), str(product), str(option_type), str(model),
            tail_probability=float(tail_probability), raw_discounted_sample=raw_sample,
        )
        payoff_cap = max(float(norm_info["payoff_cap"]), 1e-12)
        target_price_error = float(eps) * payoff_cap
        trunc_price_error = float(norm_info["truncation_price_error"])
        nm1, nm2, nm3, nm4, nm5 = st.columns(5)
        nm1.metric("Discounted payoff cap", _fmt(payoff_cap, 4))
        nm2.metric("Normalized ε", _pct(float(eps)))
        nm3.metric("Equivalent price error", _fmt(target_price_error, 4))
        nm4.metric("Truncation price error", _fmt(trunc_price_error, 6))
        nm5.metric("Encoding", str(norm_info["normalization_kind"]))
        if np.isfinite(float(norm_info.get("s_min", np.nan))) and np.isfinite(float(norm_info.get("s_max", np.nan))):
            st.caption(f"Risk-neutral terminal truncation support: S ∈ [{float(norm_info['s_min']):.2f}, {float(norm_info['s_max']):.2f}] · requested tail mass {float(tail_probability):.1e}.")
        elif float(norm_info.get("empirical_resolution", 0.0)) > float(tail_probability):
            st.markdown(f'<div class="qrl-warning"><b>Empirical tail resolution:</b> requested {float(tail_probability):.1e}, but the canonical raw-payoff sample resolves only about {float(norm_info["empirical_resolution"]):.1e}. The cap uses the empirical resolution floor.</div>', unsafe_allow_html=True)

        _section_header("QAE Resource Intelligence", "PRODUCT-AWARE RESOURCE MODEL", "Algorithm-level query envelopes are combined with explicit state-preparation, payoff, logical-gate, measurement and fault-tolerance assumptions. Path dependence and stochastic volatility now change the resource envelope.")
        q1, q2, q3 = st.columns(3)
        state_qubits = q1.slider("Base state-register qubits", 4, 30, 12, 1, key=f"{PREFIX}_qae_qubits")
        prep_depth = q2.slider("Base state-preparation depth", 50, 5000, 500, 50, key=f"{PREFIX}_prep_depth")
        payoff_depth = q3.slider("Base payoff/oracle depth", 25, 2500, 250, 25, key=f"{PREFIX}_payoff_depth")
        q4, q5, q6 = st.columns(3)
        logical_gate_ns = q4.slider("Logical gate time (ns)", 1.0, 1000.0, 50.0, 1.0, key=f"{PREFIX}_gate_ns")
        ft_overhead = q5.select_slider("Fault-tolerance time overhead", options=[1, 10, 100, 300, 1000, 3000, 10000], value=1000, key=f"{PREFIX}_ft")
        measurement_us = q6.slider("Measurement / query latency (μs)", 0.0, 1000.0, 5.0, 1.0, key=f"{PREFIX}_measure")
        q7, q8 = st.columns(2)
        physical_per_logical = q7.select_slider("Physical / logical qubit", options=[10, 50, 100, 300, 1000, 3000, 10000], value=1000, key=f"{PREFIX}_phys_log")
        profile = product_resource_profile(str(product), str(model), int(steps), int(basket_assets))
        q8.info(f"Product envelope: {profile['resource_label']} · +{int(profile['work_qubits'])} work qubits · prep×{float(profile['prep_multiplier']):.1f} · payoff×{float(profile['payoff_multiplier']):.1f}")

        res = quantum_resource_estimate_product(
            float(eps), float(confidence), str(algorithm), int(state_qubits), int(prep_depth), int(payoff_depth),
            float(logical_gate_ns), float(ft_overhead), float(measurement_us), int(physical_per_logical),
            str(product), str(model), int(steps), int(basket_assets),
        )
        algo_table = qae_algorithm_projection(float(eps), float(confidence))
        st.markdown(
            '<div class="qmc-pipeline">'
            '<div class="qmc-node"><div class="qmc-node-title">STATE PREP</div><div class="qmc-node-sub">A |0〉 → bounded state</div></div>'
            '<div class="qmc-node"><div class="qmc-node-title">PAYOFF CAP</div><div class="qmc-node-sub">f / fmax ∈ [0,1]</div></div>'
            '<div class="qmc-node"><div class="qmc-node-title">AMPLIFICATION</div><div class="qmc-node-sub">Grover iterate</div></div>'
            '<div class="qmc-node"><div class="qmc-node-title">ESTIMATION</div><div class="qmc-node-sub">QAE / IQAE / MLQAE</div></div>'
            '<div class="qmc-node"><div class="qmc-node-title">PRICE MAP</div><div class="qmc-node-sub">a × payoff cap</div></div>'
            '</div>', unsafe_allow_html=True,
        )
        qm1, qm2, qm3, qm4, qm5, qm6 = st.columns(6)
        qm1.metric("Oracle/query envelope", f"{int(res['queries']):,}"); qm2.metric("Logical qubits", f"{int(res['logical_qubits']):,}"); qm3.metric("Physical qubits proj.", f"{int(res['physical_qubits']):,}"); qm4.metric("Adjusted prep depth", f"{int(res['adjusted_prep_depth']):,}"); qm5.metric("Total logical depth", f"{int(res['total_depth']):,}"); qm6.metric("Engineering runtime", f"{res['projected_runtime_s']:.2f}s")
        at = algo_table.copy(); at["Queries"] = at["Queries"].map(lambda x: f"{int(x):,}"); st.dataframe(at, width="stretch", hide_index=True)

        _section_header("Error Budget", "FINANCIAL ERROR BUDGET", "Normalized amplitude, discretization, state-preparation, hardware and truncation components are translated into a price-error envelope through the payoff cap.")
        eb1, eb2, eb3 = st.columns(3)
        default_disc = 0.0 if (product == "European" and model.startswith("GBM")) else 0.005
        disc_err = eb1.slider("Discretization error", 0.0, 0.10, float(default_disc), 0.001, key=f"{PREFIX}_disc_err")
        prep_err = eb2.slider("State-preparation error", 0.0, 0.10, 0.005, 0.001, key=f"{PREFIX}_prep_err")
        hardware_err = eb3.slider("Hardware/noise error", 0.0, 0.20, 0.01, 0.002, key=f"{PREFIX}_hw_err")
        trunc_norm = trunc_price_error / payoff_cap
        budget = qae_error_budget(float(eps), float(disc_err), float(prep_err), float(hardware_err), float(trunc_norm))
        price_rss = float(budget["rss_total"]) * payoff_cap
        be1, be2, be3, be4, be5, be6 = st.columns(6)
        be1.metric("Amplitude est.", _pct(budget["amplitude"])); be2.metric("Discretization", _pct(budget["discretization"])); be3.metric("State prep", _pct(budget["state_prep"])); be4.metric("Hardware", _pct(budget["hardware"])); be5.metric("Truncation", _pct(budget["truncation"])); be6.metric("RSS price envelope", _fmt(price_rss, 4))
        st.markdown('<div class="qrl-warning"><b>Resource boundary:</b> product-aware qubits, depth and runtime remain engineering projections, not compiled circuits. Payoff normalisation and truncation are now explicit, but a hardware advantage claim still requires end-to-end measured execution.</div>', unsafe_allow_html=True)

    with frontier_tab:
        _section_header("Classical ↔ Quantum Break-Even Surface", "TOTAL-ERROR ADVANTAGE FRONTIER", "The frontier now operates on total absolute price error. Non-AE error components create an explicit feasibility floor; classical fits are bounded by their observed calibration domain before any break-even statement is allowed.")
        resource_kwargs = dict(
            state_qubits=int(state_qubits), state_prep_depth=int(prep_depth), payoff_depth=int(payoff_depth),
            logical_gate_ns=float(logical_gate_ns), fault_tolerance_overhead=float(ft_overhead),
            measurement_us=float(measurement_us), physical_per_logical=int(physical_per_logical),
            product=str(product), model=str(model), steps=int(steps), basket_assets=int(basket_assets),
        )
        floor_diag = qae_total_error_feasibility(
            0.0, float(payoff_cap), float(disc_err), float(prep_err), float(hardware_err), float(trunc_price_error)
        )
        error_floor_price = float(floor_diag["error_floor_price"])
        current_total_price_error = float(price_rss)
        raw_grid = float(payoff_cap) * np.geomspace(0.0002, 0.15, 60)
        total_grid = np.unique(np.sort(np.append(raw_grid, current_total_price_error)))
        frontier = product_advantage_frontier(
            total_grid, float(payoff_cap), float(confidence), str(algorithm), convergence_models, resource_kwargs,
            discretization_error=float(disc_err), state_prep_error=float(prep_err), hardware_error=float(hardware_err),
            truncation_price_error=float(trunc_price_error),
        )
        if frontier.empty:
            st.error("Insufficient classical convergence data to build the total-error frontier.")
        else:
            feasible = frontier[frontier["Feasible"]].copy()
            eligible = feasible[feasible["Break-even Eligible"]].copy()
            current_idx = (frontier["Target price error"] - current_total_price_error).abs().idxmin()
            current = frontier.loc[current_idx]
            max_row = eligible.loc[eligible["Speed ratio C/Q"].idxmax()] if not eligible.empty else None
            crossover = eligible[eligible["Speed ratio C/Q"] > 1.0] if not eligible.empty else pd.DataFrame()
            if feasible.empty:
                status = "NO FEASIBLE QUANTUM TARGETS"; note = "the current non-AE error floor dominates the entire requested frontier"; cls = "qrl-warn"
            elif crossover.empty:
                status = "NO MODELLED CROSSOVER"; note = f"best eligible frontier C/Q {_ratio_fmt(max_row['Speed ratio C/Q']) if max_row is not None else 'N/A'}"; cls = "qrl-warn"
            else:
                status = "MODELLED CROSSOVER EXISTS"; note = f"eligible in-domain diagnostic only · max {_ratio_fmt(max_row['Speed ratio C/Q'])}"; cls = "qrl-pass"
            st.markdown(f'<div class="qmc-frontier"><div class="qmc-frontier-title">BREAK-EVEN STATUS</div><div class="qmc-frontier-main {cls}">{escape(status)}</div><div class="qmc-frontier-note">{escape(note)}. This is not a measured QPU advantage.</div></div>', unsafe_allow_html=True)

            current_feas = bool(current["Feasible"])
            fm1, fm2, fm3, fm4, fm5, fm6 = st.columns(6)
            fm1.metric("Current total price error", _fmt(current_total_price_error, 4))
            fm2.metric("Irreducible error floor", _fmt(error_floor_price, 4))
            fm3.metric("AE budget available", _fmt(current.get("AE budget price"), 4) if current_feas else "INFEASIBLE")
            fm4.metric("Best classical", str(current["Best classical method"]))
            fm5.metric("Current C/Q ratio", _ratio_fmt(current["Speed ratio C/Q"]))
            fm6.metric("Best eligible ratio", _ratio_fmt(max_row["Speed ratio C/Q"]) if max_row is not None else "N/A")

            _section_header("Why No Crossover?", "BOTTLENECK DIAGNOSTIC", "The lab decomposes whether the blocker is the classical control, the non-AE error floor, state preparation / fault tolerance, or the projected query latency.")
            best_classical_runtime = float(current["Classical projected ms"]) if np.isfinite(float(current["Classical projected ms"])) else float("nan")
            query_latency = float(current["Projected query ms"]) if current_feas and np.isfinite(float(current["Projected query ms"])) else float("nan")
            break_even_q = float(current["Break-even query ms"]) if current_feas and np.isfinite(float(current["Break-even query ms"])) else float("nan")
            bottlenecks = [
                ("CLASSICAL SPEED", "STRONG CONTROL" if np.isfinite(best_classical_runtime) else "UNAVAILABLE", "qrl-pass" if np.isfinite(best_classical_runtime) else "qrl-warn"),
                ("QUERY COMPLEXITY", "QUANTUM-FAVOURABLE ASYMPTOTIC", "qrl-pass"),
                ("ERROR FLOOR", "BOTTLENECK" if error_floor_price >= 0.5 * current_total_price_error else "MANAGEABLE", "qrl-warn" if error_floor_price >= 0.5 * current_total_price_error else "qrl-pass"),
                ("STATE PREP / FT", "BOTTLENECK" if float(ft_overhead) > 10 or float(prep_depth) > 100 else "LIGHT", "qrl-warn" if float(ft_overhead) > 10 or float(prep_depth) > 100 else "qrl-pass"),
                ("QUERY LATENCY", "BOTTLENECK" if np.isfinite(query_latency) and np.isfinite(break_even_q) and query_latency > break_even_q else "COMPETITIVE", "qrl-warn" if np.isfinite(query_latency) and np.isfinite(break_even_q) and query_latency > break_even_q else "qrl-pass"),
                ("CURRENT HARDWARE", "NOT COMPETITIVE" if status != "MODELLED CROSSOVER EXISTS" else "TEST CANDIDATE", "qrl-warn" if status != "MODELLED CROSSOVER EXISTS" else "qrl-pass"),
            ]
            bh = '<div class="qmc-command-grid">'
            for label, value, klass in bottlenecks:
                bh += f'<div class="qmc-command-card"><div class="qmc-command-label">{escape(label)}</div><div class="qmc-command-value {klass}">{escape(value)}</div></div>'
            bh += '</div>'
            st.markdown(bh, unsafe_allow_html=True)

            fl, fr = st.columns([1.0, 1.0])
            with fl:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=frontier["Target price error"], y=frontier["Classical projected ms"], mode="lines", name="Best empirical classical"))
                fig.add_trace(go.Scatter(x=feasible["Target price error"], y=feasible["Quantum engineering ms"], mode="lines", name="Quantum engineering projection"))
                if error_floor_price > 0:
                    fig.add_vline(x=error_floor_price, line_dash="dash", annotation_text="quantum error floor")
                fig.update_layout(template="plotly_dark", height=420, xaxis_type="log", yaxis_type="log", xaxis_title="Target total absolute price error", yaxis_title="Projected runtime (ms)", title="Runtime frontier · total-price-error space")
                st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_frontier_runtime")
            with fr:
                fig = go.Figure()
                if not eligible.empty:
                    fig.add_trace(go.Scatter(x=eligible["Target price error"], y=eligible["Speed ratio C/Q"], mode="lines", name="Eligible C/Q ratio"))
                fig.add_hline(y=1.0, line_dash="dash", annotation_text="modelled break-even")
                if error_floor_price > 0:
                    fig.add_vline(x=error_floor_price, line_dash="dash", annotation_text="error floor")
                fig.update_layout(template="plotly_dark", height=420, xaxis_type="log", yaxis_type="log", xaxis_title="Target total absolute price error", yaxis_title="Classical / Quantum runtime", title="Engineering break-even ratio · in-domain only")
                st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_frontier_ratio")

            ft = frontier.iloc[::8].copy()
            display_cols = ["Target price error", "Error floor price", "AE budget price", "Feasible", "Best classical method", "Classical required paths", "Classical domain", "Precision R2", "Runtime R2", "Classical projected ms", "Quantum engineering ms", "Speed ratio C/Q", "Break-even query ms"]
            ft = ft[[c for c in display_cols if c in ft.columns]]
            for col in ["Target price error", "Error floor price", "AE budget price", "Classical required paths", "Precision R2", "Runtime R2", "Classical projected ms", "Quantum engineering ms", "Break-even query ms"]:
                if col in ft.columns: ft[col] = ft[col].map(lambda x: _fmt(x, 4))
            if "Speed ratio C/Q" in ft.columns: ft["Speed ratio C/Q"] = ft["Speed ratio C/Q"].map(_ratio_fmt)
            st.dataframe(ft, width="stretch", hide_index=True)

            extrap = frontier[frontier["Classical domain"] == "EXTRAPOLATED"]
            infeasible = frontier[~frontier["Feasible"]]
            if len(infeasible):
                st.markdown(f'<div class="qrl-warning"><b>Total-error feasibility gate:</b> {len(infeasible)} frontier points are below the current non-AE price-error floor of {error_floor_price:.4f} and are marked INFEASIBLE rather than assigned a quantum runtime.</div>', unsafe_allow_html=True)
            if len(extrap):
                st.markdown(f'<div class="qrl-warning"><b>Calibration-domain boundary:</b> {len(extrap)} classical points require more paths than the observed runtime grid. They remain visible as EXTRAPOLATED diagnostics but are excluded from any break-even declaration. Requirements below the observed minimum are floored to the smallest actually benchmarked path count.</div>', unsafe_allow_html=True)
            if not convergence_models.empty and float(convergence_models[["Precision R2", "Runtime R2"]].min().min()) < 0.50:
                st.markdown('<div class="qrl-warning"><b>Fit-quality warning:</b> at least one empirical scaling fit has weak log-space R². Frontier values using that fit should be treated as sensitivity diagnostics, not planning estimates.</div>', unsafe_allow_html=True)
            st.markdown('<div class="qrl-warning"><b>Advantage claim policy:</b> a projected crossover is only a hardware-testing hypothesis. Comparable optimized classical implementations, state loading, truncation, compilation, error correction, queue latency and repeated shots must be measured end-to-end before the lab can use the term “quantum advantage”.</div>', unsafe_allow_html=True)


def _portfolio_lab() -> tuple[pd.DataFrame, str]:
    _section_header(
        "QUBO / Ising Portfolio Engine · V2.4.1",
        "CONSTRAINT-PRESERVING PORTFOLIO OPTIMISATION",
        "Binary equal-weight selection with hard-constraint presolve, minimum-safe penalty diagnostics, exact/MILP/heuristic controls, X-vs-XY QAOA statevector research and empirical classical-hardness benchmarking. No QPU output is fabricated.",
    )
    raw = st.text_input("Research universe", "SPY, QQQ, IWM, TLT, GLD, HYG", key=f"{PREFIX}_universe")
    symbols = list(dict.fromkeys([x.strip().upper() for x in raw.split(",") if x.strip()]))[:12]
    if len(symbols) < 2:
        st.error("Enter at least two unique assets."); return pd.DataFrame(), "invalid universe"
    returns, source = _load_returns_cached(tuple(symbols))
    if returns.empty:
        st.error("Unable to construct an aligned return matrix."); return pd.DataFrame(), source
    labels=list(returns.columns); n=len(labels); mu,cov=annualized_moments(returns)

    _section_header("Institutional Binary Selection Problem", "PORTFOLIO COMPILER", "Hard business rules are audited classically, then required/excluded bits are presolved before the constraint-preserving QAOA comparison.")
    c1,c2,c3,c4=st.columns(4)
    k=c1.slider("Exact cardinality K",1,n,min(3,n),1,key=f"{PREFIX}_k_v241")
    risk=c2.slider("Risk aversion λ",0.1,25.0,5.0,0.1,key=f"{PREFIX}_lambda_v241")
    penalty=c3.slider("Constraint penalty M",0.1,50.0,12.0,0.1,key=f"{PREFIX}_penalty_v241")
    tcost=c4.slider("Transaction cost / turnover (bps)",0.0,100.0,5.0,1.0,key=f"{PREFIX}_tcost_v241")
    c5,c6,c7=st.columns(3)
    turnover_penalty=c5.slider("Turnover preference penalty",0.0,2.0,0.10,0.02,key=f"{PREFIX}_turn_pen_v241")
    target_enabled=c6.checkbox("Target annual return",False,key=f"{PREFIX}_target_on_v241")
    target_return=c6.slider("Target return",-0.10,0.35,0.10,0.01,key=f"{PREFIX}_target_ret_v241",disabled=not target_enabled)
    target_penalty=c7.slider("Target-return penalty",0.0,50.0,5.0 if target_enabled else 0.0,0.5,key=f"{PREFIX}_target_pen_v241",disabled=not target_enabled)
    prev=st.multiselect("Previous holdings · turnover reference",labels,default=[],key=f"{PREFIX}_prev_v241")
    a,b=st.columns(2)
    required=a.multiselect("Required assets",labels,default=[],key=f"{PREFIX}_req_v241")
    excluded=b.multiselect("Excluded assets",[x for x in labels if x not in required],default=[],key=f"{PREFIX}_exc_v241")
    if len(required)>k or n-len(excluded)<k:
        st.error("Required/excluded rules are incompatible with K."); return returns,source
    prev_x=np.array([x in prev for x in labels],float); req=np.array([x in required for x in labels],float); exc=np.array([x in excluded for x in labels],float)
    compiled=build_portfolio_qubo_components(mu,cov,risk_aversion=risk,cardinality=k,constraint_penalty=penalty,turnover_penalty=turnover_penalty,transaction_cost_bps=tcost,previous_x=prev_x,target_return=float(target_return) if target_enabled else None,target_return_penalty=float(target_penalty) if target_enabled else 0.0,required_mask=req,excluded_mask=exc)
    pre=presolve_portfolio_qubo(compiled,labels)
    audit=qubo_penalty_audit(compiled["Q"],offset=compiled["offset"],cardinality=k,required_mask=req,excluded_mask=exc)
    pfront=qubo_penalty_frontier(compiled)
    if not pre.get("available"):
        st.error(pre.get("reason","Presolve unavailable.")); return returns,source

    pipe='''<div class="qmc-pipeline"><div class="qmc-node"><div class="qmc-node-title">FINANCIAL CORE</div><div class="qmc-node-sub">μ · Σ · costs</div></div><div class="qmc-node"><div class="qmc-node-title">HARD PRESOLVE</div><div class="qmc-node-sub">required / excluded</div></div><div class="qmc-node"><div class="qmc-node-title">REDUCED QUBO</div><div class="qmc-node-sub">free variables only</div></div><div class="qmc-node"><div class="qmc-node-title">DICKE + XY</div><div class="qmc-node-sub">exact K subspace</div></div><div class="qmc-node"><div class="qmc-node-title">HARDNESS</div><div class="qmc-node-sub">classical controls</div></div></div>'''
    st.markdown(pipe,unsafe_allow_html=True)
    fixed_txt=", ".join([f"{x}={v}" for x,v in pre["fixed_labels"].items()]) or "none"
    cards=[("FULL BINARY SPACE",f"{n} qubits",f"{2**n:,} states"),("PRESOLVED SPACE",f"{pre['reduced_size']} qubits",f"{2**pre['reduced_size']:,} states"),("EXACT-K SUBSPACE",f"{comb(pre['reduced_size'],pre['cardinality_free']):,}",f"Kfree={pre['cardinality_free']}"),("FIXED RULES",fixed_txt,"removed before QAOA"),("PENALTY AUDIT","PASS" if audit.get('pass') else "REVIEW",f"margin {_fmt(audit.get('penalty_margin'),4)}")]
    html='<div class="qmc-command-grid">'+''.join(f'<div class="qmc-command-card"><div class="qmc-command-label">{escape(a)}</div><div class="qmc-command-value">{escape(str(v))}</div><div class="qmc-command-note">{escape(str(note))}</div></div>' for a,v,note in cards)+'</div>'
    st.markdown(html,unsafe_allow_html=True)

    _section_header("Hard-Constraint Presolve & Penalty Frontier","CONSTRAINT CONDITIONING","Known hard bits are removed exactly. The penalty frontier computes the minimum M required to separate the best infeasible state from the best feasible financial state; QAOA performance is never used to tune M.")
    if pfront.get("available"):
        pc1,pc2,pc3,pc4=st.columns(4)
        pc1.metric("Minimum safe M",_fmt(pfront["minimum_safe_penalty"],6)); pc2.metric("Recommended M",_fmt(pfront["recommended_penalty"],6)); pc3.metric("Current / minimum",f"{pfront['safety_multiple']:.1f}×"); pc4.metric("Penalty / financial norm",f"{pfront['penalty_to_financial_norm']:.1f}×")
        pf=pfront["frontier"]
        fig=go.Figure(); fig.add_trace(go.Scatter(x=pf["Penalty M"],y=pf["Penalty margin"],mode="lines+markers",name="feasibility margin")); fig.add_hline(y=0,line_dash="dash"); fig.add_vline(x=pfront["minimum_safe_penalty"],line_dash="dash",annotation_text="minimum safe M"); fig.add_vline(x=penalty,line_dash="dot",annotation_text="current M"); fig.update_layout(template="plotly_dark",height=360,xaxis_type="log",xaxis_title="Penalty M",yaxis_title="Best infeasible − best feasible energy",title="Penalty adequacy frontier"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_pen_front_v241")
        if pfront['safety_multiple']>10:
            st.markdown(f'<div class="qrl-warning"><b>Hamiltonian distortion warning:</b> current M is {pfront["safety_multiple"]:.1f}× the exact minimum-safe penalty and the current penalty norm is {pfront["penalty_to_financial_norm"]:.1f}× the financial-core norm. Constraint-preserving QAOA below removes this cardinality penalty rather than optimizing through it.</div>',unsafe_allow_html=True)

    _section_header("Reduced QUBO / Ising Map","OBJECTIVE DECOMPOSITION","Full penalized QUBO remains auditable, while the reduced financial Hamiltonian shows the objective seen by the Dicke+XY circuit after hard-rule presolve and exact-cardinality restriction.")
    comp=[]
    for name,mat in compiled["components"].items(): comp.append({"Component":name,"Frobenius norm":float(np.linalg.norm(mat)),"Offset":float(compiled["component_offsets"].get(name,0))})
    compdf=pd.DataFrame(comp); st.dataframe(compdf.style.format({"Frobenius norm":"{:.6f}","Offset":"{:.6f}"}),width="stretch",hide_index=True)
    q1,q2=st.columns(2)
    with q1:
        fig=go.Figure(go.Heatmap(z=compiled["Q"],x=labels,y=labels,colorbar=dict(title="Q"))); fig.update_layout(template="plotly_dark",height=390,title="Full penalized QUBO"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_fullq_v241")
    with q2:
        fig=go.Figure(go.Heatmap(z=pre["economic_Q"],x=pre["free_labels"],y=pre["free_labels"],colorbar=dict(title="Qecon"))); fig.update_layout(template="plotly_dark",height=390,title="Presolved financial QUBO · no hard/cardinality penalty"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_econq_v241")

    _section_header("Classical Solver Arena","MANDATORY CONTROLS","Exact QUBO, hard-constrained MILP, simulated annealing and local search remain the reference controls on the full compiled objective.")
    arena=qubo_solver_arena(compiled,mu,cov,labels=labels,qaoa_layers=1,qaoa_trials=24,qaoa_shots=1024)
    adf=arena["table"].copy()
    if not adf.empty:
        for col in ["Energy","Gap vs Exact","Runtime ms"]:
            if col in adf: adf[col]=adf[col].map(lambda x:_fmt(x,5))
        for col in ["Expected Return","Volatility","Turnover","Net Expected Return","Ground Probability"]:
            if col in adf: adf[col]=adf[col].map(lambda x:_pct(x,2) if pd.notna(x) else "—")
        if "Sharpe" in adf: adf["Sharpe"]=adf["Sharpe"].map(lambda x:_fmt(x,3))
        st.dataframe(adf,width="stretch",hide_index=True)

    _section_header("Constraint-Preserving QAOA Arena","DICKE STATE · XY MIXER","Matched experiment: penalty-based X-mixer QAOA is compared with a presolved Dicke-state + XY-mixer circuit that remains inside the exact-cardinality feasible subspace by construction.")
    x1,x2,x3=st.columns(3)
    maxp=x1.slider("QAOA depth sweep",1,3,3,1,key=f"{PREFIX}_qaoa_depth_v241"); trials=x2.slider("Trials / start",12,80,32,4,key=f"{PREFIX}_qaoa_trials_v241"); starts=x3.slider("Independent optimizer starts",1,5,3,1,key=f"{PREFIX}_qaoa_starts_v241")
    study=constraint_preserving_qaoa_study(compiled,labels=labels,max_depth=maxp,trials=trials,shots=2048,starts=starts)
    if not study.get("available"):
        st.info(study.get("reason","QAOA study unavailable."))
    else:
        sdf=study["table"].copy()
        show=sdf.copy()
        for col in ["Ground Probability","Feasible Mass","Ground P mean across starts","Ground P std across starts","Feasible P mean across starts"]: show[col]=show[col].map(lambda x:_pct(x,2))
        for col in ["Conditional Expected Gap","Runtime ms"]: show[col]=show[col].map(lambda x:_fmt(x,6))
        show["Shots to 95%"] = show["Shots to 95%"].map(lambda x:"∞" if not np.isfinite(x) else f"{int(x):,}")
        show["Shots to 99%"] = show["Shots to 99%"].map(lambda x:"∞" if not np.isfinite(x) else f"{int(x):,}")
        st.dataframe(show,width="stretch",hide_index=True)
        fig=go.Figure()
        for mixer,g in sdf.groupby("Mixer"):
            fig.add_trace(go.Scatter(x=g["Depth p"],y=g["Ground Probability"],mode="lines+markers",name=f"{mixer} · ground"))
            fig.add_trace(go.Scatter(x=g["Depth p"],y=g["Feasible Mass"],mode="lines+markers",line=dict(dash="dash"),name=f"{mixer} · feasible mass"))
        fig.add_hline(y=study["uniform_feasible_ground_baseline"],line_dash="dot",annotation_text="uniform feasible ground baseline")
        fig.update_layout(template="plotly_dark",height=390,yaxis_tickformat=".0%",xaxis_title="QAOA depth p",title="Ground probability and feasible probability mass"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qaoa_compare_v241")
        best_xy=sdf[sdf["Mixer"]=="Dicke + XY"].sort_values("Ground Probability",ascending=False).iloc[0]
        best_x=sdf[sdf["Mixer"]=="Penalty X"].sort_values("Ground Probability",ascending=False).iloc[0]
        z1,z2,z3,z4=st.columns(4); z1.metric("Best XY ground probability",_pct(best_xy["Ground Probability"],2)); z2.metric("XY feasible mass",_pct(best_xy["Feasible Mass"],2)); z3.metric("Best X ground probability",_pct(best_x["Ground Probability"],2)); z4.metric("XY shots → 99%",f"{int(best_xy['Shots to 99%']):,}" if np.isfinite(best_xy['Shots to 99%']) else "∞")
        run=study["runs"].get(("XY",int(best_xy["Depth p"])))
        if run:
            dist=run["distribution"].copy(); colors=["#37e6d4" if g else ("#ff5577" if not f else "#6d79ff") for f,g in zip(dist["feasible"],dist["ground"])]
            fig=go.Figure(go.Bar(x=dist["state"],y=dist["probability"],marker_color=colors,customdata=dist[["economic_energy","feasible","shots"]])); fig.add_hline(y=study["uniform_feasible_ground_baseline"],line_dash="dash",annotation_text="uniform feasible baseline"); fig.update_traces(hovertemplate="state=%{x}<br>p=%{y:.2%}<br>Eecon=%{customdata[0]:.6f}<br>feasible=%{customdata[1]}<br>shots=%{customdata[2]}<extra></extra>"); fig.update_layout(template="plotly_dark",height=370,title="Dicke+XY top-state distribution · cyan=ground · blue=feasible",yaxis_tickformat=".0%"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_xy_dist_v241")
        land=qaoa_p1_landscape(pre["economic_Q"],offset=pre["economic_offset"],mixer="XY",hamming_weight=pre["cardinality_free"],gamma_points=25,beta_points=21)
        if land.get("available"):
            fig=go.Figure(go.Heatmap(z=land["ground_probability"],x=land["gammas"],y=land["betas"],colorbar=dict(title="P*"))); fig.update_layout(template="plotly_dark",height=390,xaxis_title="γ",yaxis_title="β",title="p=1 Dicke+XY optimisation landscape · ground probability"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_xy_land_v241")
        st.markdown('<div class="qrl-warning"><b>Execution boundary:</b> both QAOA variants are classical statevector experiments. The XY mixer demonstrates feasibility-preserving algorithm design; it is not evidence of QPU speedup.</div>',unsafe_allow_html=True)

    _section_header("Empirical Classical Hardness Frontier","CLASSICAL ↔ QUANTUM ELIGIBILITY","Synthetic scaling instances are calibrated to the current return/volatility scale. Exact feasible enumeration, MILP and cardinality-preserving heuristics are timed directly; search-space size alone never creates quantum eligibility.")
    hardness=classical_hardness_benchmark(mu,cov,cardinality_ratio=k/max(n,1),risk_aversion=risk,n_grid=(6,8,10,12,14,16,18),instances=1)
    if hardness.get("available"):
        h=hardness["summary"].copy(); st.dataframe(h.style.format({"Exact runtime ms":"{:.3f}","MILP runtime ms":"{:.3f}","MILP gap":"{:.6f}","SA runtime ms":"{:.3f}","SA gap":"{:.6f}","Local runtime ms":"{:.3f}","Local gap":"{:.6f}"}),width="stretch",hide_index=True)
        h1,h2=st.columns(2)
        with h1:
            fig=go.Figure(); fig.add_trace(go.Scatter(x=h["N"],y=h["Exact runtime ms"],mode="lines+markers",name="Exact feasible enumeration")); fig.add_trace(go.Scatter(x=h["N"],y=h["MILP runtime ms"],mode="lines+markers",name="MILP")); fig.add_trace(go.Scatter(x=h["N"],y=h["SA runtime ms"],mode="lines+markers",name="SA")); fig.add_trace(go.Scatter(x=h["N"],y=h["Local runtime ms"],mode="lines+markers",name="Local")); fig.update_layout(template="plotly_dark",height=390,yaxis_type="log",title="Measured classical runtime scaling",xaxis_title="Synthetic assets N",yaxis_title="Runtime ms"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_hard_runtime_v241")
        with h2:
            fig=go.Figure(); fig.add_trace(go.Scatter(x=h["N"],y=np.abs(h["MILP gap"]),mode="lines+markers",name="MILP gap")); fig.add_trace(go.Scatter(x=h["N"],y=np.abs(h["SA gap"]),mode="lines+markers",name="SA gap")); fig.add_trace(go.Scatter(x=h["N"],y=np.abs(h["Local gap"]),mode="lines+markers",name="Local gap")); fig.update_layout(template="plotly_dark",height=390,title="Objective gap vs exact feasible optimum",xaxis_title="Synthetic assets N",yaxis_title="Absolute energy gap"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_hard_gap_v241")
        d1,d2,d3=st.columns(3); d1.metric("Current exact-K states",f"{comb(pre['reduced_size'],pre['cardinality_free']):,}"); d2.metric("Measured hardness status",hardness["eligibility"]); d3.metric("Quantum advantage claim","NOT ELIGIBLE")
        st.caption(hardness["rationale"]+". Scaling suite is synthetic and calibrated to current moment magnitudes; it is not an out-of-sample investment backtest.")

    st.markdown('<div class="qrl-warning"><b>Research boundary:</b> V2.4.1 remains a binary equal-weight selection laboratory. Required/excluded rules are presolved exactly and XY-QAOA preserves exact cardinality, but continuous weights, lot sizes and sector matrices require separate encodings. Exact/MILP/heuristic controls remain authoritative until equal-objective simulator or hardware workflows beat them.</div>',unsafe_allow_html=True)
    rt=runtime_status(); st.caption(f"Data source: {source}. Runtime: {rt.execution_mode}. QAOA results are classical statevector emulations; QPU output is never fabricated.")
    return returns,source

def _information_lab(returns: pd.DataFrame | None, source: str | None) -> None:
    _section_header(
        "Quantum Information & Tensor Network Engine · V2.5.1",
        "STRUCTURAL INFORMATION VALIDATION",
        "Covariance-density states, amplitude-encoded pair structure and Tensor-Train / MPS compression are now stress-tested against decomposition controls, permutation nulls, parameter-budgeted Tucker/HOSVD, rank/block frontiers and rolling structural stability. All execution remains classical.",
    )

    if returns is None or returns.empty:
        returns, source = fetch_multi_asset_returns(["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"])
    if returns is None or returns.empty:
        st.info("Quantum-information structure unavailable: no aligned multi-asset returns.")
        return

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    rolling_window = c1.slider("Density window", 40, 126, 63, 1, key=f"{PREFIX}_qi_win_v251")
    rolling_step = c2.slider("Rolling step", 1, 20, 5, 1, key=f"{PREFIX}_qi_step_v251")
    pair_lookback = c3.slider("Pair-state lookback", 60, 500, 252, 1, key=f"{PREFIX}_qi_pair_v251")
    tensor_block = c4.slider("Tensor block size", 5, 63, 20, 5, key=f"{PREFIX}_qi_block_v251")
    tensor_rank = c5.slider("TT max bond rank", 2, 16, 8, 1, key=f"{PREFIX}_qi_rank_v251")
    tensor_energy = c6.slider("TT retained energy", 0.90, 0.9999, 0.995, 0.0005, format="%.4f", key=f"{PREFIX}_qi_energy_v251")
    v1, v2 = st.columns(2)
    pair_perms = v1.select_slider("Pair permutation nulls", options=[49, 99, 199], value=99, key=f"{PREFIX}_qi_pair_perm_v251")
    tensor_nulls = v2.select_slider("Tensor temporal shuffles", options=[49, 99, 199], value=99, key=f"{PREFIX}_qi_tt_null_v251")

    info = quantum_information_v2(
        returns,
        rolling_window=rolling_window,
        rolling_step=rolling_step,
        pair_lookback=pair_lookback,
        tensor_block_size=tensor_block,
        tensor_max_rank=tensor_rank,
        tensor_energy=tensor_energy,
        pair_permutations=pair_perms,
        tensor_null_shuffles=tensor_nulls,
    )
    if not info.get("available"):
        st.info(str(info.get("reason", "Information structure unavailable.")))
        return

    base=info["base"]; variants=info.get("density_variants",{}); rolling=info.get("rolling",{}); decomp=info.get("density_decomposition",{})
    pairwise=info.get("pairwise",{}); pairval=info.get("pair_validation",{}); tensor=info.get("tensor",{}); labels=list(base["labels"])
    current=rolling.get("current",{}) if rolling.get("available") else {}
    headline=[
        ("STATE ENTROPY",_fmt(base.get("entropy"),3),"covariance-density entropy",""),
        ("PURITY",_fmt(base.get("purity"),3),"Tr(ρ²)",""),
        ("STATE FIDELITY",_fmt(current.get("fidelity_prev"),4),f"vs prior {rolling_step}d state","qrl-pass" if float(current.get("fidelity_prev",0) or 0)>.95 else "qrl-warn"),
        ("TRACE DISTANCE",_fmt(current.get("trace_distance_prev"),4),f"shift percentile {_pct(current.get('trace_distance_percentile'),0)}","qrl-warn" if float(current.get("trace_distance_percentile",0) or 0)>.90 else "qrl-pass"),
    ]
    html='<div class="qrl-method-grid">'
    for label,value,note,cls in headline:
        html+=f'<div class="qrl-method-card"><div class="qrl-method-label">{escape(label)}</div><div class="qrl-method-value {cls}">{escape(str(value))}</div><div class="qrl-method-note">{escape(str(note))}</div></div>'
    html+='</div>'; st.markdown(html,unsafe_allow_html=True)

    _section_header(
        "Density-State Decomposition",
        "COVARIANCE · CORRELATION · VOLATILITY",
        "The total covariance-density state is decomposed into a correlation-geometry density and a diagonal relative-volatility density. This prevents volatility redistribution from being mislabeled as a pure correlation regime shift.",
    )
    if variants.get("available"):
        vm=[]
        for nm,title in [("covariance","Covariance density"),("correlation","Correlation density"),("volatility","Volatility density")]:
            met=variants[f"{nm}_metrics"]
            vm.append((title,met["entropy"],met["purity"],met["effective_dimension"],met["spectral_gap"]))
        st.dataframe(pd.DataFrame(vm,columns=["State","Entropy","Purity","Effective dim.","Spectral gap"]).style.format({"Entropy":"{:.3f}","Purity":"{:.3f}","Effective dim.":"{:.2f}","Spectral gap":"{:.4f}"}),width="stretch",hide_index=True)
        a,b=st.columns(2)
        with a: st.plotly_chart(_density_heatmap(variants["covariance"],labels,"Covariance density |ρΣ|"),width="stretch",key=f"{PREFIX}_qi_covrho_v251")
        with b: st.plotly_chart(_density_heatmap(variants["correlation"],labels,"Correlation geometry density |ρC|"),width="stretch",key=f"{PREFIX}_qi_corrrho_v251")
        c,d=st.columns(2)
        with c:
            fig=go.Figure(go.Bar(x=labels,y=variants["volatility_share"],text=[f"{v:.1%}" for v in variants["volatility_share"]],textposition="outside")); fig.update_layout(template="plotly_dark",height=360,title="Relative variance share · volatility density",yaxis_tickformat=".0%")
            st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_volshare_v251")
        with d:
            fig=go.Figure(go.Heatmap(z=variants["raw_correlation"],x=labels,y=labels,zmin=-1,zmax=1,colorbar=dict(title="corr"))); fig.update_layout(template="plotly_dark",height=360,title="Classical Pearson correlation control")
            st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_corrctrl_v251")

    _section_header(
        "Structural State Transition Monitor",
        "FIDELITY · TRACE DISTANCE · SHIFT ATTRIBUTION",
        "Rolling states remain strictly backward-looking. Total covariance-density change is now shown beside correlation-geometry and relative-volatility shifts so structural events can be attributed rather than merely detected.",
    )
    if rolling.get("available"):
        tl=rolling["timeline"].copy(); q1,q2,q3,q4=st.columns(4)
        q1.metric("Current fidelity",_fmt(current.get("fidelity_prev"),4)); q2.metric("Current trace distance",_fmt(current.get("trace_distance_prev"),4)); q3.metric("Quantum relative entropy",_fmt(current.get("relative_entropy_prev"),4)); q4.metric("Spectral gap",_fmt(current.get("spectral_gap"),4))
        a,b=st.columns(2)
        with a:
            fig=go.Figure(); fig.add_trace(go.Scatter(x=tl.index,y=tl["entropy"],mode="lines",name="Entropy")); fig.add_trace(go.Scatter(x=tl.index,y=tl["purity"],mode="lines",name="Purity")); fig.add_trace(go.Scatter(x=tl.index,y=tl["top_eigenvalue"],mode="lines",name="Top eigenvalue")); fig.update_layout(template="plotly_dark",height=380,title="Rolling information-state concentration"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_state_v251")
        with b:
            fig=go.Figure(); fig.add_trace(go.Scatter(x=tl.index,y=tl["trace_distance_prev"],mode="lines+markers",name="Trace distance")); fig.add_trace(go.Scatter(x=tl.index,y=1-tl["fidelity_prev"],mode="lines",name="1 − fidelity")); fig.add_trace(go.Scatter(x=tl.index,y=tl["qjs_prev"],mode="lines",name="Quantum JS")); fig.update_layout(template="plotly_dark",height=380,title="State-change intensity"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_change_v251")
        if decomp.get("available"):
            dt=decomp["timeline"].copy(); fig=go.Figure(); fig.add_trace(go.Scatter(x=dt.index,y=dt["total_shift"],mode="lines",name="Total covariance state")); fig.add_trace(go.Scatter(x=dt.index,y=dt["correlation_shift"],mode="lines",name="Correlation geometry")); fig.add_trace(go.Scatter(x=dt.index,y=dt["volatility_shift"],mode="lines",name="Relative volatility")); fig.update_layout(template="plotly_dark",height=370,title="Structural shift attribution · trace-distance channels",yaxis_title="Trace distance"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_decomp_v251")
        shocks=rolling.get("shocks",pd.DataFrame()).copy()
        if not shocks.empty:
            cols=[c for c in ["Date","trace_distance_prev","fidelity_prev","relative_entropy_prev","entropy","purity"] if c in shocks.columns]; st.dataframe(shocks[cols].head(10).style.format({"trace_distance_prev":"{:.4f}","fidelity_prev":"{:.4f}","relative_entropy_prev":"{:.4f}","entropy":"{:.3f}","purity":"{:.3f}"}),width="stretch",hide_index=True)

    _section_header(
        "Amplitude-Encoded Dependence Validation",
        "PAIRWISE REPRESENTATION · PERMUTATION CONTROL",
        "Amplitude QMI/concurrence remain representation diagnostics. They are now paired with sign-MI permutation tests, FDR control, Spearman and distance correlation so a colorful heatmap cannot be mistaken for statistical evidence.",
    )
    if pairwise.get("available"):
        plabels=pairwise["labels"]; a,b=st.columns(2)
        with a:
            fig=go.Figure(go.Heatmap(z=pairwise["qmi"],x=plabels,y=plabels,colorbar=dict(title="bits"))); fig.update_layout(template="plotly_dark",height=390,title="Amplitude-encoded QMI"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_qmi_v251")
        with b:
            fig=go.Figure(go.Heatmap(z=pairwise["classical_mi"],x=plabels,y=plabels,colorbar=dict(title="bits"))); fig.update_layout(template="plotly_dark",height=390,title="Classical sign-MI control"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_mi_v251")
        if pairval.get("available"):
            pv=pairval["table"].copy(); p1,p2,p3=st.columns(3); p1.metric("Permutation nulls",str(pairval["permutations"])); p2.metric("Pairs tested",str(pairval["pairs"])); p3.metric("QMI pairs FDR <5%",str(pairval["significant_qmi_fdr"]))
            st.dataframe(pv.head(15).style.format({"Amplitude QMI bits":"{:.4f}","QMI permutation p":"{:.3f}","QMI FDR q":"{:.3f}","Classical sign MI bits":"{:.4f}","Sign MI permutation p":"{:.3f}","Sign MI FDR q":"{:.3f}","Amplitude concurrence":"{:.4f}","Pearson":"{:.3f}","Spearman":"{:.3f}","Distance correlation":"{:.3f}"}),width="stretch",hide_index=True)

    _section_header(
        "Tensor Train / MPS Validation Core",
        "TT · TUCKER · SVD · TEMPORAL NULLS",
        "The market tensor is benchmarked against both matrix SVD and parameter-budgeted Tucker/HOSVD. Temporal ordering is tested against an empirical distribution of independent shuffles rather than a single null draw.",
    )
    if tensor.get("available"):
        tt=tensor["tt"]; svd=tensor["svd_baseline"]; tuck=tensor["tucker_baseline"]; null=tensor["null_distribution"]
        cards=[
            ("VALIDATION",tensor["validation_label"],f"robustness share {tensor['robustness_share']:.0%}","qrl-pass" if tensor["validation_level"]>=3 else "qrl-warn"),
            ("TT ERROR",f"{tt['relative_error']:.4f}",f"compression {tt['compression_ratio']:.2f}×",""),
            ("TUCKER ERROR",f"{tuck['relative_error']:.4f}",f"ranks {'-'.join(map(str,tuck['ranks']))}",""),
            ("TEMPORAL NULL p",f"{tensor['null_p_value']:.3f}",f"{null['shuffles']} independent shuffles","qrl-pass" if tensor["null_p_value"]<.05 else "qrl-warn"),
        ]
        html='<div class="qrl-method-grid">'
        for label,value,note,cls in cards: html+=f'<div class="qrl-method-card"><div class="qrl-method-label">{escape(label)}</div><div class="qrl-method-value {cls}">{escape(str(value))}</div><div class="qrl-method-note">{escape(str(note))}</div></div>'
        html+='</div>'; st.markdown(html,unsafe_allow_html=True)
        if tt.get("rank_cap_binding"):
            st.markdown('<div class="qrl-warning"><b>Rank cap binding:</b> the requested retained-energy threshold is not achieved on every TT cut. Rank and block frontiers below show whether the conclusion survives a larger representation budget.</div>',unsafe_allow_html=True)
        st.markdown('<div class="qmc-pipeline"><div class="qmc-node"><div class="qmc-node-title">MARKET TENSOR</div><div class="qmc-node-sub">time × assets × channels</div></div><div class="qmc-node"><div class="qmc-node-title">TT / MPS</div><div class="qmc-node-sub">sequential low-rank cuts</div></div><div class="qmc-node"><div class="qmc-node-title">TUCKER</div><div class="qmc-node-sub">multilinear HOSVD control</div></div><div class="qmc-node"><div class="qmc-node-title">NULL DIST.</div><div class="qmc-node-sub">independent time shuffles</div></div><div class="qmc-node"><div class="qmc-node-title">ROBUSTNESS</div><div class="qmc-node-sub">rank · block · rolling</div></div></div>',unsafe_allow_html=True)
        a,b=st.columns(2)
        with a:
            comp=pd.DataFrame({"Control":["TT/MPS","Matrix SVD","Tucker/HOSVD","Shuffle median"],"Relative error":[tt["relative_error"],svd["relative_error"],tuck["relative_error"],null["median"]]}); fig=go.Figure(go.Bar(x=comp["Control"],y=comp["Relative error"],text=[f"{v:.4f}" for v in comp["Relative error"]],textposition="outside")); fig.update_layout(template="plotly_dark",height=380,title="Compression benchmark · matched controls",yaxis_title="Relative reconstruction error"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_comp_v251")
        with b:
            fig=go.Figure(go.Histogram(x=null["errors"],nbinsx=24,name="Shuffled TT error")); fig.add_vline(x=tt["relative_error"],line_dash="dash",annotation_text="ordered TT"); fig.update_layout(template="plotly_dark",height=380,title=f"Temporal-order null distribution · p={tensor['null_p_value']:.3f}",xaxis_title="TT reconstruction error"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_null_v251")

        _section_header("Rank / Compression Frontier","REPRESENTATION CAPACITY STRESS","The conclusion must survive multiple bond-rank budgets; a single hand-picked rank is not sufficient evidence.")
        rf=tensor["rank_frontier"].copy(); fig=go.Figure(); fig.add_trace(go.Scatter(x=rf["Max rank"],y=rf["TT error"],mode="lines+markers",name="TT")); fig.add_trace(go.Scatter(x=rf["Max rank"],y=rf["SVD error"],mode="lines+markers",name="Matrix SVD")); fig.add_trace(go.Scatter(x=rf["Max rank"],y=rf["Tucker error"],mode="lines+markers",name="Tucker")); fig.update_layout(template="plotly_dark",height=380,title="Reconstruction error vs TT rank budget",xaxis_title="Max TT bond rank",yaxis_title="Relative error"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_rankfront_v251")
        st.dataframe(rf.style.format({"TT error":"{:.4f}","Compression":"{:.2f}×","Min retained":"{:.2%}","SVD error":"{:.4f}","Tucker error":"{:.4f}","TT−SVD edge":"{:+.4f}","TT−Tucker edge":"{:+.4f}"}),width="stretch",hide_index=True)

        _section_header("Block-Size Robustness","TEMPORAL GRANULARITY STRESS","The tensorisation is repeated at 5/10/20/40/63-day blocks. An edge that exists only at one block size is treated as fragile.")
        bf=tensor["block_frontier"].copy()
        if not bf.empty:
            fig=go.Figure(); fig.add_trace(go.Scatter(x=bf["Block size"],y=bf["TT error"],mode="lines+markers",name="TT")); fig.add_trace(go.Scatter(x=bf["Block size"],y=bf["SVD error"],mode="lines+markers",name="SVD")); fig.add_trace(go.Scatter(x=bf["Block size"],y=bf["Tucker error"],mode="lines+markers",name="Tucker")); fig.add_trace(go.Scatter(x=bf["Block size"],y=bf["Null median"],mode="lines+markers",name="Shuffle median")); fig.update_layout(template="plotly_dark",height=380,title="Block-size robustness frontier",xaxis_title="Trading days per block",yaxis_title="Relative error"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_blockfront_v251")
            st.dataframe(bf.style.format({"TT error":"{:.4f}","Compression":"{:.2f}×","SVD error":"{:.4f}","Tucker error":"{:.4f}","Null median":"{:.4f}","Order gain":"{:+.4f}","Null p":"{:.3f}"}),width="stretch",hide_index=True)

        _section_header("Rolling Tensor Structural Stability","OUT-OF-SAMPLE STRUCTURAL MONITOR","Rolling fixed-length tensors track reconstruction quality, bond-spectrum drift and transfer of the previous low-rank template. This is a structural stability diagnostic, not a return forecast.")
        rs=tensor.get("rolling_stability",{})
        if rs.get("available"):
            rt=rs["timeline"].copy(); a,b=st.columns(2)
            with a:
                fig=go.Figure(); fig.add_trace(go.Scatter(x=rt.index,y=rt["TT error"],mode="lines+markers",name="TT error")); fig.add_trace(go.Scatter(x=rt.index,y=rt["Min retained"],mode="lines",name="Min retained")); fig.update_layout(template="plotly_dark",height=370,title="Rolling compression stability"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_rolltt_v251")
            with b:
                fig=go.Figure(); fig.add_trace(go.Scatter(x=rt.index,y=rt["Spectrum drift"],mode="lines+markers",name="Bond-spectrum drift")); fig.add_trace(go.Scatter(x=rt.index,y=rt["Template transfer error"],mode="lines",name="Template transfer error")); fig.update_layout(template="plotly_dark",height=370,title="Structural drift / template transfer"); st.plotly_chart(fig,width="stretch",key=f"{PREFIX}_qi_ttdrift_v251")
            st.dataframe(rt.tail(12).reset_index().style.format({"TT error":"{:.4f}","Compression":"{:.2f}","Mean bond entropy":"{:.3f}","Min retained":"{:.2%}","Spectrum drift":"{:.4f}","Template transfer error":"{:.4f}"}),width="stretch",hide_index=True)

        e1,e2=st.columns(2)
        with e1: st.dataframe(tensor["asset_error"].style.format({"TT relative error":"{:.4f}"}),width="stretch",hide_index=True)
        with e2: st.dataframe(tensor["channel_error"].style.format({"TT relative error":"{:.4f}"}),width="stretch",hide_index=True)

    _section_header(
        "Research Controls & Interpretation",
        "NO PHYSICAL QUANTUM CLAIM",
        "Density operators, amplitude states and Tensor Networks remain classical constructions. V2.5.1 upgrades the claim standard from descriptive compression to falsifiable representation tests with strong classical and permutation controls.",
    )
    control_rows=[
        ("Density operator","Covariance / correlation / volatility trace-one states","Pearson / variance shares / PCA spectrum","DESCRIPTIVE + ATTRIBUTION"),
        ("State transition","Fidelity / trace distance / relative entropy","Correlation-vs-volatility shift decomposition","DESCRIPTIVE"),
        ("Pair information","Amplitude QMI / concurrence","Sign MI + Spearman + distance corr + permutation FDR","REPRESENTATION TEST"),
        ("Tensor network","TT/MPS compression","Budgeted SVD + Tucker/HOSVD + temporal-null distribution","VALIDATION TEST"),
        ("Robustness","Rank / block / rolling stability","Multiple representation budgets and temporal granularities","ROBUSTNESS TEST"),
        ("Hardware claim","None","Requires measured QPU workflow","NOT ELIGIBLE"),
    ]
    st.dataframe(pd.DataFrame(control_rows,columns=["Layer","Quantum / quantum-inspired representation","Mandatory control","Claim status"]),width="stretch",hide_index=True)
    st.markdown('<div class="qrl-warning"><b>Interpretation boundary:</b> amplitude-encoded QMI/concurrence are properties of the chosen √p map; TT bond entropy is a compression-spectrum diagnostic. Neither is physical entanglement. Rolling tensor stability is not a return forecast and Level 5 remains reserved for a separately specified out-of-sample downstream task.</div>',unsafe_allow_html=True)
    st.caption(f"Data source: {source or 'current research matrix'}. Runtime: {runtime_status().execution_mode}. Tensor Train / Tucker execution is classical NumPy SVD.")

def _benchmarks(regime_result: dict[str, Any] | None, portfolio_returns: pd.DataFrame | None) -> None:
    _section_header(
        "Quantum Evidence & Benchmark Command Center · V2.6.1",
        "RESEARCH EVIDENCE · CLAIM GOVERNANCE",
        "Frozen-engine evidence is consolidated without retuning the underlying models. V2.6.1 adds coverage-aware event ranking and deterministic evidence provenance so claims remain tied to code, configuration and data cutoffs.",
    )

    st.markdown(
        '''<style>
        .qev-hero{position:relative;overflow:hidden;border:1px solid rgba(65,224,255,.22);border-radius:20px;padding:20px 22px;margin:4px 0 18px;background:linear-gradient(115deg,rgba(4,24,40,.96),rgba(10,15,37,.98) 52%,rgba(34,13,58,.92));box-shadow:0 0 42px rgba(29,194,255,.07)}
        .qev-hero:after{content:"";position:absolute;left:-30%;top:0;width:30%;height:100%;background:linear-gradient(90deg,transparent,rgba(88,230,255,.08),transparent);animation:qevScan 9s linear infinite}
        @keyframes qevScan{0%{left:-35%}100%{left:110%}}
        .qev-kicker{font-size:.70rem;letter-spacing:.22em;color:#65e8ff;font-weight:800;margin-bottom:7px}.qev-title{font-size:1.35rem;font-weight:800;color:#f4f7ff}.qev-sub{font-size:.84rem;color:#9aa9be;margin-top:6px;max-width:1100px}
        .qev-ledger{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 18px}.qev-ledger-card{border:1px solid rgba(85,213,255,.17);border-radius:15px;padding:13px;background:rgba(5,16,30,.72)}.qev-ledger-k{font-size:.58rem;letter-spacing:.16em;color:#7188a5;font-weight:800}.qev-ledger-v{font-size:1.02rem;color:#f4f7ff;font-weight:800;margin-top:5px}.qev-ledger-n{font-size:.68rem;color:#8ca0b7;margin-top:4px}
        .qev-engine-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:12px 0 20px}.qev-engine{position:relative;border:1px solid rgba(87,221,255,.18);border-radius:17px;padding:15px 16px;background:linear-gradient(135deg,rgba(4,21,35,.80),rgba(17,12,38,.78));overflow:hidden}.qev-engine:before{content:"";position:absolute;left:0;top:0;height:2px;width:100%;background:linear-gradient(90deg,#48e8ff,#7d6aff,#ff5577);opacity:.75}.qev-engine-name{font-size:.65rem;letter-spacing:.15em;color:#6ceaff;font-weight:800}.qev-engine-main{font-size:1.05rem;font-weight:850;color:#f4f7ff;margin:6px 0}.qev-engine-note{font-size:.74rem;line-height:1.45;color:#91a2b8}.qev-tag{display:inline-block;margin-top:8px;border:1px solid rgba(255,255,255,.12);border-radius:999px;padding:4px 8px;font-size:.60rem;letter-spacing:.08em;color:#b9c6d8}
        .qev-claim-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:10px 0 18px}.qev-claim{border:1px solid rgba(83,214,255,.16);border-radius:16px;padding:15px;background:rgba(5,15,29,.72)}.qev-claim h4{margin:0 0 10px;color:#71eaff;font-size:.78rem;letter-spacing:.10em}.qev-claim-row{margin:7px 0;color:#a6b5c8;font-size:.73rem;line-height:1.45}.qev-claim-row b{color:#eef4ff}
        .qev-coverage{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:6px 0 12px}.qev-pill{border:1px solid rgba(255,255,255,.12);border-radius:999px;padding:4px 9px;font-size:.62rem;color:#b8c6d9;background:rgba(4,18,31,.72)}.qev-pill.full{border-color:rgba(69,224,175,.35);color:#8df0c9}.qev-pill.partial{border-color:rgba(255,190,85,.35);color:#ffd18c}
        @media(max-width:900px){.qev-ledger,.qev-engine-grid,.qev-claim-grid{grid-template-columns:1fr 1fr}}@media(max-width:650px){.qev-ledger,.qev-engine-grid,.qev-claim-grid{grid-template-columns:1fr}}
        </style>''',
        unsafe_allow_html=True,
    )

    event_returns = portfolio_returns
    if not isinstance(event_returns, pd.DataFrame) or event_returns.empty:
        event_returns, _ = _load_returns_cached(("SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"))

    config_payloads = {
        "REGIME / DENSITY": {
            "horizon": st.session_state.get(f"{PREFIX}_reg_horizon", 5),
            "train_fraction": st.session_state.get(f"{PREFIX}_reg_train", 0.65),
            "retrain_every": st.session_state.get(f"{PREFIX}_reg_refit", 63),
            "scaler": st.session_state.get(f"{PREFIX}_reg_scaler", "standard"),
            "target_mode": st.session_state.get(f"{PREFIX}_target_mode", "persistent"),
            "confirmation_days": st.session_state.get(f"{PREFIX}_confirmation", 3),
            "min_dwell": st.session_state.get(f"{PREFIX}_min_dwell", 5),
            "winsor_z": st.session_state.get(f"{PREFIX}_reg_winsor", 5.0),
            "decoherence": st.session_state.get(f"{PREFIX}_reg_decoherence", 0.12),
            "coupling": st.session_state.get(f"{PREFIX}_reg_coupling", 0.35),
            "evolution_dt": st.session_state.get(f"{PREFIX}_reg_dt", 0.30),
            "transaction_cost_bps": st.session_state.get(f"{PREFIX}_tcost", 5.0),
            "economic_gamma": st.session_state.get(f"{PREFIX}_gamma", 5.0),
        },
        "QMC / RISK": {
            "product": st.session_state.get(f"{PREFIX}_qmc_product", "European"),
            "side": st.session_state.get(f"{PREFIX}_qmc_side", "Call"),
            "model": st.session_state.get(f"{PREFIX}_qmc_model", "GBM / Black-Scholes"),
            "method": st.session_state.get(f"{PREFIX}_qmc_method", "Control variate"),
            "paths": st.session_state.get(f"{PREFIX}_qmc_paths", 25000),
            "steps": st.session_state.get(f"{PREFIX}_qmc_steps", 64),
            "rqmc_scrambles": st.session_state.get(f"{PREFIX}_rqmc_scrambles", 16),
            "qae_algorithm": st.session_state.get(f"{PREFIX}_qae_algo", "Iterative QAE"),
            "qae_epsilon": st.session_state.get(f"{PREFIX}_qae_eps", 0.002),
        },
        "QUBO / ISING": {
            "cardinality": st.session_state.get(f"{PREFIX}_k_v241", 3),
            "risk_aversion": st.session_state.get(f"{PREFIX}_lambda_v241", 5.0),
            "penalty": st.session_state.get(f"{PREFIX}_penalty_v241", 12.0),
            "transaction_cost_bps": st.session_state.get(f"{PREFIX}_tcost_v241", 5.0),
            "turnover_penalty": st.session_state.get(f"{PREFIX}_turn_pen_v241", 0.10),
            "required": st.session_state.get(f"{PREFIX}_req_v241", []),
            "excluded": st.session_state.get(f"{PREFIX}_exc_v241", []),
            "qaoa_depth": st.session_state.get(f"{PREFIX}_qaoa_depth_v241", 3),
            "qaoa_trials": st.session_state.get(f"{PREFIX}_qaoa_trials_v241", 32),
            "qaoa_starts": st.session_state.get(f"{PREFIX}_qaoa_starts_v241", 3),
        },
        "QUANTUM INFORMATION / TT": {
            "density_window": st.session_state.get(f"{PREFIX}_qi_win_v251", 63),
            "rolling_step": st.session_state.get(f"{PREFIX}_qi_step_v251", 5),
            "pair_lookback": st.session_state.get(f"{PREFIX}_qi_pair_v251", 252),
            "tensor_block_size": st.session_state.get(f"{PREFIX}_qi_block_v251", 20),
            "tt_max_rank": st.session_state.get(f"{PREFIX}_qi_rank_v251", 8),
            "tt_retained_energy": st.session_state.get(f"{PREFIX}_qi_energy_v251", 0.995),
            "pair_permutations": st.session_state.get(f"{PREFIX}_qi_pair_perm_v251", 99),
            "tensor_temporal_shuffles": st.session_state.get(f"{PREFIX}_qi_tt_null_v251", 99),
        },
    }
    provenance = build_evidence_provenance(regime_result, event_returns, config_payloads=config_payloads)
    registry = frozen_evidence_registry(provenance)

    live_reg = live_regime_evidence(regime_result)
    live_label = live_reg.get("validation", "UNAVAILABLE") if live_reg.get("available") else "UNAVAILABLE"
    live_note = ""
    if live_reg.get("available"):
        pval = float(live_reg.get("matched_p", np.nan))
        delta = float(live_reg.get("matched_delta_logloss", np.nan))
        delta_txt = f"{delta:+.4f}" if np.isfinite(delta) else "N/A"
        p_txt = f"{pval:.3f}" if np.isfinite(pval) else "N/A"
        eff = float(live_reg.get("effective_n", np.nan))
        eff_txt = f"{eff:.0f}" if np.isfinite(eff) else "N/A"
        live_note = f"live frozen-spec run · ΔLL={delta_txt} · p={p_txt} · N_eff={eff_txt}/{live_reg.get('nominal_n', 0)}"

    st.markdown(
        f'''<div class="qev-hero"><div class="qev-kicker">QUANTUM RESEARCH GOVERNANCE LAYER</div><div class="qev-title">Evidence before claims.</div><div class="qev-sub">The four research engines remain frozen. This layer does not optimize them; it records what each engine has actually demonstrated, what it has not demonstrated, and which experiment is allowed next.</div></div>
        <div class="qev-ledger">
          <div class="qev-ledger-card"><div class="qev-ledger-k">FROZEN ENGINES</div><div class="qev-ledger-v">4 / 4</div><div class="qev-ledger-n">Regime · QMC · QUBO · Tensor</div></div>
          <div class="qev-ledger-card"><div class="qev-ledger-k">MAX WITHIN-ENGINE VALIDATED TIER</div><div class="qev-ledger-v">L3 · TENSOR NULL</div><div class="qev-ledger-n">non-comparable across tasks · downstream OOS not established</div></div>
          <div class="qev-ledger-card"><div class="qev-ledger-k">HARDWARE-ELIGIBLE CLAIMS</div><div class="qev-ledger-v">0</div><div class="qev-ledger-n">no measured QPU advantage</div></div>
          <div class="qev-ledger-card"><div class="qev-ledger-k">LIVE REGIME AUDIT</div><div class="qev-ledger-v">{escape(str(live_label))}</div><div class="qev-ledger-n">{escape(live_note or 'frozen-spec audit unavailable')}</div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    reg_main = str(live_label) if live_reg.get("available") else "L2 · FROZEN BASELINE"
    reg_note = live_note or "Matched classical improvement observed in the frozen validation study; dependency-robust OOS superiority was not established."
    engine_cards = [
        ("REGIME / DENSITY · V2.2.1", reg_main, reg_note, "ECONOMIC EDGE · NO"),
        ("QMC / RISK · V2.3.2", "NO MODELLED CROSSOVER", "QAE query complexity is asymptotically favorable, but total-error floor, state preparation / FT and latency dominate the current engineering frontier.", "QPU CLAIM · NOT ELIGIBLE"),
        ("QUBO / ISING · V2.4.1", "SIMULATOR ALGORITHMIC RESULT", "Dicke+XY preserves exact cardinality and improves statevector feasibility/optimum concentration versus penalty X-mixer, while classical MILP controls remain too easy.", "ADVANTAGE · NOT ELIGIBLE"),
        ("QUANTUM INFORMATION / TT · V2.5.1", "L3 · SURVIVES TEMPORAL NULL", "Frozen validation: temporal-null p=0.010 with partial rank/block robustness (~51%); downstream out-of-sample structural value remains unproven.", "PHYSICAL CLAIM · NONE"),
    ]
    html = '<div class="qev-engine-grid">'
    for name, main, note, tag in engine_cards:
        html += f'<div class="qev-engine"><div class="qev-engine-name">{escape(name)}</div><div class="qev-engine-main">{escape(main)}</div><div class="qev-engine-note">{escape(note)}</div><span class="qev-tag">{escape(tag)}</span></div>'
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)

    _section_header(
        "Cross-Engine Evidence Ladder",
        "DESCRIPTIVE → STATISTICAL → OOS → PRACTICAL → HARDWARE",
        "The ladder is intentionally non-additive: evidence from heterogeneous tasks is not collapsed into one synthetic 'quantum score'. A validated cell means the relevant standard was cleared within that engine's task, not that engines are directly comparable.",
    )
    ladder_labels, ladder_num = evidence_ladder()
    a, b = st.columns([1.05, 1.25])
    with a:
        st.dataframe(ladder_labels.reset_index(), width="stretch", hide_index=True)
    with b:
        fig = go.Figure(go.Heatmap(
            z=ladder_num.to_numpy(dtype=float), x=list(ladder_num.columns), y=list(ladder_num.index), zmin=0, zmax=3,
            colorbar=dict(title="evidence", tickvals=[0, 1, 2, 3], ticktext=["not established", "tested", "observed", "robust"]),
            text=ladder_labels.to_numpy(dtype=str), texttemplate="%{text}", hovertemplate="%{y}<br>%{x}<br>%{text}<extra></extra>",
        ))
        fig.update_layout(template="plotly_dark", height=360, title="Evidence state · no aggregate score", xaxis_title="", yaxis_title="")
        st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_evidence_ladder_v261")

    _section_header(
        "Cross-Engine Structural Synchronization",
        "EVENT CONFLUENCE · COVERAGE-AWARE · NON-CAUSAL",
        "Independent diagnostics are aligned only to identify dates of simultaneous structural stress. Composite rankings are comparable only within the same coverage class; missing engines are never treated as equivalent evidence.",
    )
    events = build_cross_engine_event_monitor(
        regime_result, event_returns,
        density_window=int(st.session_state.get(f"{PREFIX}_qi_win_v251", 63)),
        density_step=int(st.session_state.get(f"{PREFIX}_qi_step_v251", 5)),
        tt_block_size=int(st.session_state.get(f"{PREFIX}_qi_block_v251", 20)),
        tt_max_rank=int(st.session_state.get(f"{PREFIX}_qi_rank_v251", 8)),
        tt_energy=float(st.session_state.get(f"{PREFIX}_qi_energy_v251", 0.995)),
    )
    if events.get("available"):
        full_evt = events.get("events_full", pd.DataFrame()).copy()
        partial_evt = events.get("events_partial", pd.DataFrame()).copy()
        st.markdown(
            f'<div class="qev-coverage"><span class="qev-pill full">FULL COVERAGE · {len(full_evt)} ranked events</span><span class="qev-pill partial">PARTIAL HISTORY · {len(partial_evt)} events · separate ranking</span></div>',
            unsafe_allow_html=True,
        )
        if not full_evt.empty:
            evt = full_evt.copy()
            evt["Date"] = pd.to_datetime(evt["Date"]).dt.strftime("%Y-%m-%d")
            ev1, ev2 = st.columns([1.25, 1.0])
            with ev1:
                plot = evt.sort_values("Date")
                fig = go.Figure()
                for col, name in [("Regime pctl", "Regime shift"), ("Density pctl", "Density shift"), ("Volatility pctl", "Volatility"), ("TT pctl", "TT drift")]:
                    fig.add_trace(go.Scatter(x=plot["Date"], y=plot[col], mode="lines+markers", name=name))
                fig.add_hline(y=90, line_dash="dash", annotation_text="90th percentile confluence threshold")
                fig.update_layout(template="plotly_dark", height=420, title="Full-coverage synchronized structural events · 4/4 channels", yaxis_title="Within-channel percentile", yaxis_range=[0, 105])
                st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_cross_engine_events_v261")
            with ev2:
                heat = evt.sort_values("Composite", ascending=False).head(10).set_index("Date")[["Regime pctl", "Density pctl", "Volatility pctl", "TT pctl"]]
                fig = go.Figure(go.Heatmap(z=heat.to_numpy(float), x=list(heat.columns), y=list(heat.index), zmin=0, zmax=100, colorbar=dict(title="percentile"), text=np.round(heat.to_numpy(float), 0), texttemplate="%{text:.0f}"))
                fig.update_layout(template="plotly_dark", height=420, title="Full-coverage confluence matrix")
                st.plotly_chart(fig, width="stretch", key=f"{PREFIX}_cross_engine_heat_v261")
            show = evt[["Date", "Composite", "Confluence ≥90p", "Available Channels", "Coverage %", "Strongest channel", "Regime pctl", "Density pctl", "Volatility pctl", "TT pctl"]].copy()
            st.dataframe(show.style.format({"Composite":"{:.1f}", "Coverage %":"{:.0f}%", "Regime pctl":"{:.0f}", "Density pctl":"{:.0f}", "Volatility pctl":"{:.0f}", "TT pctl":"{:.0f}"}), width="stretch", hide_index=True)
        else:
            st.info("No 4/4 full-coverage structural event is available in the aligned history yet. Partial-history events are shown separately and are not ranked against future full-coverage events.")

        if not partial_evt.empty:
            st.markdown("#### Partial-history events · separate coverage class")
            partial_show = partial_evt.copy()
            partial_show["Date"] = pd.to_datetime(partial_show["Date"]).dt.strftime("%Y-%m-%d")
            partial_show = partial_show[["Date", "Composite", "Confluence ≥90p", "Available Channels", "Coverage %", "Strongest channel", "Regime pctl", "Density pctl", "Volatility pctl", "TT pctl"]]
            st.dataframe(partial_show.style.format({"Composite":"{:.1f}", "Coverage %":"{:.0f}%", "Regime pctl":"{:.0f}", "Density pctl":"{:.0f}", "Volatility pctl":"{:.0f}", "TT pctl":"{:.0f}"}, na_rep="—"), width="stretch", hide_index=True)
            st.caption("Partial-history composites are comparable only with other events having the same channel coverage. They are excluded from the 4/4 leaderboard above.")
        st.markdown('<div class="qrl-warning"><b>Interpretation boundary:</b> event confluence means multiple frozen diagnostics moved unusually around the same date. It does not establish common causality, predict future returns or combine the engines into a trading signal.</div>', unsafe_allow_html=True)
    else:
        st.info(events.get("reason", "Cross-engine event monitor unavailable."))

    _section_header(
        "Claim Ledger & Promotion Gates",
        "ALLOWED WORDING · PROHIBITED WORDING · NEXT TEST",
        "Every frozen result has an explicit claim boundary. Promotion requires a new experiment at the next evidence tier; changing parameters on the frozen validation sample is not a valid promotion path.",
    )
    claims = claim_governance()
    claim_html = '<div class="qev-claim-grid">'
    for _, row in claims.iterrows():
        claim_html += (
            f'<div class="qev-claim"><h4>{escape(str(row["Engine"]))}</h4>'
            f'<div class="qev-claim-row"><b>ALLOWED</b><br>{escape(str(row["Allowed Wording"]))}</div>'
            f'<div class="qev-claim-row"><b>PROHIBITED</b><br>{escape(str(row["Prohibited Wording"]))}</div>'
            f'<div class="qev-claim-row"><b>NEXT PERMITTED TEST</b><br>{escape(str(row["Promotion Requirement"]))}</div></div>'
        )
    claim_html += '</div>'
    st.markdown(claim_html, unsafe_allow_html=True)
    st.dataframe(promotion_rules(), width="stretch", hide_index=True)

    _section_header(
        "Evidence Provenance Matrix",
        "CODE HASH · CONFIG HASH · DATA CUTOFF · SNAPSHOT ID",
        "A frozen claim is tied to a deterministic source fingerprint, configuration fingerprint and visible data scope. Scenario-only QMC evidence is marked explicitly rather than assigned an artificial market cutoff.",
    )
    st.dataframe(provenance, width="stretch", hide_index=True)

    _section_header(
        "Frozen Research Registry",
        "VERSION CONTROL · RESEARCH DEBT",
        "The compact registry documents what is frozen and the evidence snapshot attached to it. Strongest controls and promotion requirements are documented in the claim cards above.",
    )
    registry_cols = ["Engine", "Frozen Version", "Research State", "Highest Evidence", "Code SHA", "Config SHA", "Data Through", "Evidence Snapshot ID"]
    st.dataframe(registry[[c for c in registry_cols if c in registry.columns]], width="stretch", hide_index=True)

    protocol = pd.DataFrame([
        ("Data", "Point-in-time universe, no look-ahead, aligned timestamps, documented provider/fallback"),
        ("Validation", "Walk-forward / purged CV, dependency-aware uncertainty, permutation/null controls and multiple-testing control where relevant"),
        ("Classical baseline", "Analytic / exact / MILP / strong heuristic / SVD-Tucker controls depending on task"),
        ("Quantum-inspired", "Density / QUBO / Tensor representation is separated from actual QPU execution"),
        ("Quantum simulator", "Circuit/statevector outputs are explicitly simulator-only; feasibility, shots and parameter stability are reported"),
        ("Quantum hardware", "Backend, compilation, physical resources, errors, mitigation, queue/runtime and repeatability must be measured"),
        ("Economic / compute value", "Net utility or end-to-end runtime must beat a credible optimized control under equal objectives"),
        ("Advantage claim", "Reserved until a measured hardware workflow beats the relevant classical workflow end-to-end"),
    ], columns=["Control Layer", "Minimum Standard"])
    st.dataframe(protocol, width="stretch", hide_index=True)
    st.markdown('<div class="qrl-warning"><b>Lab policy:</b> “quantum advantage”, “physical entanglement”, and “quantum alpha” remain reserved claims. Simulator concentration, asymptotic complexity, null-test survival, or visually distinctive representations are not sufficient.</div>', unsafe_allow_html=True)


def _phase2_program(
    regime_result: dict[str, Any] | None,
    regime_frame: pd.DataFrame | None,
    portfolio_returns: pd.DataFrame | None,
) -> None:
    _section_header(
        "Phase II · Pre-Registered OOS Experiment Program",
        "FROZEN LAB → NEW EVIDENCE",
        "The V2.6.1 laboratory remains frozen. Phase II seals the next admissible experiments before new outcomes are observed; waiting or blocked protocols do not generate synthetic results.",
    )

    st.markdown(
        '''<style>
        .qph2-hero{position:relative;overflow:hidden;border:1px solid rgba(73,225,255,.22);border-radius:20px;padding:20px 22px;margin:4px 0 18px;background:linear-gradient(120deg,rgba(3,24,39,.97),rgba(9,14,34,.97) 50%,rgba(30,12,52,.93));box-shadow:0 0 44px rgba(35,206,255,.07)}
        .qph2-hero:after{content:"";position:absolute;top:0;left:-35%;width:28%;height:100%;background:linear-gradient(90deg,transparent,rgba(91,232,255,.08),transparent);animation:qph2Scan 10s linear infinite}@keyframes qph2Scan{0%{left:-35%}100%{left:112%}}
        .qph2-k{font-size:.65rem;letter-spacing:.20em;color:#61e9ff;font-weight:850}.qph2-t{font-size:1.35rem;font-weight:850;color:#f5f8ff;margin:7px 0}.qph2-s{font-size:.82rem;color:#98a9bf;max-width:1120px;line-height:1.5}
        .qph2-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0 20px}.qph2-card{border:1px solid rgba(88,218,255,.17);border-radius:15px;background:rgba(4,16,29,.76);padding:13px}.qph2-card-k{font-size:.57rem;letter-spacing:.15em;color:#7489a4;font-weight:800}.qph2-card-v{font-size:1.00rem;color:#f5f8ff;font-weight:850;margin-top:5px}.qph2-card-n{font-size:.67rem;color:#8fa1b7;margin-top:4px;line-height:1.4}
        .qph2-protocol{position:relative;border:1px solid rgba(84,217,255,.17);border-radius:18px;padding:16px 17px;margin:11px 0;background:linear-gradient(135deg,rgba(4,20,34,.84),rgba(15,11,36,.80));overflow:hidden}.qph2-protocol:before{content:"";position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(90deg,#4aeaff,#7b6cff,#ff5a7b);opacity:.7}.qph2-pname{font-size:.65rem;letter-spacing:.14em;color:#68eaff;font-weight:850}.qph2-ptitle{font-size:1.02rem;color:#f4f7ff;font-weight:850;margin:6px 0}.qph2-row{font-size:.73rem;color:#9bacbf;line-height:1.48;margin:6px 0}.qph2-row b{color:#edf4ff}.qph2-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#a9f2ff;font-size:.70rem}
        .qph2-lock{border:1px solid rgba(255,202,88,.25);background:rgba(54,38,8,.20);border-radius:14px;padding:11px 13px;color:#d7c28c;font-size:.72rem;margin:12px 0}.qph2-ok{color:#82efc4}.qph2-wait{color:#ffd18a}.qph2-block{color:#ff9bad}
        @media(max-width:900px){.qph2-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.qph2-grid{grid-template-columns:1fr}}
        </style>''',
        unsafe_allow_html=True,
    )

    event_returns = portfolio_returns
    if not isinstance(event_returns, pd.DataFrame) or event_returns.empty:
        event_returns, _ = _load_returns_cached(("SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"))

    config_payloads = {
        "REGIME / DENSITY": {
            "horizon": st.session_state.get(f"{PREFIX}_reg_horizon", 5),
            "train_fraction": st.session_state.get(f"{PREFIX}_reg_train", 0.65),
            "retrain_every": st.session_state.get(f"{PREFIX}_reg_refit", 63),
            "scaler": st.session_state.get(f"{PREFIX}_reg_scaler", "standard"),
            "target_mode": st.session_state.get(f"{PREFIX}_target_mode", "persistent"),
            "confirmation_days": st.session_state.get(f"{PREFIX}_confirmation", 3),
            "min_dwell": st.session_state.get(f"{PREFIX}_min_dwell", 5),
            "winsor_z": st.session_state.get(f"{PREFIX}_reg_winsor", 5.0),
            "decoherence": st.session_state.get(f"{PREFIX}_reg_decoherence", 0.12),
            "coupling": st.session_state.get(f"{PREFIX}_reg_coupling", 0.35),
            "evolution_dt": st.session_state.get(f"{PREFIX}_reg_dt", 0.30),
            "transaction_cost_bps": st.session_state.get(f"{PREFIX}_tcost", 5.0),
            "economic_gamma": st.session_state.get(f"{PREFIX}_gamma", 5.0),
        },
        "QMC / RISK": {
            "product": st.session_state.get(f"{PREFIX}_qmc_product", "European"),
            "side": st.session_state.get(f"{PREFIX}_qmc_side", "Call"),
            "model": st.session_state.get(f"{PREFIX}_qmc_model", "GBM / Black-Scholes"),
            "method": st.session_state.get(f"{PREFIX}_qmc_method", "Control variate"),
            "paths": st.session_state.get(f"{PREFIX}_qmc_paths", 25000),
            "steps": st.session_state.get(f"{PREFIX}_qmc_steps", 64),
            "rqmc_scrambles": st.session_state.get(f"{PREFIX}_rqmc_scrambles", 16),
            "qae_algorithm": st.session_state.get(f"{PREFIX}_qae_algo", "Iterative QAE"),
            "qae_epsilon": st.session_state.get(f"{PREFIX}_qae_eps", 0.002),
        },
        "QUBO / ISING": {
            "cardinality": st.session_state.get(f"{PREFIX}_k_v241", 3),
            "risk_aversion": st.session_state.get(f"{PREFIX}_lambda_v241", 5.0),
            "penalty": st.session_state.get(f"{PREFIX}_penalty_v241", 12.0),
            "transaction_cost_bps": st.session_state.get(f"{PREFIX}_tcost_v241", 5.0),
            "turnover_penalty": st.session_state.get(f"{PREFIX}_turn_pen_v241", 0.10),
            "required": st.session_state.get(f"{PREFIX}_req_v241", []),
            "excluded": st.session_state.get(f"{PREFIX}_exc_v241", []),
            "qaoa_depth": st.session_state.get(f"{PREFIX}_qaoa_depth_v241", 3),
            "qaoa_trials": st.session_state.get(f"{PREFIX}_qaoa_trials_v241", 32),
            "qaoa_starts": st.session_state.get(f"{PREFIX}_qaoa_starts_v241", 3),
        },
        "QUANTUM INFORMATION / TT": {
            "density_window": st.session_state.get(f"{PREFIX}_qi_win_v251", 63),
            "rolling_step": st.session_state.get(f"{PREFIX}_qi_step_v251", 5),
            "pair_lookback": st.session_state.get(f"{PREFIX}_qi_pair_v251", 252),
            "tensor_block_size": st.session_state.get(f"{PREFIX}_qi_block_v251", 20),
            "tt_max_rank": st.session_state.get(f"{PREFIX}_qi_rank_v251", 8),
            "tt_retained_energy": st.session_state.get(f"{PREFIX}_qi_energy_v251", 0.995),
            "pair_permutations": st.session_state.get(f"{PREFIX}_qi_pair_perm_v251", 99),
            "tensor_temporal_shuffles": st.session_state.get(f"{PREFIX}_qi_tt_null_v251", 99),
        },
    }
    provenance = build_evidence_provenance(regime_result, event_returns, config_payloads=config_payloads)
    registry = build_phase2_registry(provenance)
    readiness = phase2_readiness(provenance, regime_frame, event_returns)
    manifest = phase2_manifest(provenance)
    manifest_sha = str(manifest.get("manifest_sha", "N/A"))
    source_match_count = int(registry["Source Match"].sum()) if "Source Match" in registry else 0
    execution_ready = (int(readiness["Promotion Eligible"].sum()) if "Promotion Eligible" in readiness else 0) if source_match_count == 4 else 0

    st.markdown(
        f'''<div class="qph2-hero"><div class="qph2-k">{escape(PHASE_II_VERSION)}</div><div class="qph2-t">New evidence, not new tuning.</div><div class="qph2-s">Four next-step protocols are sealed against the V2.6.1 evidence snapshots. A protocol may be waiting for genuinely new observations, armed for an explicit classical-hardness run, or blocked until a real QPU environment exists. Unfavorable outcomes are part of the record.</div></div>
        <div class="qph2-grid">
          <div class="qph2-card"><div class="qph2-card-k">SEALED PROTOCOLS</div><div class="qph2-card-v">4 / 4</div><div class="qph2-card-n">Regime · Tensor · QUBO · QMC</div></div>
          <div class="qph2-card"><div class="qph2-card-k">SOURCE SNAPSHOTS MATCH</div><div class="qph2-card-v">{source_match_count} / 4</div><div class="qph2-card-n">must remain 4/4 before execution</div></div>
          <div class="qph2-card"><div class="qph2-card-k">EXECUTION-READY NOW</div><div class="qph2-card-v">{execution_ready}</div><div class="qph2-card-n">eligible to run the sealed test · not yet promoted</div></div>
          <div class="qph2-card"><div class="qph2-card-k">MANIFEST SHA</div><div class="qph2-card-v qph2-sha">{escape(manifest_sha)}</div><div class="qph2-card-n">preregistered {escape(PREREGISTRATION_DATE)}</div></div>
        </div>''',
        unsafe_allow_html=True,
    )

    if source_match_count != 4:
        st.error("Phase-II execution lock: frozen code/config provenance differs from the sealed V2.6.1 parent. New post-cutoff observations are allowed; restore only the frozen code/config if they changed.")
    else:
        st.markdown('<div class="qph2-lock"><b>PRE-REGISTRATION LOCK · ACTIVE.</b> Frozen code/config fingerprints match the sealed parent snapshots. New post-cutoff observations are expected and do not invalidate Phase-II execution.</div>', unsafe_allow_html=True)

    _section_header(
        "Experiment Queue & Unlock Conditions",
        "WAITING · ARMED · BLOCKED",
        "Readiness is mechanical. New-market experiments remain locked until enough post-cutoff observations exist; hardware experiments remain blocked until a real authenticated backend is available.",
    )
    st.dataframe(readiness.rename(columns={"Promotion Eligible": "Confirmatory Run Eligible"}), width="stretch", hide_index=True)

    # ---- Phase-II QUBO confirmatory execution console (V2.8.1) ----
    _section_header(
        "QUBO Hardness Confirmatory Execution",
        "SEALED 120-INSTANCE RUN · CHECKPOINTED",
        "The preregistration thresholds remain unchanged. V2.8.1 preserves the sealed 120-instance execution and fixes parent-snapshot locking so genuinely new post-cutoff market data cannot invalidate an existing confirmatory run.",
    )
    qspec = qhardness_execution_spec()
    qplan = qhardness_planned_instances()
    qrun = qhardness_run_status()
    qstatus = str(qrun.get("status", "NOT INITIALIZED"))
    qsummary = qrun.get("summary") or {}
    qcompleted = int(qsummary.get("completed", 0) or 0)
    qexpected = int(qsummary.get("expected", len(qplan)) or len(qplan))
    qintegrity = bool(qrun.get("integrity_ok", True)) if qrun.get("exists") else True
    qoutcome = str(qsummary.get("outcome", "NOT RUN"))
    st.markdown(
        f'''<div class="qph2-grid">
          <div class="qph2-card"><div class="qph2-card-k">PROTOCOL SHA</div><div class="qph2-card-v qph2-sha">{escape(QUBO_PHASE2_PROTOCOL_SHA)}</div><div class="qph2-card-n">unchanged V2.7.1 promotion gate</div></div>
          <div class="qph2-card"><div class="qph2-card-k">EXECUTION SPEC SHA</div><div class="qph2-card-v qph2-sha">{escape(EXECUTION_SPEC_SHA)}</div><div class="qph2-card-n">generator + fixed solver budgets</div></div>
          <div class="qph2-card"><div class="qph2-card-k">RUN STATUS</div><div class="qph2-card-v">{escape(qstatus)}</div><div class="qph2-card-n">{qcompleted}/{qexpected} canonical instances recorded</div></div>
          <div class="qph2-card"><div class="qph2-card-k">CURRENT OUTCOME</div><div class="qph2-card-v">{escape(qoutcome)}</div><div class="qph2-card-n">gate is final only after 120/120</div></div>
        </div>''',
        unsafe_allow_html=True,
    )
    st.progress(min(max(qcompleted / max(qexpected, 1), 0.0), 1.0), text=f"QUBO Phase-II confirmatory progress · {qcompleted}/{qexpected}")
    spec_cols = st.columns([1, 1, 1])
    with spec_cols[0]:
        st.metric("MILP hard limit", f"{float(qspec['solver_budgets']['milp_time_limit_seconds']):.0f}s / instance")
    with spec_cols[1]:
        st.metric("Canonical families", "15", help="5 sizes × 3 constraint regimes; each family contains the 8 sealed seeds.")
    with spec_cols[2]:
        st.metric("Checkpoint policy", "EVERY INSTANCE")
    st.caption("The worker may require substantial wall-clock time if several MILP instances approach the sealed 75-second budget. Operational pauses are allowed; instance order, solver budgets, seeds and completed rows are not editable.")

    qspec_json = json.dumps(qspec, indent=2, sort_keys=True, default=str)
    st.download_button(
        "Download sealed QUBO execution specification",
        data=qspec_json.encode("utf-8"),
        file_name="QUBO_PHASEII_EXECUTION_SPEC_V1.json",
        mime="application/json",
        key=f"{PREFIX}_qhard_spec_download",
    )

    if source_match_count != 4:
        st.error("QUBO confirmatory execution is locked because frozen code/config provenance no longer matches the sealed Phase-II parent. Live post-cutoff data alone does not trigger this lock.")
    elif not qrun.get("exists"):
        st.markdown('<div class="qph2-lock"><b>EXECUTION SPEC · SEALED, NOT STARTED.</b> Initializing creates an immutable run manifest and environment fingerprint. No canonical result has been observed yet.</div>', unsafe_allow_html=True)
        if st.button("Initialize sealed QUBO Phase-II run", type="primary", key=f"{PREFIX}_qhard_init"):
            qhardness_initialize_run()
            st.rerun()
    else:
        if not qintegrity:
            st.error(f"QUBO execution integrity lock: {qrun.get('integrity_reason', 'unknown mismatch')}")
        else:
            worker = qrun.get("worker") or {}
            worker_status = str(worker.get("status", "IDLE"))
            worker_pid = worker.get("pid", "N/A")
            st.markdown(f'<div class="qph2-lock"><b>RUN ID</b> <span class="qph2-sha">{escape(str(qrun.get("run_id", "N/A")))}</span> · <b>WORKER</b> {escape(worker_status)} · PID {escape(str(worker_pid))}<br><b>OUTPUT</b> <span class="qph2-sha">{escape(str(qrun.get("run_dir", qhardness_results_root())))}</span></div>', unsafe_allow_html=True)
            finalized = qrun.get("finalized")
            if not finalized and worker_status != "RUNNING":
                if st.button("Launch / resume sealed 120-instance worker", type="primary", key=f"{PREFIX}_qhard_launch"):
                    launch = qhardness_launch_worker(str(qrun.get("run_dir")))
                    if launch.get("launched"):
                        st.success(f"Worker launched · PID {launch.get('pid')}. Refresh this tab to monitor checkpoints.")
                    else:
                        st.warning(str(launch.get("reason", "worker was not launched")))
                    st.rerun()
            elif worker_status == "RUNNING":
                st.info("Confirmatory worker is running. Results are checkpointed after every canonical instance; refresh/rerun the page to update progress.")

            results = qrun.get("results")
            if isinstance(results, pd.DataFrame) and not results.empty:
                cols = [c for c in ["instance_id", "N", "regime", "seed", "execution_status", "milp_runtime_s", "milp_optimality_certified", "best_heuristic_gap_pct"] if c in results.columns]
                st.dataframe(results[cols].tail(12), width="stretch", hide_index=True)
            fam = qsummary.get("family_summary")
            if isinstance(fam, pd.DataFrame) and not fam.empty:
                st.markdown("**Current family diagnostics · non-final until 120/120**")
                st.dataframe(fam, width="stretch", hide_index=True)
            if qrun.get("finalized"):
                final_outcome = str(qrun["finalized"].get("outcome", qoutcome))
                if final_outcome == "HARDNESS GATE · PASSED":
                    st.success("HARDNESS GATE · PASSED — the preregistered equal-objective QPU design gate may open. This is not a quantum-advantage result.")
                elif final_outcome == "HARDNESS GATE · FAILED":
                    st.warning("HARDNESS GATE · FAILED — classical controls remain too strong under the sealed suite; QPU comparison remains NOT ELIGIBLE.")
                else:
                    st.error("INDETERMINATE — one or more canonical instances did not produce a valid confirmatory record. No promotion is permitted.")
                bundle = qhardness_artifact_zip_bytes(str(qrun.get("run_dir")))
                if bundle:
                    st.download_button(
                        "Download immutable QUBO Phase-II execution artifact",
                        data=bundle,
                        file_name=f"{qrun.get('run_id','QUBO_PHASEII_RESULTS')}.zip",
                        mime="application/zip",
                        key=f"{PREFIX}_qhard_artifact_download",
                    )

    phase_status = dict(zip(readiness["Protocol"], readiness["Status"]))
    for spec in PROTOCOLS:
        row = registry.loc[registry["Protocol"] == spec.key].iloc[0]
        status = phase_status.get(spec.key, "UNKNOWN")
        status_class = "qph2-ok" if status.startswith("READY") or status.startswith("ARMED") else ("qph2-block" if status.startswith("BLOCKED") else "qph2-wait")
        secondary = " · ".join(spec.secondary_endpoints)
        forbidden = " · ".join(spec.forbidden_changes)
        notes = " · ".join(spec.execution_notes)
        st.markdown(
            f'''<div class="qph2-protocol">
              <div class="qph2-pname">{escape(spec.key)} · <span class="{status_class}">{escape(status)}</span></div>
              <div class="qph2-ptitle">{escape(spec.title)}</div>
              <div class="qph2-row"><b>SCIENTIFIC QUESTION</b><br>{escape(spec.scientific_question)}</div>
              <div class="qph2-row"><b>UNLOCK</b><br>{escape(spec.unlock_condition)}</div>
              <div class="qph2-row"><b>PRIMARY ENDPOINT</b><br>{escape(spec.primary_endpoint)}</div>
              <div class="qph2-row"><b>CONTROL</b><br>{escape(spec.primary_control)}</div>
              <div class="qph2-row"><b>INFERENCE</b><br>{escape(spec.inference_rule)}</div>
              <div class="qph2-row"><b>SUCCESS GATE</b><br>{escape(spec.success_rule)}</div>
              <div class="qph2-row"><b>FAILURE / NO-PROMOTION RULE</b><br>{escape(spec.failure_rule)}</div>
              <div class="qph2-row"><b>SECONDARY ENDPOINTS</b><br>{escape(secondary)}</div>
              <div class="qph2-row"><b>FORBIDDEN AFTER PREREGISTRATION</b><br>{escape(forbidden)}</div>
              <div class="qph2-row"><b>EXECUTION NOTES</b><br>{escape(notes)}</div>
              <div class="qph2-row"><b>SOURCE EVIDENCE</b> <span class="qph2-sha">{escape(str(row['Source Evidence']))}</span><br><b>PROTOCOL SHA</b> <span class="qph2-sha">{escape(str(row['Protocol SHA']))}</span></div>
            </div>''',
            unsafe_allow_html=True,
        )

    _section_header(
        "Sealed Instance & Hardware Contracts",
        "DETERMINISTIC INPUTS",
        "The only Phase-II protocols that do not wait for new market observations still have fixed inputs before execution: the QUBO hardness family and the canonical QMC hardware scenario.",
    )
    c1, c2 = st.columns(2)
    with c1:
        qtab = pd.DataFrame([
            ("Sizes N", ", ".join(map(str, QUBO_SUITE["sizes"]))),
            ("Constraint regimes", ", ".join(QUBO_SUITE["constraint_regimes"])),
            ("Seeds", ", ".join(map(str, QUBO_SUITE["seeds"]))),
            ("Instance count", len(QUBO_SUITE["sizes"]) * len(QUBO_SUITE["constraint_regimes"]) * len(QUBO_SUITE["seeds"])),
            ("MILP median gate", f'{QUBO_SUITE["milp_median_gate_seconds"]:.0f}s'),
            ("MILP p95 gate", f'{QUBO_SUITE["milp_p95_gate_seconds"]:.0f}s'),
            ("Heuristic gap gate", f'{100*QUBO_SUITE["heuristic_gap_gate"]:.2f}%'),
        ], columns=["QUBO hard-suite contract", "Sealed value"])
        qtab["Sealed value"] = qtab["Sealed value"].map(str)
        st.dataframe(qtab, width="stretch", hide_index=True)
    with c2:
        qmc_tab = pd.DataFrame([(k.replace("_", " ").title(), v) for k, v in QMC_CANONICAL.items()], columns=["QMC hardware contract", "Sealed value"])
        qmc_tab["Sealed value"] = qmc_tab["Sealed value"].map(str)
        st.dataframe(qmc_tab, width="stretch", hide_index=True)

    _section_header(
        "Outcome Discipline",
        "SUCCESS · FAILURE · INDETERMINATE",
        "Phase II records negative and inconclusive outcomes. A failed promotion gate does not trigger a new parameter search on the same confirmatory sample.",
    )
    outcome_policy = pd.DataFrame([
        ("SUCCESS", "All preregistered primary-gate conditions pass.", "Promote only to the explicitly targeted evidence tier; preserve the original result snapshot."),
        ("FAILURE", "Primary endpoint or a required gate fails.", "Record failure. Frozen engine remains frozen. A redesigned experiment requires a new protocol ID and new untouched data/instances."),
        ("INDETERMINATE", "Sample, effective N, hardware repeats or execution integrity is insufficient.", "No promotion and no failure claim; continue collecting under the same sealed protocol when allowed."),
        ("PROTOCOL VIOLATION", "Source hash/config changes, seed deletion, control substitution or unregistered tuning occurs.", "Confirmatory result is invalid; generate a new preregistration before any further confirmatory run."),
    ], columns=["Outcome", "Definition", "Action"])
    st.dataframe(outcome_policy, width="stretch", hide_index=True)

    _section_header(
        "Pre-Registration Manifest",
        "IMMUTABLE PROTOCOL FINGERPRINT",
        "The manifest serializes all four protocol definitions and their sealed V2.6.1 evidence parents. It is intended to be archived before any Phase-II confirmatory result exists.",
    )
    manifest_json = json.dumps(manifest, indent=2, sort_keys=True, default=str)
    st.code(manifest_json[:12000] + ("\n..." if len(manifest_json) > 12000 else ""), language="json")
    st.download_button(
        "Download Phase-II preregistration manifest",
        data=manifest_json.encode("utf-8"),
        file_name="QUANTUM_LAB_PHASE_II_PREREGISTRATION_V1.json",
        mime="application/json",
        key=f"{PREFIX}_phase2_manifest_download",
    )
    st.markdown('<div class="qrl-warning"><b>Execution boundary:</b> this tab defines admissible future tests. It does not backfill post-cutoff observations, simulate QPU evidence, or convert exploratory interim results into confirmatory claims.</div>', unsafe_allow_html=True)

def _phase3_qpu_program() -> None:
    _section_header(
        "Phase III · Terminal Offline Admission, Evidence Governance & Zero-Job Control Room",
        "AUTHENTIC V4.8 PARENT → DISTINCT EPOCH GATE → EXACT RESOURCE GATE → PROVIDER DISCOVERY DECISION",
        "V4.9 authenticates the exact V4.8 architecture evidence, preserves the dated diagnostics and closes the offline V4 line with a fail-closed admission dossier. Only one of three required authentic epochs exists, the strict resource screens still fail, and provider discovery, V5 entry and execution remain blocked.",
    )
    st.markdown(
        '''<style>
        .qp3-hero{position:relative;overflow:hidden;border:1px solid rgba(75,229,255,.22);border-radius:20px;padding:20px 22px;margin:4px 0 18px;background:linear-gradient(120deg,rgba(2,23,38,.98),rgba(9,14,34,.97) 48%,rgba(34,12,55,.93));box-shadow:0 0 46px rgba(48,217,255,.07)}
        .qp3-hero:after{content:"";position:absolute;top:0;left:-32%;width:24%;height:100%;background:linear-gradient(90deg,transparent,rgba(95,236,255,.08),transparent);animation:qp3scan 11s linear infinite}@keyframes qp3scan{0%{left:-32%}100%{left:112%}}
        .qp3-k{font-size:.64rem;letter-spacing:.18em;color:#64eaff;font-weight:850}.qp3-t{font-size:1.32rem;color:#f6f8ff;font-weight:850;margin:7px 0}.qp3-s{font-size:.80rem;color:#9aabc0;line-height:1.5;max-width:1150px}
        .qp3-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:12px 0 19px}.qp3-card{border:1px solid rgba(83,218,255,.17);border-radius:15px;padding:13px;background:rgba(3,16,29,.78)}.qp3-ck{font-size:.56rem;letter-spacing:.14em;color:#788ca7;font-weight:800}.qp3-cv{font-size:1.00rem;color:#f4f7ff;font-weight:850;margin-top:5px}.qp3-cn{font-size:.67rem;color:#8fa2b8;margin-top:4px;line-height:1.4}.qp3-sha{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#aef3ff}
        .qp3-panel{position:relative;border:1px solid rgba(80,216,255,.17);border-radius:18px;padding:16px 17px;margin:12px 0;background:linear-gradient(135deg,rgba(4,19,33,.85),rgba(15,11,36,.80));overflow:hidden}.qp3-panel:before{content:"";position:absolute;left:0;top:0;width:100%;height:2px;background:linear-gradient(90deg,#4aeaff,#796dff,#ff5f82);opacity:.72}.qp3-pk{font-size:.61rem;letter-spacing:.15em;color:#68eaff;font-weight:850}.qp3-pt{font-size:1.02rem;color:#f4f7ff;font-weight:850;margin:6px 0}.qp3-note{font-size:.72rem;color:#98a9bd;line-height:1.48}.qp3-ok{color:#80efc1}.qp3-warn{color:#ffd18b}.qp3-block{color:#ff9bad}
        @media(max-width:900px){.qp3-grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.qp3-grid{grid-template-columns:1fr}}
        </style>''', unsafe_allow_html=True,
    )

    gate = qpu_phase2_gate()
    eligible = gate.get("eligible_families")
    if not isinstance(eligible, pd.DataFrame):
        eligible = pd.DataFrame()
    completed = int(((gate.get("status") or {}).get("summary") or {}).get("completed", 0) or 0)
    gate_state = str(gate.get("state", "WAITING"))
    gate_ready = bool(gate.get("ready", False))
    eligible_count = int(len(eligible))
    gate_compiler_artifact: dict[str, Any] | None = None
    gate_compiler_integrity = False
    algorithmic_artifact: dict[str, Any] | None = None
    algorithmic_integrity = False
    algorithmic_hardware_eligible = False
    optimized_native_artifact: dict[str, Any] | None = None
    optimized_native_integrity = False
    backend_admission_artifact: dict[str, Any] | None = None
    backend_admission_integrity = False
    v36_artifact: dict[str, Any] | None = None
    v36_integrity = False
    v37_artifact: dict[str, Any] | None = None
    v37_integrity = False
    v38_artifact: dict[str, Any] | None = None
    v38_integrity = False
    v39_artifact: dict[str, Any] | None = None
    v39_integrity = False
    v40_artifact: dict[str, Any] | None = None
    v40_integrity = False
    v41_artifact: dict[str, Any] | None = None
    v41_integrity = False
    v42_artifact: dict[str, Any] | None = None
    v42_integrity = False
    v43_artifact: dict[str, Any] | None = None
    v43_integrity = False
    v44_artifact: dict[str, Any] | None = None
    v44_integrity = False
    v45_artifact: dict[str, Any] | None = None
    v45_integrity = False
    v46_artifact: dict[str, Any] | None = None
    v46_integrity = False
    v47_artifact: dict[str, Any] | None = None
    v47_integrity = False
    v48_artifact: dict[str, Any] | None = None
    v48_integrity = False
    v49_artifact: dict[str, Any] | None = None
    v49_integrity = False
    v49_preflight_report: dict[str, Any] = {"valid": False, "errors": []}
    try:
        v49_artifact, v49_preflight_report = load_v49_ui_artifact()
    except Exception as exc:
        v49_preflight_report = {"valid": False, "errors": [str(exc)]}
    v49_preflight_valid = bool(
        v49_preflight_report.get("valid") is True
        and v49_preflight_report.get("check_count") == EXPECTED_V49_UI_AUTH_CHECK_COUNT
    )
    v48_preflight_report: dict[str, Any] = {"valid": False, "errors": []}
    try:
        v48_artifact, v48_preflight_report = load_v48_ui_artifact()
    except Exception as exc:
        v48_preflight_report = {"valid": False, "errors": [str(exc)]}
    v48_preflight_valid = bool(
        v48_preflight_report.get("valid") is True
        and v48_preflight_report.get("check_count") == EXPECTED_V48_UI_AUTH_CHECK_COUNT
    )
    v47_preflight_report: dict[str, Any] = {"valid": False, "errors": []}
    try:
        v47_artifact, v47_preflight_report = load_v47_ui_artifact()
    except Exception as exc:
        v47_preflight_report = {"valid": False, "errors": [str(exc)]}
    v47_preflight_valid = bool(
        v47_preflight_report.get("valid") is True
        and v47_preflight_report.get("check_count") == EXPECTED_V47_UI_AUTH_CHECK_COUNT
    )
    v46_preflight_report: dict[str, Any] = {"valid": False, "errors": []}
    try:
        v46_artifact, v46_preflight_report = load_v46_ui_artifact()
    except Exception as exc:
        v46_preflight_report = {"valid": False, "errors": [str(exc)]}
    v46_preflight_valid = bool(
        v46_preflight_report.get("valid") is True
        and v46_preflight_report.get("check_count") == 30
    )
    v45_preflight_report: dict[str, Any] = {"valid": False, "errors": []}
    try:
        v45_artifact, v45_preflight_report = load_v45_ui_artifact()
    except Exception as exc:
        v45_preflight_report = {"valid": False, "errors": [str(exc)]}
    v45_preflight_valid = bool(
        v45_preflight_report.get("valid") is True
        and v45_preflight_report.get("check_count") == 28
    )
    if v49_preflight_valid:
        v45_hero_kicker = "V4.9 · TERMINAL OFFLINE ADMISSION · AUTHENTICATED RESEARCH_ONLY"
        v45_hero_title = "The final offline V4 gate is sealed — authentic epochs remain incomplete and V5 stays closed."
        v45_hero_copy = (
            "V4.9 authenticates the exact V4.8 parent and evaluates a strict two-gate admission protocol. The cohort "
            "contains one of three required authentic epochs. The frozen reference architecture spans 795,990–838,686 "
            "direct CX against a required maximum of 963. Provider discovery is denied; no credential, network, backend, "
            "simulator or QPU action is authorized."
        )
        v45_width_value, v45_width_note = "1 / 3 EPOCHS", "authentic cohort incomplete · no synthetic substitution"
        v45_cnot_value, v45_cnot_note = "≤963 TARGET", "reference max 838,686 · V5 closed"
    elif v48_preflight_valid:
        v45_hero_kicker = "V4.8 · EXACT ARCHITECTURE REDUCTION · AUTHENTICATED RESEARCH_ONLY"
        v45_hero_title = "CX and frozen-BasicSwap CZ fall materially — multi-snapshot robustness and hardware remain blocked."
        v45_hero_copy = (
            "Eight exact control-loaded Cuccaro streams reduce logical CX from 19,251,104 to 6,474,096 and routed CZ "
            "from 119,029,964 to 59,565,732 under the unchanged frozen BasicSwap oracle. Exact computational-basis "
            "equivalence passes 28,240 cases. Only one authentic historical snapshot epoch exists, and both deliberately "
            "optimistic V4.7-comparable necessary screens still fail on all eight seeds."
        )
        v45_width_value, v45_width_note = "133–145 / 156Q", "8/8 exact streams · architecture-only evidence"
        v45_cnot_value, v45_cnot_note = "6,474,096 CX", "−66.37% aggregate · hardware blocked"
    elif v47_preflight_valid:
        v45_hero_kicker = "V4.7 · DATED PROPERTIES & FAULT-EXCLUDED ROUTING · AUTHENTICATED RESEARCH_ONLY"
        v45_hero_title = "Historical stress screen complete — architecture redesign remains required and hardware stays blocked."
        v45_hero_copy = (
            "The exact eight V4.6 streams are replayed against pinned 2025-02-26 FakeMarrakesh properties. "
            "The baseline encounters reported unit-error tuples; the sole preregistered candidate excludes those tuples "
            "but is not assumed globally optimal. Integer-dt makespan and additive reported-error mass are model-scoped "
            "diagnostics, never current calibration, circuit fidelity, success probability or execution evidence."
        )
        v45_width_value, v45_width_note = "133–145 / 153Q", "healthy component · minimum margin +8"
        v45_cnot_value, v45_cnot_note = "8 / 8 AUDITED", "fixed-architecture stress screen · hardware blocked"
    elif v46_preflight_valid:
        v45_hero_kicker = "V4.6 · FULL-STREAM FAKEMARRAKESH ROUTING · AUTHENTICATED RESEARCH_ONLY"
        v45_hero_title = "All eight full streams route with zero ISA/coupling violations — hardware remains blocked."
        v45_hero_copy = (
            "The sealed streaming compiler reproduces all 48,647,214 V4.5 instructions, inserts 33,259,620 BasicSwap "
            "operations and commits 476,876,458 exactly reconstructible native instructions. The worst seed uses "
            "15,527,797 CZ and 24,893,376 structural layers, passing the limits preregistered in V4.5. This is offline "
            "topology evidence against a dated fake snapshot, not calibration, fidelity, utility or execution evidence."
        )
        v45_width_value, v45_width_note = "133–145 / 156Q", "8/8 routed · minimum margin +11"
        v45_cnot_value, v45_cnot_note = "8 / 8 ROUTED", "worst 15,527,797 CZ · limit 250M"
    elif v45_preflight_valid:
        v45_hero_kicker = "V4.5 · PROOF-CARRYING WIDTH REDUCTION · AUTHENTICATED RESEARCH_ONLY"
        v45_hero_title = "All eight frozen streams fit the 156-qubit logical gate — routing evidence unavailable."
        v45_hero_copy = (
            "Authenticated binary coin addresses, phase-local Bennett recomputation and register-liveness certificates "
            "reduce the allocation from 327–339 to 133–145 logical qubits. Exact registered-promise SELECT traces pass "
            "and every stream remains within 2.5M CX; the worst is 2,499,790 with +210 remaining. This admits only the "
            "next offline reconstruction and routing gate, not hardware execution or advantage."
        )
        v45_width_value, v45_width_note = "133–145 / 156Q", "8/8 pass · minimum margin +11"
        v45_cnot_value, v45_cnot_note = "8 / 8 PASS", "worst 2,499,790 · margin +210"
    else:
        v45_hero_kicker = "V4.5 · PROOF-CARRYING WIDTH REDUCTION · AUTHENTICATION REQUIRED"
        v45_hero_title = "V4.5 scientific outcomes are masked until the complete sealed chain authenticates."
        v45_hero_copy = (
            "The control room has detected absent, incomplete or invalid V4.5 evidence. Width, parity and CX outcomes "
            "are not disclosed from unauthenticated bytes. The V4.4 historical result remains visible below; provider, "
            "network, transpilation, routing and hardware paths remain fail-closed."
        )
        v45_width_value, v45_width_note = "MASKED", "sealed authentication required"
        v45_cnot_value, v45_cnot_note = "MASKED", "sealed authentication required"

    st.markdown(
        f'''<div class="qp3-hero"><div class="qp3-k">{escape(v45_hero_kicker)}</div><div class="qp3-t">{escape(v45_hero_title)}</div><div class="qp3-s">{escape(v45_hero_copy)}</div></div>
        <div class="qp3-grid">
          <div class="qp3-card"><div class="qp3-ck">PHASE-II PARENT</div><div class="qp3-cv">{escape(gate_state)}</div><div class="qp3-cn">{completed}/120 canonical results · final gate required</div></div>
          <div class="qp3-card"><div class="qp3-ck">ELIGIBLE FAMILIES</div><div class="qp3-cv">{eligible_count}</div><div class="qp3-cn">complete Phase-II family gates only</div></div>
          <div class="qp3-card"><div class="qp3-ck">WIDTH / CAPACITY</div><div class="qp3-cv">{escape(v45_width_value)}</div><div class="qp3-cn">{escape(v45_width_note)}</div></div>
          <div class="qp3-card"><div class="qp3-ck">ROUTING / RESOURCE</div><div class="qp3-cv">{escape(v45_cnot_value)}</div><div class="qp3-cn">{escape(v45_cnot_note)}</div></div>
          <div class="qp3-card"><div class="qp3-ck">HARDWARE SUBMISSION</div><div class="qp3-cv">DISABLED · ZERO JOBS</div><div class="qp3-cn">current calibration, duration and fidelity not tested</div></div>
        </div>''', unsafe_allow_html=True,
    )

    if gate_ready:
        st.success("Phase-II classical-hardness evidence is finalized and passed. Phase-III preparation may use only the completed gate-passing families shown below.")
    else:
        st.warning(str(gate.get("reason", "Phase-II finalization is still required.")))
        if eligible_count:
            st.caption("Any family gates visible before 120/120 are provisional diagnostics only and cannot unlock or seal a hardware benchmark.")

    if not eligible.empty:
        show_cols = [c for c in ["N", "Regime", "MILP median s", "MILP p95 s", "Heuristic hard fraction", "Family gate", "Complete family", "Optimality certified fraction"] if c in eligible.columns]
        st.dataframe(eligible[show_cols], width="stretch", hide_index=True)

    rec = gate.get("recommended_family") or None
    family_choices: list[str] = []
    family_map: dict[str, dict[str, Any]] = {}
    if not eligible.empty:
        for _, row in eligible.iterrows():
            d = row.to_dict(); key = f"N={int(d['N'])} · {str(d['Regime']).upper()}"
            family_choices.append(key); family_map[key] = d
    if family_choices:
        recommended_key = None
        if rec:
            recommended_key = f"N={int(rec['N'])} · {str(rec['Regime']).upper()}"
        idx = family_choices.index(recommended_key) if recommended_key in family_choices else 0
        selected_label = st.selectbox("Phase-III candidate family", family_choices, index=idx, key=f"{PREFIX}_p3_family")
        selected_family = family_map[selected_label]
        selected_family["Selection rule"] = "smallest N, then BASE < PAIRWISE < BANDS" if selected_label == recommended_key else "user-selected from Phase-II eligible families"
    elif rec:
        selected_family = dict(rec)
    else:
        fam_all = ((gate.get("status") or {}).get("summary") or {}).get("family_summary")
        selected_family = None
        if isinstance(fam_all, pd.DataFrame) and not fam_all.empty and "Family gate" in fam_all:
            provisional = fam_all[fam_all["Family gate"].astype(bool)]
            if not provisional.empty:
                d = provisional.sort_values(["N", "Regime"], kind="stable").iloc[0].to_dict()
                d["Selection rule"] = "PROVISIONAL ONLY · Phase-II not finalized"
                selected_family = d

    _section_header("Equal-Objective Encoding Audit", "FINANCIAL OBJECTIVE → CONSTRAINT REPRESENTATION → QAOA BLUEPRINT", "A classical-hard instance is not automatically hardware-ready. The audit preserves the Phase-II economic QUBO and identifies whether the hard constraints can be represented without silently changing the optimization problem.")
    encoding = None
    if selected_family:
        n_sel = int(selected_family["N"]); regime_sel = str(selected_family["Regime"]).upper()
        encoding = qpu_family_encoding_audit(n_sel, regime_sel, 1103)
        seed_audits = qpu_family_seed_audits(n_sel, regime_sel)
        display_encoding_status = str(encoding.get("encoding_status", ""))
        display_encoding_exactness = str(encoding.get("encoding_exactness", ""))
        if regime_sel == "BANDS" and display_encoding_status.startswith("BLOCKED"):
            display_encoding_status = "V2.9 BASELINE · FIXED-POINT PATH BLOCKED"
            display_encoding_exactness = (
                "Historical pre-oracle audit: arbitrary penalties remain forbidden. "
                "The V3.0 falsification record, V3.1 exact-dyadic successor and V3.2 "
                "gate-compiler status are evaluated independently below."
            )
            status_cls = "qp3-warn"
            if "Encoding status" in seed_audits.columns:
                seed_audits = seed_audits.copy()
                seed_audits["Encoding status"] = (
                    "V2.9 BASELINE · " + seed_audits["Encoding status"].astype(str)
                )
        else:
            status_cls = (
                "qp3-ok"
                if display_encoding_status.startswith("BLUEPRINT")
                else "qp3-block"
            )
        st.markdown(
            f'''<div class="qp3-panel"><div class="qp3-pk">CANDIDATE FAMILY · N={n_sel} · {escape(regime_sel)}</div><div class="qp3-pt {status_cls}">{escape(display_encoding_status)}</div><div class="qp3-note"><b>Initial state:</b> {escape(str(encoding.get('initial_state')))}<br><b>Mixer:</b> {escape(str(encoding.get('mixer')))}<br><b>Equal-objective condition:</b> {escape(display_encoding_exactness)}</div></div>''', unsafe_allow_html=True,
        )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Logical data qubits", int(encoding.get("logical_qubits_min", n_sel)))
        c2.metric("Economic quadratic terms", int(encoding.get("economic_quadratic_terms", 0)))
        c3.metric("Constraint interactions", int(encoding.get("pairwise_exclusions", 0) + encoding.get("group_bands", 0) + encoding.get("factor_bands", 0)))
        c4.metric("Pre-transpile 2Q interactions · p=1", int(encoding.get("logical_2q_interactions_p1_pretranspile", 0)))
        st.dataframe(seed_audits, width="stretch", hide_index=True)
        envelopes = encoding.get("constraint_resource_envelopes") or []
        if envelopes:
            st.markdown("**BANDS reversible-constraint resource envelope — diagnostic only**")
            st.dataframe(pd.DataFrame(envelopes), width="stretch", hide_index=True)
            st.warning("The BANDS family is classically hard but not yet equal-objective QPU-ready. V3.0 tested and falsified approximate 8/12/16-bit fixed point; V3.1 adds an exact dyadic route that does not round the frozen binary64 parameters.")

        if regime_sel == "BANDS":
            _section_header(
                "Exact BANDS Oracle & Fixed-Point Fidelity",
                "REAL CONSTRAINTS → INTEGER ENCODING → MILP MISMATCH PROOF → REVERSIBLE ORACLE",
                "The proof searches the full binary exact-K/group-band domain for false positives and false negatives. Random samples cannot promote fidelity. The lowest sealed precision 8→12→16 that receives eight certified seed-level proofs is selected automatically.",
            )
            oracle_root = bands_oracle_root()
            sealed_oracle = bands_load_sealed_oracle(oracle_root, n_sel)
            _fixed_point_terminal_fail = bool(
                all(
                    str(
                        bands_family_audit_summary(oracle_root, n_sel, _bits).get(
                            "status", ""
                        )
                    ).startswith("FAMILY FIDELITY FAIL")
                    for _bits in (8, 12, 16)
                )
            )
            if sealed_oracle:
                fixed_point_contract_state = "SEALED · EXACT FAMILY FIDELITY"
                fixed_point_contract_class = "qp3-ok"
            elif _fixed_point_terminal_fail:
                fixed_point_contract_state = (
                    "TERMINAL FAIL · SEALED 8/12/16 FALSIFICATION"
                )
                fixed_point_contract_class = "qp3-block"
            else:
                fixed_point_contract_state = "AUDIT REQUIRED"
                fixed_point_contract_class = "qp3-warn"
            st.markdown(
                f'<div class="qp3-panel"><div class="qp3-pk">V3.0 FIXED-POINT FIDELITY CONTRACT</div><div class="qp3-pt {fixed_point_contract_class}">{escape(fixed_point_contract_state)}</div><div class="qp3-note"><b>Oracle Spec SHA:</b> <span class="qp3-sha">{escape(BANDS_ORACLE_SPEC_SHA)}</span><br><b>Quantization:</b> signed round-half-away-from-zero · ladder 8 → 12 → 16 bits<br><b>Promotion:</b> 0 false-positive witnesses · 0 false-negative witnesses · every proof MILP certified · all 8 seeds PASS. A terminal failure is preserved and is not superseded by post-hoc precision extension.</div></div>',
                unsafe_allow_html=True,
            )
            ladder_rows = []
            for _bits in (8, 12, 16):
                _s = bands_family_audit_summary(oracle_root, n_sel, _bits)
                ladder_rows.append({"Fixed-point bits": _bits, "Status": _s.get("status"), "Completed seeds": f"{_s.get('completed',0)}/8", "Exact family fidelity": bool(_s.get("exact", False))})
            st.dataframe(pd.DataFrame(ladder_rows), width="stretch", hide_index=True)
            st.download_button(
                "Download sealed BANDS oracle audit specification",
                data=json.dumps(bands_oracle_spec_payload(), indent=2, sort_keys=True),
                file_name="PHASE_III_BANDS_ORACLE_SPEC_V1.json",
                mime="application/json",
                key=f"{PREFIX}_p3_oracle_spec_download",
            )
            worker_state = bands_oracle_worker_status(oracle_root, n_sel)
            wc1, wc2, wc3 = st.columns(3)
            wc1.metric("Audit worker", str(worker_state.get("status", "IDLE")))
            _selected_worker_bits = worker_state.get("selected_bits")
            wc2.metric("Selected exact precision", f"{int(_selected_worker_bits)} bits" if _selected_worker_bits is not None else "—")
            wc3.metric("Oracle sealed", "YES" if worker_state.get("sealed") else "NO")
            if _fixed_point_terminal_fail:
                st.error("V3.0 approximate fixed-point ladder is terminally falsified at 8 / 12 / 16 bits. Do not relaunch it or extend it post hoc; use the V3.1 exact dyadic route below.")
            elif not sealed_oracle and st.button("Launch / resume exact fidelity proof worker", key=f"{PREFIX}_p3_oracle_audit"):
                launch = bands_launch_oracle_worker(oracle_root, n_sel)
                st.session_state[f"{PREFIX}_p3_oracle_launch"] = launch
            launch = st.session_state.get(f"{PREFIX}_p3_oracle_launch")
            if isinstance(launch, dict):
                if launch.get("launched"):
                    st.info(f"Exact-fidelity worker launched in the background · PID {launch.get('pid')}. Refresh/rerun this page to update checkpoints.")
                elif launch.get("reason"):
                    st.caption(str(launch.get("reason")))
            st.caption("Proof worker policy: 30 s hard limit per MILP extremum, checkpoint after each seed. A certified mismatch immediately rejects that precision; an uncertified proof stops the ladder as INDETERMINATE rather than skipping upward.")

            selected_bits = None
            for _bits in (8, 12, 16):
                _s = bands_family_audit_summary(oracle_root, n_sel, _bits)
                if _s.get("exact"):
                    selected_bits = _bits
                    st.markdown(f"**Certified seed-level proof · {_bits}-bit fixed point**")
                    st.dataframe(_s["table"], width="stretch", hide_index=True)
                    break
                if str(_s.get("status", "")).startswith("INDETERMINATE"):
                    break
            if selected_bits is not None and not sealed_oracle:
                blueprint = bands_build_blueprint(oracle_root, n_sel, selected_bits)
                rs = blueprint.get("resource_summary") or {}
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Fixed-point precision", f"{selected_bits} bits")
                r2.metric("Logical qubits · reuse", int(rs.get("logical_qubits_sequential_reuse_max", 0)))
                r3.metric("Logical qubits · parallel envelope", int(rs.get("logical_qubits_parallel_envelope_max", 0)))
                r4.metric("Integer comparisons", int(rs.get("integer_comparisons", 0)))
                st.caption("The reversible schedule computes group counts and signed fixed-point factor exposures, flags all seven bands, aggregates feasibility, then uncomputes all temporary arithmetic ancillas.")
                if st.button("Seal exact BANDS logical-oracle blueprint", key=f"{PREFIX}_p3_oracle_seal"):
                    st.session_state[f"{PREFIX}_p3_oracle_sealed"] = bands_seal_family_oracle(oracle_root, n_sel, selected_bits)
                    sealed_oracle = bands_load_sealed_oracle(oracle_root, n_sel)
            seal_result = st.session_state.get(f"{PREFIX}_p3_oracle_sealed")
            if isinstance(seal_result, dict):
                if seal_result.get("sealed"):
                    st.success(f"Exact BANDS logical oracle sealed: {seal_result.get('path')}. No QPU job was submitted.")
                else:
                    st.error(str(seal_result.get("reason")))
            sealed_oracle = bands_load_sealed_oracle(oracle_root, n_sel)
            if sealed_oracle:
                encoding = bands_promote_encoding(encoding, sealed_oracle)
                rs = sealed_oracle.get("resource_summary") or {}
                st.markdown(f'<div class="qp3-panel"><div class="qp3-pk">V3.0 FIXED-POINT LOGICAL ORACLE</div><div class="qp3-pt qp3-ok">EXACT FEASIBLE-SET FIDELITY · PASS</div><div class="qp3-note"><b>Oracle SHA:</b> <span class="qp3-sha">{escape(str(sealed_oracle.get("oracle_blueprint_sha")))}</span><br><b>Fixed point:</b> {int(sealed_oracle.get("fixed_point_bits",0))} bits · <b>All seeds:</b> 8/8<br><b>Logical qubits, sequential-reuse envelope:</b> {int(rs.get("logical_qubits_sequential_reuse_max",0))}<br><b>Next gate:</b> compile the sealed reversible integer-arithmetic IR to a named SDK/backend without changing the Phase-II objective.</div></div>', unsafe_allow_html=True)

            # V3.1 exact dyadic route. It is only sealable after the full V3.0 8/12/16
            # ladder is preserved as a falsification record. This prevents a post-hoc
            # precision extension from replacing the preregistered failed test.
            fixed_point_summaries = [bands_family_audit_summary(oracle_root, n_sel, _bits) for _bits in (8, 12, 16)]
            v30_falsified = bool(all(str(_s.get("status", "")).startswith("FAMILY FIDELITY FAIL") for _s in fixed_point_summaries))
            _section_header(
                "Exact Dyadic BANDS Oracle",
                "BINARY64 PARAMETERS → EXACT INTEGER RATIOS → REVERSIBLE SIGNED ARITHMETIC",
                "V3.1 does not add more approximate fixed-point bits. It converts the frozen IEEE-754 binary64 coefficients and hard bounds exactly into signed integers over per-factor power-of-two denominators. Algebraic equivalence is by construction; the V3.0 failed ladder remains part of the evidence record.",
            )
            dyadic_root = default_dyadic_root()
            dyadic_summary = family_dyadic_summary(n_sel)
            dyadic_sealed = load_sealed_dyadic_oracle(dyadic_root, n_sel)
            v30_status_text = "PASS · 8/12/16 FALSIFICATION PRESERVED" if v30_falsified else "WAITING · COMPLETE V3.0 FALSIFICATION RECORD REQUIRED"
            st.markdown(
                f'<div class="qp3-panel"><div class="qp3-pk">DYADIC EXACTNESS CONTRACT</div><div class="qp3-pt {"qp3-ok" if dyadic_summary.get("exact") else "qp3-block"}">{escape(str(dyadic_summary.get("status")))}</div><div class="qp3-note"><b>Dyadic Spec SHA:</b> <span class="qp3-sha">{escape(DYADIC_SPEC_SHA)}</span><br><b>V3.0 dependency:</b> {escape(v30_status_text)}<br><b>Mapping:</b> every frozen binary64 coefficient/bound uses <code>as_integer_ratio()</code>; no 8/12/16 rounding remains.<br><b>Semantic contract:</b> exact hard-band coefficients/bounds of the authoritative Phase-II MILP. The 1e-8 feasibility tolerance remains a separate numerical validator convention.</div></div>',
                unsafe_allow_html=True,
            )
            st.dataframe(dyadic_summary["table"], width="stretch", hide_index=True)
            drs = dyadic_summary.get("resource_summary") or {}
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric("Exact seed certificates", f"{dyadic_summary.get('completed',0)}/8")
            dc2.metric("Max dyadic exponent", int(drs.get("max_dyadic_denominator_exponent", 0)))
            dc3.metric("Max accumulator bits", int(drs.get("max_factor_accumulator_bits", 0)))
            dc4.metric("Logical qubits · reuse", int(drs.get("logical_qubits_sequential_reuse_max", 0)))
            st.caption(f"Parallel-register envelope: {int(drs.get('logical_qubits_parallel_envelope_max',0))} logical qubits · controlled-add operations/seed up to {int(drs.get('controlled_add_operations_max',0))} · integer comparisons {int(drs.get('integer_comparisons',0))}.")
            st.download_button(
                "Download exact dyadic BANDS oracle specification",
                data=json.dumps(dyadic_spec_payload(), indent=2, sort_keys=True),
                file_name="PHASE_III_DYADIC_BANDS_ORACLE_SPEC_V1.json",
                mime="application/json",
                key=f"{PREFIX}_p3_dyadic_spec_download",
            )
            if not v30_falsified:
                st.warning("The exact dyadic route is intentionally not sealable yet because the V3.0 8/12/16 falsification record is incomplete in this runtime. Preserve/restore those audit checkpoints first; do not regenerate a more favorable approximate ladder.")
            elif dyadic_summary.get("exact") and not dyadic_sealed:
                if st.button("Seal exact dyadic BANDS logical-oracle blueprint", key=f"{PREFIX}_p3_dyadic_seal"):
                    st.session_state[f"{PREFIX}_p3_dyadic_sealed"] = seal_dyadic_oracle(dyadic_root, n_sel, v3_fixed_point_falsified=True)
                    dyadic_sealed = load_sealed_dyadic_oracle(dyadic_root, n_sel)
            dyadic_seal_result = st.session_state.get(f"{PREFIX}_p3_dyadic_sealed")
            if isinstance(dyadic_seal_result, dict):
                if dyadic_seal_result.get("sealed"):
                    st.success(f"Exact dyadic BANDS logical oracle sealed: {dyadic_seal_result.get('path')}. No QPU job was submitted.")
                else:
                    st.error(str(dyadic_seal_result.get("reason")))
            dyadic_sealed = load_sealed_dyadic_oracle(dyadic_root, n_sel)
            if dyadic_sealed:
                encoding = promote_dyadic_encoding(encoding, dyadic_sealed)
                drs = dyadic_sealed.get("resource_summary") or {}
                st.markdown(
                    f'<div class="qp3-panel"><div class="qp3-pk">SEALED EXACT DYADIC LOGICAL ORACLE</div><div class="qp3-pt qp3-ok">BINARY64 PARAMETER IDENTITY · PASS</div><div class="qp3-note"><b>Oracle SHA:</b> <span class="qp3-sha">{escape(str(dyadic_sealed.get("dyadic_oracle_sha")))}</span><br><b>All seeds:</b> 8/8 exact parameter certificates<br><b>Max factor accumulator:</b> {int(drs.get("max_factor_accumulator_bits",0))} signed bits · <b>max dyadic exponent:</b> {int(drs.get("max_dyadic_denominator_exponent",0))}<br><b>Logical qubits, sequential-reuse envelope:</b> {int(drs.get("logical_qubits_sequential_reuse_max",0))}<br><b>Successor gate:</b> V3.2 compiler evidence below. Hardware execution remains <b>FALSE</b> after compiler sealing until the algorithm and backend gates pass.</div></div>',
                    unsafe_allow_html=True,
                )

            _section_header(
                "V3.2 Proof-Carrying Reversible Gate Compiler",
                "IMMUTABLE PARENT → RANGE PROOF → GATE IR → CLEAN UNCOMPUTE → REPRODUCIBILITY",
                "The compiler emits a deterministic provider-neutral X/CX/CCX/MCX stream. Every seal carries its parent hashes, compiler source/spec hashes, exhaustive controls and a four-level resource ledger. It does not imply backend executability.",
            )
            compiler_spec = load_compiler_spec()
            parent_artifact_path = sealed_dyadic_oracle_path(dyadic_root, n_sel)
            if parent_artifact_path.exists():
                parent_guard = load_and_validate_dyadic_artifact(
                    parent_artifact_path,
                    expected_raw_sha256=EXPECTED_PARENT_RAW_SHA256,
                )
            else:
                parent_guard = {
                    "valid": False,
                    "failed_checks": ["PARENT_ARTIFACT_MISSING"],
                    "hashes": {},
                }
            compiler_root = default_compiler_root()
            compiler_seal_path = compiler_root / GATE_COMPILER_SEAL_NAME
            worker = compiler_worker_status(compiler_root)
            artifact_integrity: dict[str, Any] = {"valid": False, "errors": []}
            if worker.get("status") == "SEALED":
                gate_compiler_artifact = worker.get("artifact")
                artifact_integrity = worker.get("integrity") or artifact_integrity
            else:
                if compiler_seal_path.exists():
                    try:
                        gate_compiler_artifact, artifact_integrity = load_compiler_artifact(
                            compiler_seal_path
                        )
                    except Exception as exc:
                        artifact_integrity = {"valid": False, "errors": [str(exc)]}
            chain_checks = {
                "artifact_internal_hash": bool(artifact_integrity.get("valid")),
                "compiler_source_hash": bool(
                    gate_compiler_artifact
                    and gate_compiler_artifact.get("compiler", {}).get(
                        "compiler_source_sha256"
                    )
                    == compiler_source_sha256()
                ),
                "compiler_spec_hash": bool(
                    gate_compiler_artifact
                    and gate_compiler_artifact.get("compiler", {}).get(
                        "compiler_spec_sha256"
                    )
                    == compiler_spec.get("gate_compiler_spec_sha256")
                ),
                "frozen_parent_guard": bool(parent_guard.get("valid")),
                "parent_hash_chain": bool(
                    gate_compiler_artifact
                    and gate_compiler_artifact.get("parent", {}).get(
                        "raw_file_sha256"
                    )
                    == (parent_guard.get("hashes") or {}).get("raw_file_sha256")
                    == EXPECTED_PARENT_RAW_SHA256
                ),
                "validation_manifest": bool(
                    gate_compiler_artifact
                    and gate_compiler_artifact.get("validation", {}).get(
                        "overall_pass"
                    )
                    is True
                ),
            }
            gate_compiler_integrity = bool(
                gate_compiler_artifact and all(chain_checks.values())
            )
            if gate_compiler_integrity and encoding is not None:
                exact_ir = (
                    gate_compiler_artifact.get("resource_summary", {}).get(
                        DOMAIN_EXACT_K, {}
                    )
                    or {}
                )
                encoding = dict(encoding)
                encoding.update(
                    {
                        "encoding_status": (
                            "REVERSIBLE GATE IR SEALED · ALGORITHM/BACKEND BLOCKED"
                        ),
                        "compiler_status": gate_compiler_artifact.get(
                            "compiler", {}
                        ).get(
                            "status",
                            "SEALED PROVIDER-NEUTRAL REVERSIBLE GATE IR",
                        ),
                        "gate_compiler_artifact_sha": gate_compiler_artifact.get(
                            "artifact_sha256"
                        ),
                        "gate_compiler_validation_sha": gate_compiler_artifact.get(
                            "validation", {}
                        ).get("validation_manifest_sha256"),
                        "gate_ir_domain_mode": DOMAIN_EXACT_K,
                        "logical_qubits_min": int(
                            exact_ir.get(
                                "logical_qubits_max",
                                encoding.get("logical_qubits_min", 0),
                            )
                            or 0
                        ),
                        "hardware_executable": False,
                    }
                )
            compiler_state = (
                "SEALED · END-TO-END INTEGRITY PASS"
                if gate_compiler_integrity
                else (
                    "INVALID · FAIL CLOSED"
                    if gate_compiler_artifact
                    else f"{worker.get('status', 'WAITING')} · SEAL NOT AVAILABLE"
                )
            )
            compiler_state_class = (
                "qp3-ok"
                if gate_compiler_integrity
                else ("qp3-block" if gate_compiler_artifact else "qp3-warn")
            )
            artifact_sha = (
                str(gate_compiler_artifact.get("artifact_sha256", ""))[:24]
                if gate_compiler_artifact
                else "—"
            )
            validation_sha = (
                str(
                    gate_compiler_artifact.get("validation", {}).get(
                        "validation_manifest_sha256", ""
                    )
                )[:24]
                if gate_compiler_artifact
                else "—"
            )
            st.markdown(
                f'<div class="qp3-panel"><div class="qp3-pk">PROOF-CARRYING COMPILER SEAL</div><div class="qp3-pt {compiler_state_class}">{escape(compiler_state)}</div><div class="qp3-note"><b>Parent raw SHA-256:</b> <span class="qp3-sha">{escape(EXPECTED_PARENT_RAW_SHA256[:24])}…</span> · <b>guard:</b> {"PASS" if parent_guard.get("valid") else "FAIL"}<br><b>Compiler spec:</b> <span class="qp3-sha">{escape(str(compiler_spec.get("gate_compiler_spec_sha")))}</span> · <b>artifact:</b> <span class="qp3-sha">{escape(artifact_sha)}</span><br><b>Validation manifest:</b> <span class="qp3-sha">{escape(validation_sha)}</span><br><b>Unitary:</b> U<sub>f</sub>|x⟩|y⟩|0⟩ = |x⟩|y ⊕ f(x)⟩|0⟩ · negative controls explicit · all arithmetic little-endian.</div></div>',
                unsafe_allow_html=True,
            )
            if gate_compiler_integrity:
                st.markdown(
                    f'<div class="qp3-panel"><div class="qp3-pk">CURRENT EQUAL-OBJECTIVE READINESS</div><div class="qp3-pt qp3-warn">GATE IR SEALED · ALGORITHM + BACKEND STILL BLOCKED</div><div class="qp3-note"><b>Representation:</b> exact dyadic BANDS predicate compiled and reproducible · <b>reference width:</b> {int((gate_compiler_artifact.get("resource_summary", {}).get(DOMAIN_EXACT_K, {}) or {}).get("logical_qubits_max", 0))} logical qubits in the exact-K contract.<br><b>Remaining:</b> validate enforcement of all seven BANDS constraints at the algorithm level, then freeze a named native basis, calibration snapshot, decomposition, routing and error budget. This state is intentionally not hardware executable.</div></div>',
                    unsafe_allow_html=True,
                )

            spec_col, artifact_col = st.columns(2)
            with spec_col:
                st.download_button(
                    "Download V3.2 compiler specification",
                    data=json.dumps(
                        compiler_spec, indent=2, sort_keys=True, ensure_ascii=False
                    ),
                    file_name="PHASE_III_GATE_COMPILER_SPEC_V1.json",
                    mime="application/json",
                    key=f"{PREFIX}_p3_gate_compiler_spec_download",
                )
            with artifact_col:
                if gate_compiler_artifact:
                    st.download_button(
                        "Download sealed proof-carrying compiler artifact",
                        data=json.dumps(
                            gate_compiler_artifact,
                            indent=2,
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        file_name=GATE_COMPILER_SEAL_NAME,
                        mime="application/json",
                        key=f"{PREFIX}_p3_gate_compiler_artifact_download",
                    )

            if gate_compiler_artifact:
                resource_summary = gate_compiler_artifact.get("resource_summary") or {}
                exact_resources = resource_summary.get(DOMAIN_EXACT_K) or {}
                full_resources = resource_summary.get(DOMAIN_FULL_BINARY) or {}
                vm = gate_compiler_artifact.get("validation") or {}
                vc1, vc2, vc3, vc4 = st.columns(4)
                vc1.metric(
                    "Validation ladder",
                    f"{sum(bool(v) for v in (vm.get('checks') or {}).values())}/{len(vm.get('checks') or {})}",
                )
                vc2.metric(
                    "EXACT-K logical qubits",
                    int(exact_resources.get("logical_qubits_max", 0)),
                )
                vc3.metric(
                    "FULL-BINARY logical qubits",
                    int(full_resources.get("logical_qubits_max", 0)),
                )
                vc4.metric(
                    "Canonical circuits",
                    len(vm.get("compilation_entries") or []),
                )
                mode_table = pd.DataFrame(
                    [
                        {
                            "Oracle contract": "EXACT-K subspace",
                            "Domain": "popcount(x)=10",
                            "Cardinality inside oracle": "No",
                            "Constraints": 7,
                            "Max factor bits": int(
                                exact_resources.get("max_factor_width", 0)
                            ),
                            "Logical qubits max": int(
                                exact_resources.get("logical_qubits_max", 0)
                            ),
                            "Abstract gates max": int(
                                exact_resources.get("abstract_gate_count_max", 0)
                            ),
                            "FT T-count upper estimate": int(
                                exact_resources.get("fault_tolerant_t_count_max", 0)
                            ),
                        },
                        {
                            "Oracle contract": "FULL-BINARY",
                            "Domain": "all 2^40 bitstrings",
                            "Cardinality inside oracle": "Yes",
                            "Constraints": 8,
                            "Max factor bits": int(
                                full_resources.get("max_factor_width", 0)
                            ),
                            "Logical qubits max": int(
                                full_resources.get("logical_qubits_max", 0)
                            ),
                            "Abstract gates max": int(
                                full_resources.get("abstract_gate_count_max", 0)
                            ),
                            "FT T-count upper estimate": int(
                                full_resources.get("fault_tolerant_t_count_max", 0)
                            ),
                        },
                    ]
                )
                st.dataframe(mode_table, width="stretch", hide_index=True)
                seeds_69 = full_resources.get("seeds_requiring_69_factor_bits") or []
                st.info(
                    "Range-proof distinction: the exact-K contract closes at 68 signed factor bits. "
                    f"The complete full-binary contract requires 69 bits for seed(s) {', '.join(map(str, seeds_69)) or '—'}; this extra bit is retained rather than hidden by an exact-K assumption."
                )
                ladder_rows = [
                    {"Gate": key, "Pass": bool(value)}
                    for key, value in (vm.get("checks") or {}).items()
                ]
                st.markdown("**Validation ladder & provenance gates**")
                st.dataframe(
                    pd.DataFrame(ladder_rows), width="stretch", hide_index=True
                )
                seed_rows = []
                for entry in vm.get("compilation_entries") or []:
                    abstract = (
                        entry.get("resource_ledger", {})
                        .get("levels", {})
                        .get("GATE_LEVEL_ABSTRACT", {})
                    )
                    logical = (
                        entry.get("resource_ledger", {})
                        .get("levels", {})
                        .get("LOGICAL_IR", {})
                    )
                    seed_rows.append(
                        {
                            "Seed": entry.get("seed"),
                            "Mode": entry.get("domain_mode"),
                            "Gate IR SHA": str(entry.get("gate_ir_sha256", ""))[:16],
                            "Logical qubits": logical.get("logical_qubits_total"),
                            "Abstract gates": abstract.get("gate_count"),
                            "Abstract depth": abstract.get("abstract_depth"),
                        }
                    )
                with st.expander("16 canonical circuit ledgers", expanded=False):
                    st.dataframe(
                        pd.DataFrame(seed_rows),
                        width="stretch",
                        hide_index=True,
                    )
                with st.expander("Claim boundary & research backlog", expanded=True):
                    st.markdown(
                        "\n".join(
                            f"- {item}"
                            for item in gate_compiler_artifact.get("limitations") or []
                        )
                    )
                    st.caption(
                        "The next evidence gate is now the additive V3.3 algorithmic contract below. Native synthesis and backend routing remain downstream and are not implied by the compiler seal."
                    )
            else:
                w1, w2, w3 = st.columns(3)
                w1.metric("Parent guard", "PASS" if parent_guard.get("valid") else "FAIL")
                w2.metric("Compiler worker", str(worker.get("status", "IDLE")))
                w3.metric("Hardware executable", "FALSE")
                if worker.get("status") == "RUNNING":
                    st.info(
                        "The full two-pass compiler audit is running in the background. "
                        "It may take several minutes because canonical gate streams are traversed rather than estimated."
                    )
                    if worker.get("log_tail"):
                        with st.expander("Compiler worker progress", expanded=False):
                            st.code(str(worker.get("log_tail")), language="text")
                else:
                    if st.button(
                        "Launch full V3.2 compiler audit",
                        disabled=not bool(parent_guard.get("valid")),
                        key=f"{PREFIX}_p3_gate_compiler_launch",
                    ):
                        try:
                            launch = launch_compiler_worker(
                                parent_artifact_path, compiler_root
                            )
                            st.session_state[
                                f"{PREFIX}_p3_gate_compiler_launch_state"
                            ] = launch
                        except Exception as exc:
                            st.session_state[
                                f"{PREFIX}_p3_gate_compiler_launch_state"
                            ] = {"launched": False, "reason": str(exc)}
                    launch_state = st.session_state.get(
                        f"{PREFIX}_p3_gate_compiler_launch_state"
                    )
                    if isinstance(launch_state, dict):
                        if launch_state.get("launched"):
                            st.success(
                                f"Compiler audit launched · PID {launch_state.get('pid')}. Rerun this tab for progress."
                            )
                        elif launch_state.get("reason"):
                            st.warning(str(launch_state.get("reason")))
                st.caption(
                    "Fail-closed policy: a missing parent hash, source/spec drift, failed basis-state control, dirty ancilla or non-reproducible gate hash blocks the seal."
                )

            _section_header(
                "V3.3 Exact Feasible-Subspace Mixer Contract",
                "CACHED f(x) GUARD → RELABELLED f(Sx) GUARD → C2-XY → CLEAN UNCOMPUTE",
                "The institutional reference keeps one authenticated feasibility flag for the complete ordered layer and computes only the candidate neighbor predicate per edge. This proves exact invariance relative to the frozen V3.2 predicate; it does not prove that the feasible graph is connected or that the construction is hardware-practical.",
            )
            algorithm_spec = load_algorithm_spec()
            algorithm_root = default_algorithmic_root()
            algorithm_seal_path = algorithm_root / ALGORITHMIC_SEAL_NAME
            algorithm_artifact_integrity: dict[str, Any] = {
                "valid": False,
                "errors": [],
            }
            if algorithm_seal_path.exists():
                try:
                    algorithmic_artifact, algorithm_artifact_integrity = (
                        load_algorithmic_artifact(algorithm_seal_path)
                    )
                except Exception as exc:
                    algorithm_artifact_integrity = {
                        "valid": False,
                        "errors": [str(exc)],
                    }

            algorithm_decisions = (
                algorithmic_artifact.get("decisions", {})
                if algorithmic_artifact
                else {}
            )
            algorithm_validation = (
                algorithmic_artifact.get("validation", {})
                if algorithmic_artifact
                else {}
            )
            algorithm_parents = (
                algorithmic_artifact.get("parents", {})
                if algorithmic_artifact
                else {}
            )
            algorithm_chain_checks = {
                "artifact_internal_hash": bool(
                    algorithm_artifact_integrity.get("valid")
                ),
                "algorithm_source_hash": bool(
                    algorithmic_artifact
                    and algorithmic_artifact.get("algorithm", {}).get(
                        "algorithm_source_sha256"
                    )
                    == algorithm_source_sha256()
                ),
                "algorithm_spec_hash": bool(
                    algorithmic_artifact
                    and algorithmic_artifact.get("algorithm", {}).get(
                        "algorithm_spec_sha256"
                    )
                    == algorithm_spec.get("algorithm_contract_spec_sha256")
                ),
                "validation_and_verifier_source_hashes": bool(
                    algorithm_validation.get("validation_source_sha256")
                    == validation_source_sha256()
                    and algorithm_validation.get("verifier_source_sha256")
                    == verifier_source_sha256()
                ),
                "v32_semantic_parent": bool(
                    algorithmic_artifact
                    and gate_compiler_integrity
                    and gate_compiler_artifact
                    and algorithm_parents.get("v32_artifact_sha256")
                    == gate_compiler_artifact.get("artifact_sha256")
                ),
                "v32_raw_parent": bool(
                    algorithmic_artifact
                    and compiler_seal_path.exists()
                    and algorithm_parents.get("v32_raw_file_sha256")
                    == raw_file_sha256(compiler_seal_path)
                ),
                "validation_manifest": bool(
                    algorithm_validation.get("overall_pass") is True
                    and len(algorithm_validation.get("checks") or {}) == 8
                    and all(
                        bool(value)
                        for value in (algorithm_validation.get("checks") or {}).values()
                    )
                ),
                "decision_boundaries": bool(
                    str(
                        algorithm_decisions.get("feasibility_invariance", "")
                    ).startswith("PASS")
                    and algorithm_decisions.get("guard_ancilla_cleanup") == "PASS"
                    and algorithm_decisions.get("complete_global_connectivity")
                    == "INDETERMINATE"
                    and str(algorithm_decisions.get("ring_topology", "")).startswith(
                        "REJECTED"
                    )
                ),
                "hardware_fail_closed": bool(
                    algorithmic_artifact
                    and algorithmic_artifact.get("claim_boundary", {}).get(
                        "hardware_executable"
                    )
                    is False
                    and algorithmic_artifact.get("claim_boundary", {}).get(
                        "qpu_submission_enabled"
                    )
                    is False
                    and algorithm_decisions.get("hardware_execution")
                    == "BLOCKED · ZERO JOBS"
                ),
            }
            algorithmic_integrity = bool(
                algorithmic_artifact and all(algorithm_chain_checks.values())
            )
            contract_state = (
                "SEALED · INVARIANCE AND CLEANUP PASS"
                if algorithmic_integrity
                else (
                    "INVALID · FAIL CLOSED"
                    if algorithmic_artifact
                    else "WAITING · CANONICAL SEAL NOT FOUND"
                )
            )
            contract_class = (
                "qp3-ok"
                if algorithmic_integrity
                else ("qp3-block" if algorithmic_artifact else "qp3-warn")
            )
            st.markdown(
                f'''<div class="qp3-panel"><div class="qp3-pk">ALGORITHMIC CONTRACT SEAL</div><div class="qp3-pt {contract_class}">{escape(contract_state)}</div><div class="qp3-note"><b>V3.3 spec:</b> <span class="qp3-sha">{escape(str(algorithm_spec.get("algorithm_contract_spec_sha")))}</span> · <b>artifact:</b> <span class="qp3-sha">{escape(str((algorithmic_artifact or {}).get("artifact_sha256", "—"))[:24])}</span><br><b>Validation:</b> <span class="qp3-sha">{escape(str(algorithm_validation.get("validation_manifest_sha256", "—"))[:24])}</span> · <b>resource manifest:</b> <span class="qp3-sha">{escape(str((algorithmic_artifact or {}).get("resource_envelopes", {}).get("resource_manifest_sha256", "—"))[:24])}</span><br><b>Validator:</b> <span class="qp3-sha">{escape(str(algorithm_validation.get("validation_source_sha256", "—"))[:20])}</span> · <b>release verifier:</b> <span class="qp3-sha">{escape(str(algorithm_validation.get("verifier_source_sha256", "—"))[:20])}</span><br><b>Construction:</b> compute a=f(x) once · for every edge compute b=f(Sx) by logical wire relabelling · apply C²-XY only when a=b=1 · uncompute b · clear a after the ordered layer.</div></div>''',
                unsafe_allow_html=True,
            )

            card_invariance = "PASS" if algorithmic_integrity else "BLOCKED"
            card_cleanup = "PASS" if algorithmic_integrity else "BLOCKED"
            st.markdown(
                f'''<div class="qp3-grid">
                  <div class="qp3-card"><div class="qp3-ck">FEASIBLE-SUBSPACE INVARIANCE</div><div class="qp3-cv {"qp3-ok" if algorithmic_integrity else "qp3-block"}">{card_invariance}</div><div class="qp3-cn">relative to the frozen seven-constraint V3.2 predicate</div></div>
                  <div class="qp3-card"><div class="qp3-ck">GUARD ANCILLAS</div><div class="qp3-cv {"qp3-ok" if algorithmic_integrity else "qp3-block"}">{card_cleanup}</div><div class="qp3-cn">cached guard invariant + transient neighbor cleanup</div></div>
                  <div class="qp3-card"><div class="qp3-ck">GLOBAL CONNECTIVITY</div><div class="qp3-cv qp3-warn">INDETERMINATE</div><div class="qp3-cn">local witness reachability is not an ergodicity proof</div></div>
                  <div class="qp3-card"><div class="qp3-ck">BACKEND / QPU</div><div class="qp3-cv qp3-block">BLOCKED · ZERO JOBS</div><div class="qp3-cn">C2-XY synthesis, routing, calibration and noise not run</div></div>
                </div>''',
                unsafe_allow_html=True,
            )

            if algorithmic_integrity and algorithmic_artifact:
                encoding = dict(encoding or {})
                encoding.update(
                    {
                        "algorithmic_contract_pass": True,
                        "algorithmic_contract_sha": algorithmic_artifact.get(
                            "artifact_sha256"
                        ),
                        "encoding_status": (
                            "FEASIBILITY INVARIANCE SEALED · CONNECTIVITY/BACKEND BLOCKED"
                        ),
                        "hardware_executable": False,
                    }
                )
                ledgers = algorithmic_artifact.get("resource_envelopes", {}).get(
                    "ledgers", {}
                )
                complete_ledger = ledgers.get(
                    f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
                )
                ring_ledger = ledgers.get(
                    f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_RING}", {}
                )
                complete_max = complete_ledger.get("maxima", {})
                ring_max = ring_ledger.get("maxima", {})
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("V3.3 validation gates", "8 / 8")
                m2.metric(
                    "Complete-scan oracle calls",
                    f"{int(complete_ledger.get('oracle_calls', 0)):,}",
                )
                m3.metric(
                    "Provider-neutral gates · max",
                    f"{int(complete_max.get('provider_neutral_gate_count', 0)):,}",
                )
                m4.metric(
                    "Logical qubits · reuse",
                    int(complete_max.get("logical_qubits_sequential_reuse", 0)),
                )
                topology_table = pd.DataFrame(
                    [
                        {
                            "Topology": "RING · control",
                            "Decision": algorithm_decisions.get("ring_topology"),
                            "Edges": ring_ledger.get("edge_count"),
                            "Oracle calls": ring_ledger.get("oracle_calls"),
                            "IR gates · max": ring_max.get(
                                "provider_neutral_gate_count"
                            ),
                            "IR depth · max": ring_max.get(
                                "provider_neutral_depth"
                            ),
                            "Oracle-path T subtotal": ring_max.get(
                                "oracle_path_t_count_upper_subtotal"
                            ),
                            "Native / routed": "NOT RUN",
                        },
                        {
                            "Topology": "COMPLETE · canonical",
                            "Decision": algorithm_decisions.get(
                                "complete_witness_local_reachability"
                            ),
                            "Edges": complete_ledger.get("edge_count"),
                            "Oracle calls": complete_ledger.get("oracle_calls"),
                            "IR gates · max": complete_max.get(
                                "provider_neutral_gate_count"
                            ),
                            "IR depth · max": complete_max.get(
                                "provider_neutral_depth"
                            ),
                            "Oracle-path T subtotal": complete_max.get(
                                "oracle_path_t_count_upper_subtotal"
                            ),
                            "Native / routed": "NOT RUN",
                        },
                    ]
                )
                st.dataframe(topology_table, width="stretch", hide_index=True)
                st.error(
                    "Resource falsification: the canonical complete-swap layer reaches "
                    f"{int(complete_max.get('provider_neutral_gate_count', 0)):,} "
                    "provider-neutral operations and an oracle-only T subtotal of "
                    f"{int(complete_max.get('oracle_path_t_count_upper_subtotal', 0)):,}. "
                    "The missing controlled-XY synthesis can only add cost. This rejects "
                    "the reference construction as NISQ-practical; it is not a proof that "
                    "future optimized encodings are impossible."
                )

                graph_rows = (
                    algorithm_validation.get("n40_witness_graph", {}).get("rows", [])
                )
                graph_table = pd.DataFrame(
                    [
                        {
                            "Seed": row.get("seed"),
                            "Ring degree": row.get("ring_degree"),
                            "Complete degree": row.get("complete_degree"),
                            "Reachable ≤2 hops": row.get(
                                "two_hop_reachable_lower_bound"
                            ),
                            "Direct = delta": row.get(
                                "direct_delta_neighbor_parity"
                            ),
                            "Order independent": row.get(
                                "two_hop_order_independent"
                            ),
                        }
                        for row in graph_rows
                    ]
                )
                st.markdown("**Authenticated N=40 witness-neighborhood audit**")
                st.dataframe(graph_table, width="stretch", hide_index=True)
                st.warning(
                    "RING TOPOLOGY · REJECTED · AUTHENTICATED WITNESS ISOLATION. "
                    "Seed 5501 is an authenticated feasible state with ring degree 0, so "
                    "the sparse ring mixer is rejected. Every witness has 31–65 complete-swap "
                    "neighbors and 302–1,204 states reachable within two hops, but those local "
                    "lower bounds do not establish global connectivity."
                )
                decision_table = pd.DataFrame(
                    [
                        {
                            "Claim": "Seven-constraint feasibility invariance",
                            "Decision": algorithm_decisions.get(
                                "feasibility_invariance"
                            ),
                            "Evidence scope": "Symbolic + exhaustive N=6 + N=40 witness parity",
                        },
                        {
                            "Claim": "Guard cleanup",
                            "Decision": algorithm_decisions.get(
                                "guard_ancilla_cleanup"
                            ),
                            "Evidence scope": "All Boolean cases; unitary full-layer controls",
                        },
                        {
                            "Claim": "Complete feasible-graph connectivity",
                            "Decision": algorithm_decisions.get(
                                "complete_global_connectivity"
                            ),
                            "Evidence scope": "Not exhaustively enumerated at N=40",
                        },
                        {
                            "Claim": "Hardware execution / advantage",
                            "Decision": "BLOCKED / NOT CLAIMED",
                            "Evidence scope": "Native synthesis, routing, noise, QPU all not run",
                        },
                    ]
                )
                st.markdown("**Decision matrix — claims remain independent**")
                st.dataframe(decision_table, width="stretch", hide_index=True)

                spec_col, artifact_col = st.columns(2)
                with spec_col:
                    st.download_button(
                        "Download V3.3 algorithmic contract specification",
                        data=json.dumps(
                            algorithm_spec,
                            indent=2,
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        file_name="PHASE_III_ALGORITHMIC_CONTRACT_SPEC_V1.json",
                        mime="application/json",
                        key=f"{PREFIX}_p3_v33_spec_download",
                    )
                with artifact_col:
                    st.download_button(
                        "Download sealed V3.3 mixer artifact",
                        data=json.dumps(
                            algorithmic_artifact,
                            indent=2,
                            sort_keys=True,
                            ensure_ascii=False,
                        ),
                        file_name=ALGORITHMIC_SEAL_NAME,
                        mime="application/json",
                        key=f"{PREFIX}_p3_v33_artifact_download",
                    )
                with st.expander(
                    "V3.3 validation ladder, limitations & roadmap change",
                    expanded=False,
                ):
                    st.dataframe(
                        pd.DataFrame(
                            [
                                {"Gate": key, "Pass": bool(value)}
                                for key, value in (
                                    algorithm_validation.get("checks") or {}
                                ).items()
                            ]
                        ),
                        width="stretch",
                        hide_index=True,
                    )
                    st.markdown(
                        "\n".join(
                            f"- {item}"
                            for item in algorithmic_artifact.get("limitations", [])
                        )
                    )
                    st.caption(
                        "Roadmap change is explicit: backend-native MCX/C2-XY lowering moved "
                        "to V3.4 so that routing does not precede validation of the scientific "
                        "algorithm. The prior V3.3 backend milestone is not represented as complete."
                    )
            else:
                st.warning(
                    "The V3.3 seal is missing or its live parent/source/spec chain is invalid. "
                    "Feasibility invariance therefore remains fail-closed in this runtime."
                )

            v34_state = render_v34_evidence_panel(
                _section_header,
                parent_v33_artifact=algorithmic_artifact,
                parent_v33_integrity=algorithmic_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            optimized_native_artifact = v34_state.get("artifact")
            optimized_native_integrity = bool(v34_state.get("integrity"))
            if optimized_native_integrity and encoding is not None:
                encoding = dict(encoding)
                v34_complete = (
                    (optimized_native_artifact or {})
                    .get("resource_envelopes", {})
                    .get("ledgers", {})
                    .get(f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {})
                )
                encoding.update(
                    {
                        "optimized_native_contract_pass": True,
                        "optimized_native_contract_sha": (
                            optimized_native_artifact or {}
                        ).get("artifact_sha256"),
                        "encoding_status": (
                            "OPTIMIZED ELEMENTARY IR SEALED · BACKEND/CONNECTIVITY BLOCKED"
                        ),
                        "logical_qubits_min": int(
                            v34_complete.get("maxima", {}).get(
                                "logical_qubits_sequential_reuse",
                                encoding.get("logical_qubits_min", 0),
                            )
                            or 0
                        ),
                        "hardware_executable": False,
                    }
                )
            v35_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            try:
                backend_admission_artifact, v35_integrity_report = (
                    load_admission_artifact()
                )
            except Exception as exc:
                v35_integrity_report = {"valid": False, "errors": [str(exc)]}
            backend_admission_integrity = bool(v35_integrity_report.get("valid"))
            render_v35_backend_evidence_panel(
                _section_header,
                artifact=backend_admission_artifact,
                live_probe=None,
                parent_v34_artifact=optimized_native_artifact,
                parent_v34_integrity=optimized_native_integrity,
                artifact_integrity=backend_admission_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v35_integrity_report.get("errors"):
                with st.expander("V3.5 artifact integrity errors", expanded=False):
                    st.code(
                        "\n".join(
                            str(item)
                            for item in v35_integrity_report.get("errors", [])
                        )
                    )
            if backend_admission_integrity and encoding is not None:
                encoding = dict(encoding)
                encoding.update(
                    {
                        "backend_admission_artifact_sha": (
                            backend_admission_artifact or {}
                        ).get("artifact_sha256"),
                        "backend_admission_decision": (
                            (backend_admission_artifact or {}).get("decisions") or {}
                        ).get("offline_backend_admission"),
                        "encoding_status": (
                            "V3.5 MODEL SCREEN REJECTED · BACKEND SNAPSHOT/ROUTING NOT RUN"
                        ),
                        "hardware_executable": False,
                    }
                )

            v36_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v36_spec: dict[str, Any] | None = None
            try:
                v36_spec = load_v36_spec()
                v36_artifact, v36_integrity_report = load_v36_artifact()
                live_parent_report = authenticate_v36_parent_chain(v36_spec)
                v36_errors = list(v36_integrity_report.get("errors") or [])
                if live_parent_report.get("valid") is not True:
                    v36_errors.extend(str(item) for item in live_parent_report.get("errors") or [])
                if (v36_artifact.get("parent_authentication") or {}).get("valid") is not True:
                    v36_errors.append("Sealed V3.6 parent-authentication state is not valid.")
                v36_integrity_report = {
                    **v36_integrity_report,
                    "errors": v36_errors,
                    "valid": not v36_errors,
                }
            except Exception as exc:
                v36_integrity_report = {"valid": False, "errors": [str(exc)]}
            v36_integrity = bool(v36_integrity_report.get("valid"))
            render_v36_algorithmic_reduction_panel(
                _section_header,
                artifact=v36_artifact,
                spec=v36_spec,
                artifact_integrity=v36_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v36_integrity_report.get("errors"):
                with st.expander("V3.6 artifact integrity errors", expanded=False):
                    st.code(
                        "\n".join(
                            str(item)
                            for item in v36_integrity_report.get("errors", [])
                        )
                    )
            if v36_integrity and encoding is not None:
                encoding = dict(encoding)
                encoding.update(
                    {
                        "v36_reduction_artifact_sha": (
                            v36_artifact or {}
                        ).get("artifact_sha256"),
                        "v36_rewrite_decision": "ARCHITECTURE_REWRITE_REQUIRED",
                        "encoding_status": (
                            "V3.6 ARCHITECTURE REWRITE REQUIRED · REVERSIBLE COMPILER BLOCKED"
                        ),
                        "hardware_executable": False,
                    }
                )

            v37_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v37_spec: dict[str, Any] | None = None
            try:
                v37_spec = load_v37_spec()
                v37_artifact, v37_integrity_report = load_v37_artifact()
                v37_parent_report = authenticate_v37_parent_chain()
                v37_errors = list(v37_integrity_report.get("errors") or [])
                if v37_parent_report.get("valid") is not True:
                    v37_errors.extend(
                        str(item) for item in v37_parent_report.get("errors") or []
                    )
                sealed_parent = (
                    ((v37_artifact or {}).get("parent") or {}).get("authentication")
                    or {}
                )
                if sealed_parent.get("valid") is not True:
                    v37_errors.append(
                        "Sealed V3.7 parent-authentication state is not valid."
                    )
                v37_integrity_report = {
                    **v37_integrity_report,
                    "errors": v37_errors,
                    "valid": not v37_errors,
                }
            except Exception as exc:
                v37_integrity_report = {"valid": False, "errors": [str(exc)]}
            v37_integrity = bool(v37_integrity_report.get("valid"))
            v37_state = render_v37_reversible_prototype_panel(
                _section_header,
                artifact=v37_artifact,
                spec=v37_spec,
                artifact_integrity=v37_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v37_integrity_report.get("errors"):
                with st.expander("V3.7 artifact integrity errors", expanded=False):
                    st.code(
                        "\n".join(
                            str(item)
                            for item in v37_integrity_report.get("errors", [])
                        )
                    )
            if v37_integrity:
                encoding = apply_v37_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v37_state,
                    artifact=v37_artifact,
                )

            v38_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v38_spec: dict[str, Any] | None = None
            try:
                v38_spec = load_v38_spec()
                v38_artifact, v38_integrity_report = load_v38_ui_artifact()
                sealed_parent = ((v38_artifact or {}).get("parent") or {}).get("authentication") or {}
                v38_errors = list(v38_integrity_report.get("errors") or [])
                if sealed_parent.get("valid") is not True:
                    v38_errors.append("Sealed V3.8 V3.7 parent-authentication state is not valid.")
                v38_integrity_report = {
                    **v38_integrity_report,
                    "errors": v38_errors,
                    "valid": not v38_errors,
                }
            except Exception as exc:
                v38_integrity_report = {"valid": False, "errors": [str(exc)]}
            v38_integrity = bool(v38_integrity_report.get("valid"))
            v38_state = render_v38_elementary_admission_panel(
                _section_header,
                artifact=v38_artifact,
                spec=v38_spec,
                artifact_integrity=v38_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v38_integrity_report.get("errors"):
                with st.expander("V3.8 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v38_integrity_report.get("errors", [])))
            if v38_integrity:
                encoding = apply_v38_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v38_state,
                    artifact=v38_artifact,
                )

            v39_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v39_spec: dict[str, Any] | None = None
            try:
                v39_spec = load_v39_spec()
                v39_artifact, v39_integrity_report = load_v39_ui_artifact()
                sealed_parent = ((v39_artifact or {}).get("parent") or {}).get("authentication") or {}
                v39_errors = list(v39_integrity_report.get("errors") or [])
                if sealed_parent.get("valid") is not True:
                    v39_errors.append("Sealed V3.9 V3.8→V3.1 parent-authentication state is not valid.")
                v39_integrity_report = {
                    **v39_integrity_report,
                    "errors": v39_errors,
                    "valid": not v39_errors,
                }
            except Exception as exc:
                v39_integrity_report = {"valid": False, "errors": [str(exc)]}
            v39_integrity = bool(v39_integrity_report.get("valid"))
            v39_state = render_v39_scalable_ir_panel(
                _section_header,
                artifact=v39_artifact,
                spec=v39_spec,
                artifact_integrity=v39_integrity,
                spec_integrity=v39_spec is not None,
                parent_integrity=bool(((v39_artifact or {}).get("parent") or {}).get("authentication", {}).get("valid")),
                key_prefix=f"{PREFIX}_p3",
            )
            if v39_integrity_report.get("errors"):
                with st.expander("V3.9 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v39_integrity_report.get("errors", [])))
            if v39_integrity:
                encoding = apply_v39_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v39_state,
                    artifact=v39_artifact,
                )

            v40_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v40_spec: dict[str, Any] | None = None
            v40_spec_integrity = False
            try:
                v40_spec = load_v40_spec()
                v40_spec_integrity = bool(
                    v40_spec.get("v40_spec_sha256") == EXPECTED_V40_SPEC_SHA256
                )
                v40_artifact, v40_integrity_report = load_v40_ui_artifact()
                sealed_parent = ((v40_artifact or {}).get("parent") or {}).get("authentication") or {}
                v40_errors = list(v40_integrity_report.get("errors") or [])
                if not v40_spec_integrity:
                    v40_errors.append("V4.0 specification identity is not the registered confirmatory specification.")
                if sealed_parent.get("valid") is not True:
                    v40_errors.append("Sealed V4.0 V3.9→V3.1 parent-authentication state is not valid.")
                v40_integrity_report = {
                    **v40_integrity_report,
                    "errors": v40_errors,
                    "valid": not v40_errors,
                }
            except Exception as exc:
                v40_integrity_report = {"valid": False, "errors": [str(exc)]}
            v40_integrity = bool(v40_integrity_report.get("valid"))
            v40_state = render_v40_connectivity_redesign_panel(
                _section_header,
                artifact=v40_artifact,
                spec=v40_spec,
                artifact_integrity=v40_integrity,
                spec_integrity=v40_spec_integrity,
                parent_integrity=bool(((v40_artifact or {}).get("parent") or {}).get("authentication", {}).get("valid")),
                key_prefix=f"{PREFIX}_p3",
            )
            if v40_integrity_report.get("errors"):
                with st.expander("V4.0 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v40_integrity_report.get("errors", [])))
            if v40_integrity:
                encoding = apply_v40_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v40_state,
                    artifact=v40_artifact,
                )

            v41_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v41_spec: dict[str, Any] | None = None
            v41_spec_integrity = False
            try:
                v41_spec = load_v41_spec()
                v41_spec_integrity = bool(
                    v41_spec.get("v41_spec_sha256") == EXPECTED_V41_SPEC_SHA256
                )
                v41_artifact, v41_integrity_report = load_v41_ui_artifact()
                sealed_parent = ((v41_artifact or {}).get("parent") or {}).get("authentication") or {}
                v41_errors = list(v41_integrity_report.get("errors") or [])
                if not v41_spec_integrity:
                    v41_errors.append("V4.1 specification identity is not the registered certified-bridge compiler specification.")
                if sealed_parent.get("valid") is not True:
                    v41_errors.append("Sealed V4.1 V4.0→V3.1 parent-authentication state is not valid.")
                v41_integrity_report = {
                    **v41_integrity_report,
                    "errors": list(dict.fromkeys(v41_errors)),
                    "valid": not v41_errors,
                }
            except Exception as exc:
                v41_integrity_report = {"valid": False, "errors": [str(exc)]}
            v41_integrity = bool(v41_integrity_report.get("valid"))
            v41_state = render_v41_certified_bridge_compiler_panel(
                _section_header,
                artifact=v41_artifact,
                spec=v41_spec,
                artifact_integrity=v41_integrity,
                spec_integrity=v41_spec_integrity,
                parent_integrity=bool(((v41_artifact or {}).get("parent") or {}).get("authentication", {}).get("valid")),
                key_prefix=f"{PREFIX}_p3",
            )
            if v41_integrity_report.get("errors"):
                with st.expander("V4.1 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v41_integrity_report.get("errors", [])))
            if v41_integrity:
                encoding = apply_v41_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v41_state,
                    artifact=v41_artifact,
                )

            v42_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v42_spec: dict[str, Any] | None = None
            v42_spec_integrity = False
            try:
                v42_spec = load_v42_spec()
                v42_spec_integrity = bool(
                    v42_spec.get("v42_spec_sha256") == EXPECTED_V42_SPEC_SHA256
                )
                v42_artifact, v42_integrity_report = load_v42_ui_artifact()
                sealed_parent = (v42_artifact or {}).get("parent") or {}
                v42_errors = list(v42_integrity_report.get("errors") or [])
                if not v42_spec_integrity:
                    v42_errors.append("V4.2 specification identity is not the registered coined-walk compiler specification.")
                if not v41_integrity:
                    v42_errors.append("The authenticated V4.1 UI parent state is unavailable.")
                if not (
                    sealed_parent.get("immutable_files_exact") is True
                    and sealed_parent.get("immutable_file_count") == 159
                ):
                    v42_errors.append("Sealed V4.2 does not bind the exact 159-path immutable V4.1 parent.")
                v42_integrity_report = {
                    **v42_integrity_report,
                    "errors": list(dict.fromkeys(v42_errors)),
                    "valid": not v42_errors,
                }
            except Exception as exc:
                v42_integrity_report = {"valid": False, "errors": [str(exc)]}
            v42_integrity = bool(v42_integrity_report.get("valid"))
            v42_state = render_v42_coined_walk_compiler_panel(
                _section_header,
                artifact=v42_artifact,
                spec=v42_spec,
                artifact_integrity=v42_integrity,
                spec_integrity=v42_spec_integrity,
                parent_integrity=v41_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v42_integrity_report.get("errors"):
                with st.expander("V4.2 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v42_integrity_report.get("errors", [])))
            if v42_integrity:
                encoding = apply_v42_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v42_state,
                    artifact=v42_artifact,
                )

            v43_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v43_spec: dict[str, Any] | None = None
            v43_spec_integrity = False
            try:
                v43_spec = load_v43_spec()
                v43_spec_integrity = bool(
                    v43_spec.get("v43_spec_sha256") == EXPECTED_V43_SPEC_SHA256
                )
                v43_artifact, v43_integrity_report = load_v43_ui_artifact()
                sealed_parent = (v43_artifact or {}).get("parent") or {}
                v43_errors = list(v43_integrity_report.get("errors") or [])
                if not v43_spec_integrity:
                    v43_errors.append("V4.3 specification identity is not the registered reversible-circuit materialization protocol.")
                if not v42_integrity:
                    v43_errors.append("The authenticated V4.2 UI parent state is unavailable.")
                if not (
                    sealed_parent.get("immutable_files_exact") is True
                    and sealed_parent.get("immutable_file_count") == 175
                ):
                    v43_errors.append("Sealed V4.3 does not bind the exact 175-path immutable V4.2 parent.")
                v43_integrity_report = {
                    **v43_integrity_report,
                    "errors": list(dict.fromkeys(v43_errors)),
                    "valid": not v43_errors,
                }
            except Exception as exc:
                v43_integrity_report = {"valid": False, "errors": [str(exc)]}
            v43_integrity = bool(v43_integrity_report.get("valid"))
            v43_state = render_v43_reversible_circuit_panel(
                _section_header,
                artifact=v43_artifact,
                spec=v43_spec,
                artifact_integrity=v43_integrity,
                spec_integrity=v43_spec_integrity,
                parent_integrity=v42_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v43_integrity_report.get("errors"):
                with st.expander("V4.3 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v43_integrity_report.get("errors", [])))
            if v43_integrity:
                encoding = apply_v43_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v43_state,
                    artifact=v43_artifact,
                )

            v44_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v44_spec: dict[str, Any] | None = None
            v44_snapshot: dict[str, Any] | None = None
            v44_toolchain: dict[str, Any] | None = None
            v44_spec_integrity = False
            v44_snapshot_integrity = False
            v44_toolchain_integrity = False
            v44_artifact_integrity = False
            try:
                v44_spec = load_v44_spec()
                v44_snapshot = load_v44_snapshot()
                v44_toolchain = load_v44_toolchain()
                v44_artifact, v44_integrity_report = load_v44_ui_artifact()
                v44_checks = v44_integrity_report.get("checks") or {}
                sealed_parent = (v44_artifact or {}).get("parent") or {}
                v44_errors = list(v44_integrity_report.get("errors") or [])
                v44_artifact_integrity = bool(
                    v44_checks.get("artifact_raw_identity") is True
                    and v44_checks.get("artifact_semantic_identity") is True
                )
                v44_spec_integrity = bool(
                    v44_checks.get("spec_raw_semantic_identity") is True
                    and v44_spec.get("v44_spec_sha256") == EXPECTED_V44_SPEC_SHA256
                )
                v44_snapshot_integrity = bool(
                    v44_checks.get("snapshot_raw_semantic_identity") is True
                    and v44_snapshot.get("snapshot_sha256") == EXPECTED_V44_SNAPSHOT_SHA256
                )
                v44_toolchain_integrity = bool(
                    v44_checks.get("toolchain_raw_semantic_identity") is True
                    and v44_toolchain.get("manifest_sha256") == EXPECTED_V44_TOOLCHAIN_SHA256
                )
                if not v43_integrity:
                    v44_errors.append("The authenticated V4.3 UI parent state is unavailable.")
                if not (
                    sealed_parent.get("immutable_files_exact") is True
                    and sealed_parent.get("immutable_file_count") == 191
                ):
                    v44_errors.append("Sealed V4.4 does not bind the exact 191-path immutable V4.3 parent.")
                v44_integrity_report = {
                    **v44_integrity_report,
                    "errors": list(dict.fromkeys(v44_errors)),
                    "valid": not v44_errors,
                }
            except Exception as exc:
                v44_integrity_report = {"valid": False, "errors": [str(exc)]}
            v44_integrity = bool(v44_integrity_report.get("valid"))
            v44_state = render_v44_named_backend_panel(
                _section_header,
                artifact=v44_artifact,
                spec=v44_spec,
                snapshot=v44_snapshot,
                toolchain=v44_toolchain,
                artifact_integrity=v44_artifact_integrity,
                spec_integrity=v44_spec_integrity,
                snapshot_integrity=v44_snapshot_integrity,
                toolchain_integrity=v44_toolchain_integrity,
                parent_integrity=v43_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v44_integrity_report.get("errors"):
                with st.expander("V4.4 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v44_integrity_report.get("errors", [])))
            if v44_integrity:
                encoding = apply_v44_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v44_state,
                    artifact=v44_artifact,
                )

            v45_integrity_report: dict[str, Any] = {"valid": False, "errors": []}
            v45_spec: dict[str, Any] | None = None
            v45_liveness: dict[str, Any] | None = None
            v45_artifact_integrity = False
            v45_spec_integrity = False
            v45_liveness_integrity = False
            v45_source_integrity = False
            v45_checker_integrity = False
            v45_parent_integrity = False
            try:
                v45_spec = load_v45_spec()
                supporting_spec, v45_liveness = load_v45_ui_supporting_evidence()
                v45_integrity_report = dict(v45_preflight_report)
                v45_evidence_valid = bool(
                    v45_integrity_report.get("valid") is True
                    and v45_integrity_report.get("check_count") == 28
                )
                v45_checks = v45_integrity_report.get("checks") or {}
                v45_errors = list(v45_integrity_report.get("errors") or [])
                v45_artifact_integrity = bool(
                    v45_checks.get("artifact_raw_identity") is True
                    and v45_checks.get("artifact_semantic_identity") is True
                )
                v45_spec_integrity = bool(
                    v45_checks.get("spec_raw_semantic_identity") is True
                    and v45_spec.get("v45_spec_sha256") == EXPECTED_V45_SPEC_SHA256
                    and supporting_spec == v45_spec
                )
                v45_liveness_integrity = bool(
                    v45_checks.get("liveness_raw_identity") is True
                    and v45_checks.get("liveness_semantic_identity") is True
                )
                v45_source_integrity = v45_checks.get("source_raw_identity") is True
                v45_checker_integrity = v45_checks.get("checker_raw_identity") is True
                v45_parent_integrity = bool(
                    v45_checks.get("v44_parent_and_209_immutable_paths") is True
                    and v45_checks.get("artifact_parent_crosslinks") is True
                    and v44_integrity
                )
                if not v44_integrity:
                    v45_errors.append("The authenticated V4.4 UI parent state is unavailable.")
                if not v45_parent_integrity:
                    v45_errors.append("Sealed V4.5 does not bind the exact authenticated 209-path immutable V4.4 parent.")
                v45_integrity_report = {
                    **v45_integrity_report,
                    "errors": list(dict.fromkeys(v45_errors)),
                    "valid": not v45_errors and all(
                        (
                            v45_artifact_integrity,
                            v45_spec_integrity,
                            v45_liveness_integrity,
                            v45_source_integrity,
                            v45_checker_integrity,
                            v45_parent_integrity,
                            v45_evidence_valid,
                        )
                    ),
                }
            except Exception as exc:
                v45_integrity_report = {"valid": False, "errors": [str(exc)]}
            v45_integrity = bool(v45_integrity_report.get("valid"))
            if v45_integrity:
                v45_state = render_v45_width_reduction_panel(
                    _section_header,
                    artifact=v45_artifact,
                    spec=v45_spec,
                    liveness=v45_liveness,
                    artifact_integrity=v45_artifact_integrity,
                    spec_integrity=v45_spec_integrity,
                    liveness_integrity=v45_liveness_integrity,
                    parent_integrity=v45_parent_integrity,
                    source_integrity=v45_source_integrity,
                    checker_integrity=v45_checker_integrity,
                    key_prefix=f"{PREFIX}_p3",
                )
            else:
                v45_state = {
                    "authenticated": False,
                    "decision": "MASKED_FAIL_CLOSED",
                    "hardware_executable": False,
                    "research_classification": "RESEARCH_ONLY",
                }
                _section_header(
                    "V4.5 · Proof-Carrying Width Reduction",
                    "AUTHENTICATION FAILED · SCIENTIFIC OUTCOMES MASKED",
                    "The complete sealed artifact, specification, source, checker, liveness certificate and exact V4.4 parent must authenticate before any V4.5 width, parity or CX result is displayed.",
                )
                st.error("V4.5 evidence authentication failed. All V4.5 scientific outcomes remain masked fail-closed.")
            if v45_integrity_report.get("errors"):
                with st.expander("V4.5 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v45_integrity_report.get("errors", [])))
            if v45_integrity:
                encoding = apply_v45_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v45_state,
                    artifact=v45_artifact,
                )

            v46_integrity_report: dict[str, Any] = dict(v46_preflight_report)
            v46_spec: dict[str, Any] | None = None
            try:
                v46_spec = load_v46_spec()
                v46_checks = v46_integrity_report.get("checks") or {}
                v46_errors = list(v46_integrity_report.get("errors") or [])
                if not v45_integrity:
                    v46_errors.append("The authenticated V4.5 UI parent state is unavailable.")
                if v46_spec.get("v46_spec_sha256") != EXPECTED_V46_SPEC_SHA256:
                    v46_errors.append("The V4.6 preregistration identity is invalid.")
                if not (
                    v46_checks.get("parent_227_immutable_paths") is True
                    and v46_checks.get("artifact_crosslinks") is True
                    and v46_checks.get("independent_checker_36_pass") is True
                ):
                    v46_errors.append("The V4.6 artifact does not bind the exact parent, references and independent checker.")
                v46_integrity_report = {
                    **v46_integrity_report,
                    "errors": list(dict.fromkeys(v46_errors)),
                    "valid": bool(
                        not v46_errors
                        and v45_integrity
                        and v46_preflight_report.get("valid") is True
                        and v46_preflight_report.get("check_count") == 30
                    ),
                }
            except Exception as exc:
                v46_integrity_report = {"valid": False, "errors": [str(exc)]}
            v46_integrity = bool(v46_integrity_report.get("valid"))
            if v47_preflight_valid and v46_integrity:
                # V4.6 stays authenticated as the exact parent but its six-tab
                # console is replaced by the six-tab V4.7 successor console.
                # This preserves the stable 12 outer + 6 active evidence tabs.
                v46_state = {
                    "authenticated": True,
                    "hardware_executable": False,
                    "research_classification": "RESEARCH_ONLY",
                }
            else:
                v46_state = render_v46_full_stream_routing_panel(
                    _section_header,
                    artifact=v46_artifact,
                    integrity=v46_integrity,
                    key_prefix=f"{PREFIX}_p3",
                )
            if v46_integrity_report.get("errors"):
                with st.expander("V4.6 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v46_integrity_report.get("errors", [])))
            if v46_integrity and not v47_preflight_valid:
                encoding = apply_v46_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v46_state,
                    artifact=v46_artifact,
                )

            v47_integrity_report: dict[str, Any] = dict(v47_preflight_report)
            try:
                v47_checks = v47_integrity_report.get("checks") or {}
                v47_errors = list(v47_integrity_report.get("errors") or [])
                if not v46_integrity:
                    v47_errors.append("The authenticated V4.6 UI parent state is unavailable.")
                if not (
                    v47_checks.get("v46_parent_authentication") is True
                    and v47_checks.get("artifact_optimizer_crosslink") is True
                    and v47_checks.get("artifact_checker_crosslink") is True
                    and v47_checks.get("independent_checker_51_pass") is True
                ):
                    v47_errors.append(
                        "The V4.7 artifact does not bind the exact V4.6 parent, optimizer and independent checker."
                    )
                v47_integrity_report = {
                    **v47_integrity_report,
                    "errors": list(dict.fromkeys(v47_errors)),
                    "valid": bool(
                        not v47_errors
                        and v46_integrity
                        and v47_preflight_report.get("valid") is True
                        and v47_preflight_report.get("check_count")
                        == EXPECTED_V47_UI_AUTH_CHECK_COUNT
                    ),
                }
            except Exception as exc:
                v47_integrity_report = {"valid": False, "errors": [str(exc)]}
            v47_integrity = bool(v47_integrity_report.get("valid"))
            if v48_preflight_valid and v47_integrity:
                # V4.7 remains the authenticated scientific parent, while its
                # six-tab console yields to the V4.8 successor console.
                v47_state = {
                    "authenticated": True,
                    "hardware_executable": False,
                    "research_classification": "RESEARCH_ONLY",
                }
            else:
                v47_state = render_v47_dated_properties_panel(
                    _section_header,
                    artifact=v47_artifact,
                    integrity=v47_integrity,
                    key_prefix=f"{PREFIX}_p3",
                )
            if v47_integrity_report.get("errors"):
                with st.expander("V4.7 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v47_integrity_report.get("errors", [])))
            if v47_integrity and not v48_preflight_valid:
                encoding = apply_v47_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v47_state,
                    artifact=v47_artifact,
                )

            v48_integrity_report: dict[str, Any] = dict(v48_preflight_report)
            try:
                v48_checks = v48_integrity_report.get("checks") or {}
                v48_errors = list(v48_integrity_report.get("errors") or [])
                if not v47_integrity:
                    v48_errors.append("The authenticated V4.7 UI parent state is unavailable.")
                if not (
                    v48_checks.get("parent_lineage") is True
                    and v48_checks.get("artifact_optimizer_crosslink") is True
                    and v48_checks.get("artifact_checker_crosslink") is True
                    and v48_checks.get("independent_checker_65") is True
                ):
                    v48_errors.append(
                        "The V4.8 artifact does not bind the exact V4.7 parent, optimizer and independent checker."
                    )
                v48_integrity_report = {
                    **v48_integrity_report,
                    "errors": list(dict.fromkeys(v48_errors)),
                    "valid": bool(
                        not v48_errors
                        and v47_integrity
                        and v48_preflight_report.get("valid") is True
                        and v48_preflight_report.get("check_count")
                        == EXPECTED_V48_UI_AUTH_CHECK_COUNT
                    ),
                }
            except Exception as exc:
                v48_integrity_report = {"valid": False, "errors": [str(exc)]}
            v48_integrity = bool(v48_integrity_report.get("valid"))
            if v49_preflight_valid and v48_integrity:
                # The authenticated V4.8 console yields to the compact terminal
                # V4.9 admission dossier while remaining its exact parent.
                v48_state = {
                    "authenticated": True,
                    "hardware_executable": False,
                    "research_classification": "RESEARCH_ONLY",
                }
            else:
                v48_state = render_v48_multi_snapshot_architecture_panel(
                    _section_header,
                    artifact=v48_artifact,
                    integrity=v48_integrity,
                    key_prefix=f"{PREFIX}_p3",
                )
            if v48_integrity_report.get("errors"):
                with st.expander("V4.8 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v48_integrity_report.get("errors", [])))
            if v48_integrity and not v49_preflight_valid:
                encoding = apply_v48_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v48_state,
                    artifact=v48_artifact,
                )

            v49_integrity_report: dict[str, Any] = dict(v49_preflight_report)
            try:
                v49_checks = v49_integrity_report.get("checks") or {}
                v49_errors = list(v49_integrity_report.get("errors") or [])
                if not v48_integrity:
                    v49_errors.append("The authenticated V4.8 UI parent state is unavailable.")
                if not (
                    v49_checks.get("artifact_raw") is True
                    and v49_checks.get("independent_checker") is True
                    and v49_checks.get("validation_report") is True
                    and v49_checks.get("boundary") is True
                ):
                    v49_errors.append(
                        "The V4.9 dossier does not bind its sealed artifact, independent checker, validation report and execution boundary."
                    )
                v49_integrity_report = {
                    **v49_integrity_report,
                    "errors": list(dict.fromkeys(v49_errors)),
                    "valid": bool(
                        not v49_errors
                        and v48_integrity
                        and v49_preflight_report.get("valid") is True
                        and v49_preflight_report.get("check_count")
                        == EXPECTED_V49_UI_AUTH_CHECK_COUNT
                    ),
                }
            except Exception as exc:
                v49_integrity_report = {"valid": False, "errors": [str(exc)]}
            v49_integrity = bool(v49_integrity_report.get("valid"))
            v49_state = render_v49_admission_panel(
                _section_header,
                artifact=v49_artifact,
                integrity=v49_integrity,
                key_prefix=f"{PREFIX}_p3",
            )
            if v49_integrity_report.get("errors"):
                with st.expander("V4.9 artifact integrity errors", expanded=False):
                    st.code("\n".join(str(item) for item in v49_integrity_report.get("errors", [])))
            if v49_integrity:
                encoding = apply_v49_encoding_state(
                    encoding,
                    regime=regime_sel,
                    state=v49_state,
                    artifact=v49_artifact,
                )
    else:
        st.info("No Phase-II gate-passing family is available yet. The encoding audit will activate automatically when a finalized 120/120 artifact opens the hardness gate.")

    is_bands_candidate = bool(
        selected_family
        and str(selected_family.get("Regime", "")).upper() == "BANDS"
    )

    if v49_integrity:
        provider_boundary = (
            "V4.9 is the terminal offline V4 admission dossier. The authentic cohort remains at one of three required "
            "epochs, while the frozen reference architecture remains above both strict necessary resource screens. "
            "Provider discovery is denied, V5 entry is closed, and credentials, network access, simulator work, backend "
            "runs and QPU jobs remain disabled."
        )
    elif v48_integrity:
        provider_boundary = (
            "V4.8 authenticates eight exact reduced-CX streams and replays them through the unchanged frozen BasicSwap "
            "routing oracle. Logical CX and routed CZ fall materially, but only one authentic historical snapshot epoch "
            "exists and every optimistic V4.7-comparable duration/error necessary screen still fails. Provider discovery, "
            "credentials, network access, simulator work and QPU jobs remain disabled."
        )
    elif v47_integrity:
        provider_boundary = (
            "V4.7 authenticates the exact V4.6 streams and evaluates them against a pinned historical 2025-02-26 "
            "FakeMarrakesh properties file. The fixed V4.6 architecture fails both deliberately optimistic historical "
            "stress screens; one preregistered fault-excluded candidate is reported only as research evidence. Modeled "
            "integer-dt duration is not runtime and additive reported-error mass is not fidelity. Provider discovery, "
            "credentials, network access, simulator work and QPU jobs remain disabled."
        )
    elif v46_integrity:
        provider_boundary = (
            "V4.6 authenticates every one of the 48,647,214 V4.5 instructions, 24,180 ordered Qiskit paths and "
            "476,876,458 exactly reconstructible native instructions. All eight BasicSwap routes pass with zero "
            "ISA/coupling violations; the worst seed has 15,527,797 CZ and 24,893,376 structural layers, below "
            "the V4.5-preregistered 250M limits. The snapshot is dated and offline; provider discovery, credentials, "
            "network access, calibrated performance and QPU jobs remain disabled."
        )
    elif v45_integrity:
        provider_boundary = (
            "V4.5 authenticates the V4.4 predecessor and eight proof-carrying streams whose logical widths are "
            "133–145 against the pinned 156-qubit capacity, with a minimum +11 margin. Exact registered-promise "
            "SELECT traces and all eight provider-neutral CX ledgers pass; the worst stream is 2,499,790 CX with "
            "+210 remaining. Full FakeMarrakesh reconstruction, translation and routing are NOT_RUN_IN_V4_5. "
            "Provider SDK use, credential reads, provider/network calls and QPU jobs remain zero and disabled."
        )
    elif v44_integrity:
        provider_boundary = (
            "V4.4 authenticates a pinned offline FakeMarrakesh target with 156 qubits and rejects all eight frozen "
            "327–339-qubit V4.3 workloads before full transpilation. The persistent DATA, REMOVE_COIN, ADD_COIN and "
            "TARGET registers already require 160 qubits before scratch. Five bounded canaries pass the frozen Qiskit "
            "ISA/routing mechanics in two identical clean-process replays, but cannot override the capacity rejection. "
            "Provider discovery, credentials, network access and QPU jobs remain disabled."
        )
    elif v43_integrity:
        provider_boundary = (
            "V4.3 authenticates 21,925,902 elementary instructions across eight deterministic streams. The maximum "
            "is 1,158,046 CX against 2,500,000, with a +1,341,954 minimum margin and a 339-qubit recycled-workspace "
            "bound. Independent reversible controls pass only on the registered promise subspace; the off-promise "
            "cleanup counterexample is retained. Named-backend discovery, credentials, transpilation, routing and QPU "
            "work remain disabled."
        )
    elif v42_integrity:
        provider_boundary = (
            "V4.2 authenticates connected joint promise support and passes the unchanged 2,500,000-CNOT selected-model "
            "screen on all eight frozen seeds (maximum 1,135,430; minimum margin +1,364,570). This admits the "
            "provider-neutral research generator only. Circuit materialization and reversible simulation are the next "
            "falsifiable gate, so credentials, discovery, transpilation and QPU work remain disabled."
        )
    elif v41_integrity:
        provider_boundary = (
            "V4.1 certifies augmented one-plus-two-swap connectivity on all eight frozen seeds, while both registered "
            "resource candidates exceed the immutable 2,500,000-CNOT gate: R1 reaches 15,256,056 and R2 reaches "
            "15,663,936. Provider discovery remains fail-closed for BANDS; no credential, backend, transpilation or "
            "QPU result can override the resource rejection."
        )
    elif v40_integrity:
        provider_boundary = (
            "V4.0 certifies that the complete frozen one-swap feasible graph is disconnected and preserves the "
            "independent V3.9 resource rejection. V4.1 is unavailable or unauthenticated, so provider discovery "
            "remains fail-closed for BANDS and no successor outcome is inferred."
        )
    else:
        provider_boundary = (
            "The latest BANDS evidence chain is absent or invalid. Provider discovery, credentials, backend "
            "selection, transpilation and QPU execution remain fail-closed."
        )
    _section_header(
        "QPU Provider & SDK Readiness",
        "SDK · AUTHENTICATION · BACKEND · CALIBRATION",
        provider_boundary,
    )
    inventory = qpu_sdk_inventory()
    st.dataframe(inventory, width="stretch", hide_index=True)
    fp = qpu_runtime_fingerprint()
    st.caption(f"Runtime: Python {fp.get('python')} · {fp.get('platform')} · machine={fp.get('machine')}")

    if is_bands_candidate:
        # A stale session must not retain credentials, provider objects, probes or
        # prior seals after the BANDS lane becomes fail-closed.
        for blocked_key in (
            "ibm_token",
            "ibm_instance",
            "saved_account",
            "ibm_result",
            "backend",
            "probe",
            "sealed",
        ):
            st.session_state.pop(f"{PREFIX}_p3_{blocked_key}", None)
    with st.expander("Legacy/future IBM Quantum Compute connection · outside the V4.8 evidence boundary", expanded=False):
        token = st.text_input("IBM Quantum API key · session only", value="", type="password", key=f"{PREFIX}_p3_ibm_token", disabled=is_bands_candidate)
        instance = st.text_input("IBM instance / CRN · optional", value="", key=f"{PREFIX}_p3_ibm_instance", disabled=is_bands_candidate)
        saved_ok = st.checkbox("Allow previously saved IBM account credentials", value=True, key=f"{PREFIX}_p3_saved_account", disabled=is_bands_candidate)
        if st.button("Discover accessible IBM QPUs", key=f"{PREFIX}_p3_discover_ibm", disabled=is_bands_candidate):
            with st.spinner("Querying IBM Quantum Compute backends…"):
                result = qpu_discover_ibm_backends(token=token or None, instance=instance or None, saved_account_ok=saved_ok)
            st.session_state[f"{PREFIX}_p3_ibm_result"] = result
        ibm_result = None if is_bands_candidate else st.session_state.get(f"{PREFIX}_p3_ibm_result")
        if isinstance(ibm_result, dict):
            if not ibm_result.get("available"):
                st.error(str(ibm_result.get("reason", "IBM backend discovery unavailable.")))
            else:
                backend_table = ibm_result.get("backends")
                if isinstance(backend_table, pd.DataFrame) and not backend_table.empty:
                    st.dataframe(backend_table, width="stretch", hide_index=True)
                    names = backend_table["backend_name"].astype(str).tolist()
                    st.selectbox("Hardware backend", names, key=f"{PREFIX}_p3_backend")

    ibm_result = None if is_bands_candidate else st.session_state.get(f"{PREFIX}_p3_ibm_result")
    backend_snapshot = None
    backend_obj = None
    if isinstance(ibm_result, dict) and ibm_result.get("available"):
        selected_backend_name = st.session_state.get(f"{PREFIX}_p3_backend")
        backend_snapshot = (ibm_result.get("snapshots") or {}).get(selected_backend_name)
        backend_obj = (ibm_result.get("backend_objects") or {}).get(selected_backend_name)

    if encoding:
        width_screen = qpu_backend_capacity(encoding, backend_snapshot)
        if is_bands_candidate and (v48_integrity or v47_integrity or v46_integrity or v45_integrity or v44_integrity or v43_integrity or v42_integrity or v41_integrity or optimized_native_integrity or algorithmic_integrity):
            guarded_artifact = (
                optimized_native_artifact
                if optimized_native_integrity
                else algorithmic_artifact
            )
            if v48_integrity:
                v48_aggregate = (v48_artifact or {}).get("aggregate") or {}
                required_qubits = int(v48_aggregate.get("maximum_logical_qubits", 145) or 145)
                capacity_reason = (
                    "V4.8 preserves the authenticated 133–145 logical-qubit envelope while replacing only controlled "
                    "constant addition. All eight exact streams route with zero ISA/coupling violations and substantially "
                    "lower CX/CZ counts. This remains one-snapshot historical structural evidence; the deliberately "
                    "optimistic duration and reported-error necessary screens fail on all eight seeds."
                )
                capacity_status = "ARCHITECTURE REDUCED · MULTI-SNAPSHOT BLOCKED · HARDWARE BLOCKED"
            elif v47_integrity:
                v47_aggregate = (v47_artifact or {}).get("aggregate") or {}
                required_qubits = 145
                capacity_reason = (
                    "V4.7 retains the exact V4.6 logical widths (133–145) and evaluates the fixed routes plus one "
                    "preregistered candidate over the 153-qubit healthy component remaining after exclusion of 13 "
                    "undirected links with reported CZ error equal to one. Capacity therefore remains an offline "
                    "historical-model fact with at least +8 qubits, not current backend admission. The fixed "
                    "architecture fails both optimistic stress screens and hardware execution remains blocked."
                )
                capacity_status = "HISTORICAL 153Q COMPONENT · ARCHITECTURE SCREEN FAIL · HARDWARE BLOCKED"
            elif v46_integrity:
                v46_aggregate = (v46_artifact or {}).get("aggregate") or {}
                required_qubits = int(v46_aggregate.get("maximum_logical_qubits", 145) or 145)
                capacity_reason = (
                    "V4.6 routes all eight authenticated 133–145-qubit streams over the pinned offline "
                    "FakeMarrakesh 156-qubit topology. Every input manifest matches V4.5, every final layout is "
                    "sealed, and ISA/coupling violations are zero. The worst seed has 15,527,797 native CZ and "
                    "24,893,376 ASAP structural layers. This passes the inherited offline gate but remains outside "
                    "current calibration, duration, fidelity, optimization and hardware-execution evidence."
                )
                capacity_status = "ROUTED STRUCTURAL PASS · HARDWARE BLOCKED"
            elif v45_integrity:
                v45_aggregate = (v45_artifact or {}).get("aggregate") or {}
                required_qubits = int(v45_aggregate.get("maximum_logical_qubits", 145) or 145)
                capacity_reason = (
                    "V4.5 authenticates eight proof-carrying 133–145-qubit streams against the pinned 156-qubit "
                    "logical-capacity gate; every seed fits and the minimum margin is +11. Every materialized "
                    "provider-neutral stream also passes the 2,500,000-CX gate; the worst is 2,499,790 with +210. "
                    "Full FakeMarrakesh reconstruction, translation and routing remain NOT_RUN_IN_V4_5, so this "
                    "width admission is not routed-hardware capacity, calibration, performance or execution evidence."
                )
                capacity_status = "WIDTH PASS · V4.5 ROUTING NOT RUN"
            elif v44_integrity:
                v44_capacity = (v44_artifact or {}).get("capacity_precheck") or {}
                required_qubits = int(v44_capacity.get("maximum_logical_qubits", 339) or 339)
                capacity_reason = (
                    "V4.4 binds the frozen V4.3 workloads to the pinned offline FakeMarrakesh 156-qubit target. "
                    "All eight 327–339-qubit workloads are rejected before full transpilation and routing; the worst "
                    "deficit is 183 qubits, and the persistent register floor is already 160. Five bounded canaries "
                    "validate only the pinned Qiskit target mechanics. This is not current calibration or hardware evidence."
                )
                capacity_status = "REJECTED · V4.4 FAKEMARRAKESH 156Q PRECHECK"
            elif v43_integrity:
                v43_aggregate = (v43_artifact or {}).get("aggregate") or {}
                required_qubits = int(
                    v43_aggregate.get("maximum_logical_qubits_with_recycled_workspace", 0)
                    or (encoding or {}).get("logical_qubits_min", 0)
                    or 0
                )
                capacity_reason = (
                    "V4.3 materializes all eight provider-neutral elementary streams: 1,158,046 maximum CX versus "
                    "2,500,000 and +1,341,954 minimum margin, with a 339-qubit recycled-workspace bound. The result is "
                    "not a physical-backend capacity or performance result: no named backend was selected and native "
                    "lowering, coupling-map routing, calibration, noise and hardware execution remain unrun."
                )
                capacity_status = "PASSED MATERIALIZATION · BLOCKED NAMED BACKEND"
            elif v42_integrity:
                resource_seed_rows = ((v42_artifact or {}).get("resource_evidence") or {}).get("seed_rows") or []
                required_qubits = max(
                    (
                        int(row.get("logical_qubits_with_recycled_workspace", 0) or 0)
                        for row in resource_seed_rows
                    ),
                    default=int((encoding or {}).get("logical_qubits_min", 0) or 0),
                )
                capacity_reason = (
                    "V4.2 passes the provider-neutral selected-model resource screen on all eight frozen seeds: "
                    "1,135,430 maximum CNOT versus 2,500,000 and +1,364,570 minimum margin, with a 331 logical-qubit "
                    "recycled-workspace bound. This is not a physical-backend capacity result: circuit materialization, "
                    "native lowering, routing and hardware execution remain unrun."
                )
                capacity_status = "PASSED RESOURCE · BLOCKED CIRCUIT MATERIALIZATION"
            elif v41_integrity:
                resource_seed_rows = ((v41_artifact or {}).get("resource_evidence") or {}).get("seed_rows") or []
                required_qubits = max(
                    (
                        int((row.get("r2") or {}).get("logical_qubits_with_clean_decomposition_ancillas", 0) or 0)
                        for row in resource_seed_rows
                    ),
                    default=int((encoding or {}).get("logical_qubits_min", 0) or 0),
                )
                capacity_reason = (
                    "V4.1 authenticates 58,725 exact incident two-swap audits and three deterministic bridges, "
                    "certifying augmented one-plus-two-swap connectivity across all eight frozen seeds. Resource "
                    "admission nevertheless fails: R1 reaches 15,256,056 selected-model CNOT and R2 reaches "
                    "15,663,936 versus the immutable 2,500,000 limit. Cache preparation is reported separately "
                    "and excluded from those mixer numerators; no backend work is authorized."
                )
                capacity_status = "REJECTED · V4.1 R1/R2 CNOT BUDGET"
            elif v40_integrity:
                required_qubits = (
                    max(
                        int((row.get("resources") or {}).get("logical_qubits_with_clean_decomposition_ancillas", 0) or 0)
                        for row in (v39_artifact or {}).get("seed_rows", [])
                    )
                    if v39_integrity and (v39_artifact or {}).get("seed_rows")
                    else int((encoding or {}).get("logical_qubits_min", 0) or 0)
                )
                capacity_reason = (
                    "V4.0 exhaustively certifies that the frozen one-out/one-in feasible state graph is disconnected: "
                    "seeds 2207 and 7703 contain three exact feasible isolated portfolios, each closed against all 300 swaps. "
                    "Independently, V3.9 remains rejected at 781,332,180 maximum selected-model CNOT versus the preregistered "
                    "2,500,000 limit. V4.1 is preregistered but not evaluated; no backend work is authorized."
                )
                capacity_status = "REJECTED · V4.0 CONNECTIVITY + V3.9 RESOURCE"
            elif v39_integrity:
                required_qubits = max(
                    int((row.get("resources") or {}).get("logical_qubits_with_clean_decomposition_ancillas", 0) or 0)
                    for row in (v39_artifact or {}).get("seed_rows", [])
                )
                capacity_reason = (
                    "V3.9 authenticates the scalable N=40 reversible IR on all eight frozen seeds, "
                    "then rejects the frozen architecture at the selected-model resource screen: "
                    "781,332,180 maximum CNOT versus the preregistered 2,500,000 limit. "
                    "Complete feasible-graph connectivity remains indeterminate and no backend work is authorized."
                )
                capacity_status = "REJECTED · V3.9 SELECTED-MODEL RESOURCE SCREEN"
            else:
                required_qubits = (
                    (guarded_artifact or {})
                    .get("resource_envelopes", {})
                    .get("ledgers", {})
                    .get(
                        f"{PROFILE_DUAL_GUARD}::{TOPOLOGY_COMPLETE}", {}
                    )
                    .get("maxima", {})
                    .get("logical_qubits_sequential_reuse", 0)
                )
                capacity_reason = (
                    "V3.8 proves an exact 3,632-CNOT elementary lowering only on the registered "
                    "N=4, K=2 fixture. The N=40 reversible IR, eight-seed coherent equivalence, "
                    "selected-model ledger and 2.5M budget screen are not built or not evaluated. "
                    "The inherited V3.6 floor still describes only the frozen V3.4 architecture."
                )
                capacity_status = (
                    "BLOCKED · V3.8 N40 REVERSIBLE-IR GATE"
                    if v38_integrity
                    else "BLOCKED · V3.7 N40 / ELEMENTARY LEDGER GATES"
                    if v37_integrity
                    else "BLOCKED · V3.6 REVERSIBLE COMPILER GATE"
                    if v36_integrity
                    else "REJECTED · V3.5 MODEL SCREEN"
                    if backend_admission_integrity
                    else "NOT EVALUATED · V3.4 ELEMENTARY IR UNROUTED"
                    if optimized_native_integrity
                    else "NOT EVALUATED · V3.3 MIXER UNROUTED"
                )
            capacity = {
                "backend_qubits": 156 if (v48_integrity or v47_integrity or v46_integrity or v45_integrity or v44_integrity) else width_screen.get("backend_qubits", 0),
                "capacity_ok": False,
                "reason": capacity_reason,
                "required_logical_qubits_min": required_qubits,
                "status": capacity_status,
            }
        else:
            capacity = width_screen
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Guarded-mixer capacity" if is_bands_candidate else "Backend capacity",
            str(capacity.get("status")),
        )
        c2.metric("Logical IR qubits", int(capacity.get("required_logical_qubits_min", encoding.get("logical_qubits_min", 0)) or 0))
        c3.metric("Backend qubits", int(capacity.get("backend_qubits", 0) or 0))
        st.caption(str(capacity.get("reason", "")))
        if gate_compiler_integrity and not algorithmic_integrity:
            st.caption(
                "Provider-neutral exact-K reference width only; physical/routed qubit requirements remain unknown until a named backend decomposition and routing pass is frozen."
            )
    else:
        capacity = {"capacity_ok": False, "status": "WAITING"}

    probe = None if is_bands_candidate else st.session_state.get(f"{PREFIX}_p3_probe")
    if is_bands_candidate:
        if v48_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.8 BANDS certificate and is disabled. "
                "V4.8 materializes eight exact control-loaded-adder streams and replays the unchanged frozen BasicSwap "
                "oracle, reducing aggregate CX and CZ. Multi-snapshot robustness is not evaluable from the single "
                "authentic epoch, both optimistic hardware screens still fail, and all live-provider paths remain blocked."
            )
        elif v47_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.7 BANDS certificate and is disabled. "
                "V4.7 replays the exact eight V4.6 streams with dated property-conditioned schedules, evaluates one "
                "preregistered fault-excluded candidate and retains an architecture-level rejection under deliberately "
                "optimistic lower bounds. These are historical offline diagnostics; current calibration, provider "
                "discovery, performance inference and execution remain blocked."
            )
        elif v46_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.6 BANDS certificate and is disabled. "
                "V4.6 already commits every full stream to the pinned offline FakeMarrakesh topology: 8/8 structural "
                "and inherited resource gates pass with zero ISA/coupling violations. Provider discovery, current "
                "calibration, duration/error feasibility, performance inference and hardware execution remain blocked."
            )
        elif v45_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.5 BANDS certificate and is disabled. "
                "All eight exact-promise streams pass the logical-width and provider-neutral CX gates, but their "
                "full FakeMarrakesh reconstruction, translation and routing were not run in V4.5. Provider discovery, "
                "live calibration, performance inference and hardware execution remain blocked."
            )
        elif v44_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.4 BANDS certificate and is disabled. "
                "V4.4 uses a pinned offline FakeMarrakesh target: all eight full workloads fail the 156-qubit capacity "
                "gate before routing. The five successful canaries validate only the fixed translation/routing mechanics; "
                "provider discovery, live calibration and hardware execution remain blocked."
            )
        elif v43_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.3 BANDS certificate and is disabled. "
                "All eight backend-agnostic elementary streams and the finite promise-space controls pass, while the "
                "off-promise cleanup witness remains rejected. A named-backend zero-job transpilation and routing "
                "protocol is the next gate; provider discovery and hardware execution remain blocked."
            )
        elif v42_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.2 BANDS certificate and is disabled. "
                "The joint one-hot-coin/data support and selected-model resource screen both pass across all eight "
                "frozen seeds, but the provider-neutral circuit has not yet been materialized or reversibly simulated. "
                "Provider discovery, transpilation and hardware execution therefore remain blocked."
            )
        elif v41_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is outside the V4.1 BANDS certificate and is disabled. "
                "Augmented one-plus-two-swap connectivity is certified PASS across all eight seeds, but R1 and R2 "
                "both exceed the frozen 2.5M-CNOT gate (15,256,056 and 15,663,936 respectively). Provider discovery, "
                "transpilation and hardware execution therefore remain blocked."
            )
        elif v40_integrity:
            st.info(
                "The legacy BASE/PAIRWISE topology probe is not applicable to the V4.0 BANDS decision and is disabled. "
                "The complete frozen one-swap graph is disconnected, the V3.9 resource architecture is rejected, and "
                "V4.1 is absent or unauthenticated; all successor and backend claims remain fail-closed."
            )
        else:
            st.info(
                "The BANDS evidence chain is incomplete or invalid. Legacy topology probes cannot substitute for the "
                "missing exact certificates, so provider discovery, transpilation and hardware work remain blocked."
            )
    elif encoding and backend_obj is not None and not str(encoding.get("encoding_status", "")).startswith("BLOCKED"):
        p_probe = st.selectbox("Topology probe depth p", [1, 2, 3], index=0, key=f"{PREFIX}_p3_probe_p")
        if st.button("Transpile topology/depth probe · no execution", key=f"{PREFIX}_p3_transpile"):
            with st.spinner("Transpiling engineering probe to the selected backend topology…"):
                probe = qpu_transpile_probe(backend_obj, int(selected_family["N"]), str(selected_family["Regime"]), 1103, p=int(p_probe), optimization_level=3)
            st.session_state[f"{PREFIX}_p3_probe"] = probe
    if isinstance(probe, dict):
        if probe.get("available"):
            st.markdown("**Transpilation probe — topology/resource diagnostic only**")
            st.json({k: v for k, v in probe.items() if k != "count_ops"})
            st.dataframe(pd.DataFrame([{"Operation": k, "Count": v} for k, v in (probe.get("count_ops") or {}).items()]), width="stretch", hide_index=True)
        elif probe:
            st.warning(str(probe.get("reason")))

    if v48_integrity:
        hardware_contract_path = "V4.8 EXACT ARCHITECTURE REDUCTION → 8/8 ROUTES REDUCED → ONE AUTHENTIC EPOCH → OPTIMISTIC SCREENS FAIL → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.8 proves an exact control-loaded constant-adder substitution on 28,240 computational-basis cases and "
            "materializes all eight full streams. Aggregate logical CX falls from 19,251,104 to 6,474,096 and frozen-"
            "BasicSwap CZ from 119,029,964 to 59,565,732. This is offline architecture evidence only: a single dated "
            "snapshot cannot establish multi-epoch robustness, both optimistic historical necessary screens fail on all "
            "seeds, and no provider, credential, network, simulator, backend or QPU operation is authorized."
        )
    elif v47_integrity:
        hardware_contract_path = "V4.7 EXACT V4.6 ROUTES → DATED PROPERTIES REPLAY → OPTIMISTIC ARCHITECTURE SCREENS FAIL → CANDIDATE RESEARCH ONLY → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.7 authenticates the exact V4.6 route commitments, replays native macros with integer-dt durations and "
            "audits additive reported-error mass from one pinned historical properties file. The fixed architecture "
            "fails both deliberately optimistic necessary-condition screens on all eight seeds. The sole preregistered "
            "fault-excluded candidate is a research comparison without a global-optimality or current-hardware claim. "
            "No provider, credential, network, simulator, backend or QPU operation is authorized."
        )
    elif v46_integrity:
        hardware_contract_path = "V4.6 FULL STREAMS RECONSTRUCTED → 8/8 BASICSWAP ROUTES PASS → 119,029,964 CZ TOTAL → CURRENT CALIBRATION NOT TESTED → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.6 passes the exact offline structural and V4.5-preregistered resource gates on all eight streams. "
            "The maximum width is 145, the maximum native CZ is 15,527,797 and the maximum ASAP structural depth "
            "is 24,893,376. The target is a dated fake-backend snapshot, the compact native IR is not a submitted "
            "circuit, and no calibrated duration, error, fidelity, optimization, provider or QPU conclusion exists."
        )
    elif v45_integrity:
        hardware_contract_path = "V4.5 WIDTH + PROMISE PARITY PASS → 8/8 CX PASS → FULL FAKEMARRAKESH ROUTING NOT RUN → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.5 admits the redesigned 133–145-qubit allocation to one separately preregistered offline backend "
            "gate. The maximum width is 145 with +11 logical qubits remaining; the worst provider-neutral stream is "
            "2,499,790 CX with +210 remaining. Full reconstruction, translation, layout and routing on FakeMarrakesh "
            "are NOT_RUN_IN_V4_5, so no native CZ, routed depth, calibration, performance, provider or QPU conclusion exists."
        )
    elif v44_integrity:
        hardware_contract_path = "V4.4 OFFLINE TARGET AUTHENTICATED → 156Q CAPACITY REJECTED → FULL ROUTING NOT RUN → CANARIES PASS → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.4 proves that the current V4.3 allocation cannot fit the pinned offline FakeMarrakesh target: all "
            "eight workloads require 327–339 logical qubits and the persistent floor alone is 160. Full-workload "
            "transpilation, routing, native counts and depth are NOT_RUN_CAPACITY_PRECHECK_REJECTED. Five bounded "
            "canaries pass twice deterministically, but provide no calibration, performance, provider or QPU evidence."
        )
    elif v43_integrity:
        hardware_contract_path = "V4.3 CIRCUIT MATERIALIZED → PROMISE SIMULATION PASS → OFF-PROMISE WITNESS REJECTED → NAMED BACKEND NOT RUN → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.3 admits a deterministic provider-neutral circuit IR only. The eight full streams contain 21,925,902 "
            "elementary instructions; the maximum is 1,158,046 CX and 339 logical qubits under registered workspace "
            "reuse. This is not backend-native evidence. A named backend, transpilation, routing, calibration, noise, "
            "optimization performance and QPU jobs remain unauthorized."
        )
    elif v42_integrity:
        hardware_contract_path = "V4.2 JOINT SUPPORT PASS → SELECTED-MODEL RESOURCE PASS → CIRCUIT NOT RUN → BACKEND NOT RUN → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "V4.2 admits the indexed coined-walk generator only as provider-neutral research architecture. All 780 "
            "exchange positions and the three V4.1 bridges are retained; the maximum selected-model numerator is "
            "1,135,430 CNOT with a 331 logical-qubit bound. A concrete circuit, reversible simulation, native lowering, "
            "routing, calibration and hardware jobs are still unauthorized."
        )
    elif v41_integrity:
        hardware_contract_path = "V4.1 AUGMENTED CONNECTIVITY PASS → R1/R2 RESOURCE BUDGET REJECTED → BACKEND NOT RUN → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "The legacy builder remains visible for continuity. V4.1 repairs the V4.0 one-swap connectivity failure "
            "with three certified two-swap bridges, but this does not admit production: R1 reaches 15,256,056 CNOT "
            "and R2 reaches 15,663,936 against the 2,500,000 selected-model gate. Cache preparation remains separately "
            "reported; provider discovery, backend selection, transpilation and hardware jobs are unauthorized."
        )
    elif v40_integrity:
        hardware_contract_path = "V4.0 GLOBAL CONNECTIVITY DISCONNECTED → V3.9 RESOURCE REJECTED → V4.1 UNAUTHENTICATED → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "The legacy builder remains visible for continuity, but V4.0 rejects the complete frozen one-swap mixer "
            "and V3.9 rejects the prior resource architecture. No V4.1 successor result is admitted without its exact "
            "sealed identity; provider discovery, backend selection, transpilation and hardware jobs remain unauthorized."
        )
    else:
        hardware_contract_path = "EVIDENCE CHAIN INVALID → BACKEND NOT RUN → HARDWARE BLOCKED"
        hardware_contract_boundary = (
            "The BANDS evidence chain is incomplete or invalid. The legacy builder cannot bypass missing scientific "
            "proofs; provider discovery, backend selection, transpilation and hardware jobs remain unauthorized."
        )
    _section_header(
        "Phase-III Hardware Contract Builder",
        hardware_contract_path,
        hardware_contract_boundary,
    )
    shots = st.selectbox("Proposed shots per circuit", [1024, 2048, 4096, 8192], index=2, key=f"{PREFIX}_p3_shots")
    repeats = st.selectbox("Proposed independent hardware repeats", [10, 20, 30, 50], index=2, key=f"{PREFIX}_p3_repeats")
    depth_schedule = (1, 2, 3)
    draft = qpu_protocol_draft(gate, selected_family, backend_snapshot, encoding, depth_schedule=depth_schedule, shots_per_circuit=int(shots), hardware_repeats=int(repeats))
    st.json(draft)
    st.download_button("Download QPU preparation specification", data=json.dumps(qpu_preparation_spec(), indent=2, sort_keys=True), file_name="PHASE_III_QPU_PREPARATION_SPEC_V1.json", mime="application/json", key=f"{PREFIX}_p3_download_prep")

    seal_ready = bool(gate_ready and selected_family and backend_snapshot and encoding and capacity.get("capacity_ok") and not str(encoding.get("encoding_status", "")).startswith("BLOCKED") and encoding.get("hardware_executable", True) is not False and (not is_bands_candidate or algorithmic_hardware_eligible))
    if not gate_ready:
        seal_reason = "Phase-II 120/120 final HARDNESS GATE PASSED artifact is required."
    elif not selected_family:
        seal_reason = "No completed gate-passing family selected."
    elif not encoding or str(encoding.get("encoding_status", "")).startswith("BLOCKED"):
        seal_reason = "Equal-objective encoding is not executable for the selected regime."
    elif encoding.get("hardware_executable") is False:
        if is_bands_candidate and v48_integrity:
            seal_reason = "V4.8 authenticates the exact V4.7 parent, preregistered control-loaded adder, eight materialized logical streams, unchanged frozen BasicSwap oracle and 28,240-case equivalence evidence. CX and routed CZ are materially reduced, but only one authentic dated snapshot exists and both deliberately optimistic necessary screens still fail on every seed. Provider, network, simulator and QPU calls remain zero. Hardware execution stays false pending two additional authentic epochs and a deeper direct-CX reduction."
        elif is_bands_candidate and v47_integrity:
            seal_reason = "V4.7 authenticates the exact V4.6 parent, pinned 2025-02-26 FakeMarrakesh properties, normalized property oracle, duration/error model and fault-excluded path oracle. All eight exact streams are replayed and the single preregistered candidate is reported only within that frozen historical model. The fixed architecture fails both optimistic stress screens; modeled makespan is not runtime, reported-error mass is not fidelity, and provider, network, simulator and QPU calls remain zero. Hardware execution stays false pending multi-snapshot robustness and architecture-level CZ reduction."
        elif is_bands_candidate and v46_integrity:
            seal_reason = "V4.6 authenticates the exact V4.5 parent and reconstructs all 48,647,214 input instructions across eight full streams. BasicSwap routing over the pinned FakeMarrakesh snapshot passes with zero ISA/coupling violations; the worst seed uses 15,527,797 native CZ and 24,893,376 structural layers, below the inherited 250M limits. This remains an offline compact native IR against dated structural data: calibration, duration/error feasibility, optimization performance, provider work and QPU jobs are untested or zero, so hardware execution stays false."
        elif is_bands_candidate and v45_integrity:
            seal_reason = "V4.5 authenticates the exact V4.4 parent, the 133–145-qubit proof-carrying redesign, explicit phase-local liveness, exact registered-promise SELECT parity and eight provider-neutral CX budget passes. The maximum width is 145 with +11 remaining; the worst stream is 2,499,790 CX with +210 remaining. Full FakeMarrakesh reconstruction, transpilation and routing are NOT_RUN_IN_V4_5; provider SDK use, credential reads, provider/network calls and QPU jobs remain zero, and hardware execution stays false."
        elif is_bands_candidate and v44_integrity:
            seal_reason = "V4.4 authenticates the offline FakeMarrakesh 156-qubit target and rejects all eight 327–339-qubit V4.3 workloads at the mandatory capacity precheck. The persistent DATA + REMOVE_COIN + ADD_COIN + TARGET floor is 160 before scratch. Five bounded canaries pass two identical clean-process Qiskit replays, while the 157-qubit negative canary is rejected. Full-workload transpilation/routing is NOT_RUN_CAPACITY_PRECHECK_REJECTED; provider discovery, credentials, network access and QPU jobs remain blocked."
        elif is_bands_candidate and v43_integrity:
            seal_reason = "V4.3 authenticates eight full elementary circuit streams (21,925,902 instructions; maximum 1,158,046 CX; minimum margin +1,341,954; maximum recycled-workspace bound 339). Independent reversible controls pass only on exact-feasible data × two one-hot coin registers, while the mandatory off-promise cleanup witness is rejected. The next gate is a separately preregistered named-backend zero-job transpilation and routing protocol; provider discovery, credentials, backend work and QPU jobs remain blocked."
        elif is_bands_candidate and v42_integrity:
            seal_reason = "V4.2 authenticates connected joint promise support and passes the selected-model resource screen on all eight seeds (maximum 1,135,430 CNOT; minimum margin +1,364,570; maximum logical-qubit bound 331). This is a provider-neutral research admission only. Circuit materialization and independent reversible simulation are the next gate; provider discovery, backend transpilation and QPU jobs remain blocked."
        elif is_bands_candidate and v41_integrity:
            seal_reason = "V4.1 certifies augmented one-plus-two-swap connectivity with 58,725 exact incident audits and three deterministic bridges, but resource admission remains rejected. R1 reaches 15,256,056 CNOT and R2 reaches 15,663,936 versus the immutable 2,500,000 limit; cache preparation is separately reported and excluded from the numerator. Provider discovery, backend transpilation and QPU jobs remain blocked."
        elif is_bands_candidate and v40_integrity:
            seal_reason = "V4.0 exhaustively certifies a disconnected complete one-swap feasible graph: seeds 2207 and 7703 contain three feasible isolated portfolios with 900 exact infeasible-neighbor checks. V3.9 also remains rejected at 781,332,180 maximum selected-model CNOT versus 2,500,000. V4.1 is preregistered but not evaluated. Provider discovery, transpilation and jobs remain blocked."
        elif is_bands_candidate and v39_integrity:
            seal_reason = "V3.9 authenticates all eight scalable N40 reversible IRs but rejects the frozen architecture at 781,332,180 maximum selected-model CNOT versus the 2,500,000 limit. Complete feasible-graph connectivity remains indeterminate. Provider discovery, transpilation and jobs remain blocked."
        elif is_bands_candidate and v38_integrity:
            seal_reason = "V3.8 seals an exact elementary lowering only for the N=4 prototype. The N=40 reversible arithmetic/cache-update IR, eight-seed coherent equivalence, cleanup, connectivity, selected-model CNOT ledger and 2.5M budget gate remain blocked or not evaluated. Provider discovery, transpilation and jobs remain blocked."
        elif is_bands_candidate and v37_integrity:
            seal_reason = "V3.7 seals a small-instance reversible prototype only. The authenticated seven-constraint N=40 compiler, elementary one-/two-qubit decomposition, selected-model CNOT ledger and 2.5M budget gate remain blocked or not evaluated. Backend selection, credentials, transpilation and jobs remain blocked."
        elif is_bands_candidate and v36_integrity:
            seal_reason = "V3.6 structural diagnosis is sealed: topology-only optimization cannot repair the frozen V3.4 representation, while incremental exposure remains blocked pending a clean reversible compiler, coherent cache-update proof and selected-model gate ledger. Backend selection, credentials, transpilation and jobs remain blocked."
        elif is_bands_candidate and backend_admission_integrity:
            seal_reason = "V3.5 negative result is sealed: the selected-CCX CNOT accounting exceeds IBM's documented per-circuit 2Q-gate limit by 29,881.106542×. Backend selection, credentials, transpilation and jobs remain blocked."
        elif is_bands_candidate and optimized_native_integrity:
            seal_reason = "V3.4 optimized-oracle equivalence and elementary C2-XY matrix identity are sealed, but complete-graph connectivity is indeterminate and backend-native synthesis, routing, calibration, noise and resource acceptance are not run."
        elif is_bands_candidate and algorithmic_integrity:
            seal_reason = "V3.3 exact feasibility invariance is sealed, but the V3.4 elementary lowering and all backend gates are unavailable in this runtime."
        elif gate_compiler_integrity:
            seal_reason = "The V3.2 provider-neutral gate compiler is sealed, but backend-native transpilation and a validated seven-constraint algorithmic enforcement contract are still required."
        else:
            seal_reason = "Exact BANDS fidelity is sealed, but the fail-closed V3.2 gate-compiler chain is not yet valid in this runtime."
    elif not backend_snapshot:
        seal_reason = "Select and snapshot a named hardware backend."
    elif not capacity.get("capacity_ok"):
        seal_reason = "Backend raw-qubit capacity/operational check failed."
    else:
        seal_reason = "Ready to seal. Sealing still does not execute a QPU job."
    st.markdown(f'<div class="qp3-panel"><div class="qp3-pk">SEALING GATE</div><div class="qp3-pt {"qp3-ok" if seal_ready else "qp3-warn"}">{escape("READY" if seal_ready else "NOT READY")}</div><div class="qp3-note">{escape(seal_reason)}</div></div>', unsafe_allow_html=True)
    if st.button("Seal Phase-III equal-objective hardware protocol", disabled=not seal_ready, key=f"{PREFIX}_p3_seal"):
        sealed = qpu_seal_protocol(qpu_output_root(), gate, selected_family, backend_snapshot, encoding, depth_schedule=depth_schedule, shots_per_circuit=int(shots), hardware_repeats=int(repeats))
        st.session_state[f"{PREFIX}_p3_sealed"] = sealed
    sealed = st.session_state.get(f"{PREFIX}_p3_sealed")
    if isinstance(sealed, dict):
        if sealed.get("sealed"):
            st.success(f"Phase-III hardware protocol sealed: {sealed.get('path')}. No hardware jobs were submitted.")
            st.json(sealed.get("protocol") or {})
        else:
            st.error(str(sealed.get("reason", "Protocol sealing failed.")))

    if v48_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.8 authenticates eight exact control-loaded-adder streams, 28,240 computational-basis equivalence cases and unchanged frozen-BasicSwap routing. Aggregate logical CX decreases from 19,251,104 to 6,474,096 and routed CZ from 119,029,964 to 59,565,732, but these are structural offline resource counts, not calibrated performance. Only one authentic historical snapshot epoch exists; multi-snapshot robustness is therefore not evaluable, and the deliberately optimistic V4.7-comparable duration and additive reported-error necessary screens still fail for all eight seeds. Hardware executability is false; provider SDK imports, credential reads, backend/provider/network calls, simulator jobs and QPU jobs are zero; utility and quantum advantage are not claimed; classification remains RESEARCH_ONLY.</div>',
            unsafe_allow_html=True,
        )
    elif v47_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.7 authenticates the exact eight V4.6 streams against a pinned historical 2025-02-26 FakeMarrakesh properties file. Integer-dt ASAP schedules and additive reported gate-error mass are offline model diagnostics only: they are not pulse schedules, wall-clock runtime, circuit fidelity, success probability, expected failures or current calibration. The fixed V4.6 architecture fails both deliberately optimistic historical stress screens across all eight seeds; the one preregistered fault-excluded routing candidate is not asserted globally optimal or production-ready. Hardware executability is false; provider SDK imports, credential reads, backend/provider/network calls, simulator jobs and QPU jobs are zero; utility and quantum advantage are not claimed; classification remains RESEARCH_ONLY.</div>',
            unsafe_allow_html=True,
        )
    elif v46_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.6 authenticates 48,647,214 full-stream input instructions and an exactly reconstructible 476,876,458-instruction native macro IR over the pinned offline FakeMarrakesh topology. All eight streams pass the inherited structural/resource gates with zero ISA and coupling violations; maximum native CZ is 15,527,797 and maximum ASAP structural depth is 24,893,376. The route IR is not a submitted circuit, the snapshot is not current hardware evidence, depth is not calibrated duration, fidelity and optimization performance are not tested, hardware executability is false, provider SDK imports, credential reads, backend/provider/network calls, simulator jobs and QPU jobs are zero, quantum advantage is not claimed, and classification remains RESEARCH_ONLY.</div>',
            unsafe_allow_html=True,
        )
    elif v45_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.5 authenticates eight proof-carrying binary-coin streams with exact registered-promise parity, explicit clean-exit register-liveness certificates and logical widths of 133–145 against the pinned 156-qubit capacity. All eight provider-neutral streams remain at or below 2,500,000 CX; the worst is 2,499,790 with +210 remaining. Full FakeMarrakesh circuit reconstruction, transpilation, layout and routing are NOT_RUN_IN_V4_5; native CZ counts and routed depth are not measured; current calibration and optimization performance are not tested; hardware executability is false; provider SDK imports, credential reads, provider calls, network calls and QPU jobs are zero; quantum advantage is not claimed; classification remains RESEARCH_ONLY.</div>',
            unsafe_allow_html=True,
        )
    elif v44_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.4 authenticates a pinned offline FakeMarrakesh structural target with 156 qubits. Every frozen V4.3 workload requires 327–339 logical qubits, and the four persistent 40-qubit registers alone require 160; all eight full workloads are therefore rejected before circuit reconstruction, transpilation or routing. Five bounded Qiskit canaries pass two identical clean-process replays and the mandatory 157-qubit canary is rejected, but these controls cannot be extrapolated to the full workload. Full native counts and routed depth are NOT_RUN_CAPACITY_PRECHECK_REJECTED; current calibration and optimization performance are not tested; hardware executability is false; credential reads, provider calls, network calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )
    elif v43_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.3 authenticates 21,925,902 elementary instructions across eight provider-neutral circuit streams. The maximum complete-step numerator is 1,158,046 CX against 2,500,000, with +1,341,954 remaining and a 339-qubit recycled-workspace bound. Independent finite simulation passes only for exact-feasible N=40 data × two one-hot coin registers; the mandatory off-promise witness leaves the feasibility flag dirty and is explicitly rejected. Named-backend transpilation, native routing, calibration, noise and optimization performance are not run; hardware executability is false; provider calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )
    elif v42_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.2 certifies connected joint promise support and passes the unchanged selected-model resource gate across all eight frozen seeds. The maximum complete-step numerator is 1,135,430 CNOT against 2,500,000, with a 331 logical-qubit recycled-workspace bound. This admits only the provider-neutral research generator on exact-feasible data × two one-hot coin registers. Circuit materialization, reversible simulation, backend transpilation and optimization performance are not run; hardware executability is false; provider calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )
    elif v41_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.1 certifies augmented one-plus-two-swap connectivity across all eight frozen seeds using the complete V4.0 forest and three exact Hamming-distance-four bridges. This connectivity PASS does not repair resource admission: R1 reaches 15,256,056 CNOT and R2 reaches 15,663,936 against the immutable 2,500,000 gate; both resource candidates remain rejected. Cache preparation is reported separately and excluded from the mixer numerator. Backend transpilation is not run; hardware executability is false; provider calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )
    elif v40_integrity:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> V4.0 certifies that the complete one-swap feasible graph is disconnected and V3.9 preserves its resource rejection. V4.1 is absent or unauthenticated, so no augmented-connectivity or successor-resource outcome is disclosed. Backend transpilation is not run; hardware executability is false; provider calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="qrl-warning"><b>Execution boundary:</b> the latest BANDS evidence chain is absent or invalid. Connectivity, resource and production decisions remain masked fail-closed. Backend transpilation is not run; hardware executability is false; provider calls and QPU jobs are zero; quantum advantage is not claimed.</div>',
            unsafe_allow_html=True,
        )

def render_quantum_research_lab(
    ticker: str | None = None,
    price_data: pd.DataFrame | None = None,
    analysis: dict | None = None,
) -> None:
    del analysis  # reserved for future controlled integrations; avoids mutating existing app analysis.
    _inject_css()
    ticker = str(ticker or "SPY").upper().strip()

    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        price_data = pd.DataFrame()

    regime_frame, regime_source = _load_regime_cached(ticker)
    if (not isinstance(price_data, pd.DataFrame) or price_data.empty) and isinstance(regime_frame, pd.DataFrame) and not regime_frame.empty:
        hero_price = regime_frame[["PRIMARY"]].dropna().reset_index()
        hero_price.columns = ["date", "close"]
        price_data = hero_price

    # Mission Control and REGIME / DENSITY consume the exact same calibrated
    # V2.2.1 result. Streamlit session-state parameters are read before rendering
    # the tabs; any slider change triggers a rerun and therefore refreshes both.
    params = _regime_params_from_state()
    regime_result: dict[str, Any]
    if isinstance(regime_frame, pd.DataFrame) and not regime_frame.empty:
        with st.spinner("Calibrating Quantum Regime Engine V2.2.1…"):
            regime_result = _run_regime_cached(regime_frame, **params)
    else:
        regime_result = {"available": False, "reason": "Cross-asset regime panel unavailable."}

    snapshot = _snapshot_from_benchmark(regime_result, price_data)
    _hero(ticker, snapshot)

    tabs = st.tabs(
        [
            "MISSION CONTROL",
            "REGIME / DENSITY",
            "QMC / RISK",
            "QUBO / ISING",
            "QUANTUM INFORMATION",
            "BENCHMARK PROTOCOL",
            "PHASE II / OOS",
            "PHASE III / QPU",
        ]
    )

    with tabs[0]:
        _mission_control(snapshot, ticker, price_data)

    with tabs[1]:
        _regime_lab(ticker, regime_frame, regime_source, result=regime_result)

    with tabs[2]:
        _qmc_lab(price_data)

    portfolio_returns: pd.DataFrame | None = None
    portfolio_source: str | None = None
    with tabs[3]:
        portfolio_returns, portfolio_source = _portfolio_lab()

    with tabs[4]:
        _information_lab(portfolio_returns, portfolio_source)

    with tabs[5]:
        _benchmarks(regime_result, portfolio_returns)

    with tabs[6]:
        _phase2_program(regime_result, regime_frame, portfolio_returns)

    with tabs[7]:
        _phase3_qpu_program()
