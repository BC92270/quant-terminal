from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from .config import EngineConfig
from .contracts import EngineResult
from .data import align_benchmarks, assess_quality, normalize_ohlcv
from .decision import build_decision
from .ensemble import combine_forecasts
from .features import build_feature_frame
from .models import run_model_suite
from .regimes import infer_regimes
from .validation import build_walk_forward_diagnostic


def _timeframe_table(frame: pd.DataFrame) -> pd.DataFrame:
    latest = frame.iloc[-1]
    rows: list[dict] = []
    for horizon in (5, 20, 60, 120):
        if len(frame) <= horizon:
            continue
        performance = float(frame["close"].iloc[-1] / frame["close"].iloc[-horizon] - 1)
        slope = float(latest.get(f"slope_{horizon}", np.nan)) if horizon in {20, 60, 120} else float(latest.get("slope_20", np.nan))
        r2 = float(latest.get(f"r2_{horizon}", np.nan)) if horizon in {20, 60, 120} else float(latest.get("r2_20", np.nan))
        efficiency = float(latest.get(f"efficiency_{horizon}", np.nan)) if horizon in {20, 60, 120} else float(latest.get("efficiency_20", np.nan))
        signed_score = np.tanh(
            2.8 * performance
            + 0.8 * np.nan_to_num(slope)
            + np.sign(performance) * (0.6 * np.nan_to_num(r2) + 0.5 * np.nan_to_num(efficiency))
        )
        rows.append(
            {
                "Horizon": f"{horizon}D",
                "Return": performance,
                "Annualized slope": slope,
                "R²": r2,
                "Efficiency": efficiency,
                "Directional score": float(100 * signed_score),
                "State": "BULL" if signed_score > 0.20 else "BEAR" if signed_score < -0.20 else "NEUTRAL",
            }
        )
    table = pd.DataFrame(rows)
    if not table.empty:
        signs = np.sign(table["Directional score"])
        table.attrs["alignment"] = float(abs(signs.mean()))
    return table


class MomentumTrendEngine:
    def __init__(self, config: EngineConfig | None = None):
        self.config = config or EngineConfig()

    def run(
        self,
        ticker: str,
        price_data: pd.DataFrame,
        benchmarks: Mapping[str, pd.DataFrame] | None = None,
    ) -> EngineResult:
        clean = normalize_ohlcv(price_data)
        quality = assess_quality(price_data, clean)
        if len(clean) < 60:
            raise ValueError("At least 60 valid observations are required.")
        aligned = align_benchmarks(clean, benchmarks)
        features = build_feature_frame(aligned, self.config.annualisation)
        regime_history, regime = infer_regimes(features, self.config.regime_stickiness)
        forecasts = run_model_suite(features, self.config)
        ensemble = combine_forecasts(forecasts, regime, quality.quality_score)
        decision, scenarios = build_decision(features, ensemble, regime, quality, self.config)
        timeframe_table = _timeframe_table(features)
        validation_table, equity_curve = build_walk_forward_diagnostic(features, self.config)
        latest = features.iloc[-1]
        audit = {
            "causal_features": True,
            "forecast_horizon": self.config.forecast_horizon,
            "models_ready": sum(forecast.status == "READY" for forecast in forecasts),
            "models_total": len(forecasts),
            "benchmark_columns": [column for column in features if column.startswith("benchmark_")],
            "warnings": list(quality.notes),
            "methodology": "Sticky causal regime filter + reliability-weighted heterogeneous ensemble",
        }
        return EngineResult(
            ticker=str(ticker).upper().strip(),
            as_of=pd.Timestamp(latest["date"]),
            price=float(latest["close"]),
            config=self.config,
            quality=quality,
            frame=features,
            regimes=regime_history,
            regime=regime,
            forecasts=ensemble.forecasts,
            ensemble=ensemble,
            decision=decision,
            timeframe_table=timeframe_table,
            scenario_table=scenarios,
            validation_table=validation_table,
            equity_curve=equity_curve,
            audit=audit,
        )


def run_momentum_trend(
    ticker: str,
    price_data: pd.DataFrame,
    benchmarks: Mapping[str, pd.DataFrame] | None = None,
    config: EngineConfig | None = None,
) -> EngineResult:
    return MomentumTrendEngine(config).run(ticker, price_data, benchmarks)

