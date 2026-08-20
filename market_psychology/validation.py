from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _future_return(close: pd.Series, horizon: int) -> pd.Series:
    return close.shift(-horizon) / close - 1


def _future_realized_vol(ret: pd.Series, horizon: int) -> pd.Series:
    # Uses only future returns relative to each observation; suitable for ex-post validation labels.
    return ret.shift(-1).rolling(horizon).std().shift(-(horizon - 1)) * math.sqrt(TRADING_DAYS)


def _future_max_drawdown(close: pd.Series, horizon: int) -> pd.Series:
    values = close.to_numpy(dtype=float)
    out = np.full(len(values), np.nan)
    for i in range(len(values) - horizon):
        start = values[i]
        path = values[i + 1 : i + horizon + 1]
        if not np.isfinite(start) or start == 0 or len(path) == 0:
            continue
        out[i] = np.nanmin(path / start - 1.0)
    return pd.Series(out, index=close.index)


def build_forward_validation(history: pd.DataFrame, horizons: tuple[int, ...] = (5, 20, 60)) -> pd.DataFrame:
    if history is None or history.empty or "close" not in history.columns:
        return pd.DataFrame()
    work = history.copy().sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(work["close"], errors="coerce")
    ret = close.pct_change()
    score_cols = [c for c in ["attention", "fear", "herding", "extrapolation", "reflexivity"] if c in work.columns]
    rows: list[dict[str, Any]] = []

    for horizon in horizons:
        fwd_ret = _future_return(close, horizon)
        fwd_vol = _future_realized_vol(ret, horizon)
        fwd_dd = _future_max_drawdown(close, horizon)
        for score_col in score_cols:
            score = pd.to_numeric(work[score_col], errors="coerce")
            joined = pd.DataFrame({"score": score, "ret": fwd_ret, "vol": fwd_vol, "dd": fwd_dd}).dropna()
            if len(joined) < 40:
                continue
            try:
                corr_ret = float(joined["score"].corr(joined["ret"], method="spearman"))
                corr_vol = float(joined["score"].corr(joined["vol"], method="spearman"))
                corr_dd = float(joined["score"].corr(joined["dd"], method="spearman"))
            except Exception:
                corr_ret = corr_vol = corr_dd = np.nan

            q_low = joined["score"].quantile(0.2)
            q_high = joined["score"].quantile(0.8)
            low = joined[joined["score"] <= q_low]
            high = joined[joined["score"] >= q_high]
            rows.append({
                "Mechanism": score_col.title(),
                "Horizon": f"{horizon}D",
                "N": int(len(joined)),
                "Spearman → return": corr_ret,
                "Spearman → future vol": corr_vol,
                "Spearman → future drawdown": corr_dd,
                "Top quintile fwd return": float(high["ret"].mean()) if not high.empty else np.nan,
                "Bottom quintile fwd return": float(low["ret"].mean()) if not low.empty else np.nan,
                "Top - bottom": float(high["ret"].mean() - low["ret"].mean()) if not high.empty and not low.empty else np.nan,
            })
    return pd.DataFrame(rows)


