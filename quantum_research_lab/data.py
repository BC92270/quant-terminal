from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .engine import synthetic_returns


def _flatten_download(download: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if download is None or download.empty:
        return pd.DataFrame()

    data = download.copy()
    if isinstance(data.columns, pd.MultiIndex):
        level0 = [str(x).lower() for x in data.columns.get_level_values(0)]
        target = "adj close" if "adj close" in level0 else "close" if "close" in level0 else None
        if target is None:
            return pd.DataFrame()
        actual = data.columns.get_level_values(0)[level0.index(target)]
        close = data[actual].copy()
        if isinstance(close, pd.Series):
            close = close.to_frame(name=symbols[0] if symbols else "Asset")
        close.columns = [str(c).upper() for c in close.columns]
        return close

    cols = {str(c).lower(): c for c in data.columns}
    target = cols.get("adj close") or cols.get("close")
    if target is None:
        return pd.DataFrame()
    series = pd.to_numeric(data[target], errors="coerce")
    name = symbols[0] if symbols else "Asset"
    return series.to_frame(name=name)


def fetch_multi_asset_returns(
    symbols: Iterable[str],
    period: str = "2y",
    interval: str = "1d",
) -> tuple[pd.DataFrame, str]:
    symbols = [str(s).upper().strip() for s in symbols if str(s).strip()]
    symbols = list(dict.fromkeys(symbols))[:12]
    if len(symbols) < 2:
        symbols = ["SPY", "QQQ", "IWM", "TLT", "GLD", "HYG"]

    try:
        import yfinance as yf

        raw = yf.download(
            tickers=symbols,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=True,
            group_by="column",
        )
        close = _flatten_download(raw, symbols)
        if not close.empty:
            close = close.apply(pd.to_numeric, errors="coerce").dropna(how="all")
            returns = close.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
            keep = [c for c in returns.columns if returns[c].notna().sum() >= 40]
            returns = returns[keep].dropna()
            if returns.shape[1] >= 2 and len(returns) >= 40:
                return returns, "yfinance aligned daily returns"
    except Exception:
        pass

    return synthetic_returns(symbols, observations=504, seed=23), "deterministic synthetic fallback"

# ============================================================
# QUANTUM REGIME ENGINE V2 — CROSS-ASSET RESEARCH DATA
# ============================================================

def _extract_price_panel(raw: pd.DataFrame, requested: list[str]) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    data = raw.copy()
    if isinstance(data.columns, pd.MultiIndex):
        level0 = [str(x).lower() for x in data.columns.get_level_values(0)]
        target = "adj close" if "adj close" in level0 else "close" if "close" in level0 else None
        if target is None:
            return pd.DataFrame()
        actual = data.columns.get_level_values(0)[level0.index(target)]
        panel = data[actual].copy()
        if isinstance(panel, pd.Series):
            panel = panel.to_frame(name=requested[0] if requested else "PRIMARY")
        panel.columns = [str(c).upper() for c in panel.columns]
        return panel

    cols = {str(c).lower(): c for c in data.columns}
    target = cols.get("adj close") or cols.get("close")
    if target is None:
        return pd.DataFrame()
    name = requested[0] if requested else "PRIMARY"
    return pd.to_numeric(data[target], errors="coerce").to_frame(name=name)


def _synthetic_regime_prices(primary_symbol: str = "SPY", observations: int = 1008, seed: int = 41) -> pd.DataFrame:
    """Deterministic fallback with cross-asset structure; not presented as live data."""
    rng = np.random.default_rng(seed)
    labels = ["PRIMARY", "SPY", "TLT", "GLD", "HYG"]
    n = len(labels)
    # Four persistent latent environments used only to make the fallback useful
    # for UI/testing when external data is unavailable.
    transition = np.array(
        [
            [0.94, 0.025, 0.020, 0.015],
            [0.035, 0.91, 0.025, 0.030],
            [0.025, 0.020, 0.93, 0.025],
            [0.020, 0.030, 0.020, 0.93],
        ],
        dtype=float,
    )
    means = np.array(
        [
            [0.00055, 0.00045, -0.00005, 0.00010, 0.00030],  # risk-on
            [-0.00100, -0.00085, 0.00040, 0.00025, -0.00055], # risk-off
            [-0.00015, -0.00010, -0.00070, 0.00045, -0.00010], # inflation-like
            [-0.00035, -0.00025, 0.00075, -0.00010, -0.00035], # deflation-like
        ],
        dtype=float,
    )
    vols = np.array(
        [
            [0.010, 0.009, 0.006, 0.007, 0.006],
            [0.020, 0.018, 0.010, 0.011, 0.013],
            [0.014, 0.013, 0.011, 0.010, 0.009],
            [0.016, 0.014, 0.009, 0.008, 0.010],
        ],
        dtype=float,
    )
    states = np.zeros(observations, dtype=int)
    for t in range(1, observations):
        states[t] = rng.choice(4, p=transition[states[t - 1]])
    draws = np.empty((observations, n), dtype=float)
    common = rng.standard_normal(observations)
    for t, s in enumerate(states):
        idio = rng.standard_normal(n)
        draws[t] = means[s] + vols[s] * (0.55 * common[t] + 0.835 * idio)
    prices = 100.0 * np.exp(np.cumsum(draws, axis=0))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=observations)
    frame = pd.DataFrame(prices, index=idx, columns=labels)
    # VIX-like index derived from the latent environment plus noise.
    vix_base = np.array([16.0, 32.0, 24.0, 27.0])[states]
    frame["VIX"] = np.maximum(9.0, vix_base + rng.normal(0.0, 2.2, size=observations))
    if primary_symbol.upper() == "SPY":
        frame["PRIMARY"] = frame["SPY"]
    return frame


