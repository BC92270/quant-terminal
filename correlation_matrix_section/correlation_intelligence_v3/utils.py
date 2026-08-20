from __future__ import annotations

import math
import re
from html import escape
from typing import Any, Iterable

import numpy as np
import pandas as pd


def safe_float(value: Any, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, (pd.Series, pd.DataFrame, np.ndarray, list, tuple, dict)):
            return default
        if pd.isna(value):
            return default
        value = float(value)
        if not np.isfinite(value):
            return default
        return value
    except Exception:
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    value = safe_float(value, low)
    return max(low, min(high, value))


def normalize_ticker(value: str) -> str:
    return str(value or "").upper().strip().replace(" ", "")


def unique_keep_order(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        t = normalize_ticker(value)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def parse_ticker_text(raw_text: str, primary: str) -> list[str]:
    tokens = re.split(r"[,;\n\t ]+", str(raw_text or ""))
    return unique_keep_order([primary] + [x for x in tokens if normalize_ticker(x)])


def html_safe(value: Any) -> str:
    return escape(str(value if value is not None else "N/A"))


def fmt_corr(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None else f"{value:.2f}"


def fmt_pct(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None else f"{value:.2%}"


def fmt_num(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None else f"{value:,.2f}"


def fmt_score(value) -> str:
    value = safe_float(value)
    return "N/A" if value is None else f"{value:.0f}/100"


def fmt_pvalue(value) -> str:
    value = safe_float(value)
    if value is None:
        return "N/A"
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"


def table_height(df: pd.DataFrame, row_px: int = 36, min_height: int = 150, max_height: int = 620) -> int:
    n = max(len(df), 1) if isinstance(df, pd.DataFrame) else 1
    return int(min(max_height, max(min_height, 46 + row_px * n)))


def nearest_psd(matrix: pd.DataFrame, epsilon: float = 1e-8) -> pd.DataFrame:
    """Eigenvalue clipping with correlation renormalisation."""
    if matrix is None or matrix.empty:
        return pd.DataFrame()
    a = matrix.to_numpy(dtype=float)
    a = np.nan_to_num((a + a.T) / 2.0, nan=0.0, posinf=0.0, neginf=0.0)
    vals, vecs = np.linalg.eigh(a)
    vals = np.maximum(vals, epsilon)
    psd = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(psd), epsilon, None))
    psd = psd / np.outer(d, d)
    np.fill_diagonal(psd, 1.0)
    return pd.DataFrame(psd, index=matrix.index, columns=matrix.columns)


def effective_rank(eigenvalues: np.ndarray) -> float | None:
    vals = np.maximum(np.asarray(eigenvalues, dtype=float), 0.0)
    total = float(vals.sum())
    if total <= 0:
        return None
    p = vals / total
    p = p[p > 0]
    return float(np.exp(-np.sum(p * np.log(p))))


def risk_label(score: float) -> str:
    score = safe_float(score, 50.0)
    if score >= 75:
        return "Très élevé"
    if score >= 60:
        return "Élevé"
    if score >= 40:
        return "Modéré"
    return "Faible"


def corr_label(value) -> str:
    v = safe_float(value)
    if v is None:
        return "Indisponible"
    a = abs(v)
    if a >= 0.80:
        return "Très élevée"
    if a >= 0.65:
        return "Élevée"
    if a >= 0.45:
        return "Modérée"
    if a >= 0.20:
        return "Faible"
    return "Très faible"


def fisher_corr_ci(rho: float, n: int, alpha: float = 0.05) -> tuple[float | None, float | None]:
    rho = safe_float(rho)
    if rho is None or n <= 3 or abs(rho) >= 1:
        return None, None
    z = np.arctanh(rho)
    se = 1.0 / math.sqrt(n - 3)
    zcrit = 1.959963984540054
    lo, hi = z - zcrit * se, z + zcrit * se
    return float(np.tanh(lo)), float(np.tanh(hi))


def max_consecutive_missing(series: pd.Series) -> int:
    if series is None or len(series) == 0:
        return 0
    mask = series.isna().astype(int).to_numpy()
    best = cur = 0
    for x in mask:
        if x:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return int(best)
