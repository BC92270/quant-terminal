from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import DependencyConfig
from .data_hub import build_dependency_data_hub
from .force_model import ForceModelResult, fit_force_model
from .inputs import ForceInputs, collect_force_inputs, force_coverage_table
from .spaces import dependency_spaces
from .structural import (
    economic_context,
    event_dependency_attribution,
    higher_moment_dependency,
    extreme_move_dependency,
    lead_lag_table,
    liquidity_dependency,
)


@dataclass
class PairDependencyAnalysis:
    primary: str
    peer: str
    status: str = "unavailable"
    inputs: ForceInputs | None = None
    coverage: pd.DataFrame = field(default_factory=pd.DataFrame)
    force_model: ForceModelResult = field(default_factory=ForceModelResult)
    spaces: pd.DataFrame = field(default_factory=pd.DataFrame)
    lead_lag: pd.DataFrame = field(default_factory=pd.DataFrame)
    extremes: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Deprecated compatibility field; mirrors `extremes`.
    jumps: pd.DataFrame = field(default_factory=pd.DataFrame)
    higher_moments: pd.DataFrame = field(default_factory=pd.DataFrame)
    liquidity: pd.DataFrame = field(default_factory=pd.DataFrame)
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    economic_context: pd.DataFrame = field(default_factory=pd.DataFrame)
    data_hub_audit: pd.DataFrame = field(default_factory=pd.DataFrame)
    data_hub_summary: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)