def fetch_regime_research_frame(
    primary_symbol: str = "SPY",
    period: str = "5y",
    interval: str = "1d",
) -> tuple[pd.DataFrame, str]:
    """
    Fetch the controlled cross-asset panel required by Regime Engine V2.

    Canonical output columns: PRIMARY, SPY, TLT, GLD, HYG, VIX.
    """
    primary = str(primary_symbol or "SPY").upper().strip()
    proxy_map = {
        "SPY": "SPY",
        "TLT": "TLT",
        "GLD": "GLD",
        "HYG": "HYG",
        "VIX": "^VIX",
    }
    requested = [primary, *proxy_map.values()]
    requested = list(dict.fromkeys(requested))

    try:
        import yfinance as yf

        raw = yf.download(
            tickers=requested,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False,
            threads=True,
            group_by="column",
        )
        panel = _extract_price_panel(raw, requested)
        if not panel.empty:
            panel = panel.apply(pd.to_numeric, errors="coerce").sort_index()
            result = pd.DataFrame(index=panel.index)
            if primary in panel.columns:
                result["PRIMARY"] = panel[primary]
            elif "SPY" in panel.columns:
                result["PRIMARY"] = panel["SPY"]
            for canonical, provider_symbol in proxy_map.items():
                if provider_symbol in panel.columns:
                    result[canonical] = panel[provider_symbol]
            # yfinance occasionally returns ticker names with case-preserved
            # variants; use case-insensitive fallback.
            upper_lookup = {str(c).upper(): c for c in panel.columns}
            for canonical, provider_symbol in proxy_map.items():
                if canonical not in result.columns and provider_symbol.upper() in upper_lookup:
                    result[canonical] = panel[upper_lookup[provider_symbol.upper()]]
            if "PRIMARY" not in result.columns and primary.upper() in upper_lookup:
                result["PRIMARY"] = panel[upper_lookup[primary.upper()]]

            required = ["PRIMARY", "SPY", "TLT", "GLD", "HYG", "VIX"]
            for name in required:
                if name not in result.columns:
                    result[name] = np.nan
            result = result[required].replace([np.inf, -np.inf], np.nan)
            # Keep partially aligned data; feature construction performs its own
            # point-in-time rolling NA handling.
            valid_cols = sum(result[c].notna().sum() >= 180 for c in required)
            if valid_cols >= 5 and len(result) >= 220:
                return result, "yfinance · cross-asset point-in-time panel"
    except Exception:
        pass

    return _synthetic_regime_prices(primary_symbol=primary, observations=1008, seed=41), "deterministic synthetic regime fallback"
