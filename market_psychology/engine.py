from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    MECHANISM_SPECS,
    NARRATIVE_THEMES,
    NEGATIVE_WORDS,
    POSITIVE_WORDS,
    UNCERTAINTY_WORDS,
    TRADING_DAYS,
)

from .narrative_nlp import analyze_news_corpus
from .behavioral_memory import build_behavioral_memory

from .latent_state import (
    LATENT_KEYS,
    acute_alarm_level,
    build_latent_state_bundle,
    shock_semantics,
    structural_state_label,
)


@dataclass
class MechanismResult:
    key: str
    label: str
    layer: str
    score: float
    confidence: float
    status: str
    description: str
    evidence: str
    identification: str


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def clip_score(value: Any, default: float = 50.0) -> float:
    x = safe_float(value, default)
    if x is None:
        x = default
    return float(np.clip(x, 0.0, 100.0))


def z_to_score(z: Any, center: float = 50.0, amplitude: float = 32.0) -> float:
    x = safe_float(z, 0.0) or 0.0
    return clip_score(center + amplitude * np.tanh(x / 2.0))


def robust_z_last(series: pd.Series, window: int = 126, min_periods: int = 30) -> float | None:
    s = pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < min_periods:
        return None
    hist = s.tail(window)
    med = float(hist.median())
    mad = float((hist - med).abs().median())
    if mad > 1e-12:
        return float((hist.iloc[-1] - med) / (1.4826 * mad))
    sd = float(hist.std())
    return float((hist.iloc[-1] - med) / sd) if sd > 1e-12 else 0.0


def rolling_robust_z(series: pd.Series, window: int = 126, min_periods: int = 30) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    med = s.rolling(window, min_periods=min_periods).median()
    mad = (s - med).abs().rolling(window, min_periods=min_periods).median()
    denom = (1.4826 * mad).replace(0, np.nan)
    z = (s - med) / denom
    std = s.rolling(window, min_periods=min_periods).std().replace(0, np.nan)
    return z.fillna((s - med) / std)


def score_label(score: float, inverse: bool = False) -> str:
    s = clip_score(score)
    if inverse:
        s = 100 - s
    if s >= 80:
        return "EXTREME"
    if s >= 65:
        return "HIGH"
    if s >= 55:
        return "ELEVATED"
    if s >= 45:
        return "NEUTRAL"
    if s >= 30:
        return "LOW"
    return "VERY LOW"


def _price_frame(pack: dict[str, pd.DataFrame], symbol: str) -> pd.DataFrame:
    frame = pack.get(str(symbol).upper(), pd.DataFrame())
    if frame is None or frame.empty:
        return pd.DataFrame()
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce", utc=True)
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    if "volume" in work.columns:
        work["volume"] = pd.to_numeric(work["volume"], errors="coerce")
    return work.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)


def _returns(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame["close"], errors="coerce").pct_change()


def _perf(frame: pd.DataFrame, days: int) -> float | None:
    if frame.empty or len(frame) <= days:
        return None
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if len(close) <= days:
        return None
    a, b = safe_float(close.iloc[-1]), safe_float(close.iloc[-days - 1])
    return a / b - 1 if a is not None and b not in {None, 0} else None


