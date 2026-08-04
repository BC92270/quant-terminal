from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Mapping

import numpy as np
import pandas as pd

from .barriers import _build_levels
from .config import (DEFAULT_CONFIDENCE, DEFAULT_HORIZONS, ENGINE_VERSION, MAX_HORIZON,
                     MODEL_ALIASES, MODELS, SCENARIOS, MonteCarloSettings)
from .data_quality import _prepare_base
from .governance import _configuration_signature, _matrix_diagnostics
from .models.dispatcher import simulate_paths_max_horizon as _simulate_paths_max_horizon
from .risk_metrics import _summarize_paths
from .utils import _clamp
from .validation import _baseline_var_validation

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
) -> Dict[str, Any]:
    """Build the full Monte Carlo research object.

    Compatibility note:
        The first seven positional arguments are unchanged from the previous file.
        Additional institutional settings are optional keyword arguments.
    """
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

    settings = MonteCarloSettings(
        simulations=simulations,
        matrix_simulations=matrix_simulations,
        scenario=scenario,
        model=model,
        seed=int(seed),
        barrier_monitoring=barrier_monitoring,
        confidence_level=confidence_level,
        mean_block_length=mean_block_length,
        ewma_lambda=ewma_lambda,
        ruin_threshold=ruin_threshold,
    )

    base = _prepare_base(price_data, analysis=analysis or {}, ewma_lambda=ewma_lambda)
    if not base.get("ok"):
        return {
            "ok": False,
            "reason": base.get("reason", "Erreur Monte Carlo."),
            "base": base,
            "engine_version": ENGINE_VERSION,
        }

    try:
        levels = _build_levels(base, custom_levels=custom_levels)
    except ValueError as exc:
        return {
            "ok": False,
            "reason": str(exc),
            "base": base,
            "engine_version": ENGINE_VERSION,
        }

    # Selected scenario/model: retain full path cube for interactive diagnostics.
    selected_paths, selected_params, selected_metadata = _simulate_paths_max_horizon(
        base=base,
        scenario=scenario,
        model=model,
        simulations=simulations,
        seed=int(seed),
        max_horizon=MAX_HORIZON,
        mean_block_length=mean_block_length,
        ewma_lambda=ewma_lambda,
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
            monitoring=barrier_monitoring,
            seed=int(seed),
            confidence=confidence_level,
            ruin_threshold=ruin_threshold,
            include_diagnostics=True,
        )

    # Scenario matrix: path cubes are discarded after each scenario/model summary.
    # Common random numbers are preserved because each model seed is scenario-invariant.
    matrix_rows: List[Dict[str, Any]] = []
    for matrix_model in MODELS:
        for matrix_scenario in SCENARIOS:
            matrix_paths, matrix_params, matrix_metadata = _simulate_paths_max_horizon(
                base=base,
                scenario=matrix_scenario,
                model=matrix_model,
                simulations=matrix_simulations,
                seed=int(seed),
                max_horizon=MAX_HORIZON,
                mean_block_length=mean_block_length,
                ewma_lambda=ewma_lambda,
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
                        monitoring=barrier_monitoring,
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
        "drift_convention": "GBM arithmetic drift calibrated from log returns",
        "scenario_comparison": "Common random numbers by model",
        "horizon_structure": "One 90-step cube sliced at 7/30/90",
        "barrier_monitoring_requested": barrier_monitoring,
        "matrix_simulations": matrix_simulations,
        "selected_simulations": simulations,
        "limitations": [
            "No options-implied or risk-neutral calibration in V2.1.",
            "Brownian bridge is enabled only for continuous Gaussian GBM engines.",
            "Historical and bootstrap models remain sensitive to sample length and corporate-action quality.",
            "The rolling VaR validation is a baseline Gaussian diagnostic, not yet a full model-by-model backtest.",
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
        "selected_model_metadata": selected_metadata,
        "scenario_note": selected_params.note,
        "settings": asdict(settings),
        "assumptions": assumptions,
    }