def build_data_quality_table(state: dict[str, Any]) -> pd.DataFrame:
    if not isinstance(state, dict) or not state.get("available"):
        return pd.DataFrame()
    d = state.get("diagnostics", {})
    bdata = state.get("behavioral_data", {}) if isinstance(state.get("behavioral_data", {}), dict) else {}
    short_status = bdata.get("short_interest", {}) if isinstance(bdata.get("short_interest", {}), dict) else {}
    rows = [
        {
            "Component": "Price history",
            "Status": "OK" if d.get("rows", 0) >= 252 else "PARTIAL",
            "Coverage": f"{d.get('rows', 0)} daily rows",
            "Identification": "Observed market data",
        },
        {
            "Component": "News corpus",
            "Status": "OK" if d.get("news_count", 0) >= 30 and d.get("news_providers", 0) >= 2 else "PARTIAL" if d.get("news_count", 0) > 0 else "MISSING",
            "Coverage": f"{d.get('news_count', 0)} deduped / {d.get('news_raw_count', d.get('news_count',0))} raw · {d.get('news_providers',0)} providers · {d.get('news_sources',0)} sources",
            "Identification": "Multi-source current corpus; provider timestamps are observed, but the corpus is not yet a persistent historical point-in-time archive",
        },
        {
            "Component": "Narrative / belief NLP",
            "Status": "OK" if d.get("news_nlp_evidence", 0) >= 70 and d.get("news_semantic_validity", 0) >= 60 else "PARTIAL" if d.get("news_count", 0) > 0 else "MISSING",
            "Coverage": (
                f"NLP evidence {d.get('news_nlp_evidence','N/A')}/100 · semantic validity {d.get('news_semantic_validity','N/A')}/100 · "
                f"resolved {d.get('news_resolved_coverage','N/A')}% · label confidence {d.get('news_label_confidence','N/A')}/100 · "
                f"{d.get('news_story_count', d.get('news_count',0))} stories"
            ),
            "Identification": f"{d.get('nlp_backend','N/A')} · economic labels may remain OTHER / UNRESOLVED when support is weak; beliefs are calibrated model inferences, not direct surveys",
        },
        {
            "Component": "Options",
            "Status": "OK" if d.get("option_rows", 0) >= 100 else "PARTIAL" if d.get("option_rows", 0) > 0 else "MISSING",
            "Coverage": f"{d.get('option_rows', 0)} option rows",
            "Identification": "Public chain snapshot; no historical OPRA surface in fallback",
        },
        {
            "Component": "Cross-asset panel",
            "Status": "OK" if d.get("cross_asset_columns", 0) >= 5 else "PARTIAL",
            "Coverage": f"{d.get('cross_asset_columns', 0)} instruments",
            "Identification": "Observed price proxies",
        },
        {
            "Component": "Latent state engine",
            "Status": "OK" if d.get("latent_mechanisms", 0) >= 5 else "PARTIAL",
            "Coverage": f"{d.get('latent_mechanisms', 0)}/5 historical mechanisms · stability {d.get('latent_stability', 'N/A')}%",
            "Identification": f"{d.get('state_model', 'One-sided filter')} · causal filtering only; filtered state is an estimate, not direct psychology",
        },
        {
            "Component": "Calibration layer",
            "Status": "OK" if d.get("latent_mechanisms", 0) >= 5 else "PARTIAL",
            "Coverage": f"{d.get('latent_mechanisms', 0)}/5 mechanisms causally normalized",
            "Identification": "Instrument-relative rolling robust calibration; 50 means historical centre for that proxy, not an absolute psychological truth",
        },
        {
            "Component": "Observed behavioral-data layer",
            "Status": "OK" if d.get("behavioral_data_evidence", 0) >= 70 else "PARTIAL" if d.get("behavioral_data_availability", 0) > 0 else "MISSING",
            "Coverage": (
                f"availability {d.get('behavioral_data_availability',0)}% · freshness {d.get('behavioral_data_freshness',0)}% · "
                f"identification {d.get('behavioral_data_identification',0)}% · evidence {d.get('behavioral_data_evidence',0)}/100"
            ),
            "Identification": "Completeness, source freshness and identification quality are scored separately; this is not model confidence.",
        },
        {
            "Component": "Behavioral Memory Engine",
            "Status": "OK" if d.get("memory_available") and d.get("memory_structural_count",0) > 0 else "PARTIAL" if d.get("memory_available") else "MISSING",
            "Coverage": (
                f"best similarity {d.get('memory_best_similarity') if d.get('memory_best_similarity') is not None else 'N/A'} · "
                f"activation {d.get('memory_activation') if d.get('memory_activation') is not None else 'N/A'} · "
                f"structural {d.get('memory_structural_count',0)} · memory candidates {d.get('memory_candidate_count',0)} · "
                f"usable domains {d.get('memory_usable_domains',0)}/{d.get('memory_domain_total',8)} · archive {d.get('memory_archive_snapshots',0)} snapshots"
            ),
            "Identification": "Adaptive observed-domain retrieval; memory candidates must clear both structural similarity and activation thresholds. CFTC is publication-lag aligned; narrative/options history is archive-only; funding history remains current-vintage unless ALFRED is connected.",
        },
        {
            "Component": "Volatility / tail structure",
            "Status": "OK" if d.get("volatility_tail_available") and d.get("volatility_tail_coverage", 0) >= 3 else "PARTIAL" if d.get("vix_available") else "MISSING",
            "Coverage": f"{d.get('volatility_tail_coverage',0)}/5 indices · VIX {d.get('vix_level') if d.get('vix_level') is not None else 'N/A'} · VVIX {d.get('vvix_level') if d.get('vvix_level') is not None else 'N/A'} · VIX9D {d.get('vix9d_level') if d.get('vix9d_level') is not None else 'N/A'} · SKEW {d.get('skew_level') if d.get('skew_level') is not None else 'N/A'}",
            "Identification": "Observed volatility-index structure; constrains tail-risk inference but is not direct emotion.",
        },
        {
            "Component": "Breadth / participation",
            "Status": "OK" if d.get("breadth_available") else "PARTIAL" if d.get("breadth_coverage", 0) > 0 else "MISSING",
            "Coverage": f"{d.get('breadth_coverage',0)} ETF proxies · core {d.get('breadth_core_coverage',0)}/7 · sectors {d.get('breadth_sector_coverage',0)}/11 · breadth score {d.get('breadth_score') if d.get('breadth_score') is not None else 'N/A'}",
            "Identification": "Equal-weight, factor and sector ETF breadth; not constituent-level advance/decline statistics.",
        },
        {
            "Component": "CFTC positioning",
            "Status": "OK" if d.get("positioning_available") else "MISSING",
            "Coverage": f"Crowding {d.get('positioning_crowding_score') if d.get('positioning_crowding_score') is not None else 'N/A'}",
            "Identification": "Weekly TFF broad-equity futures positioning; daily historical use is aligned to conservative publication availability rather than the Tuesday report date. Not single-stock positioning or a direct belief survey.",
        },
        {
            "Component": "Funding / credit constraints",
            "Status": "OK" if d.get("funding_credit_available") else "MISSING",
            "Coverage": f"{d.get('funding_credit_coverage',0)} public series · stress {d.get('funding_stress_score') if d.get('funding_stress_score') is not None else 'N/A'}",
            "Identification": "Observed public credit spreads and financial-condition indexes; improves constraint-state identification.",
        },
        {
            "Component": "Options behavioral footprint",
            "Status": "OK" if d.get("options_behavior_available") and d.get("option_rows",0) >= 100 else "PARTIAL" if d.get("option_rows",0) > 0 else "MISSING",
            "Coverage": (
                f"{d.get('option_rows',0)} rows · current snapshot · tenor denominator "
                f"{((bdata.get('options_behavior',{}).get('metrics',{}) if isinstance(bdata.get('options_behavior',{}),dict) else {}).get('tenor_denominator_status','N/A'))}"
            ),
            "Identification": "Moneyness/tenor/IV/OI concentration are observed snapshot metrics; short-tenor shares are suppressed if the loaded chain does not extend beyond 30D; no historical OPRA or signed dealer gamma.",
        },
        {
            "Component": "Short interest / borrow",
            "Status": "OK" if d.get("short_interest_available") else "MISSING",
            "Coverage": str(short_status.get("status", "Not connected")),
            "Identification": str(short_status.get("note", "Dedicated FINRA/borrow feed required.")),
        },
        {
            "Component": "Social graph / investor-level diffusion",
            "Status": "MISSING",
            "Coverage": "Not connected",
            "Identification": "Social-contagion score must remain low-confidence until a graph/text provider is connected",
        },
        {
            "Component": "Surveys / direct beliefs",
            "Status": "MISSING",
            "Coverage": "Not connected",
            "Identification": "Confidence and higher-order beliefs are inferred, not directly observed",
        },
        {
            "Component": "Signed dealer gamma / systematic flows",
            "Status": "MISSING",
            "Coverage": "Not connected",
            "Identification": "V2.2.1 observes option concentration and volatility structure but does not infer signed dealer inventory or systematic-strategy flows.",
        },
    ]
    return pd.DataFrame(rows)


