# ============================================================
# ML DEEP LEARNING LAB V1 — OPTIONAL / LAZY LOADED MODULE
# ============================================================
# Objectif : ajouter une couche Deep Learning institutionnelle au ML Research Lab
# sans ralentir ni fragiliser le reste du Quant Terminal.
#
# Architecture prudente :
# - ce fichier n'est jamais importé depuis app.py ;
# - il est importé uniquement depuis ml_research_lab.py, dans un expander/toggle ;
# - aucun signal n'est injecté dans Decision Engine ;
# - aucun backtest n'est lancé ici ;
# - les signaux exportés sont compatibles avec Backtest Lab / Custom Signal Import ;
# - le Backtest Lab reste le juge final : coûts, slippage, t+1, safety gate, OOS.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
import hashlib
import math
import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .neural_backends import (
    TORCH_MODEL_NAMES,
    TorchSequenceConfig,
    neural_runtime_status,
    predict_torch_sequence_model,
)
from .sequence_engine import (
    SEQUENCE_MODEL_NAMES,
    build_sequence_uncertainty,
    predict_sequence_model,
    render_sequence_uncertainty,
)

try:
    from sklearn.dummy import DummyClassifier
    from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        accuracy_score,
        balanced_accuracy_score,
        brier_score_loss,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )
    from sklearn.neural_network import MLPClassifier
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except Exception:  # pragma: no cover
    SKLEARN_AVAILABLE = False


TRADING_DAYS = 252
EPS = 1e-12
MODULE_VERSION = "ML-DL-LAB-V2.1-DUAL-NEURAL"
INTEGRATION_PROTOCOL = 2
MODULE_IMPORT_FILE = globals().get("__file__", "unknown")


# ============================================================
# GENERIC HELPERS
# ============================================================


def _safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        if pd.isna(value):
            return default
        out = float(value)
        if not np.isfinite(out):
            return default
        return out
    except Exception:
        return default


def _safe_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, list, tuple, dict)):
            return default
        if pd.isna(value):
            return default
        return int(value)
    except Exception:
        return default


def _clip(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    x = _safe_float(value, low)
    if x is None:
        x = low
    return float(max(low, min(high, x)))


def _fmt_pct(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:.{digits}%}"


def _fmt_num(value: Any, digits: int = 2) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:,.{digits}f}"


def _fmt_score(value: Any) -> str:
    x = _safe_float(value)
    if x is None:
        return "N/A"
    return f"{x:.0f}/100"


def _stable_hash(payload: Any, length: int = 12) -> str:
    text = str(payload).encode("utf-8", errors="ignore")
    return hashlib.sha256(text).hexdigest()[:length]


def _plotly_config() -> dict[str, Any]:
    return {"displayModeBar": False, "responsive": True}


def _table_height(df: pd.DataFrame, row_px: int = 35, min_height: int = 160, max_height: int = 560) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return min_height
    return int(min(max_height, max(min_height, 45 + row_px * len(df))))


# ============================================================
# OPTIONAL DEEP LEARNING BACKEND
# ============================================================


def _try_import_tensorflow() -> tuple[bool, Any, str]:
    """
    Import TensorFlow uniquement au moment où l'utilisateur lance le DL Lab.
    Cela évite de ralentir ou casser le terminal au démarrage.
    """
    try:
        import tensorflow as tf  # type: ignore

        try:
            tf.get_logger().setLevel("ERROR")
        except Exception:
            pass

        return True, tf, getattr(tf, "__version__", "unknown")
    except Exception as exc:  # pragma: no cover
        return False, None, str(exc)


# ============================================================
# PRICE / FEATURE ENGINEERING
# ============================================================


def normalize_price_frame_v1(price_data: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(price_data, pd.DataFrame) or price_data.empty:
        return pd.DataFrame()

    df = price_data.copy()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = ["_".join([str(x) for x in col if str(x) not in ["", "None"]]) for col in df.columns]

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    if "date" not in df.columns:
        df = df.reset_index()
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
        if "index" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"index": "date"})
        if "datetime" in df.columns and "date" not in df.columns:
            df = df.rename(columns={"datetime": "date"})

    if "adj_close" in df.columns and "close" not in df.columns:
        df["close"] = df["adj_close"]
    if "adj_close" not in df.columns and "close" in df.columns:
        df["adj_close"] = df["close"]

    if "close" not in df.columns:
        return pd.DataFrame()

    for col in ["open", "high", "low", "close", "adj_close", "volume"]:
        if col not in df.columns:
            if col in ["open", "high", "low"]:
                df[col] = df["close"]
            elif col == "volume":
                df[col] = np.nan
            elif col == "adj_close":
                df[col] = df["close"]
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["date"] = pd.to_datetime(df.get("date"), errors="coerce").dt.tz_localize(None)
    df = df.dropna(subset=["date", "close"])
    df = df.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    df = df.replace([np.inf, -np.inf], np.nan).reset_index(drop=True)

    return df


