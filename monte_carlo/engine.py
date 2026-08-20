from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd

from .barriers import _build_levels, resolve_barrier_monitoring
from .calibration import conditional_calibration_table, fit_conditional_model_set
from .calibration_sources import resolve_calibration_data
from .config import (
    DEFAULT_CONFIDENCE,
    DEFAULT_HORIZONS,
    ENGINE_VERSION,
    MAX_HORIZON,
    MODEL_ALIASES,
    MODELS,
    SCENARIOS,
    MonteCarloSettings,
)
from .data_quality import _normalize_price_data, _prepare_base
from .eligibility import build_model_eligibility, model_eligibility_table
from .governance import _configuration_signature, _matrix_diagnostics
from .models.dispatcher import simulate_paths_max_horizon as _simulate_paths_max_horizon
from .risk_metrics import _summarize_paths
from .utils import _clamp
from .validation import _baseline_var_validation


def _metadata_with_eligibility(
    metadata: Mapping[str, Any],
    eligibility: Mapping[str, Any],
    monitoring_resolution: Mapping[str, Any],
) -> Dict[str, Any]:
    output = dict(metadata)
    output.update(
        {
            "eligibility_status": eligibility.get("status", "INELIGIBLE"),
            "eligibility_reasons": list(eligibility.get("reasons", [])),
            "eligible_for_aggregation": bool(eligibility.get("eligible_for_aggregation", False)),
            "research_only": bool(eligibility.get("research_only", True)),
            "barrier_monitoring_requested": monitoring_resolution.get("requested"),
            "barrier_monitoring_effective": monitoring_resolution.get("effective"),
            "barrier_monitoring_forced": bool(monitoring_resolution.get("forced", False)),
            "barrier_monitoring_warning": monitoring_resolution.get("warning", ""),
        }
    )
    return output