def research_protocol_table() -> pd.DataFrame:
    return pd.DataFrame([
        {"Rule": "Point-in-time corpus", "Requirement": "Archive the exact news/text/options snapshot available at each historical timestamp. Never backfill revised text into old dates.", "Priority": "CRITICAL"},
        {"Rule": "Point-in-time behavioral memory", "Requirement": "Archive derived narrative/options/behavioral snapshots prospectively. Historical memory retrieval must expose missing domains rather than reconstruct them with future information; use ALFRED vintages before treating revised macro history as fully point-in-time.", "Priority": "CRITICAL"},
        {"Rule": "Model/version locking", "Requirement": "Persist feature code version, lexicon/prompt/model version and parameters for every historical inference.", "Priority": "CRITICAL"},
        {"Rule": "Separate observation from inference", "Requirement": "Store raw proxies and latent scores independently; do not relabel VIX, skew or flows as direct emotions.", "Priority": "CRITICAL"},
        {"Rule": "Walk-forward validation", "Requirement": "Estimate/calibrate only on past windows; evaluate on chronological future blocks. Purge at least the forecast horizon so training labels never overlap the next test block.", "Priority": "CRITICAL"},
        {"Rule": "Final holdout", "Requirement": "Reserve a final untouched chronological block and report it separately from development walk-forward results. Never pool holdout observations back into development significance.", "Priority": "CRITICAL"},
        {"Rule": "Overlapping-label inference", "Requirement": "Use HAC/Newey-West inference and moving-block bootstrap confidence intervals for multi-day forward labels; naive iid p-values are secondary diagnostics only.", "Priority": "CRITICAL"},
        {"Rule": "Multiple-testing control", "Requirement": "Track the full mechanism × horizon × target hypothesis family and apply false-discovery controls before calling development evidence robust.", "Priority": "CRITICAL"},
        {"Rule": "Memory decision-time integrity", "Requirement": "At historical date t, admit only analogue states and analogue forward outcomes that would already have been observable by t; require multiple admissible analogues before producing a memory forecast.", "Priority": "CRITICAL"},
        {"Rule": "Target distribution", "Requirement": "Test return, volatility, skew, drawdown, liquidity and regime change — not only mean return.", "Priority": "HIGH"},
        {"Rule": "Universe robustness", "Requirement": "Validate across indices, single names, sectors and time periods; report failures as well as successes.", "Priority": "HIGH"},
        {"Rule": "No production promotion by score aesthetics", "Requirement": "A visually convincing regime label has zero production weight until OOS evidence exists.", "Priority": "CRITICAL"},
    ])


