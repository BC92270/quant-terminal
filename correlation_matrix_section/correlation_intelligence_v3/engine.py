from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import CorrelationConfig
from .connectedness import (
    connectedness_from_changes, partial_network_edges, frequency_connectedness_from_changes, partial_network_stability,
)
from .data import classify_asset, load_data_bundle
from .breaks import dependency_break_detector
from .covariance_lab import covariance_estimate, covariance_model_validation, covariance_to_correlation
from .estimators import correlation_matrix, pair_metrics
from .factor import multivariate_factor_model
from .forward_corr import forward_correlation_diagnostics
from .portfolio import (
    correlation_shock_scenarios,
    hedge_candidates,
    incremental_asset_impact,
    portfolio_risk_decomposition, portfolio_eigen_risk, structured_correlation_stress_scenarios,
)
from .regimes import conditional_pair_table
from .stress import build_factor_stress
from .structure import hierarchical_order, mst_edges, rmt_diagnostics
from .tail import adaptive_tail_metrics
from .tail_surface import tail_surface_table
from .utils import clamp, risk_label, safe_float


@dataclass
class AnalysisBundle:
    primary: str
    selected_days: int
    tail_mode: str = "Adaptive"
    data_source: str = ""
    provider_map: dict[str, str] = field(default_factory=dict)
    asset_type_map: dict[str, str] = field(default_factory=dict)
    levels: pd.DataFrame = field(default_factory=pd.DataFrame)
    changes: pd.DataFrame = field(default_factory=pd.DataFrame)
    quality: pd.DataFrame = field(default_factory=pd.DataFrame)
    synchronization: pd.DataFrame = field(default_factory=pd.DataFrame)
    ranking: pd.DataFrame = field(default_factory=pd.DataFrame)
    term_structure: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_raw: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_shrunk: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_partial: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_rmt_cleaned: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_forecast: pd.DataFrame = field(default_factory=pd.DataFrame)
    covariance_validation: pd.DataFrame = field(default_factory=pd.DataFrame)
    covariance_meta: dict = field(default_factory=dict)
    covariance_universe: list[str] = field(default_factory=list)
    factor_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    factor_meta: dict = field(default_factory=dict)
    tail_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    tail_surface: pd.DataFrame = field(default_factory=pd.DataFrame)
    regime_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    stress_table: pd.DataFrame = field(default_factory=pd.DataFrame)

    rmt_summary: dict = field(default_factory=dict)
    rmt_eigen: pd.DataFrame = field(default_factory=pd.DataFrame)
    rmt_loadings: pd.DataFrame = field(default_factory=pd.DataFrame)
    rmt_peer_universe: list[str] = field(default_factory=list)
    rmt_full_summary: dict = field(default_factory=dict)
    rmt_full_eigen: pd.DataFrame = field(default_factory=pd.DataFrame)
    rmt_full_loadings: pd.DataFrame = field(default_factory=pd.DataFrame)
    corr_rmt_cleaned_full: pd.DataFrame = field(default_factory=pd.DataFrame)

    mst_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    cluster_order: list[str] = field(default_factory=list)
    partial_network_edges: pd.DataFrame = field(default_factory=pd.DataFrame)
    partial_network_centrality: pd.DataFrame = field(default_factory=pd.DataFrame)
    connectedness_matrix: pd.DataFrame = field(default_factory=pd.DataFrame)
    connectedness_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    connectedness_meta: dict = field(default_factory=dict)
    connectedness_universe: list[str] = field(default_factory=list)
    frequency_connectedness: pd.DataFrame = field(default_factory=pd.DataFrame)
    frequency_directional: pd.DataFrame = field(default_factory=pd.DataFrame)
    frequency_meta: dict = field(default_factory=dict)
    partial_network_stability: pd.DataFrame = field(default_factory=pd.DataFrame)
    partial_network_stability_meta: dict = field(default_factory=dict)
    break_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    break_links: pd.DataFrame = field(default_factory=pd.DataFrame)
    break_meta: dict = field(default_factory=dict)

    hedges: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_cluster_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_shock_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_incremental_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_eigen_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_eigen_meta: dict = field(default_factory=dict)
    portfolio_structured_stress: pd.DataFrame = field(default_factory=pd.DataFrame)
    portfolio_meta: dict = field(default_factory=dict)

    forward_corr_meta: dict = field(default_factory=dict)
    forward_corr_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict = field(default_factory=dict)