def build_monte_carlo_lab(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: Dict[str, Any] | None = None,
    simulations: int = 3_000,
    scenario: str = "Conservateur",
    model: str = "GBM normal",
    seed: int = 42,
    matrix_simulations: int | None = None,
    barrier_monitoring: str = "Brownian bridge (GBM)",
    confidence_level: float = DEFAULT_CONFIDENCE,
    mean_block_length: int = 10,
    ewma_lambda: float = 0.94,
    ruin_threshold: float = -0.30,
    custom_levels: Mapping[str, float] | None = None,
    calibration_data: pd.DataFrame | None = None,
    calibration_window: int | None = None,
    calibration_source_mode: str = "auto",
    uploaded_calibration_data: pd.DataFrame | None = None,
    provider_calibration_data: pd.DataFrame | None = None,
    provider_report: Mapping[str, Any] | None = None,
    provider_name: str = "yfinance",
    provider_period: str = "10y",
    provider_cache_ttl_hours: int = 12,
    provider_price_basis: str = "adjusted",
    provider_enabled: bool = True,
    garch_maxiter: int = 800,
    garch_min_observations: int = 120,
    stability_check: bool = True,
) -> Dict[str, Any]:
    """Build the institutional forward-risk object.

    V2.4.1 retains the auditable automatic long-history bridge while adding
    calibration-source resolution, model eligibility gates, leakage-safe walk-forward
    validation and a separately governed validated-ensemble layer. Existing positional calls remain valid.
    """
    analysis = analysis or {}
    model = MODEL_ALIASES.get(model, model)
    if scenario not in SCENARIOS:
        scenario = "Conservateur"
    if model not in MODELS:
        model = "GBM normal"

    simulations = max(250, int(simulations))
    matrix_simulations = int(matrix_simulations or min(simulations, 2_000))
    matrix_simulations = max(250, min(matrix_simulations, simulations))
    confidence_level = _clamp(float(confidence_level), 0.80, 0.999)
    ewma_lambda = _clamp(float(ewma_lambda), 0.50, 0.999)
    mean_block_length = max(2, int(mean_block_length))
    ruin_threshold = _clamp(float(ruin_threshold), -0.95, -0.01)
    calibration_window = int(calibration_window) if calibration_window not in (None, 0) else None
    garch_maxiter = max(100, min(int(garch_maxiter), 5_000))
    garch_min_observations = max(60, min(int(garch_min_observations), 2_000))

    barrier_resolution = resolve_barrier_monitoring(model, barrier_monitoring)
    resolved_calibration_data, source_report = resolve_calibration_data(
        price_data=price_data,
        analysis=analysis,
        explicit_calibration_data=calibration_data,
        uploaded_calibration_data=uploaded_calibration_data,
        provider_calibration_data=provider_calibration_data,
        provider_report=provider_report,
        source_mode=calibration_source_mode,
    )

    settings = MonteCarloSettings(
        simulations=simulations,
        matrix_simulations=matrix_simulations,
        scenario=scenario,
        model=model,
        seed=int(seed),
        barrier_monitoring=str(barrier_monitoring),
        effective_barrier_monitoring=str(barrier_resolution["effective"]),
        confidence_level=confidence_level,
        mean_block_length=mean_block_length,
        ewma_lambda=ewma_lambda,
        ruin_threshold=ruin_threshold,
        calibration_window=calibration_window,
        calibration_source_mode=str(calibration_source_mode),
        garch_maxiter=garch_maxiter,
        garch_min_observations=garch_min_observations,
        stability_check=bool(stability_check),
        provider_name=str(provider_name),
        provider_period=str(provider_period),
        provider_cache_ttl_hours=max(0, int(provider_cache_ttl_hours)),
        provider_price_basis=str(provider_price_basis),
        provider_enabled=bool(provider_enabled),
    )

    base = _prepare_base(
        price_data,
        analysis=analysis,
        ewma_lambda=ewma_lambda,
        calibration_data=resolved_calibration_data,
        calibration_window=calibration_window,
        calibration_source_label=str(source_report.get("selected_source", "display_price_data")),
        calibration_source_report=source_report,
    )
    if not base.get("ok"):
        return {
            "ok": False,
            "reason": base.get("reason", "Erreur Monte Carlo."),
            "base": base,
            "engine_version": ENGINE_VERSION,
        }

    # Validation history is preserved independently from the current calibration
    # window. Current model calibration may use a 1Y/3Y/5Y tail, while walk-forward
    # validation can still use the full defensible long-history source.
    validation_df, validation_quality = _normalize_price_data(resolved_calibration_data)
    if validation_df.empty:
        validation_df = base["calibration_df"].copy()
    base["validation_df"] = validation_df
    base["validation_observations"] = max(int(len(validation_df)) - 1, 0)
    base["validation_source"] = str(source_report.get("selected_source", base.get("calibration_source")))
    base["quality"]["validation_rows"] = int(len(validation_df))
    base["quality"]["validation_observations"] = base["validation_observations"]
    base["quality"]["validation_source"] = base["validation_source"]
    for warning in validation_quality.get("warnings", []):
        base["quality"]["warnings"].append(str(warning))
    base["quality"]["warnings"] = list(dict.fromkeys(base["quality"]["warnings"]))

    conditional_calibrations = fit_conditional_model_set(
        base,
        maxiter=garch_maxiter,
        min_observations=garch_min_observations,
        stability_check=bool(stability_check),
    )
    base["conditional_calibrations"] = conditional_calibrations
    calibration_frame = conditional_calibration_table(conditional_calibrations)

    eligibility = build_model_eligibility(base, conditional_calibrations)
    eligibility_frame = model_eligibility_table(eligibility)
    selected_eligibility = eligibility[model]

    for fit in conditional_calibrations.values():
        if not fit.get("ok"):
            warning = fit.get("warning") or f"Calibration {fit.get('model')} indisponible."
            base["quality"]["warnings"].append(str(warning))
    if barrier_resolution.get("warning"):
        base["quality"]["warnings"].append(str(barrier_resolution["warning"]))
    if selected_eligibility.get("status") != "ELIGIBLE":
        base["quality"]["warnings"].append(
            f"Selected model {model}: {selected_eligibility.get('status')} — "
            + "; ".join(selected_eligibility.get("reasons", []))
        )
    base["quality"]["warnings"] = list(dict.fromkeys(base["quality"]["warnings"]))

    try:
        levels = _build_levels(base, custom_levels=custom_levels)
    except ValueError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "base": base,
            "engine_version": ENGINE_VERSION,
        }

    selected_paths, selected_params, selected_metadata_raw = _simulate_paths_max_horizon(
        base=base,
        scenario=scenario,
        model=model,
        simulations=simulations,
        seed=int(seed),
        max_horizon=MAX_HORIZON,
        mean_block_length=mean_block_length,
        ewma_lambda=ewma_lambda,
    )
    selected_metadata = _metadata_with_eligibility(
        selected_metadata_raw, selected_eligibility, barrier_resolution
    )

    paths_by_horizon: Dict[int, np.ndarray] = {}
    summaries_by_horizon: Dict[int, Dict[str, Any]] = {}
    for horizon in DEFAULT_HORIZONS:
        paths_by_horizon[horizon] = selected_paths[:, : horizon + 1]
        summaries_by_horizon[horizon] = _summarize_paths(
            paths=selected_paths,
            levels=levels,
            params=selected_params,
            model_metadata=selected_metadata,
            horizon=horizon,
            scenario=scenario,
            model=model,
            monitoring=str(barrier_resolution["effective"]),
            seed=int(seed),
            confidence=confidence_level,
            ruin_threshold=ruin_threshold,
            include_diagnostics=True,
        )

    matrix_rows: List[Dict[str, Any]] = []
    for matrix_model in MODELS:
        matrix_eligibility = eligibility[matrix_model]
        matrix_monitoring = resolve_barrier_monitoring(matrix_model, barrier_monitoring)
        for matrix_scenario in SCENARIOS:
            matrix_paths, matrix_params, matrix_metadata_raw = _simulate_paths_max_horizon(
                base=base,
                scenario=matrix_scenario,
                model=matrix_model,
                simulations=matrix_simulations,
                seed=int(seed),
                max_horizon=MAX_HORIZON,
                mean_block_length=mean_block_length,
                ewma_lambda=ewma_lambda,
            )
            matrix_metadata = _metadata_with_eligibility(
                matrix_metadata_raw, matrix_eligibility, matrix_monitoring
            )
            for horizon in DEFAULT_HORIZONS:
                matrix_rows.append(
                    _summarize_paths(
                        paths=matrix_paths,
                        levels=levels,
                        params=matrix_params,
                        model_metadata=matrix_metadata,
                        horizon=horizon,
                        scenario=matrix_scenario,
                        model=matrix_model,
                        monitoring=str(matrix_monitoring["effective"]),
                        seed=int(seed),
                        confidence=confidence_level,
                        ruin_threshold=ruin_threshold,
                        include_diagnostics=False,
                    )
                )

    matrix_df = pd.DataFrame(matrix_rows)
    matrix_diagnostics = {
        horizon: _matrix_diagnostics(matrix_df, horizon, scenario, model)
        for horizon in DEFAULT_HORIZONS
    }

    baseline_validation = _baseline_var_validation(base, alpha=0.05, window=60)
    signature = _configuration_signature(ticker, base, settings, levels)

    assumptions = {
        "measure": "Physical / forward risk (P)",
        "drift_convention": "Arithmetic price drift calibrated from log returns; scenario drift overrides model mean",
        "scenario_comparison": "Common random numbers by model",
        "horizon_structure": "One 90-step cube sliced at 7/30/90",
        "conditional_volatility": "GARCH/GJR maximum-likelihood calibration on the selected calibration sample",
        "stress_taxonomy": "Stress volatility is a scenario overlay, not a simulation model",
        "calibration_source_resolution": source_report,
        "model_eligibility": "Only ELIGIBLE models enter primary cross-model aggregation; WARNING/INELIGIBLE/FALLBACK remain visible for research audit",
        "barrier_monitoring_requested": barrier_resolution["requested"],
        "barrier_monitoring_effective": barrier_resolution["effective"],
        "barrier_monitoring_forced": barrier_resolution["forced"],
        "matrix_simulations": matrix_simulations,
        "selected_simulations": simulations,
        "calibration_source": base.get("calibration_source"),
        "calibration_observations": base.get("calibration_observations"),
        "limitations": [
            "No options-implied or risk-neutral calibration in V2.4.1.",
            "Brownian bridge is enabled only for continuous Gaussian GBM; incompatible engines are forced to discrete monitoring.",
            "GARCH calibration is maximum-likelihood and remains sample-sensitive.",
            "Eligibility is a governance gate, not a claim of predictive superiority.",
            "A failed GARCH calibration uses an explicit EWMA-FHS fallback and is excluded from aggregation.",
            "The rolling Gaussian VaR diagnostic remains a control benchmark; model-specific walk-forward validation uses the independent validation history in V2.4.1.",
            "Automatic provider history is cached and fully auditable; provider failure falls back explicitly rather than silently.",
            "Parameter/model uncertainty is a stationary-bootstrap diagnostic and is not a Bayesian posterior.",
        ],
    }

    return {
        "ok": True,
        "engine_version": ENGINE_VERSION,
        "configuration_signature": signature,
        "ticker": ticker,
        "base": base,
        "levels": asdict(levels),
        "levels_object": levels,
        "paths_by_horizon": paths_by_horizon,
        "summaries_by_horizon": summaries_by_horizon,
        "matrix_df": matrix_df,
        "matrix_diagnostics": matrix_diagnostics,
        "baseline_validation": baseline_validation,
        "conditional_calibrations": conditional_calibrations,
        "conditional_calibration_table": calibration_frame,
        "model_eligibility": eligibility,
        "model_eligibility_table": eligibility_frame,
        "selected_model_eligibility": selected_eligibility,
        "selected_model_metadata": selected_metadata,
        "barrier_monitoring_resolution": barrier_resolution,
        "calibration_source_report": source_report,
        "provider_report": dict(provider_report or {}),
        "validation_df": validation_df,
        "validation_observations": base["validation_observations"],
        "validation_source": base["validation_source"],
        "scenario_note": selected_params.note,
        "settings": asdict(settings),
        "assumptions": assumptions,
    }
