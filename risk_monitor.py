# ============================================================
# RISK MONITOR V2 — STANDALONE MODULE
# ============================================================
# Objectif :
# - Transformer le Risk Monitor en vrai cockpit pré-trade risque.
# - Ne pas répéter le Decision Engine ni le Monte Carlo Lab.
# - Lire uniquement ticker, price_data, analysis.
# - Ne dépendre d'aucune fonction de app.py.
#
# Intégration app.py :
# from risk_monitor import render_risk_monitor_v2
#
# Puis appeler directement :
# render_risk_monitor_v2(ticker=ticker, price_data=price_data, analysis=analysis)
# ============================================================

from __future__ import annotations

import html
import json

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

from risk_control import (
    RiskParameters,
    build_institutional_risk_snapshot,
    load_risk_market_enrichment,
    risk_data_readiness,
)


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


def fmt_num(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_score(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.0f}/100"


def fmt_pp(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value * 100:.2f} pts"


def fmt_pct_adaptive(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    if value != 0 and abs(value) < 0.0001:
        return "<0.01%" if value > 0 else ">-0.01%"
    if abs(value) < 0.01:
        return f"{value:.3%}"
    return f"{value:.2%}"


def fmt_days(value):
    value = safe_float(value)
    if value is None:
        return "N/A"
    if 0 < value < 0.01:
        return "<0.01 d"
    return f"{value:.2f} d"


def dataframe_has_columns(df: pd.DataFrame, cols: list[str]) -> bool:
    return isinstance(df, pd.DataFrame) and not df.empty and all(c in df.columns for c in cols)


# ============================================================
# DATA EXTRACTION
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

    df = df.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)

    return df


def get_last_price_from_frame(price_data: pd.DataFrame):
    df = prepare_price_frame(price_data)

    if df.empty or "close" not in df.columns:
        return None

    close = pd.to_numeric(df["close"], errors="coerce").dropna()

    if close.empty:
        return None

    return float(close.iloc[-1])


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

    zone_low = min(entry_aggressive, entry_prudent)
    zone_high = max(entry_aggressive, entry_prudent)

    return {
        "atr": atr,
        "atr_pct": atr / price if price else None,
        "entry_aggressive": entry_aggressive,
        "entry_prudent": entry_prudent,
        "zone_low": zone_low,
        "zone_high": zone_high,
        "stop_short": stop_short,
        "stop_structural": stop_structural,
        "target_1": target_1,
        "target_2": target_2,
        "risk_regime": plan.get("risk_regime", "N/A"),
    }


def get_returns(price_data: pd.DataFrame) -> pd.Series:
    df = prepare_price_frame(price_data)

    if df.empty or "close" not in df.columns:
        return pd.Series(dtype=float)

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    returns = close.pct_change().dropna()

    return returns.replace([np.inf, -np.inf], np.nan).dropna()


def get_mc_paths(analysis: dict) -> np.ndarray | None:
    paths = analysis.get("monte_carlo_paths") if isinstance(analysis, dict) else None

    if paths is None:
        return None

    try:
        arr = np.asarray(paths, dtype=float)

        if arr.ndim != 2 or arr.shape[0] < 2 or arr.shape[1] < 10:
            return None

        return arr
    except Exception:
        return None


def get_mc_advanced_table(analysis: dict) -> pd.DataFrame:
    table = analysis.get("mc_advanced_table", pd.DataFrame()) if isinstance(analysis, dict) else pd.DataFrame()

    if not isinstance(table, pd.DataFrame) or table.empty:
        return pd.DataFrame()

    return table.copy()


def select_mc_row(analysis: dict, horizon: int) -> tuple[pd.Series | dict, pd.DataFrame]:
    table = get_mc_advanced_table(analysis)

    if table.empty:
        return {}, table

    if "Horizon" not in table.columns:
        return table.iloc[0], table

    horizon_label = f"{horizon}D"
    match = table[table["Horizon"].astype(str) == horizon_label]

    if match.empty:
        # Never label a row from another horizon as if it matched the request.
        return {}, table

    return match.iloc[0], table


def mc_row_value(mc_row, key: str, default=None):
    try:
        if isinstance(mc_row, pd.Series):
            return safe_float(mc_row.get(key), default)
        if isinstance(mc_row, dict):
            return safe_float(mc_row.get(key), default)
    except Exception:
        pass

    return default


# ============================================================
# RISK COMPUTATION
# ============================================================

def historical_var_es(returns: pd.Series, horizon: int = 30) -> dict:
    returns = pd.to_numeric(returns, errors="coerce").dropna()

    if returns.empty or len(returns) < 30:
        return {
            "hist_var_95": None,
            "hist_var_99": None,
            "hist_es_95": None,
            "hist_es_99": None,
            "hist_vol": None,
        }

    daily = returns.copy()
    hist_vol = float(daily.std() * np.sqrt(252))

    # Méthode premium : rendements glissants réels sur l'horizon.
    # Fallback prudent si historique insuffisant.
    if len(daily) >= horizon + 30:
        horizon_returns = (
            (1 + daily)
            .rolling(window=horizon)
            .apply(np.prod, raw=True)
            .dropna()
            - 1
        )
    else:
        scale = np.sqrt(max(horizon, 1))
        horizon_returns = daily * scale

    horizon_returns = pd.to_numeric(horizon_returns, errors="coerce").dropna()

    if horizon_returns.empty:
        return {
            "hist_var_95": None,
            "hist_var_99": None,
            "hist_es_95": None,
            "hist_es_99": None,
            "hist_vol": hist_vol,
        }

    var_95 = float(np.percentile(horizon_returns, 5))
    var_99 = float(np.percentile(horizon_returns, 1))

    tail_95 = horizon_returns[horizon_returns <= var_95]
    tail_99 = horizon_returns[horizon_returns <= var_99]

    es_95 = float(tail_95.mean()) if not tail_95.empty else var_95
    es_99 = float(tail_99.mean()) if not tail_99.empty else var_99

    return {
        "hist_var_95": var_95,
        "hist_var_99": var_99,
        "hist_es_95": es_95,
        "hist_es_99": es_99,
        "hist_vol": hist_vol,
    }


def mc_risk_metrics(paths: np.ndarray | None, price: float, plan: dict, horizon: int) -> dict:
    if paths is None or price in [None, 0]:
        return {
            "mc_available": False,
            "final_returns": np.array([]),
            "final_prices": np.array([]),
            "min_prices": np.array([]),
            "max_prices": np.array([]),
            "mc_var_95": None,
            "mc_var_99": None,
            "mc_es_95": None,
            "mc_es_99": None,
            "mc_p5_price": None,
            "mc_p25_price": None,
            "mc_p50_price": None,
            "mc_p75_price": None,
            "mc_p95_price": None,
            "prob_finish_loss": None,
            "prob_loss_5": None,
            "prob_loss_10": None,
            "prob_stop_short": None,
            "prob_stop_structural": None,
            "prob_target_1": None,
            "prob_target_2": None,
            "expected_return": None,
            "median_return": None,
            "worst_path_drawdown": None,
        }

    usable_paths = paths.copy()

    # Si le Monte Carlo standard est 30D et l'utilisateur demande 7D,
    # on coupe prudemment. Si horizon > longueur, on prend la longueur disponible.
    max_idx = min(horizon, usable_paths.shape[0] - 1)
    sub_paths = usable_paths[: max_idx + 1, :]

    final_prices = sub_paths[-1, :]
    min_prices = sub_paths.min(axis=0)
    max_prices = sub_paths.max(axis=0)
    final_returns = final_prices / price - 1

    var_95 = float(np.percentile(final_returns, 5))
    var_99 = float(np.percentile(final_returns, 1))

    tail_95 = final_returns[final_returns <= var_95]
    tail_99 = final_returns[final_returns <= var_99]

    es_95 = float(tail_95.mean()) if len(tail_95) else var_95
    es_99 = float(tail_99.mean()) if len(tail_99) else var_99

    path_drawdowns = sub_paths / np.maximum.accumulate(sub_paths, axis=0) - 1
    worst_path_drawdown = float(np.percentile(path_drawdowns.min(axis=0), 5))

    stop_short = safe_float(plan.get("stop_short"))
    stop_structural = safe_float(plan.get("stop_structural"))
    target_1 = safe_float(plan.get("target_1"))
    target_2 = safe_float(plan.get("target_2"))

    return {
        "mc_available": True,
        "final_returns": final_returns,
        "final_prices": final_prices,
        "min_prices": min_prices,
        "max_prices": max_prices,
        "mc_var_95": var_95,
        "mc_var_99": var_99,
        "mc_es_95": es_95,
        "mc_es_99": es_99,
        "mc_p5_price": float(np.percentile(final_prices, 5)),
        "mc_p25_price": float(np.percentile(final_prices, 25)),
        "mc_p50_price": float(np.percentile(final_prices, 50)),
        "mc_p75_price": float(np.percentile(final_prices, 75)),
        "mc_p95_price": float(np.percentile(final_prices, 95)),
        "prob_finish_loss": float(np.mean(final_prices < price)),
        "prob_loss_5": float(np.mean(final_prices <= price * 0.95)),
        "prob_loss_10": float(np.mean(final_prices <= price * 0.90)),
        "prob_stop_short": float(np.mean(min_prices <= stop_short)) if stop_short else None,
        "prob_stop_structural": float(np.mean(min_prices <= stop_structural)) if stop_structural else None,
        "prob_target_1": float(np.mean(max_prices >= target_1)) if target_1 else None,
        "prob_target_2": float(np.mean(max_prices >= target_2)) if target_2 else None,
        "expected_return": float(np.mean(final_returns)),
        "median_return": float(np.median(final_returns)),
        "worst_path_drawdown": worst_path_drawdown,
    }


def mc_advanced_metrics(analysis: dict, horizon: int) -> dict:
    row, table = select_mc_row(analysis, horizon)

    row_missing = (
        row is None
        or (isinstance(row, dict) and len(row) == 0)
        or (isinstance(row, pd.Series) and row.empty)
    )

    if row_missing:
        return {
            "mc_score": None,
            "prob_positive": None,
            "prob_loss_5": None,
            "prob_stop_short": None,
            "prob_stop_structural": None,
            "prob_target_1": None,
            "prob_target_2": None,
            "expected_return": None,
            "median_return": None,
            "asymmetry": None,
            "p5": None,
            "p50": None,
            "p95": None,
            "table": table,
        }

    return {
        "mc_score": mc_row_value(row, "MC Score"),
        "prob_positive": mc_row_value(row, "Prob finir positif"),
        "prob_loss_5": mc_row_value(row, "Prob perte > 5%"),
        "prob_stop_short": mc_row_value(row, "Prob toucher stop court"),
        "prob_stop_structural": mc_row_value(row, "Prob toucher stop structurel"),
        "prob_target_1": mc_row_value(row, "Prob toucher Target 1"),
        "prob_target_2": mc_row_value(row, "Prob toucher Target 2"),
        "expected_return": mc_row_value(row, "Expected Return"),
        "median_return": mc_row_value(row, "Median Return"),
        "asymmetry": mc_row_value(row, "Asymétrie T1/Stop"),
        "p5": mc_row_value(row, "P5"),
        "p50": mc_row_value(row, "P50"),
        "p95": mc_row_value(row, "P95"),
        "table": table,
    }


def calculate_price_levels_from_returns(price: float, metrics: dict) -> dict:
    levels = {}

    for key in ["hist_var_95", "hist_var_99", "hist_es_95", "hist_es_99", "mc_var_95", "mc_var_99", "mc_es_95", "mc_es_99"]:
        value = metrics.get(key)

        if value is None or price is None:
            levels[f"{key}_price"] = None
        else:
            levels[f"{key}_price"] = price * (1 + value)

    return levels


def score_volatility_risk(volatility: float | None, atr_pct: float | None) -> float:
    score = 25

    if volatility is not None:
        if volatility >= 0.75:
            score += 45
        elif volatility >= 0.55:
            score += 32
        elif volatility >= 0.35:
            score += 20
        elif volatility >= 0.22:
            score += 10
        else:
            score += 2

    if atr_pct is not None:
        if atr_pct >= 0.06:
            score += 25
        elif atr_pct >= 0.04:
            score += 16
        elif atr_pct >= 0.025:
            score += 8
        else:
            score += 2

    return clamp(score)


def score_tail_risk(mc_es_95: float | None, hist_es_95: float | None, worst_dd: float | None) -> float:
    score = 25

    candidates = [x for x in [mc_es_95, hist_es_95] if x is not None]
    tail = min(candidates) if candidates else None

    if tail is not None:
        abs_tail = abs(tail)

        if abs_tail >= 0.20:
            score += 45
        elif abs_tail >= 0.14:
            score += 34
        elif abs_tail >= 0.09:
            score += 22
        elif abs_tail >= 0.05:
            score += 10
        else:
            score += 2

    if worst_dd is not None:
        abs_dd = abs(worst_dd)

        if abs_dd >= 0.30:
            score += 25
        elif abs_dd >= 0.20:
            score += 16
        elif abs_dd >= 0.12:
            score += 8

    return clamp(score)


def score_stop_risk(prob_stop_short: float | None, prob_stop_structural: float | None) -> float:
    score = 20

    if prob_stop_short is not None:
        if prob_stop_short >= 0.60:
            score += 55
        elif prob_stop_short >= 0.50:
            score += 45
        elif prob_stop_short >= 0.40:
            score += 32
        elif prob_stop_short >= 0.30:
            score += 18
        else:
            score += 5

    if prob_stop_structural is not None:
        if prob_stop_structural >= 0.40:
            score += 20
        elif prob_stop_structural >= 0.25:
            score += 12
        elif prob_stop_structural >= 0.15:
            score += 6

    return clamp(score)


def score_drawdown_risk(max_drawdown: float | None, distance_high_52w: float | None) -> float:
    score = 25

    if max_drawdown is not None:
        dd = abs(max_drawdown)

        if dd >= 0.45:
            score += 45
        elif dd >= 0.30:
            score += 32
        elif dd >= 0.20:
            score += 20
        elif dd >= 0.12:
            score += 10

    if distance_high_52w is not None:
        if distance_high_52w > -0.03:
            score += 12
        elif distance_high_52w > -0.08:
            score += 6

    return clamp(score)


def score_asymmetry_risk(prob_target_1: float | None, prob_stop_short: float | None, expected_return: float | None) -> float:
    # Ici score élevé = risque d'asymétrie défavorable.
    score = 50

    if prob_target_1 is not None and prob_stop_short is not None:
        spread = prob_target_1 - prob_stop_short

        if spread >= 0.20:
            score -= 25
        elif spread >= 0.10:
            score -= 15
        elif spread >= 0.00:
            score -= 5
        elif spread >= -0.10:
            score += 15
        else:
            score += 30

    if expected_return is not None:
        if expected_return >= 0.04:
            score -= 12
        elif expected_return > 0:
            score -= 5
        elif expected_return <= 0:
            score += 18

    return clamp(score)


def data_confidence_score(price_data: pd.DataFrame, analysis: dict, paths: np.ndarray | None, mc_table: pd.DataFrame) -> float:
    score = 25

    df = prepare_price_frame(price_data)

    if not df.empty:
        if len(df) >= 220:
            score += 25
        elif len(df) >= 120:
            score += 18
        elif len(df) >= 60:
            score += 10

    if paths is not None:
        score += 20

    if isinstance(mc_table, pd.DataFrame) and not mc_table.empty:
        score += 15

    if isinstance(analysis.get("trading_plan"), dict) and analysis.get("trading_plan"):
        score += 15

    if isinstance(analysis.get("momentum_v2"), dict) and analysis.get("momentum_v2"):
        score += 10

    return clamp(score)


def overall_risk_state(score: float, stop_risk: float, tail_risk: float, data_score: float) -> str:
    """
    État de risque final.
    Important : le score composite ne suffit pas.
    Un tail risk élevé ou un stop risk élevé doit pouvoir surclasser le score moyen.
    """

    score = safe_float(score, 0) or 0
    stop_risk = safe_float(stop_risk, 0) or 0
    tail_risk = safe_float(tail_risk, 0) or 0
    data_score = safe_float(data_score, 0) or 0

    if data_score < 45:
        return "DATA_LIMITED"

    # Veto risque critique
    if tail_risk >= 88 or stop_risk >= 88:
        return "NO_TRADE_RISK"

    # Overrides prudents
    if tail_risk >= 75 and stop_risk >= 55:
        return "ELEVATED_RISK"

    if tail_risk >= 75 and score >= 48:
        return "ELEVATED_RISK"

    if stop_risk >= 65 and score >= 48:
        return "ELEVATED_RISK"

    if tail_risk >= 80:
        return "ELEVATED_RISK"

    if score >= 75:
        return "HIGH_RISK"

    if score >= 55:
        return "ELEVATED_RISK"

    if score >= 42:
        return "MODERATE_RISK"

    return "CONTROLLED_RISK"


def risk_state_label(state: str) -> str:
    mapping = {
        "CONTROLLED_RISK": "Contrôlé",
        "MODERATE_RISK": "Modéré",
        "ELEVATED_RISK": "Élevé",
        "HIGH_RISK": "Très élevé",
        "NO_TRADE_RISK": "Risque bloquant",
        "DATA_LIMITED": "Données limitées",
    }
    return mapping.get(state, state)


def apply_risk_state_guardrails(ctx: dict, base_state: str) -> str:
    """
    Calibrage final de l'état de risque avec les mêmes guardrails
    que ceux utilisés pour réduire le risk budget.

    Objectif : éviter Modéré + 0.25R quand les métriques brutes
    indiquent déjà un risque d'exécution élevé.
    """
    data_score = safe_float(ctx.get("data_confidence_score"), 0) or 0
    tail_risk = safe_float(ctx.get("tail_risk_score"), 0) or 0
    stop_risk = safe_float(ctx.get("stop_risk_score"), 0) or 0

    mc_es95 = safe_float(ctx.get("mc_es_95"))
    prob_stop = safe_float(ctx.get("prob_stop_short"))
    price_position = ctx.get("price_position_key")

    if data_score < 45:
        return "DATA_LIMITED"

    if tail_risk >= 88 or stop_risk >= 88:
        return "NO_TRADE_RISK"

    elevated_flags = 0

    if mc_es95 is not None and mc_es95 <= -0.18:
        elevated_flags += 1

    if prob_stop is not None and prob_stop >= 0.45:
        elevated_flags += 1

    if price_position == "ABOVE_ZONE":
        elevated_flags += 1

    if tail_risk >= 70:
        elevated_flags += 1

    if stop_risk >= 60:
        elevated_flags += 1

    # Deux alertes fortes suffisent à surclasser Modéré vers Élevé.
    if elevated_flags >= 2 and base_state in ["CONTROLLED_RISK", "MODERATE_RISK"]:
        return "ELEVATED_RISK"

    return base_state


def risk_state_reason(ctx: dict) -> str:
    tail = safe_float(ctx.get("tail_risk_score"), 0) or 0
    stop = safe_float(ctx.get("stop_risk_score"), 0) or 0
    score = safe_float(ctx.get("overall_risk_score"), 0) or 0
    data = safe_float(ctx.get("data_confidence_score"), 0) or 0

    mc_es95 = safe_float(ctx.get("mc_es_95"))
    prob_stop = safe_float(ctx.get("prob_stop_short"))
    price_position = ctx.get("price_position_key")
    base_state = ctx.get("base_risk_state")
    final_state = ctx.get("risk_state")

    if data < 45:
        return "Données insuffisantes pour valider pleinement le risque."

    if tail >= 88 or stop >= 88:
        return "Veto risque : tail risk ou stop risk critique."

    raw_flags = []

    if mc_es95 is not None and mc_es95 <= -0.18:
        raw_flags.append("MC ES95 très défavorable")

    if prob_stop is not None and prob_stop >= 0.45:
        raw_flags.append("probabilité de stop supérieure à 45%")

    if price_position == "ABOVE_ZONE":
        raw_flags.append("prix au-dessus de la zone d'entrée")

    if tail >= 70:
        raw_flags.append("tail risk élevé")

    if stop >= 60:
        raw_flags.append("stop risk significatif")

    if final_state == "ELEVATED_RISK" and base_state in ["CONTROLLED_RISK", "MODERATE_RISK"] and len(raw_flags) >= 2:
        return "Override prudent : " + " + ".join(raw_flags[:3]) + "."

    if tail >= 75 and stop >= 55:
        return "Override prudent : tail risk élevé combiné à un stop risk significatif."

    if tail >= 75 and score >= 48:
        return "Override prudent : tail risk élevé malgré un score composite moyen."

    if stop >= 65 and score >= 48:
        return "Override prudent : probabilité de stop élevée."

    if score >= 75:
        return "Score composite de risque très élevé."

    if score >= 55:
        return "Score composite de risque élevé."

    if score >= 42:
        return "Risque composite modéré."

    return "Risque composite contrôlé."

def risk_budget_from_state(ctx: dict) -> tuple[str, float]:
    state = ctx["risk_state"]
    overall = ctx["overall_risk_score"]
    stop_prob = ctx["prob_stop_short"]
    tail = ctx["mc_es_95"] if ctx["mc_es_95"] is not None else ctx["hist_es_95"]
    price_position = ctx["price_position_key"]

    if state in ["NO_TRADE_RISK", "DATA_LIMITED"]:
        return "0R", 0.0

    budget = 1.0

    if state == "HIGH_RISK":
        budget *= 0.25
    elif state == "ELEVATED_RISK":
        budget *= 0.50
    elif state == "MODERATE_RISK":
        budget *= 0.75

    if stop_prob is not None:
        if stop_prob >= 0.55:
            budget *= 0.35
        elif stop_prob >= 0.45:
            budget *= 0.55
        elif stop_prob >= 0.35:
            budget *= 0.75

    if tail is not None:
        if tail <= -0.18:
            budget *= 0.40
        elif tail <= -0.12:
            budget *= 0.60
        elif tail <= -0.08:
            budget *= 0.80

    if price_position == "ABOVE_ZONE":
        budget *= 0.50
    elif price_position == "INVALIDATED":
        return "0R", 0.0

    if overall >= 80:
        budget *= 0.50

    budget = max(0.0, min(1.0, budget))

    if budget >= 0.85:
        return "1.00R", budget
    if budget >= 0.60:
        return "0.75R", budget
    if budget >= 0.35:
        return "0.50R", budget
    if budget > 0:
        return "0.25R", budget

    return "0R", 0.0


def price_position_key(price: float, plan: dict) -> tuple[str, str]:
    if price <= plan["stop_short"]:
        return "INVALIDATED", "Sous stop court"
    if plan["zone_low"] <= price <= plan["zone_high"]:
        return "IN_ZONE", "Dans la zone"
    if price > plan["zone_high"]:
        return "ABOVE_ZONE", "Au-dessus de la zone"
    return "BELOW_ZONE", "Sous la zone"


def build_stress_tests(ctx: dict) -> pd.DataFrame:
    price = ctx["price"]
    stop_short = ctx["stop_short"]
    stop_structural = ctx["stop_structural"]
    target_1 = ctx["target_1"]
    atr = ctx["atr"]

    scenarios = [
        ("Shock -3%", -0.03, "Stress court terme modéré"),
        ("Shock -5%", -0.05, "Stress court terme significatif"),
        ("Shock -8%", -0.08, "Stress type gap / earnings"),
        ("Shock -10%", -0.10, "Stress sévère"),
        ("Shock -15%", -0.15, "Stress extrême"),
    ]

    if atr and price:
        scenarios.extend([
            ("Move -1 ATR", -atr / price, "Baisse équivalente à 1 ATR"),
            ("Move -2 ATR", -2 * atr / price, "Baisse équivalente à 2 ATR"),
        ])

    rows = []

    for name, shock, description in scenarios:
        stressed_price = price * (1 + shock)

        stop_short_hit = stressed_price <= stop_short if stop_short is not None else False
        stop_struct_hit = stressed_price <= stop_structural if stop_structural is not None else False

        distance_to_short = stressed_price / stop_short - 1 if stop_short not in [None, 0] else None
        distance_to_struct = stressed_price / stop_structural - 1 if stop_structural not in [None, 0] else None
        rebound_to_target = target_1 / stressed_price - 1 if target_1 not in [None, 0] and stressed_price else None

        if stop_struct_hit:
            state = "Structure cassée"
            severity = "Bloquant"
        elif stop_short_hit:
            state = "Stop court touché"
            severity = "Élevé"
        elif shock <= -0.10:
            state = "Stress sévère"
            severity = "Élevé"
        elif shock <= -0.05:
            state = "Stress significatif"
            severity = "Modéré"
        else:
            state = "Stress contenu"
            severity = "Info"

        rows.append({
            "Scénario": name,
            "Prix stressé": stressed_price,
            "Choc": shock,
            "Distance stop court": distance_to_short,
            "Distance stop structurel": distance_to_struct,
            "Rebond requis vers Target 1": rebound_to_target,
            "Stop court touché": "Oui" if stop_short_hit else "Non",
            "Stop structurel touché": "Oui" if stop_struct_hit else "Non",
            "État": state,
            "Sévérité": severity,
            "Lecture": description,
        })

    return pd.DataFrame(rows)


def build_risk_context_v2(ticker: str, price_data: pd.DataFrame, analysis: dict, horizon: int) -> dict:
    price = first_numeric(
        analysis.get("latest_price") if isinstance(analysis, dict) else None,
        get_last_price_from_frame(price_data),
        default=0,
    )

    plan = get_trading_plan(analysis, price)
    returns = get_returns(price_data)
    paths = get_mc_paths(analysis)
    mc_row, mc_table = select_mc_row(analysis, horizon)

    hist = historical_var_es(returns, horizon=horizon)
    mc_raw = mc_risk_metrics(paths, price, plan, horizon=horizon)
    mc_adv = mc_advanced_metrics(analysis, horizon)

    # Priorité aux métriques avancées quand elles existent, fallback MC standard.
    prob_stop_short = first_numeric(mc_adv.get("prob_stop_short"), mc_raw.get("prob_stop_short"))
    prob_stop_structural = first_numeric(mc_adv.get("prob_stop_structural"), mc_raw.get("prob_stop_structural"))
    prob_target_1 = first_numeric(mc_adv.get("prob_target_1"), mc_raw.get("prob_target_1"))
    prob_target_2 = first_numeric(mc_adv.get("prob_target_2"), mc_raw.get("prob_target_2"))
    prob_loss_5 = first_numeric(mc_adv.get("prob_loss_5"), mc_raw.get("prob_loss_5"))
    expected_return = first_numeric(mc_adv.get("expected_return"), mc_raw.get("expected_return"))
    median_return = first_numeric(mc_adv.get("median_return"), mc_raw.get("median_return"))

    levels_52w = analysis.get("levels_52w", {}) if isinstance(analysis, dict) else {}

    volatility = first_numeric(
        analysis.get("effective_volatility"),
        analysis.get("volatility"),
        hist.get("hist_vol"),
        default=None,
    )

    max_drawdown = first_numeric(analysis.get("max_drawdown"), default=None)
    distance_high = first_numeric(levels_52w.get("distance_high"), default=None)
    distance_low = first_numeric(levels_52w.get("distance_low"), default=None)

    level_returns = {
        **hist,
        "mc_var_95": mc_raw.get("mc_var_95"),
        "mc_var_99": mc_raw.get("mc_var_99"),
        "mc_es_95": mc_raw.get("mc_es_95"),
        "mc_es_99": mc_raw.get("mc_es_99"),
    }

    price_levels = calculate_price_levels_from_returns(price, level_returns)

    vol_risk = score_volatility_risk(volatility, plan.get("atr_pct"))
    tail_risk = score_tail_risk(mc_raw.get("mc_es_95"), hist.get("hist_es_95"), mc_raw.get("worst_path_drawdown"))
    stop_risk = score_stop_risk(prob_stop_short, prob_stop_structural)
    drawdown_risk = score_drawdown_risk(max_drawdown, distance_high)
    asymmetry_risk = score_asymmetry_risk(prob_target_1, prob_stop_short, expected_return)
    data_score = data_confidence_score(price_data, analysis, paths, mc_table)

    overall = clamp(
        0.22 * vol_risk
        + 0.24 * tail_risk
        + 0.24 * stop_risk
        + 0.12 * drawdown_risk
        + 0.12 * asymmetry_risk
        + 0.06 * (100 - data_score)
    )

    pos_key, pos_label = price_position_key(price, plan)

    ctx = {
        "ticker": ticker,
        "horizon": horizon,
        "horizon_label": f"{horizon}D",
        "price": price,
        "price_position_key": pos_key,
        "price_position": pos_label,
        "atr": plan["atr"],
        "atr_pct": plan["atr_pct"],
        "zone_low": plan["zone_low"],
        "zone_high": plan["zone_high"],
        "stop_short": plan["stop_short"],
        "stop_structural": plan["stop_structural"],
        "target_1": plan["target_1"],
        "target_2": plan["target_2"],
        "volatility": volatility,
        "daily_vol": volatility / np.sqrt(252) if volatility is not None else None,
        "max_drawdown": max_drawdown,
        "distance_high_52w": distance_high,
        "distance_low_52w": distance_low,
        "raw_signal": analysis.get("signal", "N/A") if isinstance(analysis, dict) else "N/A",
        "quant_score": first_numeric(analysis.get("global_score"), analysis.get("score"), default=None),
        "risk_regime": plan.get("risk_regime", "N/A"),
        "paths": paths,
        "mc_table": mc_table,
        "mc_score": first_numeric(mc_adv.get("mc_score"), default=None),
        "prob_positive": first_numeric(mc_adv.get("prob_positive"), 1 - mc_raw.get("prob_finish_loss") if mc_raw.get("prob_finish_loss") is not None else None),
        "prob_finish_loss": first_numeric(mc_raw.get("prob_finish_loss"), default=None),
        "prob_loss_5": prob_loss_5,
        "prob_loss_10": mc_raw.get("prob_loss_10"),
        "prob_stop_short": prob_stop_short,
        "prob_stop_structural": prob_stop_structural,
        "prob_target_1": prob_target_1,
        "prob_target_2": prob_target_2,
        "expected_return": expected_return,
        "median_return": median_return,
        "asymmetry": first_numeric(mc_adv.get("asymmetry"), None if prob_target_1 is None or prob_stop_short is None else prob_target_1 - prob_stop_short),
        "mc_p5_price": first_numeric(mc_adv.get("p5"), mc_raw.get("mc_p5_price")),
        "mc_p50_price": first_numeric(mc_adv.get("p50"), mc_raw.get("mc_p50_price")),
        "mc_p95_price": first_numeric(mc_adv.get("p95"), mc_raw.get("mc_p95_price")),
        "mc_p25_price": mc_raw.get("mc_p25_price"),
        "mc_p75_price": mc_raw.get("mc_p75_price"),
        "final_returns": mc_raw.get("final_returns"),
        "final_prices": mc_raw.get("final_prices"),
        "worst_path_drawdown": mc_raw.get("worst_path_drawdown"),
        **hist,
        **{
            "mc_var_95": mc_raw.get("mc_var_95"),
            "mc_var_99": mc_raw.get("mc_var_99"),
            "mc_es_95": mc_raw.get("mc_es_95"),
            "mc_es_99": mc_raw.get("mc_es_99"),
        },
        **price_levels,
        "volatility_risk_score": vol_risk,
        "tail_risk_score": tail_risk,
        "stop_risk_score": stop_risk,
        "drawdown_risk_score": drawdown_risk,
        "asymmetry_risk_score": asymmetry_risk,
        "data_confidence_score": data_score,
        "overall_risk_score": overall,
    }

    base_state = overall_risk_state(overall, stop_risk, tail_risk, data_score)
    state = apply_risk_state_guardrails(ctx, base_state)

    ctx["base_risk_state"] = base_state
    ctx["risk_state"] = state
    ctx["risk_state_label"] = risk_state_label(state)
    ctx["risk_state_reason"] = risk_state_reason(ctx)

    budget_label, budget_value = risk_budget_from_state(ctx)
    ctx["risk_budget_label"] = budget_label
    ctx["risk_budget"] = budget_value

    ctx["stress_tests"] = build_stress_tests(ctx)

    return ctx


# ============================================================
# TABLE BUILDERS
# ============================================================

def build_risk_decomposition_table(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Pilier": "Volatility Risk",
            "Score risque": fmt_score(ctx["volatility_risk_score"]),
            "Statut": "Élevé" if ctx["volatility_risk_score"] >= 70 else "Modéré" if ctx["volatility_risk_score"] >= 45 else "Contrôlé",
            "Driver": f"Vol annualisée {fmt_pct(ctx['volatility'])} · ATR% {fmt_pct(ctx['atr_pct'])}",
            "Action": "Réduire taille si ATR% élevé" if ctx["volatility_risk_score"] >= 55 else "Surveiller",
        },
        {
            "Pilier": "Tail Risk",
            "Score risque": fmt_score(ctx["tail_risk_score"]),
            "Statut": "Élevé" if ctx["tail_risk_score"] >= 70 else "Modéré" if ctx["tail_risk_score"] >= 45 else "Contrôlé",
            "Driver": f"MC ES95 {fmt_pct(ctx['mc_es_95'])} · Hist ES95 {fmt_pct(ctx['hist_es_95'])} · Worst DD MC {fmt_pct(ctx['worst_path_drawdown'])}",
            "Action": "Limiter risque par trade" if ctx["tail_risk_score"] >= 55 else "Surveiller",
        },
        {
            "Pilier": "Stop Risk",
            "Score risque": fmt_score(ctx["stop_risk_score"]),
            "Statut": "Élevé" if ctx["stop_risk_score"] >= 70 else "Modéré" if ctx["stop_risk_score"] >= 45 else "Contrôlé",
            "Driver": f"Stop court {fmt_pct(ctx['prob_stop_short'])} · Stop structurel {fmt_pct(ctx['prob_stop_structural'])}",
            "Action": "Attendre meilleur prix / réduire taille" if ctx["prob_stop_short"] is not None and ctx["prob_stop_short"] >= 0.45 else "Conserver",
        },
        {
            "Pilier": "Drawdown Risk",
            "Score risque": fmt_score(ctx["drawdown_risk_score"]),
            "Statut": "Élevé" if ctx["drawdown_risk_score"] >= 70 else "Modéré" if ctx["drawdown_risk_score"] >= 45 else "Contrôlé",
            "Driver": f"Max drawdown {fmt_pct(ctx['max_drawdown'])} · Distance high 52W {fmt_pct(ctx['distance_high_52w'])}",
            "Action": "Attention aux achats proches des highs" if ctx["distance_high_52w"] is not None and ctx["distance_high_52w"] > -0.05 else "Surveiller",
        },
        {
            "Pilier": "Asymmetry Risk",
            "Score risque": fmt_score(ctx["asymmetry_risk_score"]),
            "Statut": "Défavorable" if ctx["asymmetry_risk_score"] >= 65 else "Acceptable" if ctx["asymmetry_risk_score"] >= 40 else "Favorable",
            "Driver": f"Target1 {fmt_pct(ctx['prob_target_1'])} · Stop {fmt_pct(ctx['prob_stop_short'])} · Asym {fmt_pp(ctx['asymmetry'])}",
            "Action": "Pas de taille normale si asymétrie faible" if ctx["asymmetry_risk_score"] >= 60 else "Asymétrie exploitable",
        },
        {
            "Pilier": "Data Risk",
            "Score risque": fmt_score(100 - ctx["data_confidence_score"]),
            "Statut": "OK" if ctx["data_confidence_score"] >= 70 else "Partiel",
            "Driver": f"Confidence {fmt_score(ctx['data_confidence_score'])} · MC {'OK' if ctx['paths'] is not None else 'N/A'} · Plan OK",
            "Action": "Ne pas confirmer si données faibles" if ctx["data_confidence_score"] < 60 else "OK",
        },
    ]

    return pd.DataFrame(rows)


