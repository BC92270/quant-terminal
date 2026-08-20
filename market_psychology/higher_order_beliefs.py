"""Higher-Order Beliefs research engine inside Market Psychology Lab.

V3.4 is an *experimental* research overlay.  It does not feed back into the
frozen V2.5.3 Psychology specification, its alarms, memory engine, walk-forward
validation or external-replication baseline.

Research foundations
--------------------
- Morris & Shin (2002), Social Value of Public Information.
- Camerer, Ho & Chong (2004), A Cognitive Hierarchy Model of Games.
- Allen, Morris & Shin (2006), Beauty Contests and Iterated Expectations in Asset Markets.
- Banerjee, Kaniel & Kremer (2009), Price Drift as an Outcome of Differences in Higher-Order Beliefs.
- Huo & Takayama (2025), Rational Expectations Models with Higher-Order Beliefs.
- Schmidt-Engelbertz & Vasudevan (2025), Speculating on Higher-Order Beliefs.
- Gorodnichenko & Yin (2026), Higher-Order Beliefs and Risky Asset Holdings.

The implementation is deliberately an identification architecture rather than a
claim that beliefs are directly observed. V3.4 hardens chronology integrity, separates
structural identification from direct belief evidence, and adds a deterministic
regime-feasibility audit before any taxonomy freeze.  B1/B2/B3 are latent market proxies.
Uncertainty numbers are measurement-uncertainty proxies, not statistical
standard errors, and standardized wedges are signal-to-uncertainty ratios, not
t-statistics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import math
import os
import hashlib
from typing import Any, Mapping

import numpy as np
import pandas as pd


HOB_RESEARCH_VERSION = "HOB-V3.4"
_ARCHIVE_COLUMNS = [
    "date", "symbol", "version", "b1", "b2", "b3", "u1", "u2", "u3",
    "d1", "d2", "d3", "speculative_gap", "meta_gap",
    "speculative_snr", "meta_snr", "higher_order_dominance",
    "common_knowledge_intensity", "coordination_pressure",
    "strategic_fragility", "reflexive_price_pressure", "alpha_proxy",
    "tau_proxy", "identification_confidence", "regime",
    "fundamental_anchor", "fundamental_anchor_quality", "fundamental_anchor_source", "price_fundamental_gap",
    "b1_identification", "b2_identification", "b3_identification",
    "source_independence", "effective_source_families", "anchor_temporal_integrity",
    "fundamental_anchor_pit", "fundamental_revision_gap", "pit_anchor_quality",
    "direct_belief_score", "direct_belief_source",
    "state_space_b1", "state_space_b2", "state_space_b3",
    "state_space_u1", "state_space_u2", "state_space_u3", "state_space_agreement",
    "chronology_status", "chronology_score", "taxonomy_feasibility", "spec_freeze_status",
    "b1_direct_evidence", "b2_direct_evidence", "b3_direct_evidence",
]


def _finite(x: Any) -> float | None:
    try:
        v = float(x)
        return v if np.isfinite(v) else None
    except Exception:
        return None


def _clip(x: Any, lo: float = 0.0, hi: float = 100.0, default: float = 50.0) -> float:
    v = _finite(x)
    if v is None:
        return float(default)
    return float(np.clip(v, lo, hi))


def _center(x: Any) -> float:
    return (_clip(x) - 50.0) / 50.0


def _score(x: float) -> float:
    return float(np.clip(50.0 + 50.0 * float(x), 0.0, 100.0))


def _mean_available(values: list[Any], default: float = 50.0) -> float:
    vals = [float(v) for v in (_finite(x) for x in values) if v is not None]
    return float(np.mean(vals)) if vals else float(default)


def _metric(mapping: Mapping[str, Any] | None, key: str, default: float | None = None) -> float | None:
    if not isinstance(mapping, Mapping):
        return default
    v = _finite(mapping.get(key))
    return v if v is not None else default


def _mapping(obj: Any) -> Mapping[str, Any]:
    return obj if isinstance(obj, Mapping) else {}


@dataclass(frozen=True)
class HOBConfig:
    strategic_complementarity: float = 0.55
    cognitive_hierarchy_tau: float = 1.50
    max_cognitive_level: int = 6
    uncertainty_multiplier: float = 1.0
    fundamental_anchor: float | None = None
    parameter_mode: str = "SCENARIO"


@dataclass(frozen=True)
class HOBInputs:
    # First-order / state information
    first_order_conviction: float = 50.0
    private_signal_proxy: float = 50.0
    risk_appetite: float = 50.0
    extrapolation: float = 50.0
    fundamental_anchor: float | None = None
    fundamental_anchor_quality: float = 0.0
    fundamental_anchor_source: str = "NONE"
    fundamental_anchor_temporal_integrity: str = "UNAVAILABLE"
    market_price_state: float = 50.0

    # Public/common/crowd information
    public_consensus: float = 50.0
    public_signal_quality: float = 50.0
    narrative_consensus: float = 50.0
    narrative_concentration: float = 50.0
    narrative_evidence: float = 50.0
    belief_disagreement: float = 50.0
    sentiment_dispersion: float = 50.0

    # Strategic / feedback footprints
    attention: float = 50.0
    herding: float = 50.0
    reflexivity: float = 50.0
    positioning_crowding: float = 50.0
    flow_pressure: float = 50.0
    options_speculation: float = 50.0
    breadth: float = 50.0
    arbitrage_capacity: float = 50.0

    # Identification quality / ambiguity
    uncertainty: float = 50.0
    belief_confidence: float = 50.0
    latent_stability: float = 50.0
    behavioral_data_evidence: float = 50.0
    nlp_evidence: float = 50.0
    resolved_narrative_coverage: float = 50.0


@dataclass(frozen=True)
class HOBResult:
    b1: float
    b2: float
    b3: float
    u1: float
    u2: float
    u3: float
    d1: float
    d2: float
    d3: float
    speculative_gap: float
    meta_gap: float
    speculative_snr: float
    meta_snr: float
    iterated_expectations_value: float
    cognitive_hierarchy_value: float
    strategic_price_wedge: float
    higher_order_dominance: float
    coordination_pressure: float
    common_knowledge_index: float
    common_knowledge_intensity: float
    public_private_wedge: float
    strategic_fragility: float
    reflexive_price_pressure: float
    cognitive_depth: float
    alpha_proxy: float
    tau_proxy: float
    market_price_state: float
    fundamental_anchor: float | None
    fundamental_anchor_quality: float
    fundamental_anchor_source: str
    fundamental_anchor_temporal_integrity: str
    price_fundamental_gap: float | None
    b1_identification: float
    b2_identification: float
    b3_identification: float
    source_independence: float
    effective_source_families: float
    regime: str
    regime_strength: float
    identification_confidence: float
    identification_grade: str


    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# V3.2 · Independent fundamental anchor + identification architecture
# ---------------------------------------------------------------------------
_BROAD_US_EQUITY_SYMBOLS = {
    "SPY", "IVV", "VOO", "VTI", "DIA", "QQQ", "IWM", "RSP", "QQEW",
}

_FUNDAMENTAL_SERIES = {
    # series_id, label, transform, direction, weight, expected release cadence (days)
    "corporate_profits": ("CP", "Corporate profits after tax", "yoy_q", +1.0, 0.18, 130),
    "unit_profits": ("A466RD3Q052SBEA", "Unit corporate profits", "yoy_q", +1.0, 0.10, 130),
    "real_gdp": ("GDPC1", "Real GDP", "yoy_q", +1.0, 0.12, 130),
    "industrial_production": ("INDPRO", "Industrial production", "yoy_m", +1.0, 0.15, 50),
    "unemployment": ("UNRATE", "Unemployment 6M change", "diff6_m", -1.0, 0.10, 50),
    "real_yield": ("DFII10", "10Y real yield", "level", -1.0, 0.12, 10),
    "hy_oas": ("BAMLH0A0HYM2", "HY option-adjusted spread", "level", -1.0, 0.13, 10),
    "nfci": ("NFCI", "Chicago Fed financial conditions", "level", -1.0, 0.10, 18),
}

_IDENTIFICATION_TIER_SCORE = {
    "DIRECT_SURVEY": 1.00,
    "NEAR_DIRECT_SURVEY": 0.86,
    "OBSERVED_FUNDAMENTAL": 0.88,
    "OBSERVED_MARKET": 0.74,
    "PUBLIC_TEXT_DERIVED": 0.62,
    "LATENT_PROXY": 0.48,
    "INFERRED_PROXY": 0.36,
    "MISSING": 0.00,
}


def _robust_series_z(series: pd.Series, window: int = 60, min_periods: int = 18) -> pd.Series:
    """Rolling robust z-score using only contemporaneous/current-vintage history.

    It is a normalization diagnostic, not point-in-time vintage reconstruction.
    """
    s = pd.to_numeric(series, errors="coerce").astype(float)
    med = s.rolling(window, min_periods=min_periods).median()
    mad = (s - med).abs().rolling(window, min_periods=min_periods).median()
    scale = 1.4826 * mad
    fallback = s.rolling(window, min_periods=min_periods).std(ddof=1)
    scale = scale.where(scale > 1e-9, fallback)
    z = (s - med) / scale.replace(0, np.nan)
    return z.clip(-3.5, 3.5)


def _transform_fundamental_series(df: pd.DataFrame, transform: str) -> pd.Series:
    if not isinstance(df, pd.DataFrame) or df.empty or "date" not in df.columns or "value" not in df.columns:
        return pd.Series(dtype=float)
    x = df[["date", "value"]].copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce", utc=True)
    x["value"] = pd.to_numeric(x["value"], errors="coerce")
    x = x.dropna().drop_duplicates("date", keep="last").sort_values("date")
    if x.empty:
        return pd.Series(dtype=float)
    s = pd.Series(x["value"].to_numpy(dtype=float), index=pd.DatetimeIndex(x["date"]), dtype=float)
    if transform == "yoy_q":
        s = s.pct_change(4) * 100.0
    elif transform == "yoy_m":
        s = s.pct_change(12) * 100.0
    elif transform == "diff6_m":
        s = s.diff(6)
    return s.replace([np.inf, -np.inf], np.nan).dropna()


def _fundamental_component_score(series: pd.Series, direction: float) -> tuple[float | None, float | None, pd.Series]:
    if series.empty:
        return None, None, pd.Series(dtype=float)
    # Monthly grid avoids pretending quarterly observations are daily information.
    monthly = series.resample("ME").last().ffill(limit=4)
    z = _robust_series_z(monthly, window=60, min_periods=18)
    if z.dropna().empty:
        # Conservative fallback for short histories: expanding median / std.
        med = monthly.expanding(min_periods=8).median()
        std = monthly.expanding(min_periods=8).std(ddof=1).replace(0, np.nan)
        z = ((monthly - med) / std).clip(-3.5, 3.5)
    score_hist = (50.0 + 15.0 * float(direction) * z).clip(0.0, 100.0)
    latest_raw = _finite(series.iloc[-1])
    latest_score = _finite(score_hist.dropna().iloc[-1]) if not score_hist.dropna().empty else None
    return latest_raw, latest_score, score_hist


def build_fundamental_anchor(state: Mapping[str, Any], symbol: str | None = None) -> dict[str, Any]:
    """Build a price-independent broad-US-equity fundamental *state* anchor.

    The anchor deliberately uses official macro/fundamental series rather than price
    momentum. FRED data are current-vintage here, so the historical diagnostic is NOT
    ALFRED point-in-time and cannot be promoted into HOB predictive validation.
    """
    sym = str(symbol or state.get("symbol", "")).upper().strip()
    if sym not in _BROAD_US_EQUITY_SYMBOLS:
        return {
            "status": "UNSUPPORTED_SYMBOL", "anchor": None, "quality": 0.0,
            "coverage": 0.0, "freshness": 0.0, "temporal_integrity": "N/A",
            "source": "NONE", "components": pd.DataFrame(), "history": pd.DataFrame(),
            "note": "Automatic macro-fundamental anchor is currently restricted to broad U.S. equity proxies; use an independent manual/company model for single stocks.",
        }
    try:
        from .behavioral_data import _fetch_fred_series  # same package; cached and key-aware
    except Exception as exc:
        return {
            "status": "PROVIDER_IMPORT_ERROR", "anchor": None, "quality": 0.0,
            "coverage": 0.0, "freshness": 0.0, "temporal_integrity": "CURRENT_VINTAGE",
            "source": "FRED", "components": pd.DataFrame(), "history": pd.DataFrame(),
            "note": f"FRED helper unavailable: {type(exc).__name__}",
        }

    now = pd.Timestamp.now(tz="UTC")
    rows: list[dict[str, Any]] = []
    hist_parts: dict[str, pd.Series] = {}
    available_weight = 0.0
    weighted_score = 0.0
    weighted_freshness = 0.0
    total_weight = sum(v[4] for v in _FUNDAMENTAL_SERIES.values())
    for key, (series_id, label, transform, direction, weight, cadence_days) in _FUNDAMENTAL_SERIES.items():
        try:
            df, meta = _fetch_fred_series(series_id, "10y")
        except Exception as exc:
            df, meta = pd.DataFrame(), {"status": "request_error", "detail": type(exc).__name__}
        transformed = _transform_fundamental_series(df, transform)
        raw, score, score_hist = _fundamental_component_score(transformed, direction)
        last_date = transformed.index[-1] if not transformed.empty else pd.NaT
        age_days = float((now - last_date).total_seconds() / 86400.0) if pd.notna(last_date) else np.nan
        # Freshness is cadence-aware: quarterly series are not penalized as if daily.
        freshness = 0.0 if not np.isfinite(age_days) else float(np.clip(100.0 * (1.0 - max(0.0, age_days - cadence_days * 0.25) / max(cadence_days * 1.5, 1.0)), 0.0, 100.0))
        ok = score is not None
        if ok:
            available_weight += float(weight)
            weighted_score += float(weight) * float(score)
            weighted_freshness += float(weight) * freshness
            if not score_hist.empty:
                hist_parts[key] = score_hist.rename(key)
        rows.append({
            "Component": label, "Series": series_id, "Transform": transform,
            "Direction": "+" if direction > 0 else "−", "Weight": float(weight),
            "Latest transformed": raw, "Component score": score,
            "Last observation": None if pd.isna(last_date) else str(pd.Timestamp(last_date).date()),
            "Age days": None if not np.isfinite(age_days) else age_days,
            "Freshness": freshness, "Status": "OK" if ok else str(meta.get("status", "MISSING")).upper(),
        })

    coverage = 100.0 * available_weight / max(total_weight, 1e-12)
    anchor = weighted_score / available_weight if available_weight > 0 else None
    freshness = weighted_freshness / available_weight if available_weight > 0 else 0.0
    # Official observations are high quality, but current-vintage (non-ALFRED) history
    # prevents a perfect temporal-integrity score for research validation.
    temporal_integrity_score = 72.0
    quality = float(np.clip(0.50 * coverage + 0.32 * freshness + 0.18 * temporal_integrity_score, 0.0, 88.0)) if anchor is not None else 0.0

    history = pd.DataFrame()
    if hist_parts:
        history = pd.concat(hist_parts.values(), axis=1).sort_index()
        weights = {k: _FUNDAMENTAL_SERIES[k][4] for k in hist_parts}
        num = pd.Series(0.0, index=history.index)
        den = pd.Series(0.0, index=history.index)
        for k in history.columns:
            v = pd.to_numeric(history[k], errors="coerce")
            w = float(weights[k])
            mask = v.notna()
            num.loc[mask] = num.loc[mask] + w * v.loc[mask]
            den.loc[mask] = den.loc[mask] + w
        history["Fundamental anchor · current-vintage"] = (num / den.replace(0, np.nan)).clip(0, 100)
        history = history.reset_index().rename(columns={"index": "date"})

    status = "OK" if anchor is not None and coverage >= 65 else "PARTIAL" if anchor is not None else "MISSING"
    return {
        "status": status,
        "anchor": None if anchor is None else float(np.clip(anchor, 0, 100)),
        "quality": quality,
        "coverage": float(coverage),
        "freshness": float(freshness),
        "temporal_integrity": "CURRENT_VINTAGE · NOT ALFRED/PIT",
        "source": "FRED / official macro-fundamental series",
        "components": pd.DataFrame(rows),
        "history": history,
        "note": "Independent normalized fundamental environment state; not a fair-value price and not point-in-time vintage history.",
    }


def _identification_rows(i: HOBInputs) -> list[dict[str, Any]]:
    """Measurement map used to score directness, quality and source independence."""
    anchor_tier = "OBSERVED_FUNDAMENTAL" if i.fundamental_anchor is not None else "MISSING"
    aq = _clip(i.fundamental_anchor_quality, default=0.0)
    rows = [
        # order, input, tier, family, identification weight, measurement quality
        ("B1", "Fundamental anchor", anchor_tier, "FUNDAMENTAL", 0.32, aq),
        ("B1", "First-order conviction", "INFERRED_PROXY", "BEHAVIORAL_LATENT", 0.24, _mean_available([i.belief_confidence, i.latent_stability])),
        ("B1", "Private/state proxy", "INFERRED_PROXY", "BEHAVIORAL_LATENT", 0.17, _mean_available([i.belief_confidence, 100-i.uncertainty])),
        ("B1", "Breadth", "OBSERVED_MARKET", "BREADTH", 0.11, i.behavioral_data_evidence),
        ("B1", "Risk appetite", "LATENT_PROXY", "MARKET_STATE", 0.10, i.latent_stability),
        ("B1", "Extrapolation", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.06, i.latent_stability),
        ("B2", "Public consensus", "INFERRED_PROXY", "NLP_PUBLIC", 0.24, i.nlp_evidence),
        ("B2", "Narrative consensus", "PUBLIC_TEXT_DERIVED", "NLP_PUBLIC", 0.17, i.nlp_evidence),
        ("B2", "Herding", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.12, i.latent_stability),
        ("B2", "Flow pressure", "INFERRED_PROXY", "FLOW", 0.11, i.behavioral_data_evidence),
        ("B2", "Positioning crowding", "OBSERVED_MARKET", "POSITIONING", 0.10, i.behavioral_data_evidence),
        ("B2", "Attention", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.07, i.latent_stability),
        ("B2", "Options speculation", "OBSERVED_MARKET", "OPTIONS", 0.05, i.behavioral_data_evidence),
        ("B2", "Belief disagreement", "PUBLIC_TEXT_DERIVED", "NLP_PUBLIC", 0.14, i.nlp_evidence),
        ("B3", "Reflexivity", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.22, i.latent_stability),
        ("B3", "Attention", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.14, i.latent_stability),
        ("B3", "Flow pressure", "INFERRED_PROXY", "FLOW", 0.13, i.behavioral_data_evidence),
        ("B3", "Positioning crowding", "OBSERVED_MARKET", "POSITIONING", 0.12, i.behavioral_data_evidence),
        ("B3", "Options speculation", "OBSERVED_MARKET", "OPTIONS", 0.11, i.behavioral_data_evidence),
        ("B3", "Narrative concentration", "PUBLIC_TEXT_DERIVED", "NLP_PUBLIC", 0.10, i.nlp_evidence),
        ("B3", "Narrative consensus", "PUBLIC_TEXT_DERIVED", "NLP_PUBLIC", 0.08, i.nlp_evidence),
        ("B3", "Herding", "LATENT_PROXY", "BEHAVIORAL_LATENT", 0.05, i.latent_stability),
        ("B3", "Belief disagreement", "PUBLIC_TEXT_DERIVED", "NLP_PUBLIC", 0.05, i.nlp_evidence),
    ]
    out: list[dict[str, Any]] = []
    for order, name, tier, family, weight, quality in rows:
        out.append({
            "Order": order, "Input": name, "Tier": tier, "Source family": family,
            "Weight": float(weight), "Directness": 100.0 * _IDENTIFICATION_TIER_SCORE[tier],
            "Quality": _clip(quality), "Available": tier != "MISSING",
        })
    return out


def identification_matrix(i: HOBInputs) -> tuple[pd.DataFrame, dict[str, Any]]:
    df = pd.DataFrame(_identification_rows(i))
    summaries: dict[str, Any] = {}
    for order in ["B1", "B2", "B3"]:
        d = df[df["Order"] == order].copy()
        total = float(d["Weight"].sum()) or 1.0
        avail = d[d["Available"]].copy()
        coverage = float(avail["Weight"].sum() / total)
        if avail.empty:
            directness = quality = independence = eff = score = 0.0
        else:
            w = avail["Weight"].to_numpy(float)
            w = w / max(float(w.sum()), 1e-12)
            directness = float(np.dot(w, avail["Directness"].to_numpy(float))) / 100.0
            quality = float(np.dot(w, avail["Quality"].to_numpy(float))) / 100.0
            fam = avail.groupby("Source family")["Weight"].sum().astype(float)
            fw = fam / max(float(fam.sum()), 1e-12)
            hhi = float(np.sum(np.square(fw.to_numpy(float))))
            eff = 1.0 / max(hhi, 1e-12)
            independence = float(np.clip((eff - 1.0) / 4.0, 0.0, 1.0))
            score = 100.0 * (0.34 * directness + 0.30 * quality + 0.20 * coverage + 0.16 * independence)
            # Until direct higher-order surveys exist, B2/B3 must not appear institutionally "high".
            if order == "B2" and not (avail["Tier"] == "DIRECT_SURVEY").any():
                score = min(score, 74.0)
            if order == "B3" and not (avail["Tier"] == "DIRECT_SURVEY").any():
                score = min(score, 67.0)
        summaries[order] = {
            "score": float(score), "coverage": 100.0 * coverage,
            "directness": 100.0 * directness, "quality": 100.0 * quality,
            # Canonical per-order names. Keep the short aliases for backward compatibility
            # with V3.2/V3.3 internal callers and expose the descriptive names used by UI.
            "independence": 100.0 * independence,
            "source_independence": 100.0 * independence,
            "effective_families": float(eff),
            "effective_source_families": float(eff),
        }
    summaries["overall_independence"] = float(np.mean([summaries[o]["independence"] for o in ["B1", "B2", "B3"]]))
    summaries["effective_source_families"] = float(np.mean([summaries[o]["effective_families"] for o in ["B1", "B2", "B3"]]))
    return df, summaries


def _input_sigma_map(i: HOBInputs) -> dict[str, float]:
    """Input-space uncertainty widths for deterministic measurement propagation."""
    idf, _ = identification_matrix(i)
    quality_by_name = idf.groupby("Input").agg({"Directness": "max", "Quality": "max"})
    alias = {
        "first_order_conviction": "First-order conviction", "private_signal_proxy": "Private/state proxy",
        "risk_appetite": "Risk appetite", "extrapolation": "Extrapolation", "breadth": "Breadth",
        "public_consensus": "Public consensus", "narrative_consensus": "Narrative consensus",
        "herding": "Herding", "flow_pressure": "Flow pressure", "positioning_crowding": "Positioning crowding",
        "attention": "Attention", "options_speculation": "Options speculation",
        "belief_disagreement": "Belief disagreement", "reflexivity": "Reflexivity",
        "narrative_concentration": "Narrative concentration",
    }
    out: dict[str, float] = {}
    for field, label in alias.items():
        if label in quality_by_name.index:
            direct = float(quality_by_name.loc[label, "Directness"]) / 100.0
            qual = float(quality_by_name.loc[label, "Quality"]) / 100.0
            out[field] = float(np.clip(5.0 + 15.0 * (1.0 - direct) + 10.0 * (1.0 - qual), 5.0, 26.0))
        else:
            out[field] = 18.0
    return out


def uncertainty_propagation(i: HOBInputs, cfg: HOBConfig, n: int = 500, seed: int = 7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Propagate measurement uncertainty through the HOB mapping.

    This is not a posterior and not a statistical confidence interval.  It is a
    deterministic Monte-Carlo sensitivity envelope around measurement proxies.
    """
    rng = np.random.default_rng(int(seed) % (2**32 - 1))
    sigmas = _input_sigma_map(i)
    fields = list(sigmas)
    records: list[dict[str, Any]] = []
    for _ in range(max(50, int(n))):
        kw = {}
        for f in fields:
            base = _finite(getattr(i, f, 50.0)) or 50.0
            kw[f] = float(np.clip(rng.normal(base, sigmas[f]), 0.0, 100.0))
        if i.fundamental_anchor is not None:
            anchor_sigma = float(np.clip(18.0 - 0.12 * _clip(i.fundamental_anchor_quality, default=0), 6.0, 18.0))
            kw["fundamental_anchor"] = float(np.clip(rng.normal(float(i.fundamental_anchor), anchor_sigma), 0, 100))
        rr = infer_hob(replace(i, **kw), cfg)
        records.append({
            "B1": rr.b1, "B2": rr.b2, "B3": rr.b3,
            "Speculative gap": rr.speculative_gap, "Meta gap": rr.meta_gap,
            "Strategic fragility": rr.strategic_fragility,
            "Reflexive price pressure": rr.reflexive_price_pressure,
            "Alpha proxy": rr.alpha_proxy, "Tau proxy": rr.tau_proxy,
            "Regime": rr.regime,
        })
    draws = pd.DataFrame(records)
    metrics = []
    for c in ["B1", "B2", "B3", "Speculative gap", "Meta gap", "Strategic fragility", "Reflexive price pressure", "Alpha proxy", "Tau proxy"]:
        s = pd.to_numeric(draws[c], errors="coerce").dropna()
        if s.empty:
            continue
        metrics.append((c, float(s.quantile(0.10)), float(s.median()), float(s.quantile(0.90)), float(s.std(ddof=1))))
    envelope = pd.DataFrame(metrics, columns=["Measure", "P10", "Median", "P90", "Dispersion"])
    return draws, envelope


