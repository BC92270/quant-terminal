# ============================================================
# DECISION ENGINE V2 — STANDALONE MODULE
# ============================================================
# Objectif :
# - Séparer la qualité du dossier de la qualité d'exécution.
# - Éviter les signaux ambigus type BUY_RISKY quand le prix impose d'attendre.
# - Ne dépendre d'aucune fonction de app.py pour éviter les imports circulaires.
# - Lire uniquement ticker, price_data, analysis.
#
# Intégration app.py :
# from decision_engine import render_decision_engine_v2
#
# Puis :
# def render_decision_engine_mode(ticker, price_data, analysis):
#     render_decision_engine_v2(ticker=ticker, price_data=price_data, analysis=analysis)
# ============================================================

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# SAFE HELPERS
# ============================================================

def safe_float(value, default=None):
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value, default=None):
    try:
        if value is None:
            return default
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def first_numeric(*values, default=None):
    for value in values:
        parsed = safe_float(value)
        if parsed is not None:
            return parsed
    return default


def clamp(value, low=0, high=100):
    value = safe_float(value, low)
    if value is None:
        return low
    return max(low, min(high, value))


def fmt_price(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_pct(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def fmt_score(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.0f}/100"


def fmt_num(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_pp(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value * 100:.2f} pts"


def dict_get(d: dict, path: list[str], default=None):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return cur if cur is not None else default


def dataframe_has_columns(df: pd.DataFrame, cols: list[str]) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty and all(c in df.columns for c in cols)


# ============================================================
# CORE EXTRACTION
# ============================================================

def get_last_price_from_frame(price_data: pd.DataFrame):
    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return None

    df = price_data.copy()
    df.columns = [str(c).lower() for c in df.columns]

    if "close" not in df.columns:
        return None

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if close.empty:
        return None

    return float(close.iloc[-1])


def get_company_scores(analysis: dict) -> dict:
    company = analysis.get("company_analysis", {}) if isinstance(analysis, dict) else {}
    scores = company.get("scores", {}) if isinstance(company, dict) else {}

    return {
        "company_score": first_numeric(scores.get("company_score"), default=50),
        "growth_score": first_numeric(scores.get("growth_score"), default=50),
        "profitability_score": first_numeric(scores.get("profitability_score"), default=50),
        "balance_score": first_numeric(scores.get("balance_score"), default=50),
        "valuation_score": first_numeric(scores.get("valuation_score"), default=50),
        "forward_score": first_numeric(scores.get("forward_score"), default=50),
        "estimate_surprise_score": first_numeric(scores.get("estimate_surprise_score"), default=50),
        "analyst_score": first_numeric(scores.get("analyst_score"), default=50),
        "sentiment_score": first_numeric(scores.get("sentiment_score"), default=50),
    }


def get_momentum_latest(analysis: dict) -> dict:
    mt = analysis.get("momentum_v2", {}) if isinstance(analysis, dict) else {}
    latest = mt.get("latest", {}) if isinstance(mt, dict) else {}

    return {
        "trend_score": first_numeric(latest.get("trend_score"), analysis.get("trend_score"), default=50),
        "momentum_score": first_numeric(latest.get("momentum_score"), default=50),
        "noise_risk": first_numeric(latest.get("noise_risk"), default=50),
        "timing_score": first_numeric(latest.get("timing_score"), default=50),
        "setup_score": first_numeric(latest.get("composite_score"), default=50),
        "relative_strength_score": first_numeric(latest.get("relative_strength_score"), default=50),
        "breakout_quality_score": first_numeric(latest.get("breakout_quality_score"), default=50),
        "pullback_quality_score": first_numeric(latest.get("pullback_quality_score"), default=50),
        "exhaustion_risk_score": first_numeric(latest.get("exhaustion_risk_score"), default=50),
        "entry_timing_quality_score": first_numeric(latest.get("entry_timing_quality_score"), default=50),
        "price_vs_ema20": first_numeric(latest.get("price_vs_ema20"), default=None),
        "atr_pct": first_numeric(latest.get("atr_pct"), default=None),
        "volume_zscore": first_numeric(latest.get("volume_zscore"), default=None),
        "trend_regime": latest.get("trend_regime", "N/A"),
        "execution_status": latest.get("execution_status", "N/A"),
    }


def get_trading_plan(analysis: dict, price: float) -> dict:
    plan = analysis.get("trading_plan", {}) if isinstance(analysis, dict) else {}
    atr = first_numeric(analysis.get("atr"), default=None)

    if atr is None or atr <= 0:
        atr = price * 0.02 if price and price > 0 else 1.0

    entry_aggressive = first_numeric(
        plan.get("entry_aggressive"),
        plan.get("entry_price"),
        price - 0.50 * atr,
    )
    entry_prudent = first_numeric(
        plan.get("entry_prudent"),
        price - 1.00 * atr,
    )
    stop_short = first_numeric(
        plan.get("stop_short"),
        plan.get("stop_loss"),
        price - 1.50 * atr,
    )
    stop_structural = first_numeric(
        plan.get("stop_structural"),
        price - 2.50 * atr,
    )
    target_1 = first_numeric(
        plan.get("target_1"),
        plan.get("take_profit"),
        price + 1.50 * atr,
    )
    target_2 = first_numeric(
        plan.get("target_2"),
        price + 3.00 * atr,
    )

    zone_low = min(entry_prudent, entry_aggressive)
    zone_high = max(entry_prudent, entry_aggressive)

    return {
        "atr": atr,
        "entry_aggressive": entry_aggressive,
        "entry_prudent": entry_prudent,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "stop_short": stop_short,
        "stop_structural": stop_structural,
        "target_1": target_1,
        "target_2": target_2,
    }


def select_mc_row(analysis: dict, horizon: int) -> tuple[pd.Series | dict, pd.DataFrame]:
    mc_table = analysis.get("mc_advanced_table", pd.DataFrame()) if isinstance(analysis, dict) else pd.DataFrame()

    if not isinstance(mc_table, pd.DataFrame) or mc_table.empty:
        return {}, pd.DataFrame()

    table = mc_table.copy()

    if "Horizon" not in table.columns:
        return {}, table

    horizon_label = f"{horizon}D"
    match = table[table["Horizon"].astype(str) == horizon_label]

    if match.empty:
        return table.iloc[0], table

    return match.iloc[0], table


def mc_value(mc_row, key: str, default=None):
    try:
        if isinstance(mc_row, pd.Series):
            return safe_float(mc_row.get(key), default)
        if isinstance(mc_row, dict):
            return safe_float(mc_row.get(key), default)
        return default
    except Exception:
        return default


# ============================================================
# SCORING
# ============================================================

def score_thesis_quality(company_scores: dict) -> float:
    score = (
        0.30 * company_scores["company_score"]
        + 0.15 * company_scores["growth_score"]
        + 0.15 * company_scores["profitability_score"]
        + 0.15 * company_scores["valuation_score"]
        + 0.15 * company_scores["forward_score"]
        + 0.10 * company_scores["analyst_score"]
    )
    return clamp(score)


def score_technical_quality(momentum: dict) -> float:
    score = (
        0.25 * momentum["trend_score"]
        + 0.18 * momentum["momentum_score"]
        + 0.15 * momentum["timing_score"]
        + 0.12 * momentum["relative_strength_score"]
        + 0.10 * momentum["breakout_quality_score"]
        + 0.10 * momentum["entry_timing_quality_score"]
        + 0.10 * (100 - momentum["noise_risk"])
    )

    exhaustion = momentum.get("exhaustion_risk_score", 50)
    if exhaustion >= 75:
        score -= 8
    elif exhaustion >= 65:
        score -= 4

    return clamp(score)


def score_statistical_edge(mc: dict) -> float:
    mc_score = first_numeric(mc.get("mc_score"), default=50)
    expected_return = first_numeric(mc.get("expected_return"), default=0)
    asymmetry = first_numeric(mc.get("asymmetry"), default=0)
    stop_prob = first_numeric(mc.get("stop_prob"), default=0.50)
    target_prob = first_numeric(mc.get("target1_prob"), default=0.50)

    score = mc_score

    if expected_return > 0.03:
        score += 8
    elif expected_return > 0:
        score += 4
    elif expected_return <= 0:
        score -= 12

    if asymmetry > 0.20:
        score += 10
    elif asymmetry > 0.05:
        score += 5
    elif asymmetry < 0:
        score -= 12

    if stop_prob >= 0.55:
        score -= 12
    elif stop_prob >= 0.45:
        score -= 6
    elif stop_prob <= 0.35:
        score += 8

    if target_prob >= 0.65:
        score += 6
    elif target_prob < 0.45:
        score -= 6

    return clamp(score)


def get_price_position(price: float, plan: dict) -> tuple[str, str]:
    zone_low = plan["zone_low"]
    zone_high = plan["zone_high"]
    stop_short = plan["stop_short"]

    if price <= stop_short:
        return "INVALIDATED", "Sous stop court"
    if zone_low <= price <= zone_high:
        return "IN_ZONE", "Dans la zone"
    if price > zone_high:
        return "ABOVE_ZONE", "Au-dessus de la zone"
    return "BELOW_ZONE", "Sous la zone"


def calculate_distances(price: float, plan: dict) -> dict:
    stop_short = plan["stop_short"]
    stop_structural = plan["stop_structural"]
    target_1 = plan["target_1"]
    target_2 = plan["target_2"]
    zone_low = plan["zone_low"]
    zone_high = plan["zone_high"]

    distance_stop_short = stop_short / price - 1 if price else None
    distance_stop_structural = stop_structural / price - 1 if price else None
    distance_target_1 = target_1 / price - 1 if price else None
    distance_target_2 = target_2 / price - 1 if price else None

    rr_t1 = None
    if distance_stop_short is not None and distance_stop_short < 0 and distance_target_1 is not None:
        rr_t1 = distance_target_1 / abs(distance_stop_short)

    if price > zone_high:
        distance_to_zone = zone_high / price - 1
    elif price < zone_low:
        distance_to_zone = zone_low / price - 1
    else:
        distance_to_zone = 0.0

    return {
        "distance_stop_short": distance_stop_short,
        "distance_stop_structural": distance_stop_structural,
        "distance_target_1": distance_target_1,
        "distance_target_2": distance_target_2,
        "rr_t1": rr_t1,
        "distance_to_zone": distance_to_zone,
    }


def score_execution_quality(price: float, plan: dict, distances: dict, mc: dict, momentum: dict) -> float:
    position_key, _ = get_price_position(price, plan)

    score = 50

    if position_key == "IN_ZONE":
        score += 25
    elif position_key == "ABOVE_ZONE":
        score -= 10
    elif position_key == "BELOW_ZONE":
        score -= 5
    elif position_key == "INVALIDATED":
        score -= 45

    rr_t1 = distances.get("rr_t1")
    if rr_t1 is not None:
        if rr_t1 >= 2:
            score += 18
        elif rr_t1 >= 1.3:
            score += 10
        elif rr_t1 >= 1:
            score += 2
        else:
            score -= 10

    stop_prob = mc.get("stop_prob")
    if stop_prob is not None:
        if stop_prob >= 0.55:
            score -= 18
        elif stop_prob >= 0.45:
            score -= 10
        elif stop_prob <= 0.35:
            score += 10

    entry_timing = momentum.get("entry_timing_quality_score", 50)
    score += clamp((entry_timing - 50) * 0.25, -10, 10)

    exhaustion = momentum.get("exhaustion_risk_score", 50)
    if exhaustion >= 75:
        score -= 12
    elif exhaustion >= 65:
        score -= 6

    return clamp(score)


def score_data_confidence(analysis: dict, price_data: pd.DataFrame, mc_table: pd.DataFrame) -> float:
    score = 35

    if isinstance(price_data, pd.DataFrame) and len(price_data) >= 120:
        score += 20
    elif isinstance(price_data, pd.DataFrame) and len(price_data) >= 60:
        score += 10

    if isinstance(mc_table, pd.DataFrame) and not mc_table.empty:
        score += 20

    if isinstance(analysis.get("trading_plan"), dict) and analysis.get("trading_plan"):
        score += 15

    if isinstance(analysis.get("company_analysis"), dict) and analysis.get("company_analysis"):
        score += 15

    if isinstance(analysis.get("momentum_v2"), dict) and analysis.get("momentum_v2"):
        score += 15

    return clamp(score)


def calculate_mc_robustness_v2(mc_table: pd.DataFrame) -> dict:
    if not isinstance(mc_table, pd.DataFrame) or mc_table.empty:
        return {
            "score": 50,
            "label": "Indisponible",
            "worst_mc_score": None,
            "median_mc_score": None,
            "worst_expected_return": None,
            "max_stop_prob": None,
            "table": pd.DataFrame(),
        }

    df = mc_table.copy()

    for col in ["MC Score", "Expected Return", "Prob toucher stop court", "Asymétrie T1/Stop"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    mc_scores = df["MC Score"].dropna() if "MC Score" in df.columns else pd.Series(dtype=float)
    expected = df["Expected Return"].dropna() if "Expected Return" in df.columns else pd.Series(dtype=float)
    stop_prob = df["Prob toucher stop court"].dropna() if "Prob toucher stop court" in df.columns else pd.Series(dtype=float)
    asym = df["Asymétrie T1/Stop"].dropna() if "Asymétrie T1/Stop" in df.columns else pd.Series(dtype=float)

    worst_mc = float(mc_scores.min()) if not mc_scores.empty else None
    median_mc = float(mc_scores.median()) if not mc_scores.empty else None
    worst_expected = float(expected.min()) if not expected.empty else None
    max_stop = float(stop_prob.max()) if not stop_prob.empty else None
    min_asym = float(asym.min()) if not asym.empty else None

    score = median_mc if median_mc is not None else 50

    if worst_mc is not None:
        if worst_mc < 40:
            score -= 18
        elif worst_mc < 55:
            score -= 8
        elif worst_mc >= 70:
            score += 5

    if worst_expected is not None:
        if worst_expected <= 0:
            score -= 12
        elif worst_expected > 0.03:
            score += 5

    if max_stop is not None:
        if max_stop >= 0.55:
            score -= 12
        elif max_stop <= 0.35:
            score += 6

    if min_asym is not None:
        if min_asym < 0:
            score -= 8
        elif min_asym > 0.10:
            score += 4

    score = clamp(score)

    if score >= 75:
        label = "Robuste"
    elif score >= 60:
        label = "Correcte"
    elif score >= 45:
        label = "Fragile"
    else:
        label = "Faible"

    display = df.copy()
    pct_cols = [
        "Prob finir positif",
        "Prob perte > 5%",
        "Prob toucher stop court",
        "Prob toucher stop structurel",
        "Prob toucher Target 1",
        "Prob toucher Target 2",
        "Expected Return",
        "Median Return",
    ]

    if "Asymétrie T1/Stop" in display.columns:
        display["Asymétrie T1/Stop"] = display["Asymétrie T1/Stop"].apply(fmt_pp)

    for col in pct_cols:
        if col in display.columns:
            display[col] = display[col].apply(fmt_pct)

    if "MC Score" in display.columns:
        display["MC Score"] = display["MC Score"].apply(fmt_score)

    return {
        "score": score,
        "label": label,
        "worst_mc_score": worst_mc,
        "median_mc_score": median_mc,
        "worst_expected_return": worst_expected,
        "max_stop_prob": max_stop,
        "table": display,
    }


def opportunity_grade(score: float) -> str:
    score = round(safe_float(score, 0) or 0)

    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 75:
        return "A-"
    if score >= 68:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def risk_tier(ctx: dict, state: str | None = None) -> str:
    """
    Risque interprété selon l'état d'exécution.
    - Si le moteur bloque l'entrée maintenant, on affiche un risque conditionnel.
    - Si une entrée est autorisée, on affiche le risque actif du setup.
    """
    stop_prob = ctx.get("stop_prob")
    mc_score = ctx.get("mc_score")
    execution_score = ctx.get("execution_score")
    exhaustion = ctx.get("exhaustion_risk_score")

    risk = 0

    if stop_prob is not None:
        if stop_prob >= 0.55:
            risk += 3
        elif stop_prob >= 0.45:
            risk += 2
        elif stop_prob >= 0.35:
            risk += 1

    if mc_score is not None:
        if mc_score < 45:
            risk += 3
        elif mc_score < 60:
            risk += 2

    if execution_score is not None:
        if execution_score < 45:
            risk += 2
        elif execution_score < 60:
            risk += 1

    if exhaustion is not None and exhaustion >= 70:
        risk += 1

    blocked_states = [
        "NO_TRADE",
        "NO_TRADE_RISK",
        "NO_TRADE_FUNDAMENTAL",
        "NO_TRADE_TECHNICAL",
        "NO_DECISION_DATA",
        "INVALIDATED",
    ]

    waiting_states = [
        "WAIT_PULLBACK",
        "WATCH_STABILIZATION",
        "WATCHLIST",
    ]

    if state in blocked_states:
        return "Bloqué"

    if state in waiting_states:
        if risk >= 6:
            return "Élevé si exécuté"
        if risk >= 4:
            return "Modéré si exécuté"
        if risk >= 2:
            return "Limité si exécuté"
        return "Contrôlé si exécuté"

    if risk >= 6:
        return "Très élevé"
    if risk >= 4:
        return "Élevé"
    if risk >= 2:
        return "Modéré"
    return "Contrôlé"


# ============================================================
# DECISION RULES
# ============================================================

def build_blocking_factors_v2(ctx: dict) -> pd.DataFrame:
    rows = []

    def add(name, current, threshold, status, severity, action):
        rows.append({
            "Facteur": name,
            "Actuel": current,
            "Seuil / condition": threshold,
            "Statut": status,
            "Sévérité": severity,
            "Action mécanique": action,
        })

    # Prix / exécution
    price_severity = "Info"
    price_action = "Conserver"

    if ctx["price_position_key"] == "ABOVE_ZONE":
        price_severity = "Bloquant exécution"
        price_action = "Attendre retour en zone"
    elif ctx["price_position_key"] == "BELOW_ZONE":
        price_severity = "À confirmer"
        price_action = "Attendre stabilisation"
    elif ctx["price_position_key"] == "INVALIDATED":
        price_severity = "Bloquant"
        price_action = "Setup invalidé"

    add(
        "Prix vs zone d'entrée",
        ctx["price_position"],
        f"Idéal : {fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])}",
        "OK" if ctx["price_position_key"] == "IN_ZONE" else "Bloque entrée marché",
        price_severity,
        price_action,
    )

    add(
        "MC Score",
        fmt_score(ctx["mc_score"]),
        "≥ 65 souhaitable / ≥ 70 confirmé",
        "OK" if ctx["mc_score"] >= 65 else "Fragile",
        "Réducteur" if ctx["mc_score"] < 65 else "Info",
        "Réduire sizing / attendre meilleure asymétrie" if ctx["mc_score"] < 65 else "Conserver",
    )

    add(
        "Probabilité stop court",
        fmt_pct(ctx["stop_prob"]),
        "< 45% souhaitable / < 40% confirmé",
        "OK" if ctx["stop_prob"] < 0.45 else "Risque élevé",
        "Bloquant" if ctx["stop_prob"] >= 0.55 else "Réducteur" if ctx["stop_prob"] >= 0.45 else "Info",
        "Réduire taille ou attendre meilleur point" if ctx["stop_prob"] >= 0.45 else "Conserver",
    )

    add(
        "Espérance Monte Carlo",
        fmt_pct(ctx["expected_return"]),
        "> 0%",
        "OK" if ctx["expected_return"] > 0 else "Négative",
        "Bloquant" if ctx["expected_return"] <= 0 else "Info",
        "Pas de buy confirmé" if ctx["expected_return"] <= 0 else "Conserver",
    )

    add(
        "Trend Score",
        fmt_score(ctx["trend_score"]),
        "≥ 60 souhaitable",
        "OK" if ctx["trend_score"] >= 60 else "Dégradé",
        "Réducteur" if ctx["trend_score"] < 60 else "Info",
        "Attendre amélioration trend" if ctx["trend_score"] < 60 else "Conserver",
    )

    add(
        "Company Score",
        fmt_score(ctx["company_score"]),
        "≥ 55 souhaitable / < 45 bloquant",
        "OK" if ctx["company_score"] >= 55 else "Fragile",
        "Bloquant" if ctx["company_score"] < 45 else "Réducteur" if ctx["company_score"] < 55 else "Info",
        "Réduire conviction fondamentale" if ctx["company_score"] < 55 else "Conserver",
    )

    add(
        "Valuation Score",
        fmt_score(ctx["valuation_score"]),
        "≥ 45 souhaitable",
        "OK" if ctx["valuation_score"] >= 45 else "Valorisation tendue",
        "Réducteur" if ctx["valuation_score"] < 45 else "Info",
        "Attendre meilleur prix" if ctx["valuation_score"] < 45 else "Conserver",
    )

    add(
        "Exhaustion Risk",
        fmt_score(ctx["exhaustion_risk_score"]),
        "< 70 souhaitable",
        "OK" if ctx["exhaustion_risk_score"] < 70 else "Extension élevée",
        "Réducteur" if ctx["exhaustion_risk_score"] >= 70 else "Info",
        "Éviter de courir après le prix" if ctx["exhaustion_risk_score"] >= 70 else "Conserver",
    )

    add(
        "Data Confidence",
        fmt_score(ctx["data_confidence"]),
        "≥ 60 souhaitable",
        "OK" if ctx["data_confidence"] >= 60 else "Partiel",
        "Réducteur" if ctx["data_confidence"] < 60 else "Info",
        "Ne pas confirmer si données insuffisantes" if ctx["data_confidence"] < 60 else "Conserver",
    )

    return pd.DataFrame(rows)


def derive_execution_state_v2(ctx: dict, blockers_df: pd.DataFrame) -> str:
    if ctx["data_confidence"] < 45:
        return "NO_DECISION_DATA"

    if ctx["price_position_key"] == "INVALIDATED":
        return "INVALIDATED"

    if ctx["expected_return"] <= 0 and ctx["mc_score"] < 55:
        return "NO_TRADE"

    if ctx["company_score"] < 45:
        return "NO_TRADE_FUNDAMENTAL"

    if ctx["trend_score"] < 40 and ctx["mc_score"] < 55:
        return "NO_TRADE_TECHNICAL"

    if ctx["stop_prob"] >= 0.60:
        return "NO_TRADE_RISK"

    if ctx["price_position_key"] == "ABOVE_ZONE":
        if ctx["opportunity_score"] >= 65:
            return "WAIT_PULLBACK"
        return "WATCHLIST"

    if ctx["price_position_key"] == "BELOW_ZONE":
        return "WATCH_STABILIZATION"

    if ctx["price_position_key"] == "IN_ZONE":
        if (
            ctx["composite_score"] >= 75
            and ctx["mc_score"] >= 70
            and ctx["stop_prob"] < 0.40
            and ctx["expected_return"] > 0
            and ctx["execution_score"] >= 65
        ):
            return "ENTER_LONG_CONFIRMED"

        if (
            ctx["composite_score"] >= 65
            and ctx["mc_score"] >= 55
            and ctx["expected_return"] > 0
        ):
            return "LIMIT_ONLY_REDUCED"

        return "WATCHLIST"

    return "WATCHLIST"


def execution_state_label(state: str) -> str:
    mapping = {
        "ENTER_LONG_CONFIRMED": "ENTER_LONG",
        "LIMIT_ONLY_REDUCED": "LIMIT_ONLY",
        "WAIT_PULLBACK": "WAIT_PULLBACK",
        "WATCH_STABILIZATION": "WATCH_STABILIZATION",
        "WATCHLIST": "WATCHLIST",
        "NO_TRADE": "NO_TRADE",
        "NO_TRADE_RISK": "NO_TRADE_RISK",
        "NO_TRADE_FUNDAMENTAL": "NO_TRADE_FUNDAMENTAL",
        "NO_TRADE_TECHNICAL": "NO_TRADE_TECHNICAL",
        "NO_DECISION_DATA": "NO_DECISION_DATA",
        "INVALIDATED": "INVALIDATED",
    }
    return mapping.get(state, state)


def short_decision_label(final_label: str) -> str:
    mapping = {
        "WAIT_PULLBACK": "WAIT",
        "ENTER_LONG": "ENTER",
        "LIMIT_ONLY": "LIMIT",
        "WATCH_STABILIZATION": "STABILIZE",
        "WATCHLIST": "WATCH",
        "NO_TRADE": "NO TRADE",
        "NO_TRADE_RISK": "NO TRADE",
        "NO_TRADE_FUNDAMENTAL": "NO TRADE",
        "NO_TRADE_TECHNICAL": "NO TRADE",
        "NO_DECISION_DATA": "NO DATA",
        "INVALIDATED": "INVALID",
    }
    return mapping.get(final_label, final_label)


def decision_delta_label(final_label: str) -> str:
    mapping = {
        "WAIT_PULLBACK": "Pullback",
        "ENTER_LONG": "Confirmed",
        "LIMIT_ONLY": "Limit only",
        "WATCH_STABILIZATION": "Stabilisation",
        "WATCHLIST": "Monitor",
        "NO_TRADE": "Blocked",
        "NO_TRADE_RISK": "Risk blocked",
        "NO_TRADE_FUNDAMENTAL": "Fundamental blocked",
        "NO_TRADE_TECHNICAL": "Technical blocked",
        "NO_DECISION_DATA": "Data missing",
        "INVALIDATED": "Invalidated",
    }
    return mapping.get(final_label, "")


def execution_trigger_text(ctx: dict) -> str:
    if ctx["execution_state"] == "ENTER_LONG_CONFIRMED":
        return "Déjà validé : prix dans la zone, MC et risque alignés."

    if ctx["execution_state"] == "LIMIT_ONLY_REDUCED":
        return "Déjà autorisé en taille réduite : ordre limite uniquement."

    if ctx["price_position_key"] == "ABOVE_ZONE":
        return (
            f"Retour prix ≤ {fmt_price(ctx['zone_high'])}, idéalement dans "
            f"{fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])}, "
            "puis MC Score ≥ 65/70 et stop prob < 45%."
        )

    if ctx["price_position_key"] == "BELOW_ZONE":
        return (
            f"Reprise/stabilisation au-dessus de {fmt_price(ctx['zone_low'])}, "
            "avec trend non dégradé et espérance MC positive."
        )

    if ctx["price_position_key"] == "INVALIDATED":
        return (
            f"Revalidation nécessaire au-dessus de {fmt_price(ctx['stop_short'])}, "
            "puis retour dans la zone d'entrée."
        )

    return "Amélioration MC Score, baisse de la probabilité de stop, ou confirmation trend."


def no_chase_rule_text(ctx: dict) -> str:
    if ctx["price_position_key"] == "ABOVE_ZONE":
        return (
            f"Aucun achat au marché tant que le prix reste au-dessus de "
            f"{fmt_price(ctx['zone_high'])}. Distance actuelle à la zone : "
            f"{fmt_pct(ctx['distance_to_zone'])}."
        )

    if ctx["price_position_key"] == "IN_ZONE":
        return "Prix dans la zone : exécution possible seulement si les filtres de risque restent valides."

    if ctx["price_position_key"] == "BELOW_ZONE":
        return "Ne pas anticiper : attendre stabilisation avant tout ordre."

    return "Setup invalidé : aucun ordre théorique."


def mc_robustness_comment(ctx: dict) -> tuple[str, str]:
    label = ctx.get("mc_robustness_label", "Indisponible")
    score = safe_float(ctx.get("mc_robustness_score"), 50)

    if label == "Faible" or score < 45:
        return (
            "warning",
            "Robustesse Monte Carlo faible : le setup dépend trop d'un scénario favorable. "
            "Le moteur doit limiter l'exécution ou attendre une meilleure asymétrie."
        )

    if label == "Fragile" or score < 60:
        return (
            "warning",
            "Robustesse Monte Carlo fragile : le setup reste exploitable, mais pas assez robuste pour une confirmation forte."
        )

    if label == "Correcte":
        return (
            "info",
            "Robustesse Monte Carlo correcte : le setup tient sur plusieurs horizons, mais reste soumis au contrôle du stop."
        )

    return (
        "success",
        "Robustesse Monte Carlo élevée : le profil simulé soutient davantage la décision."
    )


def state_message(state: str, ctx: dict) -> tuple[str, str]:
    if state == "ENTER_LONG_CONFIRMED":
        return (
            "success",
            "Entrée mécaniquement validée : setup, zone, Monte Carlo et risque sont alignés."
        )

    if state == "LIMIT_ONLY_REDUCED":
        return (
            "warning",
            "Entrée autorisée uniquement sous conditions : taille réduite, ordre limite et stop respecté."
        )

    if state == "WAIT_PULLBACK":
        return (
            "warning",
            "Dossier intéressant, mais prix au-dessus de la zone optimale : ne pas acheter au marché, attendre pullback."
        )

    if state == "WATCH_STABILIZATION":
        return (
            "warning",
            "Prix sous la zone d'entrée : attendre stabilisation ou revalidation technique."
        )

    if state == "WATCHLIST":
        return (
            "info",
            "Setup à surveiller : conditions incomplètes pour une exécution mécanique."
        )

    if state == "INVALIDATED":
        return (
            "error",
            "Setup invalidé : prix sous l'invalidation court terme."
        )

    if state == "NO_DECISION_DATA":
        return (
            "error",
            "Décision non confirmable : couverture de données insuffisante."
        )

    return (
        "error",
        "No trade : un ou plusieurs filtres de risque bloquent la décision."
    )


def calculate_risk_budget_v2(ctx: dict, state: str) -> tuple[float, str]:
    if state in [
        "NO_TRADE",
        "NO_TRADE_RISK",
        "NO_TRADE_FUNDAMENTAL",
        "NO_TRADE_TECHNICAL",
        "NO_DECISION_DATA",
        "INVALIDATED",
    ]:
        return 0.0, "0R"

    if state in ["WAIT_PULLBACK", "WATCH_STABILIZATION", "WATCHLIST"]:
        return 0.0, "0R maintenant"

    budget = 1.0

    if state == "LIMIT_ONLY_REDUCED":
        budget = 0.50

    if ctx["mc_score"] < 60:
        budget *= 0.60

    if ctx["stop_prob"] >= 0.45:
        budget *= 0.50

    if ctx["execution_score"] < 60:
        budget *= 0.70

    if ctx["exhaustion_risk_score"] >= 70:
        budget *= 0.70

    if ctx["data_confidence"] < 70:
        budget *= 0.75

    budget = max(0.0, min(1.0, budget))

    if budget >= 0.85:
        label = "1.00R"
    elif budget >= 0.60:
        label = "0.75R"
    elif budget >= 0.35:
        label = "0.50R"
    elif budget > 0:
        label = "0.25R"
    else:
        label = "0R"

    return budget, label


# ============================================================
# CONTEXT BUILDER
# ============================================================

def build_decision_context_v2(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict,
    horizon: int,
) -> dict:
    price = first_numeric(
        analysis.get("latest_price") if isinstance(analysis, dict) else None,
        get_last_price_from_frame(price_data),
        default=0,
    )

    plan = get_trading_plan(analysis, price)
    position_key, position_label = get_price_position(price, plan)
    distances = calculate_distances(price, plan)

    mc_row, mc_table = select_mc_row(analysis, horizon)

    mc = {
        "mc_score": first_numeric(mc_value(mc_row, "MC Score"), default=50),
        "prob_positive": first_numeric(mc_value(mc_row, "Prob finir positif"), default=0.50),
        "loss5_prob": first_numeric(mc_value(mc_row, "Prob perte > 5%"), default=0.50),
        "stop_prob": first_numeric(mc_value(mc_row, "Prob toucher stop court"), default=0.50),
        "target1_prob": first_numeric(mc_value(mc_row, "Prob toucher Target 1"), default=0.50),
        "target2_prob": first_numeric(mc_value(mc_row, "Prob toucher Target 2"), default=0.50),
        "expected_return": first_numeric(mc_value(mc_row, "Expected Return"), default=0.0),
        "median_return": first_numeric(mc_value(mc_row, "Median Return"), default=0.0),
        "asymmetry": first_numeric(mc_value(mc_row, "Asymétrie T1/Stop"), default=0.0),
        "p5": first_numeric(mc_value(mc_row, "P5"), default=None),
        "p50": first_numeric(mc_value(mc_row, "P50"), default=None),
        "p95": first_numeric(mc_value(mc_row, "P95"), default=None),
    }

    company_scores = get_company_scores(analysis)
    momentum = get_momentum_latest(analysis)

    quant_score = first_numeric(
        analysis.get("global_score") if isinstance(analysis, dict) else None,
        analysis.get("score") if isinstance(analysis, dict) else None,
        default=50,
    )

    thesis_score = score_thesis_quality(company_scores)
    technical_score = score_technical_quality(momentum)
    stat_score = score_statistical_edge(mc)
    execution_score = score_execution_quality(price, plan, distances, mc, momentum)
    data_confidence = score_data_confidence(analysis, price_data, mc_table)
    mc_robustness = calculate_mc_robustness_v2(mc_table)

    opportunity_score = clamp(
        0.35 * thesis_score
        + 0.25 * technical_score
        + 0.25 * stat_score
        + 0.15 * quant_score
    )

    composite_score = clamp(
        0.25 * thesis_score
        + 0.20 * technical_score
        + 0.25 * stat_score
        + 0.20 * execution_score
        + 0.10 * data_confidence
    )

    ctx = {
        "ticker": ticker,
        "horizon": horizon,
        "horizon_label": f"{horizon}D",
        "price": price,
        "raw_signal": analysis.get("signal", "N/A") if isinstance(analysis, dict) else "N/A",
        "quant_score": quant_score,
        "volatility": first_numeric(analysis.get("volatility") if isinstance(analysis, dict) else None, default=None),
        "drift": first_numeric(analysis.get("drift") if isinstance(analysis, dict) else None, default=None),
        "momentum_raw": first_numeric(analysis.get("momentum") if isinstance(analysis, dict) else None, default=None),
        "max_drawdown": first_numeric(analysis.get("max_drawdown") if isinstance(analysis, dict) else None, default=None),
        "atr": plan["atr"],
        "zone_low": plan["zone_low"],
        "zone_high": plan["zone_high"],
        "stop_short": plan["stop_short"],
        "stop_structural": plan["stop_structural"],
        "target_1": plan["target_1"],
        "target_2": plan["target_2"],
        "price_position_key": position_key,
        "price_position": position_label,
        "distance_stop_short": distances["distance_stop_short"],
        "distance_stop_structural": distances["distance_stop_structural"],
        "distance_target_1": distances["distance_target_1"],
        "distance_target_2": distances["distance_target_2"],
        "rr_t1": distances["rr_t1"],
        "distance_to_zone": distances["distance_to_zone"],
        "thesis_score": thesis_score,
        "technical_score": technical_score,
        "stat_score": stat_score,
        "execution_score": execution_score,
        "data_confidence": data_confidence,
        "opportunity_score": opportunity_score,
        "opportunity_grade": opportunity_grade(opportunity_score),
        "composite_score": composite_score,
        "mc_robustness_score": mc_robustness["score"],
        "mc_robustness_label": mc_robustness["label"],
        "mc_robustness": mc_robustness,
        "mc_table": mc_table,
        "mc_row": mc_row,
        **mc,
        **company_scores,
        **momentum,
    }

    blockers_df = build_blocking_factors_v2(ctx)
    state = derive_execution_state_v2(ctx, blockers_df)
    risk_budget, risk_budget_label = calculate_risk_budget_v2(ctx, state)
    tier = risk_tier(ctx, state)

    ctx.update({
        "execution_state": state,
        "final_label": execution_state_label(state),
        "risk_budget": risk_budget,
        "risk_budget_label": risk_budget_label,
        "risk_tier": tier,
        "blockers_df": blockers_df,
    })

    return ctx


# ============================================================
# TABLE BUILDERS
# ============================================================

def build_decision_matrix_v2(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Pilier": "Thesis Quality",
            "Score": fmt_score(ctx["thesis_score"]),
            "Verdict": "Fort" if ctx["thesis_score"] >= 70 else "Correct" if ctx["thesis_score"] >= 55 else "Fragile",
            "Impact": "Supporte le dossier" if ctx["thesis_score"] >= 60 else "Réduit la conviction",
            "Évidence": (
                f"Company {fmt_score(ctx['company_score'])} · "
                f"Valuation {fmt_score(ctx['valuation_score'])} · "
                f"Forward {fmt_score(ctx['forward_score'])} · "
                f"Analystes {fmt_score(ctx['analyst_score'])}"
            ),
        },
        {
            "Pilier": "Technical Timing",
            "Score": fmt_score(ctx["technical_score"]),
            "Verdict": "Constructif" if ctx["technical_score"] >= 65 else "Mixte" if ctx["technical_score"] >= 50 else "Dégradé",
            "Impact": "Supporte le setup" if ctx["technical_score"] >= 60 else "Demande confirmation",
            "Évidence": (
                f"Trend {fmt_score(ctx['trend_score'])} · "
                f"Momentum {fmt_score(ctx['momentum_score'])} · "
                f"Timing {fmt_score(ctx['timing_score'])} · "
                f"Exhaustion {fmt_score(ctx['exhaustion_risk_score'])}"
            ),
        },
        {
            "Pilier": "Statistical Edge",
            "Score": fmt_score(ctx["stat_score"]),
            "Verdict": "Exploitable" if ctx["stat_score"] >= 65 else "Fragile" if ctx["stat_score"] >= 45 else "Faible",
            "Impact": "Valide l'asymétrie" if ctx["stat_score"] >= 60 else "Réduit le sizing",
            "Évidence": (
                f"MC {fmt_score(ctx['mc_score'])} · "
                f"Target1 {fmt_pct(ctx['target1_prob'])} · "
                f"Stop {fmt_pct(ctx['stop_prob'])} · "
                f"Espérance {fmt_pct(ctx['expected_return'])}"
            ),
        },
        {
            "Pilier": "Execution Quality",
            "Score": fmt_score(ctx["execution_score"]),
            "Verdict": ctx["price_position"],
            "Impact": "Autorise l'exécution" if ctx["price_position_key"] == "IN_ZONE" else "Bloque l'entrée marché",
            "Évidence": (
                f"Zone {fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])} · "
                f"Prix {fmt_price(ctx['price'])} · "
                f"RR T1 {fmt_num(ctx['rr_t1'])}"
            ),
        },
        {
            "Pilier": "Data Confidence",
            "Score": fmt_score(ctx["data_confidence"]),
            "Verdict": "OK" if ctx["data_confidence"] >= 70 else "Partiel",
            "Impact": "Décision fiable" if ctx["data_confidence"] >= 70 else "Limiter la conviction",
            "Évidence": (
                f"MC table {'OK' if isinstance(ctx.get('mc_table'), pd.DataFrame) and not ctx['mc_table'].empty else 'manquante'} · "
                f"Plan {'OK' if ctx['target_1'] is not None else 'partiel'} · "
                f"Company {fmt_score(ctx['company_score'])}"
            ),
        },
    ]

    return pd.DataFrame(rows)


def build_upgrade_conditions_v2(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Objectif": "Passer en ENTER_LONG",
            "Condition": "Prix dans la zone + MC Score ≥ 70 + stop < 40% + espérance > 0%",
            "Actuel": (
                f"Prix {ctx['price_position']} · "
                f"MC {fmt_score(ctx['mc_score'])} · "
                f"Stop {fmt_pct(ctx['stop_prob'])} · "
                f"Espérance {fmt_pct(ctx['expected_return'])}"
            ),
            "Statut": "OK" if ctx["execution_state"] == "ENTER_LONG_CONFIRMED" else "Non validé",
        },
        {
            "Objectif": "Autoriser taille réduite",
            "Condition": "Prix dans la zone + score composite ≥ 65 + MC Score ≥ 55",
            "Actuel": (
                f"Composite {fmt_score(ctx['composite_score'])} · "
                f"MC {fmt_score(ctx['mc_score'])} · "
                f"Position {ctx['price_position']}"
            ),
            "Statut": "OK" if ctx["execution_state"] in ["ENTER_LONG_CONFIRMED", "LIMIT_ONLY_REDUCED"] else "À attendre",
        },
        {
            "Objectif": "Réduire le risque de stop",
            "Condition": "Probabilité stop court < 45%, idéalement < 40%",
            "Actuel": fmt_pct(ctx["stop_prob"]),
            "Statut": "OK" if ctx["stop_prob"] < 0.45 else "À améliorer",
        },
        {
            "Objectif": "Améliorer le point d'entrée",
            "Condition": f"Retour vers {fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])}",
            "Actuel": f"Prix actuel {fmt_price(ctx['price'])}",
            "Statut": "OK" if ctx["price_position_key"] == "IN_ZONE" else "Attendre",
        },
        {
            "Objectif": "Éviter le chase",
            "Condition": "Exhaustion Risk < 70 et prix non étendu",
            "Actuel": f"Exhaustion {fmt_score(ctx['exhaustion_risk_score'])}",
            "Statut": "OK" if ctx["exhaustion_risk_score"] < 70 else "À surveiller",
        },
    ]

    return pd.DataFrame(rows)


def build_execution_playbook_v2(ctx: dict) -> pd.DataFrame:
    order_type = "Limit uniquement"
    execution_status = "Attente pullback"

    if ctx["execution_state"] == "ENTER_LONG_CONFIRMED":
        order_type = "Limit ou market prudent"
        execution_status = "Exécutable"
    elif ctx["execution_state"] == "LIMIT_ONLY_REDUCED":
        order_type = "Limit uniquement"
        execution_status = "Exécutable avec taille réduite"
    elif ctx["execution_state"] in ["NO_TRADE", "NO_TRADE_RISK", "NO_TRADE_FUNDAMENTAL", "NO_TRADE_TECHNICAL", "INVALIDATED"]:
        order_type = "Aucun ordre"
        execution_status = "Bloqué"

    entry_trigger = execution_trigger_text(ctx)
    no_chase_rule = no_chase_rule_text(ctx)

    rows = [
        {
            "Champ": "Action finale",
            "Valeur": ctx["final_label"],
            "Lecture": state_message(ctx["execution_state"], ctx)[1],
        },
        {
            "Champ": "Opportunity Grade",
            "Valeur": ctx["opportunity_grade"],
            "Lecture": f"Qualité du dossier indépendamment du point d'entrée : {fmt_score(ctx['opportunity_score'])}.",
        },
        {
            "Champ": "État d'exécution",
            "Valeur": execution_status,
            "Lecture": "Sépare la qualité du dossier et la possibilité d'acheter maintenant.",
        },
        {
            "Champ": "Type d'ordre théorique",
            "Valeur": order_type,
            "Lecture": "Évite l'entrée marché si le prix est au-dessus de la zone optimale.",
        },
        {
            "Champ": "Déclencheur d'entrée",
            "Valeur": entry_trigger,
            "Lecture": "Condition minimale pour que le moteur améliore l'état d'exécution.",
        },
        {
            "Champ": "Règle anti-chase",
            "Valeur": no_chase_rule,
            "Lecture": "Empêche de transformer un bon dossier en mauvaise entrée.",
        },
        {
            "Champ": "Zone limite basse",
            "Valeur": fmt_price(ctx["zone_low"]),
            "Lecture": "Bas de la zone d'entrée.",
        },
        {
            "Champ": "Zone limite haute",
            "Valeur": fmt_price(ctx["zone_high"]),
            "Lecture": "Haut de la zone d'entrée.",
        },
        {
            "Champ": "Stop court terme",
            "Valeur": fmt_price(ctx["stop_short"]),
            "Lecture": "Invalidation rapide.",
        },
        {
            "Champ": "Stop structurel",
            "Valeur": fmt_price(ctx["stop_structural"]),
            "Lecture": "Invalidation large.",
        },
        {
            "Champ": "Target 1",
            "Valeur": fmt_price(ctx["target_1"]),
            "Lecture": "Premier objectif.",
        },
        {
            "Champ": "Target 2",
            "Valeur": fmt_price(ctx["target_2"]),
            "Lecture": "Objectif étendu.",
        },
        {
            "Champ": "Risk budget",
            "Valeur": ctx["risk_budget_label"],
            "Lecture": "Taille théorique liée au risque simulé. Ce n'est pas une recommandation personnalisée.",
        },
        {
            "Champ": "Condition de renforcement",
            "Valeur": "MC Score ≥ 70, stop < 40%, prix dans la zone, exhaustion < 70",
            "Lecture": "Conditions minimales pour passer vers ENTER_LONG confirmé.",
        },
    ]

    return pd.DataFrame(rows)


def build_distance_table_v2(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Bloc": "Distance stop court",
            "Valeur": fmt_pct(ctx["distance_stop_short"]),
            "Interprétation": "Distance entre le prix actuel et l'invalidation court terme.",
        },
        {
            "Bloc": "Distance stop structurel",
            "Valeur": fmt_pct(ctx["distance_stop_structural"]),
            "Interprétation": "Distance entre le prix actuel et l'invalidation large.",
        },
        {
            "Bloc": "Distance Target 1",
            "Valeur": fmt_pct(ctx["distance_target_1"]),
            "Interprétation": "Potentiel vers le premier objectif.",
        },
        {
            "Bloc": "Distance Target 2",
            "Valeur": fmt_pct(ctx["distance_target_2"]),
            "Interprétation": "Potentiel vers l'objectif étendu.",
        },
        {
            "Bloc": "RR vers Target 1",
            "Valeur": fmt_num(ctx["rr_t1"]),
            "Interprétation": "Ratio gain potentiel / risque court terme.",
        },
        {
            "Bloc": "Distance jusqu'à la zone",
            "Valeur": fmt_pct(ctx["distance_to_zone"]),
            "Interprétation": "Négatif si le prix doit baisser pour revenir dans la zone.",
        },
        {
            "Bloc": "Asymétrie MC",
            "Valeur": fmt_pp(ctx["asymmetry"]),
            "Interprétation": "Probabilité Target 1 moins probabilité stop court.",
        },
        {
            "Bloc": "Espérance MC",
            "Valeur": fmt_pct(ctx["expected_return"]),
            "Interprétation": "Rendement moyen simulé sur l'horizon sélectionné.",
        },
    ]
    return pd.DataFrame(rows)


def build_export_summary_v2(ctx: dict) -> pd.DataFrame:
    rows = [
        ("Ticker", ctx["ticker"]),
        ("Horizon", ctx["horizon_label"]),
        ("Prix actuel", fmt_price(ctx["price"])),
        ("Raw signal", ctx["raw_signal"]),
        ("Final decision", ctx["final_label"]),
        ("Opportunity grade", ctx["opportunity_grade"]),
        ("Composite score", fmt_score(ctx["composite_score"])),
        ("Opportunity score", fmt_score(ctx["opportunity_score"])),
        ("Execution score", fmt_score(ctx["execution_score"])),
        ("Execution risk", ctx["risk_tier"]),
        ("Risk budget", ctx["risk_budget_label"]),
        ("MC Score", fmt_score(ctx["mc_score"])),
        ("MC Robustness", f"{ctx['mc_robustness_label']} / {fmt_score(ctx['mc_robustness_score'])}"),
        ("Prob stop court", fmt_pct(ctx["stop_prob"])),
        ("Prob Target 1", fmt_pct(ctx["target1_prob"])),
        ("Espérance MC", fmt_pct(ctx["expected_return"])),
        ("Company Score", fmt_score(ctx["company_score"])),
        ("Valuation Score", fmt_score(ctx["valuation_score"])),
        ("Trend Score", fmt_score(ctx["trend_score"])),
        ("Zone entrée", f"{fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])}"),
        ("Stop court", fmt_price(ctx["stop_short"])),
        ("Stop structurel", fmt_price(ctx["stop_structural"])),
        ("Target 1", fmt_price(ctx["target_1"])),
        ("Target 2", fmt_price(ctx["target_2"])),
    ]

    return pd.DataFrame(rows, columns=["Champ", "Valeur"])


# ============================================================
# CHART
# ============================================================

def prepare_price_frame(price_data: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return pd.DataFrame()

    df = price_data.copy()
    df.columns = [str(c).lower() for c in df.columns]

    if "date" not in df.columns:
        df = df.reset_index().rename(columns={"index": "date"})

    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "close"]).sort_values("date")

    return df.tail(180)