def build_var_es_table(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Métrique": "Historical VaR 95",
            "Return": fmt_pct(ctx["hist_var_95"]),
            "Prix implicite": fmt_price(ctx["hist_var_95_price"]),
            "Lecture": "Seuil de perte historique défavorable sur l'horizon sélectionné.",
        },
        {
            "Métrique": "Historical ES 95",
            "Return": fmt_pct(ctx["hist_es_95"]),
            "Prix implicite": fmt_price(ctx["hist_es_95_price"]),
            "Lecture": "Perte moyenne historique au-delà de la VaR 95.",
        },
        {
            "Métrique": "Historical VaR 99",
            "Return": fmt_pct(ctx["hist_var_99"]),
            "Prix implicite": fmt_price(ctx["hist_var_99_price"]),
            "Lecture": "Seuil de perte historique extrême.",
        },
        {
            "Métrique": "Historical ES 99",
            "Return": fmt_pct(ctx["hist_es_99"]),
            "Prix implicite": fmt_price(ctx["hist_es_99_price"]),
            "Lecture": "Perte moyenne historique au-delà de la VaR 99.",
        },
        {
            "Métrique": "Monte Carlo VaR 95",
            "Return": fmt_pct(ctx["mc_var_95"]),
            "Prix implicite": fmt_price(ctx["mc_var_95_price"]),
            "Lecture": "Seuil de perte simulé défavorable.",
        },
        {
            "Métrique": "Monte Carlo ES 95",
            "Return": fmt_pct(ctx["mc_es_95"]),
            "Prix implicite": fmt_price(ctx["mc_es_95_price"]),
            "Lecture": "Perte moyenne simulée dans le mauvais 5%.",
        },
        {
            "Métrique": "Monte Carlo VaR 99",
            "Return": fmt_pct(ctx["mc_var_99"]),
            "Prix implicite": fmt_price(ctx["mc_var_99_price"]),
            "Lecture": "Seuil simulé extrême.",
        },
        {
            "Métrique": "Monte Carlo ES 99",
            "Return": fmt_pct(ctx["mc_es_99"]),
            "Prix implicite": fmt_price(ctx["mc_es_99_price"]),
            "Lecture": "Perte moyenne simulée dans le mauvais 1%.",
        },
    ]

    return pd.DataFrame(rows)


