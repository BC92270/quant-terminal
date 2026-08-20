# trading_plan.py — Trading Plan V2
# Module Streamlit autonome pour Quant Terminal.
# Objectif : transformer le signal en playbook d'exécution mécanique.

from __future__ import annotations

import re
from html import escape
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# GENERIC HELPERS
# ============================================================

def safe_float(value: Any, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, np.ndarray, list, tuple)):
            return default
        if pd.isna(value):
            return default
        value = float(value)
        if not np.isfinite(value):
            return default
        return value
    except Exception:
        return default


def first_numeric(*values, default=None):
    for value in values:
        parsed = safe_float(value, default=None)
        if parsed is not None:
            return parsed
    return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    value = safe_float(value, default=low)
    return max(low, min(high, value))


def fmt_price(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_pct(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.2%}"


def fmt_num(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:,.2f}"


def fmt_score(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.0f}/100"


def fmt_r(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    return f"{value:.2f}R"


def html_safe(value) -> str:
    return escape(str(value if value is not None else "N/A"))


def table_height(df: pd.DataFrame, row_px: int = 38, min_height: int = 150, max_height: int = 560) -> int:
    if not isinstance(df, pd.DataFrame):
        return min_height
    n = max(len(df), 1)
    return int(min(max_height, max(min_height, 46 + row_px * n)))


def render_trade_card(label: str, value: str, sub: str | None = None):
    sub_html = f"<div class='tp-card-sub'>{html_safe(sub)}</div>" if sub else ""
    st.markdown(
        f"""
        <div class="tp-card">
            <div class="tp-card-label">{html_safe(label)}</div>
            <div class="tp-card-value">{html_safe(value)}</div>
            {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_top_trade_cards(ctx: dict):
    st.markdown(
        """
        <style>
        .tp-card {
            border: 1px solid rgba(148, 163, 184, 0.22);
            background: rgba(15, 23, 42, 0.36);
            border-radius: 14px;
            padding: 14px 14px 12px 14px;
            height: 150px;
            overflow: hidden;
        }
        .tp-card-label {
            color: rgba(226, 232, 240, 0.72);
            font-size: 0.82rem;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .tp-card-value {
            color: #f8fafc;
            font-size: 1.38rem;
            line-height: 1.12;
            font-weight: 650;
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .tp-card-sub {
            margin-top: 7px;
            color: rgba(203, 213, 225, 0.76);
            font-size: 0.78rem;
            line-height: 1.2;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    p = ctx["plan"]
    cols = st.columns(6)

    cards = [
        ("Action", ctx["action_label"], ctx["execution_state"]),
        ("Type d'ordre", ctx["order_type"], "Ordre marché interdit hors zone"),
        ("Zone d'entrée", f"{fmt_price(p['zone_low'])} → {fmt_price(p['zone_high'])}", ctx["price_position"]),
        ("Budget risque", fmt_r(ctx["risk_budget_r"]), ctx["sizing_mode"]),
        ("RR Target 1", fmt_num(ctx.get("rr_t1")), f"Target 2 : {fmt_num(ctx.get('rr_t2'))}"),
        ("Prob. stop", fmt_pct(ctx["mc"].get("prob_stop")), f"MC {fmt_score(ctx['mc'].get('mc_score'))}"),
    ]

    for col, card in zip(cols, cards):
        with col:
            render_trade_card(*card)


def pct_to_score_risk(value: float | None, low: float, high: float) -> float:
    """
    Convertit une métrique de risque en score 0-100.
    low = zone contrôlée ; high = zone très risquée.
    """
    value = safe_float(value)
    if value is None:
        return 50
    if high == low:
        return 50
    return clamp((value - low) / (high - low) * 100)


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

    zone_low = min(entry_prudent, entry_aggressive)
    zone_high = max(entry_prudent, entry_aggressive)

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
        "rr_aggressive": first_numeric(plan.get("rr_aggressive"), default=None),
        "rr_prudent": first_numeric(plan.get("rr_prudent"), default=None),
        "risk_regime": plan.get("risk_regime", "N/A"),
    }


def normalize_col_name(value: str) -> str:
    text = str(value or "").lower()
    text = text.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a")
    text = text.replace("/", " ").replace(".", " ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def get_row_value(row, aliases: list[str], default=None):
    if row is None:
        return default

    if isinstance(row, pd.Series):
        data = row.to_dict()
    elif isinstance(row, dict):
        data = row
    else:
        return default

    normalized = {normalize_col_name(k): v for k, v in data.items()}

    for alias in aliases:
        key = normalize_col_name(alias)
        if key in normalized:
            return normalized[key]

    # Fallback souple : alias inclus dans le nom de colonne.
    for alias in aliases:
        alias_key = normalize_col_name(alias)
        for key, value in normalized.items():
            if alias_key in key or key in alias_key:
                return value

    return default


def get_mc_table(analysis: dict) -> pd.DataFrame:
    if not isinstance(analysis, dict):
        return pd.DataFrame()

    table = analysis.get("mc_advanced_table", pd.DataFrame())
    if isinstance(table, pd.DataFrame) and not table.empty:
        return table.copy()

    return pd.DataFrame()


def select_mc_row(analysis: dict, horizon: int) -> tuple[pd.Series | dict, pd.DataFrame]:
    table = get_mc_table(analysis)

    if isinstance(table, pd.DataFrame) and not table.empty:
        work = table.copy()

        if "Horizon" in work.columns:
            h = work["Horizon"].astype(str).str.extract(r"(\d+)")[0]
            work["_horizon_num"] = pd.to_numeric(h, errors="coerce")
            exact = work.loc[work["_horizon_num"] == int(horizon)]

            if not exact.empty:
                return exact.iloc[0], work.drop(columns=["_horizon_num"], errors="ignore")

            valid = work.dropna(subset=["_horizon_num"])
            if not valid.empty:
                idx = (valid["_horizon_num"] - int(horizon)).abs().idxmin()
                return work.loc[idx], work.drop(columns=["_horizon_num"], errors="ignore")

        return work.iloc[0], work

    # Fallback ancien Monte Carlo 30D.
    mc = analysis.get("monte_carlo", {}) if isinstance(analysis, dict) else {}
    if isinstance(mc, dict) and mc:
        return {
            "Horizon": f"{horizon}D",
            "P5": mc.get("p05"),
            "P25": mc.get("p25"),
            "P50": mc.get("p50"),
            "P75": mc.get("p75"),
            "P95": mc.get("p95"),
            "Expected Return": mc.get("expected_return"),
        }, pd.DataFrame()

    return {}, pd.DataFrame()


def get_mc_metrics(analysis: dict, horizon: int, price: float) -> dict:
    row, table = select_mc_row(analysis, horizon)

    prob_positive = safe_float(get_row_value(row, ["Prob. positif", "Prob positif", "prob_positive"]))
    prob_stop = safe_float(get_row_value(row, ["Prob. stop court", "Prob toucher stop court", "Prob. toucher stop court", "prob_stop_short"]))
    prob_stop_struct = safe_float(get_row_value(row, ["Prob. stop structurel", "Prob toucher stop structurel", "prob_stop_structural"]))
    prob_target1 = safe_float(get_row_value(row, ["Prob. Target 1", "Prob toucher Target 1", "Prob. toucher Target 1", "prob_target_1"]))
    prob_target2 = safe_float(get_row_value(row, ["Prob. Target 2", "Prob toucher Target 2", "Prob. toucher Target 2", "prob_target_2"]))
    prob_loss_5 = safe_float(get_row_value(row, ["Prob. perte > 5%", "Prob perte > 5%", "prob_loss_gt_5"]))
    expected_return = safe_float(get_row_value(row, ["Expected Return", "Expected return", "Espérance MC", "expected_return"]))
    median_return = safe_float(get_row_value(row, ["Median Return", "Median return", "median_return"]))
    mc_score = safe_float(get_row_value(row, ["MC Score", "MC score", "mc_score"]))
    asymmetry = safe_float(get_row_value(row, ["Asymétrie T1/Stop", "Asymetrie T1/Stop", "Asymétrie MC", "asymmetry"]))

    p5_price = safe_float(get_row_value(row, ["P5", "p05", "p5"]))
    p50_price = safe_float(get_row_value(row, ["P50", "p50"]))
    p95_price = safe_float(get_row_value(row, ["P95", "p95"]))

    if p5_price is not None and price:
        mc_var95 = p5_price / price - 1
    else:
        mc_var95 = safe_float(get_row_value(row, ["VaR 95", "MC VaR 95", "var95"]))

    # Si les probabilités sont absentes mais les paths existent, on calcule le strict minimum.
    paths = analysis.get("monte_carlo_paths") if isinstance(analysis, dict) else None
    if paths is not None:
        try:
            arr = np.asarray(paths, dtype=float)
            if arr.ndim == 2 and arr.shape[0] > 2 and arr.shape[1] > 5:
                h = min(int(horizon), arr.shape[0] - 1)
                final = arr[h, :]
                final_returns = final / price - 1 if price else np.array([])
                if prob_positive is None:
                    prob_positive = float(np.mean(final_returns > 0))
                if expected_return is None:
                    expected_return = float(np.mean(final_returns))
                if median_return is None:
                    median_return = float(np.median(final_returns))
                if p5_price is None:
                    p5_price = float(np.percentile(final, 5))
                if p50_price is None:
                    p50_price = float(np.percentile(final, 50))
                if p95_price is None:
                    p95_price = float(np.percentile(final, 95))
                if mc_var95 is None and price:
                    mc_var95 = p5_price / price - 1
        except Exception:
            pass

    return {
        "row": row,
        "table": table,
        "prob_positive": prob_positive,
        "prob_stop": prob_stop,
        "prob_stop_structural": prob_stop_struct,
        "prob_target1": prob_target1,
        "prob_target2": prob_target2,
        "prob_loss_5": prob_loss_5,
        "expected_return": expected_return,
        "median_return": median_return,
        "mc_score": mc_score,
        "asymmetry": asymmetry,
        "p5_price": p5_price,
        "p50_price": p50_price,
        "p95_price": p95_price,
        "mc_var95": mc_var95,
    }


def get_momentum_latest(analysis: dict) -> dict:
    mt = analysis.get("momentum_v2", {}) if isinstance(analysis, dict) else {}
    if isinstance(mt, dict) and isinstance(mt.get("latest"), dict):
        return mt.get("latest", {})
    return {}


def score_label(score: float, inverted: bool = False) -> str:
    score = safe_float(score, 50) or 50
    if inverted:
        score = 100 - score

    if score >= 75:
        return "Fort"
    if score >= 60:
        return "Constructif"
    if score >= 45:
        return "Moyen"
    return "Fragile"


# ============================================================
# CORE ENGINE
# ============================================================

def build_trade_context_v2(ticker: str, price_data: pd.DataFrame, analysis: dict, horizon: int) -> dict:
    price = first_numeric(
        analysis.get("latest_price") if isinstance(analysis, dict) else None,
        get_last_price_from_frame(price_data),
        default=None,
    )

    if price is None or price <= 0:
        return {"available": False, "reason": "Prix indisponible."}

    plan = get_trading_plan(analysis, price)
    mc = get_mc_metrics(analysis, horizon, price)
    momentum = get_momentum_latest(analysis)

    zone_low = plan["zone_low"]
    zone_high = plan["zone_high"]
    stop_short = plan["stop_short"]
    stop_structural = plan["stop_structural"]
    target_1 = plan["target_1"]
    target_2 = plan["target_2"]

    if price <= stop_structural:
        price_position_key = "STRUCTURAL_INVALIDATION"
        price_position = "Sous stop structurel"
    elif price <= stop_short:
        price_position_key = "SHORT_STOP_BROKEN"
        price_position = "Sous stop court"
    elif price < zone_low:
        price_position_key = "BELOW_ZONE"
        price_position = "Sous la zone"
    elif zone_low <= price <= zone_high:
        price_position_key = "IN_ZONE"
        price_position = "Dans la zone"
    else:
        price_position_key = "ABOVE_ZONE"
        price_position = "Au-dessus de la zone"

    # Distance jusqu'à la zone : négative si le prix doit baisser pour revenir dans la zone.
    if price > zone_high:
        distance_to_zone = zone_high / price - 1
    elif price < zone_low:
        distance_to_zone = zone_low / price - 1
    else:
        distance_to_zone = 0.0

    stop_short_dist = stop_short / price - 1
    stop_struct_dist = stop_structural / price - 1
    target1_dist = target_1 / price - 1
    target2_dist = target_2 / price - 1

    preferred_limit = zone_high if price > zone_high else price if price_position_key == "IN_ZONE" else zone_low
    preferred_limit = safe_float(preferred_limit, price) or price

    risk_per_share_short = max(preferred_limit - stop_short, 0)
    risk_per_share_struct = max(preferred_limit - stop_structural, 0)
    reward_t1 = max(target_1 - preferred_limit, 0)
    reward_t2 = max(target_2 - preferred_limit, 0)

    rr_t1 = reward_t1 / risk_per_share_short if risk_per_share_short > 0 else None
    rr_t2 = reward_t2 / risk_per_share_short if risk_per_share_short > 0 else None
    rr_t1_struct = reward_t1 / risk_per_share_struct if risk_per_share_struct > 0 else None

    vol = first_numeric(
        analysis.get("volatility") if isinstance(analysis, dict) else None,
        analysis.get("effective_volatility") if isinstance(analysis, dict) else None,
        default=None,
    )
    atr_pct = first_numeric(plan.get("atr_pct"), analysis.get("atr_pct") if isinstance(analysis, dict) else None, default=None)
    max_dd = first_numeric(analysis.get("max_drawdown") if isinstance(analysis, dict) else None, default=None)

    stop_prob = safe_float(mc.get("prob_stop"))
    target_prob = safe_float(mc.get("prob_target1"))
    expected_return = safe_float(mc.get("expected_return"))
    mc_score = safe_float(mc.get("mc_score"))
    mc_var95 = safe_float(mc.get("mc_var95"))

    stop_risk_score = pct_to_score_risk(stop_prob, 0.30, 0.65) if stop_prob is not None else 50
    tail_risk_score = pct_to_score_risk(abs(mc_var95), 0.06, 0.22) if mc_var95 is not None else 50
    vol_risk_score = pct_to_score_risk(vol, 0.20, 0.65) if vol is not None else 50
    atr_risk_score = pct_to_score_risk(atr_pct, 0.015, 0.055) if atr_pct is not None else 50
    drawdown_risk_score = pct_to_score_risk(abs(max_dd), 0.08, 0.35) if max_dd is not None else 50

    asym_bonus = 0
    if target_prob is not None and stop_prob is not None:
        asym_bonus = clamp((target_prob - stop_prob) * 100, -20, 20)

    risk_score = clamp(
        0.28 * stop_risk_score
        + 0.25 * tail_risk_score
        + 0.18 * vol_risk_score
        + 0.14 * atr_risk_score
        + 0.15 * drawdown_risk_score
        - 0.20 * asym_bonus
    )

    # Prudence : prix au-dessus de zone ou stop >45% force au moins risque élevé.
    risk_override_reasons = []
    if price_position_key == "ABOVE_ZONE":
        risk_score = max(risk_score, 68)
        risk_override_reasons.append("prix au-dessus de la zone")
    if stop_prob is not None and stop_prob >= 0.45:
        risk_score = max(risk_score, 68)
        risk_override_reasons.append("probabilité de stop supérieure à 45%")
    if mc_var95 is not None and mc_var95 <= -0.15:
        risk_score = max(risk_score, 65)
        risk_override_reasons.append("queue MC défavorable")
    if mc_score is not None and mc_score < 50:
        risk_score = max(risk_score, 70)
        risk_override_reasons.append("MC Score fragile")

    if price_position_key in ["STRUCTURAL_INVALIDATION", "SHORT_STOP_BROKEN"]:
        final_action = "NO_TRADE"
        action_label = "NO_TRADE"
        order_type = "Aucun ordre"
        execution_state = "Setup invalidé"
        risk_state = "Bloquant"
        risk_budget_r = 0.0
        sizing_mode = "Aucun"
        main_driver = "Invalidation"
        message = "Setup invalidé : le prix est sous un niveau d'invalidation. Pas d'ordre mécanique."
        message_level = "error"
    elif price_position_key == "ABOVE_ZONE":
        final_action = "WAIT_PULLBACK"
        action_label = "WAIT · Pullback"
        order_type = "Buy Limit uniquement"
        execution_state = "Attente zone"
        risk_state = "Élevé" if risk_score >= 65 else "Modéré"
        risk_budget_r = 0.25
        sizing_mode = "Défensif"
        main_driver = "Mauvais point d'entrée"
        message = "Prix au-dessus de la zone : ne pas acheter au marché, attendre un retour dans la zone."
        message_level = "warning"
    elif price_position_key == "BELOW_ZONE":
        final_action = "WAIT_STABILIZATION"
        action_label = "WAIT · Stabilisation"
        order_type = "Aucun ordre tant que pas de reprise"
        execution_state = "Sous zone"
        risk_state = "Élevé" if risk_score >= 65 else "Modéré"
        risk_budget_r = 0.25
        sizing_mode = "Défensif"
        main_driver = "Prix sous zone"
        message = "Prix sous zone : attendre stabilisation ou réintégration avant tout ordre."
        message_level = "warning"
    else:
        if risk_score >= 75:
            final_action = "ENTER_REDUCED_ONLY"
            action_label = "ENTER · Réduit"
            order_type = "Buy Limit réduit + bracket"
            execution_state = "Zone exploitable mais risquée"
            risk_state = "Élevé"
            risk_budget_r = 0.25
            sizing_mode = "Réduit"
            message = "Prix dans la zone, mais le risque impose une taille réduite et un bracket strict."
            message_level = "warning"
        elif risk_score >= 55:
            final_action = "ENTER_LIMIT_REDUCED"
            action_label = "ENTER · Limit réduit"
            order_type = "Buy Limit + bracket"
            execution_state = "Zone exploitable"
            risk_state = "Modéré"
            risk_budget_r = 0.50
            sizing_mode = "Standard réduit"
            message = "Prix dans la zone : entrée possible seulement en limit avec taille ajustée au risque."
            message_level = "info"
        else:
            final_action = "ENTER_LIMIT"
            action_label = "ENTER · Limit"
            order_type = "Buy Limit + bracket"
            execution_state = "Zone favorable"
            risk_state = "Contrôlé"
            risk_budget_r = 0.75 if mc_score is None or mc_score < 70 else 1.00
            sizing_mode = "Normal" if risk_budget_r >= 0.75 else "Standard réduit"
            message = "Prix dans la zone et risque contrôlé : setup mécaniquement exploitable en limit."
            message_level = "success"

        main_driver = "Tail risk" if tail_risk_score >= stop_risk_score else "Stop risk" if stop_risk_score >= 60 else "Execution"

    if final_action.startswith("ENTER") and rr_t1 is not None and rr_t1 < 1:
        risk_budget_r = min(risk_budget_r, 0.25)
        sizing_mode = "Réduit"
        message = "Prix dans la zone, mais le ratio Target 1 / Stop est trop faible : taille réduite uniquement."
        message_level = "warning"
        risk_override_reasons.append("RR Target 1 inférieur à 1")

    if risk_override_reasons:
        reason = "Override prudent : " + " + ".join(dict.fromkeys(risk_override_reasons)) + "."
    else:
        reason = f"Risque composite {risk_state.lower()}."

    opportunity_score = first_numeric(
        analysis.get("score") if isinstance(analysis, dict) else None,
        momentum.get("composite_score"),
        default=50,
    )
    trend_score = first_numeric(momentum.get("trend_score"), default=50)
    timing_score = first_numeric(momentum.get("timing_score"), default=50)
    exhaustion_score = first_numeric(momentum.get("exhaustion_risk_score"), default=50)

    if opportunity_score >= 80:
        opportunity_grade = "A"
    elif opportunity_score >= 65:
        opportunity_grade = "B"
    elif opportunity_score >= 50:
        opportunity_grade = "C"
    else:
        opportunity_grade = "D"

    return {
        "available": True,
        "ticker": ticker,
        "horizon": int(horizon),
        "price": price,
        "signal": analysis.get("signal", "N/A") if isinstance(analysis, dict) else "N/A",
        "plan": plan,
        "mc": mc,
        "momentum": momentum,
        "price_position_key": price_position_key,
        "price_position": price_position,
        "distance_to_zone": distance_to_zone,
        "preferred_limit": preferred_limit,
        "risk_per_share_short": risk_per_share_short,
        "risk_per_share_struct": risk_per_share_struct,
        "reward_t1": reward_t1,
        "reward_t2": reward_t2,
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
        "rr_t1_struct": rr_t1_struct,
        "stop_short_dist": stop_short_dist,
        "stop_struct_dist": stop_struct_dist,
        "target1_dist": target1_dist,
        "target2_dist": target2_dist,
        "risk_score": round(risk_score, 1),
        "risk_state": risk_state,
        "risk_budget_r": risk_budget_r,
        "sizing_mode": sizing_mode,
        "main_driver": main_driver,
        "final_action": final_action,
        "action_label": action_label,
        "order_type": order_type,
        "execution_state": execution_state,
        "message": message,
        "message_level": message_level,
        "risk_state_reason": reason,
        "opportunity_score": opportunity_score,
        "opportunity_grade": opportunity_grade,
        "trend_score": trend_score,
        "timing_score": timing_score,
        "exhaustion_score": exhaustion_score,
        "vol": vol,
        "atr_pct": atr_pct,
        "max_dd": max_dd,
        "stop_risk_score": stop_risk_score,
        "tail_risk_score": tail_risk_score,
        "vol_risk_score": vol_risk_score,
        "atr_risk_score": atr_risk_score,
        "drawdown_risk_score": drawdown_risk_score,
    }


# ============================================================
# TABLE BUILDERS
# ============================================================

def build_entry_protocol_table(ctx: dict) -> pd.DataFrame:
    p = ctx["plan"]
    mc = ctx["mc"]

    rows = [
        {
            "Gate": "Prix dans zone",
            "Condition": f"{fmt_price(p['zone_low'])} → {fmt_price(p['zone_high'])}",
            "Actuel": ctx["price_position"],
            "Statut": "OK" if ctx["price_position_key"] == "IN_ZONE" else "Non validé",
            "Action": "Autoriser limit" if ctx["price_position_key"] == "IN_ZONE" else "Attendre",
        },
        {
            "Gate": "No chase",
            "Condition": "Ne pas acheter au-dessus de la zone",
            "Actuel": fmt_pct(ctx["distance_to_zone"]),
            "Statut": "Bloque entrée marché" if ctx["price_position_key"] == "ABOVE_ZONE" else "OK",
            "Action": "Buy limit uniquement" if ctx["price_position_key"] == "ABOVE_ZONE" else "Conserver",
        },
        {
            "Gate": "Stop risk",
            "Condition": "Prob. stop < 45% souhaitable / < 40% confirmé",
            "Actuel": fmt_pct(mc.get("prob_stop")),
            "Statut": "Fragile" if safe_float(mc.get("prob_stop"), 0) >= 0.45 else "OK",
            "Action": "Réduire taille / attendre meilleur prix" if safe_float(mc.get("prob_stop"), 0) >= 0.45 else "Conserver",
        },
        {
            "Gate": "Asymétrie MC",
            "Condition": "Prob. Target 1 > Prob. stop",
            "Actuel": f"T1 {fmt_pct(mc.get('prob_target1'))} · Stop {fmt_pct(mc.get('prob_stop'))}",
            "Statut": "OK" if safe_float(mc.get("prob_target1"), 0) > safe_float(mc.get("prob_stop"), 0) else "Non validé",
            "Action": "Conserver" if safe_float(mc.get("prob_target1"), 0) > safe_float(mc.get("prob_stop"), 0) else "Réduire / attendre",
        },
        {
            "Gate": "Risk budget",
            "Condition": "0R si invalidé, 0.25R si élevé, 0.50R+ si contrôlé",
            "Actuel": fmt_r(ctx["risk_budget_r"]),
            "Statut": ctx["risk_state"],
            "Action": ctx["sizing_mode"],
        },
        {
            "Gate": "R/R Target 1",
            "Condition": ">= 1.0 minimum / >= 1.5 préférable",
            "Actuel": fmt_num(ctx.get("rr_t1")),
            "Statut": "OK" if safe_float(ctx.get("rr_t1"), 0) >= 1 else "Fragile",
            "Action": "Conserver" if safe_float(ctx.get("rr_t1"), 0) >= 1 else "Réduire taille",
        },
    ]

    return pd.DataFrame(rows)


def build_order_ticket_table(ctx: dict) -> pd.DataFrame:
    p = ctx["plan"]

    rows = [
        {"Bloc": "Décision finale", "Valeur": ctx["final_action"], "Lecture": ctx["message"]},
        {"Bloc": "Type d'ordre", "Valeur": ctx["order_type"], "Lecture": "Pas d'ordre marché si le prix est hors zone."},
        {"Bloc": "Preferred limit", "Valeur": fmt_price(ctx["preferred_limit"]), "Lecture": "Niveau de référence théorique pour l'ordre limit."},
        {"Bloc": "Zone basse", "Valeur": fmt_price(p["zone_low"]), "Lecture": "Bas de la zone d'entrée."},
        {"Bloc": "Zone haute", "Valeur": fmt_price(p["zone_high"]), "Lecture": "Haut de la zone d'entrée."},
        {"Bloc": "Stop court", "Valeur": fmt_price(p["stop_short"]), "Lecture": "Invalidation rapide."},
        {"Bloc": "Stop structurel", "Valeur": fmt_price(p["stop_structural"]), "Lecture": "Invalidation large / scénario cassé."},
        {"Bloc": "Target 1", "Valeur": fmt_price(p["target_1"]), "Lecture": "Premier objectif principal."},
        {"Bloc": "Target 2", "Valeur": fmt_price(p["target_2"]), "Lecture": "Objectif étendu."},
        {"Bloc": "Risk budget", "Valeur": fmt_r(ctx["risk_budget_r"]), "Lecture": "Budget en unité R, pas une recommandation personnalisée."},
        {"Bloc": "Sizing mode", "Valeur": ctx["sizing_mode"], "Lecture": ctx["risk_state_reason"]},
    ]

    return pd.DataFrame(rows)


def build_r_multiple_table(ctx: dict) -> pd.DataFrame:
    rows = [
        {
            "Métrique": "Risque stop court",
            "Prix / niveau": fmt_price(ctx["plan"]["stop_short"]),
            "Distance vs prix": fmt_pct(ctx["stop_short_dist"]),
            "Distance vs limit": fmt_price(ctx["risk_per_share_short"]),
            "R-multiple": "-1.00R",
        },
        {
            "Métrique": "Risque stop structurel",
            "Prix / niveau": fmt_price(ctx["plan"]["stop_structural"]),
            "Distance vs prix": fmt_pct(ctx["stop_struct_dist"]),
            "Distance vs limit": fmt_price(ctx["risk_per_share_struct"]),
            "R-multiple": f"-{fmt_num(ctx['risk_per_share_struct'] / ctx['risk_per_share_short'])}R" if ctx["risk_per_share_short"] else "N/A",
        },
        {
            "Métrique": "Target 1",
            "Prix / niveau": fmt_price(ctx["plan"]["target_1"]),
            "Distance vs prix": fmt_pct(ctx["target1_dist"]),
            "Distance vs limit": fmt_price(ctx["reward_t1"]),
            "R-multiple": fmt_r(ctx.get("rr_t1")),
        },
        {
            "Métrique": "Target 2",
            "Prix / niveau": fmt_price(ctx["plan"]["target_2"]),
            "Distance vs prix": fmt_pct(ctx["target2_dist"]),
            "Distance vs limit": fmt_price(ctx["reward_t2"]),
            "R-multiple": fmt_r(ctx.get("rr_t2")),
        },
    ]
    return pd.DataFrame(rows)


def build_scenario_playbook(ctx: dict) -> pd.DataFrame:
    p = ctx["plan"]
    key = ctx["price_position_key"]
    price = ctx["price"]

    return pd.DataFrame([
        {
            "Priorité": "Haute" if key == "ABOVE_ZONE" else "Moyenne",
            "Scénario": "Pullback propre",
            "Déclencheur": f"Retour dans {fmt_price(p['zone_low'])} → {fmt_price(p['zone_high'])}",
            "Statut actuel": "À attendre" if key == "ABOVE_ZONE" else "À surveiller",
            "Action mécanique": "Autoriser buy limit avec bracket" if ctx["risk_budget_r"] > 0 else "Réévaluer setup",
            "Risque": "Exécution",
            "Invalidation": f"Clôture sous {fmt_price(p['stop_short'])}",
        },
        {
            "Priorité": "Haute" if key == "ABOVE_ZONE" else "Info",
            "Scénario": "Chase / prix étendu",
            "Déclencheur": f"Prix > {fmt_price(p['zone_high'])}",
            "Statut actuel": "Actif" if key == "ABOVE_ZONE" else "Inactif",
            "Action mécanique": "Ne pas acheter au marché ; laisser un limit ou attendre reset",
            "Risque": "Mauvais point d'entrée",
            "Invalidation": "Aucune entrée tant que hors zone",
        },
        {
            "Priorité": "Haute" if key == "IN_ZONE" else "Conditionnelle",
            "Scénario": "Entrée validée",
            "Déclencheur": "Prix dans zone + risque accepté + bracket posé",
            "Statut actuel": "Validé" if key == "IN_ZONE" and ctx["risk_budget_r"] > 0 else "Non validé",
            "Action mécanique": f"Budget max {fmt_r(ctx['risk_budget_r'])} en R-théorique",
            "Risque": ctx["risk_state"],
            "Invalidation": f"Stop court {fmt_price(p['stop_short'])}",
        },
        {
            "Priorité": "Moyenne",
            "Scénario": "Target 1 touché",
            "Déclencheur": f"Prix ≥ {fmt_price(p['target_1'])}",
            "Statut actuel": "Touché" if price >= p["target_1"] else "Non touché",
            "Action mécanique": "Sécuriser le risque / réduire l'exposition théorique",
            "Risque": "Gestion du gain",
            "Invalidation": "Éviter de transformer un gain en perte",
        },
        {
            "Priorité": "Critique",
            "Scénario": "Stop court cassé",
            "Déclencheur": f"Clôture sous {fmt_price(p['stop_short'])}",
            "Statut actuel": "Cassé" if price <= p["stop_short"] else "Non cassé",
            "Action mécanique": "Setup court terme invalidé",
            "Risque": "Invalidation rapide",
            "Invalidation": "Sortie / arrêt du scénario court terme",
        },
        {
            "Priorité": "Critique",
            "Scénario": "Structure cassée",
            "Déclencheur": f"Clôture sous {fmt_price(p['stop_structural'])}",
            "Statut actuel": "Cassée" if price <= p["stop_structural"] else "Non cassée",
            "Action mécanique": "Annuler le scénario",
            "Risque": "Invalidation structurelle",
            "Invalidation": "Ne pas revalider sans nouveau signal",
        },
    ])


def build_invalidation_revalidation_table(ctx: dict) -> pd.DataFrame:
    p = ctx["plan"]
    mc = ctx["mc"]

    return pd.DataFrame([
        {
            "Bloc": "Invalidation rapide",
            "Niveau / condition": f"Clôture sous stop court : {fmt_price(p['stop_short'])}",
            "Lecture": "Le setup court terme est invalidé.",
        },
        {
            "Bloc": "Invalidation structurelle",
            "Niveau / condition": f"Clôture sous stop structurel : {fmt_price(p['stop_structural'])}",
            "Lecture": "Le scénario quantitatif devient trop dégradé.",
        },
        {
            "Bloc": "Invalidation statistique",
            "Niveau / condition": "MC Score < 50 ou espérance MC négative",
            "Lecture": f"Actuel : MC {fmt_score(mc.get('mc_score'))} · Espérance {fmt_pct(mc.get('expected_return'))}.",
        },
        {
            "Bloc": "Revalidation",
            "Niveau / condition": "Prix dans zone + prob. stop < 45% + asymétrie positive",
            "Lecture": "Le setup redevient mécaniquement exploitable.",
        },
        {
            "Bloc": "Upgrade taille",
            "Niveau / condition": "Risk score < 55 + RR T1 >= 1.5 + prix en zone",
            "Lecture": "Le budget peut passer de défensif à standard.",
        },
    ])


def build_export_table(ctx: dict) -> pd.DataFrame:
    p = ctx["plan"]
    mc = ctx["mc"]

    rows = [
        ("Ticker", ctx["ticker"]),
        ("Horizon", f"{ctx['horizon']}D"),
        ("Prix actuel", fmt_price(ctx["price"])),
        ("Signal brut", ctx["signal"]),
        ("Décision finale", ctx["final_action"]),
        ("Action label", ctx["action_label"]),
        ("Type d'ordre", ctx["order_type"]),
        ("Position prix", ctx["price_position"]),
        ("Distance zone", fmt_pct(ctx["distance_to_zone"])),
        ("Entry zone basse", fmt_price(p["zone_low"])),
        ("Entry zone haute", fmt_price(p["zone_high"])),
        ("Preferred limit", fmt_price(ctx["preferred_limit"])),
        ("Stop court", fmt_price(p["stop_short"])),
        ("Stop structurel", fmt_price(p["stop_structural"])),
        ("Target 1", fmt_price(p["target_1"])),
        ("Target 2", fmt_price(p["target_2"])),
        ("RR Target 1", fmt_num(ctx.get("rr_t1"))),
        ("RR Target 2", fmt_num(ctx.get("rr_t2"))),
        ("Risk state", ctx["risk_state"]),
        ("Risk score", fmt_score(ctx["risk_score"])),
        ("Risk budget", fmt_r(ctx["risk_budget_r"])),
        ("Sizing mode", ctx["sizing_mode"]),
        ("Main driver", ctx["main_driver"]),
        ("Prob stop", fmt_pct(mc.get("prob_stop"))),
        ("Prob Target 1", fmt_pct(mc.get("prob_target1"))),
        ("Expected Return MC", fmt_pct(mc.get("expected_return"))),
        ("MC Score", fmt_score(mc.get("mc_score"))),
        ("Raison moteur", ctx["risk_state_reason"]),
    ]

    return pd.DataFrame(rows, columns=["Champ", "Valeur"])


# ============================================================
# CHARTS
# ============================================================

def add_hline_with_label(fig: go.Figure, y: float, label: str, color: str, dash: str = "dash", width: int = 1):
    y = safe_float(y)
    if y is None:
        return

    fig.add_hline(
        y=y,
        line_dash=dash,
        line_color=color,
        line_width=width,
        annotation_text=f"{label} {fmt_price(y)}",
        annotation_position="right",
        annotation_font=dict(color=color, size=12),
    )


def render_execution_map(ctx: dict, price_data: pd.DataFrame):
    df = prepare_price_frame(price_data)

    if df.empty:
        st.info("Graphique indisponible : historique prix vide.")
        return

    df = df.tail(180).copy()
    p = ctx["plan"]

    fig = go.Figure()

    has_ohlc = all(c in df.columns for c in ["open", "high", "low", "close"])
    if has_ohlc:
        fig.add_trace(go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=ctx["ticker"],
            increasing_line_color="#2ecc71",
            decreasing_line_color="#ff7675",
        ))
    else:
        fig.add_trace(go.Scatter(
            x=df["date"],
            y=df["close"],
            mode="lines",
            name="Close",
        ))

    first_date = df["date"].min()
    last_date = df["date"].max()
    future_date = last_date + pd.Timedelta(days=35)

    x0 = first_date
    x1 = future_date

    # Zone entrée.
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=x0,
        x1=x1,
        y0=p["zone_low"],
        y1=p["zone_high"],
        line=dict(width=0),
        fillcolor="rgba(65, 145, 255, 0.16)",
        layer="below",
    )

    # Zone no chase au-dessus de zone jusqu'à Target 1.
    if p["target_1"] > p["zone_high"]:
        fig.add_shape(
            type="rect",
            xref="x",
            yref="y",
            x0=x0,
            x1=x1,
            y0=p["zone_high"],
            y1=p["target_1"],
            line=dict(width=0),
            fillcolor="rgba(255, 184, 0, 0.08)",
            layer="below",
        )

    # Zone invalidation.
    fig.add_shape(
        type="rect",
        xref="x",
        yref="y",
        x0=x0,
        x1=x1,
        y0=min(df["low"].min() if "low" in df.columns else df["close"].min(), p["stop_structural"]),
        y1=p["stop_short"],
        line=dict(width=0),
        fillcolor="rgba(255, 65, 65, 0.08)",
        layer="below",
    )

    add_hline_with_label(fig, ctx["price"], "Prix actuel", "#ffffff", "solid", 2)
    add_hline_with_label(fig, p["zone_high"], "Zone haute", "#4da3ff", "dash", 1)
    add_hline_with_label(fig, p["zone_low"], "Zone basse", "#4da3ff", "dash", 1)
    add_hline_with_label(fig, p["stop_short"], "Stop court", "#ffb000", "dash", 1)
    add_hline_with_label(fig, p["stop_structural"], "Stop structurel", "#ff4d4d", "dot", 2)
    add_hline_with_label(fig, p["target_1"], "Target 1", "#2ecc71", "dash", 1)
    add_hline_with_label(fig, p["target_2"], "Target 2", "#2ecc71", "dot", 1)

    fig.add_annotation(
        x=x0,
        y=(p["zone_low"] + p["zone_high"]) / 2,
        text="ZONE D'ENTRÉE",
        showarrow=False,
        xanchor="left",
        font=dict(color="#9cc8ff", size=12),
    )

    fig.add_annotation(
        x=x0,
        y=(p["zone_high"] + p["target_1"]) / 2 if p["target_1"] > p["zone_high"] else p["zone_high"],
        text="NO CHASE / ATTENTE",
        showarrow=False,
        xanchor="left",
        font=dict(color="#ffd166", size=12),
    )

    fig.add_annotation(
        x=x0,
        y=p["stop_short"],
        text="ZONE STOP / INVALIDATION",
        showarrow=False,
        xanchor="left",
        yshift=-18,
        font=dict(color="#ff9f9f", size=12),
    )

    last_date = df["date"].iloc[-1]
    fig.add_annotation(
        x=last_date,
        y=ctx["price"],
        text=f"{ctx['action_label']}<br>{ctx['order_type']}",
        showarrow=True,
        arrowhead=2,
        ax=-80,
        ay=-70,
        bgcolor="rgba(15, 23, 42, 0.92)",
        bordercolor="#ffd166" if ctx["final_action"].startswith("WAIT") else "#2ecc71",
        borderwidth=1,
        font=dict(color="#ffffff", size=12),
    )

    fig.add_annotation(
        x=x0,
        y=p["target_2"],
        text=(
            f"<b>{ctx['action_label']}</b><br>"
            f"Opportunity {ctx['opportunity_grade']} · Risk {fmt_score(ctx['risk_score'])}<br>"
            f"Budget {fmt_r(ctx['risk_budget_r'])} · {ctx['main_driver']}"
        ),
        showarrow=False,
        xanchor="left",
        yanchor="top",
        bgcolor="rgba(15, 23, 42, 0.92)",
        bordercolor="rgba(148, 163, 184, 0.8)",
        borderwidth=1,
        font=dict(color="#ffffff", size=12),
    )

    y_values = [
        safe_float(ctx["price"]),
        safe_float(p["zone_low"]),
        safe_float(p["zone_high"]),
        safe_float(p["stop_short"]),
        safe_float(p["stop_structural"]),
        safe_float(p["target_1"]),
        safe_float(p["target_2"]),
    ]

    if "low" in df.columns:
        y_values.append(safe_float(df["low"].min()))
    if "high" in df.columns:
        y_values.append(safe_float(df["high"].max()))
    else:
        y_values.append(safe_float(df["close"].min()))
        y_values.append(safe_float(df["close"].max()))

    y_values = [v for v in y_values if v is not None]

    if y_values:
        y_min = min(y_values)
        y_max = max(y_values)
        y_pad = max((y_max - y_min) * 0.08, ctx["price"] * 0.015)
    else:
        y_min, y_max, y_pad = None, None, None

    # Range Y propre : inclut prix, zone, stops, targets et historique.
    y_candidates = [
        safe_float(df["low"].min() if "low" in df.columns else df["close"].min()),
        safe_float(df["high"].max() if "high" in df.columns else df["close"].max()),
        safe_float(ctx["price"]),
        safe_float(p["zone_low"]),
        safe_float(p["zone_high"]),
        safe_float(p["stop_short"]),
        safe_float(p["stop_structural"]),
        safe_float(p["target_1"]),
        safe_float(p["target_2"]),
    ]
    y_candidates = [x for x in y_candidates if x is not None]

    if y_candidates:
        y_min = min(y_candidates)
        y_max = max(y_candidates)
        y_padding = max((y_max - y_min) * 0.08, ctx["price"] * 0.015 if ctx["price"] else 1)
        y_range = [y_min - y_padding, y_max + y_padding]
    else:
        y_range = None

    fig.update_layout(
        height=720,
        title=f"Execution Map — {ctx['ticker']}",
        xaxis_title="Date",
        yaxis_title="Prix",
        template="plotly_dark",
        hovermode="x unified",
        margin=dict(l=40, r=210, t=75, b=45),
        xaxis_rangeslider_visible=False,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10, 14, 22, 0.55)",
        font=dict(color="#f8fafc"),
    )

    fig.update_xaxes(
        range=[first_date, future_date],
        showgrid=False,
        zeroline=False,
        rangeslider_visible=False,
    )

    fig.update_yaxes(
        range=y_range,
        automargin=True,
        showgrid=True,
        gridcolor="rgba(148, 163, 184, 0.18)",
        zeroline=False,
    )

    st.plotly_chart(fig, use_container_width=True)


def render_r_multiple_bar(ctx: dict):
    rows = [
        {"Niveau": "Stop court", "R": -1.0},
        {"Niveau": "Target 1", "R": safe_float(ctx.get("rr_t1"), 0) or 0},
        {"Niveau": "Target 2", "R": safe_float(ctx.get("rr_t2"), 0) or 0},
    ]
    df = pd.DataFrame(rows)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["Niveau"],
        y=df["R"],
        text=df["R"].apply(lambda x: f"{x:.2f}R"),
        textposition="auto",
        name="R-multiple",
    ))
    fig.add_hline(y=0, line_dash="dash")
    fig.add_hline(y=1, line_dash="dot", annotation_text="1R")
    fig.update_layout(
        height=380,
        title="Payoff théorique en R-multiple",
        yaxis_title="R",
        template="plotly_dark",
        margin=dict(l=20, r=20, t=70, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


# ============================================================
# RENDERER
# ============================================================

def render_trading_plan_v2(ticker: str, price_data: pd.DataFrame, analysis: dict):
    st.subheader(f"Trading Plan V2 — {ticker}")

    horizon = st.selectbox(
        "Horizon d'exécution",
        [7, 30, 90],
        index=1,
        key=f"trading_plan_v2_horizon_{ticker}",
    )

    ctx = build_trade_context_v2(
        ticker=ticker,
        price_data=price_data,
        analysis=analysis,
        horizon=int(horizon),
    )

    if not ctx.get("available"):
        st.warning(ctx.get("reason", "Trading Plan V2 indisponible."))
        return

    render_top_trade_cards(ctx)

    msg = ctx["message"]
    if ctx["message_level"] == "success":
        st.success(msg)
    elif ctx["message_level"] == "error":
        st.error(msg)
    elif ctx["message_level"] == "warning":
        st.warning(msg)
    else:
        st.info(msg)

    st.caption(
        f"Prix {fmt_price(ctx['price'])} · Position {ctx['price_position']} · "
        f"Distance zone {fmt_pct(ctx['distance_to_zone'])} · "
        f"Risk {fmt_score(ctx['risk_score'])} · "
        f"MC {fmt_score(ctx['mc'].get('mc_score'))} · "
        f"T1 {fmt_pct(ctx['mc'].get('prob_target1'))} · "
        f"Espérance {fmt_pct(ctx['mc'].get('expected_return'))}"
    )
    st.caption(f"Raison moteur : {ctx['risk_state_reason']}")

    tabs = st.tabs([
        "Executive Ticket",
        "Entry Protocol",
        "Bracket & Sizing",
        "Scenario Playbook",
        "Execution Map",
        "Export",
    ])

    with tabs[0]:
        st.subheader("Execution Ticket")

        ticket = build_order_ticket_table(ctx)
        st.dataframe(ticket, use_container_width=True, hide_index=True, height=table_height(ticket, max_height=440))

        st.subheader("Lecture synthétique")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Opportunity", f"{ctx['opportunity_grade']} / {fmt_score(ctx['opportunity_score'])}")
        k2.metric("Risk State", ctx["risk_state"])
        k3.metric("Sizing", ctx["sizing_mode"])
        k4.metric("Stop dist", fmt_pct(ctx["stop_short_dist"]))
        k5.metric("Target 1 dist", fmt_pct(ctx["target1_dist"]))

        executive_df = pd.DataFrame([
            {
                "Pilier": "Opportunity",
                "Score / lecture": f"{ctx['opportunity_grade']} · {fmt_score(ctx['opportunity_score'])}",
                "Impact": "Qualité du dossier indépendamment du prix d'entrée.",
                "Évidence": f"Signal {ctx['signal']} · Trend {fmt_score(ctx['trend_score'])} · Timing {fmt_score(ctx['timing_score'])}",
            },
            {
                "Pilier": "Execution",
                "Score / lecture": ctx["price_position"],
                "Impact": "Détermine si l'entrée est autorisée maintenant.",
                "Évidence": f"Zone {fmt_price(ctx['plan']['zone_low'])} → {fmt_price(ctx['plan']['zone_high'])} · Prix {fmt_price(ctx['price'])}",
            },
            {
                "Pilier": "Risk",
                "Score / lecture": f"{ctx['risk_state']} · {fmt_score(ctx['risk_score'])}",
                "Impact": "Détermine le budget R théorique.",
                "Évidence": f"Stop {fmt_pct(ctx['mc'].get('prob_stop'))} · VaR95 {fmt_pct(ctx['mc'].get('mc_var95'))} · ATR% {fmt_pct(ctx.get('atr_pct'))}",
            },
            {
                "Pilier": "Asymmetry",
                "Score / lecture": f"RR T1 {fmt_num(ctx.get('rr_t1'))} · T1/Stop {fmt_pct((ctx['mc'].get('prob_target1') or 0) - (ctx['mc'].get('prob_stop') or 0))}",
                "Impact": "Valide ou réduit l'intérêt du trade.",
                "Évidence": f"T1 {fmt_pct(ctx['mc'].get('prob_target1'))} · Stop {fmt_pct(ctx['mc'].get('prob_stop'))}",
            },
        ])

        st.dataframe(
            executive_df,
            use_container_width=True,
            hide_index=True,
            height=table_height(executive_df, max_height=360),
        )

    with tabs[1]:
        st.subheader("Entry Protocol / Gating")
        entry_df = build_entry_protocol_table(ctx)
        st.dataframe(entry_df, use_container_width=True, hide_index=True, height=table_height(entry_df, max_height=360))

        st.subheader("Invalidation / Revalidation")
        inv_df = build_invalidation_revalidation_table(ctx)
        st.dataframe(inv_df, use_container_width=True, hide_index=True, height=table_height(inv_df, max_height=320))

    with tabs[2]:
        st.subheader("Bracket Order théorique")
        bracket_df = build_order_ticket_table(ctx)
        st.dataframe(bracket_df, use_container_width=True, hide_index=True, height=table_height(bracket_df, max_height=520))

        st.subheader("R-Multiple / Payoff")
        r_df = build_r_multiple_table(ctx)
        st.dataframe(r_df, use_container_width=True, hide_index=True, height=table_height(r_df, max_height=280))
        render_r_multiple_bar(ctx)

        with st.expander("Sizing mécanique optionnel", expanded=False):
            st.caption(
                "Calcul purement mécanique : il convertit un budget de risque en nombre d'actions théorique. "
                "Ce n'est pas une recommandation personnalisée."
            )
            risk_capital = st.number_input(
                "Capital risqué par 1R, optionnel",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"trading_plan_v2_risk_capital_{ticker}",
            )

            if risk_capital > 0 and ctx["risk_per_share_short"] > 0:
                allowed_risk = risk_capital * ctx["risk_budget_r"]
                theoretical_shares = allowed_risk / ctx["risk_per_share_short"]
                theoretical_notional = theoretical_shares * ctx["preferred_limit"]

                st.dataframe(
                    pd.DataFrame([
                        {"Champ": "Capital risqué 1R", "Valeur": fmt_price(risk_capital)},
                        {"Champ": "Budget appliqué", "Valeur": fmt_r(ctx["risk_budget_r"])},
                        {"Champ": "Risque monétaire autorisé", "Valeur": fmt_price(allowed_risk)},
                        {"Champ": "Risque par action", "Valeur": fmt_price(ctx["risk_per_share_short"])},
                        {"Champ": "Actions théoriques", "Valeur": fmt_num(theoretical_shares)},
                        {"Champ": "Notionnel théorique", "Valeur": fmt_price(theoretical_notional)},
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Entre un capital de risque 1R pour obtenir une conversion théorique.")

    with tabs[3]:
        st.subheader("Scenario Playbook")
        scenario_df = build_scenario_playbook(ctx)
        st.dataframe(scenario_df, use_container_width=True, hide_index=True, height=table_height(scenario_df, max_height=380))

        st.subheader("Checklist exécution")
        checklist = pd.DataFrame([
            {"Check": "Ordre marché interdit si prix hors zone", "Statut": "OK" if ctx["price_position_key"] != "ABOVE_ZONE" else "Bloquant"},
            {"Check": "Stop défini avant entrée", "Statut": "OK" if ctx["plan"]["stop_short"] < ctx["preferred_limit"] else "KO"},
            {"Check": "Target 1 supérieur à l'entrée", "Statut": "OK" if ctx["plan"]["target_1"] > ctx["preferred_limit"] else "KO"},
            {"Check": "RR Target 1 acceptable", "Statut": "OK" if safe_float(ctx.get("rr_t1"), 0) >= 1 else "Fragile"},
            {"Check": "Probabilité de stop contrôlée", "Statut": "OK" if safe_float(ctx["mc"].get("prob_stop"), 1) < 0.45 else "Fragile"},
            {"Check": "Budget R cohérent avec le risque", "Statut": fmt_r(ctx["risk_budget_r"])},
        ])
        st.dataframe(checklist, use_container_width=True, hide_index=True)

    with tabs[4]:
        st.subheader("Execution Map — prix, zone, stops, targets")
        render_execution_map(ctx, price_data)

    with tabs[5]:
        st.subheader("Export Trading Plan Summary")
        export_df = build_export_table(ctx)
        st.dataframe(export_df, use_container_width=True, hide_index=True, height=table_height(export_df, max_height=760))

        csv = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Télécharger le résumé trading plan CSV",
            data=csv,
            file_name=f"trading_plan_v2_{ticker}.csv",
            mime="text/csv",
            key=f"download_trading_plan_v2_{ticker}",
        )