def render_decision_price_map_v2(ticker: str, price_data: pd.DataFrame, ctx: dict):
    df = prepare_price_frame(price_data)

    if df.empty:
        st.info("Graphique indisponible : historique prix vide.")
        return

    fig = go.Figure()

    # ------------------------------------------------------------
    # Candles / prix
    # ------------------------------------------------------------
    if dataframe_has_columns(df, ["date", "open", "high", "low", "close"]):
        fig.add_trace(go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=ticker,
            increasing_line_color="#2ecc71",
            increasing_fillcolor="#2ecc71",
            decreasing_line_color="#ff7f7f",
            decreasing_fillcolor="#ff7f7f",
            opacity=0.95,
        ))
    else:
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["close"],
            mode="lines",
            name="Close",
            line=dict(color="#f5f5f5", width=2),
        ))

    # ------------------------------------------------------------
    # Dates étendues à droite pour labels lisibles
    # ------------------------------------------------------------
    first_date = df["date"].min()
    last_date = df["date"].max()
    future_date = last_date + pd.Timedelta(days=38)

    # ------------------------------------------------------------
    # Zones visuelles
    # ------------------------------------------------------------
    zone_low = ctx["zone_low"]
    zone_high = ctx["zone_high"]
    price = ctx["price"]

    stop_short = ctx["stop_short"]
    stop_structural = ctx["stop_structural"]
    target_1 = ctx["target_1"]
    target_2 = ctx["target_2"]

    # Zone d'entrée principale
    fig.add_hrect(
        y0=zone_low,
        y1=zone_high,
        x0=first_date,
        x1=future_date,
        fillcolor="rgba(30, 120, 255, 0.22)",
        line_width=0,
        annotation_text="ZONE D'ENTRÉE OPTIMALE",
        annotation_position="top left",
        annotation_font_size=12,
        annotation_font_color="#dbeafe",
    )

    # Zone de chase si le prix est au-dessus de la zone
    if price is not None and price > zone_high:
        upper_chase = max(price, target_1 if target_1 is not None else price)
        fig.add_hrect(
            y0=zone_high,
            y1=upper_chase,
            x0=first_date,
            x1=future_date,
            fillcolor="rgba(255, 193, 7, 0.055)",
            line_width=0,
            annotation_text="CHASE / ATTENTE",
            annotation_position="bottom left",
            annotation_font_size=10,
            annotation_font_color="rgba(250, 204, 21, 0.75)",
        )

    # Zone invalidation
    if stop_structural is not None and stop_short is not None:
        fig.add_hrect(
            y0=stop_structural,
            y1=stop_short,
            x0=first_date,
            x1=future_date,
            fillcolor="rgba(255, 80, 80, 0.08)",
            line_width=0,
            annotation_text="ZONE D'INVALIDATION",
            annotation_position="bottom left",
            annotation_font_size=11,
            annotation_font_color="#fecaca",
        )

    # ------------------------------------------------------------
    # Lignes de décision
    # ------------------------------------------------------------
    level_specs = [
        {
            "label": "Target 2",
            "value": target_2,
            "color": "#16a34a",
            "dash": "dot",
            "width": 1.3,
            "side": "top right",
        },
        {
            "label": "Target 1",
            "value": target_1,
            "color": "#22c55e",
            "dash": "dash",
            "width": 1.6,
            "side": "top right",
        },
        {
            "label": "Prix actuel",
            "value": price,
            "color": "#f8fafc",
            "dash": "solid",
            "width": 2.2,
            "side": "top right",
        },
        {
            "label": "Zone haute",
            "value": zone_high,
            "color": "#60a5fa",
            "dash": "dash",
            "width": 1.5,
            "side": "bottom right",
        },
        {
            "label": "Zone basse",
            "value": zone_low,
            "color": "#60a5fa",
            "dash": "dash",
            "width": 1.5,
            "side": "bottom right",
        },
        {
            "label": "Stop court",
            "value": stop_short,
            "color": "#f59e0b",
            "dash": "dash",
            "width": 1.4,
            "side": "bottom right",
        },
        {
            "label": "Stop structurel",
            "value": stop_structural,
            "color": "#ef4444",
            "dash": "dot",
            "width": 1.4,
            "side": "bottom right",
        },
    ]

    for spec in level_specs:
        value = safe_float(spec["value"])
        if value is None:
            continue

        fig.add_hline(
            y=value,
            line_dash=spec["dash"],
            line_width=spec["width"],
            line_color=spec["color"],
            opacity=0.90,
            annotation_text=f"{spec['label']} {fmt_price(value)}",
            annotation_position=spec["side"],
            annotation_font_size=12,
            annotation_font_color=spec["color"],
        )

    # ------------------------------------------------------------
    # Annotation décisionnelle
    # ------------------------------------------------------------
    if ctx["price_position_key"] == "ABOVE_ZONE":
        annotation = (
            "Prix au-dessus de la zone<br>"
            "Attendre pullback / limit only"
        )
        annotation_color = "#facc15"
    elif ctx["price_position_key"] == "IN_ZONE":
        annotation = (
            "Prix dans la zone<br>"
            "Exécution possible sous conditions"
        )
        annotation_color = "#22c55e"
    elif ctx["price_position_key"] == "INVALIDATED":
        annotation = (
            "Prix sous stop<br>"
            "Setup invalidé"
        )
        annotation_color = "#ef4444"
    else:
        annotation = (
            "Prix sous la zone<br>"
            "Attendre stabilisation"
        )
        annotation_color = "#facc15"

    fig.add_annotation(
        x=df["date"].iloc[-1],
        y=price,
        text=annotation,
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.6,
        arrowcolor=annotation_color,
        ax=-130,
        ay=-55,
        font=dict(size=12, color="#f8fafc"),
        bgcolor="rgba(15, 23, 42, 0.88)",
        bordercolor=annotation_color,
        borderwidth=1,
        borderpad=6,
    )

    # ------------------------------------------------------------
    # Petit résumé dans le graphique
    # ------------------------------------------------------------
    graph_decision = short_decision_label(ctx["final_label"])

    risk_short = str(ctx["risk_tier"]).replace(" si exécuté", "")

    summary_text = (
        f"<b>{graph_decision}</b> · {decision_delta_label(ctx['final_label'])}<br>"
        f"Opportunity {ctx['opportunity_grade']} · "
        f"Execution {fmt_score(ctx['execution_score'])}<br>"
        f"MC {fmt_score(ctx['mc_score'])} · "
        f"Stop {fmt_pct(ctx['stop_prob'])} · "
        f"Exec risk {risk_short}"
    )

    summary_top = max(
        df["high"].max() if "high" in df.columns else df["close"].max(),
        target_2 or price,
    )

    summary_offset = max(
        (summary_top - min(stop_structural or summary_top, df["low"].min() if "low" in df.columns else df["close"].min())) * 0.045,
        price * 0.012 if price else 1,
    )

    summary_y = summary_top - summary_offset

    fig.add_annotation(
        x=first_date,
        y=summary_y,
        text=summary_text,
        showarrow=False,
        xanchor="left",
        yanchor="top",
        align="left",
        font=dict(size=12, color="#e5e7eb"),
        bgcolor="rgba(15, 23, 42, 0.86)",
        bordercolor="rgba(148, 163, 184, 0.55)",
        borderwidth=1,
        borderpad=8,
    )

    # ------------------------------------------------------------
    # Layout premium
    # ------------------------------------------------------------
    y_candidates = [
        safe_float(df["low"].min() if "low" in df.columns else df["close"].min()),
        stop_structural,
        stop_short,
        zone_low,
        zone_high,
        price,
        target_1,
        target_2,
        safe_float(df["high"].max() if "high" in df.columns else df["close"].max()),
    ]
    y_candidates = [x for x in y_candidates if x is not None]

    if y_candidates:
        y_min = min(y_candidates)
        y_max = max(y_candidates)
        y_padding = max((y_max - y_min) * 0.08, price * 0.015 if price else 1)
        y_range = [y_min - y_padding, y_max + y_padding]
    else:
        y_range = None

    fig.update_layout(
        height=680,
        title=f"Decision Price Map — {ticker}",
        xaxis_title="Date",
        yaxis_title="Prix",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=210, t=75, b=45),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10, 14, 22, 0.55)",
        font=dict(color="#f8fafc"),
    )

    fig.update_xaxes(
        rangeslider_visible=False,
        range=[first_date, future_date],
        showgrid=False,
        zeroline=False,
    )

    fig.update_yaxes(
        range=y_range,
        automargin=True,
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.18)",
        zeroline=False,
    )

    st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------
    # Table compacte des niveaux
    # ------------------------------------------------------------
    levels_df = pd.DataFrame([
        {
            "Niveau": "Target 2",
            "Prix": fmt_price(target_2),
            "Lecture": "Objectif étendu",
        },
        {
            "Niveau": "Target 1",
            "Prix": fmt_price(target_1),
            "Lecture": "Objectif principal",
        },
        {
            "Niveau": "Prix actuel",
            "Prix": fmt_price(price),
            "Lecture": "Référence actuelle",
        },
        {
            "Niveau": "Zone haute",
            "Prix": fmt_price(zone_high),
            "Lecture": "Haut de zone d'entrée",
        },
        {
            "Niveau": "Zone basse",
            "Prix": fmt_price(zone_low),
            "Lecture": "Bas de zone d'entrée",
        },
        {
            "Niveau": "Stop court",
            "Prix": fmt_price(stop_short),
            "Lecture": "Invalidation rapide",
        },
        {
            "Niveau": "Stop structurel",
            "Prix": fmt_price(stop_structural),
            "Lecture": "Invalidation large",
        },
    ])

    with st.expander("Voir les niveaux affichés sur le graphique", expanded=False):
        st.dataframe(
            levels_df,
            use_container_width=True,
            hide_index=True,
        )