def build_barrier_table(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Barrière": "Stop court",
            "Niveau": fmt_price(ctx["stop_short"]),
            "Probabilité touchée": fmt_pct(ctx["prob_stop_short"]),
            "Distance actuelle": fmt_pct(ctx["stop_short"] / ctx["price"] - 1 if ctx["price"] else None),
            "Lecture": "Risque d'invalidation rapide.",
        },
        {
            "Barrière": "Stop structurel",
            "Niveau": fmt_price(ctx["stop_structural"]),
            "Probabilité touchée": fmt_pct(ctx["prob_stop_structural"]),
            "Distance actuelle": fmt_pct(ctx["stop_structural"] / ctx["price"] - 1 if ctx["price"] else None),
            "Lecture": "Risque d'invalidation large.",
        },
        {
            "Barrière": "Target 1",
            "Niveau": fmt_price(ctx["target_1"]),
            "Probabilité touchée": fmt_pct(ctx["prob_target_1"]),
            "Distance actuelle": fmt_pct(ctx["target_1"] / ctx["price"] - 1 if ctx["price"] else None),
            "Lecture": "Probabilité d'atteindre le premier objectif.",
        },
        {
            "Barrière": "Target 2",
            "Niveau": fmt_price(ctx["target_2"]),
            "Probabilité touchée": fmt_pct(ctx["prob_target_2"]),
            "Distance actuelle": fmt_pct(ctx["target_2"] / ctx["price"] - 1 if ctx["price"] else None),
            "Lecture": "Probabilité d'atteindre l'objectif étendu.",
        },
    ]

    return pd.DataFrame(rows)


