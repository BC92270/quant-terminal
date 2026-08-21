from __future__ import annotations

"""Behavioral Memory Engine — V2.3.1.

The engine retrieves historically similar *market-state episodes* using only data that
is available for each historical timestamp. It deliberately separates:

1. State similarity: how close a prior episode is to the current configuration.
2. Memory salience: how extreme / attention-worthy the prior episode was.
3. Recency: associative-memory recency weighting.
4. Memory activation: a retrieval score combining the three above.

Narrative/belief and option-memory domains are **never backfilled**. They enter
historical matching only when a point-in-time snapshot has actually been archived by
this package on or before the candidate date. FRED historical series are marked
CURRENT-VINTAGE because a non-ALFRED pull is not vintage locked.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import math
import os
import shutil
import tempfile

import numpy as np
import pandas as pd


MEMORY_VERSION = "V2.3.1"
MEMORY_SIMILARITY_THRESHOLD = 65.0  # hard floor; final threshold is adaptive.
MEMORY_ACTIVATION_THRESHOLD = 55.0  # hard floor; final threshold is adaptive.
MEMORY_MIN_COVERAGE = 0.60
MEMORY_DOMAIN_CUE_THRESHOLD = 62.0
MEMORY_SIMILARITY_QUANTILE = 0.80
MEMORY_ACTIVATION_QUANTILE = 0.65
MEMORY_EXCLUSION_DAYS = 60
MEMORY_SPACING_DAYS = 30


DOMAIN_WEIGHTS: dict[str, float] = {
    "Market state": 1.00,
    "Behavioral state": 1.35,
    "Volatility / tail": 0.95,
    "Breadth / participation": 0.95,
    "Funding / credit": 0.70,
    "Positioning": 0.75,
    "Narrative / beliefs": 1.15,
    "Options behavior": 0.65,
}

# Multipliers are deliberately conservative where history is not true vintage data.
DOMAIN_TEMPORAL_INTEGRITY: dict[str, float] = {
    "Market state": 1.00,
    "Behavioral state": 1.00,
    "Volatility / tail": 0.95,
    "Breadth / participation": 1.00,
    "Funding / credit": 0.65,  # FRED history, but not ALFRED vintage locked.
    "Positioning": 0.95,  # publication-lag aligned before daily use.
    "Narrative / beliefs": 1.00,  # only archived point-in-time snapshots are admitted.
    "Options behavior": 1.00,    # only archived point-in-time snapshots are admitted.
}


@dataclass(frozen=True)
class DomainSpec:
    name: str
    columns: tuple[str, ...]
    min_features: int


DOMAIN_SPECS: tuple[DomainSpec, ...] = (
    DomainSpec("Market state", ("mkt_ret5", "mkt_ret20", "mkt_ret60", "mkt_vol20", "mkt_drawdown", "mkt_volume"), 3),
    DomainSpec("Behavioral state", ("beh_attention", "beh_fear", "beh_herding", "beh_extrapolation", "beh_reflexivity"), 3),
    DomainSpec("Volatility / tail", ("vol_vix", "vol_vvix", "vol_skew", "vol_front_slope", "vol_term_slope"), 2),
    DomainSpec("Breadth / participation", ("br_equal_weight", "br_nasdaq_equal", "br_smallcap", "br_highbeta", "br_sector_positive", "br_sector_ma20", "br_dispersion"), 2),
    DomainSpec("Funding / credit", ("fund_hy", "fund_ig", "fund_nfci_risk", "fund_stlfsi"), 2),
    DomainSpec("Positioning", ("pos_lev_net", "pos_asset_mgr", "pos_dealer", "pos_crowding"), 2),
    DomainSpec("Narrative / beliefs", ("nar_concentration", "nar_disagreement", "nar_confidence", "nar_sentiment", "nar_resolved"), 2),
    DomainSpec("Options behavior", ("opt_tail", "opt_lottery", "opt_concentration", "opt_put_call"), 2),
)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _score_from_z(z: pd.Series | float, center: float = 50.0, amplitude: float = 32.0):
    return np.clip(center + amplitude * np.tanh(np.asarray(z, dtype=float) / 2.0), 0.0, 100.0)


def _causal_robust_z(series: pd.Series, window: int = 252, min_periods: int = 60) -> pd.Series:
    """Robust rolling z-score where the reference distribution excludes timestamp t."""
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    prior = s.shift(1)
    med = prior.rolling(window, min_periods=min_periods).median()
    # Rolling MAD approximation using deviations from the rolling prior median.
    abs_dev = (prior - med).abs()
    mad = abs_dev.rolling(window, min_periods=min_periods).median()
    denom = (1.4826 * mad).replace(0, np.nan)
    z = (s - med) / denom
    sd = prior.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    fallback = (s - med) / sd
    return z.where(z.notna(), fallback).clip(-6, 6)


def _causal_percentile(series: pd.Series, window: int = 156, min_periods: int = 26) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    out = pd.Series(np.nan, index=s.index, dtype=float)
    vals = s.to_numpy(dtype=float)
    for i in range(len(vals)):
        if not np.isfinite(vals[i]):
            continue
        start = max(0, i - window)
        hist = vals[start:i]
        hist = hist[np.isfinite(hist)]
        if len(hist) < min_periods:
            continue
        out.iloc[i] = 100.0 * np.mean(hist <= vals[i])
    return out


def _normalise_feature(series: pd.Series, window: int = 252, min_periods: int = 60) -> pd.Series:
    z = _causal_robust_z(series, window=window, min_periods=min_periods)
    return pd.Series(_score_from_z(z), index=series.index, dtype=float)


def _frame_indexed(df: pd.DataFrame | None, value_col: str = "close") -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "date" not in df.columns or value_col not in df.columns:
        return pd.Series(dtype=float)
    w = df[["date", value_col]].copy()
    w["date"] = pd.to_datetime(w["date"], errors="coerce", utc=True)
    w[value_col] = pd.to_numeric(w[value_col], errors="coerce")
    return w.dropna().drop_duplicates("date").set_index("date")[value_col].sort_index()


def _base_index(target: pd.DataFrame) -> pd.DatetimeIndex:
    if target is None or target.empty or "date" not in target.columns:
        return pd.DatetimeIndex([])
    idx = pd.to_datetime(target["date"], errors="coerce", utc=True).dropna().drop_duplicates().sort_values()
    return pd.DatetimeIndex(idx)


def _build_market_panel(target: pd.DataFrame) -> pd.DataFrame:
    idx = _base_index(target)
    if len(idx) == 0:
        return pd.DataFrame()
    w = target.copy()
    w["date"] = pd.to_datetime(w["date"], errors="coerce", utc=True)
    w = w.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index().reindex(idx)
    close = pd.to_numeric(w.get("close"), errors="coerce")
    volume = pd.to_numeric(w.get("volume", pd.Series(np.nan, index=w.index)), errors="coerce")
    ret = close.pct_change()
    vol20 = ret.rolling(20).std() * math.sqrt(252)
    drawdown = close / close.cummax() - 1
    raw = {
        "mkt_ret5": close.pct_change(5),
        "mkt_ret20": close.pct_change(20),
        "mkt_ret60": close.pct_change(60),
        "mkt_vol20": vol20,
        "mkt_drawdown": drawdown,
        "mkt_volume": np.log1p(volume.replace(0, np.nan)),
    }
    out = pd.DataFrame(index=idx)
    for key, series in raw.items():
        out[key] = _normalise_feature(pd.Series(series, index=idx), 252, 60)
    out["close"] = close.reindex(idx)
    out["ret_20_raw"] = raw["mkt_ret20"].reindex(idx)
    out["vol_20_raw"] = vol20.reindex(idx)
    out["drawdown_raw"] = drawdown.reindex(idx)
    return out


def _build_behavior_panel(history: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.DataFrame:
    if history is None or history.empty or "date" not in history.columns:
        return pd.DataFrame(index=idx)
    h = history.copy()
    h["date"] = pd.to_datetime(h["date"], errors="coerce", utc=True)
    h = h.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    out = pd.DataFrame(index=idx)
    for key in ("attention", "fear", "herding", "extrapolation", "reflexivity"):
        col = f"{key}_latent" if f"{key}_latent" in h.columns else key
        if col in h.columns:
            out[f"beh_{key}"] = pd.to_numeric(h[col], errors="coerce").reindex(idx)
    return out


def _build_vol_panel(vol_layer: dict[str, Any], idx: pd.DatetimeIndex) -> pd.DataFrame:
    histories = vol_layer.get("histories", {}) if isinstance(vol_layer, dict) else {}
    out = pd.DataFrame(index=idx)
    raw: dict[str, pd.Series] = {}
    for name in ("VIX", "VVIX", "SKEW", "VIX9D", "VIX3M"):
        df = histories.get(name, pd.DataFrame()) if isinstance(histories, dict) else pd.DataFrame()
        s = _frame_indexed(df, "value")
        if not s.empty:
            raw[name] = s.reindex(idx).ffill(limit=5)
    if "VIX" in raw:
        out["vol_vix"] = _normalise_feature(raw["VIX"], 252, 60)
    if "VVIX" in raw:
        out["vol_vvix"] = _normalise_feature(raw["VVIX"], 252, 60)
    if "SKEW" in raw:
        out["vol_skew"] = _normalise_feature(raw["SKEW"], 252, 60)
    if "VIX9D" in raw and "VIX" in raw:
        out["vol_front_slope"] = _normalise_feature(raw["VIX9D"] - raw["VIX"], 252, 60)
    if "VIX3M" in raw and "VIX" in raw:
        out["vol_term_slope"] = _normalise_feature(raw["VIX3M"] - raw["VIX"], 252, 60)
    return out


def _build_breadth_panel(breadth_layer: dict[str, Any], idx: pd.DatetimeIndex) -> pd.DataFrame:
    frames = breadth_layer.get("frames", {}) if isinstance(breadth_layer, dict) else {}
    if not isinstance(frames, dict) or not frames:
        return pd.DataFrame(index=idx)
    closes: dict[str, pd.Series] = {}
    for symbol, df in frames.items():
        s = _frame_indexed(df, "close")
        if not s.empty:
            closes[str(symbol)] = s.reindex(idx)
    out = pd.DataFrame(index=idx)

    def ret20(sym: str) -> pd.Series | None:
        s = closes.get(sym)
        return s.pct_change(20) if s is not None else None

    r = {s: ret20(s) for s in closes}
    if r.get("RSP") is not None and r.get("SPY") is not None:
        out["br_equal_weight"] = 50 + 35 * np.tanh((r["RSP"] - r["SPY"]) / 0.04)
    if r.get("QQEW") is not None and r.get("QQQ") is not None:
        out["br_nasdaq_equal"] = 50 + 35 * np.tanh((r["QQEW"] - r["QQQ"]) / 0.05)
    if r.get("IWM") is not None and r.get("SPY") is not None:
        out["br_smallcap"] = 50 + 35 * np.tanh((r["IWM"] - r["SPY"]) / 0.06)
    if r.get("SPHB") is not None and r.get("SPLV") is not None:
        out["br_highbeta"] = 50 + 35 * np.tanh((r["SPHB"] - r["SPLV"]) / 0.08)

    sector_cols = [s for s in ("XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLRE", "XLU", "XLV", "XLY") if r.get(s) is not None]
    if sector_cols:
        sector_ret = pd.concat([r[s].rename(s) for s in sector_cols], axis=1)
        out["br_sector_positive"] = 100 * (sector_ret > 0).mean(axis=1)
        out["br_dispersion"] = _normalise_feature(sector_ret.std(axis=1), 252, 60)
        ma_flags = []
        for s in sector_cols:
            c = closes.get(s)
            if c is None:
                continue
            ma_flags.append((c > c.rolling(20).mean()).rename(s))
        if ma_flags:
            out["br_sector_ma20"] = 100 * pd.concat(ma_flags, axis=1).mean(axis=1)
    return out.clip(0, 100)


def _build_funding_panel(funding_layer: dict[str, Any], idx: pd.DatetimeIndex) -> pd.DataFrame:
    series = funding_layer.get("series", {}) if isinstance(funding_layer, dict) else {}
    out = pd.DataFrame(index=idx)
    mapping = {
        "hy_oas": "fund_hy",
        "ig_oas": "fund_ig",
        "nfci_risk": "fund_nfci_risk",
        "stlfsi": "fund_stlfsi",
    }
    for src, dst in mapping.items():
        df = series.get(src, pd.DataFrame()) if isinstance(series, dict) else pd.DataFrame()
        s = _frame_indexed(df, "value")
        if s.empty:
            continue
        # Current-vintage FRED history. merge_asof semantics: carry only the most
        # recent dated observation backward-to-forward, never a future observation.
        aligned = s.reindex(s.index.union(idx)).sort_index().ffill().reindex(idx)
        out[dst] = _normalise_feature(aligned, 156 if "nfci" in src or src == "stlfsi" else 252, 30)
    return out


def _build_positioning_panel(positioning_layer: dict[str, Any], idx: pd.DatetimeIndex) -> pd.DataFrame:
    hist = positioning_layer.get("history", pd.DataFrame()) if isinstance(positioning_layer, dict) else pd.DataFrame()
    if hist is None or not isinstance(hist, pd.DataFrame) or hist.empty or "date" not in hist.columns:
        return pd.DataFrame(index=idx)
    h = hist.copy()
    h["date"] = pd.to_datetime(h["date"], errors="coerce", utc=True)
    if "availability_date" in h.columns:
        h["availability_date"] = pd.to_datetime(h["availability_date"], errors="coerce", utc=True)
    else:
        # Backward compatibility for an older behavioral-data object. V2.3.1
        # deliberately refuses report-date alignment; if explicit availability
        # metadata is absent, shift by four business-day sessions conservatively.
        h["availability_date"] = h["date"] + pd.offsets.BDay(4)
    h = h.dropna(subset=["date", "availability_date"]).drop_duplicates("availability_date").set_index("availability_date").sort_index()
    weekly = pd.DataFrame(index=h.index)
    source_map = {
        "lev_money_net_pct_oi": "pos_lev_net",
        "asset_mgr_net_pct_oi": "pos_asset_mgr",
        "dealer_net_pct_oi": "pos_dealer",
    }
    for src, dst in source_map.items():
        if src in h.columns:
            weekly[dst] = _normalise_feature(pd.to_numeric(h[src], errors="coerce"), 156, 26)
    if "lev_money_net_pct_oi" in h.columns:
        pct = _causal_percentile(pd.to_numeric(h["lev_money_net_pct_oi"], errors="coerce"), 156, 26)
        weekly["pos_crowding"] = 2.0 * (pct - 50.0).abs()
    if weekly.empty:
        return pd.DataFrame(index=idx)
    # CFTC is weekly. Carry forward only from the conservative publication
    # availability date, never from the Tuesday report date. This removes the
    # subtle report-date look-ahead that would otherwise contaminate retrieval.
    daily = weekly.reindex(weekly.index.union(idx)).sort_index().ffill().reindex(idx)
    return daily.clip(0, 100)


def _memory_dir() -> Path:
    """Package-local prospective memory store with legacy migration.

    The behavioral-memory equations and point-in-time rules are unchanged. This only
    consolidates runtime storage into ``market_psychology/memory`` so the complete Lab
    has one visible parent folder.
    """
    configured = os.getenv("MARKET_PSYCHOLOGY_MEMORY_DIR", "").strip()
    if configured:
        root = Path(configured).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

    root = Path(__file__).resolve().parent / "memory"
    root.mkdir(parents=True, exist_ok=True)
    legacy = Path.cwd() / ".market_psychology_memory"
    if legacy.exists() and legacy.is_dir():
        try:
            for src in legacy.iterdir():
                if not src.is_file():
                    continue
                dst = root / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
        except Exception:
            pass
    return root


def _archive_path(symbol: str) -> Path:
    safe = "".join(ch for ch in str(symbol).upper() if ch.isalnum() or ch in {"-", "_", "."}) or "UNKNOWN"
    return _memory_dir() / f"{safe}_behavioral_snapshots.jsonl"


def _snapshot_payload(symbol: str, scores: dict[str, Any], news: dict[str, Any], behavioral_data: dict[str, Any]) -> dict[str, Any]:
    bdata = behavioral_data if isinstance(behavioral_data, dict) else {}
    vt = bdata.get("volatility_tail", {}).get("metrics", {}) if isinstance(bdata.get("volatility_tail", {}), dict) else {}
    br = bdata.get("breadth", {}).get("metrics", {}) if isinstance(bdata.get("breadth", {}), dict) else {}
    fu = bdata.get("funding_credit", {}).get("metrics", {}) if isinstance(bdata.get("funding_credit", {}), dict) else {}
    po = bdata.get("positioning", {}).get("metrics", {}) if isinstance(bdata.get("positioning", {}), dict) else {}
    op = bdata.get("options_behavior", {}).get("metrics", {}) if isinstance(bdata.get("options_behavior", {}), dict) else {}
    now = pd.Timestamp.now(tz="UTC")
    payload = {
        "timestamp": now.isoformat(),
        "date": now.normalize().isoformat(),
        "symbol": str(symbol).upper(),
        "version": MEMORY_VERSION,
        "attention": _safe_float(scores.get("attention")),
        "fear": _safe_float(scores.get("fear")),
        "herding": _safe_float(scores.get("herding")),
        "extrapolation": _safe_float(scores.get("extrapolation")),
        "reflexivity": _safe_float(scores.get("reflexivity")),
        "narrative_score": _safe_float(scores.get("narrative")),
        "narrative_concentration": _safe_float(news.get("theme_concentration")),
        "belief_disagreement": _safe_float(news.get("belief_disagreement")),
        "belief_confidence": _safe_float(news.get("belief_confidence_mean")),
        "narrative_sentiment": _safe_float(news.get("sentiment_mean")),
        "resolved_coverage": _safe_float(news.get("resolved_coverage")),
        "dominant_narrative": str(news.get("dominant_narrative", "OTHER / UNRESOLVED")),
        "tail_stress": _safe_float(vt.get("tail_stress_score")),
        "breadth_score": _safe_float(br.get("breadth_score")),
        "funding_stress": _safe_float(fu.get("funding_stress_score")),
        "positioning_crowding": _safe_float(po.get("positioning_crowding_score")),
        "option_tail": _safe_float(op.get("option_tail_demand_score")),
        "option_lottery": _safe_float(op.get("option_lottery_score")),
        "option_concentration": _safe_float(op.get("convexity_concentration_score")),
        "put_call_volume": _safe_float(op.get("put_call_volume")),
        "observed_data_evidence": _safe_float(bdata.get("evidence_score")),
    }
    return payload


def archive_current_snapshot(symbol: str, scores: dict[str, Any], news: dict[str, Any], behavioral_data: dict[str, Any]) -> dict[str, Any]:
    """Persist a derived point-in-time snapshot. Never stores article text or credentials.

    The operation is best-effort and non-blocking for the research UI. At most one
    snapshot per UTC date and symbol is retained; reruns replace that day's derived row.
    """
    path = _archive_path(symbol)
    payload = _snapshot_payload(symbol, scores, news, behavioral_data)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list[dict[str, Any]] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        existing.append(row)
                except Exception:
                    continue
        day = str(payload["date"])
        existing = [r for r in existing if str(r.get("date")) != day]
        existing.append(payload)
        existing = sorted(existing, key=lambda r: str(r.get("timestamp", r.get("date", ""))))
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as tmp:
            tmp_path = Path(tmp.name)
            for row in existing:
                tmp.write(json.dumps(row, sort_keys=True, ensure_ascii=True) + "\n")
        tmp_path.replace(path)
        return {"status": "OK", "path": str(path), "snapshots": len(existing), "stored": True}
    except Exception as exc:
        return {"status": "UNAVAILABLE", "path": str(path), "snapshots": 0, "stored": False, "detail": type(exc).__name__}


def load_snapshot_archive(symbol: str) -> pd.DataFrame:
    path = _archive_path(symbol)
    if not path.exists():
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:
                continue
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.dropna(subset=["date"]).sort_values("date").drop_duplicates("date", keep="last")
    return df.reset_index(drop=True)


def _build_archive_panels(archive: pd.DataFrame, idx: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    nar = pd.DataFrame(index=idx)
    opt = pd.DataFrame(index=idx)
    if archive is None or archive.empty or "date" not in archive.columns:
        return nar, opt
    a = archive.copy()
    a["date"] = pd.to_datetime(a["date"], errors="coerce", utc=True)
    a = a.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    # No ffill across long horizons: a snapshot is valid only for a narrow ±3-business-day episode window.
    mapping_n = {
        "narrative_concentration": "nar_concentration",
        "belief_disagreement": "nar_disagreement",
        "belief_confidence": "nar_confidence",
        "narrative_sentiment": "nar_sentiment",
        "resolved_coverage": "nar_resolved",
    }
    for src, dst in mapping_n.items():
        if src not in a.columns:
            continue
        s = pd.to_numeric(a[src], errors="coerce")
        if src in {"narrative_concentration", "resolved_coverage"}:
            s = 100.0 * s.where(s.abs() <= 1.5, s / 100.0)
        elif src == "narrative_sentiment":
            s = 50.0 + 50.0 * s.clip(-1, 1)
        nar[dst] = s.reindex(idx, method=None)
    mapping_o = {
        "option_tail": "opt_tail",
        "option_lottery": "opt_lottery",
        "option_concentration": "opt_concentration",
        "put_call_volume": "opt_put_call",
    }
    for src, dst in mapping_o.items():
        if src not in a.columns:
            continue
        s = pd.to_numeric(a[src], errors="coerce")
        if src == "put_call_volume":
            s = 50 + 35 * np.tanh((s - 0.9) / 0.45)
        opt[dst] = s.reindex(idx, method=None)
    return nar.clip(0, 100), opt.clip(0, 100)


def _domain_similarity(current: pd.Series, candidate: pd.Series, columns: tuple[str, ...], min_features: int) -> tuple[float | None, int]:
    vals = []
    for col in columns:
        a = _safe_float(current.get(col))
        b = _safe_float(candidate.get(col))
        if a is None or b is None:
            continue
        vals.append(a - b)
    if len(vals) < min_features:
        return None, len(vals)
    rmse = float(np.sqrt(np.mean(np.square(vals))))
    # 20 score-points RMSE ~= 61 similarity; 10 ~= 78.
    return float(np.clip(100.0 * math.exp(-rmse / 40.0), 0, 100)), len(vals)


def _candidate_salience(row: pd.Series) -> float:
    cols = [
        "beh_attention", "beh_fear", "beh_extrapolation", "beh_herding", "beh_reflexivity",
        "mkt_ret20", "mkt_vol20", "mkt_drawdown", "vol_vix", "vol_vvix",
    ]
    vals = [_safe_float(row.get(c)) for c in cols]
    vals = [v for v in vals if v is not None]
    if not vals:
        return 0.0
    return float(np.clip(2.2 * np.mean([abs(v - 50.0) for v in vals]), 0, 100))


def _episode_tags(row: pd.Series, current_narrative: str | None = None) -> list[str]:
    tags: list[str] = []
    def val(k: str) -> float | None:
        return _safe_float(row.get(k))
    if (val("beh_extrapolation") or 0) >= 65: tags.append("HIGH_EXTRAPOLATION")
    if (val("beh_fear") or 50) <= 40: tags.append("LOW_FEAR")
    if (val("beh_fear") or 0) >= 65: tags.append("HIGH_FEAR")
    if (val("beh_herding") or 0) >= 65: tags.append("CROWDING")
    if (val("beh_reflexivity") or 0) >= 65: tags.append("REFLEXIVE_HEAT")
    sector_vals = [val(k) for k in ("br_sector_positive", "br_sector_ma20")]
    sector_vals = [v for v in sector_vals if v is not None]
    leadership_vals = [val(k) for k in ("br_equal_weight", "br_nasdaq_equal", "br_smallcap", "br_highbeta")]
    leadership_vals = [v for v in leadership_vals if v is not None]
    sector_breadth = float(np.mean(sector_vals)) if sector_vals else None
    leadership_breadth = float(np.mean(leadership_vals)) if leadership_vals else None
    if sector_breadth is not None or leadership_breadth is not None:
        if sector_breadth is not None and leadership_breadth is not None:
            if sector_breadth <= 40 and leadership_breadth <= 45:
                tags.append("NARROW_BREADTH")
            elif sector_breadth >= 58 and leadership_breadth <= 45:
                tags.append("MEGACAP_LED_BREADTH")
            elif sector_breadth >= 60 and leadership_breadth >= 52:
                tags.append("BROAD_PARTICIPATION")
            else:
                tags.append("MIXED_BREADTH")
        else:
            b = sector_breadth if sector_breadth is not None else leadership_breadth
            if b is not None and b <= 40:
                tags.append("NARROW_BREADTH")
            elif b is not None and b >= 62:
                tags.append("BROAD_PARTICIPATION")
            else:
                tags.append("MIXED_BREADTH")
    tail_vals = [val(k) for k in ("vol_vix", "vol_vvix", "vol_skew")]
    tail_vals = [v for v in tail_vals if v is not None]
    if tail_vals and float(np.mean(tail_vals)) >= 65: tags.append("TAIL_STRESS")
    fund_vals = [val(k) for k in ("fund_hy", "fund_ig", "fund_nfci_risk", "fund_stlfsi")]
    fund_vals = [v for v in fund_vals if v is not None]
    if fund_vals:
        f = float(np.mean(fund_vals))
        if f >= 65: tags.append("FUNDING_STRESS")
        elif f <= 42: tags.append("EASY_FINANCIAL_CONDITIONS")
    if (val("pos_crowding") or 0) >= 70: tags.append("CROWDED_POSITIONING")
    if (val("nar_concentration") or 0) >= 65: tags.append("NARRATIVE_CONCENTRATION")
    if (val("nar_disagreement") or 0) >= 65: tags.append("BELIEF_FRAGMENTATION")
    if current_narrative and str(current_narrative).strip() and str(current_narrative) != "OTHER / UNRESOLVED":
        tags.append(f"NARRATIVE:{str(current_narrative)[:28]}")
    return tags[:8]


def _forward_outcomes(target: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    if target is None or target.empty:
        return pd.DataFrame(index=dates.index)
    w = target.copy()
    w["date"] = pd.to_datetime(w["date"], errors="coerce", utc=True)
    w = w.dropna(subset=["date"]).drop_duplicates("date").set_index("date").sort_index()
    close = pd.to_numeric(w["close"], errors="coerce")
    ret = close.pct_change()
    fwd20 = close.shift(-20) / close - 1
    fwd60 = close.shift(-60) / close - 1
    fwdvol20 = ret.shift(-1).rolling(20).std().shift(-19) * math.sqrt(252)
    worst60 = pd.Series(np.nan, index=close.index, dtype=float)
    vals = close.to_numpy(dtype=float)
    for i in range(len(vals) - 60):
        if not np.isfinite(vals[i]) or vals[i] == 0:
            continue
        path = vals[i + 1:i + 61]
        worst60.iloc[i] = np.nanmin(path / vals[i] - 1.0) if len(path) else np.nan
    out = pd.DataFrame({"date": dates})
    out["fwd_20d"] = out["date"].map(fwd20)
    out["fwd_60d"] = out["date"].map(fwd60)
    out["fwd_vol20"] = out["date"].map(fwdvol20)
    out["fwd_worst60"] = out["date"].map(worst60)
    return out


def _select_spaced(frame: pd.DataFrame, top_n: int, spacing_days: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    chosen: list[int] = []
    chosen_dates: list[pd.Timestamp] = []
    for idx, row in frame.sort_values(["Similarity", "Activation"], ascending=False).iterrows():
        dt = pd.to_datetime(row["date"], errors="coerce", utc=True)
        if pd.isna(dt):
            continue
        if all(abs((dt - d).days) >= spacing_days for d in chosen_dates):
            chosen.append(idx)
            chosen_dates.append(dt)
        if len(chosen) >= top_n:
            break
    return frame.loc[chosen].reset_index(drop=True)


def _domain_current_and_history(target: pd.DataFrame, latent_history: pd.DataFrame, behavioral_data: dict[str, Any], archive: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    idx = _base_index(target)
    panels: dict[str, pd.DataFrame] = {
        "Market state": _build_market_panel(target),
        "Behavioral state": _build_behavior_panel(latent_history, idx),
        "Volatility / tail": _build_vol_panel(behavioral_data.get("volatility_tail", {}), idx),
        "Breadth / participation": _build_breadth_panel(behavioral_data.get("breadth", {}), idx),
        "Funding / credit": _build_funding_panel(behavioral_data.get("funding_credit", {}), idx),
        "Positioning": _build_positioning_panel(behavioral_data.get("positioning", {}), idx),
    }
    nar, opt = _build_archive_panels(archive, idx)
    panels["Narrative / beliefs"] = nar
    panels["Options behavior"] = opt
    combined = pd.DataFrame(index=idx)
    for panel in panels.values():
        if panel is not None and not panel.empty:
            combined = combined.join(panel, how="left")
    return combined, panels


def _inject_current_snapshot(current: pd.Series, scores: dict[str, Any], news: dict[str, Any], behavioral_data: dict[str, Any]) -> pd.Series:
    cur = current.copy()
    for key in ("attention", "fear", "herding", "extrapolation", "reflexivity"):
        value = _safe_float(scores.get(key))
        if value is not None:
            cur[f"beh_{key}"] = value
    concentration = _safe_float(news.get("theme_concentration"))
    if concentration is not None:
        cur["nar_concentration"] = 100.0 * concentration if concentration <= 1.5 else concentration
    for src, dst in (("belief_disagreement", "nar_disagreement"), ("belief_confidence_mean", "nar_confidence"), ("resolved_coverage", "nar_resolved")):
        value = _safe_float(news.get(src))
        if value is not None:
            cur[dst] = 100.0 * value if src == "resolved_coverage" and value <= 1.5 else value
    sentiment = _safe_float(news.get("sentiment_mean"))
    if sentiment is not None:
        cur["nar_sentiment"] = 50 + 50 * np.clip(sentiment, -1, 1)
    op = behavioral_data.get("options_behavior", {}).get("metrics", {}) if isinstance(behavioral_data.get("options_behavior", {}), dict) else {}
    mapping = {
        "option_tail_demand_score": "opt_tail",
        "option_lottery_score": "opt_lottery",
        "convexity_concentration_score": "opt_concentration",
    }
    for src, dst in mapping.items():
        value = _safe_float(op.get(src))
        if value is not None:
            cur[dst] = value
    pc = _safe_float(op.get("put_call_volume"))
    if pc is not None:
        cur["opt_put_call"] = float(np.clip(50 + 35 * np.tanh((pc - 0.9) / 0.45), 0, 100))
    return cur


def build_behavioral_memory(
    symbol: str,
    target: pd.DataFrame,
    latent_history: pd.DataFrame,
    behavioral_data: dict[str, Any],
    news: dict[str, Any],
    scores: dict[str, Any],
    *,
    top_n: int = 8,
    similarity_threshold: float = MEMORY_SIMILARITY_THRESHOLD,
    activation_threshold: float = MEMORY_ACTIVATION_THRESHOLD,
    min_coverage: float = MEMORY_MIN_COVERAGE,
    exclusion_days: int = MEMORY_EXCLUSION_DAYS,
    spacing_days: int = MEMORY_SPACING_DAYS,
) -> dict[str, Any]:
    """Build a multi-domain associative-memory retrieval diagnostic."""
    if target is None or target.empty or len(target) < 150:
        return {"available": False, "reason": "Insufficient price history for behavioral-memory retrieval."}

    archive_status = archive_current_snapshot(symbol, scores, news, behavioral_data)
    archive = load_snapshot_archive(symbol)
    combined, panels = _domain_current_and_history(target, latent_history, behavioral_data, archive)
    if combined.empty:
        return {"available": False, "reason": "Historical memory feature panel is unavailable.", "archive": archive_status}

    # Current row uses full current observations, including snapshot-only domains.
    current = combined.iloc[-1].copy()
    current = _inject_current_snapshot(current, scores, news, behavioral_data)
    current_date = combined.index[-1]

    domain_current_available: dict[str, bool] = {}
    domain_rows: list[dict[str, Any]] = []
    for spec in DOMAIN_SPECS:
        available_features = sum(_safe_float(current.get(c)) is not None for c in spec.columns)
        available = available_features >= spec.min_features
        domain_current_available[spec.name] = available
        panel = panels.get(spec.name, pd.DataFrame())
        hist_coverage = 0.0
        if panel is not None and not panel.empty:
            valid = panel[list(c for c in spec.columns if c in panel.columns)].notna().sum(axis=1) if any(c in panel.columns for c in spec.columns) else pd.Series(0, index=combined.index)
            hist_coverage = float((valid >= spec.min_features).mean()) if len(valid) else 0.0
        domain_rows.append({
            "Domain": spec.name,
            "Current": "AVAILABLE" if available else "MISSING",
            "Current features": f"{available_features}/{len(spec.columns)}",
            "Historical coverage": round(100 * hist_coverage, 1),
            "Weight": DOMAIN_WEIGHTS[spec.name],
            "Temporal integrity": round(100 * DOMAIN_TEMPORAL_INTEGRITY[spec.name], 0),
            "Integrity note": (
                "POINT-IN-TIME / MARKET OBSERVED" if spec.name in {"Market state", "Behavioral state", "Breadth / participation"}
                else "CURRENT-VINTAGE; not ALFRED locked" if spec.name == "Funding / credit"
                else "ARCHIVE-ONLY; never backfilled" if spec.name in {"Narrative / beliefs", "Options behavior"}
                else "PUBLICATION-LAG ALIGNED / PUBLIC" if spec.name == "Positioning"
                else "HISTORICAL OBSERVED / PUBLIC" 
            ),
        })
    domain_coverage = pd.DataFrame(domain_rows)

    # The denominator includes domains available *today*. Missing historical archive
    # therefore reduces analogue coverage instead of silently disappearing.
    total_current_weight = sum(
        DOMAIN_WEIGHTS[s.name] * DOMAIN_TEMPORAL_INTEGRITY[s.name]
        for s in DOMAIN_SPECS if domain_current_available.get(s.name)
    ) or 1.0

    # Exclude current / overlapping recent observations from candidate search.
    cutoff = current_date - pd.Timedelta(days=max(int(exclusion_days), 1))
    candidates = combined.loc[combined.index < cutoff].copy()
    if candidates.empty:
        return {"available": False, "reason": "No non-overlapping historical episodes in the selected research horizon.", "archive": archive_status}

    rows: list[dict[str, Any]] = []
    for dt, row in candidates.iterrows():
        domain_sim: dict[str, float] = {}
        available_weight = 0.0
        weighted_similarity = 0.0
        feature_count = 0
        for spec in DOMAIN_SPECS:
            if not domain_current_available.get(spec.name):
                continue
            sim, n_features = _domain_similarity(current, row, spec.columns, spec.min_features)
            if sim is None:
                continue
            eff_weight = DOMAIN_WEIGHTS[spec.name] * DOMAIN_TEMPORAL_INTEGRITY[spec.name]
            domain_sim[spec.name] = sim
            available_weight += eff_weight
            weighted_similarity += eff_weight * sim
            feature_count += n_features
        if available_weight <= 0:
            continue
        similarity = weighted_similarity / available_weight
        coverage = float(np.clip(available_weight / total_current_weight, 0, 1))
        salience = _candidate_salience(row)
        age_years = max((current_date - dt).days / 365.25, 0.0)
        recency = float(100.0 * math.exp(-age_years / 5.0))
        activation = float(np.clip((0.72 * similarity + 0.18 * salience + 0.10 * recency) * (0.75 + 0.25 * coverage), 0, 100))
        ordered = sorted(domain_sim.items(), key=lambda kv: kv[1], reverse=True)
        reasons = [name for name, sim in ordered[:3] if sim >= MEMORY_DOMAIN_CUE_THRESHOLD]
        mismatches = [name for name, sim in sorted(domain_sim.items(), key=lambda kv: kv[1])[:3] if sim < 55]
        tags = _episode_tags(row)
        rows.append({
            "date": dt,
            "Similarity": round(similarity, 1),
            "Activation": round(activation, 1),
            "Coverage": round(100 * coverage, 1),
            "Salience": round(salience, 1),
            "Recency": round(recency, 1),
            "Features": int(feature_count),
            "Tags": " · ".join(tags) if tags else "UNCLASSIFIED",
            "Why retrieved": " · ".join(reasons) if reasons else "No dominant matching domain",
            "Main mismatch": " · ".join(mismatches) if mismatches else "None material",
            **{f"sim::{k}": round(v, 1) for k, v in domain_sim.items()},
        })
    raw_candidates = pd.DataFrame(rows)
    if raw_candidates.empty:
        return {"available": False, "reason": "No candidate episode has enough overlapping domains.", "archive": archive_status, "domain_coverage": domain_coverage}

    raw_candidates = raw_candidates.sort_values(["Similarity", "Activation"], ascending=False).reset_index(drop=True)

    # V2.3.1 retrieval calibration: a fixed floor is retained, but the actual
    # structural threshold adapts to the instrument/horizon distribution. This
    # prevents a universal 62/100 cutoff from declaring almost every nearby state
    # "reliable" on one asset while rejecting all candidates on another.
    calibration_pool = raw_candidates[pd.to_numeric(raw_candidates["Coverage"], errors="coerce") >= 45.0].copy()
    sim_q = float(pd.to_numeric(calibration_pool["Similarity"], errors="coerce").quantile(MEMORY_SIMILARITY_QUANTILE)) if len(calibration_pool) >= 20 else float(similarity_threshold)
    adaptive_similarity_threshold = float(min(max(float(similarity_threshold), sim_q), max(85.0, float(similarity_threshold))))
    structural_pool = calibration_pool[pd.to_numeric(calibration_pool["Similarity"], errors="coerce") >= adaptive_similarity_threshold]
    act_source = structural_pool if len(structural_pool) >= 5 else calibration_pool
    act_q = float(pd.to_numeric(act_source["Activation"], errors="coerce").quantile(MEMORY_ACTIVATION_QUANTILE)) if len(act_source) >= 5 else float(activation_threshold)
    adaptive_activation_threshold = float(min(max(float(activation_threshold), act_q), max(78.0, float(activation_threshold))))

    def classify(row: pd.Series) -> str:
        sim = _safe_float(row.get("Similarity"), 0.0) or 0.0
        act = _safe_float(row.get("Activation"), 0.0) or 0.0
        cov = (_safe_float(row.get("Coverage"), 0.0) or 0.0) / 100.0
        if sim >= adaptive_similarity_threshold and cov >= min_coverage:
            return "MEMORY CANDIDATE" if act >= adaptive_activation_threshold else "STRUCTURAL ANALOGUE"
        if sim >= 55.0 and cov >= 0.50:
            return "PARTIAL"
        return "WEAK"

    raw_candidates["Retrieval class"] = raw_candidates.apply(classify, axis=1)
    # Backward-compatible alias used by older integration surfaces.
    raw_candidates["Reliability"] = raw_candidates["Retrieval class"]

    selected = _select_spaced(raw_candidates, max(top_n * 3, 20), spacing_days)
    outcomes = _forward_outcomes(target, selected["date"])
    for col in ("fwd_20d", "fwd_60d", "fwd_vol20", "fwd_worst60"):
        selected[col] = outcomes[col].to_numpy() if col in outcomes.columns else np.nan
    class_rank = {"MEMORY CANDIDATE": 4, "STRUCTURAL ANALOGUE": 3, "PARTIAL": 2, "WEAK": 1}
    selected["_class_rank"] = selected["Retrieval class"].map(class_rank).fillna(0)
    selected = selected.sort_values(["_class_rank", "Similarity", "Activation"], ascending=False).drop(columns=["_class_rank"]).reset_index(drop=True)
    # Keep strongest episodes but preserve spaced selection.
    selected = selected.head(max(top_n, 1)).copy()
    structural = selected[selected["Retrieval class"].isin(["MEMORY CANDIDATE", "STRUCTURAL ANALOGUE"])].copy()
    memory_candidates = selected[selected["Retrieval class"].eq("MEMORY CANDIDATE")].copy()
    nearest = selected.copy()

    # Backward alias: "reliable_analogues" now means observed-domain structural
    # analogues, not a claim of full narrative/options memory coverage.
    reliable = structural.copy()
    ensemble_source = memory_candidates if not memory_candidates.empty else structural if not structural.empty else selected[selected["Retrieval class"].eq("PARTIAL")]
    ensemble = {
        "count": int(len(ensemble_source)),
        "reliable_count": int(len(structural)),
        "structural_count": int(len(structural)),
        "memory_candidate_count": int(len(memory_candidates)),
        "median_20d": _safe_float(ensemble_source["fwd_20d"].median()) if not ensemble_source.empty else None,
        "median_60d": _safe_float(ensemble_source["fwd_60d"].median()) if not ensemble_source.empty else None,
        "positive_20d_share": _safe_float((ensemble_source["fwd_20d"] > 0).mean()) if not ensemble_source.empty else None,
        "positive_60d_share": _safe_float((ensemble_source["fwd_60d"] > 0).mean()) if not ensemble_source.empty else None,
        "median_worst60": _safe_float(ensemble_source["fwd_worst60"].median()) if not ensemble_source.empty else None,
        "median_future_vol20": _safe_float(ensemble_source["fwd_vol20"].median()) if not ensemble_source.empty else None,
    }

    # Current cue tags include current narrative only; historical rows never receive
    # a narrative tag unless an archived snapshot existed at that historical date.
    current_tags = _episode_tags(current, str(news.get("dominant_narrative", "")))
    current_profile_rows = []
    for spec in DOMAIN_SPECS:
        vals = [_safe_float(current.get(c)) for c in spec.columns]
        vals = [v for v in vals if v is not None]
        current_profile_rows.append({
            "Domain": spec.name,
            "Current state": round(float(np.mean(vals)), 1) if vals else np.nan,
            "Available features": len(vals),
            "Required": spec.min_features,
        })
    current_profile = pd.DataFrame(current_profile_rows)

    archive_df = archive.copy() if isinstance(archive, pd.DataFrame) else pd.DataFrame()
    archive_diag = {
        **archive_status,
        "snapshots": int(len(archive_df)),
        "first_date": archive_df["date"].min() if not archive_df.empty and "date" in archive_df.columns else None,
        "last_date": archive_df["date"].max() if not archive_df.empty and "date" in archive_df.columns else None,
        "narrative_history_ready": bool(len(archive_df) >= 10),
        "options_history_ready": bool(len(archive_df) >= 10),
        "note": "Derived snapshots only; no raw news text or credentials are stored. Historical narrative/options matching starts only as this archive grows.",
    }

    best_similarity = _safe_float(selected["Similarity"].max()) if not selected.empty else None
    memory_activation = _safe_float((memory_candidates["Activation"].max() if not memory_candidates.empty else structural["Activation"].max() if not structural.empty else selected["Activation"].max()), 0.0) if not selected.empty else 0.0
    coverage_score = float(np.clip(np.mean([r["Historical coverage"] for r in domain_rows if r["Current"] == "AVAILABLE"]), 0, 100)) if any(r["Current"] == "AVAILABLE" for r in domain_rows) else 0.0
    structural_exists = not structural.empty
    historically_usable_domains = int(sum(1 for r in domain_rows if r["Current"] == "AVAILABLE" and float(r["Historical coverage"]) >= 25.0))
    current_available_domains = int(sum(1 for r in domain_rows if r["Current"] == "AVAILABLE"))
    history_years = float(max((current_date - combined.index.min()).days / 365.25, 0.0)) if len(combined.index) else 0.0

    return {
        "available": True,
        "version": MEMORY_VERSION,
        "similarity_threshold": float(adaptive_similarity_threshold),
        "similarity_floor": float(similarity_threshold),
        "activation_threshold": float(adaptive_activation_threshold),
        "activation_floor": float(activation_threshold),
        "domain_cue_threshold": float(MEMORY_DOMAIN_CUE_THRESHOLD),
        "min_coverage": float(min_coverage),
        "exclusion_days": int(exclusion_days),
        "spacing_days": int(spacing_days),
        "no_reliable_analogue": not structural_exists,
        "no_structural_analogue": not structural_exists,
        "best_similarity": best_similarity,
        "memory_activation_score": float(memory_activation),
        "historical_domain_coverage": coverage_score,
        "historically_usable_domains": historically_usable_domains,
        "current_available_domains": current_available_domains,
        "domain_total": len(DOMAIN_SPECS),
        "history_years": history_years,
        "current_tags": current_tags,
        "analogues": selected,
        "reliable_analogues": reliable,
        "structural_analogues": structural,
        "memory_candidates": memory_candidates,
        "nearest_analogues": nearest,
        "ensemble": ensemble,
        "domain_coverage": domain_coverage,
        "current_profile": current_profile,
        "archive": archive_diag,
        "domain_specs": {s.name: list(s.columns) for s in DOMAIN_SPECS},
        "method_note": (
            "Overall similarity is a coverage-weighted multi-domain state distance. V2.3.1 separates structural analogues from memory candidates: "
            "the structural cutoff is instrument/horizon-adaptive, while memory candidates must also clear an activation threshold. Memory activation combines 72% state similarity, "
            "18% episode salience and 10% recency, then applies a coverage penalty. CFTC positioning is aligned to conservative publication availability; narrative/options are archive-only; funding history is current-vintage and down-weighted."
        ),
    }


__all__ = [
    "MEMORY_VERSION",
    "archive_current_snapshot",
    "load_snapshot_archive",
    "build_behavioral_memory",
]