def regime_reachability(i: HOBInputs, cfg: HOBConfig, n_global: int = 1800, n_local: int = 900, seed: int = 11) -> pd.DataFrame:
    """Audit whether the fixed ex-ante regime taxonomy is mathematically reachable.

    Global draws explore a broad plausible 5–95 input cube. Local draws perturb the
    current measurement state. No future return/outcome enters this diagnostic.
    """
    rng = np.random.default_rng(int(seed) % (2**32 - 1))
    strategic_fields = [
        "first_order_conviction", "private_signal_proxy", "risk_appetite", "extrapolation",
        "public_consensus", "narrative_consensus", "narrative_concentration",
        "belief_disagreement", "attention", "herding", "reflexivity",
        "positioning_crowding", "flow_pressure", "options_speculation", "breadth",
        "arbitrage_capacity", "uncertainty", "belief_confidence",
    ]
    base_vec = np.array([_clip(getattr(i, f)) for f in strategic_fields], dtype=float)
    base_scale = np.array([16.0 if f not in {"belief_disagreement", "uncertainty"} else 20.0 for f in strategic_fields], dtype=float)
    regimes = sorted({
        "HIGHER-ORDER MANIA", "SPECULATIVE BEAUTY CONTEST", "STRATEGIC SKEPTICISM",
        "STRATEGIC DISTRUST", "CONTRARIAN / RESALE COORDINATION", "COORDINATION BREAKDOWN",
        "FUNDAMENTAL / COMMON CONSENSUS", "REFLEXIVE COORDINATION", "MIXED STRATEGIC BELIEFS",
    })
    counts_g = {r: 0 for r in regimes}
    counts_l = {r: 0 for r in regimes}
    mind = {r: np.inf for r in regimes}
    for kind, n in [("g", n_global), ("l", n_local)]:
        for _ in range(max(100, int(n))):
            if kind == "g":
                vec = rng.uniform(5.0, 95.0, size=len(strategic_fields))
            else:
                vec = np.clip(rng.normal(base_vec, base_scale), 0.0, 100.0)
            kw = {f: float(v) for f, v in zip(strategic_fields, vec)}
            rr = infer_hob(replace(i, **kw), cfg)
            if kind == "g":
                counts_g[rr.regime] = counts_g.get(rr.regime, 0) + 1
            else:
                counts_l[rr.regime] = counts_l.get(rr.regime, 0) + 1
                dist = float(np.sqrt(np.mean(np.square((vec - base_vec) / base_scale))))
                mind[rr.regime] = min(mind.get(rr.regime, np.inf), dist)
    rows = []
    for r in regimes:
        gp = 100.0 * counts_g.get(r, 0) / max(int(n_global), 1)
        lp = 100.0 * counts_l.get(r, 0) / max(int(n_local), 1)
        md = mind.get(r, np.inf)
        if gp < 0.10:
            reach = "NEAR-UNREACHABLE"
        elif gp < 0.75:
            reach = "VERY RARE"
        elif gp < 3.0:
            reach = "RARE"
        else:
            reach = "REACHABLE"
        rows.append({
            "Regime": r, "Global reach %": gp, "Local reach %": lp,
            "Nearest local distance": None if not np.isfinite(md) else md,
            "Reachability": reach,
        })
    return pd.DataFrame(rows).sort_values(["Global reach %", "Regime"], ascending=[False, True]).reset_index(drop=True)

def cognitive_hierarchy_weights(tau: float, max_level: int = 6) -> np.ndarray:
    """Poisson cognitive-hierarchy weights.

    pi_k = exp(-tau) tau^k / k!, normalized after truncation at max_level.
    """
    tau = max(float(tau), 1e-6)
    max_level = max(int(max_level), 0)
    raw = np.array(
        [math.exp(-tau) * tau**k / math.factorial(k) for k in range(max_level + 1)],
        dtype=float,
    )
    total = float(raw.sum())
    return raw / total if total > 0 else raw


def iterated_expectation_value(beliefs: list[float], alpha: float) -> float:
    """Finite Allen-Morris-Shin-style beauty-contest truncation.

    For B1/B2/B3 this equals
        (1-a)B1 + (1-a)a B2 + a^2 B3.
    """
    if not beliefs:
        return 50.0
    a = float(np.clip(alpha, 0.0, 0.95))
    if len(beliefs) == 1:
        return float(np.clip(beliefs[0], 0.0, 100.0))
    value = 0.0
    for k, b in enumerate(beliefs[:-1]):
        value += (1.0 - a) * (a**k) * float(b)
    value += (a ** (len(beliefs) - 1)) * float(beliefs[-1])
    return float(np.clip(value, 0.0, 100.0))


def _public_signal_strength(i: HOBInputs) -> float:
    # Strength, not direction: common/public salience × evidence quality.
    directional_consensus = 0.52 * _clip(i.public_consensus) + 0.48 * _clip(i.narrative_consensus)
    salience = 0.55 * _clip(i.attention) + 0.45 * _clip(i.narrative_concentration)
    quality = 0.55 * _clip(i.public_signal_quality) + 0.45 * _clip(i.nlp_evidence)
    return float(np.clip(0.46 * directional_consensus + 0.24 * salience + 0.30 * quality, 0, 100))


def _private_signal_strength(i: HOBInputs) -> float:
    return float(np.clip(
        0.45 * _clip(i.first_order_conviction)
        + 0.30 * _clip(i.private_signal_proxy)
        + 0.15 * _clip(i.belief_confidence)
        + 0.10 * _clip(i.breadth),
        0, 100,
    ))


def inferred_alpha_proxy(i: HOBInputs) -> float:
    """Non-structural proxy for strategic complementarity.

    It is intentionally not estimated from returns.  It rises when coordination
    footprints/common knowledge are strong and falls when disagreement/ambiguity are high.
    """
    ck = 100.0 - 0.55 * _clip(i.belief_disagreement) - 0.25 * _clip(i.uncertainty) + 0.20 * _clip(i.narrative_consensus)
    raw = (
        0.18 * _center(i.narrative_consensus)
        + 0.15 * _center(i.herding)
        + 0.16 * _center(i.reflexivity)
        + 0.13 * _center(i.positioning_crowding)
        + 0.10 * _center(i.flow_pressure)
        + 0.09 * _center(i.attention)
        + 0.10 * _center(ck)
        + 0.09 * _center(100.0 - i.uncertainty)
    )
    return float(np.clip(0.52 + 0.30 * raw, 0.08, 0.90))


def inferred_tau_proxy(i: HOBInputs) -> float:
    """Strategic-depth *proxy*, not a cognitive-ability estimate."""
    raw = (
        0.28 * _center(i.attention)
        + 0.20 * _center(i.narrative_concentration)
        + 0.16 * _center(i.positioning_crowding)
        + 0.16 * _center(i.reflexivity)
        + 0.12 * _center(i.public_consensus)
        + 0.08 * _center(100.0 - i.belief_disagreement)
    )
    return float(np.clip(1.50 + 1.35 * raw, 0.30, 4.00))


def _crowd_target(i: HOBInputs) -> tuple[float, dict[str, float]]:
    terms = {
        "Public consensus": 0.25 * _center(i.public_consensus),
        "Narrative consensus": 0.18 * _center(i.narrative_consensus),
        "Herding": 0.12 * _center(i.herding),
        "Flow pressure": 0.11 * _center(i.flow_pressure),
        "Positioning crowding": 0.09 * _center(i.positioning_crowding),
        "Attention": 0.07 * _center(i.attention),
        "Options speculation": 0.05 * _center(i.options_speculation),
        "Breadth": 0.05 * _center(i.breadth),
        "Belief disagreement": -0.08 * _center(i.belief_disagreement),
    }
    return _score(sum(terms.values())), terms


def _meta_target(i: HOBInputs) -> tuple[float, dict[str, float]]:
    terms = {
        "Reflexivity": 0.22 * _center(i.reflexivity),
        "Attention": 0.14 * _center(i.attention),
        "Flow pressure": 0.13 * _center(i.flow_pressure),
        "Positioning crowding": 0.12 * _center(i.positioning_crowding),
        "Options speculation": 0.11 * _center(i.options_speculation),
        "Narrative concentration": 0.10 * _center(i.narrative_concentration),
        "Narrative consensus": 0.09 * _center(i.narrative_consensus),
        "Herding": 0.08 * _center(i.herding),
        "Belief disagreement": -0.09 * _center(i.belief_disagreement),
    }
    return _score(sum(terms.values())), terms


def _first_order(i: HOBInputs) -> tuple[float, dict[str, float]]:
    # If a genuine/manual fundamental anchor exists it enters explicitly; otherwise
    # weights are renormalized over observed first-order proxies rather than silently
    # pretending that momentum is fundamental value.
    terms: dict[str, float] = {
        "First-order conviction": 0.34 * _center(i.first_order_conviction),
        "Private-signal proxy": 0.23 * _center(i.private_signal_proxy),
        "Risk appetite": 0.16 * _center(i.risk_appetite),
        "Extrapolation": 0.10 * _center(i.extrapolation),
        "Breadth": 0.09 * _center(i.breadth),
        "Uncertainty": -0.08 * _center(i.uncertainty),
    }
    if i.fundamental_anchor is not None and _finite(i.fundamental_anchor) is not None:
        # V3.2 quality-adjusts the anchor weight. A weak/manual anchor cannot receive
        # the same influence as a high-coverage observed fundamental state.
        q = _clip(i.fundamental_anchor_quality, default=0.0) / 100.0
        anchor_weight = float(np.clip(0.15 + 0.20 * q, 0.15, 0.35))
        shrink = 1.0 - anchor_weight
        terms = {k: shrink * v for k, v in terms.items()}
        terms["Fundamental anchor"] = anchor_weight * _center(i.fundamental_anchor)
    return _score(sum(terms.values())), terms


def _order_uncertainty(
    i: HOBInputs, multiplier: float = 1.0, identification: Mapping[str, Any] | None = None
) -> tuple[float, float, float]:
    m = float(np.clip(multiplier, 0.5, 2.0))
    data_gap = 100.0 - _clip(i.behavioral_data_evidence)
    nlp_gap = 100.0 - _clip(i.nlp_evidence)
    stability_gap = 100.0 - _clip(i.latent_stability)
    bconf_gap = 100.0 - _clip(i.belief_confidence)
    ids = identification or {}
    b1_id = _clip(_mapping(ids.get("B1", {})).get("score"), default=40.0)
    b2_id = _clip(_mapping(ids.get("B2", {})).get("score"), default=45.0)
    b3_id = _clip(_mapping(ids.get("B3", {})).get("score"), default=42.0)
    if i.fundamental_anchor is None:
        anchor_penalty = 14.0
    else:
        anchor_penalty = 10.0 * (1.0 - _clip(i.fundamental_anchor_quality, default=0.0) / 100.0)
    u1 = 6 + 0.11 * _clip(i.uncertainty) + 0.08 * bconf_gap + 0.05 * stability_gap + 0.11 * (100.0 - b1_id) + anchor_penalty
    u2 = 9 + 0.14 * _clip(i.belief_disagreement) + 0.09 * nlp_gap + 0.06 * data_gap + 0.05 * _clip(i.uncertainty) + 0.10 * (100.0 - b2_id)
    u3 = 12 + 0.13 * _clip(i.belief_disagreement) + 0.08 * nlp_gap + 0.08 * data_gap + 0.07 * _clip(i.uncertainty) + 0.12 * (100.0 - b3_id)
    return tuple(float(np.clip(m * x, 6, 45)) for x in (u1, u2, u3))


def _order_disagreement(i: HOBInputs) -> tuple[float, float, float]:
    d1 = float(np.clip(
        0.42 * _clip(i.uncertainty)
        + 0.28 * _clip(i.sentiment_dispersion)
        + 0.18 * (100.0 - _clip(i.belief_confidence))
        + 0.12 * (100.0 - _clip(i.breadth)), 0, 100))
    d2 = float(np.clip(
        0.56 * _clip(i.belief_disagreement)
        + 0.24 * (100.0 - _clip(i.narrative_consensus))
        + 0.20 * (100.0 - _clip(i.public_consensus)), 0, 100))
    d3 = float(np.clip(
        0.34 * d2
        + 0.20 * _clip(i.uncertainty)
        + 0.18 * (100.0 - _clip(i.herding))
        + 0.16 * (100.0 - _clip(i.narrative_concentration))
        + 0.12 * (100.0 - _clip(i.reflexivity)), 0, 100))
    return d1, d2, d3


def build_belief_hierarchy(i: HOBInputs, cfg: HOBConfig) -> tuple[list[float], dict[str, Any]]:
    alpha = inferred_alpha_proxy(i) if str(cfg.parameter_mode).upper().startswith("INFER") else float(np.clip(cfg.strategic_complementarity, 0.0, 0.95))
    b1, b1_terms = _first_order(i)
    crowd, crowd_terms = _crowd_target(i)
    meta, meta_terms = _meta_target(i)
    b2 = float(np.clip((1.0 - alpha) * b1 + alpha * crowd, 0, 100))
    b3 = float(np.clip((1.0 - alpha) * b2 + alpha * meta, 0, 100))

    # Finite recursive representation for cognitive-hierarchy aggregation.  B4+ are
    # not displayed as observed belief orders; they are a controlled recursive proxy
    # converging toward the meta/coordination target.  This is an engineering
    # approximation motivated by finite-state HOB results, not Huo-Takayama's exact model.
    levels = [b1, b2, b3]
    long_run_meta = float(np.clip(0.62 * meta + 0.38 * crowd, 0, 100))
    while len(levels) <= max(int(cfg.max_cognitive_level), 2):
        prev = levels[-1]
        levels.append(float(np.clip((1.0 - alpha) * prev + alpha * long_run_meta, 0, 100)))
    return levels, {
        "alpha_used": alpha,
        "b1_terms": b1_terms,
        "crowd_terms": crowd_terms,
        "meta_terms": meta_terms,
        "crowd_target": crowd,
        "meta_target": meta,
        "long_run_meta_target": long_run_meta,
    }