# ============================================================
# MAIN RENDER
# ============================================================

def render_decision_engine_v2(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict,
):
    st.subheader(f"Decision Engine V2 — {ticker}")

    if not isinstance(analysis, dict) or not analysis:
        st.error("Analyse indisponible : le dictionnaire analysis est vide.")
        return

    selected_horizon = st.selectbox(
        "Horizon de décision",
        [7, 30, 90],
        index=1,
        key=f"decision_engine_v2_horizon_{ticker}"
    )

    ctx = build_decision_context_v2(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis,
        horizon=selected_horizon,
    )

    severity, message = state_message(ctx["execution_state"], ctx)

    # ------------------------------------------------------------
    # Executive card
    # ------------------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    decision_short = short_decision_label(ctx["final_label"])
    decision_delta = decision_delta_label(ctx["final_label"])

    c1.metric("Décision", decision_short, delta=decision_delta)
    c2.metric("Opportunity", ctx["opportunity_grade"], delta=fmt_score(ctx["opportunity_score"]))
    c3.metric("Execution", fmt_score(ctx["execution_score"]), delta=ctx["price_position"])
    c4.metric("Conviction", fmt_score(ctx["composite_score"]))
    c5.metric("Risk Budget", ctx["risk_budget_label"])
    c6.metric("Execution Risk", ctx["risk_tier"], delta=ctx["risk_budget_label"])

    if severity == "success":
        st.success(message)
    elif severity == "warning":
        st.warning(message)
    elif severity == "error":
        st.error(message)
    else:
        st.info(message)

    st.caption(
        f"Prix {fmt_price(ctx['price'])} · "
        f"Zone {fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])} · "
        f"Stop court {fmt_price(ctx['stop_short'])} · "
        f"Target 1 {fmt_price(ctx['target_1'])} · "
        f"MC {fmt_score(ctx['mc_score'])} · "
        f"Stop prob {fmt_pct(ctx['stop_prob'])} · "
        f"Espérance {fmt_pct(ctx['expected_return'])}"
    )

    tabs = st.tabs([
        "Executive",
        "Audit & Veto",
        "Execution",
        "Monte Carlo",
        "Graphique / Export",
    ])

    # ------------------------------------------------------------
    # Executive
    # ------------------------------------------------------------
    with tabs[0]:
        st.subheader("Opportunity vs Execution Matrix")

        st.dataframe(
            build_decision_matrix_v2(ctx),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Lecture synthétique")

        if ctx["execution_state"] == "WAIT_PULLBACK":
            st.warning(
                "Le dossier est exploitable, mais le prix n'est pas exploitable maintenant. "
                "Le moteur refuse l'entrée au marché et privilégie un ordre limite dans la zone."
            )
        elif ctx["execution_state"] == "ENTER_LONG_CONFIRMED":
            st.success(
                "Le dossier, l'exécution et le Monte Carlo sont alignés. "
                "L'entrée est mécaniquement validée sous respect du stop."
            )
        elif ctx["execution_state"] == "LIMIT_ONLY_REDUCED":
            st.warning(
                "Entrée possible uniquement avec taille réduite. "
                "Le risque Monte Carlo ou la probabilité de stop empêchent une taille normale."
            )
        elif ctx["execution_state"].startswith("NO_TRADE") or ctx["execution_state"] == "INVALIDATED":
            st.error(
                "Le moteur bloque l'opération. Le risque, la structure ou la qualité du dossier ne justifie pas une exécution."
            )
        else:
            st.info(
                "Le setup reste en surveillance. Les conditions ne sont pas suffisantes pour une exécution mécanique."
            )

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Thesis", fmt_score(ctx["thesis_score"]))
        k2.metric("Technical", fmt_score(ctx["technical_score"]))
        k3.metric("Stat Edge", fmt_score(ctx["stat_score"]))
        k4.metric("Execution", fmt_score(ctx["execution_score"]))
        k5.metric("Data", fmt_score(ctx["data_confidence"]))

    # ------------------------------------------------------------
    # Audit & veto
    # ------------------------------------------------------------
    with tabs[1]:
        st.subheader("Blocking Factors / Veto Rules")

        blockers = ctx["blockers_df"]
        st.dataframe(
            blockers,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Conditions d'upgrade")

        st.dataframe(
            build_upgrade_conditions_v2(ctx),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Invalidation / Revalidation")

        invalidation_df = pd.DataFrame([
            {
                "Bloc": "Invalidation rapide",
                "Niveau / condition": f"Clôture sous stop court : {fmt_price(ctx['stop_short'])}",
                "Lecture": "Le setup court terme est invalidé.",
            },
            {
                "Bloc": "Invalidation structurelle",
                "Niveau / condition": f"Clôture sous stop structurel : {fmt_price(ctx['stop_structural'])}",
                "Lecture": "Le scénario quantitatif devient trop dégradé.",
            },
            {
                "Bloc": "Invalidation statistique",
                "Niveau / condition": "MC Score < 50 ou espérance MC négative",
                "Lecture": "Le moteur ne valide plus l'asymétrie.",
            },
            {
                "Bloc": "Invalidation fondamentale",
                "Niveau / condition": "Company Score < 45 ou forte dégradation croissance / marges",
                "Lecture": "Le support entreprise devient insuffisant.",
            },
            {
                "Bloc": "Revalidation",
                "Niveau / condition": "MC Score > 65, stop < 45%, prix dans la zone",
                "Lecture": "Le setup redevient exploitable avec meilleur contrôle du risque.",
            },
            {
                "Bloc": "Passage ENTER_LONG",
                "Niveau / condition": "Score composite ≥ 75, MC ≥ 70, stop < 40%, prix dans la zone",
                "Lecture": "Le setup passe de conditionnel à confirmé.",
            },
        ])

        st.dataframe(
            invalidation_df,
            use_container_width=True,
            hide_index=True,
        )

    # ------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------
    with tabs[2]:
        st.subheader("Zone d'entrée optimale")

        z1, z2, z3, z4 = st.columns(4)
        z1.metric("Type de zone", "Zone prudente")
        z2.metric("Bas zone", fmt_price(ctx["zone_low"]))
        z3.metric("Haut zone", fmt_price(ctx["zone_high"]))
        z4.metric("Position prix", ctx["price_position"])

        if ctx["price_position_key"] == "ABOVE_ZONE":
            st.warning(
                f"Distance estimée jusqu'à la zone : {fmt_pct(ctx['distance_to_zone'])}. "
                "Le moteur privilégie l'attente d'un retour dans la zone."
            )
        elif ctx["price_position_key"] == "IN_ZONE":
            st.success("Le prix est dans la zone d'entrée mécanique.")
        elif ctx["price_position_key"] == "INVALIDATED":
            st.error("Le prix est sous l'invalidation court terme.")
        else:
            st.warning("Le prix est sous la zone : attendre stabilisation ou revalidation.")

        st.subheader("Execution Playbook")

        st.dataframe(
            build_execution_playbook_v2(ctx),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Distances et asymétrie")

        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Distance stop court", fmt_pct(ctx["distance_stop_short"]))
        d2.metric("Distance Target 1", fmt_pct(ctx["distance_target_1"]))
        d3.metric("RR Target 1", fmt_num(ctx["rr_t1"]))
        d4.metric("Asymétrie MC", fmt_pp(ctx["asymmetry"]))
        d5.metric("Espérance MC", fmt_pct(ctx["expected_return"]))

        st.dataframe(
            build_distance_table_v2(ctx),
            use_container_width=True,
            hide_index=True,
        )

    # ------------------------------------------------------------
    # Monte Carlo
    # ------------------------------------------------------------
    with tabs[3]:
        st.subheader("Preuves Monte Carlo")

        proof_df = pd.DataFrame([{
            "Horizon": ctx["horizon_label"],
            "Prob. positif": fmt_pct(ctx["prob_positive"]),
            "Prob. stop court": fmt_pct(ctx["stop_prob"]),
            "Prob. Target 1": fmt_pct(ctx["target1_prob"]),
            "Prob. perte > 5%": fmt_pct(ctx["loss5_prob"]),
            "Expected Return": fmt_pct(ctx["expected_return"]),
            "Asymétrie T1/Stop": fmt_pp(ctx["asymmetry"]),
            "MC Score": fmt_score(ctx["mc_score"]),
            "P5": fmt_price(ctx["p5"]),
            "P50": fmt_price(ctx["p50"]),
            "P95": fmt_price(ctx["p95"]),
        }])

        st.dataframe(
            proof_df,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Robustesse Monte Carlo sur horizons")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Robustesse", ctx["mc_robustness_label"])
        r2.metric("Robustness Score", fmt_score(ctx["mc_robustness_score"]))
        r3.metric("Worst MC", fmt_score(ctx["mc_robustness"].get("worst_mc_score")))
        r4.metric("Max stop prob", fmt_pct(ctx["mc_robustness"].get("max_stop_prob")))

        mc_msg_type, mc_msg = mc_robustness_comment(ctx)

        if mc_msg_type == "success":
            st.success(mc_msg)
        elif mc_msg_type == "warning":
            st.warning(mc_msg)
        elif mc_msg_type == "error":
            st.error(mc_msg)
        else:
            st.info(mc_msg)

        robust_table = ctx["mc_robustness"].get("table", pd.DataFrame())

        if isinstance(robust_table, pd.DataFrame) and not robust_table.empty:
            st.dataframe(
                robust_table,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Table Monte Carlo indisponible pour la robustesse.")

        st.caption(
            "Lecture : le moteur pénalise les setups dont la qualité dépend trop d'un seul horizon "
            "ou dont l'espérance devient fragile quand la probabilité de stop monte."
        )

    # ------------------------------------------------------------
    # Graphique / Export
    # ------------------------------------------------------------
    with tabs[4]:
        st.subheader("Graphique prix avec zone de décision")

        render_decision_price_map_v2(ticker, price_data, ctx)

        st.subheader("Export résumé final")

        export_df = build_export_summary_v2(ctx)

        st.dataframe(
            export_df,
            use_container_width=True,
            hide_index=True,
        )

        csv = export_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Télécharger le résumé CSV",
            data=csv,
            file_name=f"{ticker}_decision_engine_v2_{ctx['horizon_label']}.csv",
            mime="text/csv",
            key=f"download_decision_engine_v2_{ticker}_{ctx['horizon_label']}",
        )