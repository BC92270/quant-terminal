from __future__ import annotations

from typing import Any
import numpy as np
import pandas as pd


def apply_alignment_lags(changes: pd.DataFrame, lag_map: dict[str, int] | None = None) -> pd.DataFrame:
    """Apply explicit session-alignment lags after return transformation.

    Positive lag shifts the series forward by that many rows so that information intervals line up with
    the reference market. No price forward-fill is introduced.
    """
    if changes is None or changes.empty or not lag_map:
        return changes.copy() if isinstance(changes, pd.DataFrame) else pd.DataFrame()
    out = changes.copy()
    for k, v in lag_map.items():
        key = str(k).upper().strip()
        if key in out.columns:
            try:
                lag = int(v)
            except Exception:
                continue
            if lag:
                out[key] = out[key].shift(lag)
    return out


def synchronization_audit(levels: pd.DataFrame, changes: pd.DataFrame, metadata: dict[str, Any] | None = None,
                          lag_map: dict[str, int] | None = None) -> pd.DataFrame:
    metadata = metadata or {}; lag_map = lag_map or {}
    rows = []
    for c in levels.columns if isinstance(levels, pd.DataFrame) else []:
        m = metadata.get(c, {}) if isinstance(metadata.get(c, {}), dict) else {}
        s = changes[c] if c in changes else pd.Series(dtype=float)
        rows.append({
            "Ticker": c,
            "Timezone": m.get("timezone", "Unknown"),
            "Session close": m.get("session_close", "Unknown"),
            "Calendar": m.get("calendar", "Unknown"),
            "Base currency": m.get("currency", "Unknown"),
            "Return space": m.get("space", "Return"),
            "Alignment lag": int(lag_map.get(c, 0) or 0),
            "Return obs": int(s.notna().sum()),
            "First return": s.dropna().index.min() if s.notna().any() else None,
            "Last return": s.dropna().index.max() if s.notna().any() else None,
        })
    return pd.DataFrame(rows)


def hayashi_yoshida_covariance(a: pd.Series, b: pd.Series) -> float | None:
    """Hayashi-Yoshida covariance for asynchronous *interval returns*.

    Series indices are interval end timestamps; the previous timestamp defines each interval start.
    This function is provided for intraday adapters and is not applied to daily closes automatically.
    """
    a = pd.to_numeric(a, errors="coerce").dropna().sort_index()
    b = pd.to_numeric(b, errors="coerce").dropna().sort_index()
    if len(a) < 2 or len(b) < 2:
        return None
    ai = a.index.to_numpy(); bi = b.index.to_numpy()
    av = a.to_numpy(dtype=float); bv = b.to_numpy(dtype=float)
    total = 0.0
    i = j = 1
    while i < len(a) and j < len(b):
        a0, a1 = ai[i-1], ai[i]
        b0, b1 = bi[j-1], bi[j]
        if a0 < b1 and b0 < a1:
            total += av[i] * bv[j]
        if a1 <= b1:
            i += 1
        else:
            j += 1
    return float(total)