def _regime_from_geometry(
    b1: float, b2: float, b3: float,
    u1: float, u2: float, u3: float,
    d2: float, d3: float, reflexivity: float, ck_intensity: float,
) -> tuple[str, float]:
    g2 = b2 - b1
    g3 = b3 - b2
    s2 = g2 / max(math.sqrt(u1**2 + u2**2), 1e-9)
    s3 = g3 / max(math.sqrt(u2**2 + u3**2), 1e-9)
    # "strength" is geometry × measurement quality, not a probability.
    geom = min(100.0, 35.0 * (abs(s2) + abs(s3)))
    quality = max(0.0, 100.0 - 0.5 * (d2 + d3))
    strength = float(np.clip(0.62 * geom + 0.38 * quality, 0, 100))

    if d2 >= 72 or d3 >= 72 or ck_intensity <= 25:
        return "COORDINATION BREAKDOWN", strength
    if g2 >= 8 and g3 >= 6 and b3 >= 65 and reflexivity >= 62 and s2 >= 0.25 and s3 >= 0.20:
        return "HIGHER-ORDER MANIA", strength
    if g2 >= 8 and b2 >= 60 and s2 >= 0.25:
        return "SPECULATIVE BEAUTY CONTEST", strength
    if b1 >= 58 and g2 <= -8 and g3 <= -2 and s2 <= -0.25:
        return "STRATEGIC SKEPTICISM", strength
    if b1 >= 60 and b2 <= 48 and g2 <= -8:
        return "STRATEGIC DISTRUST", strength
    if b1 <= 44 and b2 >= 55 and g2 >= 8:
        return "CONTRARIAN / RESALE COORDINATION", strength
    if abs(g2) <= 5 and abs(g3) <= 5 and d2 <= 48 and b1 >= 55:
        return "FUNDAMENTAL / COMMON CONSENSUS", strength
    if reflexivity >= 68 and abs(g2) >= 6:
        return "REFLEXIVE COORDINATION", strength
    return "MIXED STRATEGIC BELIEFS", strength


def infer_hob(inputs: HOBInputs, config: HOBConfig | None = None) -> HOBResult:
    cfg = config or HOBConfig()
    hierarchy, detail = build_belief_hierarchy(inputs, cfg)
    b1, b2, b3 = hierarchy[:3]
    alpha = float(detail["alpha_used"])
    tau_used = inferred_tau_proxy(inputs) if str(cfg.parameter_mode).upper().startswith("INFER") else float(np.clip(cfg.cognitive_hierarchy_tau, 0.3, 4.0))

    _id_df, id_summary = identification_matrix(inputs)
    u1, u2, u3 = _order_uncertainty(inputs, cfg.uncertainty_multiplier, id_summary)
    d1, d2, d3 = _order_disagreement(inputs)
    g2 = b2 - b1
    g3 = b3 - b2
    spec_snr = float(g2 / max(math.sqrt(u1**2 + u2**2), 1e-9))
    meta_snr = float(g3 / max(math.sqrt(u2**2 + u3**2), 1e-9))

    public_strength = _public_signal_strength(inputs)
    private_strength = _private_signal_strength(inputs)
    public_private_wedge = public_strength - private_strength
    ck_index = float(np.clip(
        0.30 * _clip(inputs.public_consensus)
        + 0.22 * _clip(inputs.narrative_consensus)
        + 0.18 * _clip(inputs.public_signal_quality)
        + 0.14 * (100.0 - _clip(inputs.belief_disagreement))
        + 0.08 * _clip(inputs.attention)
        + 0.08 * _clip(inputs.narrative_concentration), 0, 100))
    ck_intensity = float(np.clip(
        100.0 * public_strength / max(public_strength + d1 + 0.45 * d2, 1e-9), 0, 100))

    hod = float(np.clip(
        100.0 * (abs(g2) + abs(g3)) / max(2.0 * _clip(inputs.uncertainty, default=50.0), 30.0),
        0, 100,
    ))
    coordination = float(np.clip(
        0.22 * b2 + 0.20 * b3 + 0.20 * ck_index + 0.14 * _clip(inputs.herding)
        + 0.12 * _clip(inputs.positioning_crowding) + 0.12 * _clip(inputs.reflexivity), 0, 100))
    fragility = float(np.clip(
        0.24 * hod
        + 0.18 * _clip(inputs.positioning_crowding)
        + 0.18 * _clip(inputs.reflexivity)
        + 0.16 * d2 + 0.12 * d3
        + 0.12 * (100.0 - _clip(inputs.arbitrage_capacity)), 0, 100))
    signed_gap = (0.65 * g2 + 0.35 * g3) / 50.0
    feedback = (
        0.38 * _center(inputs.reflexivity)
        + 0.24 * _center(inputs.flow_pressure)
        + 0.18 * _center(inputs.positioning_crowding)
        + 0.12 * _center(inputs.options_speculation)
        + 0.08 * _center(inputs.attention)
    )
    rpp = float(np.clip(50.0 + 35.0 * signed_gap + 24.0 * feedback, 0, 100))

    weights = cognitive_hierarchy_weights(tau_used, cfg.max_cognitive_level)
    level_arr = np.asarray(hierarchy[: len(weights)], dtype=float)
    ch_value = float(np.clip(np.dot(weights, level_arr), 0, 100))
    levels = np.arange(len(weights), dtype=float)
    depth = float(np.dot(levels, weights))
    depth_score = float(np.clip(100.0 * depth / max(cfg.max_cognitive_level, 1), 0, 100))
    ie = iterated_expectation_value([b1, b2, b3], alpha)
    strategic_wedge = ch_value - b1

    alpha_proxy = inferred_alpha_proxy(inputs)
    tau_proxy = inferred_tau_proxy(inputs)
    anchor = _finite(inputs.fundamental_anchor)
    pf_gap = float(inputs.market_price_state - anchor) if anchor is not None else None

    # V3.2 identification confidence explicitly uses order-specific directness, quality,
    # coverage and source-independence. It remains capped without direct HOB surveys.
    b1_id = float(id_summary["B1"]["score"])
    b2_id = float(id_summary["B2"]["score"])
    b3_id = float(id_summary["B3"]["score"])
    source_independence = float(id_summary["overall_independence"])
    effective_families = float(id_summary["effective_source_families"])
    quality = (
        0.31 * b1_id + 0.31 * b2_id + 0.26 * b3_id
        + 0.12 * source_independence
    )
    # The absence of direct investor HOB surveys still limits institutional identification.
    confidence_cap = 74.0 if anchor is not None else 64.0
    confidence = float(np.clip(quality, 10.0, confidence_cap))
    grade = "MEDIUM" if confidence >= 52 else "LOW" if confidence >= 35 else "VERY LOW"

    regime, regime_strength = _regime_from_geometry(
        b1, b2, b3, u1, u2, u3, d2, d3, inputs.reflexivity, ck_intensity
    )
    return HOBResult(
        b1=b1, b2=b2, b3=b3,
        u1=u1, u2=u2, u3=u3,
        d1=d1, d2=d2, d3=d3,
        speculative_gap=g2, meta_gap=g3,
        speculative_snr=spec_snr, meta_snr=meta_snr,
        iterated_expectations_value=ie,
        cognitive_hierarchy_value=ch_value,
        strategic_price_wedge=strategic_wedge,
        higher_order_dominance=hod,
        coordination_pressure=coordination,
        common_knowledge_index=ck_index,
        common_knowledge_intensity=ck_intensity,
        public_private_wedge=public_private_wedge,
        strategic_fragility=fragility,
        reflexive_price_pressure=rpp,
        cognitive_depth=depth_score,
        alpha_proxy=alpha_proxy,
        tau_proxy=tau_proxy,
        market_price_state=_clip(inputs.market_price_state),
        fundamental_anchor=anchor,
        fundamental_anchor_quality=_clip(inputs.fundamental_anchor_quality, default=0.0),
        fundamental_anchor_source=str(inputs.fundamental_anchor_source),
        fundamental_anchor_temporal_integrity=str(inputs.fundamental_anchor_temporal_integrity),
        price_fundamental_gap=pf_gap,
        b1_identification=b1_id,
        b2_identification=b2_id,
        b3_identification=b3_id,
        source_independence=source_independence,
        effective_source_families=effective_families,
        regime=regime,
        regime_strength=regime_strength,
        identification_confidence=confidence,
        identification_grade=grade,
    )


def _behavioral_metric(state: Mapping[str, Any], layer: str, key: str, default: float = 50.0) -> float:
    bdata = _mapping(state.get("behavioral_data", {}))
    obj = _mapping(bdata.get(layer, {}))
    metrics = _mapping(obj.get("metrics", {}))
    return _clip(metrics.get(key), default=default)


def _price_state_proxy(state: Mapping[str, Any]) -> float:
    target = state.get("target_history", pd.DataFrame())
    if not isinstance(target, pd.DataFrame) or target.empty or "close" not in target.columns:
        return 50.0
    close = pd.to_numeric(target["close"], errors="coerce").dropna()
    if len(close) < 25:
        return 50.0
    r20 = float(close.iloc[-1] / close.iloc[-21] - 1.0) if len(close) >= 21 else 0.0
    r60 = float(close.iloc[-1] / close.iloc[-61] - 1.0) if len(close) >= 61 else r20
    dd = float(close.iloc[-1] / close.cummax().iloc[-1] - 1.0)
    realized = close.pct_change().tail(20).std(ddof=1) * math.sqrt(252.0)
    scale = max(float(realized) if np.isfinite(realized) else 0.15, 0.08)
    state_score = 50.0 + 22.0 * np.tanh(r20 / scale) + 14.0 * np.tanh(r60 / (1.5 * scale)) + 10.0 * np.tanh(dd / 0.08)
    return float(np.clip(state_score, 0, 100))


def inputs_from_psychology_state(
    state: Mapping[str, Any], fundamental_anchor: float | None = None,
    fundamental_meta: Mapping[str, Any] | None = None,
) -> tuple[HOBInputs, pd.DataFrame]:
    scores = _mapping(state.get("scores", {}))
    news = _mapping(state.get("news", {}))
    diagnostics = _mapping(state.get("diagnostics", {}))

    attention = _clip(scores.get("attention"))
    extrapolation = _clip(scores.get("extrapolation"))
    herding = _clip(scores.get("herding"))
    reflexivity = _clip(scores.get("reflexivity"))
    risk_appetite = _clip(scores.get("risk_appetite"))
    confidence = _clip(scores.get("confidence"))
    ambiguity = _clip(scores.get("ambiguity"))
    disagreement = _clip(news.get("belief_disagreement", scores.get("disagreement", 50.0)))
    narrative_consensus = _clip(news.get("narrative_consensus", 100.0 - disagreement))
    narrative_concentration = float(np.clip(100.0 * (_finite(news.get("theme_concentration")) or 0.0), 0, 100))
    if narrative_concentration <= 0:
        narrative_concentration = _clip(scores.get("narrative"), default=50.0)
    nlp_evidence = _clip(news.get("nlp_evidence_score", diagnostics.get("news_nlp_evidence", 50.0)))
    resolved_cov = _clip(news.get("resolved_coverage", diagnostics.get("news_resolved_coverage", 50.0)))
    sentiment_std = _finite(news.get("sentiment_std"))
    sentiment_dispersion = float(np.clip(100.0 * (sentiment_std or 0.50), 0, 100))
    public_consensus = float(np.clip(
        0.50 * (100.0 - disagreement) + 0.34 * narrative_consensus + 0.16 * narrative_concentration,
        0, 100,
    ))
    public_quality = float(np.clip(0.58 * nlp_evidence + 0.42 * resolved_cov, 0, 100))

    positioning = _behavioral_metric(state, "positioning", "positioning_crowding_score", 50.0)
    breadth = _behavioral_metric(state, "breadth", "breadth_score", risk_appetite)
    option_lottery = _behavioral_metric(state, "options_behavior", "option_lottery_score", scores.get("lottery_demand", 50.0))
    arb_capacity = _behavioral_metric(state, "funding", "arbitrage_capacity_score", scores.get("arbitrage_capacity", 50.0))

    bdata = _mapping(state.get("behavioral_data", {}))
    bdata_evidence = _clip(bdata.get("evidence_score", diagnostics.get("behavioral_data_evidence", 50.0)))
    latent_stability = _clip(state.get("latent_stability", 50.0))

    # Conservative first-order proxies.  A true valuation/fundamental anchor is still
    # separate and optional; it is never fabricated from momentum.
    first_order_conviction = float(np.clip(
        0.38 * confidence + 0.30 * risk_appetite + 0.20 * (100.0 - ambiguity) + 0.12 * breadth,
        0, 100,
    ))
    private_signal_proxy = float(np.clip(
        0.44 * confidence + 0.20 * extrapolation + 0.18 * breadth + 0.18 * (100.0 - ambiguity),
        0, 100,
    ))
    flow_pressure = float(np.clip(0.48 * risk_appetite + 0.32 * breadth + 0.20 * positioning, 0, 100))
    market_price_state = _price_state_proxy(state)
    fmeta = _mapping(fundamental_meta)
    fquality = _clip(fmeta.get("quality"), default=0.0) if fundamental_anchor is not None else 0.0
    fsource = str(fmeta.get("source", "MANUAL RESEARCH INPUT" if fundamental_anchor is not None else "NONE"))
    ftemporal = str(fmeta.get("temporal_integrity", "MANUAL / SCENARIO" if fundamental_anchor is not None else "UNAVAILABLE"))

    inputs = HOBInputs(
        first_order_conviction=first_order_conviction,
        private_signal_proxy=private_signal_proxy,
        risk_appetite=risk_appetite,
        extrapolation=extrapolation,
        fundamental_anchor=_finite(fundamental_anchor),
        fundamental_anchor_quality=fquality,
        fundamental_anchor_source=fsource,
        fundamental_anchor_temporal_integrity=ftemporal,
        market_price_state=market_price_state,
        public_consensus=public_consensus,
        public_signal_quality=public_quality,
        narrative_consensus=narrative_consensus,
        narrative_concentration=narrative_concentration,
        narrative_evidence=nlp_evidence,
        belief_disagreement=disagreement,
        sentiment_dispersion=sentiment_dispersion,
        attention=attention,
        herding=herding,
        reflexivity=reflexivity,
        positioning_crowding=positioning,
        flow_pressure=flow_pressure,
        options_speculation=option_lottery,
        breadth=breadth,
        arbitrage_capacity=arb_capacity,
        uncertainty=ambiguity,
        belief_confidence=confidence,
        latent_stability=latent_stability,
        behavioral_data_evidence=bdata_evidence,
        nlp_evidence=nlp_evidence,
        resolved_narrative_coverage=resolved_cov,
    )

    rows = [
        ("Fundamental anchor", fundamental_anchor, "UNOBSERVED" if fundamental_anchor is None else ("OBSERVED FUNDAMENTAL" if fsource.startswith("FRED") else "MANUAL RESEARCH INPUT"), "B1", f"{fsource} · quality {fquality:.0f}/100 · {ftemporal}" if fundamental_anchor is not None else "No independent fundamental anchor connected; never manufactured from momentum."),
        ("First-order conviction", first_order_conviction, "INFERRED", "B1", "Belief confidence + risk appetite + inverse ambiguity + breadth."),
        ("Private-signal proxy", private_signal_proxy, "INFERRED", "B1", "Confidence + extrapolation + breadth + inverse ambiguity; not investor-private data."),
        ("Market price state", market_price_state, "OBSERVED-DERIVED", "GAP ONLY", "Return/drawdown state used only if a separate fundamental anchor is supplied."),
        ("Public consensus", public_consensus, "INFERRED", "B2", "Belief disagreement + narrative consensus + narrative concentration."),
        ("Public-signal quality", public_quality, "MEASUREMENT QUALITY", "B2/CK", "NLP evidence + resolved narrative coverage."),
        ("Narrative consensus", narrative_consensus, "OBSERVED/INFERRED", "B2/B3", "Current multi-source NLP; historical PIT depth remains limited."),
        ("Narrative concentration", narrative_concentration, "OBSERVED/INFERRED", "B2/B3", "Current narrative share/concentration."),
        ("Belief disagreement", disagreement, "INFERRED", "B2/B3/D", "Multi-source NLP belief dispersion."),
        ("Attention", attention, "LATENT", "B2/B3", "Frozen V2.5.3 latent state."),
        ("Herding", herding, "LATENT", "B2/B3", "Frozen V2.5.3 latent state; historical coverage can be limited."),
        ("Reflexivity", reflexivity, "LATENT", "B3", "Frozen V2.5.3 latent state."),
        ("Positioning crowding", positioning, "OBSERVED/PROXY", "B2/B3", "CFTC broad-market positioning proxy when available."),
        ("Flow pressure", flow_pressure, "INFERRED", "B2/B3", "Risk appetite + breadth + positioning; not signed investor-level flows."),
        ("Options speculation", option_lottery, "OBSERVED/PROXY", "B2/B3", "Short-tenor/OTM footprint; not direct belief observation."),
        ("Arbitrage capacity", arb_capacity, "OBSERVED/PROXY", "FRAGILITY", "Funding/credit constraint layer; not a belief."),
        ("Uncertainty", ambiguity, "LATENT/PROXY", "U1/U2/U3", "Ambiguity / uncertainty state."),
        ("NLP evidence", nlp_evidence, "QUALITY", "IDENTIFICATION", "Semantic evidence quality; does not prove HOB validity."),
        ("Behavioral-data evidence", bdata_evidence, "QUALITY", "IDENTIFICATION", "Availability/freshness/identification composite from observed data layer."),
    ]
    evidence = pd.DataFrame(rows, columns=["Input", "Value", "Identification", "Role", "Evidence / limitation"])
    return inputs, evidence


def contribution_table(inputs: HOBInputs, cfg: HOBConfig) -> pd.DataFrame:
    hierarchy, detail = build_belief_hierarchy(inputs, cfg)
    rows: list[dict[str, Any]] = []
    for order, terms in [("B1", detail["b1_terms"]), ("B2 crowd target", detail["crowd_terms"]), ("B3 meta target", detail["meta_terms"])]:
        for name, term in terms.items():
            rows.append({
                "Order": order,
                "Input": name,
                "Contribution pts": 50.0 * float(term),
                "Direction": "UP" if term > 0 else "DOWN" if term < 0 else "NEUTRAL",
            })
    rows.extend([
        {"Order": "B2 blend", "Input": "B1 carry-over", "Contribution pts": (1.0 - detail["alpha_used"]) * hierarchy[0], "Direction": "LEVEL"},
        {"Order": "B2 blend", "Input": "Crowd target", "Contribution pts": detail["alpha_used"] * detail["crowd_target"], "Direction": "LEVEL"},
        {"Order": "B3 blend", "Input": "B2 carry-over", "Contribution pts": (1.0 - detail["alpha_used"]) * hierarchy[1], "Direction": "LEVEL"},
        {"Order": "B3 blend", "Input": "Meta target", "Contribution pts": detail["alpha_used"] * detail["meta_target"], "Direction": "LEVEL"},
    ])
    return pd.DataFrame(rows)


def counterfactual_table(inputs: HOBInputs, cfg: HOBConfig, shock_size: float = 10.0) -> pd.DataFrame:
    base = infer_hob(inputs, cfg)
    s = float(shock_size)
    scenarios = [
        ("Fundamental conviction +", replace(inputs, first_order_conviction=_clip(inputs.first_order_conviction + s))),
        ("Public consensus +", replace(inputs, public_consensus=_clip(inputs.public_consensus + s))),
        ("Narrative consensus +", replace(inputs, narrative_consensus=_clip(inputs.narrative_consensus + s))),
        ("Belief disagreement +", replace(inputs, belief_disagreement=_clip(inputs.belief_disagreement + s))),
        ("Reflexivity +", replace(inputs, reflexivity=_clip(inputs.reflexivity + s))),
        ("Positioning crowding +", replace(inputs, positioning_crowding=_clip(inputs.positioning_crowding + s))),
        ("Attention +", replace(inputs, attention=_clip(inputs.attention + s))),
        ("Options speculation +", replace(inputs, options_speculation=_clip(inputs.options_speculation + s))),
        ("Arbitrage capacity -", replace(inputs, arbitrage_capacity=_clip(inputs.arbitrage_capacity - s))),
    ]
    if inputs.fundamental_anchor is not None:
        scenarios.insert(1, ("Independent fundamental anchor +", replace(inputs, fundamental_anchor=_clip(float(inputs.fundamental_anchor) + s))))
    rows = []
    for name, altered in scenarios:
        r = infer_hob(altered, cfg)
        rows.append({
            "Shock": name,
            "ΔB1": r.b1 - base.b1,
            "ΔB2": r.b2 - base.b2,
            "ΔB3": r.b3 - base.b3,
            "ΔSpec gap": r.speculative_gap - base.speculative_gap,
            "ΔMeta gap": r.meta_gap - base.meta_gap,
            "ΔFragility": r.strategic_fragility - base.strategic_fragility,
            "ΔReflexive pressure": r.reflexive_price_pressure - base.reflexive_price_pressure,
            "ΔPrice-fund gap": (r.price_fundamental_gap - base.price_fundamental_gap) if (r.price_fundamental_gap is not None and base.price_fundamental_gap is not None) else np.nan,
            "Point geometry": _point_geometry_label(r),
            "Uncertainty-adjusted regime": r.regime,
        })
    return pd.DataFrame(rows)