def _vol(frame: pd.DataFrame, days: int = 20) -> float | None:
    r = _returns(frame).dropna().tail(days)
    return float(r.std() * math.sqrt(TRADING_DAYS)) if len(r) >= max(5, days // 2) else None


def _drawdown(frame: pd.DataFrame) -> float | None:
    if frame.empty:
        return None
    close = pd.to_numeric(frame["close"], errors="coerce").dropna()
    if close.empty:
        return None
    dd = close / close.cummax() - 1
    return safe_float(dd.iloc[-1])


def _latest_return_z(frame: pd.DataFrame) -> float | None:
    return robust_z_last(_returns(frame), 126, 30)


def _volume_z(frame: pd.DataFrame) -> float | None:
    if frame.empty or "volume" not in frame.columns:
        return None
    vol = pd.to_numeric(frame["volume"], errors="coerce").replace(0, np.nan)
    return robust_z_last(np.log1p(vol), 126, 30)


def _range_z(frame: pd.DataFrame) -> float | None:
    if frame.empty or not all(c in frame.columns for c in ["high", "low", "close"]):
        return None
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce").replace(0, np.nan)
    tr = (high - low).abs() / close
    return robust_z_last(tr, 126, 30)


def _relative_perf(pack: dict[str, pd.DataFrame], a: str, b: str, days: int = 20) -> float | None:
    pa = _perf(_price_frame(pack, a), days)
    pb = _perf(_price_frame(pack, b), days)
    return pa - pb if pa is not None and pb is not None else None


def _build_return_panel(pack: dict[str, pd.DataFrame], symbols: tuple[str, ...]) -> pd.DataFrame:
    cols = []
    for symbol in symbols:
        f = _price_frame(pack, symbol)
        if f.empty:
            continue
        s = f.set_index("date")["close"].pct_change().rename(symbol)
        cols.append(s)
    return pd.concat(cols, axis=1).sort_index() if cols else pd.DataFrame()


def _news_analysis(news_df: pd.DataFrame, symbol: str | None = None) -> dict[str, Any]:
    """V2.1.1 semantic reliability + auditable belief extraction layer."""
    return analyze_news_corpus(news_df, symbol=symbol)


def build_historical_analogues(frame: pd.DataFrame, top_n: int = 8) -> pd.DataFrame:
    if frame is None or frame.empty or len(frame) < 150:
        return pd.DataFrame()
    work = frame.copy().sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(work["close"], errors="coerce")
    ret = close.pct_change()
    vol = ret.rolling(20).std() * math.sqrt(TRADING_DAYS)
    dd = close / close.cummax() - 1
    volume = pd.to_numeric(work.get("volume", pd.Series(np.nan, index=work.index)), errors="coerce")
    volume_z = rolling_robust_z(np.log1p(volume.replace(0, np.nan)), 126, 30)

    feats = pd.DataFrame({
        "date": work["date"],
        "ret_5": close.pct_change(5),
        "ret_20": close.pct_change(20),
        "vol_20": vol,
        "drawdown": dd,
        "volume_z": volume_z,
    })
    feature_cols = ["ret_5", "ret_20", "vol_20", "drawdown", "volume_z"]
    for col in feature_cols:
        z = rolling_robust_z(feats[col], 252, 60)
        feats[f"z_{col}"] = z
    zcols = [f"z_{c}" for c in feature_cols]
    current = feats[zcols].iloc[-1]
    if current.isna().all():
        return pd.DataFrame()
    candidates = feats.iloc[:-60].copy()
    common = [c for c in zcols if pd.notna(current[c])]
    if len(common) < 3:
        return pd.DataFrame()
    candidates = candidates.dropna(subset=common)
    if candidates.empty:
        return pd.DataFrame()
    distances = np.sqrt(((candidates[common] - current[common]) ** 2).mean(axis=1))
    candidates["distance"] = distances
    candidates["similarity"] = 100 * np.exp(-candidates["distance"])

    # Forward returns are shown only for already-historical analogues and are not used in state scoring.
    candidates["fwd_20d"] = close.shift(-20) / close - 1
    candidates["fwd_60d"] = close.shift(-60) / close - 1
    candidates = candidates.nsmallest(top_n, "distance")
    return candidates[["date", "similarity", "ret_20", "vol_20", "drawdown", "fwd_20d", "fwd_60d"]].reset_index(drop=True)


def _historical_state_series(target: pd.DataFrame, pack: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if target.empty:
        return pd.DataFrame()
    w = target.copy().sort_values("date").set_index("date")
    close = pd.to_numeric(w["close"], errors="coerce")
    ret = close.pct_change()
    vol = ret.rolling(20).std() * math.sqrt(TRADING_DAYS)
    vol_z = rolling_robust_z(vol, 126, 30)
    abs_ret_z = rolling_robust_z(ret.abs(), 126, 30)
    volume = pd.to_numeric(w.get("volume", pd.Series(index=w.index, dtype=float)), errors="coerce")
    volume_z = rolling_robust_z(np.log1p(volume.replace(0, np.nan)), 126, 30)
    mom20 = close.pct_change(20)
    mom_z = rolling_robust_z(mom20, 126, 30)

    vixf = _price_frame(pack, "^VIX")
    if not vixf.empty:
        vix = vixf.set_index("date")["close"].reindex(w.index).ffill()
        vix_z = rolling_robust_z(vix, 126, 30)
    else:
        vix_z = pd.Series(0.0, index=w.index)

    corr_panel = _build_return_panel(pack, ("SPY", "QQQ", "IWM", "HYG"))
    if not corr_panel.empty:
        corr_panel = corr_panel.reindex(w.index)
        rolling_corrs = []
        cols = list(corr_panel.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                rolling_corrs.append(corr_panel[cols[i]].rolling(20).corr(corr_panel[cols[j]]))
        herding_raw = pd.concat(rolling_corrs, axis=1).mean(axis=1) if rolling_corrs else pd.Series(np.nan, index=w.index)
    else:
        herding_raw = pd.Series(np.nan, index=w.index)

    autocorr20 = ret.rolling(40).apply(lambda x: pd.Series(x).autocorr(1), raw=False)
    out = pd.DataFrame(index=w.index)
    out["attention"] = 50 + 18 * abs_ret_z.fillna(0).clip(-3, 3) + 10 * volume_z.fillna(0).clip(-3, 3)
    out["fear"] = 50 + 20 * vix_z.fillna(0).clip(-3, 3) - 180 * mom20.fillna(0).clip(-0.2, 0.2)
    out["herding"] = 50 + 45 * herding_raw.fillna(0).clip(-0.2, 1.0)
    out["extrapolation"] = 50 + 22 * mom_z.fillna(0).clip(-3, 3) + 20 * autocorr20.fillna(0).clip(-0.5, 0.5)
    out["reflexivity"] = 0.45 * out["attention"] + 0.35 * out["extrapolation"] + 0.20 * (50 + 60 * autocorr20.fillna(0))
    for col in out.columns:
        out[col] = out[col].clip(0, 100)
    out["close"] = close
    out["return"] = ret
    out["vol_20"] = vol
    return out.dropna(subset=["close"]).reset_index()


def _regime_from_scores(s: dict[str, float]) -> tuple[str, str]:
    fear = s.get("fear", 50)
    attention = s.get("attention", 50)
    extrap = s.get("extrapolation", 50)
    narrative = s.get("narrative", 50)
    herding = s.get("herding", 50)
    higher = s.get("higher_order", 50)
    confidence = s.get("confidence", 50)
    disagreement = s.get("disagreement", 50)
    reflex = s.get("reflexivity", 50)
    appetite = s.get("risk_appetite", 50)

    if fear >= 78 and attention >= 70 and appetite <= 35:
        if extrap <= 30:
            return "CAPITULATION", "Fear, attention and negative extrapolation are simultaneously extreme."
        return "FEAR CASCADE", "Fear is propagating with elevated attention and weak risk appetite."
    if disagreement >= 72 and confidence >= 62:
        return "BELIEF FRAGMENTATION", "High disagreement coexists with high conviction: a two-sided unstable market."
    if confidence >= 75 and disagreement <= 30 and extrap >= 65:
        return "FRAGILE CONSENSUS", "Consensus is unusually tight while confidence and extrapolation are elevated."
    if narrative >= 78 and attention >= 72 and higher >= 70:
        return "NARRATIVE MANIA", "Narrative concentration, attention and higher-order optimism are jointly extreme."
    if reflex >= 72 and extrap >= 65 and herding >= 65 and appetite >= 60:
        return "REFLEXIVE SPECULATIVE EXPANSION", "Price/attention feedback, synchronization and risk appetite are reinforcing each other."
    if extrap >= 65 and appetite >= 55:
        return "EXTRAPOLATIVE EXPANSION", "Recent performance is being extended in a constructive risk-taking regime."
    if appetite >= 58 and fear <= 45 and disagreement <= 55:
        return "CAUTIOUS ACCUMULATION", "Risk appetite is positive without clear evidence of mania or extreme consensus."
    if disagreement <= 48 and 40 <= confidence <= 68 and narrative <= 68 and fear <= 60:
        return "RATIONAL CONSENSUS", "Signals are relatively coherent without extreme behavioral amplification."
    return "MIXED / UNIDENTIFIED", "No single behavioral mechanism dominates with sufficient strength."



# ============================================================
# V1.2 — VISUAL ALARM / SCENARIO MONITOR
# ============================================================
# This layer does not change the underlying psychology estimates.
# It maps existing latent/proxy scores into operational alert states,
# threshold crossings and scenario-pattern matches for rapid visual reading.


def _alarm_level(score: Any) -> tuple[str, int]:
    s = clip_score(score)
    if s >= 82:
        return "CRITICAL", 3
    if s >= 70:
        return "HIGH", 2
    if s >= 58:
        return "WATCH", 1
    return "NORMAL", 0


def _history_delta(history: pd.DataFrame, column: str, lookback: int = 5) -> float | None:
    if history is None or history.empty or column not in history.columns:
        return None
    s = pd.to_numeric(history[column], errors="coerce").dropna()
    if len(s) <= lookback:
        return None
    return safe_float(s.iloc[-1] - s.iloc[-1 - lookback])


def _trend_label(delta: Any, threshold: float = 4.0) -> str:
    d = safe_float(delta)
    if d is None:
        return "SNAPSHOT"
    if d >= threshold:
        return "RISING"
    if d <= -threshold:
        return "FALLING"
    return "STABLE"


def _soft_high(value: Any, threshold: float, width: float = 18.0) -> float:
    """0..100 match score for a high-side condition."""
    v = clip_score(value)
    x = (v - threshold) / max(width, 1e-6)
    return float(np.clip(50.0 + 50.0 * np.tanh(x), 0.0, 100.0))


def _soft_low(value: Any, threshold: float, width: float = 18.0) -> float:
    """0..100 match score for a low-side condition."""
    v = clip_score(value)
    x = (threshold - v) / max(width, 1e-6)
    return float(np.clip(50.0 + 50.0 * np.tanh(x), 0.0, 100.0))


def build_behavioral_alerts(
    scores: dict[str, float],
    history: pd.DataFrame | None = None,
    latent_table: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    V2.0.1 operational board.

    Structural state and acute alarm are intentionally separate:
    - structural state = persistent level geometry (LOW/NORMAL/ELEVATED/HIGH/EXTREME)
    - acute alarm = unusual/new directional event (NORMAL/WATCH/HIGH/CRITICAL)

    Snapshot-only mechanisms expose a structural state but no calibrated acute alarm.
    """
    history = history if isinstance(history, pd.DataFrame) else pd.DataFrame()
    latent_table = latent_table if isinstance(latent_table, pd.DataFrame) else pd.DataFrame()

    latent_lookup: dict[str, dict[str, Any]] = {}
    if not latent_table.empty and "Key" in latent_table.columns:
        for _, row in latent_table.iterrows():
            latent_lookup[str(row.get("Key", ""))] = row.to_dict()

    derived = [
        {
            "key": "fear", "alarm": "Tail / fear stress",
            "score": clip_score(scores.get("fear", 50)), "history_key": "fear",
            "question": "Is defensive psychology becoming extreme or newly accelerating?",
            "trigger": "Structural state + direction-aware acute stress alarm.",
        },
        {
            "key": "attention", "alarm": "Attention shock",
            "score": clip_score(scores.get("attention", 50)), "history_key": "attention",
            "question": "Is the market entering an abnormal attention regime?",
            "trigger": "Two-sided attention shock: surge or collapse can be acute.",
        },
        {
            "key": "herding", "alarm": "Crowding / herding",
            "score": clip_score(scores.get("herding", 50)), "history_key": "herding",
            "question": "Are cross-asset behaviours synchronizing, and is crowding accelerating?",
            "trigger": "Structural crowding is separated from a new crowding event.",
        },
        {
            "key": "extrapolation", "alarm": "Extrapolation heat",
            "score": clip_score(scores.get("extrapolation", 50)), "history_key": "extrapolation",
            "question": "Are recent returns being extended into beliefs?",
            "trigger": "Positive extrapolation shocks count as heat; normalization does not.",
        },
        {
            "key": "narrative", "alarm": "Narrative concentration",
            "score": clip_score(scores.get("narrative", 50)), "history_key": None,
            "question": "Is one story dominating the information set?",
            "trigger": "Structural snapshot only; point-in-time narrative history is not yet connected.",
        },
        {
            "key": "reflexivity", "alarm": "Reflexive feedback",
            "score": clip_score(max(scores.get("reflexivity", 50), scores.get("mechanical_reflexivity", 50))),
            "history_key": "reflexivity",
            "question": "Are price, attention and positioning feeding back on each other?",
            "trigger": "Psychological feedback is calibrated historically; mechanical reflexivity remains a snapshot proxy.",
        },
        {
            "key": "belief_fragmentation", "alarm": "Belief fragmentation",
            "score": clip_score(0.58 * scores.get("disagreement", 50) + 0.42 * scores.get("ambiguity", 50)),
            "history_key": None,
            "question": "Is the market divided while uncertainty remains high?",
            "trigger": "Structural snapshot composite; direct belief archive not yet connected.",
        },
        {
            "key": "speculative_convexity", "alarm": "Speculative convexity",
            "score": clip_score(
                0.38 * scores.get("lottery_demand", 50)
                + 0.32 * scores.get("higher_order", 50)
                + 0.30 * scores.get("risk_appetite", 50)
            ),
            "history_key": None,
            "question": "Are convexity demand and crowd optimism reinforcing speculation?",
            "trigger": "Structural snapshot composite; historical options/belief data is required for acute calibration.",
        },
    ]

    visual_names = {0: "NORMAL", 1: "WATCH", 2: "HIGH", 3: "CRITICAL"}
    rows = []
    for item in derived:
        latent = latent_lookup.get(item["key"], {})
        percentile = safe_float(latent.get("Percentile"))
        shock_z = safe_float(latent.get("Shock z"))
        velocity = safe_float(latent.get("5D velocity"))
        acceleration = safe_float(latent.get("Acceleration"))
        persistence = safe_float(latent.get("Persistence"))

        if item.get("history_key") and latent:
            # Structural display is always based on the actual alert score. For Reflexivity,
            # that score may be lifted by the mechanical snapshot, while the acute event
            # calibration remains psychological/history-based.
            structural_state, structural_rank = structural_state_label(item["score"])
            acute_alarm = str(latent.get("Acute alarm", "NORMAL"))
            acute_rank = int(safe_float(latent.get("Acute rank"), 0) or 0)
            shock_direction = str(latent.get("Shock direction", shock_semantics(item["key"], shock_z)))
            acute_duration = int(safe_float(latent.get("Acute duration"), 0) or 0)
            structural_duration = int(safe_float(latent.get("Structural duration"), 0) or 0)
            acute_onset = latent.get("Acute onset", pd.NaT)
            structural_onset = latent.get("Structural onset", pd.NaT)
            if item["key"] == "reflexivity" and item["score"] > clip_score(scores.get("reflexivity", 50)) + 1e-6:
                # The structural level is partly mechanical and snapshot-only, so no fake
                # historical duration/onset is claimed for that combined state.
                structural_duration = 0
                structural_onset = pd.NaT
            delta = velocity * 5.0 if velocity is not None else _history_delta(history, item["history_key"], lookback=5)
        else:
            structural_state, structural_rank = structural_state_label(item["score"])
            acute_alarm = "N/A"
            acute_rank = 0
            shock_direction = "SNAPSHOT"
            acute_duration = 0
            structural_duration = 0
            acute_onset = pd.NaT
            structural_onset = pd.NaT
            delta = None

        visual_code = max(int(structural_rank), int(acute_rank))
        level = visual_names.get(visual_code, "NORMAL")
        rows.append({
            "Key": item["key"],
            "Alarm": item["alarm"],
            "Score": round(float(item["score"]), 1),
            "Structural State": structural_state,
            "StructuralRank": int(structural_rank),
            "Acute Alarm": acute_alarm,
            "AcuteRank": int(acute_rank),
            "Shock Direction": shock_direction,
            # Legacy visual severity for sorting / colour only.
            "Level": level,
            "LevelCode": visual_code,
            "Percentile": round(float(percentile), 1) if percentile is not None else np.nan,
            "Shock z": round(float(shock_z), 2) if shock_z is not None else np.nan,
            "5D Delta": round(float(delta), 1) if delta is not None else np.nan,
            "Velocity": round(float(velocity), 2) if velocity is not None else np.nan,
            "Acceleration": round(float(acceleration), 3) if acceleration is not None else np.nan,
            "Persistence": round(float(persistence), 1) if persistence is not None else np.nan,
            "Acute Duration": acute_duration,
            "Structural Duration": structural_duration,
            "Acute Onset": acute_onset,
            "Structural Onset": structural_onset,
            # Compatibility aliases.
            "Duration": acute_duration,
            "Onset": acute_onset,
            "Trend": _trend_label(delta),
            "Question": item["question"],
            "Trigger": item["trigger"],
        })
    return pd.DataFrame(rows).sort_values(["LevelCode", "Score"], ascending=[False, False]).reset_index(drop=True)

def build_scenario_monitor(
    scores: dict[str, float],
    diagnostics: dict[str, Any] | None = None,
    latent_table: pd.DataFrame | None = None,
    history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    V2.0.1 scenario monitor with hard necessary-condition gates.

    A template similarity cannot activate a scenario unless its defining conditions
    have actually been observed. This prevents patterns such as POST-CAPITULATION
    from appearing solely because Fear is falling from an ordinary level.
    """
    d = diagnostics or {}
    latent_table = latent_table if isinstance(latent_table, pd.DataFrame) else pd.DataFrame()
    history = history if isinstance(history, pd.DataFrame) else pd.DataFrame()
    lookup: dict[str, dict[str, Any]] = {}
    if not latent_table.empty and "Key" in latent_table.columns:
        for _, row in latent_table.iterrows():
            lookup[str(row.get("Key", ""))] = row.to_dict()

    fear = scores.get("fear", 50)
    attn = scores.get("attention", 50)
    extrap = scores.get("extrapolation", 50)
    narr = scores.get("narrative", 50)
    herd = scores.get("herding", 50)
    higher = scores.get("higher_order", 50)
    conf = scores.get("confidence", 50)
    dis = scores.get("disagreement", 50)
    amb = scores.get("ambiguity", 50)
    refl = max(scores.get("reflexivity", 50), scores.get("mechanical_reflexivity", 50))
    appetite = scores.get("risk_appetite", 50)
    lottery = scores.get("lottery_demand", 50)
    arb = scores.get("arbitrage_capacity", 50)

    def dyn(key: str, direction: int = 1) -> float:
        row = lookup.get(key, {})
        v = safe_float(row.get("5D velocity"), 0.0) or 0.0
        a = safe_float(row.get("Acceleration"), 0.0) or 0.0
        p = safe_float(row.get("Persistence"), 50.0) or 50.0
        directional = 50.0 + 32.0 * np.tanh(direction * v / 2.0) + 18.0 * np.tanh(direction * a / 0.45)
        return clip_score(0.70 * directional + 0.30 * p)

    def lv(key: str, field: str, default: float = 0.0) -> float:
        return safe_float(lookup.get(key, {}).get(field), default) or default

    def recent_peak(key: str, days: int = 60) -> float | None:
        col = f"{key}_latent"
        if history.empty or col not in history.columns:
            return None
        s = pd.to_numeric(history[col], errors="coerce").dropna().tail(days)
        return float(s.max()) if not s.empty else None

    fear_peak_60 = recent_peak("fear", 60)
    fear_v = lv("fear", "5D velocity")
    fear_z = lv("fear", "Shock z")
    extrap_v = lv("extrapolation", "5D velocity")
    herd_v = lv("herding", "5D velocity")
    refl_v = lv("reflexivity", "5D velocity")

    scenarios = [
        {
            "name": "REFLEXIVE SPECULATIVE EXPANSION",
            "conditions": [_soft_high(extrap, 66), _soft_high(herd, 65), _soft_high(refl, 68), _soft_high(appetite, 58), _soft_low(fear, 50)],
            "dynamics": [dyn("extrapolation", 1), dyn("herding", 1), dyn("reflexivity", 1)],
            "gate": bool(extrap >= 58 and herd >= 60 and refl >= 55 and appetite >= 52 and (extrap_v > 0 or herd_v > 0 or refl_v > 0)),
            "gate_reason": "Requires elevated extrapolation/crowding/reflexivity, constructive risk appetite and at least one reinforcing trajectory.",
            "description": "Momentum, crowding and feedback loops reinforce risk-taking.",
            "watch": "Fragility rises if persistence remains high while narrative concentration accelerates or arbitrage capacity weakens.",
        },
        {
            "name": "NARRATIVE MANIA",
            "conditions": [_soft_high(narr, 72), _soft_high(attn, 68), _soft_high(higher, 64), _soft_high(lottery, 62)],
            "dynamics": [dyn("attention", 1), dyn("extrapolation", 1)],
            "gate": bool(narr >= 70 and attn >= 60 and higher >= 60),
            "gate_reason": "Requires a concentrated narrative plus elevated attention and higher-order speculative beliefs.",
            "description": "A concentrated story captures attention and supports higher-order speculative demand.",
            "watch": "Watch narrative saturation, attention persistence, option convexity and breadth deterioration.",
        },
        {
            "name": "FRAGILE CONSENSUS",
            "conditions": [_soft_high(conf, 68), _soft_low(dis, 38), _soft_high(herd, 62), _soft_high(narr, 58)],
            "dynamics": [dyn("herding", 1)],
            "gate": bool(conf >= 65 and dis <= 45 and herd >= 60),
            "gate_reason": "Requires high confidence, genuinely low disagreement and synchronized positioning.",
            "description": "Investors appear unusually aligned and confident.",
            "watch": "Low disagreement plus persistent synchronization can make the market vulnerable to a common-belief reversal.",
        },
        {
            "name": "BELIEF FRAGMENTATION",
            "conditions": [_soft_high(dis, 68), _soft_high(amb, 58), _soft_high(conf, 55)],
            "dynamics": [],
            "gate": bool(dis >= 65 and amb >= 55),
            "gate_reason": "Requires simultaneously elevated disagreement and ambiguity.",
            "description": "Substantial disagreement coexists with uncertainty about the state of the world.",
            "watch": "Expect unstable two-sided price discovery, volume and volatility; direct belief history is still required.",
        },
        {
            "name": "FEAR CASCADE",
            "conditions": [_soft_high(fear, 68), _soft_high(attn, 65), _soft_low(appetite, 42), _soft_high(amb, 58)],
            "dynamics": [dyn("fear", 1), dyn("attention", 1)],
            "gate": bool(fear >= 62 and appetite <= 48 and (fear_v > 0.25 or fear_z > 1.0)),
            "gate_reason": "Requires elevated Fear, impaired risk appetite and a positive Fear shock/trajectory.",
            "description": "Defensive beliefs, attention and uncertainty are propagating together.",
            "watch": "Escalation risk increases if fear/attention accelerate while liquidity and cross-asset synchronization deteriorate.",
        },
        {
            "name": "CAPITULATION",
            "conditions": [_soft_high(fear, 78), _soft_high(attn, 70), _soft_low(extrap, 35), _soft_low(appetite, 35)],
            "dynamics": [dyn("fear", 1), dyn("attention", 1), dyn("extrapolation", -1)],
            "gate": bool(fear >= 72 and attn >= 62 and appetite <= 40 and (fear_v > 0 or fear_z > 1.0)),
            "gate_reason": "Requires genuinely extreme Fear/attention, damaged risk appetite and ongoing defensive acceleration.",
            "description": "Fear and attention are extreme while extrapolation and risk appetite collapse.",
            "watch": "Research-only reversal watch; require breadth, liquidity and flow confirmation.",
        },
        {
            "name": "POST-CAPITULATION",
            "conditions": [_soft_high(fear, 62), _soft_high(appetite, 45), _soft_low(extrap, 48)],
            "dynamics": [dyn("fear", -1), dyn("extrapolation", 1)],
            "gate": bool(
                fear_peak_60 is not None
                and fear_peak_60 >= 72
                and fear <= fear_peak_60 - 8
                and fear_v < 0
                and appetite >= 45
            ),
            "gate_reason": "Requires a documented recent Fear peak >=72 followed by meaningful Fear decay and recovering risk appetite.",
            "description": "A previously extreme defensive state is unwinding while risk appetite begins to recover.",
            "watch": "Potential stabilization pattern; require breadth/flow confirmation before interpretation.",
        },
        {
            "name": "COMPLACENT RISK-ON",
            "conditions": [_soft_low(fear, 35), _soft_high(appetite, 68), _soft_low(dis, 45), _soft_high(arb, 55)],
            "dynamics": [dyn("fear", -1), dyn("herding", 1)],
            "gate": bool(fear <= 40 and appetite >= 60 and dis <= 50),
            "gate_reason": "Requires subdued Fear/disagreement and clearly elevated risk appetite.",
            "description": "Risk-taking is strong while fear and disagreement are subdued.",
            "watch": "Watch for asymmetric tail-risk repricing if volatility, ambiguity or attention shocks turn higher.",
        },
    ]

    rows = []
    for spec in scenarios:
        conditions = spec["conditions"]
        dynamics = spec["dynamics"]
        level_match = float(np.mean(conditions)) if conditions else 0.0
        dynamic_match = float(np.mean(dynamics)) if dynamics else 50.0
        dynamic_weight = 0.22 if dynamics else 0.0
        raw_match = (1.0 - dynamic_weight) * level_match + dynamic_weight * dynamic_match
        eligible = bool(spec["gate"])
        match = raw_match if eligible else min(raw_match, 47.0)

        if not eligible:
            status = "GATED"
        elif match >= 78:
            status = "ACTIVE"
        elif match >= 62:
            status = "WATCH"
        elif match >= 48:
            status = "PARTIAL"
        else:
            status = "QUIET"

        relevant = []
        for key in ("attention", "fear", "herding", "extrapolation", "reflexivity"):
            row = lookup.get(key)
            if row:
                relevant.append((safe_float(row.get("5D velocity"), 0.0) or 0.0, safe_float(row.get("Persistence"), 0.0) or 0.0))
        mean_v = float(np.mean([x[0] for x in relevant])) if relevant else 0.0
        mean_p = float(np.mean([x[1] for x in relevant])) if relevant else np.nan
        trajectory = "ACCELERATING" if mean_v >= 0.8 else "DECELERATING" if mean_v <= -0.8 else "STABLE"

        rows.append({
            "Scenario": spec["name"],
            "Match": round(match, 1),
            "Raw template match": round(raw_match, 1),
            "Level match": round(level_match, 1),
            "Dynamic match": round(dynamic_match, 1),
            "Eligible": eligible,
            "Gate": "PASS" if eligible else "FAIL",
            "Gate reason": spec["gate_reason"],
            "Status": status,
            "Trajectory": trajectory,
            "Persistence": round(mean_p, 1) if np.isfinite(mean_p) else np.nan,
            "Observed pattern": spec["description"],
            "What to watch": spec["watch"],
        })
    return pd.DataFrame(rows).sort_values(["Eligible", "Match"], ascending=[False, False]).reset_index(drop=True)

def build_alarm_evolution(history: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """Compact adaptive alarm panel based on the one-sided latent state history."""
    if history is None or history.empty:
        return pd.DataFrame()
    cols = [c for c in ["attention", "fear", "herding", "extrapolation", "reflexivity"] if c in history.columns]
    if not cols:
        return pd.DataFrame()
    keep = ["date"] + cols
    for col in cols:
        for suffix in ["_severity", "_percentile", "_shock_z"]:
            c = f"{col}{suffix}"
            if c in history.columns:
                keep.append(c)
    h = history[keep].copy().tail(max(int(window), 20))
    h["date"] = pd.to_datetime(h["date"], errors="coerce", utc=True)
    for col in [c for c in h.columns if c != "date"]:
        h[col] = pd.to_numeric(h[col], errors="coerce")
    return h.dropna(subset=["date"]).reset_index(drop=True)


def build_historical_alarm_events(history: pd.DataFrame, max_events: int = 16) -> pd.DataFrame:
    """
    V2 historical adaptive-alarm onset log. A run is logged only when severity first reaches
    HIGH/CRITICAL (>=2). Forward returns remain descriptive and never enter state construction.
    """
    if history is None or history.empty or "date" not in history.columns:
        return pd.DataFrame()
    h = history.copy().sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(h.get("close", np.nan), errors="coerce")
    h["fwd_5d"] = close.shift(-5) / close - 1
    h["fwd_20d"] = close.shift(-20) / close - 1

    specs = [
        ("ATTENTION SHOCK", "attention"),
        ("FEAR STRESS", "fear"),
        ("CROWDING / HERDING", "herding"),
        ("EXTRAPOLATION SURGE", "extrapolation"),
        ("REFLEXIVE HEAT", "reflexivity"),
    ]
    rows = []
    for label, key in specs:
        score = pd.to_numeric(h.get(key, np.nan), errors="coerce")
        severity_col = f"{key}_severity"
        if severity_col in h.columns:
            severity = pd.to_numeric(h[severity_col], errors="coerce").fillna(0).astype(int)
            condition = severity >= 2
        else:
            condition = score >= 82
            severity = pd.Series(np.where(score >= 82, 3, np.where(score >= 70, 2, 0)), index=h.index)
        onset = condition & ~condition.shift(1, fill_value=False)
        for idx in h.index[onset]:
            sev = int(severity.iloc[idx])
            level = "CRITICAL" if sev >= 3 else "HIGH"
            pct = safe_float(h.loc[idx, f"{key}_percentile"]) if f"{key}_percentile" in h.columns else None
            shock_z = safe_float(h.loc[idx, f"{key}_shock_z"]) if f"{key}_shock_z" in h.columns else None
            rows.append({
                "Date": h.loc[idx, "date"],
                "Observed alarm": label,
                "State": round(float(score.iloc[idx]), 1) if pd.notna(score.iloc[idx]) else np.nan,
                "Percentile": round(float(pct), 1) if pct is not None else np.nan,
                "Shock z": round(float(shock_z), 2) if shock_z is not None else np.nan,
                "Severity": level,
                "5D forward": h.loc[idx, "fwd_5d"],
                "20D forward": h.loc[idx, "fwd_20d"],
            })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Date", ascending=False).head(max_events).reset_index(drop=True)


def build_psychology_state(
    symbol: str,
    pack: dict[str, pd.DataFrame],
    news_df: pd.DataFrame,
    options: dict[str, Any],
    behavioral_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbol = str(symbol or "SPY").upper().strip()
    target = _price_frame(pack, symbol)
    if target.empty:
        raw_target = pack.get(symbol, pd.DataFrame()) if isinstance(pack, dict) else pd.DataFrame()
        attempts = []
        try:
            attempts = list(raw_target.attrs.get("provider_attempts", []))
        except Exception:
            attempts = []
        return {
            "available": False,
            "reason": f"No price data for {symbol} after the configured provider waterfall.",
            "provider_attempts": attempts,
        }

    news = _news_analysis(news_df, symbol=symbol)
    panel = _build_return_panel(pack, ("SPY", "QQQ", "IWM", "HYG", "TLT", "GLD"))
    bdata = behavioral_data if isinstance(behavioral_data, dict) else {}
    vol_tail = bdata.get("volatility_tail", {}) if isinstance(bdata.get("volatility_tail", {}), dict) else {}
    breadth_layer = bdata.get("breadth", {}) if isinstance(bdata.get("breadth", {}), dict) else {}
    funding_layer = bdata.get("funding_credit", {}) if isinstance(bdata.get("funding_credit", {}), dict) else {}
    positioning_layer = bdata.get("positioning", {}) if isinstance(bdata.get("positioning", {}), dict) else {}
    option_behavior_layer = bdata.get("options_behavior", {}) if isinstance(bdata.get("options_behavior", {}), dict) else {}
    vol_metrics = vol_tail.get("metrics", {}) if isinstance(vol_tail.get("metrics", {}), dict) else {}
    breadth_metrics = breadth_layer.get("metrics", {}) if isinstance(breadth_layer.get("metrics", {}), dict) else {}
    funding_metrics = funding_layer.get("metrics", {}) if isinstance(funding_layer.get("metrics", {}), dict) else {}
    positioning_metrics = positioning_layer.get("metrics", {}) if isinstance(positioning_layer.get("metrics", {}), dict) else {}
    option_behavior = option_behavior_layer.get("metrics", {}) if isinstance(option_behavior_layer.get("metrics", {}), dict) else {}

    ret_z = _latest_return_z(target)
    volume_z = _volume_z(target)
    range_z = _range_z(target)
    perf5 = _perf(target, 5)
    perf20 = _perf(target, 20)
    perf60 = _perf(target, 60)
    vol20 = _vol(target, 20)
    dd = _drawdown(target)
    ret = _returns(target).dropna()
    autocorr = safe_float(ret.tail(60).autocorr(1), 0.0) or 0.0
    skew = safe_float(ret.tail(60).skew(), 0.0) or 0.0

    vix = _price_frame(pack, "^VIX")
    vix_level = safe_float(vix["close"].iloc[-1]) if not vix.empty else None
    vix_z = robust_z_last(vix["close"], 126, 30) if not vix.empty else None
    # V2.2 prefers observed Cboe/FRED volatility-layer values when available.
    if safe_float(vol_metrics.get("vix")) is not None:
        vix_level = safe_float(vol_metrics.get("vix"))
    if safe_float(vol_metrics.get("vix_z")) is not None:
        vix_z = safe_float(vol_metrics.get("vix_z"))
    tail_stress_score = safe_float(vol_metrics.get("tail_stress_score"))
    vol_ambiguity_score = safe_float(vol_metrics.get("ambiguity_score"))
    breadth_score = safe_float(breadth_metrics.get("breadth_score"))
    participation_fragility = safe_float(breadth_metrics.get("participation_fragility_score"))
    funding_stress_score = safe_float(funding_metrics.get("funding_stress_score"))
    funding_arbitrage_capacity = safe_float(funding_metrics.get("arbitrage_capacity_score"))
    positioning_crowding = safe_float(positioning_metrics.get("positioning_crowding_score"))
    lev_money_percentile = safe_float(positioning_metrics.get("lev_money_percentile"))
    option_tail_score = safe_float(option_behavior.get("option_tail_demand_score"))
    option_lottery_score = safe_float(option_behavior.get("option_lottery_score"))
    option_concentration_score = safe_float(option_behavior.get("convexity_concentration_score"))

    # Cross-asset disagreement and synchronization.
    dispersion = 0.0
    sign_sync = 0.5
    avg_corr = 0.0
    if not panel.empty:
        last20 = (1 + panel.tail(20)).prod() - 1
        dispersion = safe_float(last20.std(), 0.0) or 0.0
        signs = np.sign(last20.dropna())
        if len(signs) > 0:
            pos_share = float((signs > 0).mean())
            neg_share = float((signs < 0).mean())
            sign_sync = max(pos_share, neg_share)
        corr = panel.tail(60).corr()
        vals = corr.values[np.triu_indices_from(corr.values, k=1)] if len(corr.columns) >= 2 else np.array([])
        vals = vals[np.isfinite(vals)]
        avg_corr = float(vals.mean()) if len(vals) else 0.0

    put_call_vol = safe_float(options.get("put_call_volume")) if isinstance(options, dict) else None
    put_call_oi = safe_float(options.get("put_call_oi")) if isinstance(options, dict) else None
    near_term_share = safe_float(options.get("near_term_share")) if isinstance(options, dict) else None
    call_volume = safe_float(options.get("call_volume")) if isinstance(options, dict) else None
    put_volume = safe_float(options.get("put_volume")) if isinstance(options, dict) else None
    option_rows = int(options.get("rows", 0)) if isinstance(options, dict) else 0
    call_share = None
    if call_volume is not None and put_volume is not None and call_volume + put_volume > 0:
        call_share = call_volume / (call_volume + put_volume)

    # 1) Cognition.
    attention = clip_score(
        50
        + 12 * abs(np.clip(ret_z or 0, -3, 3))
        + 10 * np.clip(volume_z or 0, -3, 3)
        + min(18, news["count"] * 1.6)
    )
    salience = clip_score(
        50
        + 14 * abs(np.clip(ret_z or 0, -3, 3))
        + 10 * abs(np.clip(range_z or 0, -3, 3))
        + 70 * max(0.0, abs(perf5 or 0) - 0.02)
    )
    extrapolation = clip_score(
        50
        + 260 * np.clip(perf20 or 0, -0.20, 0.20)
        + 120 * np.clip(perf60 or 0, -0.35, 0.35)
        + 30 * np.clip(autocorr, -0.5, 0.5)
    )

    # 2) Beliefs.
    dispersion_component = np.clip(dispersion / 0.08, 0, 2)
    option_two_sided = 0.5
    if put_call_vol is not None:
        option_two_sided = max(0.0, 1.0 - min(abs(math.log(max(put_call_vol, 1e-6))) / 1.2, 1.0))
    market_disagreement = clip_score(
        24
        + 34 * dispersion_component
        + 24 * option_two_sided
        + 18 * np.clip(news.get("sentiment_std", 0.0), 0, 1)
    )
    disagreement = clip_score(
        0.54 * news.get("belief_disagreement", 50.0)
        + 0.38 * market_disagreement
        + 0.08 * (50.0 if positioning_crowding is None else 100.0 - abs((lev_money_percentile or 50.0) - 50.0))
    )
    trend_coherence = clip_score(50 + 160 * abs(perf20 or 0) - 450 * (vol20 or 0.20) * 0.05)
    confidence = clip_score(
        0.34 * (100 - disagreement)
        + 0.34 * trend_coherence
        + 0.32 * news.get("belief_confidence_mean", 50.0)
    )
    ambiguity_market = clip_score(
        35
        + 12 * max(vix_z or 0, 0)
        + 30 * np.clip(news["uncertainty_share"], 0, 1)
        + 18 * dispersion_component
        + 20 * np.clip(1 - abs(avg_corr), 0, 1)
    )
    ambiguity = clip_score(
        0.72 * ambiguity_market
        + 0.28 * (vol_ambiguity_score if vol_ambiguity_score is not None else ambiguity_market)
    )

    # 3) Preferences / affect.
    put_call_fear = 0.0
    if put_call_vol is not None:
        put_call_fear = np.clip((put_call_vol - 0.75) / 1.0, -0.8, 1.5)
    fear_base = clip_score(
        42
        + 15 * max(vix_z or 0, -1.5)
        - 230 * np.clip(perf20 or 0, -0.20, 0.20)
        + 18 * put_call_fear
        + 25 * news["negative_share"]
    )
    fear_observed_parts = [fear_base]
    if tail_stress_score is not None:
        fear_observed_parts.append(tail_stress_score)
    if option_tail_score is not None:
        fear_observed_parts.append(option_tail_score)
    fear = clip_score(np.average(fear_observed_parts, weights=[0.58] + ([0.27] if tail_stress_score is not None else []) + ([0.15] if option_tail_score is not None else [])))
    smallcap_rel = _relative_perf(pack, "IWM", "SPY", 20) or 0.0
    credit_rel = _relative_perf(pack, "HYG", "TLT", 20) or 0.0
    risk_appetite_base = clip_score(
        52
        + 260 * np.clip(smallcap_rel, -0.12, 0.12)
        + 180 * np.clip(credit_rel, -0.12, 0.12)
        + 130 * np.clip(_perf(_price_frame(pack, "SPY"), 20) or 0, -0.15, 0.15)
        - 10 * max(vix_z or 0, -1.0)
    )
    risk_appetite = clip_score(
        0.72 * risk_appetite_base
        + 0.28 * (breadth_score if breadth_score is not None else risk_appetite_base)
    )
    lottery_base = clip_score(
        45
        + (35 * ((call_share - 0.5) / 0.5) if call_share is not None else 0)
        + (24 * ((near_term_share - 0.35) / 0.65) if near_term_share is not None else 0)
        + 12 * np.clip(skew, -1.5, 2.5)
    )
    lottery_demand = clip_score(
        0.68 * lottery_base
        + 0.32 * (option_lottery_score if option_lottery_score is not None else lottery_base)
    )

    # 4) Social / reflexive.
    narrative = clip_score(news.get("narrative_state_score", 35.0)) if news.get("count", 0) else 35.0
    herding_market = clip_score(40 + 48 * np.clip(avg_corr, -0.2, 1.0) + 18 * np.clip((sign_sync - 0.5) / 0.5, 0, 1))
    herding_parts = [herding_market]
    herding_weights = [0.62]
    if participation_fragility is not None:
        herding_parts.append(participation_fragility)
        herding_weights.append(0.18)
    if positioning_crowding is not None:
        herding_parts.append(positioning_crowding)
        herding_weights.append(0.20)
    herding = clip_score(np.average(herding_parts, weights=herding_weights))
    social_contagion = clip_score(0.38 * attention + 0.34 * herding + 0.28 * narrative)
    higher_order = clip_score(
        0.22 * attention
        + 0.22 * extrapolation
        + 0.17 * lottery_demand
        + 0.16 * herding
        + 0.14 * narrative
        + 0.09 * (positioning_crowding if positioning_crowding is not None else 50.0)
        - 0.12 * max(fear - 50, 0)
    )

    ret_volume_corr = 0.0
    if "volume" in target.columns:
        tmp = pd.DataFrame({
            "r": ret,
            "vz": pd.to_numeric(target.set_index("date")["volume"], errors="coerce").pct_change(),
        }).dropna().tail(60)
        if len(tmp) >= 20:
            ret_volume_corr = abs(safe_float(tmp["r"].corr(tmp["vz"]), 0.0) or 0.0)
    # Historical-compatible reflexivity proxy is retained for the causal latent filter.
    # V2.2 snapshot observations are not backfilled into history.
    reflexivity_historical_compatible = clip_score(
        0.30 * attention
        + 0.25 * extrapolation
        + 0.20 * herding_market
        + 0.15 * lottery_base
        + 10 * np.clip(abs(autocorr) / 0.35, 0, 1)
        + 10 * np.clip(ret_volume_corr / 0.5, 0, 1)
    )
    reflexivity = clip_score(
        0.72 * reflexivity_historical_compatible
        + 0.10 * (breadth_score if breadth_score is not None else 50.0)
        + 0.10 * (option_concentration_score if option_concentration_score is not None else 50.0)
        + 0.08 * (positioning_crowding if positioning_crowding is not None else 50.0)
    )
    mechanical_base = clip_score(
        42
        + 12 * max(vix_z or 0, 0)
        + 20 * (near_term_share or 0)
        + 8 * abs(np.clip(ret_z or 0, -3, 3))
        + 7 * max(volume_z or 0, 0)
    )
    mechanical_parts = [mechanical_base]
    mechanical_weights = [0.68]
    if option_concentration_score is not None:
        mechanical_parts.append(option_concentration_score)
        mechanical_weights.append(0.17)
    if tail_stress_score is not None:
        mechanical_parts.append(tail_stress_score)
        mechanical_weights.append(0.15)
    mechanical_reflexivity = clip_score(np.average(mechanical_parts, weights=mechanical_weights))
    arbitrage_base = clip_score(
        68
        - 12 * max(vix_z or 0, 0)
        - 180 * max(-credit_rel, 0)
        - 12 * max(volume_z or 0, 0)
        + 8 * max(avg_corr, 0)
    )
    arbitrage_capacity = clip_score(
        0.58 * arbitrage_base
        + 0.42 * (funding_arbitrage_capacity if funding_arbitrage_capacity is not None else arbitrage_base)
    )

    # V2.3.1 replaces the legacy price/vol nearest-neighbour memory score after
    # the calibrated latent-state history has been built. Keep a neutral placeholder
    # here so memory never contaminates the five latent mechanisms.
    analogues = pd.DataFrame()
    memory_score = 50.0
    memory_evidence = "Behavioral Memory V2.3.1 pending temporal/retrieval calibration."

    experience_score = 50.0  # intentionally unobserved in the public fallback
    information_processing = clip_score(
        25
        + 38 * news.get("semantic_redundancy", news.get("headline_redundancy", 0.0))
        + 22 * news.get("theme_concentration", 0.0)
        + 0.18 * news.get("belief_disagreement", 50.0)
        + min(12, news.get("count", 0) * 0.35)
    ) if news.get("count", 0) else 35.0

    # Mental-model classifier is intentionally categorical; score = strength of dominant evidence.
    model_candidates = {
        "EXTRAPOLATIVE / MOMENTUM": extrapolation,
        "NARRATIVE-DRIVEN": narrative,
        "FLOW / RISK-ON": risk_appetite,
        "TAIL-RISK / DEFENSIVE": fear,
        "REFLEXIVE": reflexivity,
    }
    mental_model_label, mental_model_strength = max(model_candidates.items(), key=lambda kv: kv[1])
    nlp_mental_model = str(news.get("dominant_mental_model", "MIXED / UNIDENTIFIED"))
    if mental_model_strength < 62 and nlp_mental_model not in {"", "MIXED / UNIDENTIFIED"}:
        mental_model_label = nlp_mental_model
        mental_model_strength = max(55.0, narrative)
    elif mental_model_strength < 62:
        mental_model_label = "MIXED / FUNDAMENTAL-UNIDENTIFIED"
    mental_model_score = clip_score(mental_model_strength)

    raw_scores = {
        "attention": attention,
        "salience": salience,
        "memory": memory_score,
        "experience": experience_score,
        "information_processing": information_processing,
        "extrapolation": extrapolation,
        "mental_model": mental_model_score,
        "confidence": confidence,
        "disagreement": disagreement,
        "higher_order": higher_order,
        "ambiguity": ambiguity,
        "fear": fear,
        "risk_appetite": risk_appetite,
        "lottery_demand": lottery_demand,
        "narrative": narrative,
        "herding": herding,
        "social_contagion": social_contagion,
        "reflexivity": reflexivity,
        "mechanical_reflexivity": mechanical_reflexivity,
        "arbitrage_capacity": arbitrage_capacity,
    }

    # Data-dependent confidence. Higher-order/social/reflexive claims stay capped.
    price_conf = 90 if len(target) >= 252 else 72 if len(target) >= 126 else 55
    # Text confidence now follows semantic validity / belief reliability rather than
    # technical corpus availability alone. A perfectly fetched but poorly labelled
    # corpus must not receive near-institutional confidence.
    text_conf = min(90, news.get("nlp_evidence_score", news.get("corpus_quality", 0.0))) if news.get("count", 0) else 18
    option_conf = min(85, 35 + option_rows / 40) if options.get("available") else 15
    cross_conf = 85 if panel.shape[1] >= 5 and len(panel.dropna(how="all")) >= 126 else 55
    vol_conf = 88 if vol_tail.get("coverage", 0) >= 3 else 65 if vol_tail.get("available") else 20
    breadth_conf = 82 if breadth_layer.get("coverage", 0) >= 7 else 62 if breadth_layer.get("available") else 20
    funding_conf = 88 if funding_layer.get("coverage", 0) >= 5 else 65 if funding_layer.get("available") else 20
    positioning_conf = 78 if positioning_layer.get("available") else 18
    option_behavior_conf = 80 if option_behavior_layer.get("available") and option_rows >= 100 else option_conf

    conf_map = {
        "attention": 0.65 * price_conf + 0.35 * text_conf,
        "salience": price_conf,
        "memory": min(80, price_conf - 5),
        "experience": 5.0,
        "information_processing": min(68, text_conf),
        "extrapolation": price_conf,
        "mental_model": min(60, 0.55 * price_conf + 0.45 * text_conf),
        "confidence": min(70, 0.5 * cross_conf + 0.5 * price_conf),
        "disagreement": min(86, 0.40 * cross_conf + 0.25 * text_conf + 0.20 * option_behavior_conf + 0.15 * positioning_conf),
        "higher_order": min(60, 0.28 * text_conf + 0.27 * option_behavior_conf + 0.22 * cross_conf + 0.23 * positioning_conf),
        "ambiguity": min(86, 0.34 * cross_conf + 0.31 * text_conf + 0.35 * vol_conf),
        "fear": min(92, 0.30 * price_conf + 0.18 * text_conf + 0.22 * option_behavior_conf + 0.30 * vol_conf),
        "risk_appetite": min(90, 0.52 * cross_conf + 0.48 * breadth_conf),
        "lottery_demand": min(88, 0.72 * option_behavior_conf + 0.28 * price_conf),
        "narrative": text_conf,
        "herding": min(90, 0.50 * cross_conf + 0.28 * breadth_conf + 0.22 * positioning_conf),
        "social_contagion": min(50, 0.45 * cross_conf + 0.55 * text_conf),
        "reflexivity": min(76, 0.48 * price_conf + 0.20 * option_behavior_conf + 0.17 * cross_conf + 0.15 * breadth_conf),
        "mechanical_reflexivity": min(74, 0.28 * price_conf + 0.42 * option_behavior_conf + 0.30 * vol_conf),
        "arbitrage_capacity": min(82, 0.30 * cross_conf + 0.70 * funding_conf),
    }

    evidence_map = {
        "attention": f"Return z {ret_z or 0:+.2f} · volume z {volume_z or 0:+.2f} · {news['count']} news items.",
        "salience": f"|return z| {abs(ret_z or 0):.2f} · range z {range_z or 0:+.2f} · 5D {perf5 or 0:+.1%}.",
        "memory": memory_evidence,
        "experience": "No investor-cohort or account-level experience panel is connected; score deliberately left unobserved/neutral.",
        "information_processing": f"Story compression {news.get('story_compression',0):.0%} · exact/ultra-near dedup removed {news.get('dedup_removed',0)} · resolved narrative coverage {news.get('resolved_coverage',0):.0f}% · semantic validity {news.get('semantic_validity_score',0):.0f}/100.",
        "extrapolation": f"20D {perf20 or 0:+.1%} · 60D {perf60 or 0:+.1%} · return autocorr {autocorr:+.2f}.",
        "mental_model": f"Dominant observable model: {mental_model_label}.",
        "confidence": f"Calibrated belief confidence {news.get('belief_confidence_mean',0):.0f}/100 · belief extraction quality {news.get('belief_extraction_quality',0):.0f}/100 · disagreement {disagreement:.0f}/100 · trend coherence {trend_coherence:.0f}/100.",
        "disagreement": f"Belief disagreement {news.get('belief_disagreement',50):.0f}/100 · cross-asset 20D dispersion {dispersion:.2%} · sentiment dispersion {news['sentiment_std']:.2f} · put/call {put_call_vol if put_call_vol is not None else 'N/A'} · CFTC leveraged-money pctile {lev_money_percentile if lev_money_percentile is not None else 'N/A'}.",
        "higher_order": f"Composite proxy from attention {attention:.0f}, extrapolation {extrapolation:.0f}, calls/lottery {lottery_demand:.0f}, herding {herding:.0f}.",
        "ambiguity": f"VIX {vix_level if vix_level is not None else 'N/A'} · VVIX {vol_metrics.get('vvix','N/A')} · SKEW {vol_metrics.get('skew','N/A')} · term slope {vol_metrics.get('term_slope','N/A')} · uncertainty-language share {news['uncertainty_share']:.0%}.",
        "fear": f"VIX {vix_level if vix_level is not None else 'N/A'} · VIX9D {vol_metrics.get('vix9d','N/A')} · VVIX {vol_metrics.get('vvix','N/A')} · tail-state {tail_stress_score if tail_stress_score is not None else 'N/A'} · option-tail {option_tail_score if option_tail_score is not None else 'N/A'} · negative news {news['negative_share']:.0%}.",
        "risk_appetite": f"IWM-SPY 20D {smallcap_rel:+.1%} · HYG-TLT 20D {credit_rel:+.1%} · equal-weight breadth {breadth_metrics.get('equal_weight_rel_20d','N/A')} · sector participation {breadth_metrics.get('sector_positive_share_20d','N/A')}.",
        "lottery_demand": f"Call share {call_share if call_share is not None else 'N/A'} · ≤7D option share {option_behavior.get('dte_7_share','N/A')} · OTM call-volume share {option_behavior.get('otm_call_volume_share','N/A')} · option-lottery score {option_lottery_score if option_lottery_score is not None else 'N/A'}.",
        "narrative": f"Dominant resolved narrative {news.get('dominant_narrative','N/A')} · lifecycle {news.get('dominant_lifecycle','N/A')} · concentration {news['theme_concentration']:.0%} · label confidence {news.get('label_confidence_score',0):.0f}/100 · resolved coverage {news.get('resolved_coverage',0):.0f}% · {news['count']} documents / {news.get('story_count',news['count'])} stories.",
        "herding": f"Average cross-asset correlation {avg_corr:+.2f} · sign synchronization {sign_sync:.0%} · breadth {breadth_score if breadth_score is not None else 'N/A'} · CFTC crowding {positioning_crowding if positioning_crowding is not None else 'N/A'}.",
        "social_contagion": "Proxy combining attention, synchronization and narrative concentration; no investor-level social graph is observed.",
        "reflexivity": f"Attention {attention:.0f} · extrapolation {extrapolation:.0f} · autocorr {autocorr:+.2f} · |return-volume corr| {ret_volume_corr:.2f}.",
        "mechanical_reflexivity": f"VIX z {vix_z or 0:+.2f} · ≤7D options {option_behavior.get('dte_7_share','N/A')} · top-5-strike OI share {option_behavior.get('oi_top5_strike_share','N/A')} · convexity concentration {option_concentration_score if option_concentration_score is not None else 'N/A'}. Signed dealer gamma is not inferred.",
        "arbitrage_capacity": f"Funding/credit stress {funding_stress_score if funding_stress_score is not None else 'N/A'} · HY OAS {funding_metrics.get('hy_oas','N/A')} · NFCI risk {funding_metrics.get('nfci_risk','N/A')} · market-liquidity proxies. Borrow/dealer balance-sheet capacity remains unobserved.",
    }

    identification_map = {
        "experience": "UNOBSERVED — experience effects require investor/cohort histories; V1 refuses to infer them from aggregate prices.",
        "information_processing": "LOW/MEDIUM — repeated/correlated information is observable, but correlation neglect by investors is not directly observed.",
        "higher_order": "LOW IDENTIFICATION — true second-order beliefs require surveys/text/positioning that distinguish self-belief from expected crowd belief.",
        "social_contagion": "LOW IDENTIFICATION — no account-level diffusion network; current score is a market-level synchronization proxy.",
        "mechanical_reflexivity": "MEDIUM — V2.2 observes volatility structure and option concentration, but signed dealer gamma, margin books and systematic strategy flows are still not directly observed.",
        "arbitrage_capacity": "MEDIUM — public credit/financial-condition stress is directly observed; securities borrow and institution-specific balance-sheet capacity still require dedicated feeds.",
        "mental_model": "LOW/MEDIUM — categorical inference from observable footprints, not a direct survey of investor reasoning.",
        "memory": "MEDIUM — analogue retrieval is measurable, but actual investor memory is not directly observed.",
        "confidence": "MEDIUM — inferred from coherence/dispersion, not direct subjective-confidence surveys.",
    }

    # ------------------------------------------------------------
    # V2.0.1 calibrated latent-state layer
    # ------------------------------------------------------------
    raw_state_history = _historical_state_series(target, pack)
    # Point-in-time integrity rule: V2.2 snapshot-only data must not create a false
    # historical innovation. The five latent mechanisms receive only proxies whose
    # historical construction is already present in raw_state_history. Richer V2.2
    # observations remain visible as separate observed overlays until archived.
    latent_input_scores = dict(raw_scores)
    latent_input_scores["fear"] = fear_base
    latent_input_scores["herding"] = herding_market
    latent_input_scores["reflexivity"] = reflexivity_historical_compatible
    latent_bundle = build_latent_state_bundle(raw_state_history, latent_input_scores, conf_map)
    state_history = latent_bundle.get("history", pd.DataFrame())
    latent_table = latent_bundle.get("current_table", pd.DataFrame())
    operational_scores = dict(latent_bundle.get("operational_scores", raw_scores))

    # ------------------------------------------------------------
    # V2.3.1 Behavioral Memory — temporal/retrieval calibrated associative retrieval
    # ------------------------------------------------------------
    memory_bundle = build_behavioral_memory(
        symbol=symbol,
        target=target,
        latent_history=state_history,
        behavioral_data=bdata,
        news=news,
        scores=operational_scores,
        top_n=8,
    )
    if isinstance(memory_bundle, dict) and memory_bundle.get("available"):
        analogues = memory_bundle.get("analogues", pd.DataFrame())
        memory_score = clip_score(memory_bundle.get("memory_activation_score", 50.0))
        raw_scores["memory"] = memory_score
        operational_scores["memory"] = memory_score
        best_sim = safe_float(memory_bundle.get("best_similarity"), 0.0) or 0.0
        structural_n = int(len(memory_bundle.get("structural_analogues", pd.DataFrame()))) if isinstance(memory_bundle.get("structural_analogues", pd.DataFrame()), pd.DataFrame) else 0
        memory_candidate_n = int(len(memory_bundle.get("memory_candidates", pd.DataFrame()))) if isinstance(memory_bundle.get("memory_candidates", pd.DataFrame()), pd.DataFrame) else 0
        if memory_bundle.get("no_structural_analogue", memory_bundle.get("no_reliable_analogue")):
            memory_evidence = (
                f"No structural observed-domain analogue clears adaptive similarity {memory_bundle.get('similarity_threshold', 65):.0f}/100, "
                f"activation {memory_bundle.get('activation_threshold',55):.0f}/100 and coverage {100*memory_bundle.get('min_coverage',.60):.0f}%; "
                f"nearest state {best_sim:.1f}/100 · activation {memory_score:.1f}/100. "
                "Narrative/options history is archive-only and is never backfilled."
            )
        else:
            memory_evidence = (
                f"{structural_n} structural observed-domain analogue(s), {memory_candidate_n} memory candidate(s) · "
                f"best similarity {best_sim:.1f}/100 · activation {memory_score:.1f}/100 · "
                f"usable historical domains {memory_bundle.get('historically_usable_domains',0)}/{memory_bundle.get('domain_total',8)}."
            )
        memory_archive = memory_bundle.get("archive", {}) if isinstance(memory_bundle.get("archive", {}), dict) else {}
        archive_n = int(memory_archive.get("snapshots", 0) or 0)
        memory_conf = min(88.0, 42.0 + 0.34 * float(memory_bundle.get("historical_domain_coverage", 0.0)) + min(12.0, archive_n * 0.8))
        if memory_bundle.get("no_reliable_analogue"):
            memory_conf *= 0.88
        conf_map["memory"] = memory_conf
        evidence_map["memory"] = memory_evidence
    else:
        memory_bundle = memory_bundle if isinstance(memory_bundle, dict) else {"available": False}
        raw_scores["memory"] = 35.0
        operational_scores["memory"] = 35.0
        conf_map["memory"] = min(conf_map.get("memory", 50.0), 35.0)
        evidence_map["memory"] = str(memory_bundle.get("reason", "Behavioral-memory retrieval unavailable."))

    # Recompute the current observable mental-model proxy using filtered states where available.
    model_candidates_v2 = {
        "EXTRAPOLATIVE / MOMENTUM": operational_scores.get("extrapolation", extrapolation),
        "NARRATIVE-DRIVEN": operational_scores.get("narrative", narrative),
        "FLOW / RISK-ON": operational_scores.get("risk_appetite", risk_appetite),
        "TAIL-RISK / DEFENSIVE": operational_scores.get("fear", fear),
        "REFLEXIVE": operational_scores.get("reflexivity", reflexivity),
    }
    mental_model_label, mental_model_strength = max(model_candidates_v2.items(), key=lambda kv: kv[1])
    nlp_mental_model = str(news.get("dominant_mental_model", "MIXED / UNIDENTIFIED"))
    if mental_model_strength < 62 and nlp_mental_model not in {"", "MIXED / UNIDENTIFIED"}:
        mental_model_label = nlp_mental_model
        mental_model_strength = max(55.0, operational_scores.get("narrative", narrative))
    elif mental_model_strength < 62:
        mental_model_label = "MIXED / FUNDAMENTAL-UNIDENTIFIED"
    operational_scores["mental_model"] = clip_score(mental_model_strength)

    # Map raw and latent estimates into the mechanism table without hiding measurement uncertainty.
    latent_lookup = {}
    if isinstance(latent_table, pd.DataFrame) and not latent_table.empty:
        latent_lookup = {str(r.get("Key")): r.to_dict() for _, r in latent_table.iterrows()}

    mechanisms: list[MechanismResult] = []
    for spec in MECHANISM_SPECS:
        score = operational_scores.get(spec.key, raw_scores.get(spec.key, 50.0))
        evidence = evidence_map.get(spec.key, "")
        if spec.key in latent_lookup:
            lr = latent_lookup[spec.key]
            evidence += (
                f" · raw {safe_float(lr.get('Raw observation'), score):.1f}"
                f" -> normalized {safe_float(lr.get('Normalized observation'), score):.1f}"
                f" -> latent {safe_float(lr.get('Latent state'), score):.1f}"
                f" · structural {lr.get('Structural state', 'N/A')}"
                f" · acute {lr.get('Acute alarm', 'N/A')}"
                f" · {lr.get('Shock direction', 'N/A')}"
                f" · pct {safe_float(lr.get('Percentile'), np.nan):.0f} · shock z {safe_float(lr.get('Shock z'), 0.0):+.2f}."
            )
        mechanisms.append(MechanismResult(
            key=spec.key,
            label=spec.label,
            layer=spec.layer,
            score=round(score, 1),
            confidence=round(clip_score(conf_map.get(spec.key, 50)), 1),
            status="UNOBSERVED" if spec.key == "experience" else score_label(score),
            description=spec.description,
            evidence=evidence,
            identification=identification_map.get(spec.key, "MEDIUM/HIGH — inference still depends on proxy assumptions and should be validated out-of-sample."),
        ))

    regime, regime_reason = _regime_from_scores(operational_scores)
    overall_confidence = float(np.average(
        [m.confidence for m in mechanisms],
        weights=[1.0 if m.layer != "Constraints" else 0.7 for m in mechanisms],
    ))

    # Evidence quality is deliberately not described as a calibrated probability.
    direct_penalty = 0.82  # no direct survey/social/dealer-state observations yet
    evidence_quality_score = float(np.clip(overall_confidence * direct_penalty, 0, 100))
    evidence_quality_label = (
        "HIGH" if evidence_quality_score >= 75
        else "MEDIUM" if evidence_quality_score >= 50
        else "LOW"
    )

    # Layer scores remain visible as summaries but never collapse the full state into one psychology score.
    layer_rows = []
    for layer in ["Cognition", "Beliefs", "Preference / affect", "Social / reflexive", "Constraints"]:
        ms = [m for m in mechanisms if m.layer == layer]
        if ms:
            layer_rows.append({
                "Layer": layer,
                "State": round(float(np.mean([m.score for m in ms])), 1),
                "Confidence": round(float(np.mean([m.confidence for m in ms])), 1),
                "Mechanisms": len(ms),
            })

    alert_board = build_behavioral_alerts(operational_scores, state_history, latent_table)
    scenario_monitor = build_scenario_monitor(operational_scores, {
        "perf_20d": perf20,
        "vol_20d": vol20,
        "drawdown": dd,
    }, latent_table=latent_table, history=state_history)
    alarm_evolution = build_alarm_evolution(state_history, window=120)
    historical_alarm_events = build_historical_alarm_events(state_history, max_events=16)


    return {
        "available": True,
        "symbol": symbol,
        "regime": regime,
        "regime_reason": regime_reason,
        "overall_confidence": round(overall_confidence, 1),
        "evidence_quality_score": round(evidence_quality_score, 1),
        "evidence_quality_label": evidence_quality_label,
        "latent_coverage": int(latent_bundle.get("coverage", 0)),
        "latent_stability": round(100.0 * float(latent_bundle.get("stability", np.nan)), 1) if np.isfinite(latent_bundle.get("stability", np.nan)) else np.nan,
        "scores": operational_scores,
        "scores_raw": raw_scores,
        "latent_state": latent_table,
        "raw_history": raw_state_history,
        "mechanisms": mechanisms,
        "mechanism_table": pd.DataFrame([m.__dict__ for m in mechanisms]),
        "layers": pd.DataFrame(layer_rows),
        "news": news,
        "options": options,
        "behavioral_data": bdata,
        "memory": memory_bundle,
        "analogues": analogues,
        "history": state_history,
        "target_history": target.copy(),
        "alerts": alert_board,
        "scenarios": scenario_monitor,
        "alarm_evolution": alarm_evolution,
        "historical_alarm_events": historical_alarm_events,
        "mental_model": mental_model_label,
        "diagnostics": {
            "rows": int(len(target)),
            "news_count": int(news["count"]),
            "news_raw_count": int(news.get("raw_count", news["count"])),
            "news_dedup_removed": int(news.get("dedup_removed", 0)),
            "news_providers": int(news.get("provider_count", 0)),
            "news_sources": int(news.get("source_count", 0)),
            "news_corpus_quality": round(float(news.get("corpus_quality", 0.0)), 1),
            "news_nlp_evidence": round(float(news.get("nlp_evidence_score", 0.0)), 1),
            "news_semantic_validity": round(float(news.get("semantic_validity_score", 0.0)), 1),
            "news_cluster_separation": round(float(news.get("cluster_separation_score", 0.0)), 1),
            "news_cluster_cohesion": round(float(news.get("cluster_cohesion_score", 0.0)), 1),
            "news_label_confidence": round(float(news.get("label_confidence_score", 0.0)), 1),
            "news_resolved_coverage": round(float(news.get("resolved_coverage", 0.0)), 1),
            "news_belief_quality": round(float(news.get("belief_extraction_quality", 0.0)), 1),
            "news_story_count": int(news.get("story_count", news.get("count", 0))),
            "news_duplicate_story_docs": int(news.get("duplicate_story_docs", 0)),
            "nlp_backend": str(news.get("backend", "N/A")),
            "dominant_narrative": str(news.get("dominant_narrative", "N/A")),
            "dominant_lifecycle": str(news.get("dominant_lifecycle", "N/A")),
            "option_rows": option_rows,
            "cross_asset_columns": int(panel.shape[1]),
            "behavioral_data_coverage": round(float(bdata.get("coverage_score", 0.0)), 1) if isinstance(bdata, dict) else 0.0,
            "behavioral_data_availability": round(float(bdata.get("availability_score", bdata.get("coverage_score", 0.0))), 1) if isinstance(bdata, dict) else 0.0,
            "behavioral_data_freshness": round(float(bdata.get("freshness_score", 0.0)), 1) if isinstance(bdata, dict) else 0.0,
            "behavioral_data_identification": round(float(bdata.get("identification_score", 0.0)), 1) if isinstance(bdata, dict) else 0.0,
            "behavioral_data_evidence": round(float(bdata.get("evidence_score", 0.0)), 1) if isinstance(bdata, dict) else 0.0,
            "volatility_tail_available": bool(vol_tail.get("available")),
            "volatility_tail_coverage": int(vol_tail.get("coverage", 0) or 0),
            "breadth_available": bool(breadth_layer.get("available")),
            "breadth_coverage": int(breadth_layer.get("coverage", 0) or 0),
            "breadth_core_coverage": int(breadth_layer.get("core_coverage", 0) or 0),
            "breadth_sector_coverage": int(breadth_layer.get("sector_coverage", 0) or 0),
            "funding_credit_available": bool(funding_layer.get("available")),
            "funding_credit_coverage": int(funding_layer.get("coverage", 0) or 0),
            "positioning_available": bool(positioning_layer.get("available")),
            "options_behavior_available": bool(option_behavior_layer.get("available")),
            "short_interest_available": bool((bdata.get("short_interest", {}) if isinstance(bdata, dict) else {}).get("available")),
            "vix_available": (safe_float(vol_metrics.get("vix")) is not None) or (not vix.empty),
            "vix_level": vix_level,
            "vvix_level": safe_float(vol_metrics.get("vvix")),
            "vix9d_level": safe_float(vol_metrics.get("vix9d")),
            "vix3m_level": safe_float(vol_metrics.get("vix3m")),
            "skew_level": safe_float(vol_metrics.get("skew")),
            "tail_stress_score": tail_stress_score,
            "breadth_score": breadth_score,
            "funding_stress_score": funding_stress_score,
            "positioning_crowding_score": positioning_crowding,
            "perf_20d": perf20,
            "vol_20d": vol20,
            "drawdown": dd,
            "price_provider": str(target.attrs.get("provider", "Unknown")),
            "price_provider_attempts": list(target.attrs.get("provider_attempts", [])),
            "latent_mechanisms": int(latent_bundle.get("coverage", 0)),
            "latent_stability": round(100.0 * float(latent_bundle.get("stability", np.nan)), 1) if np.isfinite(latent_bundle.get("stability", np.nan)) else np.nan,
            "memory_available": bool(memory_bundle.get("available")) if isinstance(memory_bundle, dict) else False,
            "memory_best_similarity": safe_float(memory_bundle.get("best_similarity")) if isinstance(memory_bundle, dict) else None,
            "memory_activation": safe_float(memory_bundle.get("memory_activation_score")) if isinstance(memory_bundle, dict) else None,
            "memory_reliable_count": int(len(memory_bundle.get("structural_analogues", memory_bundle.get("reliable_analogues", pd.DataFrame())))) if isinstance(memory_bundle, dict) and isinstance(memory_bundle.get("structural_analogues", memory_bundle.get("reliable_analogues", pd.DataFrame())), pd.DataFrame) else 0,
            "memory_structural_count": int(len(memory_bundle.get("structural_analogues", pd.DataFrame()))) if isinstance(memory_bundle, dict) and isinstance(memory_bundle.get("structural_analogues", pd.DataFrame()), pd.DataFrame) else 0,
            "memory_candidate_count": int(len(memory_bundle.get("memory_candidates", pd.DataFrame()))) if isinstance(memory_bundle, dict) and isinstance(memory_bundle.get("memory_candidates", pd.DataFrame()), pd.DataFrame) else 0,
            "memory_usable_domains": int(memory_bundle.get("historically_usable_domains",0)) if isinstance(memory_bundle, dict) else 0,
            "memory_domain_total": int(memory_bundle.get("domain_total",8)) if isinstance(memory_bundle, dict) else 8,
            "memory_domain_coverage": safe_float(memory_bundle.get("historical_domain_coverage")) if isinstance(memory_bundle, dict) else None,
            "memory_archive_snapshots": int((memory_bundle.get("archive", {}) or {}).get("snapshots", 0)) if isinstance(memory_bundle, dict) else 0,
            "state_model": "Causal robust normalization + one-sided adaptive local-level Kalman filter",
        },
    }
