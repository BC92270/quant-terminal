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
# Puis :
# def render_risk_monitor_mode(ticker, price_data, analysis):
#     render_risk_monitor_v2(ticker=ticker, price_data=price_data, analysis=analysis)
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
        return table.iloc[0], table

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

    st.plotly_chart(fig, use_container_width=True)


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

    st.plotly_chart(fig, use_container_width=True)


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

    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# MAIN RENDER
# ============================================================

def render_risk_monitor_v2(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict,
):
    st.subheader(f"Risk Monitor V2 — {ticker}")

    if not isinstance(analysis, dict) or not analysis:
        st.error("Analyse indisponible : le dictionnaire analysis est vide.")
        return

    selected_horizon = st.selectbox(
        "Horizon de risque",
        [7, 30, 90],
        index=1,
        key=f"risk_monitor_v2_horizon_{ticker}"
    )

    ctx = build_risk_context_v2(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis,
        horizon=selected_horizon,
    )

    msg_type, msg = risk_message(ctx)

    # ------------------------------------------------------------
    # Executive risk tape
    # ------------------------------------------------------------
    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric("État risque", ctx["risk_state_label"])
    c2.metric("Score composite", fmt_score(ctx["overall_risk_score"]))
    c3.metric("Budget risque", ctx["risk_budget_label"])
    c4.metric("Risque principal", main_risk_driver(ctx))
    c5.metric("Prob. stop", fmt_pct(ctx["prob_stop_short"]))
    c6.metric("MC ES95", fmt_pct(ctx["mc_es_95"]))

    if msg_type == "success":
        st.success(msg)
    elif msg_type == "warning":
        st.warning(msg)
    elif msg_type == "error":
        st.error(msg)
    else:
        st.info(msg)

    st.caption(f"Raison moteur : {ctx['risk_state_reason']}")

    st.caption(
        f"Prix {fmt_price(ctx['price'])} · "
        f"Vol {fmt_pct(ctx['volatility'])} · "
        f"ATR% {fmt_pct(ctx['atr_pct'])} · "
        f"Max DD {fmt_pct(ctx['max_drawdown'])} · "
        f"Target1 {fmt_pct(ctx['prob_target_1'])} · "
        f"Stop court {fmt_pct(ctx['prob_stop_short'])} · "
        f"Espérance MC {fmt_pct(ctx['expected_return'])}"
    )

    tabs = st.tabs([
        "Executive",
        "VaR / ES",
        "Barrier Risk",
        "Stress Tests",
        "Risk Map",
        "MC Cone",
        "Export",
    ])

    # ------------------------------------------------------------
    # Executive
    # ------------------------------------------------------------
    with tabs[0]:
        st.subheader("Risk Decomposition Matrix")

        st.caption("Lecture : dans cette table, plus le score est élevé, plus le risque est élevé.")

        st.dataframe(
            build_risk_decomposition_table(ctx),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Position Risk / Sizing Guardrail")

        st.dataframe(
            build_guardrail_table(ctx),
            use_container_width=True,
            hide_index=True,
        )

        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Vol Risk", fmt_score(ctx["volatility_risk_score"]))
        k2.metric("Tail Risk", fmt_score(ctx["tail_risk_score"]))
        k3.metric("Stop Risk", fmt_score(ctx["stop_risk_score"]))
        k4.metric("Asym Risk", fmt_score(ctx["asymmetry_risk_score"]))
        k5.metric("Data Confidence", fmt_score(ctx["data_confidence_score"]))

    # ------------------------------------------------------------
    # VaR / ES
    # ------------------------------------------------------------
    with tabs[1]:
        st.subheader("VaR / Expected Shortfall")

        v1, v2, v3, v4 = st.columns(4)
        v1.metric("MC VaR 95", fmt_pct(ctx["mc_var_95"]))
        v2.metric("MC ES 95", fmt_pct(ctx["mc_es_95"]))
        v3.metric("Hist VaR 95", fmt_pct(ctx["hist_var_95"]))
        v4.metric("Hist ES 95", fmt_pct(ctx["hist_es_95"]))

        st.dataframe(
            build_var_es_table(ctx),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Distribution des rendements simulés")

        render_return_distribution(ctx)

    # ------------------------------------------------------------
    # Barrier Risk
    # ------------------------------------------------------------
    with tabs[2]:
        st.subheader("Stop / Target Barrier Risk")

        b_msg_type, b_msg = barrier_comment(ctx)

        if b_msg_type == "success":
            st.success(b_msg)
        elif b_msg_type == "warning":
            st.warning(b_msg)
        elif b_msg_type == "error":
            st.error(b_msg)
        else:
            st.info(b_msg)

        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Stop court", fmt_pct(ctx["prob_stop_short"]))
        b2.metric("Target 1", fmt_pct(ctx["prob_target_1"]))
        b3.metric("Spread T1 / Stop", fmt_pp(ctx["asymmetry"]))
        b4.metric("Expected Return", fmt_pct(ctx["expected_return"]))

        st.dataframe(
            build_barrier_table(ctx),
            use_container_width=True,
            hide_index=True,
        )

    # ------------------------------------------------------------
    # Stress Tests
    # ------------------------------------------------------------
    with tabs[3]:
        st.subheader("Stress Test Dashboard")

        stress = ctx["stress_tests"].copy()

        s_msg_type, s_msg = stress_summary(ctx)

        if s_msg_type == "success":
            st.success(s_msg)
        elif s_msg_type == "warning":
            st.warning(s_msg)
        elif s_msg_type == "error":
            st.error(s_msg)
        else:
            st.info(s_msg)

        if stress.empty:
            st.info("Stress tests indisponibles.")
        else:
            display = stress.copy()

            for col in ["Prix stressé"]:
                display[col] = display[col].apply(fmt_price)

            for col in ["Choc", "Distance stop court", "Distance stop structurel", "Rebond requis vers Target 1"]:
                display[col] = display[col].apply(fmt_pct)

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
            )

            chart = stress.copy()
            chart["Prix stressé"] = pd.to_numeric(chart["Prix stressé"], errors="coerce")

            fig = go.Figure()

            fig.add_trace(go.Bar(
                x=chart["Scénario"],
                y=chart["Prix stressé"],
                text=chart["Prix stressé"].apply(fmt_price),
                textposition="auto",
                name="Prix stressé",
            ))

            fig.add_hline(
                y=ctx["stop_short"],
                line_dash="dash",
                line_color="#f59e0b",
                annotation_text=f"Stop court {fmt_price(ctx['stop_short'])}",
                annotation_position="right",
            )

            fig.add_hline(
                y=ctx["stop_structural"],
                line_dash="dot",
                line_color="#ef4444",
                annotation_text=f"Stop structurel {fmt_price(ctx['stop_structural'])}",
                annotation_position="right",
            )

            stress_y_values = [
                safe_float(ctx["stop_structural"]),
                safe_float(ctx["stop_short"]),
                safe_float(ctx["price"]),
                *[safe_float(x) for x in chart["Prix stressé"].tolist()],
            ]
            stress_y_values = [x for x in stress_y_values if x is not None]

            if stress_y_values:
                y_min = min(stress_y_values) * 0.96
                y_max = max(stress_y_values) * 1.03
            else:
                y_min, y_max = None, None

            fig.update_layout(
                height=430,
                title="Prix stressé vs niveaux d'invalidation",
                xaxis_title="Scénario",
                yaxis_title="Prix stressé",
                template="plotly_dark",
                margin=dict(l=40, r=120, t=70, b=45),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(10, 14, 22, 0.55)",
            )

            if y_min is not None and y_max is not None:
                fig.update_yaxes(range=[y_min, y_max])

            st.plotly_chart(fig, use_container_width=True)

    # ------------------------------------------------------------
    # Risk Map
    # ------------------------------------------------------------
    with tabs[4]:
        st.subheader("Risk Map — prix, stops, VaR, ES et zones critiques")

        render_risk_map_chart(ticker, price_data, ctx)

        levels_df = pd.DataFrame([
            {"Niveau": "Target 2", "Prix": fmt_price(ctx["target_2"]), "Lecture": "Objectif étendu"},
            {"Niveau": "Target 1", "Prix": fmt_price(ctx["target_1"]), "Lecture": "Objectif principal"},
            {"Niveau": "Prix actuel", "Prix": fmt_price(ctx["price"]), "Lecture": "Référence actuelle"},
            {"Niveau": "Zone haute", "Prix": fmt_price(ctx["zone_high"]), "Lecture": "Haut de zone d'entrée"},
            {"Niveau": "Zone basse", "Prix": fmt_price(ctx["zone_low"]), "Lecture": "Bas de zone d'entrée"},
            {"Niveau": "Stop court", "Prix": fmt_price(ctx["stop_short"]), "Lecture": "Invalidation rapide"},
            {"Niveau": "Stop structurel", "Prix": fmt_price(ctx["stop_structural"]), "Lecture": "Invalidation large"},
            {"Niveau": "MC P5", "Prix": fmt_price(ctx["mc_p5_price"]), "Lecture": "Percentile défavorable simulé"},
            {"Niveau": "MC VaR95", "Prix": fmt_price(ctx["mc_var_95_price"]), "Lecture": "Seuil VaR 95 simulé"},
            {"Niveau": "MC ES95", "Prix": fmt_price(ctx["mc_es_95_price"]), "Lecture": "Perte moyenne du mauvais 5% simulé"},
        ])

        with st.expander("Voir les niveaux affichés sur la Risk Map", expanded=False):
            st.dataframe(levels_df, use_container_width=True, hide_index=True)

    # ------------------------------------------------------------
    # MC Cone
    # ------------------------------------------------------------
    with tabs[5]:
        st.subheader("Monte Carlo Risk Cone")

        render_mc_risk_cone(ctx)

        proof_df = pd.DataFrame([{
            "Horizon": ctx["horizon_label"],
            "Prob. positif": fmt_pct(ctx["prob_positive"]),
            "Prob. perte > 5%": fmt_pct(ctx["prob_loss_5"]),
            "Prob. perte > 10%": fmt_pct(ctx["prob_loss_10"]),
            "Prob. stop court": fmt_pct(ctx["prob_stop_short"]),
            "Prob. stop structurel": fmt_pct(ctx["prob_stop_structural"]),
            "Prob. Target 1": fmt_pct(ctx["prob_target_1"]),
            "Expected Return": fmt_pct(ctx["expected_return"]),
            "Median Return": fmt_pct(ctx["median_return"]),
            "MC Score": fmt_score(ctx["mc_score"]),
            "P5": fmt_price(ctx["mc_p5_price"]),
            "P50": fmt_price(ctx["mc_p50_price"]),
            "P95": fmt_price(ctx["mc_p95_price"]),
        }])

        st.dataframe(
            proof_df,
            use_container_width=True,
            hide_index=True,
        )

    # ------------------------------------------------------------
    # Export
    # ------------------------------------------------------------
    with tabs[6]:
        st.subheader("Export Risk Summary")

        export_df = build_export_summary(ctx)

        st.dataframe(
            export_df,
            use_container_width=True,
            hide_index=True,
        )

        csv = export_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Télécharger le résumé risque CSV",
            data=csv,
            file_name=f"{ticker}_risk_monitor_v2_{ctx['horizon_label']}.csv",
            mime="text/csv",
            key=f"download_risk_monitor_v2_{ticker}_{ctx['horizon_label']}",
        )