def _rsi(close: pd.Series, window: int = 14) -> pd.Series:
    close = pd.to_numeric(close, errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / max(window, 1), adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / max(window, 1), adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    close = pd.to_numeric(df["close"], errors="coerce")
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.rolling(window, min_periods=max(3, window // 2)).mean()


def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    minp = min(int(window), max(2, int(window) // 3))
    mean = s.rolling(window, min_periods=minp).mean()
    std = s.rolling(window, min_periods=minp).std(ddof=1)
    return (s - mean) / std.replace(0, np.nan)


def _downside_vol(returns: pd.Series, window: int) -> pd.Series:
    r = pd.to_numeric(returns, errors="coerce")
    downside = r.where(r < 0.0, 0.0)
    return downside.rolling(window, min_periods=max(5, window // 3)).std(ddof=1) * math.sqrt(TRADING_DAYS)


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    x = np.arange(window, dtype=float)
    x = x - x.mean()
    denom = float(np.sum(x * x))

    def calc(values: np.ndarray) -> float:
        y = np.asarray(values, dtype=float)
        if np.isnan(y).any() or denom <= 0:
            return np.nan
        y = y - y.mean()
        return float(np.sum(x * y) / denom)

    return s.rolling(window, min_periods=window).apply(calc, raw=True)


def extract_current_context_snapshot_v1(analysis: dict | None) -> pd.DataFrame:
    """
    Extrait quelques métriques des autres modules en lecture current-only.
    Elles ne sont PAS utilisées dans l'entraînement historique par défaut,
    car elles peuvent être calculées avec information récente et créer du look-ahead.
    """
    if not isinstance(analysis, dict):
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []

    def add(path: str, value: Any, usage: str, comment: str) -> None:
        x = _safe_float(value)
        if x is None:
            return
        rows.append(
            {
                "Feature contextuelle": path,
                "Valeur": x,
                "Usage autorisé": usage,
                "Lecture": comment,
            }
        )

    # Top-level scores.
    for key in ["global_score", "composite_score", "score", "decision_score", "trend_score", "atr"]:
        if key in analysis:
            add(key, analysis.get(key), "Current inference only", "Non injecté dans l'entraînement historique.")

    company = analysis.get("company_analysis", {}) if isinstance(analysis.get("company_analysis", {}), dict) else {}
    scores = company.get("scores", {}) if isinstance(company.get("scores", {}), dict) else {}
    for key in [
        "company_score",
        "growth_score",
        "profitability_score",
        "balance_score",
        "valuation_score",
        "forward_score",
        "analyst_score",
        "sentiment_score",
    ]:
        if key in scores:
            add(f"company_analysis.scores.{key}", scores.get(key), "Current inference only", "Snapshot fondamental actuel seulement.")

    momentum = analysis.get("momentum_v2", {}) if isinstance(analysis.get("momentum_v2", {}), dict) else {}
    latest = momentum.get("latest", {}) if isinstance(momentum.get("latest", {}), dict) else {}
    for key in [
        "trend_score",
        "momentum_score",
        "timing_score",
        "setup_score",
        "relative_strength_score",
        "breakout_quality_score",
        "pullback_quality_score",
        "exhaustion_risk_score",
        "entry_timing_quality_score",
        "noise_risk",
    ]:
        if key in latest:
            add(f"momentum_v2.latest.{key}", latest.get(key), "Current inference only", "Snapshot technique actuel seulement.")

    return pd.DataFrame(rows)


def build_deep_feature_frame_v1(price_data: pd.DataFrame, analysis: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Feature store causal : uniquement des informations connues à la clôture de chaque date.
    Les colonnes forward_* et labels sont construites plus tard et exclues des features.
    """
    df = normalize_price_frame_v1(price_data)
    context = extract_current_context_snapshot_v1(analysis)

    if df.empty or len(df) < 120:
        return pd.DataFrame(), context

    close = pd.to_numeric(df["close"], errors="coerce")
    high = pd.to_numeric(df["high"], errors="coerce")
    low = pd.to_numeric(df["low"], errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")

    ret = close.pct_change()
    log_ret = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan)

    out = df[["date", "open", "high", "low", "close", "volume"]].copy()
    out["return_1d"] = ret
    out["log_return_1d"] = log_ret

    for h in [2, 3, 5, 10, 20, 40, 60, 120]:
        out[f"return_{h}d"] = close.pct_change(h)
        out[f"log_return_{h}d"] = np.log(close / close.shift(h)).replace([np.inf, -np.inf], np.nan)
        out[f"price_z_{h}d"] = _rolling_zscore(close, h)

    for w in [5, 10, 20, 40, 60, 120]:
        out[f"realized_vol_{w}d"] = ret.rolling(w, min_periods=max(5, w // 3)).std(ddof=1) * math.sqrt(TRADING_DAYS)
        out[f"downside_vol_{w}d"] = _downside_vol(ret, w)
        mom_minp = min(int(w), max(5, int(w) // 2))
        out[f"return_skew_{w}d"] = ret.rolling(w, min_periods=mom_minp).skew()
        out[f"return_kurt_{w}d"] = ret.rolling(w, min_periods=mom_minp).kurt()

    out["atr_14"] = _atr(df, 14)
    out["atr_pct"] = out["atr_14"] / close.replace(0, np.nan)
    out["hl_range_pct"] = (high - low) / close.replace(0, np.nan)
    out["close_to_high_pct"] = close / high.replace(0, np.nan) - 1.0
    out["close_to_low_pct"] = close / low.replace(0, np.nan) - 1.0

    for span in [10, 20, 50, 100, 200]:
        ema = close.ewm(span=span, adjust=False, min_periods=max(5, span // 3)).mean()
        sma = close.rolling(span, min_periods=max(5, span // 3)).mean()
        out[f"price_vs_ema_{span}"] = close / ema.replace(0, np.nan) - 1.0
        out[f"price_vs_sma_{span}"] = close / sma.replace(0, np.nan) - 1.0
        out[f"ema_slope_{span}"] = _rolling_slope(np.log(ema.replace(0, np.nan)), min(span, 60))

    out["rsi_14"] = _rsi(close, 14)
    out["rsi_28"] = _rsi(close, 28)
    out["rsi_delta"] = out["rsi_14"] - out["rsi_28"]

    ema12 = close.ewm(span=12, adjust=False, min_periods=6).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=10).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=5).mean()
    out["macd_pct"] = macd / close.replace(0, np.nan)
    out["macd_signal_pct"] = macd_signal / close.replace(0, np.nan)
    out["macd_hist_pct"] = (macd - macd_signal) / close.replace(0, np.nan)

    rolling_high = close.cummax()
    out["drawdown"] = close / rolling_high.replace(0, np.nan) - 1.0
    out["drawdown_z_60d"] = _rolling_zscore(out["drawdown"], 60)

    for w in [20, 60, 120]:
        prev_high = close.shift(1).rolling(w, min_periods=max(5, w // 3)).max()
        prev_low = close.shift(1).rolling(w, min_periods=max(5, w // 3)).min()
        out[f"breakout_{w}d"] = close / prev_high.replace(0, np.nan) - 1.0
        out[f"breakdown_{w}d"] = close / prev_low.replace(0, np.nan) - 1.0
        out[f"range_position_{w}d"] = (close - prev_low) / (prev_high - prev_low).replace(0, np.nan)

    if volume.notna().sum() >= 40:
        out["volume_z_20d"] = _rolling_zscore(volume, 20)
        out["volume_z_60d"] = _rolling_zscore(volume, 60)
        out["dollar_volume"] = volume * close
        out["dollar_volume_z_60d"] = _rolling_zscore(out["dollar_volume"], 60)
        out["volume_trend_20d"] = _rolling_slope(np.log(volume.replace(0, np.nan)), 20)
    else:
        out["volume_z_20d"] = np.nan
        out["volume_z_60d"] = np.nan
        out["dollar_volume"] = np.nan
        out["dollar_volume_z_60d"] = np.nan
        out["volume_trend_20d"] = np.nan

    # Regime proxies, still causal.
    out["vol_regime_20_vs_120"] = out["realized_vol_20d"] / out["realized_vol_120d"].replace(0, np.nan) - 1.0
    out["trend_regime_50_200"] = out["price_vs_sma_50"] - out["price_vs_sma_200"]
    out["momentum_regime_20_60"] = out["return_20d"] - out["return_60d"]

    out = out.replace([np.inf, -np.inf], np.nan)
    return out.reset_index(drop=True), context


# ============================================================
# LABEL ENGINE
# ============================================================


def make_deep_triple_barrier_labels_v1(
    feature_df: pd.DataFrame,
    horizon: int = 20,
    pt_mult: float = 1.5,
    sl_mult: float = 1.5,
    conservative_intraday: bool = True,
) -> pd.DataFrame:
    if feature_df is None or feature_df.empty:
        return pd.DataFrame()

    df = feature_df.copy().reset_index(drop=True)
    n = len(df)

    for col in [
        "tb_label",
        "target_success",
        "tb_entry_price",
        "tb_exit_price",
        "tb_tp_price",
        "tb_sl_price",
        "tb_return",
        "tb_mfe",
        "tb_mae",
        "tb_holding_days",
    ]:
        df[col] = np.nan

    df["tb_event"] = pd.Series([pd.NA] * n, dtype="object")
    df["tb_event_start"] = pd.NaT
    df["tb_event_end"] = pd.NaT
    df["available_at"] = pd.NaT

    horizon = max(int(horizon), 1)
    last_start = n - horizon - 1
    if last_start <= 0:
        return df

    for i in range(0, last_start + 1):
        entry = _safe_float(df.loc[i, "close"])
        atr = _safe_float(df.loc[i, "atr_14"])
        if entry is None or entry <= 0:
            continue
        if atr is None or atr <= 0:
            vol = _safe_float(df.loc[i, "realized_vol_20d"])
            if vol is None or vol <= 0:
                continue
            atr = entry * vol / math.sqrt(TRADING_DAYS)

        tp_price = entry + float(pt_mult) * atr
        sl_price = entry - float(sl_mult) * atr
        future = df.iloc[i + 1 : i + horizon + 1]
        if future.empty:
            continue

        label = 0.0
        event = "TIMEOUT"
        exit_idx = int(future.index[-1])
        exit_price = _safe_float(future.iloc[-1].get("close"), entry) or entry

        for idx, row in future.iterrows():
            high = _safe_float(row.get("high"))
            low = _safe_float(row.get("low"))
            close = _safe_float(row.get("close"), entry) or entry
            if high is None or low is None:
                continue

            hit_tp = high >= tp_price
            hit_sl = low <= sl_price

            if hit_tp and hit_sl:
                exit_idx = int(idx)
                if conservative_intraday:
                    label = -1.0
                    event = "SL_AND_TP_SAME_DAY_CONSERVATIVE_SL"
                    exit_price = sl_price
                else:
                    label = 0.0
                    event = "SL_AND_TP_SAME_DAY_UNRESOLVED"
                    exit_price = close
                break

            if hit_sl:
                label = -1.0
                event = "SL_FIRST"
                exit_idx = int(idx)
                exit_price = sl_price
                break

            if hit_tp:
                label = 1.0
                event = "TP_FIRST"
                exit_idx = int(idx)
                exit_price = tp_price
                break

        future_high = _safe_float(future["high"].max(), entry) or entry
        future_low = _safe_float(future["low"].min(), entry) or entry

        df.loc[i, "tb_label"] = label
        df.loc[i, "target_success"] = 1.0 if label == 1.0 else 0.0
        df.loc[i, "tb_event"] = event
        df.loc[i, "tb_entry_price"] = entry
        df.loc[i, "tb_exit_price"] = exit_price
        df.loc[i, "tb_tp_price"] = tp_price
        df.loc[i, "tb_sl_price"] = sl_price
        df.loc[i, "tb_return"] = exit_price / entry - 1.0
        df.loc[i, "tb_mfe"] = future_high / entry - 1.0
        df.loc[i, "tb_mae"] = future_low / entry - 1.0
        df.loc[i, "tb_holding_days"] = int(exit_idx - i)

        if "date" in df.columns:
            start_date = pd.to_datetime(df.loc[i, "date"], errors="coerce")
            end_date = pd.to_datetime(df.loc[exit_idx, "date"], errors="coerce")
            df.loc[i, "tb_event_start"] = start_date
            df.loc[i, "tb_event_end"] = end_date
            df.loc[i, "available_at"] = start_date

    return df.replace([np.inf, -np.inf], np.nan)


# ============================================================
# DATASET / SPLIT ENGINE
# ============================================================


def select_deep_feature_columns_v1(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty:
        return []

    forbidden_prefixes = (
        "tb_",
        "target_",
        "forward_",
        "future_",
        "label_",
        "y_",
    )
    forbidden_exact = {
        "date",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adj_close",
        "ticker",
    }

    cols: list[str] = []
    for col in df.columns:
        name = str(col)
        low = name.lower()
        if low in forbidden_exact:
            continue
        if low.startswith(forbidden_prefixes):
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            valid_ratio = pd.to_numeric(df[col], errors="coerce").notna().mean()
            if valid_ratio >= 0.45:
                cols.append(name)

    return cols


def build_supervised_dataset_v1(
    labeled_df: pd.DataFrame,
    timeout_policy: str = "failure",
) -> pd.DataFrame:
    if labeled_df is None or labeled_df.empty or "tb_label" not in labeled_df.columns:
        return pd.DataFrame()

    df = labeled_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["tb_event_start"] = pd.to_datetime(df.get("tb_event_start"), errors="coerce")
    df["tb_event_end"] = pd.to_datetime(df.get("tb_event_end"), errors="coerce")
    df["available_at"] = pd.to_datetime(df.get("available_at"), errors="coerce").fillna(df["date"])

    df = df.dropna(subset=["date", "tb_label", "tb_event_start", "tb_event_end"]).copy()

    if timeout_policy == "drop":
        df = df[df["tb_label"] != 0].copy()
        df["target_success"] = (df["tb_label"] == 1).astype(float)
    else:
        df["target_success"] = (df["tb_label"] == 1).astype(float)

    return df.sort_values("date").reset_index(drop=True)


def build_purged_walk_forward_splits_v1(
    df: pd.DataFrame,
    n_splits: int = 4,
    embargo_days: int = 5,
    min_train_size: int = 120,
    min_test_size: int = 30,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """
    Purged walk-forward adaptatif V1.1.

    Correctif important : sur une fenêtre courte type 1y daily, un split fixe
    4 folds x 30 tests peut devenir impossible même avec 218 labels exploitables
    (98 observations test restantes / 4 folds = 24.5).

    La fonction réduit donc le nombre effectif de folds avant de déclarer KO.
    Elle ne réduit pas la purge, ne supprime pas l'embargo et ne crée jamais
    de train après le test. Si l'échantillon reste trop court, l'audit explique
    pourquoi au lieu de rester vide.
    """
    if df is None or df.empty:
        return [], pd.DataFrame(
            [{
                "Fold": 0,
                "Status": "Dataset empty",
                "Train size": 0,
                "Test size": 0,
                "Test start": pd.NaT,
                "Test end": pd.NaT,
                "Embargo days": int(embargo_days),
                "Purged removed": 0,
                "Overlap after purge": 0,
                "Train TP %": np.nan,
                "Test TP %": np.nan,
                "Read": "Dataset supervisé vide."
            }]
        )

    work = df.dropna(subset=["date", "tb_event_start", "tb_event_end", "target_success"]).copy()
    work = work.sort_values("tb_event_start").reset_index(drop=True)

    n = len(work)
    min_train_size = max(40, int(min_train_size))
    min_test_size = max(10, int(min_test_size))
    requested_splits = max(2, int(n_splits))

    if n < min_train_size + min_test_size:
        return [], pd.DataFrame(
            [{
                "Fold": 0,
                "Status": "Sample too small",
                "Train size": int(n),
                "Test size": 0,
                "Test start": pd.NaT,
                "Test end": pd.NaT,
                "Embargo days": int(embargo_days),
                "Purged removed": 0,
                "Overlap after purge": 0,
                "Train TP %": np.nan,
                "Test TP %": np.nan,
                "Read": f"{n} labels supervisés < min_train {min_train_size} + min_test {min_test_size}. Charge plus d'historique ou baisse lookback/min test."
            }]
        )

    # Fenêtre train initiale : assez large pour entraîner, mais pas si large
    # qu'elle rend les folds impossibles sur 1y daily.
    initial_train_end = max(min_train_size, int(n * 0.35))
    initial_train_end = min(initial_train_end, n - min_test_size)

    test_positions = np.arange(initial_train_end, n)
    test_available = int(len(test_positions))

    if test_available < min_test_size:
        return [], pd.DataFrame(
            [{
                "Fold": 0,
                "Status": "Test window too small",
                "Train size": int(initial_train_end),
                "Test size": int(test_available),
                "Test start": pd.NaT,
                "Test end": pd.NaT,
                "Embargo days": int(embargo_days),
                "Purged removed": 0,
                "Overlap after purge": 0,
                "Train TP %": np.nan,
                "Test TP %": np.nan,
                "Read": f"Fenêtre test restante {test_available} < min_test {min_test_size}."
            }]
        )

    # Réduit le nombre de folds au maximum compatible avec min_test_size.
    effective_splits = min(requested_splits, max(1, test_available // min_test_size))
    if effective_splits < 2 and test_available >= min_test_size * 2:
        effective_splits = 2
    if effective_splits < 1:
        effective_splits = 1

    chunks = [chunk for chunk in np.array_split(test_positions, effective_splits) if len(chunk) > 0]

    splits: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    embargo_delta = pd.Timedelta(days=int(embargo_days))

    for fold_id, chunk in enumerate(chunks, start=1):
        test_start_pos = int(chunk[0])
        test_end_pos = int(chunk[-1])
        test_start = pd.Timestamp(work.loc[test_start_pos, "tb_event_start"])
        test_end = pd.Timestamp(work.loc[test_end_pos, "tb_event_start"])
        embargo_cutoff = test_start - embargo_delta

        test_mask = (work["tb_event_start"] >= test_start) & (work["tb_event_start"] <= test_end)
        train_candidate_mask = work["tb_event_start"] < test_start
        train_mask = train_candidate_mask & (work["tb_event_end"] < embargo_cutoff)

        train_idx = work.index[train_mask].to_numpy(dtype=int)
        test_idx = work.index[test_mask].to_numpy(dtype=int)

        purged_removed = int(train_candidate_mask.sum() - train_mask.sum())
        overlap_after_purge = 0
        if len(train_idx) > 0:
            overlap_after_purge = int((work.loc[train_idx, "tb_event_end"] >= test_start).sum())

        y_train = work.loc[train_idx, "target_success"] if len(train_idx) else pd.Series(dtype=float)
        y_test = work.loc[test_idx, "target_success"] if len(test_idx) else pd.Series(dtype=float)

        status = "OK"
        read = "Fold exploitable."
        if len(train_idx) < min_train_size:
            status = "Train too small"
            read = f"Train final {len(train_idx)} < min_train {min_train_size} après purge/embargo."
        elif len(test_idx) < min_test_size:
            status = "Test too small"
            read = f"Test {len(test_idx)} < min_test {min_test_size}."
        elif y_train.nunique(dropna=True) < 2:
            status = "Train one-class"
            read = "Le train ne contient qu'une classe cible."
        elif y_test.nunique(dropna=True) < 2:
            status = "Test one-class"
            read = "Le test ne contient qu'une classe cible."
        elif overlap_after_purge > 0:
            status = "Leakage risk"
            read = "Overlap résiduel après purge."

        row = {
            "Fold": fold_id,
            "Status": status,
            "Train size": int(len(train_idx)),
            "Test size": int(len(test_idx)),
            "Test start": test_start,
            "Test end": test_end,
            "Embargo days": int(embargo_days),
            "Purged removed": purged_removed,
            "Overlap after purge": overlap_after_purge,
            "Train TP %": float(y_train.mean()) if len(y_train) else np.nan,
            "Test TP %": float(y_test.mean()) if len(y_test) else np.nan,
            "Requested folds": int(requested_splits),
            "Effective folds": int(effective_splits),
            "Read": read,
        }
        rows.append(row)

        if status == "OK":
            splits.append(
                {
                    "fold": fold_id,
                    "train_idx": train_idx,
                    "test_idx": test_idx,
                    "test_start": test_start,
                    "test_end": test_end,
                }
            )

    return splits, pd.DataFrame(rows)


def make_sequence_arrays_v1(
    df: pd.DataFrame,
    feature_cols: list[str],
    lookback: int,
) -> tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    if df is None or df.empty or not feature_cols:
        return np.empty((0, 0, 0)), np.array([]), pd.DataFrame()

    lookback = max(int(lookback), 2)
    work = df.copy().reset_index(drop=True)
    values = work[feature_cols].apply(pd.to_numeric, errors="coerce")
    values = values.replace([np.inf, -np.inf], np.nan)
    values = values.ffill().bfill()

    X_rows: list[np.ndarray] = []
    y_rows: list[float] = []
    meta_rows: list[dict[str, Any]] = []

    for i in range(lookback - 1, len(work)):
        seq = values.iloc[i - lookback + 1 : i + 1].to_numpy(dtype=float)
        target = _safe_float(work.loc[i, "target_success"])
        if target is None or not np.isfinite(seq).all():
            continue
        X_rows.append(seq)
        y_rows.append(float(target))
        meta_rows.append(
            {
                "row_id": int(i),
                "date": work.loc[i, "date"],
                "available_at": work.loc[i, "available_at"],
                "tb_event_start": work.loc[i, "tb_event_start"],
                "tb_event_end": work.loc[i, "tb_event_end"],
                "target_success": work.loc[i, "target_success"],
                "tb_label": work.loc[i, "tb_label"],
                "tb_event": work.loc[i, "tb_event"],
                "tb_return": work.loc[i, "tb_return"],
                "tb_mfe": work.loc[i, "tb_mfe"],
                "tb_mae": work.loc[i, "tb_mae"],
                "tb_holding_days": work.loc[i, "tb_holding_days"],
            }
        )

    if not X_rows:
        return np.empty((0, 0, 0)), np.array([]), pd.DataFrame()

    return np.stack(X_rows), np.asarray(y_rows, dtype=float), pd.DataFrame(meta_rows)


def _sequence_index_map(meta: pd.DataFrame) -> dict[int, int]:
    return {int(row_id): int(pos) for pos, row_id in enumerate(meta["row_id"].astype(int).tolist())}


def _scale_sequences_train_test(
    X_train: np.ndarray,
    X_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    if not SKLEARN_AVAILABLE:
        # Fallback manuel train-only.
        flat = X_train.reshape(-1, X_train.shape[-1])
        mean = np.nanmean(flat, axis=0)
        std = np.nanstd(flat, axis=0)
        std = np.where(std <= EPS, 1.0, std)
        return (X_train - mean) / std, (X_test - mean) / std

    scaler = StandardScaler()
    n_features = X_train.shape[-1]
    flat_train = X_train.reshape(-1, n_features)
    scaler.fit(flat_train)
    train_scaled = scaler.transform(flat_train).reshape(X_train.shape)
    test_scaled = scaler.transform(X_test.reshape(-1, n_features)).reshape(X_test.shape)
    return train_scaled, test_scaled



# ============================================================
# SEQUENCE-LEVEL PURGED WFO V1.2
# ============================================================


def build_sequence_purged_walk_forward_splits_v12(
    meta_seq: pd.DataFrame,
    y_seq: np.ndarray,
    n_splits: int = 4,
    embargo_days: int = 5,
    min_train_size: int = 80,
    min_test_size: int = 25,
    lookback: int = 30,
) -> tuple[list[dict[str, Any]], pd.DataFrame]:
    """
    V1.2 : split purgé directement au niveau des séquences utilisables.

    Pourquoi : le V1.0/V1.1 pouvait construire des folds sur les lignes brutes,
    puis les perdre après transformation en séquences (lookback). Cette version
    splitte uniquement les observations réellement entraînables.

    Garanties conservées :
    - train strictement avant test ;
    - purge des événements train dont tb_event_end chevauche le test ;
    - embargo avant la fenêtre test ;
    - adaptation du nombre de folds si la fenêtre 1y est courte ;
    - fallback holdout purgé si le WFO multi-fold est impossible.
    """
    if meta_seq is None or meta_seq.empty or y_seq is None or len(y_seq) == 0:
        return [], pd.DataFrame([
            {
                "Fold": 0,
                "Status": "Dataset empty",
                "Mode": "none",
                "Train size": 0,
                "Test size": 0,
                "Test start": pd.NaT,
                "Test end": pd.NaT,
                "Embargo days": int(embargo_days),
                "Purged removed": 0,
                "Overlap after purge": 0,
                "Train TP %": np.nan,
                "Test TP %": np.nan,
                "Requested folds": int(n_splits),
                "Effective folds": 0,
                "Read": "Aucune séquence exploitable après lookback/missing values.",
            }
        ])

    work = meta_seq.copy().reset_index(drop=True)
    work["seq_pos"] = np.arange(len(work), dtype=int)
    work["y"] = np.asarray(y_seq, dtype=float)[: len(work)]

    for col in ["date", "available_at", "tb_event_start", "tb_event_end"]:
        if col in work.columns:
            work[col] = pd.to_datetime(work[col], errors="coerce")

    if "tb_event_start" not in work.columns or work["tb_event_start"].isna().all():
        work["tb_event_start"] = pd.to_datetime(work.get("date"), errors="coerce")
    if "tb_event_end" not in work.columns or work["tb_event_end"].isna().all():
        # Fallback prudent : l'événement finit à la date courante si l'ancien fichier
        # n'avait pas encore les colonnes meta enrichies. Cela ne crée pas de fuite,
        # mais rend la purge moins informative.
        work["tb_event_end"] = pd.to_datetime(work.get("date"), errors="coerce")

    work = work.dropna(subset=["date", "tb_event_start", "tb_event_end", "y"]).copy()
    work = work.sort_values("tb_event_start").reset_index(drop=True)
    work["seq_pos"] = work["seq_pos"].astype(int)

    n = int(len(work))
    requested_splits = max(1, int(n_splits))
    min_test_size = max(8, int(min_test_size))

    # Le seuil train est adaptatif mais borné : suffisamment grand pour éviter un
    # entraînement absurde, pas tellement grand qu'un 1y daily devienne impossible.
    requested_train = max(30, int(min_train_size))
    sequence_floor = max(30, int(lookback) + 10)
    max_feasible_train = max(sequence_floor, n - min_test_size)
    effective_min_train = min(max(requested_train, sequence_floor), max_feasible_train)

    rows: list[dict[str, Any]] = []
    splits: list[dict[str, Any]] = []
    embargo_delta = pd.Timedelta(days=int(embargo_days))

    def _make_row(
        fold_id: int,
        status: str,
        mode: str,
        train_pos: np.ndarray,
        test_pos: np.ndarray,
        test_start: Any,
        test_end: Any,
        purged_removed: int,
        overlap_after_purge: int,
        read: str,
        effective_folds: int,
    ) -> dict[str, Any]:
        y_train = work.loc[train_pos, "y"] if len(train_pos) else pd.Series(dtype=float)
        y_test = work.loc[test_pos, "y"] if len(test_pos) else pd.Series(dtype=float)
        return {
            "Fold": int(fold_id),
            "Status": str(status),
            "Mode": str(mode),
            "Train size": int(len(train_pos)),
            "Test size": int(len(test_pos)),
            "Test start": test_start,
            "Test end": test_end,
            "Embargo days": int(embargo_days),
            "Purged removed": int(purged_removed),
            "Overlap after purge": int(overlap_after_purge),
            "Train TP %": float(y_train.mean()) if len(y_train) else np.nan,
            "Test TP %": float(y_test.mean()) if len(y_test) else np.nan,
            "Train classes": int(y_train.nunique(dropna=True)) if len(y_train) else 0,
            "Test classes": int(y_test.nunique(dropna=True)) if len(y_test) else 0,
            "Requested folds": int(requested_splits),
            "Effective folds": int(effective_folds),
            "Effective min train": int(effective_min_train),
            "Min test": int(min_test_size),
            "Sequence rows": int(n),
            "Read": str(read),
        }

    if n < effective_min_train + min_test_size:
        rows.append(_make_row(
            0,
            "Sample too small",
            "none",
            np.array([], dtype=int),
            np.array([], dtype=int),
            pd.NaT,
            pd.NaT,
            0,
            0,
            f"{n} séquences < min_train {effective_min_train} + min_test {min_test_size}. Charge plus d'historique ou baisse lookback/min test.",
            0,
        ))
        return [], pd.DataFrame(rows)

    initial_train_end = max(effective_min_train, int(n * 0.35))
    initial_train_end = min(initial_train_end, n - min_test_size)
    test_positions = np.arange(initial_train_end, n, dtype=int)
    test_available = int(len(test_positions))

    effective_splits = min(requested_splits, max(1, test_available // min_test_size))
    # Évite des chunks trop petits sur 1y daily.
    effective_splits = max(1, effective_splits)
    chunks = [chunk for chunk in np.array_split(test_positions, effective_splits) if len(chunk) > 0]

    for fold_id, chunk in enumerate(chunks, start=1):
        test_start_pos = int(chunk[0])
        test_end_pos = int(chunk[-1])
        test_start = pd.Timestamp(work.loc[test_start_pos, "tb_event_start"])
        test_end = pd.Timestamp(work.loc[test_end_pos, "tb_event_start"])
        embargo_cutoff = test_start - embargo_delta

        test_mask = (work["tb_event_start"] >= test_start) & (work["tb_event_start"] <= test_end)
        train_candidate_mask = work["tb_event_start"] < test_start
        train_mask = train_candidate_mask & (work["tb_event_end"] < embargo_cutoff)

        train_work_pos = work.index[train_mask].to_numpy(dtype=int)
        test_work_pos = work.index[test_mask].to_numpy(dtype=int)
        purged_removed = int(train_candidate_mask.sum() - train_mask.sum())
        overlap_after_purge = int((work.loc[train_work_pos, "tb_event_end"] >= test_start).sum()) if len(train_work_pos) else 0

        y_train = work.loc[train_work_pos, "y"] if len(train_work_pos) else pd.Series(dtype=float)
        y_test = work.loc[test_work_pos, "y"] if len(test_work_pos) else pd.Series(dtype=float)

        status = "OK"
        read = "Fold séquence exploitable."
        if len(train_work_pos) < effective_min_train:
            status = "Train too small"
            read = f"Train final {len(train_work_pos)} < min_train adaptatif {effective_min_train} après purge/embargo."
        elif len(test_work_pos) < min_test_size:
            status = "Test too small"
            read = f"Test {len(test_work_pos)} < min_test {min_test_size}."
        elif y_train.nunique(dropna=True) < 2:
            status = "Train one-class"
            read = "Train one-class : seul Dummy/prior peut être interprété ; modèles discriminants ignorés."
        elif overlap_after_purge > 0:
            status = "Leakage risk"
            read = "Overlap résiduel après purge."
        elif y_test.nunique(dropna=True) < 2:
            # Pas hard block : AUC peut être NaN, mais on garde le fold pour produire
            # des probabilités OOS et diagnostiquer le régime.
            status = "OK"
            read = "Fold utilisable ; test one-class, AUC potentiellement NaN."

        row = _make_row(fold_id, status, "adaptive WFO", train_work_pos, test_work_pos, test_start, test_end, purged_removed, overlap_after_purge, read, effective_splits)
        rows.append(row)

        if status == "OK":
            splits.append({
                "fold": int(fold_id),
                "train_seq_idx": work.loc[train_work_pos, "seq_pos"].to_numpy(dtype=int),
                "test_seq_idx": work.loc[test_work_pos, "seq_pos"].to_numpy(dtype=int),
                "test_start": test_start,
                "test_end": test_end,
                "mode": "adaptive WFO",
            })

    # Fallback institutionnel : un seul holdout purgé, uniquement si aucun fold OK.
    # Cela évite une interface vide tout en restant causal. Il est explicitement marqué.
    if not splits:
        test_size = min(max(min_test_size, int(n * 0.20)), max(8, n - effective_min_train))
        test_work_pos = np.arange(n - test_size, n, dtype=int)
        test_start = pd.Timestamp(work.loc[int(test_work_pos[0]), "tb_event_start"])
        test_end = pd.Timestamp(work.loc[int(test_work_pos[-1]), "tb_event_start"])
        embargo_cutoff = test_start - embargo_delta
        train_candidate_mask = work["tb_event_start"] < test_start
        train_mask = train_candidate_mask & (work["tb_event_end"] < embargo_cutoff)
        train_work_pos = work.index[train_mask].to_numpy(dtype=int)
        purged_removed = int(train_candidate_mask.sum() - train_mask.sum())
        overlap_after_purge = int((work.loc[train_work_pos, "tb_event_end"] >= test_start).sum()) if len(train_work_pos) else 0

        if len(train_work_pos) >= max(30, min(effective_min_train, n - test_size)) and len(test_work_pos) >= 8 and overlap_after_purge == 0:
            rows.append(_make_row(
                len(rows) + 1,
                "OK",
                "fallback purged holdout",
                train_work_pos,
                test_work_pos,
                test_start,
                test_end,
                purged_removed,
                overlap_after_purge,
                "Fallback holdout purgé activé car aucun fold multi-WFO n'était exploitable. Diagnostic seulement.",
                1,
            ))
            splits.append({
                "fold": int(len(rows)),
                "train_seq_idx": work.loc[train_work_pos, "seq_pos"].to_numpy(dtype=int),
                "test_seq_idx": work.loc[test_work_pos, "seq_pos"].to_numpy(dtype=int),
                "test_start": test_start,
                "test_end": test_end,
                "mode": "fallback purged holdout",
            })

    return splits, pd.DataFrame(rows)

# ============================================================
# METRICS / GATES
# ============================================================


def _safe_auc(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    try:
        if len(np.unique(y_true)) < 2:
            return np.nan
        if SKLEARN_AVAILABLE:
            return float(roc_auc_score(y_true, y_prob))
        # Mann-Whitney AUC fallback.
        pos = y_prob[y_true == 1]
        neg = y_prob[y_true == 0]
        if len(pos) == 0 or len(neg) == 0:
            return np.nan
        score = 0.0
        for p in pos:
            score += float((p > neg).sum()) + 0.5 * float((p == neg).sum())
        return score / max(len(pos) * len(neg), 1)
    except Exception:
        return np.nan


def classification_metrics_v1(y_true: np.ndarray, y_prob: np.ndarray, threshold: float = 0.55) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_prob = np.asarray(y_prob, dtype=float)
    y_pred = (y_prob >= float(threshold)).astype(float)

    out: dict[str, float] = {
        "auc": _safe_auc(y_true, y_prob),
        "mean_prob": float(np.nanmean(y_prob)) if len(y_prob) else np.nan,
        "positive_rate": float(np.nanmean(y_true)) if len(y_true) else np.nan,
        "selection_rate": float(np.nanmean(y_pred)) if len(y_pred) else np.nan,
    }

    if SKLEARN_AVAILABLE:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                out.update(
                    {
                        "accuracy": float(accuracy_score(y_true, y_pred)),
                        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
                        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
                        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
                        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
                        "brier": float(brier_score_loss(y_true, np.clip(y_prob, EPS, 1.0 - EPS))),
                    }
                )
        except Exception:
            pass
    else:
        tp = float(((y_pred == 1) & (y_true == 1)).sum())
        fp = float(((y_pred == 1) & (y_true == 0)).sum())
        fn = float(((y_pred == 0) & (y_true == 1)).sum())
        tn = float(((y_pred == 0) & (y_true == 0)).sum())
        out["accuracy"] = (tp + tn) / max(tp + fp + fn + tn, 1.0)
        out["precision"] = tp / max(tp + fp, 1.0)
        out["recall"] = tp / max(tp + fn, 1.0)
        out["f1"] = 2 * out["precision"] * out["recall"] / max(out["precision"] + out["recall"], EPS)
        out["balanced_accuracy"] = 0.5 * (tp / max(tp + fn, 1.0) + tn / max(tn + fp, 1.0))
        out["brier"] = float(np.mean((y_prob - y_true) ** 2)) if len(y_true) else np.nan

    return out


def build_calibration_table_v1(predictions: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    if predictions is None or predictions.empty or "probability" not in predictions.columns:
        return pd.DataFrame()

    df = predictions.dropna(subset=["probability", "y_true"]).copy()
    if df.empty:
        return pd.DataFrame()

    df["bin"] = pd.cut(df["probability"], bins=np.linspace(0, 1, n_bins + 1), include_lowest=True)
    rows = []
    for b, g in df.groupby("bin", observed=False):
        if g.empty:
            continue
        rows.append(
            {
                "Probability bin": str(b),
                "Count": int(len(g)),
                "Avg probability": float(g["probability"].mean()),
                "Observed TP %": float(g["y_true"].mean()),
                "Avg barrier return": float(g["tb_return"].mean()) if "tb_return" in g.columns else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_acceptance_gate_v1(
    metrics_df: pd.DataFrame,
    split_audit: pd.DataFrame,
    predictions: pd.DataFrame,
    min_auc: float = 0.55,
    max_train_test_gap: float = 0.12,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def add(gate: str, status: str, detail: str, hard_block: bool = False) -> None:
        rows.append({"Gate": gate, "Status": status, "Detail": detail, "Hard block": "Yes" if hard_block else "No"})

    if metrics_df is None or metrics_df.empty:
        add("Metrics", "BLOCK", "Aucune métrique OOS disponible.", True)
        return pd.DataFrame(rows)

    ok_folds = int((split_audit.get("Status", pd.Series(dtype=str)) == "OK").sum()) if isinstance(split_audit, pd.DataFrame) else 0
    add("Purged WFO folds", "PASS" if ok_folds >= 2 else ("WARN" if ok_folds == 1 else "BLOCK"), f"{ok_folds} fold(s) OK. 2+ recommandé pour robustesse, 1 accepté pour diagnostic.", ok_folds < 1)

    oos = metrics_df[metrics_df["Sample"] == "OOS"].copy() if "Sample" in metrics_df.columns else pd.DataFrame()
    train = metrics_df[metrics_df["Sample"] == "Train"].copy() if "Sample" in metrics_df.columns else pd.DataFrame()

    if oos.empty:
        add("OOS metrics", "BLOCK", "Aucune métrique OOS.", True)
        return pd.DataFrame(rows)

    best_oos_auc = pd.to_numeric(oos.get("AUC"), errors="coerce").max()
    add("OOS AUC", "PASS" if best_oos_auc >= min_auc else "WARN", f"Meilleur AUC OOS : {_fmt_num(best_oos_auc, 3)} ; seuil : {_fmt_num(min_auc, 3)}.", False)

    dummy_auc = np.nan
    try:
        dummy_auc = float(oos.loc[oos["Model"].astype(str).str.contains("Dummy", case=False, na=False), "AUC"].max())
    except Exception:
        dummy_auc = np.nan

    non_dummy = oos.loc[~oos["Model"].astype(str).str.contains("Dummy", case=False, na=False)].copy()
    best_model_auc = pd.to_numeric(non_dummy.get("AUC"), errors="coerce").max() if not non_dummy.empty else np.nan
    lift_vs_dummy = best_model_auc - dummy_auc if np.isfinite(best_model_auc) and np.isfinite(dummy_auc) else np.nan
    add("Lift vs Dummy", "PASS" if np.isfinite(lift_vs_dummy) and lift_vs_dummy > 0.02 else "WARN", f"AUC lift : {_fmt_num(lift_vs_dummy, 3)}.", False)

    max_gap = np.nan
    if not train.empty:
        gaps = []
        for model in sorted(set(metrics_df["Model"].astype(str))):
            train_auc = pd.to_numeric(train.loc[train["Model"].astype(str) == model, "AUC"], errors="coerce").mean()
            oos_auc = pd.to_numeric(oos.loc[oos["Model"].astype(str) == model, "AUC"], errors="coerce").mean()
            if np.isfinite(train_auc) and np.isfinite(oos_auc):
                gaps.append(float(train_auc - oos_auc))
        max_gap = max(gaps) if gaps else np.nan
    add("Train/OOS gap", "PASS" if (not np.isfinite(max_gap) or max_gap <= max_train_test_gap) else "WARN", f"Gap max AUC train-OOS : {_fmt_num(max_gap, 3)}.", False)

    n_pred = int(len(predictions)) if isinstance(predictions, pd.DataFrame) else 0
    add("OOS predictions", "PASS" if n_pred >= 60 else "WARN", f"{n_pred} prédictions OOS.", False)

    if isinstance(predictions, pd.DataFrame) and not predictions.empty:
        coverage = float((pd.to_numeric(predictions.get("signal", 0), errors="coerce").abs() > 0).mean())
        add("Signal coverage", "PASS" if 0.02 <= coverage <= 0.70 else "WARN", f"Couverture signal : {_fmt_pct(coverage)}.", False)

    add("Decision Engine integration", "BLOCKED BY DESIGN", "Le Deep Learning ne pilote pas le Decision Engine. Export CSV seulement.", False)
    add("Backtest validation", "MANDATORY", "Le CSV doit passer par Backtest Lab / Custom Signal Import avec coûts, slippage et t+1.", False)

    return pd.DataFrame(rows)


# ============================================================
# MODEL TRAINING
# ============================================================


@dataclass
class DLExperimentConfig:
    horizon: int = 20
    pt_mult: float = 1.5
    sl_mult: float = 1.5
    lookback: int = 30
    n_splits: int = 4
    embargo_days: int = 5
    min_train_size: int = 120
    min_test_size: int = 30
    timeout_policy: str = "failure"
    threshold_long: float = 0.58
    threshold_short: float = 0.35
    allow_short_export: bool = False
    max_epochs: int = 12
    batch_size: int = 32
    random_state: int = 42
    selected_models: tuple[str, ...] = ("Dummy", "Logistic", "Sequence MLP")



def _predict_dummy_or_logistic(
    model_name: str,
    X_train_2d: np.ndarray,
    y_train: np.ndarray,
    X_test_2d: np.ndarray,
    random_state: int,
) -> tuple[np.ndarray, np.ndarray, str]:
    if not SKLEARN_AVAILABLE:
        base_prob = float(np.mean(y_train)) if len(y_train) else 0.5
        return np.repeat(base_prob, len(X_train_2d)), np.repeat(base_prob, len(X_test_2d)), "manual prior fallback"

    if model_name == "Dummy":
        clf = DummyClassifier(strategy="prior", random_state=random_state)
    elif model_name == "Logistic":
        clf = LogisticRegression(max_iter=1000, C=0.5, class_weight="balanced", random_state=random_state)
    elif model_name == "HistGradientBoosting":
        clf = HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_iter=180,
            max_leaf_nodes=15,
            l2_regularization=1.0,
            early_stopping=True,
            random_state=random_state,
        )
    elif model_name == "Extra Trees":
        clf = ExtraTreesClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=5,
            class_weight="balanced_subsample",
            n_jobs=-1,
            random_state=random_state,
        )
    elif model_name == "Sklearn MLP":
        clf = MLPClassifier(
            hidden_layer_sizes=(64, 32),
            activation="relu",
            solver="adam",
            alpha=1e-3,
            learning_rate_init=1e-3,
            max_iter=300,
            early_stopping=True,
            n_iter_no_change=12,
            random_state=random_state,
        )
    else:
        raise ValueError(f"Unknown sklearn model: {model_name}")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clf.fit(X_train_2d, y_train)

    if hasattr(clf, "predict_proba"):
        train_proba = clf.predict_proba(X_train_2d)
        test_proba = clf.predict_proba(X_test_2d)
        classes = list(getattr(clf, "classes_", []))
        if 1 in classes:
            pos_idx = classes.index(1)
            train_prob = train_proba[:, pos_idx]
            test_prob = test_proba[:, pos_idx]
        else:
            # Cas one-class : sklearn ne renvoie qu'une colonne.
            # Si la classe positive est absente, P(success)=0 ; si elle est seule, P(success)=1.
            only_class = classes[0] if classes else 0
            base_prob = 1.0 if float(only_class) == 1.0 else 0.0
            train_prob = np.repeat(base_prob, len(X_train_2d))
            test_prob = np.repeat(base_prob, len(X_test_2d))
    else:
        train_prob = clf.predict(X_train_2d)
        test_prob = clf.predict(X_test_2d)

    detail = getattr(clf, "__class__", type(clf)).__name__
    return np.asarray(train_prob, dtype=float), np.asarray(test_prob, dtype=float), detail


def _build_tf_model(tf: Any, architecture: str, input_shape: tuple[int, int], random_state: int) -> Any:
    try:
        tf.keras.utils.set_random_seed(int(random_state))
    except Exception:
        pass

    layers = tf.keras.layers
    models = tf.keras.models
    regularizers = tf.keras.regularizers

    inputs = layers.Input(shape=input_shape)

    if architecture == "TF MLP":
        x = layers.Flatten()(inputs)
        x = layers.Dense(96, activation="relu", kernel_regularizer=regularizers.l2(1e-4))(x)
        x = layers.BatchNormalization()(x)
        x = layers.Dropout(0.25)(x)
        x = layers.Dense(48, activation="relu", kernel_regularizer=regularizers.l2(1e-4))(x)
        x = layers.Dropout(0.20)(x)

    elif architecture == "TF LSTM":
        x = layers.LSTM(48, return_sequences=False, dropout=0.20, recurrent_dropout=0.0)(inputs)
        x = layers.Dense(32, activation="relu", kernel_regularizer=regularizers.l2(1e-4))(x)
        x = layers.Dropout(0.20)(x)

    elif architecture == "TF GRU":
        x = layers.GRU(48, return_sequences=False, dropout=0.20, recurrent_dropout=0.0)(inputs)
        x = layers.Dense(32, activation="relu", kernel_regularizer=regularizers.l2(1e-4))(x)
        x = layers.Dropout(0.20)(x)

    elif architecture == "TF Conv1D":
        x = layers.Conv1D(filters=48, kernel_size=3, padding="causal", activation="relu")(inputs)
        x = layers.BatchNormalization()(x)
        x = layers.Dropout(0.20)(x)
        x = layers.Conv1D(filters=32, kernel_size=3, padding="causal", activation="relu")(x)
        x = layers.GlobalAveragePooling1D()(x)
        x = layers.Dense(32, activation="relu", kernel_regularizer=regularizers.l2(1e-4))(x)
        x = layers.Dropout(0.20)(x)

    else:
        raise ValueError(f"Architecture TensorFlow inconnue : {architecture}")

    outputs = layers.Dense(1, activation="sigmoid")(x)
    model = models.Model(inputs=inputs, outputs=outputs)
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3),
        loss="binary_crossentropy",
        metrics=[tf.keras.metrics.AUC(name="auc")],
    )
    return model


def _predict_tensorflow_model(
    model_name: str,
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_test: np.ndarray,
    cfg: DLExperimentConfig,
) -> tuple[np.ndarray, np.ndarray, str]:
    ok, tf, version = _try_import_tensorflow()
    if not ok:
        raise RuntimeError(f"TensorFlow indisponible : {version}")

    model = _build_tf_model(tf, model_name, input_shape=(X_train.shape[1], X_train.shape[2]), random_state=cfg.random_state)

    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=4,
            restore_best_weights=True,
            min_delta=1e-4,
        )
    ]

    val_split = 0.15 if len(X_train) >= 200 else 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model.fit(
            X_train,
            y_train,
            epochs=int(cfg.max_epochs),
            batch_size=int(cfg.batch_size),
            validation_split=val_split,
            verbose=0,
            callbacks=callbacks if val_split > 0 else None,
            shuffle=False,
        )

    train_prob = model.predict(X_train, verbose=0).reshape(-1)
    test_prob = model.predict(X_test, verbose=0).reshape(-1)
    return np.asarray(train_prob, dtype=float), np.asarray(test_prob, dtype=float), f"TensorFlow {version}"


def run_deep_learning_experiment_v1(
    ticker: str,
    price_data: pd.DataFrame,
    analysis: dict | None,
    cfg: DLExperimentConfig,
) -> dict[str, Any]:
    feature_df, context_df = build_deep_feature_frame_v1(price_data, analysis)
    if feature_df.empty:
        return {
            "ok": False,
            "reason": "Feature frame vide ou historique insuffisant.",
            "feature_df": feature_df,
            "context_df": context_df,
        }

    labeled = make_deep_triple_barrier_labels_v1(
        feature_df,
        horizon=cfg.horizon,
        pt_mult=cfg.pt_mult,
        sl_mult=cfg.sl_mult,
        conservative_intraday=True,
    )
    supervised = build_supervised_dataset_v1(labeled, timeout_policy=cfg.timeout_policy)
    feature_cols = select_deep_feature_columns_v1(supervised)

    if supervised.empty or len(feature_cols) < 8:
        return {
            "ok": False,
            "reason": "Dataset supervisé ou feature set insuffisant.",
            "feature_df": feature_df,
            "labeled_df": labeled,
            "supervised_df": supervised,
            "context_df": context_df,
            "feature_cols": feature_cols,
        }

    X_seq, y_seq, meta_seq = make_sequence_arrays_v1(supervised, feature_cols, lookback=cfg.lookback)
    if X_seq.size == 0 or meta_seq.empty:
        return {
            "ok": False,
            "reason": "Séquences DL indisponibles après lookback/missing values.",
            "feature_df": feature_df,
            "labeled_df": labeled,
            "supervised_df": supervised,
            "context_df": context_df,
            "feature_cols": feature_cols,
            "split_audit": pd.DataFrame(),
        }

    splits, split_audit = build_sequence_purged_walk_forward_splits_v12(
        meta_seq=meta_seq,
        y_seq=y_seq,
        n_splits=cfg.n_splits,
        embargo_days=cfg.embargo_days,
        min_train_size=cfg.min_train_size,
        min_test_size=cfg.min_test_size,
        lookback=cfg.lookback,
    )

    metric_rows: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    model_errors: list[dict[str, Any]] = []

    selected_models = list(cfg.selected_models or [])
    if "Dummy" not in selected_models:
        selected_models = ["Dummy"] + selected_models

    for split in splits:
        fold = int(split["fold"])
        train_seq_idx = list(np.asarray(split.get("train_seq_idx", []), dtype=int))
        test_seq_idx = list(np.asarray(split.get("test_seq_idx", []), dtype=int))

        if len(train_seq_idx) < 30 or len(test_seq_idx) < 8:
            model_errors.append({
                "Fold": fold,
                "Model": "Split",
                "Error": f"Séquences insuffisantes après split séquence: train={len(train_seq_idx)}, test={len(test_seq_idx)}."
            })
            continue

        X_train_raw = X_seq[train_seq_idx]
        X_test_raw = X_seq[test_seq_idx]
        y_train = y_seq[train_seq_idx].astype(int)
        y_test = y_seq[test_seq_idx].astype(int)

        train_one_class = len(np.unique(y_train)) < 2
        test_one_class = len(np.unique(y_test)) < 2

        X_train, X_test = _scale_sequences_train_test(X_train_raw, X_test_raw)
        X_train_2d = X_train[:, -1, :]
        X_test_2d = X_test[:, -1, :]

        for model_name in selected_models:
            try:
                if train_one_class and model_name != "Dummy":
                    model_errors.append({
                        "Fold": fold,
                        "Model": model_name,
                        "Error": "Train one-class : modèle discriminant ignoré, Dummy prior conservé."
                    })
                    continue

                if model_name in SEQUENCE_MODEL_NAMES:
                    train_prob, test_prob, backend_detail = predict_sequence_model(
                        model_name,
                        X_train,
                        y_train,
                        X_test,
                        random_state=cfg.random_state + fold,
                        purge_bars=cfg.horizon,
                    )
                elif model_name in TORCH_MODEL_NAMES:
                    train_prob, test_prob, backend_detail = predict_torch_sequence_model(
                        model_name,
                        X_train,
                        y_train,
                        X_test,
                        random_state=cfg.random_state + fold,
                        purge_bars=cfg.horizon,
                        config=TorchSequenceConfig(
                            epochs=cfg.max_epochs,
                            batch_size=cfg.batch_size,
                        ),
                    )
                elif model_name in {"Dummy", "Logistic", "HistGradientBoosting", "Extra Trees", "Sklearn MLP"}:
                    train_prob, test_prob, backend_detail = _predict_dummy_or_logistic(
                        model_name,
                        X_train_2d,
                        y_train,
                        X_test_2d,
                        random_state=cfg.random_state + fold,
                    )
                elif model_name in {"TF MLP", "TF LSTM", "TF GRU", "TF Conv1D"}:
                    train_prob, test_prob, backend_detail = _predict_tensorflow_model(model_name, X_train, y_train, X_test, cfg)
                else:
                    raise ValueError(f"Modèle inconnu : {model_name}")

                train_metrics = classification_metrics_v1(y_train, train_prob, threshold=cfg.threshold_long)
                test_metrics = classification_metrics_v1(y_test, test_prob, threshold=cfg.threshold_long)

                for sample_name, met, size in [("Train", train_metrics, len(y_train)), ("OOS", test_metrics, len(y_test))]:
                    metric_rows.append(
                        {
                            "Model": model_name,
                            "Fold": fold,
                            "Sample": sample_name,
                            "Backend": backend_detail,
                            "Size": int(size),
                            "AUC": met.get("auc", np.nan),
                            "Brier": met.get("brier", np.nan),
                            "Balanced accuracy": met.get("balanced_accuracy", np.nan),
                            "Precision": met.get("precision", np.nan),
                            "Recall": met.get("recall", np.nan),
                            "F1": met.get("f1", np.nan),
                            "Positive rate": met.get("positive_rate", np.nan),
                            "Selection rate": met.get("selection_rate", np.nan),
                            "Mean probability": met.get("mean_prob", np.nan),
                        }
                    )

                test_meta = meta_seq.iloc[test_seq_idx].copy().reset_index(drop=True)
                for j, row in test_meta.iterrows():
                    prob = float(np.clip(test_prob[j], 0.0, 1.0))
                    signal = 1.0 if prob >= cfg.threshold_long else 0.0
                    if cfg.allow_short_export and prob <= cfg.threshold_short:
                        signal = -1.0
                    prediction_rows.append(
                        {
                            "ticker": str(ticker).upper().strip(),
                            "date": pd.to_datetime(row.get("date"), errors="coerce"),
                            "available_at": pd.to_datetime(row.get("available_at"), errors="coerce"),
                            "model": model_name,
                            "fold": fold,
                            "y_true": float(y_test[j]),
                            "probability": prob,
                            "confidence": float(abs(prob - 0.5) * 2.0),
                            "signal": float(signal),
                            "exposure": float(signal),
                            "tb_label": row.get("tb_label"),
                            "tb_event": row.get("tb_event"),
                            "tb_return": row.get("tb_return"),
                            "tb_mfe": row.get("tb_mfe"),
                            "tb_mae": row.get("tb_mae"),
                            "tb_holding_days": row.get("tb_holding_days"),
                            "model_version": MODULE_VERSION,
                            "label_horizon": int(cfg.horizon),
                            "pt_mult": float(cfg.pt_mult),
                            "sl_mult": float(cfg.sl_mult),
                            "lookback": int(cfg.lookback),
                            "threshold_long": float(cfg.threshold_long),
                            "threshold_short": float(cfg.threshold_short),
                            "source": "ML Deep Learning Lab — OOS purged WFO export",
                        }
                    )
            except Exception as exc:
                model_errors.append({"Fold": fold, "Model": model_name, "Error": str(exc)})
                continue

    metrics_df = pd.DataFrame(metric_rows)
    predictions = pd.DataFrame(prediction_rows)
    errors_df = pd.DataFrame(model_errors)

    if not predictions.empty:
        predictions = predictions.sort_values(["date", "model", "fold"]).drop_duplicates(
            subset=["date", "model"], keep="last"
        )

    uncertainty = build_sequence_uncertainty(predictions)

    selected_export_model = _select_export_model_v1(metrics_df)
    export_df = build_signal_export_v1(predictions, selected_export_model, cfg)
    calibration = build_calibration_table_v1(predictions[predictions["model"] == selected_export_model]) if selected_export_model else pd.DataFrame()
    gates = build_acceptance_gate_v1(metrics_df, split_audit, export_df)
    model_card = build_model_card_v1(ticker, feature_cols, cfg, metrics_df, split_audit, gates, selected_export_model)

    return {
        "ok": True,
        "module_version": MODULE_VERSION,
        "module_import_file": MODULE_IMPORT_FILE,
        "reason": "OK",
        "feature_df": feature_df,
        "labeled_df": labeled,
        "supervised_df": supervised,
        "context_df": context_df,
        "feature_cols": feature_cols,
        "splits": splits,
        "split_audit": split_audit,
        "metrics": metrics_df,
        "predictions": predictions,
        "uncertainty": uncertainty,
        "errors": errors_df,
        "selected_export_model": selected_export_model,
        "export_signal": export_df,
        "calibration": calibration,
        "gates": gates,
        "model_card": model_card,
    }


def _select_export_model_v1(metrics_df: pd.DataFrame) -> str:
    if metrics_df is None or metrics_df.empty:
        return ""
    oos = metrics_df[metrics_df["Sample"] == "OOS"].copy()
    if oos.empty:
        return ""
    grouped = (
        oos.groupby("Model", as_index=False)
        .agg(
            AUC=("AUC", "mean"),
            Brier=("Brier", "mean"),
            Folds=("Fold", "nunique"),
            Size=("Size", "sum"),
        )
        .sort_values(["AUC", "Brier", "Folds"], ascending=[False, True, False])
    )
    non_dummy = grouped.loc[~grouped["Model"].astype(str).str.contains("Dummy", case=False, na=False)].copy()
    if not non_dummy.empty:
        return str(non_dummy.iloc[0]["Model"])
    return str(grouped.iloc[0]["Model"])


def build_signal_export_v1(predictions: pd.DataFrame, selected_model: str, cfg: DLExperimentConfig) -> pd.DataFrame:
    if predictions is None or predictions.empty or not selected_model:
        return pd.DataFrame(columns=["date", "signal", "exposure", "probability", "confidence", "available_at", "model_version"])

    df = predictions[predictions["model"].astype(str) == str(selected_model)].copy()
    if df.empty:
        return pd.DataFrame(columns=["date", "signal", "exposure", "probability", "confidence", "available_at", "model_version"])

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["available_at"] = pd.to_datetime(df["available_at"], errors="coerce").fillna(df["date"])
    df = df.dropna(subset=["date"]).sort_values("date")

    # Recalcule explicitement le signal exporté, pour éviter d'exporter un seuil ancien.
    prob = pd.to_numeric(df["probability"], errors="coerce")
    df["signal"] = np.where(prob >= float(cfg.threshold_long), 1.0, 0.0)
    if cfg.allow_short_export:
        df.loc[prob <= float(cfg.threshold_short), "signal"] = -1.0
    df["exposure"] = df["signal"].clip(-1.0, 1.0)
    df["confidence"] = (prob - 0.5).abs().mul(2.0).clip(0.0, 1.0)

    keep = [
        "date",
        "signal",
        "exposure",
        "probability",
        "confidence",
        "available_at",
        "model_version",
        "model",
        "fold",
        "source",
        "label_horizon",
        "pt_mult",
        "sl_mult",
        "lookback",
        "threshold_long",
        "threshold_short",
    ]
    keep = [c for c in keep if c in df.columns]
    out = df[keep].copy()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    out["available_at"] = pd.to_datetime(out["available_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    return out.reset_index(drop=True)


def build_model_card_v1(
    ticker: str,
    feature_cols: list[str],
    cfg: DLExperimentConfig,
    metrics_df: pd.DataFrame,
    split_audit: pd.DataFrame,
    gates: pd.DataFrame,
    selected_model: str,
) -> pd.DataFrame:
    rows = [
        ["Module version", MODULE_VERSION, "Research-only, lazy loaded."],
        ["Loaded file", MODULE_IMPORT_FILE, "Chemin réel du module importé par Python."],
        ["Ticker", str(ticker).upper().strip(), "Actif analysé."],
        ["Selected export model", selected_model or "N/A", "Meilleur modèle non-dummy par AUC OOS moyen."],
        ["Label", f"Triple barrier h={cfg.horizon}, TP={cfg.pt_mult} ATR, SL={cfg.sl_mult} ATR", "Conservateur en same-day TP/SL."],
        ["Target", "TP first vs non-TP", "Timeout traité selon policy."],
        ["Timeout policy", cfg.timeout_policy, "failure ou drop."],
        ["Lookback", str(cfg.lookback), "Longueur séquence DL."],
        ["Features", str(len(feature_cols)), "Features causales prix/volume/régime."],
        ["Purged WFO", f"{cfg.n_splits} folds demandés · embargo {cfg.embargo_days} jours", "Split séquence adaptatif ; train toujours avant test."],
        ["Decision Engine", "Blocked", "Aucune intégration directe."],
        ["Backtest path", "CSV Custom Signal Import", "Le Backtest Lab applique t+1, coûts, slippage, safety gate."],
    ]

    if isinstance(metrics_df, pd.DataFrame) and not metrics_df.empty:
        oos = metrics_df[metrics_df["Sample"] == "OOS"].copy()
        if not oos.empty:
            rows.append(["Best OOS AUC", _fmt_num(pd.to_numeric(oos["AUC"], errors="coerce").max(), 3), "Lecture indicative, non suffisante sans backtest."])
            rows.append(["Avg OOS Brier", _fmt_num(pd.to_numeric(oos["Brier"], errors="coerce").mean(), 3), "Calibration moyenne."])

    if isinstance(split_audit, pd.DataFrame) and not split_audit.empty:
        rows.append(["Valid folds", str(int((split_audit["Status"] == "OK").sum())), "Folds purgés utilisables."])

    if isinstance(gates, pd.DataFrame) and not gates.empty:
        blockers = int((gates["Hard block"].astype(str) == "Yes").sum()) if "Hard block" in gates.columns else 0
        rows.append(["Hard blockers", str(blockers), "0 requis pour considérer l'export propre." ])

    return pd.DataFrame(rows, columns=["Field", "Value", "Read"])


# ============================================================
# UI RENDERING
# ============================================================


def render_deep_learning_lab_v1(ticker: str, price_data: pd.DataFrame, analysis: dict | None = None) -> None:
    from importlib.util import find_spec
    from .institutional_ui import render_deep_learning_radar

    render_deep_learning_radar(find_spec("tensorflow") is not None)
    st.subheader(f"Deep Learning Validation Lab — {ticker}")
    st.caption(
        "Module optionnel, chargé à la demande. Il entraîne des modèles de recherche sur séquences causales, "
        "produit des prédictions OOS purgées et exporte un CSV compatible Backtest Lab. "
        "Il ne modifie ni Decision Engine, ni Risk Monitor, ni Backtest Lab."
    )

    feature_probe, context_probe = build_deep_feature_frame_v1(price_data, analysis)

    if feature_probe.empty:
        st.error("Historique insuffisant ou données prix invalides pour le Deep Learning Lab.")
        return

    b1, b2, b3 = st.columns(3)
    b1.metric("Rows prix", f"{len(feature_probe):,}")
    b2.metric("Début", pd.to_datetime(feature_probe["date"]).min().strftime("%Y-%m-%d"))
    b3.metric("Fin", pd.to_datetime(feature_probe["date"]).max().strftime("%Y-%m-%d"))
    b4, b5, b6 = st.columns(3)
    b4.metric("Features brutes", f"{len(select_deep_feature_columns_v1(feature_probe)):,}")
    b5.metric("Backend sklearn", "OK" if SKLEARN_AVAILABLE else "Manquant")
    b6.metric("Module", MODULE_VERSION.replace("ML-DL-LAB-", ""))
    runtime = neural_runtime_status()
    runtime_label = (
        f"PyTorch {'OK' if runtime['pytorch'] else 'absent'} · "
        f"TensorFlow {'OK' if runtime['tensorflow'] else 'absent'}"
    )
    st.caption(
        f"Deep Learning module chargé : {MODULE_IMPORT_FILE} · {MODULE_VERSION} · {runtime_label}"
    )

    with st.expander("Doctrine et garde-fous", expanded=True):
        doctrine = pd.DataFrame(
            [
                ["Rôle du Deep Learning", "Recherche / probabilités OOS", "Pas de signal live autonome."],
                ["Chargement", "Lazy import", "TensorFlow chargé seulement si modèle TF sélectionné et expérience lancée."],
                ["Validation", "Purged walk-forward", "Train passé seulement, purge + embargo."],
                ["Decision Engine", "Interdit", "Aucune probabilité DL ne pilote le Decision Engine."],
                ["Backtest", "Obligatoire", "Export CSV à valider dans Custom Signal Import."],
                ["Look-ahead", "Contrôlé", "Features contextuelles des autres modules non utilisées en training historique."],
            ],
            columns=["Bloc", "Règle", "Lecture"],
        )
        st.dataframe(doctrine, width="stretch", hide_index=True)

    with st.expander("Paramètres expérience", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        horizon = c1.selectbox("Horizon label", [5, 10, 20, 40, 60], index=2, key=f"dl_horizon_{ticker}")
        pt_mult = c2.slider("TP ATR", 0.5, 5.0, 1.5, 0.25, key=f"dl_pt_{ticker}")
        sl_mult = c3.slider("SL ATR", 0.5, 5.0, 1.5, 0.25, key=f"dl_sl_{ticker}")
        timeout_policy = c4.selectbox("Timeout policy", ["failure", "drop"], index=0, key=f"dl_timeout_{ticker}")

        c5, c6, c7, c8 = st.columns(4)
        lookback = c5.slider("Lookback séquence", 10, 90, 30, 5, key=f"dl_lookback_{ticker}")
        n_splits = c6.slider("Purged WFO folds", 2, 8, 4, 1, key=f"dl_folds_{ticker}")
        embargo_days = c7.slider("Embargo jours", 0, 30, 5, 1, key=f"dl_embargo_{ticker}")
        min_test_size = c8.slider("Min test/fold", 10, 120, 25, 5, key=f"dl_min_test_{ticker}")

        c9, c10, c11, c12 = st.columns(4)
        threshold_long = c9.slider("Seuil export long", 0.50, 0.80, 0.58, 0.01, key=f"dl_th_long_{ticker}")
        allow_short_export = c10.toggle("Autoriser export short", value=False, key=f"dl_allow_short_{ticker}")
        threshold_short = c11.slider("Seuil export short", 0.20, 0.49, 0.35, 0.01, key=f"dl_th_short_{ticker}")
        random_state = c12.number_input("Random seed", min_value=1, max_value=9999, value=42, step=1, key=f"dl_seed_{ticker}")

        available_models = ["Dummy", "Logistic", "HistGradientBoosting", "Extra Trees", *SEQUENCE_MODEL_NAMES, *TORCH_MODEL_NAMES, "Sklearn MLP", "TF MLP", "TF LSTM", "TF GRU", "TF Conv1D"]
        selected_models = st.multiselect(
            "Model zoo",
            available_models,
            default=["Dummy", "Logistic", "Sequence MLP"],
            key=f"dl_models_{ticker}",
        )

        c13, c14 = st.columns(2)
        max_epochs = c13.slider("Max epochs TensorFlow", 4, 50, 12, 1, key=f"dl_epochs_{ticker}")
        batch_size = c14.selectbox("Batch size", [16, 32, 64, 128], index=1, key=f"dl_batch_{ticker}")

    cfg = DLExperimentConfig(
        horizon=int(horizon),
        pt_mult=float(pt_mult),
        sl_mult=float(sl_mult),
        lookback=int(lookback),
        n_splits=int(n_splits),
        embargo_days=int(embargo_days),
        min_train_size=max(50, int(lookback) * 2),
        min_test_size=int(min_test_size),
        timeout_policy=str(timeout_policy),
        threshold_long=float(threshold_long),
        threshold_short=float(threshold_short),
        allow_short_export=bool(allow_short_export),
        max_epochs=int(max_epochs),
        batch_size=int(batch_size),
        random_state=int(random_state),
        selected_models=tuple(selected_models or ["Dummy", "Logistic", "Sklearn MLP"]),
    )

    run_key = f"dl_results_{ticker}_{MODULE_VERSION}_{_stable_hash(cfg)}"

    c_run, c_clear = st.columns([0.62, 0.38])
    run_button = c_run.button("Lancer / recalculer l'expérience Deep Learning", key=f"dl_run_button_{ticker}_{MODULE_VERSION}")
    clear_button = c_clear.button("Réinitialiser cache DL", key=f"dl_clear_cache_{ticker}_{MODULE_VERSION}")

    if clear_button:
        for key in list(st.session_state.keys()):
            if str(key).startswith(f"dl_results_{ticker}_") or str(key) == f"dl_last_key_{ticker}":
                del st.session_state[key]
        st.success("Cache Deep Learning réinitialisé. Relance l'expérience.")

    if run_button:
        with st.spinner("Expérience Deep Learning en cours : feature store, labels, purged WFO, modèles, export CSV..."):
            result = run_deep_learning_experiment_v1(ticker, price_data, analysis, cfg)
            if isinstance(result, dict):
                result["module_version"] = MODULE_VERSION
                result["module_import_file"] = MODULE_IMPORT_FILE
            st.session_state[run_key] = result
            st.session_state[f"dl_last_key_{ticker}"] = run_key

    last_key = st.session_state.get(f"dl_last_key_{ticker}", run_key)
    result = st.session_state.get(last_key)

    if isinstance(result, dict) and result.get("module_version") not in [None, MODULE_VERSION]:
        st.warning(
            f"Ancien résultat DL ignoré : {result.get('module_version')} ≠ {MODULE_VERSION}. "
            "Clique sur Réinitialiser cache DL puis relance l'expérience."
        )
        result = None

    if not isinstance(result, dict):
        st.info("L'expérience n'est pas lancée. Les paramètres sont prêts, mais aucun modèle n'est entraîné automatiquement.")
        _render_dataset_preview(feature_probe, context_probe)
        return

    if not result.get("ok"):
        st.error(f"Expérience indisponible : {result.get('reason', 'raison inconnue')}")
        _render_dataset_preview(result.get("feature_df", feature_probe), result.get("context_df", context_probe))
        return

    selected_model = str(result.get("selected_export_model") or "Aucun")
    oos_metrics = result.get("metrics")
    selected_oos = pd.DataFrame()
    if isinstance(oos_metrics, pd.DataFrame) and not oos_metrics.empty:
        selected_oos = oos_metrics[
            (oos_metrics["Sample"] == "OOS") & (oos_metrics["Model"] == selected_model)
        ]
    mean_auc = float(pd.to_numeric(selected_oos.get("AUC"), errors="coerce").mean()) if not selected_oos.empty else np.nan
    mean_balanced = (
        float(pd.to_numeric(selected_oos.get("Balanced accuracy"), errors="coerce").mean())
        if not selected_oos.empty else np.nan
    )
    oos_rows = int(pd.to_numeric(selected_oos.get("Size"), errors="coerce").sum()) if not selected_oos.empty else 0

    r1, r2 = st.columns(2)
    r1.metric("Champion de recherche", selected_model)
    r2.metric("Observations OOS", f"{oos_rows:,}")
    r3, r4 = st.columns(2)
    r3.metric("AUC OOS moyen", f"{mean_auc:.3f}" if np.isfinite(mean_auc) else "N/A")
    r4.metric("Balanced accuracy OOS", f"{mean_balanced:.3f}" if np.isfinite(mean_balanced) else "N/A")
    st.caption("Champion de recherche uniquement · export shadow mode · aucune autorisation de trading autonome.")

    tabs = st.tabs([
        "Dataset & Leakage",
        "Purged WFO",
        "Model Metrics",
        "OOS Predictions",
        "Uncertainty",
        "Signal Export",
        "Model Card",
    ])

    with tabs[0]:
        _render_dataset_preview(result.get("feature_df"), result.get("context_df"), result.get("feature_cols"))

    with tabs[1]:
        _render_split_audit(result.get("split_audit"))

    with tabs[2]:
        _render_metrics(result.get("metrics"), result.get("errors"))

    with tabs[3]:
        _render_predictions(result.get("predictions"), result.get("selected_export_model"), result.get("calibration"))

    with tabs[4]:
        render_sequence_uncertainty(result.get("uncertainty", {}))

    with tabs[5]:
        _render_signal_export(ticker, result.get("export_signal"), result.get("selected_export_model"), cfg)

    with tabs[6]:
        _render_model_card(result.get("model_card"), result.get("gates"))


# ============================================================
# UI PANELS
# ============================================================


def _render_dataset_preview(feature_df: pd.DataFrame, context_df: pd.DataFrame | None = None, feature_cols: list[str] | None = None) -> None:
    st.subheader("Dataset causal & feature store")

    if feature_df is None or feature_df.empty:
        st.warning("Feature frame indisponible.")
        return

    feature_cols = feature_cols or select_deep_feature_columns_v1(feature_df)
    audit_rows = [
        {"Contrôle": "Lignes prix", "Statut": "OK" if len(feature_df) >= 120 else "Fragile", "Détail": f"{len(feature_df):,} lignes."},
        {"Contrôle": "Features causales", "Statut": "OK" if len(feature_cols) >= 8 else "Fragile", "Détail": f"{len(feature_cols)} colonnes retenues."},
        {"Contrôle": "Colonnes interdites", "Statut": "OK", "Détail": "Prix bruts, labels, forward returns et target exclus du training."},
        {"Contrôle": "Context modules", "Statut": "Read-only", "Détail": "Scores Decision/Company/Momentum non utilisés en training historique."},
    ]
    st.dataframe(pd.DataFrame(audit_rows), width="stretch", hide_index=True)

    missing = feature_df[feature_cols].isna().mean().sort_values(ascending=False).head(25) if feature_cols else pd.Series(dtype=float)
    if not missing.empty:
        miss_df = pd.DataFrame({"Feature": missing.index, "Missing %": missing.values})
        miss_show = miss_df.copy()
        miss_show["Missing %"] = miss_show["Missing %"].map(_fmt_pct)
        st.dataframe(miss_show, width="stretch", hide_index=True, height=_table_height(miss_show, max_height=360))

        fig = go.Figure()
        fig.add_trace(go.Bar(x=miss_df["Feature"], y=miss_df["Missing %"], name="Missing"))
        fig.update_layout(height=360, title="Top missing features", yaxis_tickformat=".0%", margin=dict(l=20, r=20, t=60, b=80))
        st.plotly_chart(fig, width="stretch", config=_plotly_config())

    with st.expander("Context current-only des autres modules", expanded=False):
        if isinstance(context_df, pd.DataFrame) and not context_df.empty:
            show = context_df.copy()
            if "Valeur" in show.columns:
                show["Valeur"] = show["Valeur"].map(lambda x: _fmt_num(x, 4))
            st.dataframe(show, width="stretch", hide_index=True)
            st.caption("Ces valeurs peuvent servir à l'analyse courante, mais pas à l'entraînement historique par défaut.")
        else:
            st.info("Aucun contexte module exploitable détecté.")


def _render_split_audit(split_audit: pd.DataFrame) -> None:
    st.subheader("Purged Walk-Forward Validation")
    if split_audit is None or split_audit.empty:
        st.warning("Aucun split purgé exploitable.")
        return

    show = split_audit.copy()
    for col in ["Test start", "Test end"]:
        if col in show.columns:
            show[col] = pd.to_datetime(show[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["Train TP %", "Test TP %"]:
        if col in show.columns:
            show[col] = show[col].map(_fmt_pct)
    st.dataframe(show, width="stretch", hide_index=True)

    ok = int((split_audit["Status"] == "OK").sum()) if "Status" in split_audit.columns else 0
    if ok >= 2:
        st.success(f"{ok} folds purgés exploitables. Train passé uniquement, purge + embargo actifs.")
    else:
        st.warning(f"Seulement {ok} fold(s) OK. Lecture fragile.")


def _render_metrics(metrics: pd.DataFrame, errors: pd.DataFrame | None = None) -> None:
    st.subheader("Model zoo — métriques Train / OOS")
    if metrics is None or metrics.empty:
        st.warning("Aucune métrique modèle.")
        return

    display = metrics.copy()
    for col in ["AUC", "Brier", "Balanced accuracy", "Precision", "Recall", "F1", "Positive rate", "Selection rate", "Mean probability"]:
        if col in display.columns:
            display[col] = display[col].map(lambda x: _fmt_num(x, 3))
    st.dataframe(display, width="stretch", hide_index=True, height=_table_height(display, max_height=540))

    oos = metrics[metrics["Sample"] == "OOS"].copy()
    if not oos.empty:
        grouped = oos.groupby("Model", as_index=False).agg(AUC=("AUC", "mean"), Brier=("Brier", "mean"), Folds=("Fold", "nunique"))
        fig = go.Figure()
        fig.add_trace(go.Bar(x=grouped["Model"], y=grouped["AUC"], text=grouped["AUC"].map(lambda x: _fmt_num(x, 3)), textposition="auto", name="OOS AUC"))
        fig.update_layout(height=380, title="AUC OOS moyen par modèle", yaxis_title="AUC", margin=dict(l=20, r=20, t=60, b=50))
        st.plotly_chart(fig, width="stretch", config=_plotly_config())

    if isinstance(errors, pd.DataFrame) and not errors.empty:
        with st.expander("Erreurs modèle capturées", expanded=False):
            st.dataframe(errors, width="stretch", hide_index=True)


def _render_predictions(predictions: pd.DataFrame, selected_model: str, calibration: pd.DataFrame) -> None:
    st.subheader("Prédictions OOS purgées")
    if predictions is None or predictions.empty:
        st.warning("Aucune prédiction OOS.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Prédictions OOS", f"{len(predictions):,}")
    c2.metric("Modèle export", selected_model or "N/A")
    c3.metric("Prob. moyenne", _fmt_pct(predictions["probability"].mean()))
    c4.metric("Couverture signal", _fmt_pct((predictions["signal"].abs() > 0).mean()))

    show = predictions.tail(250).copy()
    for col in ["date", "available_at"]:
        if col in show.columns:
            show[col] = pd.to_datetime(show[col], errors="coerce").dt.strftime("%Y-%m-%d")
    for col in ["probability", "confidence", "tb_return", "tb_mfe", "tb_mae"]:
        if col in show.columns:
            show[col] = show[col].map(lambda x: _fmt_num(x, 4))
    st.dataframe(show, width="stretch", hide_index=True, height=_table_height(show, max_height=560))

    if selected_model:
        view = predictions[predictions["model"].astype(str) == str(selected_model)].copy()
    else:
        view = predictions.copy()

    if not view.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=view["date"], y=view["probability"], mode="lines", name="Probability"))
        fig.add_hline(y=0.5, line_dash="dot")
        fig.update_layout(height=380, title="Probabilité OOS — modèle export", yaxis_title="P(TP first)", yaxis_tickformat=".0%", margin=dict(l=20, r=20, t=60, b=40))
        st.plotly_chart(fig, width="stretch", config=_plotly_config())

    with st.expander("Calibration OOS", expanded=False):
        if isinstance(calibration, pd.DataFrame) and not calibration.empty:
            cal = calibration.copy()
            for col in ["Avg probability", "Observed TP %", "Avg barrier return"]:
                if col in cal.columns:
                    cal[col] = cal[col].map(_fmt_pct)
            st.dataframe(cal, width="stretch", hide_index=True)
        else:
            st.info("Calibration indisponible.")


def _render_signal_export(ticker: str, export_signal: pd.DataFrame, selected_model: str, cfg: DLExperimentConfig) -> None:
    st.subheader("Export CSV vers Backtest Lab / Custom Signal Import")
    st.caption(
        "Deux exports sont séparés : le CSV recherche complet sert à l'audit ML ; "
        "le CSV Backtest Safe est le seul recommandé pour Backtest Lab, car il retire les colonnes "
        "probability / label_horizon / target-like afin d'éviter les faux blocages du Signal Safety Gate. "
        "Backtest Lab appliquera ensuite son t+1, ses coûts/slippage et sa safety gate."
    )

    if export_signal is None or export_signal.empty:
        st.warning("Aucun signal exportable.")
        return

    research_export = export_signal.copy()

    # ------------------------------------------------------------
    # V1.4 — Backtest Safe Export
    # ------------------------------------------------------------
    # Objectif : éviter que le Backtest Lab bloque l'import à cause de
    # colonnes de recherche légitimes mais lexicalement suspectes
    # (probability, label_horizon, y_true, target, tb_label...).
    #
    # Le moteur Backtest n'a besoin que de :
    # - date : date de décision / signal ;
    # - exposure : exposition [-1, 1] ;
    # - available_at : date de disponibilité, optionnelle mais utile pour audit.
    #
    # Toutes les probabilités et métadonnées restent disponibles dans le CSV
    # recherche complet, mais ne sont pas poussées par défaut vers Backtest Lab.
    safe_export = pd.DataFrame()
    try:
        safe_export["date"] = pd.to_datetime(research_export.get("date"), errors="coerce")
        if "exposure" in research_export.columns:
            safe_export["exposure"] = pd.to_numeric(research_export["exposure"], errors="coerce")
        elif "signal" in research_export.columns:
            safe_export["exposure"] = pd.to_numeric(research_export["signal"], errors="coerce")
        else:
            safe_export["exposure"] = 0.0

        if "available_at" in research_export.columns:
            safe_export["available_at"] = pd.to_datetime(research_export["available_at"], errors="coerce")
        else:
            safe_export["available_at"] = safe_export["date"]

        safe_export["available_at"] = safe_export["available_at"].fillna(safe_export["date"])
        safe_export["exposure"] = safe_export["exposure"].fillna(0.0).clip(-1.0, 1.0)
        safe_export = safe_export.dropna(subset=["date"]).sort_values("date")
        safe_export = safe_export.drop_duplicates(subset=["date"], keep="last")
        safe_export["date"] = safe_export["date"].dt.strftime("%Y-%m-%d")
        safe_export["available_at"] = pd.to_datetime(safe_export["available_at"], errors="coerce").dt.strftime("%Y-%m-%d")
        safe_export = safe_export[["date", "exposure", "available_at"]].reset_index(drop=True)
    except Exception as exc:
        st.error(f"Construction du CSV Backtest Safe impossible : {exc}")
        safe_export = pd.DataFrame(columns=["date", "exposure", "available_at"])

    active_rows = int((pd.to_numeric(safe_export.get("exposure", pd.Series(dtype=float)), errors="coerce").abs() > 0).sum()) if not safe_export.empty else 0
    total_rows = int(len(safe_export)) if isinstance(safe_export, pd.DataFrame) else 0
    coverage = active_rows / max(total_rows, 1)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Lignes safe", f"{total_rows:,}")
    c2.metric("Barres actives", f"{active_rows:,}")
    c3.metric("Couverture safe", _fmt_pct(coverage))
    c4.metric("Modèle", selected_model or "N/A")

    with st.expander("CSV Backtest Safe — recommandé", expanded=True):
        st.caption(
            "Format minimal envoyé au Backtest Lab : date, exposure, available_at. "
            "Aucune colonne probability, label, target, y_true ou horizon n'est incluse."
        )
        if safe_export.empty:
            st.warning("CSV Backtest Safe vide.")
        else:
            st.dataframe(
                safe_export.tail(250),
                width="stretch",
                hide_index=True,
                height=_table_height(safe_export.tail(250), max_height=520),
            )

    with st.expander("CSV recherche complet — audit ML uniquement", expanded=False):
        show = research_export.copy()
        for col in ["probability", "confidence"]:
            if col in show.columns:
                show[col] = show[col].map(lambda x: _fmt_num(x, 4))
        st.caption(
            "Ce fichier complet conserve probability, confidence, fold, model_version et paramètres de label. "
            "Il est utile pour l'audit ML, mais peut déclencher un faux blocage du Safety Gate si on l'importe directement dans Backtest Lab."
        )
        st.dataframe(
            show.tail(250),
            width="stretch",
            hide_index=True,
            height=_table_height(show.tail(250), max_height=520),
        )

    model_name = str(selected_model or "model").replace(" ", "_")
    ticker_name = str(ticker).upper().strip()
    safe_file_name = f"dl_backtest_safe_{ticker_name}_{model_name}_h{cfg.horizon}.csv"
    research_file_name = f"dl_research_full_{ticker_name}_{model_name}_h{cfg.horizon}.csv"

    safe_csv_text = safe_export.to_csv(index=False)
    research_csv_text = research_export.to_csv(index=False)

    d1, d2, d3 = st.columns([0.30, 0.45, 0.25])

    d1.download_button(
        "Télécharger CSV Backtest Safe",
        data=safe_csv_text.encode("utf-8"),
        file_name=safe_file_name,
        mime="text/csv",
        key=f"dl_download_backtest_safe_{ticker}_{_stable_hash(safe_file_name)}",
        disabled=safe_export.empty,
    )

    if d2.button(
        "Pré-remplir Backtest Lab avec CSV Backtest Safe",
        key=f"dl_push_backtest_safe_{ticker}_{_stable_hash(safe_file_name)}",
        disabled=safe_export.empty,
    ):
        st.session_state["bt_custom_signal_paste_area"] = safe_csv_text
        st.session_state["bt_custom_signal_paste"] = safe_csv_text
        st.session_state["bt_custom_signal_source"] = "ML Deep Learning Lab V1.4 — Backtest Safe Export"
        st.success(
            "CSV Backtest Safe placé dans la session Backtest Lab. "
            "Va dans Backtest Lab > Custom Signal Import : le Safety Gate ne devrait plus bloquer probability/label_horizon."
        )

    d3.download_button(
        "Télécharger CSV recherche complet",
        data=research_csv_text.encode("utf-8"),
        file_name=research_file_name,
        mime="text/csv",
        key=f"dl_download_research_full_{ticker}_{_stable_hash(research_file_name)}",
    )

    if active_rows == 0:
        st.warning(
            "Le modèle n'a généré aucune exposition active au seuil choisi. "
            "Baisse le seuil ou considère que le modèle ne produit pas d'edge exploitable."
        )
    else:
        st.info(
            "Pour la validation finale, utilise le bouton Backtest Safe. "
            "Le CSV recherche complet doit rester un fichier d'audit, pas le fichier principal de backtest."
        )



def _render_model_card(model_card: pd.DataFrame, gates: pd.DataFrame) -> None:
    st.subheader("Model card & acceptance gates")
    if isinstance(model_card, pd.DataFrame) and not model_card.empty:
        st.dataframe(model_card, width="stretch", hide_index=True)

    if isinstance(gates, pd.DataFrame) and not gates.empty:
        st.markdown("**Acceptance gates**")
        st.dataframe(gates, width="stretch", hide_index=True)
        hard_blocks = int((gates["Hard block"].astype(str) == "Yes").sum()) if "Hard block" in gates.columns else 0
        if hard_blocks > 0:
            st.error(f"{hard_blocks} hard blocker(s). Export à utiliser uniquement pour diagnostic, pas comme stratégie validée.")
        else:
            st.warning("Aucun hard blocker technique, mais validation finale obligatoire dans Backtest Lab.")