class DependencyIntelligence:
    """Multi-force dependency attribution layer.

    It consumes the frozen V3.1.1 correlation-core outputs plus optional external force/event/
    metadata feeds. It does *not* alter the core correlation calculations and does not claim
    causality from regressions, correlations, VARs or event windows.
    """

    def __init__(self, config: DependencyConfig | None = None):
        self.config = config or DependencyConfig()

    def analyse_pair(
        self,
        primary: str,
        peer: str,
        changes: pd.DataFrame,
        analysis: dict[str, Any] | None = None,
        portfolio_weights: dict[str, float] | None = None,
    ) -> PairDependencyAnalysis:
        b = PairDependencyAnalysis(primary=primary, peer=peer)
        if changes is None or changes.empty or primary not in changes.columns or peer not in changes.columns:
            b.summary = {"status": "unavailable", "message": "Pair data unavailable."}
            return b

        hub = build_dependency_data_hub(primary, peer, changes, analysis or {})
        b.data_hub_audit = hub.audit
        b.data_hub_summary = hub.summary
        inputs = collect_force_inputs(changes, hub.analysis)
        b.inputs = inputs
        b.coverage = force_coverage_table(inputs, changes)
        fm = fit_force_model(primary, peer, changes, inputs.series, inputs.metadata, self.config)
        b.force_model = fm
        b.spaces = dependency_spaces(
            primary, peer, changes, inputs,
            residual_primary=fm.residual_primary if fm.status == "ok" else None,
            residual_peer=fm.residual_peer if fm.status == "ok" else None,
            min_obs=self.config.min_pair_obs,
        )
        b.lead_lag = lead_lag_table(primary, peer, changes, self.config.lead_lag_max_days, self.config.min_pair_obs, self.config)
        extreme_threshold = float(getattr(self.config, "extreme_z_threshold", self.config.jump_z_threshold))
        b.extremes = extreme_move_dependency(primary, peer, changes, extreme_threshold, self.config.min_pair_obs, self.config)
        b.jumps = b.extremes.copy()
        b.higher_moments = higher_moment_dependency(primary, peer, changes, self.config.min_pair_obs, self.config)
        b.liquidity = liquidity_dependency(primary, peer, inputs, self.config.liquidity_min_obs)
        b.events = event_dependency_attribution(primary, peer, changes, inputs, self.config)
        b.economic_context = economic_context(primary, peer, changes, inputs, portfolio_weights)
        b.status = "ok"
        b.summary = self._summary(b)
        return b

    def _summary(self, b: PairDependencyAnalysis) -> dict[str, Any]:
        fm = b.force_model
        active = b.coverage[b.coverage["Status"] != "Not connected"] if not b.coverage.empty else pd.DataFrame()
        mechanisms = sorted(set(active["Mechanism"].dropna().astype(str))) if not active.empty else []
        force_count = len(fm.factors_used) if fm.status == "ok" else 0

        synchronous_corr, best_lag, best_lag_corr = None, None, None
        best_lag_ci_low = best_lag_ci_high = best_lag_p = None
        best_lag_evidence = None
        if not b.lead_lag.empty:
            x = b.lead_lag.dropna(subset=["Correlation"]).copy()
            sync = x[x["Lag days"] == 0]
            if not sync.empty:
                synchronous_corr = float(sync.iloc[0]["Correlation"])
            nz = x[x["Lag days"] != 0]
            if not nz.empty:
                r = nz.loc[nz["Abs correlation"].idxmax()]
                best_lag = int(r["Lag days"])
                best_lag_corr = float(r["Correlation"])
                for key, dest in [("CI low", "lo"), ("CI high", "hi"), ("Selection-adjusted p", "p")]:
                    try:
                        val = float(r.get(key, np.nan))
                    except Exception:
                        val = np.nan
                    if dest == "lo" and np.isfinite(val):
                        best_lag_ci_low = val
                    elif dest == "hi" and np.isfinite(val):
                        best_lag_ci_high = val
                    elif dest == "p" and np.isfinite(val):
                        best_lag_p = val
                ev = str(r.get("Evidence", "") or "").strip()
                best_lag_evidence = ev or None

        coextreme = None
        if not b.extremes.empty:
            rr = b.extremes[b.extremes["Metric"] == "P(peer extreme | primary extreme)"]
            if not rr.empty:
                try:
                    coextreme = float(rr.iloc[0]["Value"])
                except Exception:
                    coextreme = None

        return {
            "status": "ok",
            "raw_corr": fm.raw_corr if fm.status == "ok" else self._raw_corr(b),
            "residual_corr": fm.residual_corr if fm.status == "ok" else None,
            "systematic_covariance_share": fm.systematic_share_of_observed if fm.status == "ok" else None,
            "primary_factor_r2": fm.primary_r2 if fm.status == "ok" else None,
            "peer_factor_r2": fm.peer_r2 if fm.status == "ok" else None,
            "factors_used": force_count,
            "active_force_channels": int(len(active)),
            "active_mechanisms": mechanisms,
            "synchronous_corr": synchronous_corr,
            "best_nonzero_lag_days": best_lag,
            "best_nonzero_lag_corr": best_lag_corr,
            "best_nonzero_lag_ci_low": best_lag_ci_low,
            "best_nonzero_lag_ci_high": best_lag_ci_high,
            "best_nonzero_lag_p": best_lag_p,
            "best_nonzero_lag_evidence": best_lag_evidence,
            # Compatibility aliases now explicitly point to the strongest non-zero lag.
            "best_lead_lag_days": best_lag,
            "best_lead_lag_corr": best_lag_corr,
            "coextreme_conditional": coextreme,
            "cojump_conditional": coextreme,
            "data_hub_mode": b.data_hub_summary.get("mode"),
            "data_hub_active": b.data_hub_summary.get("active", False),
            "event_force_groups": int(len(b.events)) if not b.events.empty else 0,
            "causal_status": "Associational unless an upstream force is explicitly identified by a structural/event design",
        }

    @staticmethod
    def _raw_corr(b: PairDependencyAnalysis) -> float | None:
        if b.spaces.empty:
            return None
        r = b.spaces[b.spaces["Space"] == "Observed / core"]
        if r.empty:
            return None
        v = r.iloc[0]["Correlation"]
        try:
            return float(v) if np.isfinite(float(v)) else None
        except Exception:
            return None