def sensitivity_grid(inputs: HOBInputs, max_level: int = 6) -> pd.DataFrame:
    alphas = np.linspace(0.05, 0.90, 18)
    taus = np.linspace(0.30, 4.00, 20)
    rows = []
    for a in alphas:
        for tau in taus:
            cfg = HOBConfig(strategic_complementarity=float(a), cognitive_hierarchy_tau=float(tau), max_cognitive_level=max_level)
            r = infer_hob(inputs, cfg)
            wedge = r.cognitive_hierarchy_value - r.b1
            if wedge >= 8 and r.cognitive_hierarchy_value >= 58:
                sreg = "CROWD-LED / SPECULATIVE"
            elif wedge <= -8 and r.b1 >= 55:
                sreg = "STRATEGIC SKEPTICISM"
            elif abs(wedge) <= 4:
                sreg = "FUNDAMENTAL-ALIGNED"
            else:
                sreg = "MIXED"
            rows.append({
                "alpha": float(a), "tau": float(tau),
                "strategic_value": r.cognitive_hierarchy_value,
                "strategic_wedge": wedge,
                "fragility": r.strategic_fragility,
                "hob_regime": r.regime,
                "sensitivity_regime": sreg,
            })
    return pd.DataFrame(rows)


def _historical_core_proxy(state: Mapping[str, Any], alpha: float) -> pd.DataFrame:
    """Core-only historical HOB approximation for visualization, never validation."""
    hist = state.get("history", pd.DataFrame())
    if not isinstance(hist, pd.DataFrame) or hist.empty:
        return pd.DataFrame()
    needed = ["attention", "fear", "herding", "extrapolation", "reflexivity"]
    if not all(c in hist.columns for c in needed):
        return pd.DataFrame()
    h = hist.copy().tail(1300)
    for c in needed:
        h[c] = pd.to_numeric(h[c], errors="coerce").clip(0, 100)
    h["B1 core proxy"] = (
        0.42 * h["extrapolation"] + 0.24 * (100 - h["fear"])
        + 0.18 * h["attention"] + 0.10 * h["reflexivity"] + 0.06 * (100 - h["herding"])
    ).clip(0, 100)
    crowd = (
        0.32 * h["herding"] + 0.24 * h["attention"]
        + 0.22 * h["reflexivity"] + 0.14 * (100 - h["fear"]) + 0.08 * h["extrapolation"]
    ).clip(0, 100)
    h["B2 core proxy"] = ((1 - alpha) * h["B1 core proxy"] + alpha * crowd).clip(0, 100)
    meta = (
        0.38 * h["reflexivity"] + 0.23 * h["attention"]
        + 0.18 * h["herding"] + 0.14 * h["extrapolation"] + 0.07 * (100 - h["fear"])
    ).clip(0, 100)
    h["B3 core proxy"] = ((1 - alpha) * h["B2 core proxy"] + alpha * meta).clip(0, 100)
    h["Speculative wedge core"] = h["B2 core proxy"] - h["B1 core proxy"]
    h["Meta wedge core"] = h["B3 core proxy"] - h["B2 core proxy"]
    return h


def _archive_path(symbol: str) -> Path:
    root = Path(__file__).resolve().parent / "memory"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in str(symbol).upper() if ch.isalnum() or ch in {"-", "_"}) or "MARKET"
    return root / f"{safe}_hob_v3_snapshots.csv"


def archive_hob_snapshot(state: Mapping[str, Any], result: HOBResult) -> dict[str, Any]:
    """Prospectively upsert one derived HOB snapshot per market date.

    The archive contains no raw news text, API credentials or future outcomes.  It is
    an experimental V3 archive and is not part of the frozen V2.5.3 baseline.
    """
    symbol = str(state.get("symbol", "MARKET")).upper()
    target = state.get("target_history", pd.DataFrame())
    date_value: str
    if isinstance(target, pd.DataFrame) and not target.empty:
        if "date" in target.columns:
            dt = pd.to_datetime(target["date"], errors="coerce").dropna()
        else:
            dt = pd.to_datetime(target.index, errors="coerce")
            dt = pd.Series(dt).dropna()
        date_value = pd.Timestamp(dt.iloc[-1]).strftime("%Y-%m-%d") if len(dt) else pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    else:
        date_value = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
    row = {
        "date": date_value, "symbol": symbol, "version": HOB_RESEARCH_VERSION,
        "b1": result.b1, "b2": result.b2, "b3": result.b3,
        "u1": result.u1, "u2": result.u2, "u3": result.u3,
        "d1": result.d1, "d2": result.d2, "d3": result.d3,
        "speculative_gap": result.speculative_gap, "meta_gap": result.meta_gap,
        "speculative_snr": result.speculative_snr, "meta_snr": result.meta_snr,
        "higher_order_dominance": result.higher_order_dominance,
        "common_knowledge_intensity": result.common_knowledge_intensity,
        "coordination_pressure": result.coordination_pressure,
        "strategic_fragility": result.strategic_fragility,
        "reflexive_price_pressure": result.reflexive_price_pressure,
        "alpha_proxy": result.alpha_proxy, "tau_proxy": result.tau_proxy,
        "identification_confidence": result.identification_confidence,
        "fundamental_anchor": result.fundamental_anchor,
        "fundamental_anchor_quality": result.fundamental_anchor_quality,
        "fundamental_anchor_source": result.fundamental_anchor_source,
        "price_fundamental_gap": result.price_fundamental_gap,
        "b1_identification": result.b1_identification,
        "b2_identification": result.b2_identification,
        "b3_identification": result.b3_identification,
        "source_independence": result.source_independence,
        "effective_source_families": result.effective_source_families,
        "anchor_temporal_integrity": result.fundamental_anchor_temporal_integrity,
        "regime": result.regime,
    }
    path = _archive_path(symbol)
    try:
        old = pd.read_csv(path) if path.exists() else pd.DataFrame()
        row_df = pd.DataFrame([row])
        new = row_df.copy() if old.empty else pd.concat([old, row_df], ignore_index=True)
        new["date"] = new["date"].astype(str)
        for col in _ARCHIVE_COLUMNS:
            if col not in new.columns:
                new[col] = np.nan
        extra_cols = [c for c in new.columns if c not in _ARCHIVE_COLUMNS]
        new = new[_ARCHIVE_COLUMNS + extra_cols]
        new = new.drop_duplicates(subset=["date", "symbol"], keep="last").sort_values(["date", "symbol"])
        tmp = path.with_suffix(".tmp.csv")
        new.to_csv(tmp, index=False)
        os.replace(tmp, path)
        return {
            "status": "OK", "path": str(path), "snapshots": int(len(new)),
            "first": str(new["date"].iloc[0]) if len(new) else None,
            "last": str(new["date"].iloc[-1]) if len(new) else None,
        }
    except Exception as exc:
        return {"status": "ERROR", "detail": type(exc).__name__, "path": str(path), "snapshots": 0}


def _literature_table() -> pd.DataFrame:
    rows = [
        ("Morris & Shin", 2002, "Public information + strategic complementarity", "Public/common signals can be disproportionately influential when agents coordinate.", "Common-knowledge intensity / public-private wedge"),
        ("Camerer, Ho & Chong", 2004, "Cognitive hierarchy", "Agents differ in bounded strategic depth; average ~1.5 steps fits many games.", "Poisson depth distribution / τ sensitivity"),
        ("Allen, Morris & Shin", 2006, "Iterated expectations in asset markets", "Prices can depend on averages of averages of expectations rather than only terminal-payoff beliefs.", "B1→B2→B3 / iterated-expectations value"),
        ("Banerjee, Kaniel & Kremer", 2009, "Higher-order disagreement", "Dynamic higher-order disagreement can generate price drift.", "Order-specific disagreement + belief wedges"),
        ("Huo & Takayama", 2025, "Finite-state HOB representation", "Infinite HOB hierarchies can admit finite-state representations under finite ARMA signals.", "Finite recursive hierarchy; explicitly an approximation"),
        ("Schmidt-Engelbertz & Vasudevan", 2025, "Nonfundamental speculation", "HOB can motivate positions conflicting with investors' own valuation and amplify overreaction/excess volatility.", "Speculative wedge / strategic-price wedge"),
        ("Gorodnichenko & Yin", 2026, "Causal HOB portfolio effects", "FOB and HOB are distinct; experimentally shifting HOB can affect risky-asset holdings differently from FOB.", "FOB/HOB separation; no assumption HOB = bullish herding"),
    ]
    return pd.DataFrame(rows, columns=["Research", "Year", "Mechanism", "Key implication", "Implemented in Lab"])


def _stable_seed(*parts: Any) -> int:
    text = "|".join(str(x) for x in parts)
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _point_geometry_label(result: HOBResult) -> str:
    g2, g3 = result.speculative_gap, result.meta_gap
    if g2 >= 8 and g3 >= 6 and result.b3 >= 62:
        return "HIGHER-ORDER MANIA"
    if g2 >= 8 and result.b2 >= 58:
        return "SPECULATIVE BEAUTY CONTEST"
    if result.b1 >= 55 and g2 <= -8 and g3 <= -2:
        return "STRATEGIC SKEPTICISM"
    if result.b1 >= 60 and result.b2 <= 48 and g2 <= -8:
        return "STRATEGIC DISTRUST"
    if result.b1 <= 44 and result.b2 >= 55 and g2 >= 8:
        return "CONTRARIAN / RESALE COORDINATION"
    if abs(g2) <= 5 and abs(g3) <= 5:
        return "FUNDAMENTAL-ALIGNED"
    return "MIXED"


def _belief_measurement_connector_table() -> pd.DataFrame:
    rows = [
        ("Yale/Shiller U.S. Stock Market Confidence", "NEAR-DIRECT SURVEY", "Monthly", "B1 / public-belief calibration", "MANUAL / PERMISSION-AWARE", "Free confidence indices exist; full question set/extended indices require Yale permission/request. Do not scrape or redistribute raw survey data."),
        ("AAII Sentiment Survey", "NEAR-DIRECT FIRST-ORDER / CROWD", "Weekly", "B1 + observed crowd calibration", "AUTO BEST-EFFORT V3.4", "Official AAII historical-results table; not a direct B2/B3 beliefs-about-others measure."),
        ("FMP analyst estimates", "NEAR-DIRECT PUBLIC EXPECTATIONS", "Event / estimate updates", "Single-stock B1 / public consensus", "CONNECTOR CANDIDATE", "Existing terminal key can support analyst EPS/revenue estimate inputs for single-stock HOB, subject to plan entitlements."),
        ("Customized HOB investor survey", "DIRECT HOB", "Research-specific", "B2 / B3 identification", "NOT CONNECTED", "Required gold-standard measurement layer for direct beliefs-about-others; current market proxies remain indirect."),
    ]
    return pd.DataFrame(rows, columns=["Source", "Measurement tier", "Frequency", "Potential role", "Status", "Constraint / interpretation"])


def _regime_explanation(regime: str) -> str:
    return {
        "HIGHER-ORDER MANIA": "B3 > B2 > B1 with strong reflexive coordination: progressively deeper orders are more optimistic than first-order conviction.",
        "SPECULATIVE BEAUTY CONTEST": "Expected crowd belief materially exceeds first-order conviction; coordination/resale motives dominate more than own-state belief.",
        "STRATEGIC SKEPTICISM": "B1 > B2 > B3: own/state conviction is stronger than expected crowd and meta-crowd beliefs.",
        "STRATEGIC DISTRUST": "First-order conviction is constructive while expected crowd belief falls below neutral; strategic exit/coordination risk is elevated.",
        "CONTRARIAN / RESALE COORDINATION": "First-order conviction is weak while expected crowd belief is stronger; positions may be motivated by expected resale/coordination rather than own valuation.",
        "COORDINATION BREAKDOWN": "Disagreement/low common knowledge is too high for a stable higher-order hierarchy.",
        "FUNDAMENTAL / COMMON CONSENSUS": "B1/B2/B3 are close and disagreement is contained: coordination adds relatively little beyond the first-order state.",
        "REFLEXIVE COORDINATION": "Higher-order wedges coexist with strong reflexive feedback; endogenous price-belief feedback is the main risk to monitor.",
        "MIXED STRATEGIC BELIEFS": "No ex-ante strategic-belief geometry dominates once measurement uncertainty and disagreement are considered.",
    }.get(regime, "")



# ---------------------------------------------------------------------------
# V3.4 · Chronology integrity, belief-evidence discipline, taxonomy pre-freeze
# state-space identification and executive research interface.
# ---------------------------------------------------------------------------

_ALFRED_DAILY_CACHE: dict[tuple[str, str, str], tuple[pd.DataFrame, dict[str, Any]]] = {}
_AAII_DAILY_CACHE: dict[str, dict[str, Any]] = {}


def _hob_secret(*names: str) -> str:
    """Read a secret without importing Streamlit at module import time."""
    for name in names:
        try:
            import streamlit as st  # local import keeps non-UI tests lightweight
            v = st.secrets.get(name, "")
        except Exception:
            v = ""
        if isinstance(v, str) and v.strip():
            return v.strip()
        ev = os.getenv(name, "")
        if isinstance(ev, str) and ev.strip():
            return ev.strip()
    return ""


def _period_years(period: str) -> int:
    return {"1y": 1, "2y": 2, "5y": 5, "10y": 10, "15y": 15}.get(str(period).lower(), 10)


def _fred_json_request(endpoint: str, params: Mapping[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Small FRED request wrapper that never exposes the API key in diagnostics."""
    try:
        import requests
        r = requests.get(endpoint, params=dict(params), timeout=(5, 30))
        status = int(getattr(r, "status_code", 0) or 0)
        try:
            payload = r.json()
        except Exception:
            payload = None
        if status >= 400:
            detail = None
            if isinstance(payload, Mapping):
                detail = payload.get("error_message") or payload.get("message")
            return None, {"status": "http_error", "http": status, "detail": str(detail or "")[:180]}
        if not isinstance(payload, Mapping):
            return None, {"status": "bad_json", "http": status}
        if payload.get("error_code") or payload.get("error_message"):
            return None, {
                "status": "api_error", "http": status,
                "detail": str(payload.get("error_message") or payload.get("error_code"))[:180],
            }
        return dict(payload), {"status": "ok", "http": status}
    except Exception as exc:
        return None, {"status": "request_error", "detail": type(exc).__name__}


def _parse_fred_realtime_rows(payload: Mapping[str, Any] | None) -> pd.DataFrame:
    """Normalize FRED long-form observation responses to date/release/value rows."""
    if not isinstance(payload, Mapping):
        return pd.DataFrame(columns=["date", "release_date", "value"])
    obs = payload.get("observations", [])
    if not isinstance(obs, list) or not obs:
        return pd.DataFrame(columns=["date", "release_date", "value"])
    out = pd.DataFrame(obs)
    if "date" not in out.columns or "value" not in out.columns:
        return pd.DataFrame(columns=["date", "release_date", "value"])
    release_col = "realtime_start" if "realtime_start" in out.columns else None
    if release_col is None:
        return pd.DataFrame(columns=["date", "release_date", "value"])
    out["date"] = pd.to_datetime(out["date"], errors="coerce", utc=True)
    out["release_date"] = pd.to_datetime(out[release_col], errors="coerce", utc=True)
    out["value"] = pd.to_numeric(out["value"].replace(".", np.nan), errors="coerce")
    out = out[["date", "release_date", "value"]].dropna()
    if out.empty:
        return out
    # Reject impossible chronology and future releases.
    now = pd.Timestamp.now(tz="UTC").normalize()
    out = out[(out["release_date"] <= now) & (out["release_date"] >= out["date"] - pd.Timedelta(days=7))]
    return out.sort_values(["date", "release_date"]).reset_index(drop=True)


def _fetch_fred_initial_release(series_id: str, period: str = "15y") -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch initial-release FRED/ALFRED observations with a verified fallback.

    Primary path uses FRED ``output_type=4`` (Initial Release Only).  If that path
    is unavailable for a series/account combination, the fallback requests
    ``output_type=1`` over the relevant real-time period and takes the earliest
    real-time start for each observation date.  FRED documents real-time start as
    the first vintage for which a value was current, so the earliest such row is
    the initial public value.
    """
    key = _hob_secret("FRED_API_KEY")
    base_meta: dict[str, Any] = {"provider": "FRED/ALFRED", "series": series_id}
    if not key:
        return pd.DataFrame(), {**base_meta, "status": "disabled", "detail": "FRED_API_KEY missing"}
    now = pd.Timestamp.now(tz="UTC").normalize()
    cache_key = (str(series_id), str(period), str(now.date()))
    cached = _ALFRED_DAILY_CACHE.get(cache_key)
    if cached is not None:
        return cached[0].copy(), dict(cached[1])

    years = _period_years(period)
    obs_start = (now - pd.DateOffset(years=years + 2)).date().isoformat()
    # The real-time window must include the first public release for every requested
    # observation.  Using the full documented lower bound avoids the empty-response
    # behavior seen when output_type=4 is combined with an overly narrow real-time window.
    common = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": obs_start,
        "observation_end": now.date().isoformat(),
        "realtime_start": "1776-07-04",
        "realtime_end": now.date().isoformat(),
        "sort_order": "asc",
        "limit": 100000,
    }
    attempts: list[dict[str, Any]] = []

    # Official initial-release endpoint.
    payload4, meta4 = _fred_json_request(
        "https://api.stlouisfed.org/fred/series/observations",
        {**common, "output_type": 4},
    )
    out4 = _parse_fred_realtime_rows(payload4)
    attempts.append({"method": "OUTPUT_TYPE_4", **meta4, "rows": int(len(out4))})
    if not out4.empty:
        out4 = out4.sort_values(["date", "release_date"]).drop_duplicates("date", keep="first").reset_index(drop=True)
        meta = {
            **base_meta, "status": "ok", "rows": int(len(out4)),
            "method": "OUTPUT_TYPE_4", "attempts": attempts,
            "temporal_integrity": "INITIAL_RELEASE_VINTAGE_LOCKED",
        }
        _ALFRED_DAILY_CACHE[cache_key] = (out4.copy(), dict(meta))
        return out4, meta

    # Verified reconstruction fallback: output_type=1 contains real-time periods.
    # Earliest realtime_start per observation is the initial release.
    payload1, meta1 = _fred_json_request(
        "https://api.stlouisfed.org/fred/series/observations",
        {**common, "output_type": 1},
    )
    rt = _parse_fred_realtime_rows(payload1)
    attempts.append({"method": "REALTIME_FIRST_REVISION", **meta1, "rows": int(len(rt))})
    if not rt.empty:
        first = rt.sort_values(["date", "release_date"]).drop_duplicates("date", keep="first").reset_index(drop=True)
        meta = {
            **base_meta, "status": "ok", "rows": int(len(first)),
            "method": "REALTIME_FIRST_REVISION", "attempts": attempts,
            "temporal_integrity": "INITIAL_RELEASE_RECONSTRUCTED_FROM_REALTIME_PERIODS",
        }
        _ALFRED_DAILY_CACHE[cache_key] = (first.copy(), dict(meta))
        return first, meta

    detail = "; ".join(
        f"{a.get('method')}:{a.get('status')}" + (f"[{a.get('http')}]" if a.get("http") else "")
        for a in attempts
    )
    return pd.DataFrame(), {
        **base_meta, "status": "unavailable", "rows": 0, "attempts": attempts,
        "detail": detail[:240], "temporal_integrity": "UNAVAILABLE",
    }


def _transform_initial_release_frame(df: pd.DataFrame, transform: str) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["date", "release_date", "transformed"])
    x = df[["date", "release_date", "value"]].copy().sort_values("date")
    s = pd.to_numeric(x["value"], errors="coerce")
    if transform == "yoy_q":
        x["transformed"] = s.pct_change(4) * 100.0
        lag_rel = x["release_date"].shift(4)
        x["release_date"] = pd.concat([x["release_date"], lag_rel], axis=1).max(axis=1)
    elif transform == "yoy_m":
        x["transformed"] = s.pct_change(12) * 100.0
        lag_rel = x["release_date"].shift(12)
        x["release_date"] = pd.concat([x["release_date"], lag_rel], axis=1).max(axis=1)
    elif transform == "diff6_m":
        x["transformed"] = s.diff(6)
        lag_rel = x["release_date"].shift(6)
        x["release_date"] = pd.concat([x["release_date"], lag_rel], axis=1).max(axis=1)
    else:
        x["transformed"] = s
    x = x.replace([np.inf, -np.inf], np.nan).dropna(subset=["date", "release_date", "transformed"])
    return x[["date", "release_date", "transformed"]]