def build_guardrail_table(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Guardrail": "Risk State",
            "Lecture actuelle": ctx["risk_state_label"],
            "Seuil de réduction": "Élevé ou plus",
            "Action": "Limiter taille si état élevé.",
        },
        {
            "Guardrail": "Risk Budget",
            "Lecture actuelle": ctx["risk_budget_label"],
            "Seuil de réduction": "0.25R / 0.50R selon risque",
            "Action": "Taille théorique, pas recommandation personnalisée.",
        },
        {
            "Guardrail": "Stop Probability",
            "Lecture actuelle": fmt_pct(ctx["prob_stop_short"]),
            "Seuil de réduction": "> 45%",
            "Action": "Attendre meilleur prix ou réduire risque.",
        },
        {
            "Guardrail": "MC ES95",
            "Lecture actuelle": fmt_pct(ctx["mc_es_95"]),
            "Seuil de réduction": "< -12%",
            "Action": "Queue de distribution trop défavorable.",
        },
        {
            "Guardrail": "ATR %",
            "Lecture actuelle": fmt_pct(ctx["atr_pct"]),
            "Seuil de réduction": "> 4%",
            "Action": "Volatilité tactique élevée.",
        },
        {
            "Guardrail": "Position prix",
            "Lecture actuelle": ctx["price_position"],
            "Seuil de réduction": "Prix au-dessus zone / invalidé",
            "Action": "Pas de taille normale si mauvais point d'entrée.",
        },
    ]

    return pd.DataFrame(rows)


def build_export_summary(ctx: dict) -> pd.DataFrame:
    rows = [
        ("Ticker", ctx["ticker"]),
        ("Horizon", ctx["horizon_label"]),
        ("Prix actuel", fmt_price(ctx["price"])),
        ("Risk state", ctx["risk_state_label"]),
        ("Risk state reason", ctx.get("risk_state_reason", "N/A")),
        ("Composite risk score", fmt_score(ctx["overall_risk_score"])),
        ("Risk budget", ctx["risk_budget_label"]),
        ("Volatility risk", fmt_score(ctx["volatility_risk_score"])),
        ("Tail risk", fmt_score(ctx["tail_risk_score"])),
        ("Stop risk", fmt_score(ctx["stop_risk_score"])),
        ("Asymmetry risk", fmt_score(ctx["asymmetry_risk_score"])),
        ("Vol annualisée", fmt_pct(ctx["volatility"])),
        ("ATR %", fmt_pct(ctx["atr_pct"])),
        ("Max drawdown", fmt_pct(ctx["max_drawdown"])),
        ("Prob stop court", fmt_pct(ctx["prob_stop_short"])),
        ("Prob stop structurel", fmt_pct(ctx["prob_stop_structural"])),
        ("Prob Target 1", fmt_pct(ctx["prob_target_1"])),
        ("Prob Target 2", fmt_pct(ctx["prob_target_2"])),
        ("Expected return MC", fmt_pct(ctx["expected_return"])),
        ("MC VaR 95", fmt_pct(ctx["mc_var_95"])),
        ("MC ES 95", fmt_pct(ctx["mc_es_95"])),
        ("Hist VaR 95", fmt_pct(ctx["hist_var_95"])),
        ("Hist ES 95", fmt_pct(ctx["hist_es_95"])),
        ("Stop court", fmt_price(ctx["stop_short"])),
        ("Stop structurel", fmt_price(ctx["stop_structural"])),
        ("Target 1", fmt_price(ctx["target_1"])),
        ("Target 2", fmt_price(ctx["target_2"])),
        ("Zone entrée", f"{fmt_price(ctx['zone_low'])} → {fmt_price(ctx['zone_high'])}"),
    ]

    return pd.DataFrame(rows, columns=["Champ", "Valeur"])


# ============================================================
# NARRATIVES
# ============================================================

def risk_message(ctx: dict) -> tuple[str, str]:
    state = ctx["risk_state"]

    if state == "CONTROLLED_RISK":
        return (
            "success",
            "Risque global contrôlé : volatilité, tail risk et probabilité de stop restent compatibles avec un risk budget normal."
        )

    if state == "MODERATE_RISK":
        return (
            "info",
            "Risque modéré : le setup reste exploitable, mais la taille doit tenir compte de la volatilité et du stop."
        )

    if state == "ELEVATED_RISK":
        return (
            "warning",
            "Risque élevé : le setup peut rester intéressant, mais le tail risk, la probabilité de stop ou le prix au-dessus de la zone imposent une taille réduite."
        )

    if state == "HIGH_RISK":
        return (
            "error",
            "Risque très élevé : l'entrée agressive est fragile. Le moteur privilégie une forte réduction du risque ou l'attente."
        )

    if state == "NO_TRADE_RISK":
        return (
            "error",
            "Risque bloquant : au moins un filtre critique de stop ou de tail risk rend l'exécution non acceptable mécaniquement."
        )

    return (
        "warning",
        "Données de risque incomplètes : le moteur limite la confiance dans la lecture."
    )


def main_risk_driver(ctx: dict) -> str:
    drivers = [
        ("Volatilité", ctx["volatility_risk_score"]),
        ("Tail risk", ctx["tail_risk_score"]),
        ("Stop risk", ctx["stop_risk_score"]),
        ("Drawdown", ctx["drawdown_risk_score"]),
        ("Asymétrie", ctx["asymmetry_risk_score"]),
    ]

    drivers = [(name, safe_float(score, 0) or 0) for name, score in drivers]
    drivers = sorted(drivers, key=lambda x: x[1], reverse=True)

    if not drivers:
        return "N/A"

    return drivers[0][0]


def barrier_comment(ctx: dict) -> tuple[str, str]:
    stop = ctx["prob_stop_short"]
    target = ctx["prob_target_1"]

    if stop is None or target is None:
        return "info", "Probabilités de barrière incomplètes."

    spread = target - stop

    if stop >= 0.55:
        return (
            "error",
            "Probabilité de stop court très élevée : le risque tactique domine même si le scénario haussier existe."
        )

    if stop >= 0.45 and spread > 0:
        return (
            "warning",
            "Asymétrie positive mais fragile : Target 1 est plus probable que le stop, mais le stop reste trop fréquent pour une entrée agressive."
        )

    if spread >= 0.20:
        return (
            "success",
            "Asymétrie favorable : la probabilité de Target 1 dépasse nettement celle du stop court."
        )

    if spread >= 0:
        return (
            "info",
            "Asymétrie légèrement positive : exploitable seulement avec discipline sur le sizing."
        )

    return (
        "error",
        "Asymétrie défavorable : la probabilité de stop est supérieure à la probabilité de Target 1."
    )


def stress_summary(ctx: dict) -> tuple[str, str]:
    stress = ctx.get("stress_tests")

    if not isinstance(stress, pd.DataFrame) or stress.empty:
        return "info", "Stress tests indisponibles."

    stop_rows = stress[stress["Stop court touché"] == "Oui"]
    struct_rows = stress[stress["Stop structurel touché"] == "Oui"]

    first_stop = stop_rows.iloc[0]["Scénario"] if not stop_rows.empty else None
    first_struct = struct_rows.iloc[0]["Scénario"] if not struct_rows.empty else None

    if first_struct:
        return (
            "error",
            f"Premier stress structurel critique : {first_struct}. Le stop structurel est cassé dans ce scénario."
        )

    if first_stop:
        return (
            "warning",
            f"Premier stress critique : {first_stop}. Le stop court est touché avant cassure structurelle."
        )

    return (
        "success",
        "Aucun scénario standard ne touche les stops : le stress test reste contenu."
    )



# ============================================================
# CHARTS
# ============================================================

def render_risk_map_chart(ticker: str, price_data: pd.DataFrame, ctx: dict):
    df = prepare_price_frame(price_data).tail(180)

    if df.empty:
        st.info("Graphique indisponible : historique prix vide.")
        return

    fig = go.Figure()

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
            line=dict(color="#f8fafc", width=2),
        ))

    first_date = df["date"].min()
    last_date = df["date"].max()
    future_date = last_date + pd.Timedelta(days=38)

    price = ctx["price"]

    # Zones
    if ctx["stop_structural"] is not None and ctx["stop_short"] is not None:
        fig.add_hrect(
            y0=ctx["stop_structural"],
            y1=ctx["stop_short"],
            x0=first_date,
            x1=future_date,
            fillcolor="rgba(239, 68, 68, 0.09)",
            line_width=0,
            annotation_text="ZONE STOP / INVALIDATION",
            annotation_position="bottom left",
            annotation_font_color="#fecaca",
            annotation_font_size=11,
        )

    if ctx["mc_es_95_price"] is not None and ctx["mc_var_95_price"] is not None:
        y0 = min(ctx["mc_es_95_price"], ctx["mc_var_95_price"])
        y1 = max(ctx["mc_es_95_price"], ctx["mc_var_95_price"])
        fig.add_hrect(
            y0=y0,
            y1=y1,
            x0=first_date,
            x1=future_date,
            fillcolor="rgba(168, 85, 247, 0.09)",
            line_width=0,
            annotation_text="TAIL RISK MC",
            annotation_position="top left",
            annotation_font_color="#ddd6fe",
            annotation_font_size=11,
        )

    fig.add_hrect(
        y0=ctx["zone_low"],
        y1=ctx["zone_high"],
        x0=first_date,
        x1=future_date,
        fillcolor="rgba(30, 120, 255, 0.14)",
        line_width=0,
        annotation_text="ZONE D'ENTRÉE",
        annotation_position="top left",
        annotation_font_color="#bfdbfe",
        annotation_font_size=11,
    )

    levels = [
        ("Target 2", ctx["target_2"], "#16a34a", "dot", 1.2),
        ("Target 1", ctx["target_1"], "#22c55e", "dash", 1.5),
        ("Prix actuel", price, "#f8fafc", "solid", 2.2),
        ("Zone haute", ctx["zone_high"], "#60a5fa", "dash", 1.2),
        ("Zone basse", ctx["zone_low"], "#60a5fa", "dash", 1.2),
        ("Stop court", ctx["stop_short"], "#f59e0b", "dash", 1.4),
        ("Stop structurel", ctx["stop_structural"], "#ef4444", "dot", 1.4),
        ("MC P5", ctx["mc_p5_price"], "#a78bfa", "dash", 1.4),
        ("MC VaR95", ctx["mc_var_95_price"], "#c084fc", "dot", 1.2),
        ("MC ES95", ctx["mc_es_95_price"], "#e879f9", "dot", 1.2),
    ]

    for label, value, color, dash, width in levels:
        value = safe_float(value)

        if value is None:
            continue

        fig.add_hline(
            y=value,
            line_color=color,
            line_dash=dash,
            line_width=width,
            opacity=0.88,
            annotation_text=f"{label} {fmt_price(value)}",
            annotation_position="right",
            annotation_font_color=color,
            annotation_font_size=11,
        )

    msg_type, msg = risk_message(ctx)

    annotation_color = {
        "success": "#22c55e",
        "info": "#38bdf8",
        "warning": "#facc15",
        "error": "#ef4444",
    }.get(msg_type, "#38bdf8")

    fig.add_annotation(
        x=df["date"].iloc[-1],
        y=price,
        text=f"{ctx['risk_state_label']}<br>Budget {ctx['risk_budget_label']}",
        showarrow=True,
        arrowhead=2,
        arrowsize=1,
        arrowwidth=1.6,
        arrowcolor=annotation_color,
        ax=-120,
        ay=-55,
        font=dict(size=12, color="#f8fafc"),
        bgcolor="rgba(15, 23, 42, 0.88)",
        bordercolor=annotation_color,
        borderwidth=1,
        borderpad=6,
    )

    summary_text = (
        f"<b>{ctx['risk_state_label']}</b> · {ctx['risk_budget_label']}<br>"
        f"Risk {fmt_score(ctx['overall_risk_score'])} · Driver {main_risk_driver(ctx)}<br>"
        f"Stop {fmt_pct(ctx['prob_stop_short'])} · ES95 {fmt_pct(ctx['mc_es_95'])}"
    )

    y_top_candidates = [
        df["high"].max() if "high" in df.columns else df["close"].max(),
        ctx["target_2"],
        ctx["target_1"],
        price,
    ]
    y_top_candidates = [safe_float(x) for x in y_top_candidates if safe_float(x) is not None]
    summary_y = max(y_top_candidates) if y_top_candidates else price

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

    y_candidates = [
        df["low"].min() if "low" in df.columns else df["close"].min(),
        ctx["mc_es_95_price"],
        ctx["mc_var_95_price"],
        ctx["mc_p5_price"],
        ctx["stop_structural"],
        ctx["stop_short"],
        ctx["zone_low"],
        ctx["zone_high"],
        price,
        ctx["target_1"],
        ctx["target_2"],
        df["high"].max() if "high" in df.columns else df["close"].max(),
    ]
    y_candidates = [safe_float(x) for x in y_candidates if safe_float(x) is not None]

    if y_candidates:
        y_min = min(y_candidates)
        y_max = max(y_candidates)
        padding = max((y_max - y_min) * 0.08, price * 0.015 if price else 1)
        y_range = [y_min - padding, y_max + padding]
    else:
        y_range = None

    fig.update_layout(
        height=680,
        title=f"Risk Map — {ticker}",
        xaxis_title="Date",
        yaxis_title="Prix",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=220, t=75, b=45),
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

    st.plotly_chart(fig, width="stretch")


