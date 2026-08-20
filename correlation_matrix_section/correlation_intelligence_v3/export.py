from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pandas as pd


def _csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=True).encode("utf-8")


def _json_safe_meta(d: dict | None) -> dict:
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, (pd.DataFrame, pd.Series)):
            continue
        out[k] = v
    return out


def research_pack_zip(bundle, config, metadata: dict | None = None) -> bytes:
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as z:
        meta = dict(metadata or {})
        meta["config"] = asdict(config) if is_dataclass(config) else str(config)
        meta["provider_map"] = getattr(bundle, "provider_map", {})
        meta["asset_type_map"] = getattr(bundle, "asset_type_map", {})
        meta["rmt_peer_universe"] = getattr(bundle, "rmt_peer_universe", [])
        meta["connectedness_universe"] = getattr(bundle, "connectedness_universe", [])
        meta["summary"] = getattr(bundle, "summary", {})
        meta["factor_meta"] = getattr(bundle, "factor_meta", {})
        meta["connectedness_meta"] = _json_safe_meta(getattr(bundle, "connectedness_meta", {}))
        meta["frequency_meta"] = _json_safe_meta(getattr(bundle, "frequency_meta", {}))
        meta["covariance_meta"] = _json_safe_meta(getattr(bundle, "covariance_meta", {}))
        meta["break_meta"] = _json_safe_meta(getattr(bundle, "break_meta", {}))
        meta["partial_network_stability_meta"] = _json_safe_meta(getattr(bundle, "partial_network_stability_meta", {}))
        meta["portfolio_eigen_meta"] = _json_safe_meta(getattr(bundle, "portfolio_eigen_meta", {}))
        meta["portfolio_meta"] = _json_safe_meta(getattr(bundle, "portfolio_meta", {}))
        meta["forward_corr_meta"] = _json_safe_meta(getattr(bundle, "forward_corr_meta", {}))
        z.writestr("metadata.json", json.dumps(meta, indent=2, default=str))

        frames = {
            "quality.csv": bundle.quality,
            "peer_ranking.csv": bundle.ranking,
            "term_structure.csv": bundle.term_structure,
            "factor_model.csv": bundle.factor_table,
            "tail_metrics.csv": bundle.tail_table,
            "tail_surface.csv": getattr(bundle, "tail_surface", pd.DataFrame()),
            "regimes.csv": bundle.regime_table,
            "stress.csv": bundle.stress_table,
            "rmt_peer_eigenvalues.csv": bundle.rmt_eigen,
            "rmt_peer_loadings.csv": bundle.rmt_loadings,
            "rmt_full_eigenvalues.csv": getattr(bundle, "rmt_full_eigen", pd.DataFrame()),
            "rmt_full_loadings.csv": getattr(bundle, "rmt_full_loadings", pd.DataFrame()),
            "mst_edges.csv": bundle.mst_table,
            "partial_network_edges.csv": getattr(bundle, "partial_network_edges", pd.DataFrame()),
            "partial_network_centrality.csv": getattr(bundle, "partial_network_centrality", pd.DataFrame()),
            "connectedness_matrix.csv": getattr(bundle, "connectedness_matrix", pd.DataFrame()),
            "connectedness_directional.csv": getattr(bundle, "connectedness_table", pd.DataFrame()),
            "connectedness_frequency.csv": getattr(bundle, "frequency_connectedness", pd.DataFrame()),
            "connectedness_frequency_directional.csv": getattr(bundle, "frequency_directional", pd.DataFrame()),
            "partial_network_stability.csv": getattr(bundle, "partial_network_stability", pd.DataFrame()),
            "dependency_break_curve.csv": getattr(bundle, "break_curve", pd.DataFrame()),
            "dependency_break_links.csv": getattr(bundle, "break_links", pd.DataFrame()),
            "covariance_model_validation.csv": getattr(bundle, "covariance_validation", pd.DataFrame()),
            "covariance_fold_losses.csv": getattr(bundle, "covariance_meta", {}).get("fold_losses", pd.DataFrame()),
            "connectedness_frequency_matrix_long.csv": getattr(bundle, "frequency_meta", {}).get("matrix_long", pd.DataFrame()),
            "corr_forecast_champion.csv": getattr(bundle, "corr_forecast", pd.DataFrame()),
            "hedge_candidates.csv": bundle.hedges,
            "portfolio_risk.csv": bundle.portfolio_table,
            "portfolio_clusters.csv": getattr(bundle, "portfolio_cluster_table", pd.DataFrame()),
            "portfolio_correlation_shocks.csv": getattr(bundle, "portfolio_shock_table", pd.DataFrame()),
            "portfolio_incremental_impact.csv": getattr(bundle, "portfolio_incremental_table", pd.DataFrame()),
            "portfolio_eigen_risk.csv": getattr(bundle, "portfolio_eigen_table", pd.DataFrame()),
            "portfolio_structured_stress.csv": getattr(bundle, "portfolio_structured_stress", pd.DataFrame()),
            "synchronization_audit.csv": getattr(bundle, "synchronization", pd.DataFrame()),
            "forward_correlation_history.csv": getattr(bundle, "forward_corr_history", pd.DataFrame()),
            "corr_raw.csv": bundle.corr_raw,
            "corr_shrunk.csv": bundle.corr_shrunk,
            "corr_partial.csv": bundle.corr_partial,
            "corr_rmt_cleaned_full.csv": getattr(bundle, "corr_rmt_cleaned_full", bundle.corr_rmt_cleaned),
            "levels.csv": bundle.levels,
            "changes.csv": bundle.changes,
        }
        cov = getattr(bundle, "portfolio_meta", {}).get("covariance") if hasattr(bundle, "portfolio_meta") else None
        if isinstance(cov, pd.DataFrame):
            frames["portfolio_covariance.csv"] = cov
        pret = getattr(bundle, "portfolio_meta", {}).get("portfolio_returns") if hasattr(bundle, "portfolio_meta") else None
        if isinstance(pret, pd.Series):
            frames["portfolio_returns.csv"] = pret.to_frame()

        for name, df in frames.items():
            if isinstance(df, pd.DataFrame) and not df.empty:
                z.writestr(name, _csv_bytes(df))
    return buf.getvalue()