def _initial_release_component_events(df: pd.DataFrame, transform: str, direction: float) -> pd.DataFrame:
    t = _transform_initial_release_frame(df, transform)
    if t.empty:
        return pd.DataFrame(columns=["release_date", "score", "observation_date", "raw"])
    by_obs = pd.Series(t["transformed"].to_numpy(float), index=pd.DatetimeIndex(t["date"]), dtype=float).sort_index()
    # Native-frequency trailing normalization. This avoids assigning an end-of-month
    # score to earlier daily observations in the same month (a subtle look-ahead).
    if len(by_obs) >= 3:
        gaps = by_obs.index.to_series().diff().dt.total_seconds().div(86400.0).dropna()
        med_gap = float(gaps.median()) if not gaps.empty else 30.0
    else:
        med_gap = 30.0
    if med_gap <= 7.0:       # daily / business-daily
        window, min_periods = 252, 60
    elif med_gap <= 45.0:    # monthly-ish
        window, min_periods = 60, 18
    else:                    # quarterly-ish
        window, min_periods = 20, 8
    z = _robust_series_z(by_obs, window=window, min_periods=min_periods)
    if z.dropna().empty:
        med = by_obs.expanding(min_periods=max(6, min_periods // 2)).median()
        std = by_obs.expanding(min_periods=max(6, min_periods // 2)).std(ddof=1).replace(0, np.nan)
        z = ((by_obs - med) / std).clip(-3.5, 3.5)
    score_obs = (50.0 + 15.0 * float(direction) * z).clip(0.0, 100.0)
    rows = []
    for _, row in t.iterrows():
        obs_date = pd.Timestamp(row["date"])
        sc = _finite(score_obs.get(obs_date))
        if sc is None:
            continue
        rows.append({
            "release_date": pd.Timestamp(row["release_date"]).normalize(),
            "score": float(sc),
            "observation_date": obs_date.normalize(),
            "raw": float(row["transformed"]),
        })
    if not rows:
        return pd.DataFrame(columns=["release_date", "score", "observation_date", "raw"])
    out = pd.DataFrame(rows).sort_values(["release_date", "observation_date"])
    return out.drop_duplicates("release_date", keep="last").reset_index(drop=True)


def build_vintage_locked_fundamental_anchor(state: Mapping[str, Any], symbol: str | None = None) -> dict[str, Any]:
    """Build an initial-release-vintage fundamental state for broad U.S. equities."""
    sym = str(symbol or state.get("symbol", "")).upper().strip()
    if sym not in _BROAD_US_EQUITY_SYMBOLS:
        return {
            "status": "UNSUPPORTED_SYMBOL", "anchor": None, "quality": 0.0,
            "coverage": 0.0, "source": "FRED/ALFRED", "history": pd.DataFrame(),
            "components": pd.DataFrame(), "temporal_integrity": "N/A",
        }
    now = pd.Timestamp.utcnow().normalize()
    total_weight = sum(v[4] for v in _FUNDAMENTAL_SERIES.values())
    component_series: dict[str, pd.Series] = {}
    component_weights: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    available_weight = 0.0
    freshness_num = 0.0
    for key, (series_id, label, transform, direction, weight, cadence_days) in _FUNDAMENTAL_SERIES.items():
        raw, meta = _fetch_fred_initial_release(series_id, "15y")
        events = _initial_release_component_events(raw, transform, direction)
        if events.empty:
            rows.append({
                "Component": label, "Series": series_id, "Weight": weight,
                "Status": str(meta.get("status", "MISSING")).upper(),
                "Latest initial-release score": None, "Last public release": None,
                "Freshness": 0.0,
                "Acquisition method": str(meta.get("method", "N/A")),
                "Diagnostic": str(meta.get("detail", meta.get("status", "")))[:120],
            })
            continue
        last = events.iloc[-1]
        age = max(0.0, float((now - pd.Timestamp(last["release_date"])).total_seconds() / 86400.0))
        freshness = float(np.clip(100.0 * (1.0 - max(0.0, age - cadence_days * 0.25) / max(cadence_days * 1.5, 1.0)), 0.0, 100.0))
        s = pd.Series(events["score"].to_numpy(float), index=pd.DatetimeIndex(events["release_date"]), dtype=float)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        component_series[key] = s
        component_weights[key] = float(weight)
        available_weight += float(weight)
        freshness_num += float(weight) * freshness
        rows.append({
            "Component": label, "Series": series_id, "Weight": weight,
            "Status": "OK", "Latest initial-release score": float(last["score"]),
            "Last public release": str(pd.Timestamp(last["release_date"]).date()),
            "Latest underlying observation": str(pd.Timestamp(last["observation_date"]).date()),
            "Freshness": freshness,
            "Acquisition method": str(meta.get("method", "OUTPUT_TYPE_4")),
            "Diagnostic": str(meta.get("status", "ok")),
        })

    if not component_series:
        return {
            "status": "MISSING", "anchor": None, "quality": 0.0,
            "coverage": 0.0, "source": "FRED/ALFRED", "history": pd.DataFrame(),
            "components": pd.DataFrame(rows), "temporal_integrity": "INITIAL_RELEASE_VINTAGE_LOCKED",
        }

    start = min(s.index.min() for s in component_series.values())
    idx = pd.date_range(start=start, end=now, freq="D", tz="UTC")
    num = pd.Series(0.0, index=idx)
    den = pd.Series(0.0, index=idx)
    for key, s in component_series.items():
        aligned = s.reindex(idx).ffill()
        w = component_weights[key]
        mask = aligned.notna()
        num.loc[mask] += w * aligned.loc[mask]
        den.loc[mask] += w
    anchor_hist = (num / den.replace(0, np.nan)).clip(0.0, 100.0)
    anchor_hist = anchor_hist.dropna()
    anchor = _finite(anchor_hist.iloc[-1]) if not anchor_hist.empty else None
    coverage = 100.0 * available_weight / max(total_weight, 1e-12)
    freshness = freshness_num / available_weight if available_weight else 0.0
    quality = float(np.clip(0.48 * coverage + 0.27 * freshness + 0.25 * 100.0, 0.0, 96.0)) if anchor is not None else 0.0
    hist = pd.DataFrame({
        "date": anchor_hist.index,
        "Fundamental anchor · PIT initial release": anchor_hist.to_numpy(float),
    })
    return {
        "status": "OK" if coverage >= 65 else "PARTIAL",
        "anchor": anchor, "quality": quality, "coverage": float(coverage),
        "freshness": float(freshness), "source": "FRED/ALFRED initial releases",
        "history": hist, "components": pd.DataFrame(rows),
        "temporal_integrity": "INITIAL_RELEASE_VINTAGE_LOCKED",
        "note": "Historical fundamental state uses only initial-release observations available by each release date.",
    }


def build_fundamental_anchor_v33(state: Mapping[str, Any], symbol: str | None = None) -> dict[str, Any]:
    live = build_fundamental_anchor(state, symbol)
    pit = build_vintage_locked_fundamental_anchor(state, symbol)
    live_anchor = _finite(live.get("anchor"))
    pit_anchor = _finite(pit.get("anchor"))
    revision_gap = None if live_anchor is None or pit_anchor is None else float(live_anchor - pit_anchor)
    return {
        "live": live,
        "pit": pit,
        "anchor": live_anchor,
        "pit_anchor": pit_anchor,
        "revision_gap": revision_gap,
        "quality": _finite(live.get("quality")) or 0.0,
        "pit_quality": _finite(pit.get("quality")) or 0.0,
        "coverage": _finite(live.get("coverage")) or 0.0,
        "pit_coverage": _finite(pit.get("coverage")) or 0.0,
        "source": str(live.get("source", "NONE")),
        "temporal_integrity": (
            "LIVE CURRENT-VINTAGE + PIT INITIAL-RELEASE HISTORY"
            if pit_anchor is not None else str(live.get("temporal_integrity", "CURRENT_VINTAGE"))
        ),
    }


def fetch_aaii_direct_belief() -> dict[str, Any]:
    """Best-effort official AAII current/recent sentiment survey readout.

    AAII is near-direct first-order/crowd evidence only.  V3.4 accepts either the
    official HTML table or a conservative text fallback; it never promotes the
    survey to a direct B2/B3 beliefs-about-others measure.
    """
    cache_key = str(pd.Timestamp.now(tz="UTC").date())
    cached = _AAII_DAILY_CACHE.get(cache_key)
    if cached is not None:
        out = dict(cached)
        if isinstance(out.get("history"), pd.DataFrame):
            out["history"] = out["history"].copy()
        return out
    try:
        import requests
        from io import StringIO
        url = "https://www.aaii.com/sentimentsurvey/sent_results"
        r = requests.get(url, timeout=(5, 20), headers={"User-Agent": "Mozilla/5.0 QuantResearch/1.0"})
        r.raise_for_status()
        tables = []
        try:
            tables = pd.read_html(StringIO(r.text))
        except Exception:
            tables = []
        target = None
        for t in tables:
            t = t.copy()
            flat = []
            for c in t.columns:
                if isinstance(c, tuple):
                    parts = [str(x).strip() for x in c if str(x).strip().lower() not in {"", "nan", "unnamed"}]
                    name = parts[-1] if parts else str(c[-1])
                else:
                    name = str(c)
                flat.append(name.strip().lower())
            t.columns = flat
            if {"bullish", "neutral", "bearish"}.issubset(set(flat)):
                target = t
                break

        # Official page text fallback.  This is deliberately narrow: only rows with
        # a month/day followed by three percentages are accepted.
        if target is None or target.empty:
            import re as _re
            cleaned = _re.sub(r"<[^>]+>", " ", r.text)
            cleaned = cleaned.replace("&nbsp;", " ")
            pattern = _re.compile(
                r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+"
                r"(\d{1,3}(?:\.\d+)?)%\s+(\d{1,3}(?:\.\d+)?)%\s+(\d{1,3}(?:\.\d+)?)%",
                _re.I,
            )
            rows = pattern.findall(" ".join(cleaned.split()))
            if rows:
                target = pd.DataFrame(
                    [(f"{m} {d}", b, n, be) for m, d, b, n, be in rows],
                    columns=["reported date", "bullish", "neutral", "bearish"],
                )
        if target is None or target.empty:
            return {"status": "empty", "source": "AAII official", "score": None, "history": pd.DataFrame(), "detail": "historical table not parsed"}

        for c in ["bullish", "neutral", "bearish"]:
            target[c] = pd.to_numeric(target[c].astype(str).str.replace("%", "", regex=False), errors="coerce")
        date_col = "reported date" if "reported date" in target.columns else target.columns[0]
        now = pd.Timestamp.now(tz="UTC")
        parsed_dates = []
        for raw in target[date_col].astype(str):
            parsed = pd.to_datetime(raw, errors="coerce")
            if pd.notna(parsed) and getattr(parsed, "year", 1900) != 1900:
                d = pd.Timestamp(parsed)
                if d.tzinfo is None:
                    d = d.tz_localize("UTC")
                else:
                    d = d.tz_convert("UTC")
                parsed_dates.append(d)
                continue
            # AAII current page often omits the year; infer it without allowing a future date.
            try:
                d = pd.to_datetime(f"{raw} {now.year}", errors="raise")
                d = pd.Timestamp(d).tz_localize("UTC")
                if d > now + pd.Timedelta(days=7):
                    d = pd.to_datetime(f"{raw} {now.year-1}", errors="raise").tz_localize("UTC")
                parsed_dates.append(pd.Timestamp(d))
            except Exception:
                parsed_dates.append(pd.NaT)
        target["date"] = parsed_dates
        target = target.dropna(subset=["date", "bullish", "bearish"]).copy()
        target = target[(target["bullish"].between(0, 100)) & (target["bearish"].between(0, 100))]
        target["net_bull"] = target["bullish"] - target["bearish"]
        target["belief_score"] = (50.0 + 0.5 * target["net_bull"]).clip(0.0, 100.0)
        target["survey_disagreement"] = (100.0 - target["neutral"].fillna(33.0) - target["net_bull"].abs() * 0.35).clip(0.0, 100.0)
        target = target.drop_duplicates("date", keep="last").sort_values("date")
        if target.empty:
            return {"status": "empty", "source": "AAII official", "score": None, "history": pd.DataFrame(), "detail": "no valid rows"}
        latest = target.iloc[-1]
        out = {
            "status": "ok", "source": "AAII official Sentiment Survey",
            "score": float(latest["belief_score"]),
            "bullish": _finite(latest.get("bullish")), "neutral": _finite(latest.get("neutral")),
            "bearish": _finite(latest.get("bearish")), "net_bull": _finite(latest.get("net_bull")),
            "disagreement": _finite(latest.get("survey_disagreement")),
            "date": str(pd.Timestamp(latest["date"]).date()),
            "history": target[["date", "bullish", "neutral", "bearish", "belief_score", "survey_disagreement"]].reset_index(drop=True),
            "tier": "NEAR_DIRECT_SURVEY",
            "note": "Aggregate own-market outlook / observed crowd distribution; not a direct B2/B3 beliefs-about-others survey.",
        }
        _AAII_DAILY_CACHE[cache_key] = dict(out)
        return out
    except Exception as exc:
        return {"status": "request_error", "source": "AAII official", "score": None, "history": pd.DataFrame(), "detail": type(exc).__name__}


def _kalman_scalar_update(x: np.ndarray, P: np.ndarray, y: float, H: np.ndarray, sigma: float) -> tuple[np.ndarray, np.ndarray]:
    """One scalar measurement update for the 3-state HOB filter.

    NumPy 2.x no longer permits ``float(array([[value]]))``.  Keep the
    state/loading vectors explicitly one-dimensional so all quadratic forms
    below resolve to true scalars rather than 1x1 arrays.  This also makes the
    update robust if a caller hands in x or H as column/row vectors.
    """
    x = np.asarray(x, dtype=float).reshape(-1)
    P = np.asarray(P, dtype=float)
    h = np.asarray(H, dtype=float).reshape(-1)

    if P.shape != (x.size, x.size) or h.size != x.size:
        return x, P

    yy = _finite(y)
    if yy is None:
        return x, P

    R = max(float(sigma) ** 2, 1e-6)
    predicted = float(np.dot(h, x))
    innovation = float(yy - predicted)
    S = float(h @ P @ h + R)
    if not np.isfinite(S) or S <= 1e-9:
        return x, P

    K = (P @ h) / S
    x2 = x + K * innovation
    P2 = (np.eye(x.size) - np.outer(K, h)) @ P
    P2 = (P2 + P2.T) / 2.0
    return x2.reshape(-1), P2


def _current_measurement_rows(i: HOBInputs, direct: Mapping[str, Any] | None = None) -> pd.DataFrame:
    """Fixed sparse loading restrictions for the V3.4 internal measurement cross-check."""
    rows = [
        ("Fundamental anchor", i.fundamental_anchor, [1.00, 0.08, 0.00], "FUNDAMENTAL", 0.88, i.fundamental_anchor_quality),
        ("First-order conviction", i.first_order_conviction, [0.90, 0.10, 0.00], "BEHAVIORAL_LATENT", 0.36, _mean_available([i.belief_confidence, i.latent_stability])),
        ("Private/state proxy", i.private_signal_proxy, [0.85, 0.10, 0.00], "BEHAVIORAL_LATENT", 0.36, _mean_available([i.belief_confidence, 100-i.uncertainty])),
        ("Breadth", i.breadth, [0.60, 0.20, 0.00], "BREADTH", 0.74, i.behavioral_data_evidence),
        ("Public consensus", i.public_consensus, [0.10, 0.85, 0.10], "NLP_PUBLIC", 0.36, i.nlp_evidence),
        ("Narrative consensus", i.narrative_consensus, [0.05, 0.78, 0.17], "NLP_PUBLIC", 0.62, i.nlp_evidence),
        ("Herding", i.herding, [0.05, 0.66, 0.22], "BEHAVIORAL_LATENT", 0.48, i.latent_stability),
        ("Flow pressure", i.flow_pressure, [0.05, 0.55, 0.30], "FLOW", 0.36, i.behavioral_data_evidence),
        ("Positioning", i.positioning_crowding, [0.05, 0.52, 0.34], "POSITIONING", 0.74, i.behavioral_data_evidence),
        ("Reflexivity", i.reflexivity, [0.00, 0.20, 0.86], "BEHAVIORAL_LATENT", 0.48, i.latent_stability),
        ("Attention", i.attention, [0.05, 0.28, 0.56], "BEHAVIORAL_LATENT", 0.48, i.latent_stability),
        ("Options speculation", i.options_speculation, [0.00, 0.25, 0.66], "OPTIONS", 0.74, i.behavioral_data_evidence),
        ("Narrative concentration", i.narrative_concentration, [0.05, 0.30, 0.62], "NLP_PUBLIC", 0.62, i.nlp_evidence),
        ("Agreement inverse", 100.0-i.belief_disagreement, [0.05, 0.50, 0.42], "NLP_PUBLIC", 0.62, i.nlp_evidence),
    ]
    if isinstance(direct, Mapping) and _finite(direct.get("score")) is not None:
        rows.append((
            "AAII observed investor outlook", float(direct["score"]), [0.68, 0.32, 0.00],
            "AAII_SURVEY", 0.86, 72.0,
        ))
    out = []
    for name, value, loading, family, directness, quality in rows:
        v = _finite(value)
        if v is None:
            continue
        out.append({
            "Measurement": name, "Value": float(v), "H1": float(loading[0]), "H2": float(loading[1]), "H3": float(loading[2]),
            "Source family": family, "Directness": float(directness), "Quality": _clip(quality),
        })
    return pd.DataFrame(out)


def restricted_state_space_identification(
    state: Mapping[str, Any], inputs: HOBInputs, proxy_result: HOBResult,
    pit_anchor: Mapping[str, Any] | None = None, direct: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Restricted random-walk Kalman measurement fusion, never fitted to returns.

    This is a model cross-check, not a replacement for the transparent V3.2 proxy
    construction. Historical core proxies provide the daily measurement backbone;
    vintage-locked fundamentals and near-direct survey data enter only when available.
    """
    alpha = inferred_alpha_proxy(inputs)
    core = _historical_core_proxy(state, alpha)
    if core.empty:
        return {"status": "NO_HISTORY", "history": pd.DataFrame(), "current": None}
    core = core.copy()
    if "date" in core.columns:
        core["date"] = pd.to_datetime(core["date"], errors="coerce", utc=True)
        core = core.dropna(subset=["date"]).set_index("date")
    else:
        core.index = pd.to_datetime(core.index, errors="coerce", utc=True)
        core = core[~core.index.isna()]
    core = core.sort_index()
    if core.empty:
        return {"status": "NO_HISTORY", "history": pd.DataFrame(), "current": None}

    pit_series = pd.Series(dtype=float)
    if isinstance(pit_anchor, Mapping):
        ph = pit_anchor.get("history", pd.DataFrame())
        if isinstance(ph, pd.DataFrame) and not ph.empty and "Fundamental anchor · PIT initial release" in ph.columns:
            dates = pd.to_datetime(ph["date"], errors="coerce", utc=True)
            pit_series = pd.Series(pd.to_numeric(ph["Fundamental anchor · PIT initial release"], errors="coerce").to_numpy(), index=dates).dropna().sort_index()
            pit_series = pit_series[~pit_series.index.duplicated(keep="last")]

    survey_series = pd.Series(dtype=float)
    if isinstance(direct, Mapping):
        dh = direct.get("history", pd.DataFrame())
        if isinstance(dh, pd.DataFrame) and not dh.empty and "belief_score" in dh.columns:
            dates = pd.to_datetime(dh["date"], errors="coerce", utc=True)
            survey_series = pd.Series(pd.to_numeric(dh["belief_score"], errors="coerce").to_numpy(), index=dates).dropna().sort_index()
            survey_series = survey_series[~survey_series.index.duplicated(keep="last")]

    idx = core.index
    x = np.array([50.0, 50.0, 50.0], dtype=float)
    P = np.diag([18.0**2, 20.0**2, 22.0**2])
    Q = np.diag([1.7**2, 1.8**2, 2.0**2])
    rows = []
    last_pit = None
    last_survey = None
    for dt in idx:
        P = P + Q
        obs = [
            (core.loc[dt, "B1 core proxy"], np.array([0.88, 0.10, 0.02]), 10.5),
            (core.loc[dt, "B2 core proxy"], np.array([0.12, 0.78, 0.10]), 11.5),
            (core.loc[dt, "B3 core proxy"], np.array([0.04, 0.20, 0.76]), 13.0),
        ]
        for y, H, sigma in obs:
            yy = _finite(y)
            if yy is not None:
                x, P = _kalman_scalar_update(x, P, yy, H, sigma)
        # Use vintage-locked fundamental only when a new public value becomes available.
        if not pit_series.empty:
            available = pit_series[pit_series.index <= dt]
            if not available.empty:
                cur = float(available.iloc[-1])
                release = available.index[-1]
                if last_pit is None or release != last_pit:
                    x, P = _kalman_scalar_update(x, P, cur, np.array([0.94, 0.06, 0.00]), 9.5)
                    last_pit = release
        if not survey_series.empty:
            available = survey_series[survey_series.index <= dt]
            if not available.empty:
                cur = float(available.iloc[-1])
                release = available.index[-1]
                if last_survey is None or release != last_survey:
                    x, P = _kalman_scalar_update(x, P, cur, np.array([0.68, 0.32, 0.00]), 11.0)
                    last_survey = release
        x = np.clip(x, 0.0, 100.0)
        std = np.sqrt(np.maximum(np.diag(P), 0.0))
        rows.append({"date": dt, "SS B1": x[0], "SS B2": x[1], "SS B3": x[2], "SS U1": std[0], "SS U2": std[1], "SS U3": std[2]})

    hist = pd.DataFrame(rows)
    # Current rich cross-sectional measurement update. Source-family repetition is
    # penalized so multiple NLP derivatives cannot masquerade as independent evidence.
    current_rows = _current_measurement_rows(inputs, direct)
    if not hist.empty:
        x = hist[["SS B1", "SS B2", "SS B3"]].iloc[-1].to_numpy(float)
        P = np.diag(np.square(hist[["SS U1", "SS U2", "SS U3"]].iloc[-1].to_numpy(float)))
    fam_counts = current_rows["Source family"].value_counts().to_dict() if not current_rows.empty else {}
    update_audit = []
    for _, row in current_rows.iterrows():
        H = row[["H1", "H2", "H3"]].to_numpy(float)
        directness = float(row["Directness"])
        quality = float(row["Quality"]) / 100.0
        family_penalty = math.sqrt(max(1, int(fam_counts.get(row["Source family"], 1))))
        sigma = float(np.clip((7.5 + 15.0*(1-directness) + 12.0*(1-quality)) * family_penalty, 7.0, 36.0))
        before = x.copy()
        x, P = _kalman_scalar_update(x, P, float(row["Value"]), H, sigma)
        update_audit.append({
            "Measurement": row["Measurement"], "Source family": row["Source family"], "Sigma": sigma,
            "ΔB1": x[0]-before[0], "ΔB2": x[1]-before[1], "ΔB3": x[2]-before[2],
        })
    x = np.clip(x, 0.0, 100.0)
    std = np.sqrt(np.maximum(np.diag(P), 0.0))
    proxy = np.array([proxy_result.b1, proxy_result.b2, proxy_result.b3], dtype=float)
    mae = float(np.mean(np.abs(x - proxy)))
    agreement = float(np.clip(100.0 - 4.0 * mae, 0.0, 100.0))
    return {
        "status": "OK", "history": hist, "current": x, "uncertainty": std,
        "agreement": agreement, "mae": mae, "measurement_rows": current_rows,
        "update_audit": pd.DataFrame(update_audit),
        "note": "Restricted random-walk Kalman measurement fusion with fixed sparse loadings; no return target is fitted.",
    }


def _top_contribution_summary(contrib: pd.DataFrame, order: str) -> tuple[str, str]:
    d = contrib[contrib["Order"] == order].copy() if isinstance(contrib, pd.DataFrame) and not contrib.empty else pd.DataFrame()
    if d.empty:
        return "N/A", "N/A"
    d["Contribution pts"] = pd.to_numeric(d["Contribution pts"], errors="coerce")
    d = d.dropna(subset=["Contribution pts"])
    if d.empty:
        return "N/A", "N/A"
    pos = d.sort_values("Contribution pts", ascending=False).iloc[0]
    neg = d.sort_values("Contribution pts", ascending=True).iloc[0]
    return f"{pos['Input']} ({pos['Contribution pts']:+.1f})", f"{neg['Input']} ({neg['Contribution pts']:+.1f})"


def _transition_watch(reach: pd.DataFrame, current_regime: str) -> dict[str, Any]:
    if not isinstance(reach, pd.DataFrame) or reach.empty:
        return {"nearest": "N/A", "distance": None, "local": 0.0}
    others = reach[reach["Regime"] != current_regime].copy()
    others["Nearest local distance"] = pd.to_numeric(others["Nearest local distance"], errors="coerce")
    others = others.dropna(subset=["Nearest local distance"]).sort_values("Nearest local distance")
    current = reach[reach["Regime"] == current_regime]
    local = float(current["Local reach %"].iloc[0]) if not current.empty else 0.0
    if others.empty:
        return {"nearest": "N/A", "distance": None, "local": local}
    row = others.iloc[0]
    return {"nearest": str(row["Regime"]), "distance": float(row["Nearest local distance"]), "local": local}


def _strategic_brief(
    result: HOBResult, p_skeptic: float, p_mania: float,
    fundamental: Mapping[str, Any], state_space: Mapping[str, Any],
    contrib: pd.DataFrame, transition: Mapping[str, Any],
) -> list[str]:
    lines = []
    lines.append(
        f"Belief hierarchy: B1 {result.b1:.1f} vs B2 {result.b2:.1f} vs B3 {result.b3:.1f}; "
        f"measurement perturbations preserve B1>B2>B3 in {p_skeptic:.0f}% of draws."
    )
    pfg = _finite(result.price_fundamental_gap)
    if pfg is not None:
        qualifier = "small" if abs(pfg) < 6 else "material" if abs(pfg) < 15 else "large"
        lines.append(f"Fundamental disconnect: normalized price–fundamental gap {pfg:+.1f} ({qualifier}); V3.4 does not attribute it causally to HOB.")
    if isinstance(state_space, Mapping) and state_space.get("status") == "OK":
        ss = state_space.get("current")
        if ss is not None:
            lines.append(f"Internal measurement-model cross-check: state-space estimate {ss[0]:.1f}/{ss[1]:.1f}/{ss[2]:.1f}; proxy/state-space agreement {float(state_space.get('agreement',0)):.0f}/100.")
    pos2, neg2 = _top_contribution_summary(contrib, "B2 crowd target")
    pos3, neg3 = _top_contribution_summary(contrib, "B3 meta target")
    lines.append(f"Crowd-belief drivers: strongest positive {pos2}; strongest drag {neg2}. Meta-belief: positive {pos3}; drag {neg3}.")
    if p_mania < 10:
        lines.append(f"Higher-order mania geometry is not identified: only {p_mania:.1f}% of measurement perturbations produce B3>B2>B1.")
    nearest = str(transition.get("nearest", "N/A"))
    dist = _finite(transition.get("distance"))
    if nearest != "N/A" and dist is not None:
        lines.append(f"Transition watch: nearest alternative taxonomy region is {nearest} at normalized local distance {dist:.2f}; this is reachability, not forecast probability.")
    return lines



def direct_belief_evidence_by_order(direct: Mapping[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Separate structural identification from direct/near-direct belief evidence."""
    d = _mapping(direct)
    aaii_ok = _finite(d.get("score")) is not None
    return {
        "B1": {
            "score": 72.0 if aaii_ok else 0.0,
            "tier": "NEAR-DIRECT" if aaii_ok else "MISSING",
            "source": "AAII own-market outlook" if aaii_ok else "No direct/near-direct survey",
        },
        "B2": {"score": 0.0, "tier": "MISSING", "source": "No direct beliefs-about-others survey"},
        "B3": {"score": 0.0, "tier": "MISSING", "source": "No direct third-order belief survey"},
    }


def chronology_coverage_matrix(
    state: Mapping[str, Any], fundamental: Mapping[str, Any], direct: Mapping[str, Any],
    archive_info: Mapping[str, Any], state_space: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Audit what is truly chronology-safe versus prospective/current-only.

    The historical state-space reconstruction is allowed to use only core causal
    history, initial-release fundamentals, and publication-dated survey rows.  Current
    narrative/options/positioning enrich the *current* state but are not retro-backfilled.
    """
    pit = _mapping(fundamental.get("pit"))
    pit_ok = _finite(pit.get("anchor")) is not None and isinstance(pit.get("history"), pd.DataFrame) and not pit.get("history").empty
    pit_cov = _clip(pit.get("coverage"), default=0.0)
    direct_hist = direct.get("history", pd.DataFrame()) if isinstance(direct, Mapping) else pd.DataFrame()
    survey_ok = _finite(direct.get("score")) is not None if isinstance(direct, Mapping) else False
    survey_hist_ok = survey_ok and isinstance(direct_hist, pd.DataFrame) and not direct_hist.empty
    ss_ok = state_space.get("status") == "OK" and isinstance(state_space.get("history"), pd.DataFrame) and not state_space.get("history").empty
    snapshots = int(archive_info.get("snapshots", 0) or 0)

    rows = [
        ("Core price / latent-state backbone", "USED", "CAUSAL / OBSERVED HISTORY", 100, "Historical prices and one-sided/core state reconstruction; no future outcomes."),
        ("Fundamental anchor · initial release", "USED" if pit_ok else "REQUESTED / EXCLUDED", "VINTAGE-LOCKED" if pit_ok else "MISSING", pit_cov if pit_ok else 0, "FRED/ALFRED initial public values keyed to release dates."),
        ("AAII near-direct investor outlook", "USED" if survey_hist_ok else "OPTIONAL / EXCLUDED", "PUBLICATION-DATED" if survey_hist_ok else "MISSING", 72 if survey_hist_ok else 0, "Own-market outlook only; never relabeled as direct B2/B3 HOB."),
        ("Narrative / news HOB", "CURRENT ONLY", "PROSPECTIVE-ONLY", 0, "Not retrospectively backfilled; future PIT observations accumulate through daily snapshots."),
        ("Options / speculative convexity", "CURRENT ONLY", "PROSPECTIVE-ONLY", 0, "No retrospective HOB options backfill in this specification."),
        ("Positioning / crowding", "CURRENT ONLY", "CURRENT / LAG-AWARE", 0, "Used for current cross-section; excluded from reconstructed HOB history unless a release-dated archive exists."),
        ("Restricted state-space reconstruction", "ACTIVE" if ss_ok else "PARTIAL", "CHRONOLOGY-SAFE CORE" if (ss_ok and pit_ok) else "PARTIAL-PIT RECONSTRUCTION", 100 if (ss_ok and pit_ok) else 55 if ss_ok else 0, "Uses only chronology-eligible measurements at historical dates."),
        ("Prospective full-HOB archive", "BUILDING", "PIT SNAPSHOTS", min(100, snapshots * 2), f"{snapshots} daily snapshot(s); required before validating narrative/options-rich HOB states."),
    ]
    df = pd.DataFrame(rows, columns=["Layer", "Historical role", "Chronology status", "Coverage /100", "Rule / limitation"])
    core_ready = bool(ss_ok and pit_ok)
    overall = "CHRONOLOGY-SAFE CORE" if core_ready else "PARTIAL-PIT RECONSTRUCTION"
    score = float(np.clip(55.0 + (30.0 if pit_ok else 0.0) + (8.0 if survey_hist_ok else 0.0) + min(7.0, snapshots / 10.0), 0.0, 100.0)) if ss_ok else 0.0
    return df, {
        "status": overall, "score": score, "pit_fundamental": pit_ok,
        "survey_history": survey_hist_ok, "state_space": ss_ok, "snapshots": snapshots,
        "full_hob_history_ready": snapshots >= 120,
    }


def _taxonomy_witnesses() -> dict[str, dict[str, float]]:
    """Constructive witnesses derived from the fixed V3.4 regime inequalities."""
    base = {"u1": 20.0, "u2": 20.0, "u3": 20.0, "d2": 32.0, "d3": 32.0, "reflexivity": 45.0, "ck": 60.0}
    def w(b1, b2, b3, **kw):
        return {**base, "b1": float(b1), "b2": float(b2), "b3": float(b3), **{k: float(v) for k, v in kw.items()}}
    return {
        "COORDINATION BREAKDOWN": w(50, 50, 50, d2=80, ck=60),
        "HIGHER-ORDER MANIA": w(48, 65, 78, reflexivity=75, ck=75),
        "SPECULATIVE BEAUTY CONTEST": w(48, 65, 61, reflexivity=45, ck=70),
        "STRATEGIC SKEPTICISM": w(66, 52, 47, reflexivity=45, ck=65),
        "STRATEGIC DISTRUST": w(66, 46, 50, u1=35, u2=35, reflexivity=40, ck=65),
        "CONTRARIAN / RESALE COORDINATION": w(40, 58, 55, reflexivity=45, ck=65),
        "FUNDAMENTAL / COMMON CONSENSUS": w(64, 63, 62, d2=30, d3=30, reflexivity=40, ck=72),
        "REFLEXIVE COORDINATION": w(50, 56, 54, reflexivity=80, ck=65),
        "MIXED STRATEGIC BELIEFS": w(50, 50, 50, d2=52, d3=52, reflexivity=45, ck=55),
    }


def regime_feasibility_solver(seed: int = 41) -> pd.DataFrame:
    """Deterministic rule-feasibility audit for the fixed taxonomy.

    Unlike Monte-Carlo reachability, this asks whether each regime has at least one
    explicit latent-geometry witness satisfying the ordered regime rules.  A small
    deterministic neighborhood test distinguishes robust from boundary-only witnesses.
    It never sees market outcomes and never retunes thresholds.
    """
    rng = np.random.default_rng(int(seed))
    rows = []
    for target, q in _taxonomy_witnesses().items():
        got, strength = _regime_from_geometry(
            q["b1"], q["b2"], q["b3"], q["u1"], q["u2"], q["u3"],
            q["d2"], q["d3"], q["reflexivity"], q["ck"],
        )
        feasible = got == target
        local_hits = 0
        local_n = 80
        if feasible:
            for _ in range(local_n):
                z = dict(q)
                for k in ["b1", "b2", "b3", "d2", "d3", "reflexivity", "ck"]:
                    z[k] = float(np.clip(rng.normal(z[k], 1.5), 0, 100))
                g, _ = _regime_from_geometry(z["b1"], z["b2"], z["b3"], z["u1"], z["u2"], z["u3"], z["d2"], z["d3"], z["reflexivity"], z["ck"])
                local_hits += int(g == target)
        neighborhood = 100.0 * local_hits / max(local_n, 1) if feasible else 0.0
        status = "FEASIBLE" if feasible and neighborhood >= 40 else "BOUNDARY-FEASIBLE" if feasible else "INFEASIBLE"
        rows.append({
            "Regime": target, "Feasibility": status, "Neighborhood pass %": neighborhood,
            "Witness B1/B2/B3": f"{q['b1']:.0f}/{q['b2']:.0f}/{q['b3']:.0f}",
            "Witness d2/d3": f"{q['d2']:.0f}/{q['d3']:.0f}",
            "Witness reflexivity": q["reflexivity"], "Witness common knowledge": q["ck"],
            "Classifier result": got, "Geometry strength": strength,
        })
    return pd.DataFrame(rows)


def measurement_spec_freeze_gate(
    chronology: Mapping[str, Any], feasibility: pd.DataFrame, direct_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    taxonomy_pass = isinstance(feasibility, pd.DataFrame) and not feasibility.empty and not feasibility["Feasibility"].eq("INFEASIBLE").any()
    chronology_pass = str(chronology.get("status")) == "CHRONOLOGY-SAFE CORE"
    blockers = []
    if not chronology_pass:
        blockers.append("PIT fundamental/core chronology incomplete")
    if not taxonomy_pass:
        blockers.append("taxonomy contains infeasible regime(s)")
    b2_direct = float(_mapping(direct_evidence.get("B2")).get("score", 0.0) or 0.0)
    b3_direct = float(_mapping(direct_evidence.get("B3")).get("score", 0.0) or 0.0)
    if b2_direct <= 0 or b3_direct <= 0:
        # This is a documented identification limitation, not a chronology/taxonomy
        # blocker for freezing the measurement specification itself.
        direct_note = "B2/B3 direct HOB evidence missing — predictive promotion remains constrained"
    else:
        direct_note = "Direct HOB evidence available"
    ready = chronology_pass and taxonomy_pass
    return {
        "status": "READY TO FREEZE" if ready else "NOT READY",
        "chronology_pass": chronology_pass, "taxonomy_pass": taxonomy_pass,
        "blockers": blockers, "direct_evidence_note": direct_note,
    }


def _research_status_table(
    result: HOBResult, fundamental_v34: Mapping[str, Any], direct: Mapping[str, Any],
    state_space: Mapping[str, Any], archive_info: Mapping[str, Any], stability: float,
    chronology: Mapping[str, Any] | None = None, feasibility: pd.DataFrame | None = None,
    freeze_gate: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    pit = _mapping(fundamental_v34.get("pit"))
    pit_ready = _finite(pit.get("anchor")) is not None
    direct_ok = _finite(direct.get("score")) is not None
    chron = _mapping(chronology)
    feasible = isinstance(feasibility, pd.DataFrame) and not feasibility.empty and not feasibility["Feasibility"].eq("INFEASIBLE").any()
    fg = _mapping(freeze_gate)
    rows = [
        ("Frozen V2.5.3 core", "LOCKED", 100, "No HOB output feeds back into validated Psychology."),
        ("Vintage-locked fundamental history", "ACTIVE" if pit_ready else "MISSING", int(_clip(pit.get("quality"), default=0)), "FRED/ALFRED initial-release observations; chronology blocker if absent."),
        ("Chronology-safe reconstructed core", str(chron.get("status", "PARTIAL")), int(_clip(chron.get("score"), default=0)), "Only chronology-eligible historical measurements may enter reconstructed HOB history."),
        ("Near-direct investor belief", "ACTIVE" if direct_ok else "BEST-EFFORT", 72 if direct_ok else 0, "AAII own-market outlook; B1/crowd evidence, never direct B2/B3 HOB."),
        ("B1 structural identification", "EXPERIMENTAL", int(result.b1_identification), "Measurement architecture; not a probability that B1 is observed correctly."),
        ("B2 structural identification", "EXPERIMENTAL", int(result.b2_identification), "Public/narrative/crowd footprints; direct beliefs-about-others evidence remains absent."),
        ("B3 structural identification", "EXPERIMENTAL", int(result.b3_identification), "Coordination/feedback footprints; direct third-order evidence remains absent."),
        ("Restricted state-space cross-check", "ACTIVE" if state_space.get("status") == "OK" else "PARTIAL", int(_clip(state_space.get("agreement"), default=0)), "Internal measurement-spec agreement; not independent external validation."),
        ("Taxonomy rule feasibility", "PASS" if feasible else "FAIL", 100 if feasible else 0, "Constructive witnesses test the fixed regime inequalities without market outcomes."),
        ("Regime parameter stability", "ACTIVE", int(stability), "α×τ sensitivity; not predictive evidence."),
        ("Prospective full-HOB archive", "BUILDING", min(100, int(12 + 2 * int(archive_info.get("snapshots", 0)))), "Daily derived snapshots only; no narrative/options retrospective backfill."),
        ("Measurement-spec pre-freeze", str(fg.get("status", "NOT READY")), 100 if fg.get("status") == "READY TO FREEZE" else 0, "; ".join(fg.get("blockers", [])) or str(fg.get("direct_evidence_note", ""))),
        ("Predictive validation", "NOT ESTABLISHED", 0, "Freeze the HOB measurement specification before any walk-forward/holdout test."),
    ]
    return pd.DataFrame(rows, columns=["Component", "Status", "Readiness /100", "Rule / limitation"])


def archive_hob_snapshot_v33(
    state: Mapping[str, Any], result: HOBResult, extras: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Archive via the existing file, adding V3.4 fields without creating folders."""
    base = archive_hob_snapshot(state, result)
    if base.get("status") != "OK" or not extras:
        return base
    path = Path(str(base["path"]))
    try:
        df = pd.read_csv(path)
        if df.empty:
            return base
        symbol = str(state.get("symbol", "MARKET")).upper()
        target = state.get("target_history", pd.DataFrame())
        if isinstance(target, pd.DataFrame) and not target.empty:
            if "date" in target.columns:
                dt = pd.to_datetime(target["date"], errors="coerce").dropna()
            else:
                dt = pd.Series(pd.to_datetime(target.index, errors="coerce")).dropna()
            date_value = pd.Timestamp(dt.iloc[-1]).strftime("%Y-%m-%d") if len(dt) else pd.Timestamp.utcnow().strftime("%Y-%m-%d")
        else:
            date_value = pd.Timestamp.utcnow().strftime("%Y-%m-%d")
        mask = (df["symbol"].astype(str).str.upper() == symbol) & (df["date"].astype(str) == date_value)
        for key, value in extras.items():
            if key not in df.columns:
                df[key] = np.nan
            df.loc[mask, key] = value
        tmp = path.with_suffix(".tmp.csv")
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)
        base["snapshots"] = int(len(df))
        return base
    except Exception as exc:
        return {**base, "status": "ERROR_ENRICH", "detail": type(exc).__name__}


def render_higher_order_beliefs(state: Mapping[str, Any]) -> None:
    """Render the V3.4 HOB research layer inside Market Psychology Lab."""
    import streamlit as st
    import plotly.graph_objects as go
    import plotly.express as px

    symbol = str(state.get("symbol", "MKT")).upper()
    st.markdown("<div class='psy-section'>Higher-Order Beliefs · V3.4 Chronology Integrity & Taxonomy Pre-Freeze</div>", unsafe_allow_html=True)
    st.warning(
        "Experimental research overlay only — NOT part of the frozen V2.5.3 baseline. "
        "B1/B2/B3 remain inferred latent research states. V3.4 hardens initial-release chronology, "
        "separates structural identification from direct evidence, and audits taxonomy feasibility; none is a trading signal."
    )

    # -------------------- Controls & core measurements --------------------
    fundamental = build_fundamental_anchor_v33(state, symbol)
    live_anchor = _finite(fundamental.get("anchor"))
    pit_anchor = _finite(fundamental.get("pit_anchor"))
    direct = fetch_aaii_direct_belief()

    with st.expander("Research controls · parameters, anchor mode & theory", expanded=False):
        c1, c2, c3 = st.columns([1.1, 1.0, 1.0])
        with c1:
            parameter_mode = st.selectbox(
                "Parameter mode", ["SCENARIO · literature anchor", "INFERRED PROXY · market footprints"],
                index=0, key=f"hob_mode_{symbol}",
            )
        with c2:
            alpha_scenario = st.slider("Strategic complementarity α", 0.0, 0.90, 0.55, 0.05, key=f"hob_alpha_{symbol}")
        with c3:
            tau_scenario = st.slider("Cognitive hierarchy τ", 0.3, 4.0, 1.5, 0.1, key=f"hob_tau_{symbol}")
        a1, a2, a3 = st.columns([1.2, 1.0, 1.0])
        with a1:
            anchor_options = ["AUTO · live current-vintage + PIT initial-release", "MANUAL · research scenario", "DISABLED"]
            anchor_mode = st.selectbox("Fundamental anchor mode", anchor_options, index=0 if live_anchor is not None else 2, key=f"hob_anchor_mode_{symbol}")
        with a2:
            manual_anchor = st.slider("Manual anchor", 0.0, 100.0, 50.0, 1.0, disabled=not anchor_mode.startswith("MANUAL"), key=f"hob_anchor_{symbol}")
        with a3:
            st.metric("PIT fundamental", "N/A" if pit_anchor is None else f"{pit_anchor:.1f}", f"quality {float(fundamental.get('pit_quality',0)):.0f}/100")
        st.latex(r"a_{i,t}=(1-\alpha)E_i[\theta_t]+\alpha E_i[\bar a_t]")
        st.latex(r"B_t^{(1)}=E_t[\theta_t],\quad B_t^{(2)}=E_t[\bar B_t^{(1)}],\quad B_t^{(3)}=E_t[\bar B_t^{(2)}]")
        st.latex(r"G_t^{spec}=B_t^{(2)}-B_t^{(1)},\qquad G_t^{meta}=B_t^{(3)}-B_t^{(2)}")
        st.latex(r"\pi_k(\tau)=e^{-\tau}\frac{\tau^k}{k!}")
        st.caption("PIT fundamentals use FRED/ALFRED initial-release observations. V3.4 first requests official output_type=4 and falls back to the earliest real-time period for each observation when needed; release dates remain the chronology key. Current diagnosis still uses today’s live current-vintage anchor.")
        st.dataframe(_literature_table(), use_container_width=True, hide_index=True)

    if anchor_mode.startswith("AUTO") and live_anchor is not None:
        chosen_anchor = live_anchor
        live_meta = _mapping(fundamental.get("live"))
        anchor_meta = {**live_meta, "temporal_integrity": fundamental.get("temporal_integrity")}
    elif anchor_mode.startswith("MANUAL"):
        chosen_anchor = float(manual_anchor)
        anchor_meta = {"quality": 35.0, "source": "MANUAL RESEARCH INPUT", "temporal_integrity": "SCENARIO ONLY", "status": "MANUAL"}
    else:
        chosen_anchor = None
        anchor_meta = {"quality": 0.0, "source": "NONE", "temporal_integrity": "UNAVAILABLE", "status": "DISABLED"}

    inputs, evidence = inputs_from_psychology_state(state, chosen_anchor, anchor_meta)
    proxy_alpha = inferred_alpha_proxy(inputs)
    proxy_tau = inferred_tau_proxy(inputs)
    inferred_mode = parameter_mode.startswith("INFERRED")
    cfg = HOBConfig(
        strategic_complementarity=alpha_scenario,
        cognitive_hierarchy_tau=tau_scenario,
        max_cognitive_level=6,
        fundamental_anchor=chosen_anchor,
        parameter_mode="INFERRED" if inferred_mode else "SCENARIO",
    )
    result = infer_hob(inputs, cfg)
    identification_detail, identification_summary = identification_matrix(inputs)
    uncertainty_draws, uncertainty_envelope = uncertainty_propagation(inputs, cfg, n=500, seed=_stable_seed(symbol, HOB_RESEARCH_VERSION, "measurement"))
    p_b2_gt_b1 = float((uncertainty_draws["B2"] > uncertainty_draws["B1"]).mean() * 100.0) if not uncertainty_draws.empty else 0.0
    p_b3_gt_b2 = float((uncertainty_draws["B3"] > uncertainty_draws["B2"]).mean() * 100.0) if not uncertainty_draws.empty else 0.0
    p_skeptic = float(((uncertainty_draws["B1"] > uncertainty_draws["B2"]) & (uncertainty_draws["B2"] > uncertainty_draws["B3"])).mean() * 100.0) if not uncertainty_draws.empty else 0.0
    p_mania = float(((uncertainty_draws["B3"] > uncertainty_draws["B2"]) & (uncertainty_draws["B2"] > uncertainty_draws["B1"])).mean() * 100.0) if not uncertainty_draws.empty else 0.0
    point_geometry = _point_geometry_label(result)
    contrib = contribution_table(inputs, cfg)
    reach = regime_reachability(inputs, cfg, n_global=520, n_local=260, seed=_stable_seed(symbol, HOB_RESEARCH_VERSION, "reachability"))
    transition = _transition_watch(reach, result.regime)
    state_space = restricted_state_space_identification(state, inputs, result, _mapping(fundamental.get("pit")), direct)
    direct_evidence = direct_belief_evidence_by_order(direct)

    sens = sensitivity_grid(inputs, 6)
    current_wedge = result.cognitive_hierarchy_value - result.b1
    if current_wedge >= 8 and result.cognitive_hierarchy_value >= 58:
        current_sreg = "CROWD-LED / SPECULATIVE"
    elif current_wedge <= -8 and result.b1 >= 55:
        current_sreg = "STRATEGIC SKEPTICISM"
    elif abs(current_wedge) <= 4:
        current_sreg = "FUNDAMENTAL-ALIGNED"
    else:
        current_sreg = "MIXED"
    stability = float((sens["sensitivity_regime"] == current_sreg).mean() * 100.0) if not sens.empty else 0.0

    # Archive only default automatic research measurement; never UI scenario choices.
    archive_anchor = live_anchor
    archive_meta = _mapping(fundamental.get("live")) if live_anchor is not None else None
    archive_inputs, _ = inputs_from_psychology_state(state, archive_anchor, archive_meta)
    archive_result = infer_hob(archive_inputs, HOBConfig(fundamental_anchor=archive_anchor))
    ss_cur = state_space.get("current") if state_space.get("status") == "OK" else None
    ss_u = state_space.get("uncertainty") if state_space.get("status") == "OK" else None
    archive_extras = {
        "fundamental_anchor_pit": pit_anchor,
        "fundamental_revision_gap": _finite(fundamental.get("revision_gap")),
        "pit_anchor_quality": _finite(fundamental.get("pit_quality")),
        "direct_belief_score": _finite(direct.get("score")),
        "direct_belief_source": str(direct.get("source", "NONE")),
        "state_space_b1": None if ss_cur is None else float(ss_cur[0]),
        "state_space_b2": None if ss_cur is None else float(ss_cur[1]),
        "state_space_b3": None if ss_cur is None else float(ss_cur[2]),
        "state_space_u1": None if ss_u is None else float(ss_u[0]),
        "state_space_u2": None if ss_u is None else float(ss_u[1]),
        "state_space_u3": None if ss_u is None else float(ss_u[2]),
        "state_space_agreement": _finite(state_space.get("agreement")),
        "chronology_status": chronology.get("status") if "chronology" in locals() else None,
        "chronology_score": chronology.get("score") if "chronology" in locals() else None,
        "taxonomy_feasibility": None,
        "spec_freeze_status": None,
        "b1_direct_evidence": _mapping(direct_evidence.get("B1")).get("score") if "direct_evidence" in locals() else None,
        "b2_direct_evidence": _mapping(direct_evidence.get("B2")).get("score") if "direct_evidence" in locals() else None,
        "b3_direct_evidence": _mapping(direct_evidence.get("B3")).get("score") if "direct_evidence" in locals() else None,
    }
    archive_info = archive_hob_snapshot_v33(state, archive_result, archive_extras)
    chronology_df, chronology = chronology_coverage_matrix(state, fundamental, direct, archive_info, state_space)
    feasibility = regime_feasibility_solver(seed=_stable_seed(symbol, HOB_RESEARCH_VERSION, "taxonomy_feasibility"))
    freeze_gate = measurement_spec_freeze_gate(chronology, feasibility, direct_evidence)

    # Re-write the same-day prospective snapshot with chronology/taxonomy metadata
    # that only becomes available after the first archive pass. The archive helper
    # upserts the current date, so this enriches rather than duplicates the row.
    feasible_n = int((feasibility["Feasibility"] != "INFEASIBLE").sum()) if isinstance(feasibility, pd.DataFrame) and not feasibility.empty else 0
    archive_extras.update({
        "chronology_status": chronology.get("status"),
        "chronology_score": chronology.get("score"),
        "taxonomy_feasibility": f"{feasible_n}/9",
        "spec_freeze_status": freeze_gate.get("status"),
    })
    archive_info = archive_hob_snapshot_v33(state, archive_result, archive_extras)

    # ============================ EXECUTIVE HEADER ============================
    st.markdown("### Strategic Belief Intelligence")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Research regime", result.regime)
    k2.metric("Geometry robustness", f"{p_skeptic:.0f}%" if result.regime == "STRATEGIC SKEPTICISM" else f"{max(p_skeptic,p_mania):.0f}%")
    k3.metric("Price − fundamentals", "N/A" if result.price_fundamental_gap is None else f"{result.price_fundamental_gap:+.1f}")
    k4.metric("Identification", f"{result.identification_confidence:.0f}/100", result.identification_grade)
    k5.metric("Internal model agreement", "N/A" if state_space.get("status") != "OK" else f"{float(state_space.get('agreement',0)):.0f}/100")
    k6.metric("Pre-freeze status", str(freeze_gate.get("status")), f"chronology {float(chronology.get('score',0)):.0f}/100")

    brief = _strategic_brief(result, p_skeptic, p_mania, fundamental, state_space, contrib, transition)
    brief.append(f"Chronology integrity: {chronology.get('status')} ({float(chronology.get('score',0)):.0f}/100); full narrative/options-rich HOB remains prospective until the archive matures.")
    brief.append(f"Taxonomy feasibility: {feasible_n}/9 regimes have explicit rule witnesses; empirical reachability frequency is reported separately and does not redefine the taxonomy.")
    brief.append(f"Direct evidence discipline: B2/B3 direct HOB survey evidence remains 0/100 even when structural identification is higher.")
    st.info("\n\n".join([f"• {x}" for x in brief]))

    # Compact belief strip.
    b1c, b2c, b3c, b4c, b5c, b6c = st.columns(6)
    b1c.metric("B1 · own/state", f"{result.b1:.1f}", f"±{result.u1:.1f} U")
    b2c.metric("B2 · crowd", f"{result.b2:.1f}", f"{result.speculative_gap:+.1f} vs B1")
    b3c.metric("B3 · meta-crowd", f"{result.b3:.1f}", f"{result.meta_gap:+.1f} vs B2")
    b4c.metric("Common knowledge", f"{result.common_knowledge_intensity:.1f}")
    b5c.metric("Coordination", f"{result.coordination_pressure:.1f}")
    b6c.metric("Strategic fragility", f"{result.strategic_fragility:.1f}")

    tab_exec, tab_ident, tab_fund, tab_dyn, tab_robust, tab_hist = st.tabs([
        "Executive Map", "Identification", "Fundamentals", "Strategic Dynamics", "Robustness & Scenarios", "History & Audit"
    ])

    # ============================ EXECUTIVE MAP ============================
    with tab_exec:
        st.markdown("#### Current geometry & transition watch")
        c1, c2 = st.columns([1.05, 0.95])
        with c1:
            fig = go.Figure()
            xs = ["B1 · own/state", "B2 · crowd", "B3 · meta-crowd"]
            ys = [result.b1, result.b2, result.b3]
            us = [result.u1, result.u2, result.u3]
            fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers+text", text=[f"{v:.1f}" for v in ys], textposition="top center", error_y=dict(type="data", array=us, visible=True), name="Proxy hierarchy"))
            if state_space.get("status") == "OK":
                ss = state_space["current"]
                fig.add_trace(go.Scatter(x=xs, y=ss, mode="markers+text", text=[f"SS {v:.1f}" for v in ss], textposition="bottom center", name="Restricted state-space"))
            fig.add_hline(y=50, line_dash="dot", opacity=0.4)
            fig.update_yaxes(range=[0,100], title="Belief state")
            fig.update_layout(height=390, margin=dict(l=20,r=20,t=35,b=20), title="Belief hierarchy · proxy + structural cross-check")
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            phase = go.Figure()
            phase.add_vline(x=0, line_dash="dot", opacity=0.4); phase.add_hline(y=0, line_dash="dot", opacity=0.4)
            phase.add_trace(go.Scatter(x=[result.speculative_gap], y=[result.meta_gap], mode="markers+text", text=[result.regime], textposition="top center", marker=dict(size=max(18,14+result.higher_order_dominance*0.3))))
            lim=max(20,abs(result.speculative_gap)+10,abs(result.meta_gap)+10)
            phase.update_xaxes(range=[-lim,lim], title="B2 − B1"); phase.update_yaxes(range=[-lim,lim], title="B3 − B2")
            phase.update_layout(height=390, margin=dict(l=20,r=20,t=35,b=20), title="Strategic-belief phase space", showlegend=False)
            st.plotly_chart(phase, use_container_width=True)
        e1,e2,e3,e4,e5 = st.columns(5)
        e1.metric("Point geometry", point_geometry)
        e2.metric("Uncertainty-adjusted", result.regime)
        e3.metric("P(B1>B2>B3)", f"{p_skeptic:.1f}%")
        e4.metric("P(B3>B2>B1)", f"{p_mania:.1f}%")
        e5.metric("Nearest alternative", str(transition.get("nearest","N/A")), "N/A" if _finite(transition.get("distance")) is None else f"distance {float(transition['distance']):.2f}")

        st.markdown("#### Strategic condition board")
        pfg = _finite(result.price_fundamental_gap)
        board = pd.DataFrame([
            ("Belief hierarchy", "STRUCTURED" if p_skeptic>=70 else "MIXED", f"P(B1>B2>B3) {p_skeptic:.1f}%", "Geometry robustness under measurement perturbations"),
            ("Fundamental disconnect", "LOW" if pfg is not None and abs(pfg)<6 else "WATCH" if pfg is not None and abs(pfg)<15 else "HIGH" if pfg is not None else "N/A", "N/A" if pfg is None else f"PFG {pfg:+.1f}", "Normalized state gap, not dollar mispricing"),
            ("Coordination pressure", "NORMAL" if result.coordination_pressure<55 else "ELEVATED" if result.coordination_pressure<70 else "HIGH", f"{result.coordination_pressure:.1f}", "Crowd/common-knowledge coordination footprint"),
            ("Strategic fragility", "NORMAL" if result.strategic_fragility<50 else "ELEVATED" if result.strategic_fragility<70 else "HIGH", f"{result.strategic_fragility:.1f}", "Wedges + crowding + disagreement + constraints"),
            ("Structural identification", result.identification_grade, f"{result.identification_confidence:.0f}/100", f"Source independence {result.source_independence:.0f}/100"),
            ("Chronology integrity", str(chronology.get("status")), f"{float(chronology.get('score',0)):.0f}/100", "Historical reconstruction status; full HOB still requires prospective snapshots"),
            ("Measurement pre-freeze", str(freeze_gate.get("status")), "Taxonomy PASS" if freeze_gate.get("taxonomy_pass") else "Taxonomy FAIL", "; ".join(freeze_gate.get("blockers", [])) or freeze_gate.get("direct_evidence_note", "")),
        ], columns=["Dimension","Status","Reading","Interpretation"])
        st.dataframe(board, use_container_width=True, hide_index=True)

    # ============================ IDENTIFICATION ============================
    with tab_ident:
        st.markdown("#### Belief-order Identification Architecture")
        i1,i2,i3,i4 = st.columns(4)
        i1.metric("B1 structural ID", f"{result.b1_identification:.0f}/100", f"{identification_summary['B1']['effective_source_families']:.2f} eff. families")
        i2.metric("B2 structural ID", f"{result.b2_identification:.0f}/100", f"{identification_summary['B2']['effective_source_families']:.2f} eff. families")
        i3.metric("B3 structural ID", f"{result.b3_identification:.0f}/100", f"{identification_summary['B3']['effective_source_families']:.2f} eff. families")
        i4.metric("Source independence", f"{result.source_independence:.0f}/100", f"{result.effective_source_families:.2f} avg families")
        summary_rows=[]
        for order in ["B1","B2","B3"]:
            s=identification_summary[order]
            # identification_matrix already stores these fields on a 0..100 scale.
            # Do not multiply by 100 again when rendering the audit table.
            summary_rows.append((order,s['coverage'],s['directness'],s['quality'],s['source_independence'],s['effective_source_families'],s['score']))
        st.dataframe(pd.DataFrame(summary_rows, columns=["Order","Coverage %","Directness %","Quality %","Source independence %","Effective source families","Identification /100"]), use_container_width=True, hide_index=True)

        d1,d2,d3,d4 = st.columns(4)
        d1.metric("AAII near-direct", "ACTIVE" if _finite(direct.get("score")) is not None else "N/A", "N/A" if _finite(direct.get("score")) is None else f"score {float(direct['score']):.1f}")
        d2.metric("AAII net bull", "N/A" if _finite(direct.get("net_bull")) is None else f"{float(direct['net_bull']):+.1f} pp")
        d3.metric("Direct B2 survey", "MISSING")
        d4.metric("Direct B3 survey", "MISSING")
        st.caption("AAII measures respondents’ own market outlook and the observed crowd distribution. It is near-direct B1/crowd evidence, not a direct beliefs-about-others (B2/B3) survey.")

        st.markdown("#### Structural identification vs direct belief evidence")
        de_rows=[]
        for order in ["B1","B2","B3"]:
            s=identification_summary[order]
            d=_mapping(direct_evidence.get(order))
            de_rows.append((order, float(s.get("identification",0)), float(d.get("score",0) or 0), str(d.get("tier","MISSING")), str(d.get("source","")), float(s.get("source_independence",s.get("independence",0))), float(s.get("effective_source_families",s.get("effective_families",0)))))
        st.dataframe(pd.DataFrame(de_rows,columns=["Order","Structural identification /100","Direct / near-direct belief evidence /100","Direct evidence tier","Direct evidence source","Source independence /100","Effective source families"]),use_container_width=True,hide_index=True)
        st.caption("Structural identification measures the proxy/measurement architecture. Direct evidence is a separate axis. A high structural score must never be read as a probability that B2/B3 are directly observed.")
        if isinstance(direct.get("history"), pd.DataFrame) and not direct["history"].empty:
            dh=direct["history"]
            figd=go.Figure()
            figd.add_trace(go.Scatter(x=dh["date"], y=dh["bullish"], mode="lines+markers", name="Bullish"))
            figd.add_trace(go.Scatter(x=dh["date"], y=dh["bearish"], mode="lines+markers", name="Bearish"))
            figd.add_trace(go.Scatter(x=dh["date"], y=dh["neutral"], mode="lines+markers", name="Neutral"))
            figd.update_layout(height=300, margin=dict(l=20,r=20,t=30,b=20), title="AAII official near-direct investor outlook · recent observations", legend=dict(orientation="h"))
            st.plotly_chart(figd, use_container_width=True)

        st.markdown("#### Restricted state-space identification cross-check")
        if state_space.get("status") == "OK":
            ss=state_space["current"]; su=state_space["uncertainty"]
            ssc1,ssc2,ssc3,ssc4=st.columns(4)
            ssc1.metric("SS B1", f"{ss[0]:.1f}", f"±{su[0]:.1f}")
            ssc2.metric("SS B2", f"{ss[1]:.1f}", f"±{su[1]:.1f}")
            ssc3.metric("SS B3", f"{ss[2]:.1f}", f"±{su[2]:.1f}")
            ssc4.metric("Proxy ↔ SS agreement", f"{float(state_space['agreement']):.0f}/100", f"MAE {float(state_space['mae']):.1f}")
            st.caption(state_space["note"])
            with st.expander("State-space measurement update audit", expanded=False):
                st.dataframe(state_space["measurement_rows"], use_container_width=True, hide_index=True)
                st.dataframe(state_space["update_audit"], use_container_width=True, hide_index=True)
        else:
            st.info("Restricted state-space cross-check unavailable for this run.")

        st.markdown("#### Measurement uncertainty propagation")
        u1,u2,u3,u4=st.columns(4)
        u1.metric("P(B2 > B1)", f"{p_b2_gt_b1:.1f}%")
        u2.metric("P(B3 > B2)", f"{p_b3_gt_b2:.1f}%")
        u3.metric("P(B1 > B2 > B3)", f"{p_skeptic:.1f}%")
        u4.metric("P(B3 > B2 > B1)", f"{p_mania:.1f}%")
        st.dataframe(uncertainty_envelope, use_container_width=True, hide_index=True)
        st.caption("Measurement-sensitivity envelope only — not a Bayesian posterior, t-statistic or frequentist confidence interval.")

        with st.expander("Input directness / source-family audit", expanded=False):
            st.dataframe(identification_detail, use_container_width=True, hide_index=True)
        with st.expander("Direct / near-direct belief measurement roadmap", expanded=False):
            st.dataframe(_belief_measurement_connector_table(), use_container_width=True, hide_index=True)

    # ============================ FUNDAMENTALS ============================
    with tab_fund:
        st.markdown("#### Live vs vintage-locked fundamental state")
        live=_mapping(fundamental.get("live")); pit=_mapping(fundamental.get("pit"))
        f1,f2,f3,f4,f5=st.columns(5)
        f1.metric("Live current-vintage", "N/A" if live_anchor is None else f"{live_anchor:.1f}", f"quality {float(fundamental.get('quality',0)):.0f}/100")
        f2.metric("PIT initial-release", "N/A" if pit_anchor is None else f"{pit_anchor:.1f}", f"quality {float(fundamental.get('pit_quality',0)):.0f}/100")
        f3.metric("Revision-state gap", "N/A" if _finite(fundamental.get('revision_gap')) is None else f"{float(fundamental['revision_gap']):+.1f}")
        f4.metric("Market price-state", f"{result.market_price_state:.1f}")
        f5.metric("Price − live fundamental", "N/A" if result.price_fundamental_gap is None else f"{result.price_fundamental_gap:+.1f}")
        st.caption("Live anchor reflects today’s information set including revisions. PIT history uses initial-release values and availability dates. Neither is a dollar fair-value estimate.")

        pit_components = pit.get("components", pd.DataFrame()) if isinstance(pit, Mapping) else pd.DataFrame()
        if isinstance(pit_components, pd.DataFrame) and not pit_components.empty:
            ok_n = int((pit_components.get("Status", pd.Series(dtype=str)).astype(str).str.upper()=="OK").sum())
            pd1,pd2,pd3=st.columns(3)
            pd1.metric("PIT components usable",f"{ok_n}/{len(pit_components)}")
            methods = sorted(set(str(x) for x in pit_components.get("Acquisition method", pd.Series(dtype=str)).dropna() if str(x) not in {"", "N/A"}))
            pd2.metric("PIT acquisition",", ".join(methods[:2]) if methods else "UNAVAILABLE")
            pd3.metric("PIT chronology",str(pit.get("temporal_integrity","UNAVAILABLE")))

        hf1,hf2=st.columns(2)
        with hf1:
            lh=live.get("history",pd.DataFrame())
            if isinstance(lh,pd.DataFrame) and not lh.empty and "Fundamental anchor · current-vintage" in lh.columns:
                fl=go.Figure(go.Scatter(x=lh["date"], y=lh["Fundamental anchor · current-vintage"], mode="lines", name="Current-vintage"))
                fl.add_hline(y=50,line_dash="dot",opacity=.4); fl.update_yaxes(range=[0,100]); fl.update_layout(height=330,margin=dict(l=20,r=20,t=35,b=20),title="Current-vintage fundamental diagnostic")
                st.plotly_chart(fl,use_container_width=True)
        with hf2:
            ph=pit.get("history",pd.DataFrame())
            if isinstance(ph,pd.DataFrame) and not ph.empty:
                fp=go.Figure(go.Scatter(x=ph["date"], y=ph["Fundamental anchor · PIT initial release"], mode="lines", name="PIT initial release"))
                fp.add_hline(y=50,line_dash="dot",opacity=.4); fp.update_yaxes(range=[0,100]); fp.update_layout(height=330,margin=dict(l=20,r=20,t=35,b=20),title="Vintage-locked initial-release fundamental state")
                st.plotly_chart(fp,use_container_width=True)
        with st.expander("Current-vintage component audit", expanded=False):
            st.dataframe(live.get("components",pd.DataFrame()), use_container_width=True, hide_index=True)
        with st.expander("Initial-release / ALFRED component audit", expanded=False):
            st.dataframe(pit.get("components",pd.DataFrame()), use_container_width=True, hide_index=True)

        st.markdown("#### Fundamental vs strategic price decomposition")
        ff1,ff2,ff3,ff4=st.columns(4)
        ff1.metric("Market price-state", f"{result.market_price_state:.1f}")
        ff2.metric("Fundamental state", "N/A" if result.fundamental_anchor is None else f"{result.fundamental_anchor:.1f}")
        ff3.metric("Price − fundamental", "N/A" if result.price_fundamental_gap is None else f"{result.price_fundamental_gap:+.1f}")
        ff4.metric("Strategic wedge", f"{result.strategic_price_wedge:+.1f}")
        if result.price_fundamental_gap is not None:
            alignment = "ALIGNED" if np.sign(result.price_fundamental_gap)==np.sign(result.strategic_price_wedge) and abs(result.price_fundamental_gap)>=3 else "NOT ALIGNED / WEAK"
            st.info(f"Price/fundamental vs strategic-wedge sign alignment: {alignment}. Descriptive only; V3.4 does not attribute the gap causally to HOB.")

    # ============================ STRATEGIC DYNAMICS ============================
    with tab_dyn:
        st.markdown("#### Information structure & coordination")
        info = pd.DataFrame([
            ("B1 · own/state", result.b1, result.u1, result.d1, _private_signal_strength(inputs), "Private/state + fundamental"),
            ("B2 · crowd", result.b2, result.u2, result.d2, _public_signal_strength(inputs), "Public/common + crowd"),
            ("B3 · meta-crowd", result.b3, result.u3, result.d3, result.coordination_pressure, "Coordination/feedback"),
        ], columns=["Order","Belief","Measurement uncertainty","Disagreement","Signal/coordination strength","Dominant channel"])
        st.dataframe(info,use_container_width=True,hide_index=True)
        ic1,ic2,ic3,ic4,ic5=st.columns(5)
        ic1.metric("Public signal",f"{_public_signal_strength(inputs):.1f}")
        ic2.metric("Private/state",f"{_private_signal_strength(inputs):.1f}")
        ic3.metric("Public − private",f"{result.public_private_wedge:+.1f}")
        ic4.metric("Common knowledge",f"{result.common_knowledge_index:.1f}")
        ic5.metric("Reflexive pressure",f"{result.reflexive_price_pressure:.1f}")

        st.markdown("#### Belief construction · driver map")
        plot=contrib[contrib["Order"].isin(["B1","B2 crowd target","B3 meta target"])].copy()
        if not plot.empty:
            fc=px.bar(plot,x="Contribution pts",y="Input",color="Order",orientation="h",title="Observable footprints pushing each belief order")
            fc.update_layout(height=520,margin=dict(l=20,r=20,t=45,b=20)); st.plotly_chart(fc,use_container_width=True)
        with st.expander("Full contribution table",expanded=False):
            st.dataframe(contrib,use_container_width=True,hide_index=True)

        st.markdown("#### Cognitive hierarchy & strategic depth")
        tau_used=result.tau_proxy if inferred_mode else tau_scenario
        weights=cognitive_hierarchy_weights(tau_used,6)
        hierarchy,_=build_belief_hierarchy(inputs,cfg)
        ch=pd.DataFrame({"Reasoning level k":list(range(len(weights))),"Population weight %":100*weights,"Belief-order proxy":hierarchy[:len(weights)]})
        ch1,ch2=st.columns(2)
        with ch1:
            f=go.Figure(go.Bar(x=ch["Reasoning level k"].astype(str),y=ch["Population weight %"])); f.update_layout(height=320,margin=dict(l=20,r=20,t=30,b=20),yaxis_title="Population weight %"); st.plotly_chart(f,use_container_width=True)
        with ch2:
            f=go.Figure(go.Scatter(x=ch["Reasoning level k"],y=ch["Belief-order proxy"],mode="lines+markers")); f.add_hline(y=result.b1,line_dash="dot",opacity=.4); f.update_yaxes(range=[0,100]); f.update_layout(height=320,margin=dict(l=20,r=20,t=30,b=20)); st.plotly_chart(f,use_container_width=True)
        st.caption("Levels above B3 are recursive sensitivity proxies only; they are not claimed as observed fourth-, fifth- or sixth-order beliefs.")

    # ============================ ROBUSTNESS & SCENARIOS ============================
    with tab_robust:
        st.markdown("#### Parameter robustness · α × τ")
        alpha_p10=float(uncertainty_draws["Alpha proxy"].quantile(.10)) if not uncertainty_draws.empty else proxy_alpha
        alpha_p90=float(uncertainty_draws["Alpha proxy"].quantile(.90)) if not uncertainty_draws.empty else proxy_alpha
        tau_p10=float(uncertainty_draws["Tau proxy"].quantile(.10)) if not uncertainty_draws.empty else proxy_tau
        tau_p90=float(uncertainty_draws["Tau proxy"].quantile(.90)) if not uncertainty_draws.empty else proxy_tau
        r1,r2,r3,r4,r5=st.columns(5)
        r1.metric("Point sensitivity geometry",current_sreg)
        r2.metric("α×τ grid stability",f"{stability:.1f}%")
        r3.metric("α proxy",f"{proxy_alpha:.2f}",f"P10–P90 {alpha_p10:.2f}–{alpha_p90:.2f}")
        r4.metric("τ proxy",f"{proxy_tau:.2f}",f"P10–P90 {tau_p10:.2f}–{tau_p90:.2f}")
        r5.metric("Uncertainty-adjusted regime",result.regime)
        pivot=sens.pivot(index="tau",columns="alpha",values="strategic_wedge")
        hm=px.imshow(pivot.values,x=[f"{x:.2f}" for x in pivot.columns],y=[f"{y:.2f}" for y in pivot.index],aspect="auto",origin="lower",labels={"x":"Strategic complementarity α","y":"Cognitive hierarchy τ","color":"CH value − B1"},title="Higher-order strategic wedge across parameter space")
        hm.update_layout(height=480,margin=dict(l=20,r=20,t=45,b=20)); st.plotly_chart(hm,use_container_width=True)

        st.markdown("#### Regime feasibility solver · fixed-rule audit")
        if isinstance(feasibility,pd.DataFrame) and not feasibility.empty:
            fs1,fs2,fs3=st.columns(3)
            fs1.metric("Rule-feasible regimes",f"{int((feasibility['Feasibility']!='INFEASIBLE').sum())}/{len(feasibility)}")
            fs2.metric("Infeasible",str(int((feasibility['Feasibility']=='INFEASIBLE').sum())))
            fs3.metric("Taxonomy gate","PASS" if freeze_gate.get("taxonomy_pass") else "FAIL")
            st.dataframe(feasibility,use_container_width=True,hide_index=True)
        st.caption("Constructive latent-geometry witnesses test whether each fixed regime is mathematically attainable. This is distinct from empirical/reachability frequency and never tunes thresholds to SPY.")

        st.markdown("#### Regime reachability · taxonomy frequency audit")
        if not reach.empty:
            rr1,rr2,rr3,rr4=st.columns(4)
            rr1.metric("Reachable",f"{int((reach['Reachability']=='REACHABLE').sum())}/{len(reach)}")
            rr2.metric("Very rare / near-unreachable",str(int(reach['Reachability'].isin(['VERY RARE','NEAR-UNREACHABLE']).sum())))
            rr3.metric("Current local reach",f"{float(transition.get('local',0)):.1f}%")
            rr4.metric("Nearest alternative",str(transition.get('nearest','N/A')),"N/A" if _finite(transition.get('distance')) is None else f"distance {float(transition['distance']):.2f}")
            st.dataframe(reach,use_container_width=True,hide_index=True)
        st.caption("Reachability uses synthetic input-space draws only; it never uses future outcomes or tunes thresholds to this run.")

        st.markdown("#### Counterfactual Strategic Shock Lab")
        shock=st.slider("Counterfactual shock size",5.0,25.0,10.0,5.0,key=f"hob_shock_{symbol}")
        cf=counterfactual_table(inputs,cfg,shock)
        st.dataframe(cf.style.format({c:"{:+.2f}" for c in ["ΔB1","ΔB2","ΔB3","ΔSpec gap","ΔMeta gap","ΔFragility","ΔReflexive pressure","ΔPrice-fund gap"]}),use_container_width=True,hide_index=True)
        st.caption("One-at-a-time mechanical sensitivity only. Not causal estimates and not forecasts.")

    # ============================ HISTORY & AUDIT ============================
    with tab_hist:
        st.markdown("#### Historical HOB reconstruction & chronology audit")
        ch1,ch2,ch3,ch4=st.columns(4)
        ch1.metric("Reconstruction status",str(chronology.get("status")))
        ch2.metric("Chronology score",f"{float(chronology.get('score',0)):.0f}/100")
        ch3.metric("PIT fundamental","READY" if chronology.get("pit_fundamental") else "MISSING")
        ch4.metric("Full-HOB archive","READY" if chronology.get("full_hob_history_ready") else "BUILDING",f"{chronology.get('snapshots',0)} snapshots")
        st.dataframe(chronology_df,use_container_width=True,hide_index=True)
        st.caption("The reconstruction is called point-in-time only when every historical measurement actually used at a date was publicly available by that date. Narrative/options-rich HOB remains prospective-only until enough daily snapshots accumulate.")

        if state_space.get("status") == "OK" and isinstance(state_space.get("history"),pd.DataFrame) and not state_space["history"].empty:
            sh=state_space["history"]
            sf=go.Figure()
            for c in ["SS B1","SS B2","SS B3"]:
                sf.add_trace(go.Scatter(x=sh["date"],y=sh[c],mode="lines",name=c))
            sf.add_hline(y=50,line_dash="dot",opacity=.4); sf.update_yaxes(range=[0,100]); sf.update_layout(height=360,margin=dict(l=20,r=20,t=35,b=20),legend=dict(orientation="h"),title=f"Restricted state-space HOB reconstruction · {chronology.get('status')}")
            st.plotly_chart(sf,use_container_width=True)
        core=_historical_core_proxy(state,proxy_alpha if inferred_mode else alpha_scenario)
        if not core.empty:
            x=core["date"] if "date" in core.columns else core.index
            hf=go.Figure()
            for c in ["B1 core proxy","B2 core proxy","B3 core proxy"]:
                hf.add_trace(go.Scatter(x=x,y=core[c],mode="lines",name=c))
            hf.update_yaxes(range=[0,100]); hf.update_layout(height=330,margin=dict(l=20,r=20,t=30,b=20),legend=dict(orientation="h"),title="Core-observed historical approximation · visualization only")
            st.plotly_chart(hf,use_container_width=True)
        st.caption("Core proxy history does not backfill narrative, positioning or options. The state-space reconstruction uses the core causal backbone plus vintage-locked fundamentals and publication-dated survey observations only when available; current-only layers are excluded historically.")

        st.markdown("#### Research readiness")
        readiness=_research_status_table(result,fundamental,direct,state_space,archive_info,stability,chronology,feasibility,freeze_gate)
        st.dataframe(readiness,use_container_width=True,hide_index=True)
        rs1,rs2,rs3,rs4,rs5=st.columns(5)
        rs1.metric("Overlay version",HOB_RESEARCH_VERSION)
        rs2.metric("Regime stability",f"{stability:.1f}%")
        rs3.metric("Archive",f"{archive_info.get('snapshots',0)} snapshots")
        rs4.metric("Measurement spec",str(freeze_gate.get("status")))
        rs5.metric("Predictive status","NOT ESTABLISHED")
        st.info("V3.4 pre-freeze gate: chronology integrity and taxonomy rule feasibility must pass before the measurement specification is frozen. Direct B2/B3 survey evidence remains a documented identification limitation; full narrative/options-rich predictive validation still requires the prospective HOB archive.")