def render_mc_risk_cone(ctx: dict):
    paths = ctx.get("paths")

    if paths is None:
        st.info("Monte Carlo paths indisponibles.")
        return

    max_idx = min(ctx["horizon"], paths.shape[0] - 1)
    sub_paths = paths[: max_idx + 1, :]
    x = np.arange(sub_paths.shape[0])

    p05 = np.percentile(sub_paths, 5, axis=1)
    p25 = np.percentile(sub_paths, 25, axis=1)
    p50 = np.percentile(sub_paths, 50, axis=1)
    p75 = np.percentile(sub_paths, 75, axis=1)
    p95 = np.percentile(sub_paths, 95, axis=1)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=x,
        y=p95,
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p05,
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(59, 130, 246, 0.14)",
        line=dict(width=0),
        name="P5-P95",
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p75,
        mode="lines",
        line=dict(width=0),
        showlegend=False,
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p25,
        mode="lines",
        fill="tonexty",
        fillcolor="rgba(59, 130, 246, 0.24)",
        line=dict(width=0),
        name="P25-P75",
        hoverinfo="skip",
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p50,
        mode="lines",
        name="P50",
        line=dict(color="#f8fafc", width=2.4),
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p05,
        mode="lines",
        name="P5",
        line=dict(color="#a78bfa", width=1.4, dash="dot"),
    ))

    fig.add_trace(go.Scatter(
        x=x,
        y=p95,
        mode="lines",
        name="P95",
        line=dict(color="#22c55e", width=1.4, dash="dot"),
    ))

    for label, value, color in [
        ("Prix actuel", ctx["price"], "#f8fafc"),
        ("Stop court", ctx["stop_short"], "#f59e0b"),
        ("Stop structurel", ctx["stop_structural"], "#ef4444"),
        ("Target 1", ctx["target_1"], "#22c55e"),
    ]:
        value = safe_float(value)

        if value is None:
            continue

        fig.add_hline(
            y=value,
            line_color=color,
            line_dash="dash",
            line_width=1.2,
            annotation_text=f"{label} {fmt_price(value)}",
            annotation_position="right",
            annotation_font_color=color,
        )

    fig.update_layout(
        height=540,
        title=(
            f"Monte Carlo Risk Cone — {ctx['horizon_label']} "
            f"| Stop {fmt_pct(ctx['prob_stop_short'])} | Target1 {fmt_pct(ctx['prob_target_1'])}"
        ),
        xaxis_title="Jours",
        yaxis_title="Prix simulé",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=160, t=75, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10, 14, 22, 0.55)",
        font=dict(color="#f8fafc"),
    )

    fig.update_yaxes(gridcolor="rgba(148, 163, 184, 0.18)")
    fig.update_xaxes(showgrid=False)

    st.plotly_chart(fig, width="stretch")


def render_return_distribution(ctx: dict):
    returns = ctx.get("final_returns")

    if returns is None or len(returns) == 0:
        st.info("Distribution Monte Carlo indisponible.")
        return

    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=returns,
        nbinsx=50,
        name="Final returns",
        opacity=0.82,
    ))

    for label, value, color in [
        ("VaR95", ctx["mc_var_95"], "#c084fc"),
        ("ES95", ctx["mc_es_95"], "#e879f9"),
        ("0%", 0.0, "#f8fafc"),
        ("Expected", ctx["expected_return"], "#22c55e"),
    ]:
        value = safe_float(value)

        if value is None:
            continue

        fig.add_vline(
            x=value,
            line_dash="dash",
            line_color=color,
            annotation_text=label,
            annotation_position="top",
        )

    fig.update_layout(
        height=420,
        title=f"Distribution des rendements simulés — {ctx['horizon_label']}",
        xaxis_title="Rendement final simulé",
        yaxis_title="Fréquence",
        template="plotly_dark",
        margin=dict(l=40, r=40, t=70, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10, 14, 22, 0.55)",
    )

    fig.update_xaxes(tickformat=".0%")
    fig.update_yaxes(gridcolor="rgba(148, 163, 184, 0.18)")

    st.plotly_chart(fig, width="stretch")


# ============================================================
# INSTITUTIONAL VIEWS
# ============================================================