class CorrelationEngine:
    def __init__(self, config: CorrelationConfig | None = None):
        self.config = config or CorrelationConfig()

    def analyse(
        self,
        primary: str,
        tickers: list[str],
        price_data: pd.DataFrame | None,
        selected_days: int,
        period: str,
        analysis: dict[str, Any] | None = None,
    ) -> AnalysisBundle:
        analysis = analysis or {}
        db = load_data_bundle(tickers, primary, price_data, period, analysis)
        ch = db.changes
        tail_mode = str(analysis.get("correlation_tail_mode", self.config.tail_mode_default))
        b = AnalysisBundle(
            primary=primary,
            selected_days=selected_days,
            tail_mode=tail_mode,
            data_source=db.source,
            provider_map=db.provider_map,
            levels=db.levels,
            changes=ch,
            quality=db.quality,
            synchronization=db.synchronization,
        )
        if ch.empty or primary not in ch.columns:
            b.summary = {"status": "unavailable", "message": "Données insuffisantes."}
            return b

        custom_types = analysis.get("correlation_asset_type_map", {})
        b.asset_type_map = {c: classify_asset(c, primary, custom_types) for c in ch.columns}

        rows = []
        for peer in ch.columns:
            if peer == primary:
                continue
            row = pair_metrics(ch, primary, peer, selected_days)
            row["Type"] = b.asset_type_map.get(peer, "Unknown")
            c30, c1y = row.get("Corr 30D"), row.get("Corr 1Y")
            delta = row.get("ΔCorr 30D-1Y")
            if c30 is not None and c1y is not None:
                if abs(delta) <= 0.10:
                    stability = "Stable"
                elif delta > 0.20:
                    stability = "Lien en hausse"
                elif delta < -0.20:
                    stability = "Lien en baisse"
                else:
                    stability = "Variable"
            else:
                stability = "N/A"
            row["Stability"] = stability
            rows.append(row)

        b.ranking = pd.DataFrame(rows)
        if not b.ranking.empty:
            b.ranking["_sort"] = pd.to_numeric(b.ranking["Corr"], errors="coerce").abs()
            b.ranking = b.ranking.sort_values("_sort", ascending=False).drop(columns="_sort").reset_index(drop=True)

        term_cols = ["Ticker", "Corr 30D", "Corr 90D", "Corr 180D", "Corr 1Y", "ΔCorr 30D-1Y"]
        b.term_structure = b.ranking[[c for c in term_cols if c in b.ranking.columns]].copy() if not b.ranking.empty else pd.DataFrame()

        b.corr_raw = correlation_matrix(ch, selected_days, "Pearson", self.config.min_pair_obs)
        b.corr_shrunk = correlation_matrix(ch, selected_days, "Ledoit-Wolf", self.config.min_matrix_obs)
        b.corr_partial = correlation_matrix(ch, selected_days, "Partial", self.config.min_matrix_obs)

        # V3.1 covariance champion/challenger lab. Keep the research universe parsimonious so
        # walk-forward validation is stable and responsive inside Streamlit.
        cov_universe = [primary] + [x for x in b.ranking.get("Ticker", pd.Series(dtype=str)).head(7).tolist() if x in ch.columns]
        cov_universe = list(dict.fromkeys(cov_universe))
        if len(cov_universe) < 3:
            cov_universe = list(ch.columns)[:8]
        b.covariance_universe = cov_universe
        external_nls = analysis.get("correlation_nonlinear_shrinkage_callable")
        b.covariance_validation, b.covariance_meta = covariance_model_validation(
            ch[cov_universe],
            self.config.covariance_validation_models,
            train_days=self.config.covariance_train_days,
            forecast_horizon=int(analysis.get("correlation_forecast_horizon", self.config.covariance_forecast_horizon)),
            min_train=self.config.covariance_min_train,
            max_folds=self.config.covariance_validation_max_folds,
            ewma_lambda=self.config.ewma_lambda,
            external_nls=external_nls if callable(external_nls) else None,
            champion_bootstrap_samples=int(analysis.get("correlation_champion_bootstrap_samples", self.config.covariance_champion_bootstrap_samples)),
            seed=self.config.random_seed,
        )
        champion = b.covariance_meta.get("champion") if b.covariance_meta else None
        if champion:
            cf = covariance_estimate(
                ch[cov_universe], champion, days=max(self.config.covariance_train_days, selected_days),
                min_obs=min(self.config.covariance_min_train, max(60, selected_days)),
                ewma_lambda=self.config.ewma_lambda, external_nls=external_nls if callable(external_nls) else None,
            )
            b.covariance_meta["current_champion_meta"] = cf.metadata
            b.corr_forecast = covariance_to_correlation(cf.covariance)

        factors = [f for f in self.config.factor_candidates if f in ch.columns and f != primary]
        b.factor_table, b.factor_meta = multivariate_factor_model(
            primary,
            ch,
            factors,
            selected_days,
            self.config.hac_maxlags,
            self.config.collinearity_pair_threshold,
        )

        # V3 adaptive tail: horizon is pair-specific and decoupled from central correlation horizon.
        tail_rows = []
        for peer in ch.columns:
            if peer == primary:
                continue
            r = adaptive_tail_metrics(
                primary,
                peer,
                ch,
                central_days=selected_days,
                mode=tail_mode,
                q=self.config.tail_quantile,
                target_tail_obs=self.config.tail_target_obs,
                max_days=self.config.tail_max_days,
            )
            r["Type"] = b.asset_type_map.get(peer, "Unknown")
            tail_rows.append(r)
        b.tail_table = pd.DataFrame(tail_rows)
        if not b.tail_table.empty and "Tail evidence score" in b.tail_table.columns:
            b.tail_table = b.tail_table.sort_values(
                ["Tail evidence score", "Emp lower co-exceedance"],
                ascending=False,
                na_position="last",
            ).reset_index(drop=True)

        tail_peers = b.ranking["Ticker"].head(8).tolist() if not b.ranking.empty else peers[:8] if "peers" in locals() else []
        b.tail_surface = tail_surface_table(
            ch, primary, tail_peers, days=self.config.tail_surface_days, quantiles=self.config.tail_surface_quantiles
        )

        market = next((x for x in self.config.regime_market_candidates if x in ch.columns), None)
        peers = [x for x in ch.columns if x != primary]
        b.regime_table = conditional_pair_table(
            primary,
            ch,
            peers,
            market,
            max(selected_days, 180),
            self.config.min_regime_compute_obs,
            self.config.reliable_regime_obs,
        )
        b.stress_table = build_factor_stress(primary, ch, selected_days, analysis.get("correlation_stress_shocks"))
        break_universe = [primary] + [x for x in b.ranking["Ticker"].head(7).tolist() if x in ch.columns] if not b.ranking.empty else list(ch.columns)[:8]
        b.break_curve, b.break_links, b.break_meta = dependency_break_detector(
            ch[break_universe], primary, days=self.config.break_detection_days, side_window=self.config.break_side_window,
            step=self.config.break_step, bootstrap_samples=int(analysis.get("correlation_break_bootstrap_samples", self.config.break_bootstrap_samples)), seed=self.config.random_seed,
        )

        (
            b.rmt_full_summary,
            b.rmt_full_eigen,
            b.rmt_full_loadings,
            b.corr_rmt_cleaned_full,
        ) = rmt_diagnostics(ch, selected_days, self.config.min_matrix_obs)
        b.corr_rmt_cleaned = b.corr_rmt_cleaned_full

        peer_cols = [primary] + [
            c for c in ch.columns if c != primary and b.asset_type_map.get(c) == "Peer Equity"
        ]
        peer_cols = [c for c in peer_cols if c in ch.columns]
        if len(peer_cols) < 3:
            peer_cols = list(ch.columns)
        b.rmt_peer_universe = peer_cols
        (
            b.rmt_summary,
            b.rmt_eigen,
            b.rmt_loadings,
            _peer_cleaned,
        ) = rmt_diagnostics(ch[peer_cols], selected_days, self.config.min_matrix_obs)

        matrix_for_structure = b.corr_shrunk if not b.corr_shrunk.empty else b.corr_raw
        b.cluster_order = hierarchical_order(matrix_for_structure)
        b.mst_table = mst_edges(matrix_for_structure)
        b.partial_network_edges, b.partial_network_centrality = partial_network_edges(
            b.corr_partial,
            b.asset_type_map,
            threshold=self.config.partial_network_threshold,
            max_edges=self.config.partial_network_max_edges,
        )

        # Directional connectedness universe: override > homogeneous peers > top dependency links.
        supplied_conn = analysis.get("correlation_connectedness_universe")
        if isinstance(supplied_conn, (list, tuple)):
            conn = [str(x).upper().strip() for x in supplied_conn if str(x).upper().strip() in ch.columns]
            if primary in ch.columns and primary not in conn:
                conn.insert(0, primary)
        else:
            conn = [c for c in b.rmt_peer_universe if c in ch.columns]
            if len(conn) < 3 and not b.ranking.empty:
                conn = [primary] + [x for x in b.ranking["Ticker"].head(self.config.connectedness_max_assets - 1).tolist() if x in ch.columns]
        conn = list(dict.fromkeys(conn))[: self.config.connectedness_max_assets]
        b.connectedness_universe = conn
        b.connectedness_matrix, b.connectedness_table, b.connectedness_meta = connectedness_from_changes(
            ch,
            conn,
            days=max(selected_days, self.config.connectedness_window),
            horizon=self.config.connectedness_horizon,
            maxlags=self.config.connectedness_maxlags,
            min_obs=self.config.connectedness_min_obs,
        )

        b.frequency_connectedness, b.frequency_directional, b.frequency_meta = frequency_connectedness_from_changes(
            ch, conn, days=max(self.config.frequency_connectedness_days, selected_days),
            maxlags=self.config.connectedness_maxlags, min_obs=self.config.frequency_connectedness_min_obs,
        )
        b.partial_network_stability, b.partial_network_stability_meta = partial_network_stability(
            ch, conn, days=max(self.config.connectedness_window, selected_days),
            bootstrap_samples=int(analysis.get("correlation_network_bootstrap_samples", self.config.network_bootstrap_samples)), block=self.config.pair_bootstrap_block,
            threshold=self.config.partial_network_threshold, selection_threshold=self.config.network_selection_threshold,
            seed=self.config.random_seed,
        )

        hedge_type_map = {p: b.asset_type_map.get(p, "Unknown") for p in peers}
        b.hedges = hedge_candidates(primary, ch, peers, selected_days, self.config.hedge_windows, hedge_type_map)

        weights = analysis.get("portfolio_weights") or {}
        if isinstance(weights, dict) and weights:
            b.portfolio_table, b.portfolio_meta = portfolio_risk_decomposition(
                ch, weights, selected_days, b.asset_type_map
            )
            cluster_table = b.portfolio_meta.get("cluster_table")
            if isinstance(cluster_table, pd.DataFrame):
                b.portfolio_cluster_table = cluster_table
            b.portfolio_shock_table = correlation_shock_scenarios(
                ch, weights, selected_days, self.config.correlation_shock_levels
            )
            b.portfolio_incremental_table = incremental_asset_impact(
                ch,
                weights,
                list(ch.columns),
                selected_days,
                self.config.incremental_add_weight,
            )

            b.portfolio_eigen_table, b.portfolio_eigen_meta = portfolio_eigen_risk(
                ch, weights, days=max(selected_days, self.config.eigen_risk_days),
            )
            b.portfolio_structured_stress = structured_correlation_stress_scenarios(
                ch, weights, selected_days, b.asset_type_map
            )

        b.forward_corr_meta, b.forward_corr_history = forward_correlation_diagnostics(
            analysis,
            ch,
            default_realized_days=self.config.forward_realized_days,
        )

        b.summary = self._summary(b)
        return b

    def _summary(self, b: AnalysisBundle) -> dict:
        ranking = b.ranking
        peer = "N/A"; peer_corr = None
        if not ranking.empty:
            peer_rows = ranking[ranking["Type"] == "Peer Equity"]
            top = peer_rows.iloc[0] if not peer_rows.empty else ranking.iloc[0]
            peer, peer_corr = top["Ticker"], safe_float(top["Corr"])

        corr_change = None
        if not ranking.empty:
            vals = pd.to_numeric(ranking["ΔCorr 30D-1Y"], errors="coerce").dropna()
            corr_change = float(vals.abs().head(5).mean()) if len(vals) else None

        dominant_factor = "N/A"; factor_beta = None; factor_std_beta = None; factor_r2 = None
        if not b.factor_table.empty:
            topf = b.factor_table.iloc[0]
            dominant_factor = topf.get("Factor", "N/A")
            factor_beta = safe_float(topf.get("Raw Beta"))
            factor_std_beta = safe_float(topf.get("Standardized Beta"))
            factor_r2 = safe_float(topf.get("Incremental R²"))

        tail_peer = "N/A"; tail_lower = None; tail_ci_width = None
        tail_evidence_score = 0.0; tail_evidence = "Inconclusive"; tail_quality = "Fragile"
        tail_obs = 0; tail_horizon = None
        if not b.tail_table.empty and "Tail evidence score" in b.tail_table.columns:
            valid = b.tail_table.dropna(subset=["Tail evidence score"])
            if not valid.empty:
                tr = valid.iloc[0]
                tail_peer = tr.get("Ticker", "N/A")
                tail_lower = safe_float(tr.get("Emp lower co-exceedance"))
                tail_ci_width = safe_float(tr.get("Lower CI width"))
                tail_evidence_score = safe_float(tr.get("Tail evidence score"), 0.0) or 0.0
                tail_evidence = str(tr.get("Tail evidence", "Inconclusive"))
                tail_quality = str(tr.get("Tail quality", "Fragile"))
                tail_obs = int(tr.get("Lower tail obs") or 0)
                tail_horizon = int(tr.get("Tail horizon days") or 0)

        pc1 = safe_float(b.rmt_summary.get("pc1_variance")) if b.rmt_summary else None
        effective_rank = safe_float(b.rmt_summary.get("effective_rank")) if b.rmt_summary else None
        top_abs = pd.to_numeric(ranking.get("Corr"), errors="coerce").abs().head(5).mean() if not ranking.empty else np.nan
        cluster_score = clamp(20 + (0 if pd.isna(top_abs) else top_abs * 55) + (pc1 or 0) * 25)
        dependency_score = clamp(0.58 * cluster_score + 22 * max(corr_change or 0, 0) + 0.20 * tail_evidence_score)

        n = int(ranking["Obs"].max()) if not ranking.empty and "Obs" in ranking else 0
        confidence = 35 + min(35, n / 252 * 35)
        if tail_ci_width is not None:
            confidence += max(0, 15 * (1 - min(tail_ci_width, 1)))
        if not b.corr_shrunk.empty:
            confidence += 10
        if tail_quality == "Fragile":
            confidence -= 5
        elif tail_quality == "Adequate":
            confidence += 4
        if not b.regime_table.empty and "Stress quality" in b.regime_table.columns:
            fragile_share = (b.regime_table["Stress quality"] == "Fragile").mean()
            confidence -= 8 * float(fragile_share)
        confidence = clamp(confidence)

        best_hedge = "N/A"; best_hedge_type = "N/A"; hedge_reduction = None
        hedge_stability = "N/A"; hedge_oos = None; hedge_score = None
        if not b.hedges.empty:
            systematic_types = {"Benchmark", "ETF / Sector", "Rates ETF", "Credit ETF", "Commodity ETF", "FX", "Volatility", "Crypto"}
            systematic = b.hedges[b.hedges["Type"].isin(systematic_types)]
            hrow = systematic.iloc[0] if not systematic.empty else b.hedges.iloc[0]
            best_hedge = hrow.get("Hedge", "N/A")
            best_hedge_type = hrow.get("Type", "N/A")
            hedge_reduction = safe_float(hrow.get("Vol reduction"))
            hedge_stability = str(hrow.get("Stability", "N/A"))
            hedge_oos = safe_float(hrow.get("OOS vol reduction"))
            hedge_score = safe_float(hrow.get("Robust hedge score"))

        conn_tci = safe_float(b.connectedness_meta.get("TCI")) if b.connectedness_meta else None
        cov_champion = b.covariance_meta.get("champion") if b.covariance_meta else None
        break_p = safe_float(b.break_meta.get("bootstrap_pvalue")) if b.break_meta else None
        break_date = b.break_meta.get("break_date") if b.break_meta else None
        freq_short = None
        if not b.frequency_connectedness.empty:
            rr = b.frequency_connectedness[b.frequency_connectedness["Band"].astype(str).str.startswith("Short")]
            if not rr.empty: freq_short = safe_float(rr.iloc[0].get("Absolute TCI contribution"))
        net_transmitter = "N/A"; net_transmitter_value = None
        if not b.connectedness_table.empty:
            topc = b.connectedness_table.iloc[0]
            net_transmitter = str(topc.get("Asset", "N/A"))
            net_transmitter_value = safe_float(topc.get("NET transmitter"))

        forward_imp = safe_float(b.forward_corr_meta.get("implied_corr_clipped", b.forward_corr_meta.get("implied_corr"))) if b.forward_corr_meta else None
        forward_realized = safe_float(b.forward_corr_meta.get("realized_corr", b.forward_corr_meta.get("realized_corr_proxy"))) if b.forward_corr_meta else None
        forward_premium = safe_float(b.forward_corr_meta.get("correlation_risk_premium", b.forward_corr_meta.get("correlation_risk_premium_proxy"))) if b.forward_corr_meta else None

        return {
            "status": "ok",
            "dependency_score": dependency_score,
            "dependency_label": risk_label(dependency_score),
            "cluster_score": cluster_score,
            "peer": peer,
            "peer_corr": peer_corr,
            "corr_change": corr_change,
            "dominant_factor": dominant_factor,
            "factor_beta": factor_beta,
            "factor_standardized_beta": factor_std_beta,
            "factor_incremental_r2": factor_r2,
            "factor_multicollinearity": b.factor_meta.get("Multicollinearity", "N/A"),
            "tail_peer": tail_peer,
            "tail_lower": tail_lower,
            "tail_ci_width": tail_ci_width,
            "tail_evidence_score": tail_evidence_score,
            "tail_evidence": tail_evidence,
            "tail_quality": tail_quality,
            "tail_obs": tail_obs,
            "tail_horizon": tail_horizon,
            "tail_mode": b.tail_mode,
            "pc1_variance": pc1,
            "effective_rank": effective_rank,
            "rmt_peer_assets": len(b.rmt_peer_universe),
            "best_hedge": best_hedge,
            "best_hedge_type": best_hedge_type,
            "hedge_vol_reduction": hedge_reduction,
            "hedge_stability": hedge_stability,
            "hedge_oos_reduction": hedge_oos,
            "hedge_robust_score": hedge_score,
            "connectedness_tci": conn_tci,
            "connectedness_short_tci": freq_short,
            "covariance_champion": cov_champion,
            "covariance_champion_status": b.covariance_meta.get("champion_status") if b.covariance_meta else None,
            "covariance_runner_up": b.covariance_meta.get("runner_up") if b.covariance_meta else None,
            "covariance_champion_probability": safe_float(b.covariance_meta.get("champion_probability")) if b.covariance_meta else None,
            "break_pvalue": break_p,
            "break_date": break_date,
            "break_pvalue_resolution": safe_float(b.break_meta.get("pvalue_resolution")) if b.break_meta else None,
            "break_pvalue_at_floor": bool(b.break_meta.get("pvalue_at_floor")) if b.break_meta else False,
            "portfolio_top_eigen_risk": safe_float(b.portfolio_eigen_meta.get("top_mode_share")) if b.portfolio_eigen_meta else None,
            "net_transmitter": net_transmitter,
            "net_transmitter_value": net_transmitter_value,
            "forward_implied_corr": forward_imp,
            "forward_realized_corr": forward_realized,
            "forward_corr_premium": forward_premium,
            "portfolio_annualized_vol": safe_float(b.portfolio_meta.get("annualized_vol")) if b.portfolio_meta else None,
            "portfolio_cvar95": safe_float(b.portfolio_meta.get("CVaR95 daily")) if b.portfolio_meta else None,
            "portfolio_diversification_ratio": safe_float(b.portfolio_meta.get("diversification_ratio")) if b.portfolio_meta else None,
            "confidence_score": confidence,
            "confidence_label": "Bonne" if confidence >= 75 else "Correcte" if confidence >= 60 else "Limitée" if confidence >= 40 else "Fragile",
            "n_obs": n,
            "n_assets": int(b.changes.shape[1]),
            "data_source": b.data_source,
        }