def build_latent_filter_diagnostics(history: pd.DataFrame) -> pd.DataFrame:
    """Research diagnostics for normalization/filter mechanics; not evidence of trading value."""
    if history is None or history.empty:
        return pd.DataFrame()
    rows = []
    for key in ["attention", "fear", "herding", "extrapolation", "reflexivity"]:
        raw_col = f"{key}_raw"
        norm_col = f"{key}_normalized"
        latent_col = f"{key}_latent" if f"{key}_latent" in history.columns else key
        if raw_col not in history.columns or norm_col not in history.columns or latent_col not in history.columns:
            continue
        raw = pd.to_numeric(history[raw_col], errors="coerce")
        normalized = pd.to_numeric(history[norm_col], errors="coerce")
        latent = pd.to_numeric(history[latent_col], errors="coerce")
        joined = pd.DataFrame({"raw": raw, "normalized": normalized, "latent": latent}).dropna()
        if len(joined) < 40:
            continue
        raw_churn = float(joined["raw"].diff().abs().mean())
        normalized_churn = float(joined["normalized"].diff().abs().mean())
        latent_churn = float(joined["latent"].diff().abs().mean())
        reduction = 1.0 - latent_churn / normalized_churn if normalized_churn > 1e-12 else np.nan
        corr = float(joined["normalized"].corr(joined["latent"])) if len(joined) > 2 else np.nan
        ar1 = float(joined["latent"].autocorr(1)) if len(joined) > 3 else np.nan
        shock_col = f"{key}_shock_z"
        sd_col = f"{key}_state_sd"
        shock = pd.to_numeric(history.get(shock_col, np.nan), errors="coerce")
        state_sd = pd.to_numeric(history.get(sd_col, np.nan), errors="coerce")
        raw_sat = float(((joined["raw"] <= 0.5) | (joined["raw"] >= 99.5)).mean())
        rows.append({
            "Mechanism": key.title(),
            "N": int(len(joined)),
            "Raw daily churn": raw_churn,
            "Normalized daily churn": normalized_churn,
            "Latent daily churn": latent_churn,
            "Normalized→latent noise reduction": reduction,
            "Normalized median": float(joined["normalized"].median()),
            "Raw saturation share": raw_sat,
            "Normalized ↔ latent corr": corr,
            "Latent AR(1)": ar1,
            "Shock z ≥ +2 share": float((shock >= 2).mean()) if isinstance(shock, pd.Series) else np.nan,
            "Shock z ≤ -2 share": float((shock <= -2).mean()) if isinstance(shock, pd.Series) else np.nan,
            "Median state uncertainty": float(state_sd.median()) if isinstance(state_sd, pd.Series) and state_sd.notna().any() else np.nan,
        })
    return pd.DataFrame(rows)