def _risk_css():
    st.markdown(
        """
        <style>
        .risk-hero{position:relative;overflow:hidden;border:1px solid rgba(82,196,255,.28);border-radius:18px;padding:17px 19px 15px;
          background:radial-gradient(circle at 86% 15%,rgba(124,58,237,.19),transparent 31%),
          linear-gradient(118deg,rgba(3,13,28,.99),rgba(7,29,53,.96) 58%,rgba(17,11,38,.94));
          box-shadow:inset 0 1px rgba(255,255,255,.035),inset 0 0 55px rgba(56,189,248,.045),0 18px 48px rgba(0,0,0,.24);margin:2px 0 12px}
        .risk-hero:after{content:"";position:absolute;inset:0;pointer-events:none;opacity:.18;
          background-image:linear-gradient(rgba(103,232,249,.10) 1px,transparent 1px),linear-gradient(90deg,rgba(103,232,249,.08) 1px,transparent 1px);background-size:28px 28px}
        .risk-kicker{position:relative;z-index:1;font-size:.65rem;font-weight:900;letter-spacing:.20em;text-transform:uppercase;color:#67e8f9}
        .risk-title{position:relative;z-index:1;font-size:1.48rem;font-weight:950;color:#f8fafc;margin-top:4px;letter-spacing:-.035em}
        .risk-sub{position:relative;z-index:1;font-size:.78rem;line-height:1.5;color:#9fb4c9;margin-top:5px;max-width:1050px}
        .risk-chip{position:relative;z-index:1;display:inline-block;margin:10px 6px 0 0;padding:4px 9px;border-radius:999px;
          border:1px solid rgba(103,232,249,.22);background:rgba(2,10,22,.66);color:#cbd5e1;font-size:.61rem;font-weight:850;letter-spacing:.035em}
        .risk-command{border:1px solid rgba(56,189,248,.18);border-left:3px solid #38bdf8;
          background:linear-gradient(90deg,rgba(8,31,55,.88),rgba(6,18,34,.78));padding:10px 13px;
          border-radius:4px 12px 12px 4px;margin:9px 0 12px;color:#dbeafe;font-size:.76rem;box-shadow:0 8px 22px rgba(0,0,0,.13)}
        .risk-section{margin:16px 0 8px;padding:0 0 8px;border-bottom:1px solid rgba(83,169,222,.15)}
        .risk-section-kicker{font-size:.59rem;font-weight:900;letter-spacing:.18em;color:#67e8f9;text-transform:uppercase}
        .risk-section-title{font-size:1.03rem;font-weight:900;color:#eef6ff;margin-top:2px;letter-spacing:-.015em}
        .risk-section-copy{font-size:.71rem;color:#8399af;margin-top:3px;line-height:1.4}
        .risk-model-badge{display:inline-flex;align-items:center;gap:5px;padding:4px 8px;border-radius:7px;margin:2px 5px 2px 0;
          background:rgba(10,29,50,.82);border:1px solid rgba(76,181,235,.18);font-size:.62rem;color:#bad3e8;font-weight:750}
        .risk-model-badge b{color:#6ee7b7}
        .risk-status-green{color:#34d399}.risk-status-amber{color:#fbbf24}.risk-status-red{color:#fb7185}
        div[data-testid="stMetric"]{border:1px solid rgba(91,198,255,.16)!important;
          background:radial-gradient(circle at 90% 0,rgba(56,189,248,.09),transparent 35%),linear-gradient(180deg,rgba(8,23,43,.88),rgba(4,13,27,.82))!important;
          border-radius:14px!important;padding:11px 13px!important;min-height:88px!important;box-shadow:inset 0 1px rgba(255,255,255,.025),0 8px 24px rgba(0,0,0,.12)!important}
        div[data-testid="stMetric"] label{font-size:.65rem!important;letter-spacing:.065em!important;text-transform:uppercase!important;color:#90a8bd!important}
        div[data-testid="stMetricValue"]{font-size:1.16rem!important;color:#f2f8ff!important;letter-spacing:-.02em!important}
        div[data-testid="stDataFrame"]{border:1px solid rgba(84,172,224,.14);border-radius:12px;overflow:hidden;background:rgba(4,14,27,.55)}
        div[data-baseweb="tab-list"]{gap:3px;background:rgba(3,12,24,.70);padding:4px;border:1px solid rgba(83,169,222,.12);border-radius:11px}
        button[data-baseweb="tab"]{font-size:.70rem!important;font-weight:780!important;border-radius:8px!important;padding:.46rem .65rem!important}
        button[data-baseweb="tab"][aria-selected="true"]{background:linear-gradient(180deg,rgba(22,71,108,.80),rgba(10,38,65,.86))!important;color:#e9f7ff!important}
        div[data-testid="stExpander"]{border:1px solid rgba(83,169,222,.14)!important;border-radius:12px!important;background:rgba(4,14,27,.38)!important}
        @media(max-width:900px){.risk-title{font-size:1.25rem}.risk-sub{font-size:.73rem}.risk-chip{font-size:.56rem}div[data-baseweb="tab-list"]{overflow-x:auto}}
        @media(max-width:800px){
          div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"]){flex-wrap:wrap!important;gap:.7rem!important}
          div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"])>div[data-testid="stColumn"]{min-width:calc(33.333% - .7rem)!important;flex:1 1 calc(33.333% - .7rem)!important}
        }
        @media(max-width:560px){
          div[data-testid="stHorizontalBlock"]:has(div[data-testid="stMetric"])>div[data-testid="stColumn"]{min-width:calc(50% - .7rem)!important;flex:1 1 calc(50% - .7rem)!important}
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _plot_layout(title: str, height: int = 420) -> dict:
    return {
        "height": height,
        "title": dict(text=title, x=0.015, xanchor="left", font=dict(size=15, color="#f1f7ff")),
        "template": "plotly_dark",
        "margin": dict(l=42, r=24, t=64, b=42),
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(5,15,29,.62)",
        "font": dict(color="#c9d9e8", family="Inter, ui-sans-serif, system-ui"),
        "hovermode": "x unified",
        "hoverlabel": dict(bgcolor="#071526", bordercolor="#27465f", font_color="#edf7ff"),
        "legend": dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1, font=dict(size=10)),
    }


def _section_header(kicker: str, title: str, copy: str):
    st.markdown(
        f"<div class='risk-section'><div class='risk-section-kicker'>{html.escape(kicker)}</div>"
        f"<div class='risk-section-title'>{html.escape(title)}</div>"
        f"<div class='risk-section-copy'>{html.escape(copy)}</div></div>",
        unsafe_allow_html=True,
    )


def render_risk_radar(ctx: dict):
    labels = ["Volatility", "Tail", "Stop", "Drawdown", "Asymmetry", "Data risk"]
    values = [
        ctx["volatility_risk_score"],
        ctx["tail_risk_score"],
        ctx["stop_risk_score"],
        ctx["drawdown_risk_score"],
        ctx["asymmetry_risk_score"],
        100 - ctx["data_confidence_score"],
    ]
    fig = go.Figure(go.Scatterpolar(
        r=values + values[:1], theta=labels + labels[:1], fill="toself",
        line=dict(color="#38bdf8", width=2), fillcolor="rgba(56,189,248,.18)",
        hovertemplate="%{theta}: %{r:.0f}/100<extra></extra>",
    ))
    fig.update_layout(
        **_plot_layout("Risk factor radar · score élevé = risque élevé", 410),
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(range=[0, 100], gridcolor="rgba(148,163,184,.18)", tickfont=dict(size=9)),
            angularaxis=dict(gridcolor="rgba(148,163,184,.18)"),
        ),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")


def render_tail_model_chart(intel: dict):
    table = intel["tail_models"].dropna(subset=["VaR", "ES"]).sort_values("ES", ascending=False)
    if table.empty:
        st.info("Comparaison multi-modèles indisponible.")
        return
    fig = go.Figure()
    for _, row in table.iterrows():
        fig.add_trace(go.Scatter(
            x=[row["ES"], row["VaR"]], y=[row["Model"], row["Model"]], mode="lines",
            line=dict(color="rgba(100,143,176,.46)", width=4), showlegend=False, hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        x=table["VaR"], y=table["Model"], name="VaR", mode="markers",
        marker=dict(size=10, color="#38bdf8", line=dict(width=1, color="#d9f5ff")),
        customdata=table[["Status", "Method"]],
        hovertemplate="<b>%{y}</b><br>VaR %{x:.2%}<br>Status %{customdata[0]}<br>%{customdata[1]}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=table["ES"], y=table["Model"], name="Expected Shortfall", mode="markers",
        marker=dict(size=11, color="#c084fc", symbol="diamond", line=dict(width=1, color="#f1dcff")),
        customdata=table[["Status", "Method"]],
        hovertemplate="<b>%{y}</b><br>ES %{x:.2%}<br>Status %{customdata[0]}<br>%{customdata[1]}<extra></extra>",
    ))
    layout = _plot_layout("Model challenge · VaR to Expected Shortfall", max(430, 78 + 52 * len(table)))
    layout.update(
        xaxis=dict(title="Loss return", tickformat=".1%", gridcolor="rgba(116,157,188,.13)", zerolinecolor="rgba(116,157,188,.28)"),
        yaxis=dict(title=None, automargin=True, categoryorder="array", categoryarray=table["Model"].tolist()),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_drawdown_regime_chart(intel: dict):
    drawdown = intel["drawdown"].get("series", pd.Series(dtype=float))
    vol = intel["regime"].get("series_20d", pd.Series(dtype=float))
    if drawdown.empty and vol.empty:
        st.info("Historique insuffisant pour les régimes et drawdowns.")
        return
    fig = go.Figure()
    if not drawdown.empty:
        fig.add_trace(go.Scatter(
            x=drawdown.index, y=drawdown, name="Drawdown", fill="tozeroy",
            line=dict(color="#fb7185", width=1.6), fillcolor="rgba(251,113,133,.15)",
        ))
    if not vol.empty:
        fig.add_trace(go.Scatter(
            x=vol.index, y=vol, name="Realized vol 20D", yaxis="y2",
            line=dict(color="#fbbf24", width=1.7),
        ))
    layout = _plot_layout("Drawdown path & realized-volatility regime", 440)
    layout.update(
        yaxis=dict(title="Drawdown", tickformat=".0%", gridcolor="rgba(148,163,184,.14)"),
        yaxis2=dict(title="Volatility", tickformat=".0%", overlaying="y", side="right", showgrid=False),
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_scenario_chart(intel: dict):
    table = intel["scenarios"].sort_values("P&L / NAV", ascending=True)
    if table.empty:
        st.info("Scénarios indisponibles.")
        return
    colors = ["#fb7185" if value == "YES" else "#38bdf8" for value in table["Limit breached"]]
    fig = go.Figure(go.Bar(
        y=table["Scenario"], x=table["P&L / NAV"], marker_color=colors, orientation="h",
        text=table["P&L / NAV"].map(lambda value: f"{value:.1%}"), textposition="outside",
        customdata=table[["Asset shock", "Position P&L", "Liquidity overlay", "Loss-limit usage"]],
        hovertemplate="<b>%{y}</b><br>P&L / NAV %{x:.2%}<br>Asset shock %{customdata[0]:.2%}<br>Position P&L $%{customdata[1]:,.0f}<br>Liquidity $%{customdata[2]:,.0f}<br>Limit usage %{customdata[3]:.1%}<extra></extra>",
    ))
    limit = intel["parameters"].loss_limit_pct
    fig.add_vline(x=-limit, line_color="#f43f5e", line_dash="dash", annotation_text=f"Loss limit -{limit:.1%}")
    layout = _plot_layout("Scenario loss map · position + liquidity overlay", max(455, 88 + 43 * len(table)))
    layout.update(
        xaxis=dict(tickformat=".1%", gridcolor="rgba(116,157,188,.13)", zerolinecolor="rgba(116,157,188,.30)"),
        yaxis=dict(automargin=True),
        showlegend=False,
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_uncertainty_chart(intel: dict):
    uncertainty = intel.get("advanced", {}).get("uncertainty", {})
    table = uncertainty.get("table", pd.DataFrame())
    if not isinstance(table, pd.DataFrame) or table.empty:
        st.info(uncertainty.get("reason", "Bootstrap uncertainty is unavailable."))
        return
    error_plus = table["CI high"] - table["Median"]
    error_minus = table["Median"] - table["CI low"]
    colors = ["#38bdf8", "#c084fc"]
    fig = go.Figure(go.Scatter(
        x=table["Median"], y=table["Metric"], mode="markers",
        marker=dict(size=14, color=colors, line=dict(width=1.5, color="#edf8ff")),
        error_x=dict(type="data", symmetric=False, array=error_plus, arrayminus=error_minus, color="#7dd3fc", thickness=3, width=8),
        customdata=table[["CI low", "CI high", "CI width"]],
        hovertemplate="<b>%{y}</b><br>Median %{x:.2%}<br>95% CI %{customdata[0]:.2%} → %{customdata[1]:.2%}<br>Width %{customdata[2]:.2%}<extra></extra>",
    ))
    layout = _plot_layout("Parameter uncertainty · moving-block bootstrap 95% interval", 310)
    layout.update(
        xaxis=dict(tickformat=".1%", gridcolor="rgba(116,157,188,.13)", zerolinecolor="rgba(116,157,188,.28)"),
        yaxis=dict(automargin=True),
        showlegend=False,
    )
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_nonlinear_scenario_chart(intel: dict):
    nonlinear = intel.get("advanced", {}).get("nonlinear", {})
    table = nonlinear.get("summary", pd.DataFrame())
    if not isinstance(table, pd.DataFrame) or table.empty:
        st.info(nonlinear.get("reason", "Nonlinear scenarios are unavailable."))
        return
    metrics = [
        column for column in (
            "p05_terminal_return", "expected_shortfall", "median_max_drawdown", "p05_max_drawdown"
        ) if column in table
    ]
    heat = table.set_index("Scenario")[metrics].copy()
    labels = {
        "p05_terminal_return": "Terminal P05",
        "expected_shortfall": "Expected shortfall",
        "median_max_drawdown": "Median max DD",
        "p05_max_drawdown": "Max DD P05",
    }
    fig = go.Figure(go.Heatmap(
        z=heat.to_numpy(dtype=float), x=[labels.get(column, column) for column in heat.columns], y=heat.index,
        colorscale=[[0, "#7f1d3a"], [0.45, "#1e3a5f"], [1, "#0f766e"]], zmid=-0.05,
        text=np.vectorize(lambda value: f"{value:.1%}")(heat.to_numpy(dtype=float)), texttemplate="%{text}",
        colorbar=dict(title="Return", tickformat=".0%", thickness=10),
        hovertemplate="<b>%{y}</b><br>%{x}: %{z:.2%}<extra></extra>",
    ))
    layout = _plot_layout("Nonlinear scenario surface · regime, EVT and liquidity feedback", max(405, 125 + 48 * len(heat)))
    layout.update(xaxis=dict(side="top"), yaxis=dict(automargin=True), hovermode="closest")
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_regime_mix(intel: dict):
    mix = intel.get("advanced", {}).get("nonlinear", {}).get("regime_mix", {})
    if not mix:
        st.info("Regime simulation mix unavailable.")
        return
    labels = [str(label).title() for label in mix]
    values = [float(value) for value in mix.values()]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker_color=["#34d399", "#fbbf24", "#fb7185"][: len(values)],
        text=[f"{value:.1%}" for value in values], textposition="inside",
        hovertemplate="%{y}: %{x:.2%}<extra></extra>",
    ))
    layout = _plot_layout("Simulated regime occupancy", 300)
    layout.update(xaxis=dict(range=[0, 1], tickformat=".0%", gridcolor="rgba(116,157,188,.13)"), showlegend=False)
    fig.update_layout(**layout)
    st.plotly_chart(fig, width="stretch")


def render_backtest_chart(intel: dict):
    series = intel["backtests"].get("series", pd.DataFrame())
    if series.empty:
        st.info("Backtest VaR indisponible : historique insuffisant.")
        return
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series["Return"], name="Actual return", mode="markers", marker=dict(size=4, color="#94a3b8")))
    for model, color in (("Historical VaR", "#38bdf8"), ("EWMA Gaussian VaR", "#c084fc")):
        fig.add_trace(go.Scatter(x=series.index, y=series[model], name=model, line=dict(color=color, width=1.5)))
        exceptions = series[series[f"{model} exception"]]
        fig.add_trace(go.Scatter(
            x=exceptions.index, y=exceptions["Return"], name=f"{model} breach", mode="markers",
            marker=dict(size=8, color="#fb7185", symbol="x"), visible="legendonly" if "EWMA" in model else True,
        ))
    fig.update_layout(**_plot_layout("Daily VaR exceptions · out-of-sample outcome analysis", 470), yaxis_tickformat=".1%")
    st.plotly_chart(fig, width="stretch")


def _format_risk_table(table: pd.DataFrame, percent_columns: list[str] | None = None, money_columns: list[str] | None = None) -> pd.DataFrame:
    result = table.copy()
    for column in percent_columns or []:
        if column in result:
            result[column] = result[column].map(fmt_pct)
    for column in money_columns or []:
        if column in result:
            result[column] = result[column].map(lambda value: "N/A" if safe_float(value) is None else f"${safe_float(value):,.0f}")
    return result


def _institutional_export(ctx: dict, intel: dict) -> pd.DataFrame:
    base = build_export_summary(ctx)
    extra = [
        ("Control status", intel["control_status"]),
        ("Validation status", intel["validation_status"]),
        ("Selected confidence", fmt_pct(intel["parameters"].confidence)),
        ("Position notional", f"${intel['parameters'].position_notional:,.0f}"),
        ("Portfolio NAV", f"${intel['parameters'].portfolio_nav:,.0f}"),
        ("Position side", intel["parameters"].side),
        ("Loss limit", fmt_pct(intel["parameters"].loss_limit_pct)),
        ("Conservative VaR", fmt_pct(intel["conservative_var"])),
        ("Conservative ES", fmt_pct(intel["conservative_es"])),
        ("ES capital", f"${intel['position']['es_dollars']:,.0f}"),
        ("Model ES dispersion", fmt_pct(intel["model_dispersion_es"])),
        ("Liquidity status", intel["liquidity"].get("status", "N/A")),
        ("Days to liquidate", fmt_num(intel["liquidity"].get("days_to_liquidate"))),
        ("Volatility regime", intel["regime"].get("label", "N/A")),
        ("Current drawdown", fmt_pct(intel["drawdown"].get("current_drawdown"))),
        ("Data quality", fmt_score(intel["data_quality"].get("score"))),
        ("Provider", intel["data_quality"].get("provider", {}).get("provider", "Unknown")),
        ("Advanced model count", str(len(intel.get("advanced", {}).get("catalog", pd.DataFrame())))),
        ("GJR-GARCH state", intel.get("advanced", {}).get("gjr", {}).get("status", "N/A")),
        ("Bootstrap confidence", intel.get("advanced", {}).get("uncertainty", {}).get("status", "N/A")),
        ("Factor model state", intel.get("advanced", {}).get("factors", {}).get("status", "N/A")),
    ]
    return pd.concat([base, pd.DataFrame(extra, columns=["Champ", "Valeur"])], ignore_index=True)


def _streamlit_secrets() -> dict[str, object]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


@st.cache_data(ttl=600, max_entries=32, show_spinner=False)
def _cached_institutional_snapshot(
    price_data: pd.DataFrame,
    price: float,
    parameters_dict: dict,
    stop_short: float | None,
    stop_structural: float | None,
    factor_returns: pd.DataFrame | None,
) -> dict:
    return build_institutional_risk_snapshot(
        price_data,
        price=price,
        parameters=RiskParameters(**parameters_dict),
        stop_short=stop_short,
        stop_structural=stop_structural,
        factor_returns=factor_returns,
    )


@st.cache_data(ttl=600, max_entries=48, show_spinner=False)
def _cached_market_enrichment(ticker: str, underlying_price: float) -> dict:
    return load_risk_market_enrichment(
        ticker,
        underlying_price=underlying_price,
        secrets=_streamlit_secrets(),
    )


# ============================================================
# MAIN RENDER
# ============================================================

def render_risk_monitor_v2(ticker: str, price_data: pd.DataFrame, analysis: dict):
    _risk_css()
    analysis = analysis if isinstance(analysis, dict) else {}
    safe_ticker = html.escape(str(ticker))
    st.markdown(
        f"""
        <div class="risk-hero">
          <div class="risk-kicker">INSTITUTIONAL RISK CONTROL · LIVE WORKBENCH</div>
          <div class="risk-title">{safe_ticker} / Adaptive Multi-Model Risk Monitor</div>
          <div class="risk-sub">Institutional pre-trade control, nonlinear tail research and model governance in one auditable surface.
          Every result is recomputed from the visible assumptions; unavailable proprietary inputs remain explicitly gated.</div>
          <span class="risk-chip">VaR + EXPECTED SHORTFALL</span><span class="risk-chip">GJR-GARCH-t / FHS</span>
          <span class="risk-chip">MARKOV REGIMES</span><span class="risk-chip">DYNAMIC EVT + BOOTSTRAP</span>
          <span class="risk-chip">REVERSE STRESS</span><span class="risk-chip">DATA FABRIC READY</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Risk assumptions & control limits", expanded=True):
        a1, a2, a3, a4 = st.columns(4)
        with a1:
            selected_horizon = st.selectbox("Holding horizon", [1, 5, 10, 20, 30, 60, 90], index=2, key=f"risk_horizon_{ticker}")
        with a2:
            confidence_label = st.selectbox("Tail confidence", ["95.0%", "97.5%", "99.0%"], index=1, key=f"risk_confidence_{ticker}")
        with a3:
            side = st.selectbox("Position side", ["Long", "Short"], index=0, key=f"risk_side_{ticker}")
        with a4:
            ewma_lambda = st.selectbox("EWMA decay", [0.90, 0.94, 0.97], index=1, key=f"risk_ewma_{ticker}")

        b1, b2, b3, b4 = st.columns(4)
        with b1:
            portfolio_nav = st.number_input("Portfolio NAV ($)", min_value=1_000.0, value=1_000_000.0, step=50_000.0, key=f"risk_nav_{ticker}")
        with b2:
            position_notional = st.number_input("Position notional ($)", min_value=0.0, value=100_000.0, step=10_000.0, key=f"risk_notional_{ticker}")
        with b3:
            loss_limit_bps = st.number_input("Loss limit (bp NAV)", min_value=1.0, max_value=10_000.0, value=100.0, step=10.0, key=f"risk_limit_{ticker}")
        with b4:
            adv_participation_pct = st.number_input("Max ADV participation (%)", min_value=0.1, max_value=100.0, value=10.0, step=1.0, key=f"risk_adv_{ticker}")

        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            volatility_stress = st.number_input("Volatility shock (×)", min_value=1.0, max_value=10.0, value=2.0, step=0.25, key=f"risk_vol_stress_{ticker}")
        with c2:
            custom_shock_pct = st.number_input("Custom asset shock (%)", min_value=-99.0, max_value=500.0, value=-10.0, step=1.0, key=f"risk_custom_shock_{ticker}")
        with c3:
            st.caption("Sizing and liquidity are scenario controls, not personalized advice. The impact estimate is an explicit square-root proxy, not an executable quote.")

    confidence = {"95.0%": 0.95, "97.5%": 0.975, "99.0%": 0.99}[confidence_label]
    parameters = RiskParameters(
        horizon_days=selected_horizon,
        confidence=confidence,
        portfolio_nav=portfolio_nav,
        position_notional=position_notional,
        side=side,
        loss_limit_pct=loss_limit_bps / 10_000.0,
        adv_participation=adv_participation_pct / 100.0,
        volatility_stress=volatility_stress,
        custom_shock=custom_shock_pct / 100.0,
        ewma_lambda=ewma_lambda,
    )
    ctx = build_risk_context_v2(ticker, price_data, analysis, selected_horizon)
    factor_returns = analysis.get("factor_returns")
    if not isinstance(factor_returns, pd.DataFrame):
        factor_returns = None
    with st.spinner("Calibrating conditional volatility, nonlinear scenarios and uncertainty…"):
        intel = _cached_institutional_snapshot(
            price_data,
            ctx["price"],
            parameters.normalized().__dict__,
            ctx["stop_short"],
            ctx["stop_structural"],
            factor_returns,
        )
    secrets = _streamlit_secrets()
    data_readiness = risk_data_readiness(secrets)
    auto_enrichment_ready = bool(
        data_readiness.loc[
            data_readiness["Capability"].isin(["NBBO / executable spread", "Options IV / Greeks / OI"]),
            "State",
        ].eq("CONFIGURED").any()
    )
    enrichment = (
        _cached_market_enrichment(ticker, ctx["price"])
        if auto_enrichment_ready
        else {"ok": False, "status": "READY_FOR_KEY", "quote": {}, "options": {}, "attempts": []}
    )

    status_class = {"GREEN": "risk-status-green", "AMBER": "risk-status-amber", "RED": "risk-status-red"}[intel["control_status"]]
    provider = intel["data_quality"].get("provider", {}).get("provider", "Unknown")
    st.markdown(
        f"<div class='risk-command'><b class='{status_class}'>● CONTROL {intel['control_status']}</b> · "
        f"{selected_horizon}D / {confidence:.1%} · {side.upper()} ${position_notional:,.0f} · "
        f"Source {html.escape(str(provider))} · {len(intel['returns']):,} returns · "
        f"{int((intel['alerts']['Severity'] == 'CRITICAL').sum())} critical / "
        f"{int((intel['alerts']['Severity'] == 'WARNING').sum())} warnings · "
        f"{len(intel['tail_models'])} tail models · Data fabric {enrichment.get('status', 'READY')}</div>",
        unsafe_allow_html=True,
    )

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Control status", intel["control_status"])
    m2.metric(f"Conservative ES {confidence:.1%}", fmt_pct(intel["conservative_es"]))
    m3.metric("ES capital", f"${intel['position']['es_dollars']:,.0f}")
    m4.metric("Exit capacity", fmt_days(intel["liquidity"].get("days_to_liquidate")))
    m5.metric("Vol regime", intel["regime"].get("label", "N/A"))
    m6.metric("Model validation", intel["validation_status"])

    tabs = st.tabs([
        "Control",
        "Tail Models",
        "Advanced",
        "Stress",
        "Liquidity",
        "Validation",
        "Market Map",
        "Data Fabric",
        "Audit",
    ])

    with tabs[0]:
        _section_header(
            "CONTROL PLANE",
            "Exception-first control tower",
            "Critical and warning controls lead the view; every measurement maps to an explicit operating response.",
        )
        alerts = intel["alerts"].copy()
        for index, value in enumerate(alerts["Current"]):
            if isinstance(value, (float, np.floating)) and np.isfinite(value):
                alerts.at[index, "Current"] = f"{value:.2%}" if abs(value) <= 5 else f"{value:,.2f}"
        st.dataframe(alerts, width="stretch", hide_index=True)
        left, right = st.columns([1, 1.35])
        with left:
            render_risk_radar(ctx)
        with right:
            render_drawdown_regime_chart(intel)
        _section_header("RISK ATTRIBUTION", "Pre-trade decomposition", "Normalized drivers connect the control state to the underlying evidence.")
        st.dataframe(build_risk_decomposition_table(ctx), width="stretch", hide_index=True)

    with tabs[1]:
        _section_header(
            "TAIL MODEL STACK",
            "Production benchmarks and governed challengers",
            f"{len(intel['tail_models'])} complementary estimators separate empirical history, parametric tails, conditional volatility, regimes and outcome weighting.",
        )
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Worst VaR", fmt_pct(intel["conservative_var"]))
        t2.metric("Worst ES", fmt_pct(intel["conservative_es"]))
        t3.metric("ES dispersion", fmt_pct(intel["model_dispersion_es"]))
        t4.metric("Tail capital / limit", fmt_pct(intel["position"]["es_dollars"] / max(intel["position"]["loss_limit_dollars"], 1e-12)))
        model_table = intel["tail_models"].copy()
        model_table["VaR P&L"] = model_table["VaR"].abs() * position_notional
        model_table["ES P&L"] = model_table["ES"].abs() * position_notional
        display_models = _format_risk_table(model_table, ["VaR", "ES"], ["VaR P&L", "ES P&L"])
        st.dataframe(display_models, width="stretch", hide_index=True)
        render_tail_model_chart(intel)

        _section_header("DISTRIBUTION", "Path and asymmetry diagnostics", "Realized distribution statistics contextualize model output without replacing tail controls.")
        diagnostics = intel["distribution"]
        drawdown = intel["drawdown"]
        diag_table = pd.DataFrame([
            {"Metric": "Annualized volatility", "Value": fmt_pct(diagnostics.get("annual_volatility")), "Interpretation": "Unconditional realized volatility"},
            {"Metric": "Downside deviation", "Value": fmt_pct(diagnostics.get("downside_deviation")), "Interpretation": "Annualized negative-return deviation"},
            {"Metric": "Skewness", "Value": fmt_num(diagnostics.get("skewness")), "Interpretation": "Negative values signal left-tail asymmetry"},
            {"Metric": "Excess kurtosis", "Value": fmt_num(diagnostics.get("excess_kurtosis")), "Interpretation": "Positive values signal fat tails"},
            {"Metric": "Omega (0% MAR)", "Value": fmt_num(diagnostics.get("omega_zero")), "Interpretation": "Probability-weighted gains / losses proxy"},
            {"Metric": "Sortino (0% MAR)", "Value": fmt_num(diagnostics.get("sortino_zero_mar")), "Interpretation": "Return per unit of downside deviation"},
            {"Metric": "Ulcer index", "Value": fmt_pct(drawdown.get("ulcer_index")), "Interpretation": "Depth and persistence of drawdowns"},
            {"Metric": "Max underwater duration", "Value": f"{drawdown.get('max_underwater_days', 'N/A')} bars", "Interpretation": "Longest time below a prior high"},
        ])
        st.dataframe(diag_table, width="stretch", hide_index=True)

        evt = intel["evt"]
        with st.expander("Extreme Value Theory · Peaks over Threshold", expanded=False):
            if not evt.get("ok"):
                st.info(evt.get("reason", "EVT diagnostics unavailable."))
            else:
                e1, e2, e3, e4 = st.columns(4)
                e1.metric("EVT status", evt.get("status", "N/A"))
                e2.metric("Shape ξ", fmt_num(evt.get("shape")))
                e3.metric("Exceedances", str(evt.get("exceedances", "N/A")))
                e4.metric("KS p-value", fmt_num(evt.get("ks_p_value")))
                metrics = evt.get("metrics", {})
                st.dataframe(pd.DataFrame([
                    {"Tail level": "99.0%", "EVT VaR": fmt_pct(-metrics.get("var_99_loss")) if metrics.get("var_99_loss") is not None else "N/A", "EVT ES": fmt_pct(-metrics.get("es_99_loss")) if metrics.get("es_99_loss") is not None else "N/A"},
                    {"Tail level": "99.5%", "EVT VaR": fmt_pct(-metrics.get("var_995_loss")) if metrics.get("var_995_loss") is not None else "N/A", "EVT ES": fmt_pct(-metrics.get("es_995_loss")) if metrics.get("es_995_loss") is not None else "N/A"},
                    {"Tail level": "99.9%", "EVT VaR": fmt_pct(-metrics.get("var_999_loss")) if metrics.get("var_999_loss") is not None else "N/A", "EVT ES": fmt_pct(-metrics.get("es_999_loss")) if metrics.get("es_999_loss") is not None else "N/A"},
                ]), width="stretch", hide_index=True)
                stability_table = evt.get("stability_table", pd.DataFrame())
                if isinstance(stability_table, pd.DataFrame) and not stability_table.empty:
                    st.caption(f"Threshold stability: {evt.get('stability', {}).get('status', 'N/A')}")
                    st.dataframe(stability_table, width="stretch", hide_index=True)

        with st.expander("Monte Carlo distribution evidence", expanded=False):
            render_return_distribution(ctx)

    with tabs[2]:
        _section_header(
            "RESEARCH LAB",
            "Conditional volatility, nonlinear regimes and uncertainty",
            "Advanced challengers remain visibly separated from validated benchmarks until their outcome gates pass.",
        )
        advanced = intel.get("advanced", {})
        gjr = advanced.get("gjr", {})
        uncertainty = advanced.get("uncertainty", {})
        benchmark = advanced.get("benchmark", {})
        gfit = gjr.get("fit", {})
        gparams = gfit.get("parameters", {})
        a1, a2, a3, a4, a5 = st.columns(5)
        a1.metric("GJR-GARCH", gjr.get("status", "N/A"))
        a2.metric("Persistence", fmt_num(gfit.get("persistence")))
        a3.metric("Student-t df", fmt_num(gparams.get("degrees_of_freedom")))
        a4.metric("Bootstrap confidence", uncertainty.get("status", "N/A"))
        a5.metric("OOS ensemble", benchmark.get("status", "N/A"))
        catalog = advanced.get("catalog", pd.DataFrame())
        if isinstance(catalog, pd.DataFrame) and not catalog.empty:
            st.dataframe(catalog, width="stretch", hide_index=True)

        left, right = st.columns([1.12, 0.88])
        with left:
            render_uncertainty_chart(intel)
        with right:
            render_regime_mix(intel)
        render_nonlinear_scenario_chart(intel)

        weights = benchmark.get("weight_table", pd.DataFrame())
        with st.expander("Outcome-weighted benchmark governance", expanded=False):
            if isinstance(weights, pd.DataFrame) and not weights.empty:
                display_weights = _format_risk_table(
                    weights,
                    ["Exception rate", "Expected rate", "Conditional p-value", "Weight", "VaR", "ES"],
                )
                st.dataframe(display_weights, width="stretch", hide_index=True)
                st.caption(str(benchmark.get("method", "")))
            else:
                st.info("The ensemble remains blocked until two benchmark histories clear their validation gate.")

        factors = advanced.get("factors", {})
        with st.expander("Multi-factor decomposition contract", expanded=False):
            if factors.get("ok"):
                f1, f2, f3 = st.columns(3)
                f1.metric("Factor R²", fmt_pct(factors.get("r_squared")))
                f2.metric("Systematic vol", fmt_pct(factors.get("factor_volatility")))
                f3.metric("Idiosyncratic vol", fmt_pct(factors.get("idiosyncratic_volatility")))
                st.dataframe(factors.get("table", pd.DataFrame()), width="stretch", hide_index=True)
            else:
                st.info(factors.get("reason", "Factor matrix unavailable."))
                st.dataframe(factors.get("contract", pd.DataFrame()), width="stretch", hide_index=True)

    with tabs[3]:
        _section_header(
            "SCENARIO ENGINE",
            "Forward, historical and reverse stress testing",
            "Deterministic loss controls are paired with nonlinear research paths and liquidity overlays.",
        )
        p = intel["position"]
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Shock to loss limit", fmt_pct(p["shock_to_loss_limit"]))
        r2.metric("Shock to short stop", fmt_pct(p["stop_short_return"]))
        r3.metric("Shock to structural stop", fmt_pct(p["stop_structural_return"]))
        worst_scenario = intel["scenarios"].sort_values("P&L / NAV").iloc[0] if not intel["scenarios"].empty else None
        r4.metric("Worst scenario / NAV", fmt_pct(worst_scenario["P&L / NAV"] if worst_scenario is not None else None))
        st.caption("Reverse stress starts from a limit breach and solves for the asset shock that produces it under the selected side and notional.")
        display_scenarios = _format_risk_table(
            intel["scenarios"],
            ["Asset shock", "P&L / NAV", "Loss-limit usage"],
            ["Position P&L", "Liquidity overlay"],
        )
        st.dataframe(display_scenarios, width="stretch", hide_index=True)
        render_scenario_chart(intel)
        with st.expander("Deterministic price-level stress evidence", expanded=False):
            legacy_stress = ctx["stress_tests"].copy()
            if not legacy_stress.empty:
                legacy_stress["Prix stressé"] = legacy_stress["Prix stressé"].map(fmt_price)
                for column in ["Choc", "Distance stop court", "Distance stop structurel", "Rebond requis vers Target 1"]:
                    legacy_stress[column] = legacy_stress[column].map(fmt_pct)
                st.dataframe(legacy_stress, width="stretch", hide_index=True)

    with tabs[4]:
        _section_header("LIQUIDITY", "Liquidity-adjusted position control", "Capacity, impact and sizing remain disabled rather than imputed when source fields are absent.")
        liquidity = intel["liquidity"]
        l1, l2, l3, l4 = st.columns(4)
        l1.metric("Liquidity status", liquidity.get("status", "N/A"))
        l2.metric("Position / ADV", fmt_pct_adaptive(liquidity.get("position_adv")))
        l3.metric("Days to liquidate", fmt_days(liquidity.get("days_to_liquidate")))
        l4.metric("Impact proxy", fmt_pct_adaptive(liquidity.get("impact_proxy")))
        if liquidity.get("available"):
            liquid_table = liquidity["table"].copy()
            def format_liquidity_row(row):
                metric = str(row["Metric"])
                value = row["Value"]
                if "dollar ADV" in metric:
                    return "N/A" if safe_float(value) is None else f"${safe_float(value):,.0f}"
                if metric in {"Position / ADV", "Square-root impact proxy"}:
                    return fmt_pct_adaptive(value)
                if metric == "Days to liquidate":
                    return fmt_days(value)
                return fmt_num(value)

            liquid_table["Value"] = liquid_table.apply(format_liquidity_row, axis=1).astype(str)
            st.dataframe(liquid_table, width="stretch", hide_index=True)
        else:
            st.warning("Volume absent or insufficient: capacity and market-impact controls are disabled, not imputed.")

        _section_header("CAPITAL ALLOCATION", "Binding notional limits", "The strictest approved stop or Expected Shortfall constraint determines position capacity.")
        sizing = p["table"].copy()
        sizing = _format_risk_table(sizing, ["Usage"], ["Value"])
        st.dataframe(sizing, width="stretch", hide_index=True)
        s1, s2, s3 = st.columns(3)
        s1.metric("Max notional / stop", "N/A" if p["max_notional_stop"] is None else f"${p['max_notional_stop']:,.0f}")
        s2.metric("Max notional / ES", "N/A" if p["max_notional_es"] is None else f"${p['max_notional_es']:,.0f}")
        s3.metric("Binding limit", "N/A" if p["binding_notional_limit"] is None else f"${p['binding_notional_limit']:,.0f}")
        st.caption("Capacity uses median dollar volume and the selected maximum ADV participation. The sizing limit binds to the more conservative of stop-loss and ES capital.")

    with tabs[5]:
        _section_header("MODEL GOVERNANCE", "Validation and outcome analysis", "Coverage, independence, specification risk and challenger state are visible in one audit trail.")
        summary = intel["backtests"].get("summary", pd.DataFrame()).copy()
        if summary.empty:
            st.warning("At least 80 daily returns are required for rolling out-of-sample VaR validation.")
        else:
            summary = _format_risk_table(summary, ["exception_rate", "expected_rate", "kupiec_p_value", "independence_p_value", "conditional_p_value"])
            st.dataframe(summary, width="stretch", hide_index=True)
            render_backtest_chart(intel)
        st.caption(
            "Kupiec tests unconditional coverage; Christoffersen tests exception independence. "
            "LIMITED means the out-of-sample window is too short for a strong validation claim."
        )
        _section_header("SPECIFICATION", "Model risk register", "Known limitations are paired with an explicit mitigation or a data gate.")
        specification = pd.DataFrame([
            {"Model / control": "Historical simulation", "Primary limitation": "History may omit future regimes", "Mitigation": "Student-t, FHS, EVT and stress comparison"},
            {"Model / control": "Gaussian VaR", "Primary limitation": "Thin tails and square-root horizon assumption", "Mitigation": "Never used alone; compare ES dispersion"},
            {"Model / control": "Student-t", "Primary limitation": "IID fitted innovations", "Mitigation": "EWMA-filtered history and outcome tests"},
            {"Model / control": "GJR-GARCH-t FHS", "Primary limitation": "Parameter instability on short histories", "Mitigation": "Stationarity gate, bootstrap intervals and challenger-only role"},
            {"Model / control": "Markov regimes", "Primary limitation": "State transitions are scenario assumptions", "Mitigation": "Research-only label and visible regime occupancy"},
            {"Model / control": "EVT", "Primary limitation": "Few tail exceedances and threshold sensitivity", "Mitigation": "Adaptive threshold, 80-draw bootstrap and stability panel"},
            {"Model / control": "Liquidity impact", "Primary limitation": "Proxy without order-book/spread data", "Mitigation": "Explicit ADV participation; treat as overlay"},
            {"Model / control": "Single-position view", "Primary limitation": "No cross-asset diversification/concentration", "Mitigation": "Use Portfolio Lab for aggregate exposures"},
        ])
        st.dataframe(specification, width="stretch", hide_index=True)

    with tabs[6]:
        _section_header("MARKET GEOMETRY", "Barriers and simulated path structure", "Trading-plan levels are challenged against the same horizon and path evidence used by the risk engine.")
        render_risk_map_chart(ticker, price_data, ctx)
        b_msg_type, b_msg = barrier_comment(ctx)
        {"success": st.success, "warning": st.warning, "error": st.error}.get(b_msg_type, st.info)(b_msg)
        st.dataframe(build_barrier_table(ctx), width="stretch", hide_index=True)
        with st.expander("Monte Carlo cone & barrier proof", expanded=False):
            render_mc_risk_cone(ctx)
            st.dataframe(pd.DataFrame([{
                "Requested horizon": ctx["horizon_label"],
                "Prob. positive": fmt_pct(ctx["prob_positive"]),
                "Prob. loss > 5%": fmt_pct(ctx["prob_loss_5"]),
                "Prob. short stop": fmt_pct(ctx["prob_stop_short"]),
                "Prob. structural stop": fmt_pct(ctx["prob_stop_structural"]),
                "Prob. Target 1": fmt_pct(ctx["prob_target_1"]),
                "Expected return": fmt_pct(ctx["expected_return"]),
            }]), width="stretch", hide_index=True)

    with tabs[7]:
        _section_header(
            "DATA FABRIC",
            "Credential-aware institutional enrichment",
            "Each adapter is already wired: configuring the named secret activates its loader without a code change.",
        )
        configured_count = int((data_readiness["State"] == "CONFIGURED").sum())
        ready_count = int((data_readiness["State"] == "READY FOR KEY").sum())
        d1, d2, d3, d4 = st.columns(4)
        d1.metric("Fabric state", enrichment.get("status", "READY"))
        d2.metric("Configured feeds", str(configured_count))
        d3.metric("Ready for key", str(ready_count))
        d4.metric("Active enrichment", enrichment.get("provider") or "BASE OHLCV")
        st.dataframe(
            data_readiness[["Capability", "State", "Provider", "Activation"]],
            width="stretch",
            hide_index=True,
        )
        with st.expander("Capability coverage & engine hooks", expanded=False):
            st.dataframe(
                data_readiness[["Capability", "Coverage", "Engine hook"]],
                width="stretch",
                hide_index=True,
            )

        quote = enrichment.get("quote", {}) or {}
        options = enrichment.get("options", {}) or {}
        if quote:
            _section_header("EXECUTION MARK", "Underlying quote and spread", "Entitled bid/ask data supersedes proxy-only execution diagnostics when available.")
            q1, q2, q3, q4 = st.columns(4)
            q1.metric("Bid", fmt_price(quote.get("bid")))
            q2.metric("Ask", fmt_price(quote.get("ask")))
            q3.metric("Mid", fmt_price(quote.get("mid")))
            q4.metric("Quoted spread", fmt_pct_adaptive(quote.get("spread_pct")))
        if options:
            _section_header("IMPLIED RISK", "Options surface snapshot", f"Nearest eligible expiry: {enrichment.get('expiration', 'N/A')}")
            o1, o2, o3, o4, o5 = st.columns(5)
            o1.metric("Contracts", f"{int(options.get('contracts') or 0):,}")
            o2.metric("ATM IV", fmt_pct(options.get("atm_iv")))
            o3.metric("Put / call OI", fmt_num(options.get("put_call_oi")))
            o4.metric("25Δ put-call IV", fmt_pct(options.get("risk_reversal_25d")))
            o5.metric("Greeks coverage", fmt_pct(options.get("greeks_coverage")))
        if not quote and not options:
            st.info("The base OHLCV engine is active. Add one of the displayed secrets to unlock executable-spread and implied-risk enrichment automatically.")
        attempts = enrichment.get("attempts", [])
        if attempts:
            with st.expander("Sanitized adapter diagnostics", expanded=False):
                for attempt in attempts:
                    st.caption(f"• {attempt}")

        _section_header("FUTURE INPUTS", "Portfolio and factor contracts", "The computation hooks are present; only synchronized positions, factors or depth snapshots are missing.")
        st.dataframe(advanced.get("factors", {}).get("contract", pd.DataFrame()), width="stretch", hide_index=True)

    with tabs[8]:
        _section_header("AUDIT TRAIL", "Data lineage, assumptions and export", "Reproduce the decision with source provenance, normalized controls and a machine-readable manifest.")
        q1, q2, q3, q4 = st.columns(4)
        q1.metric("Data quality", fmt_score(intel["data_quality"].get("score")))
        q2.metric("Quality status", intel["data_quality"].get("status", "N/A"))
        q3.metric("Provider", provider)
        q4.metric("Usable returns", f"{len(intel['returns']):,}")
        quality_checks = intel["data_quality"]["checks"].copy()
        for index, value in enumerate(quality_checks["Value"]):
            if isinstance(value, (float, np.floating)) and np.isfinite(value) and abs(value) <= 1:
                quality_checks.at[index, "Value"] = fmt_pct(value)
        quality_checks["Value"] = quality_checks["Value"].map(lambda value: "N/A" if value is None else str(value))
        st.dataframe(quality_checks, width="stretch", hide_index=True)
        st.caption("Provider lineage")
        st.json(intel["data_quality"].get("provider", {}) or {"provider": "Unknown", "status": "No gateway context"})

        assumptions_table = pd.DataFrame([
            {"Assumption": key, "Value": str(value)}
            for key, value in intel["parameters_dict"].items()
        ])
        st.dataframe(assumptions_table, width="stretch", hide_index=True)

        export_df = _institutional_export(ctx, intel)
        st.dataframe(export_df, width="stretch", hide_index=True)
        manifest = {
            "ticker": ticker,
            "control_status": intel["control_status"],
            "validation_status": intel["validation_status"],
            "parameters": intel["parameters_dict"],
            "provider": intel["data_quality"].get("provider", {}),
            "data_fabric": {
                "status": enrichment.get("status"),
                "provider": enrichment.get("provider"),
                "expiration": enrichment.get("expiration"),
            },
            "research": {
                "gjr_garch": advanced.get("gjr", {}).get("status"),
                "bootstrap_confidence": advanced.get("uncertainty", {}).get("status"),
                "oos_benchmark": advanced.get("benchmark", {}).get("status"),
                "factor_model": advanced.get("factors", {}).get("status"),
            },
            "risk": {
                "conservative_var": intel["conservative_var"],
                "conservative_es": intel["conservative_es"],
                "model_dispersion_es": intel["model_dispersion_es"],
                "es_dollars": intel["position"]["es_dollars"],
                "days_to_liquidate": intel["liquidity"].get("days_to_liquidate"),
            },
        }
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download control summary CSV", export_df.to_csv(index=False).encode("utf-8"),
                file_name=f"{ticker}_institutional_risk_{selected_horizon}D.csv", mime="text/csv",
                key=f"risk_export_csv_{ticker}_{selected_horizon}_{confidence_label}",
            )
        with d2:
            st.download_button(
                "Download assumptions manifest JSON", json.dumps(manifest, indent=2, default=str).encode("utf-8"),
                file_name=f"{ticker}_risk_manifest_{selected_horizon}D.json", mime="application/json",
                key=f"risk_export_json_{ticker}_{selected_horizon}_{confidence_label}",
            )
