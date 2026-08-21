from __future__ import annotations

"""Dependency Data Hub V4.0.2.

Best-effort enrichment layer for the Multi-Force Dependency engine.

Design rules
------------
1. User/injected data always wins over auto-enrichment.
2. Public macro data are labelled as observed level/change proxies, never as surprises.
3. No price forward-fill is introduced into the frozen correlation core.  State variables
   are aligned *after* their own observations are loaded, with bounded as-of carry solely
   to map a macro/funding state onto the selected return dates.
4. Asset metadata/liquidity enrichment is pair-scoped and cached to keep Streamlit reruns
   bounded.
5. Any unavailable provider simply degrades coverage; it must never block the section.
"""

from dataclasses import dataclass, field
from io import StringIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import math
import os
import time
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


FRED_GRAPH_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={ids}&cosd={start}"
FRED_API_URL = "https://api.stlouisfed.org/fred/series/observations?series_id={series}&observation_start={start}&api_key={api_key}&file_type=json"
FRED_DISK_CACHE_VERSION = "v402"


# Public high-frequency/state variables.  These are deliberately not called "surprises".
# `tier=balanced` is a compact core; `tier=max` adds useful but more redundant state series.
FRED_FORCE_CATALOG: tuple[dict[str, Any], ...] = (
    {"series": "DGS2", "force": "Intermediate rates", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "US 2Y Treasury yield change"},
    {"series": "DGS10", "force": "Long-duration rates", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "US 10Y Treasury yield change"},
    {"series": "DFII10", "force": "Real yields", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "US 10Y real-yield change"},
    {"series": "T10Y2Y", "force": "Yield-curve slope", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "US 10Y-2Y slope change"},
    {"series": "T10YIE", "force": "Inflation expectations / breakevens", "mechanism": "Exogenous", "family": "Macro", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "US 10Y breakeven change"},
    {"series": "THREEFFTP10", "force": "Term premium", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "10Y-forward term-premium change"},
    {"series": "DFF", "force": "Fed policy rate change", "mechanism": "Exogenous", "family": "Monetary policy", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "Effective Fed Funds change"},
    {"series": "ECBDFR", "force": "ECB policy rate change", "mechanism": "Exogenous", "family": "Monetary policy", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "ECB deposit-facility rate change"},
    {"series": "BAMLH0A0HYM2", "force": "High-yield credit", "mechanism": "Exogenous", "family": "Credit", "transform": "diff", "max_age": 7, "tier": "balanced", "label": "US HY OAS change"},
    {"series": "BAMLC0A0CM", "force": "Investment-grade credit", "mechanism": "Exogenous", "family": "Credit", "transform": "diff", "max_age": 7, "tier": "balanced", "label": "US IG OAS change"},
    {"series": "SOFR", "force": "Funding / repo conditions", "mechanism": "Endogenous Market", "family": "Funding", "transform": "bp_diff", "max_age": 7, "tier": "balanced", "label": "SOFR change"},
    {"series": "SOFRVOL", "force": "Repo / funding transaction volume", "mechanism": "Endogenous Market", "family": "Funding", "transform": "log_return", "max_age": 7, "tier": "balanced", "label": "SOFR transaction-volume change"},
    {"series": "NFCI", "force": "Financial conditions", "mechanism": "Exogenous", "family": "Macro-financial", "transform": "diff", "max_age": 14, "tier": "balanced", "label": "Chicago Fed NFCI change"},
    {"series": "WALCL", "force": "QE / QT / central-bank balance sheet", "mechanism": "Exogenous", "family": "Monetary policy", "transform": "log_return", "max_age": 14, "tier": "balanced", "label": "Federal Reserve balance-sheet change"},
    {"series": "RRPONTSYD", "force": "Fed reverse-repo liquidity", "mechanism": "Endogenous Market", "family": "Funding", "transform": "diff", "max_age": 7, "tier": "balanced", "label": "Fed overnight reverse-repo change"},
    {"series": "WTREGEN", "force": "Treasury cash balance / TGA", "mechanism": "Exogenous", "family": "Fiscal", "transform": "diff", "max_age": 14, "tier": "balanced", "label": "US Treasury General Account change"},
    {"series": "USEPUINDXD", "force": "Economic policy uncertainty", "mechanism": "Information/Event", "family": "Information", "transform": "log_return", "max_age": 7, "tier": "balanced", "label": "US daily Economic Policy Uncertainty change"},
    {"series": "WLEMUINDXD", "force": "Equity market uncertainty", "mechanism": "Information/Event", "family": "Information", "transform": "log_return", "max_age": 7, "tier": "balanced", "label": "Daily equity-market-related economic uncertainty change"},

    # Max tier: additional state dimensions.  Failure of any one series is harmless.
    {"series": "DGS5", "force": "US 5Y rates", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "max", "label": "US 5Y Treasury yield change"},
    {"series": "DGS30", "force": "US 30Y rates", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "max", "label": "US 30Y Treasury yield change"},
    {"series": "T10Y3M", "force": "Yield-curve slope 10Y-3M", "mechanism": "Exogenous", "family": "Rates", "transform": "bp_diff", "max_age": 7, "tier": "max", "label": "US 10Y-3M slope change"},
    {"series": "T5YIE", "force": "5Y inflation expectations", "mechanism": "Exogenous", "family": "Macro", "transform": "bp_diff", "max_age": 7, "tier": "max", "label": "US 5Y breakeven change"},
    {"series": "SOFR99", "force": "Funding tail rate", "mechanism": "Endogenous Market", "family": "Funding", "transform": "bp_diff", "max_age": 7, "tier": "max", "label": "SOFR 99th-percentile change"},
    {"series": "ANFCI", "force": "Adjusted financial conditions", "mechanism": "Exogenous", "family": "Macro-financial", "transform": "diff", "max_age": 14, "tier": "max", "label": "Adjusted NFCI change"},
    {"series": "STLFSI4", "force": "Financial stress", "mechanism": "Exogenous", "family": "Macro-financial", "transform": "diff", "max_age": 14, "tier": "max", "label": "St. Louis Fed Financial Stress Index change"},
)


MARKET_FORCE_CATALOG: tuple[dict[str, Any], ...] = (
    {"symbol": "EURUSD=X", "force": "EUR/USD", "mechanism": "Exogenous", "family": "FX", "tier": "balanced"},
    {"symbol": "USDJPY=X", "force": "USD/JPY", "mechanism": "Exogenous", "family": "FX", "tier": "balanced"},
    {"symbol": "HG=F", "force": "Copper / industrial metals", "mechanism": "Exogenous", "family": "Commodities", "tier": "max"},
    {"symbol": "NG=F", "force": "Natural gas / power", "mechanism": "Exogenous", "family": "Commodities", "tier": "max"},
    {"symbol": "ZC=F", "force": "Agricultural inputs", "mechanism": "Exogenous", "family": "Commodities", "tier": "max"},
    {"symbol": "BTC-USD", "force": "Crypto market factor", "mechanism": "Endogenous Market", "family": "Crypto", "tier": "max"},
)

AI_GPR_DAILY_URL = "https://www.matteoiacoviello.com/ai_gpr_files/ai_gpr_data_daily.csv"
AI_GPR_FORCE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Geopolitical-risk index", ("gpr_ai", "ai_gpr", "gpr")),
    ("Geopolitical threats index", ("threats_gpr", "gpr_threats", "threats")),
    ("Geopolitical acts index", ("acts_gpr", "gpr_acts", "acts")),
    ("Geopolitical oil-disruption risk", ("oil_gpr", "gpr_oil", "oil")),
)


@dataclass
class DataHubResult:
    analysis: dict[str, Any]
    audit: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict[str, Any] = field(default_factory=dict)


_CACHE: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str, ttl: int) -> Any | None:
    item = _CACHE.get(key)
    if not item:
        return None
    ts, value = item
    if time.time() - ts > ttl:
        _CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: Any) -> Any:
    _CACHE[key] = (time.time(), value)
    return value


def _safe_num(x: Any) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except Exception:
        return None


def _target_index(changes: pd.DataFrame) -> pd.DatetimeIndex:
    idx = pd.to_datetime(changes.index, errors="coerce")
    idx = pd.DatetimeIndex(idx[~pd.isna(idx)])
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.sort_values().unique()


def _fred_cache_dir() -> Path:
    """Writable persistent cache for public FRED series.

    The path can be overridden with ``QUANT_TERMINAL_CACHE_DIR``.  Cache files are
    provider data, never part of the research package and never required for correctness.
    """
    root = os.getenv("QUANT_TERMINAL_CACHE_DIR")
    base = Path(root).expanduser() if root else Path.home() / ".cache" / "quant_terminal"
    path = base / "dependency_intelligence" / "fred" / FRED_DISK_CACHE_VERSION
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Fall back to a process-local temp-like location if HOME is read-only.
        path = Path("/tmp") / "quant_terminal_dependency_fred" / FRED_DISK_CACHE_VERSION
        path.mkdir(parents=True, exist_ok=True)
    return path


def _fred_cache_paths(series_id: str) -> tuple[Path, Path]:
    safe = "".join(ch for ch in str(series_id).upper() if ch.isalnum() or ch in {"_", "-"})
    return _fred_cache_dir() / f"{safe}.csv", _fred_cache_dir() / f"{safe}.json"


def _load_fred_disk_series(series_id: str) -> tuple[pd.Series, dict[str, Any]]:
    csv_path, meta_path = _fred_cache_paths(series_id)
    if not csv_path.exists():
        return pd.Series(dtype=float, name=series_id), {}
    try:
        df = pd.read_csv(csv_path)
        if df.empty or not {"date", "value"}.issubset(df.columns):
            return pd.Series(dtype=float, name=series_id), {}
        idx = pd.to_datetime(df["date"], errors="coerce")
        vals = pd.to_numeric(df["value"], errors="coerce")
        s = pd.Series(vals.to_numpy(), index=idx, name=series_id).dropna().sort_index()
        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                meta = {}
        try:
            mtime = csv_path.stat().st_mtime
            meta.setdefault("cache_age_hours", max(0.0, (time.time() - mtime) / 3600.0))
        except Exception:
            pass
        return s, meta
    except Exception:
        return pd.Series(dtype=float, name=series_id), {}


def _save_fred_disk_series(series_id: str, series: pd.Series, source: str) -> None:
    s = pd.to_numeric(series, errors="coerce").dropna().sort_index()
    if s.empty:
        return
    csv_path, meta_path = _fred_cache_paths(series_id)
    try:
        tmp = csv_path.with_suffix(".tmp")
        pd.DataFrame({"date": pd.to_datetime(s.index), "value": s.to_numpy()}).to_csv(tmp, index=False)
        tmp.replace(csv_path)
        meta = {
            "series_id": series_id,
            "source": source,
            "fetched_at_utc": pd.Timestamp.utcnow().isoformat(),
            "last_observation": pd.Timestamp(s.index.max()).isoformat(),
            "observations": int(s.notna().sum()),
        }
        meta_path.write_text(json.dumps(meta, indent=2))
    except Exception:
        # Provider cache failure must never block analytics.
        return


def _read_fred_url(url: str, timeout: float) -> pd.DataFrame:
    req = Request(url, headers={"User-Agent": "QuantTerminal-DependencyDataHub/4.0.2"})
    with urlopen(req, timeout=timeout) as r:
        raw = r.read().decode("utf-8", errors="replace")
    df = pd.read_csv(StringIO(raw))
    if df is None or df.empty:
        return pd.DataFrame()
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    for c in df.columns:
        df[c] = pd.to_numeric(df[c].replace(".", np.nan), errors="coerce")
    return df


def _read_fred_api_series(series_id: str, start: pd.Timestamp, api_key: str, timeout: float) -> pd.Series:
    url = FRED_API_URL.format(
        series=quote(series_id),
        start=quote(pd.Timestamp(start).strftime("%Y-%m-%d")),
        api_key=quote(api_key),
    )
    req = Request(url, headers={"User-Agent": "QuantTerminal-DependencyDataHub/4.0.2"})
    with urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8", errors="replace"))
    obs = payload.get("observations", []) if isinstance(payload, dict) else []
    if not isinstance(obs, list):
        return pd.Series(dtype=float, name=series_id)
    dates, vals = [], []
    for row in obs:
        if not isinstance(row, dict):
            continue
        dt = pd.to_datetime(row.get("date"), errors="coerce")
        val = pd.to_numeric(row.get("value"), errors="coerce")
        if pd.isna(dt) or pd.isna(val):
            continue
        dates.append(dt); vals.append(float(val))
    return pd.Series(vals, index=pd.DatetimeIndex(dates), name=series_id).sort_index()


def _extract_project_fred_levels(analysis: dict[str, Any] | None) -> pd.DataFrame:
    """Find already-loaded raw FRED/state levels from the Quant Terminal when exposed.

    This bridge intentionally accepts several neutral container names so the Correlation
    folder can consume an existing macro cache without importing Macro UI modules. Columns
    are expected to be FRED series IDs (e.g. DGS10, DFF, NFCI) and values are *levels*.
    """
    analysis = analysis or {}
    candidates = [
        "dependency_fred_levels", "fred_levels", "fred_series_frame", "macro_fred_levels",
        "macro_fred_series", "macro_state_levels", "macro_data_bundle",
    ]
    frames: list[pd.DataFrame] = []
    for key in candidates:
        obj = analysis.get(key)
        if isinstance(obj, pd.Series):
            frames.append(obj.to_frame())
        elif isinstance(obj, pd.DataFrame) and not obj.empty:
            frames.append(obj.copy())
        elif isinstance(obj, dict):
            cols: dict[str, pd.Series] = {}
            for k, v in obj.items():
                if isinstance(v, pd.Series):
                    cols[str(k)] = v
                elif isinstance(v, pd.DataFrame) and v.shape[1] >= 1:
                    cols[str(k)] = v.iloc[:, 0]
            if cols:
                frames.append(pd.DataFrame(cols))
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, axis=1)
    try:
        out.index = pd.to_datetime(out.index, errors="coerce")
        out = out.loc[~out.index.isna()].sort_index()
    except Exception:
        return pd.DataFrame()
    out.columns = [str(c).upper().strip() for c in out.columns]
    out = out.loc[:, ~out.columns.duplicated(keep="last")]
    return out.apply(pd.to_numeric, errors="coerce")


def _fred_api_key(analysis: dict[str, Any] | None = None) -> str | None:
    analysis = analysis or {}
    for key in ("fred_api_key", "FRED_API_KEY", "dependency_fred_api_key"):
        val = analysis.get(key)
        if val:
            return str(val).strip()
    for key in ("FRED_API_KEY", "FRED_KEY"):
        val = os.getenv(key)
        if val:
            return str(val).strip()
    return None


def _fetch_fred_batch(
    series_ids: list[str],
    start: pd.Timestamp,
    timeout: float = 3.0,
    ttl: int = 21600,
    analysis: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, str | None]:
    """Production-grade FRED cascade with persistent last-valid fallback.

    Priority:
      1. project/internal raw FRED levels when exposed in ``analysis``;
      2. fresh persistent local cache;
      3. official FRED API when an API key is available;
      4. small concurrent FRED graph-CSV chunks (not one giant batch);
      5. stale last-valid disk cache.

    The returned DataFrame carries provenance in ``df.attrs['fred_provenance']``.
    Network failure therefore degrades freshness rather than repeatedly stalling every
    Streamlit rerun.
    """
    ids = [str(x).upper().strip() for x in series_ids if str(x).strip()]
    ids = list(dict.fromkeys(ids))
    if not ids:
        return pd.DataFrame(), "no series"
    start = pd.Timestamp(start)
    start_s = start.strftime("%Y-%m-%d")
    key = "fred-v402:" + ",".join(ids) + ":" + start_s
    cached = _cache_get(key, ttl)
    if cached is not None:
        out = cached.copy()
        return out, None

    provenance: dict[str, dict[str, Any]] = {}
    pieces: dict[str, pd.Series] = {}
    stale_cache: dict[str, tuple[pd.Series, dict[str, Any]]] = {}
    errors: list[str] = []

    # 1) Existing Quant Terminal macro/FRED levels.
    project = _extract_project_fred_levels(analysis)
    for sid in ids:
        if sid in project.columns and not project[sid].dropna().empty:
            s = pd.to_numeric(project[sid], errors="coerce").dropna().sort_index()
            pieces[sid] = s
            provenance[sid] = {"source": "Quant Terminal macro/FRED cache", "fallback": False, "cache_age_hours": 0.0}

    # 2) Persistent cache. Fresh cache avoids any network call; stale cache is retained as
    # a final fallback if public providers fail.
    for sid in ids:
        if sid in pieces:
            continue
        disk, meta = _load_fred_disk_series(sid)
        if disk.empty:
            continue
        age = float(meta.get("cache_age_hours", np.inf)) if meta else np.inf
        stale_cache[sid] = (disk, meta)
        if age <= ttl / 3600.0:
            pieces[sid] = disk
            provenance[sid] = {
                "source": "FRED local cache",
                "fallback": False,
                "cache_age_hours": age,
                "fetched_at_utc": meta.get("fetched_at_utc"),
            }

    missing = [sid for sid in ids if sid not in pieces]

    # 3) Official API, only when keyed. Calls run concurrently and are individually bounded.
    api_key = _fred_api_key(analysis)
    if missing and api_key:
        def api_one(sid: str):
            try:
                return sid, _read_fred_api_series(sid, start, api_key, timeout), None
            except Exception as exc:
                return sid, pd.Series(dtype=float), f"{type(exc).__name__}: {str(exc)[:90]}"
        with ThreadPoolExecutor(max_workers=min(6, len(missing))) as pool:
            futs = [pool.submit(api_one, sid) for sid in missing]
            for fut in as_completed(futs):
                sid, ser, err = fut.result()
                if not ser.empty:
                    pieces[sid] = ser
                    provenance[sid] = {"source": "FRED API", "fallback": False, "cache_age_hours": 0.0}
                    _save_fred_disk_series(sid, ser, "FRED API")
                elif err:
                    errors.append(f"API {sid} {err}")
        missing = [sid for sid in ids if sid not in pieces]

    # 4) Public graph CSV in *small chunks*. The V4.0.1 monolithic request was the source
    # of the observed timeout. Small chunks are parallel, bounded and independently cached.
    if missing:
        chunk_size = 4
        chunks = [missing[i:i + chunk_size] for i in range(0, len(missing), chunk_size)]
        def graph_chunk(chunk: list[str]):
            url = FRED_GRAPH_URL.format(ids=quote(",".join(chunk), safe=","), start=quote(start_s))
            try:
                return chunk, _read_fred_url(url, timeout), None
            except Exception as exc:
                return chunk, pd.DataFrame(), f"{type(exc).__name__}: {str(exc)[:90]}"
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            futs = [pool.submit(graph_chunk, c) for c in chunks]
            for fut in as_completed(futs):
                chunk, frame, err = fut.result()
                if err:
                    errors.append(f"graph {','.join(chunk)} {err}")
                    continue
                for sid in chunk:
                    if sid in frame.columns and not frame[sid].dropna().empty:
                        ser = pd.to_numeric(frame[sid], errors="coerce").dropna().sort_index().rename(sid)
                        pieces[sid] = ser
                        provenance[sid] = {"source": "FRED graph CSV", "fallback": False, "cache_age_hours": 0.0}
                        _save_fred_disk_series(sid, ser, "FRED graph CSV")
        missing = [sid for sid in ids if sid not in pieces]

    # 5) Last-valid stale cache. This is explicitly labelled stale/fallback in the audit.
    for sid in missing:
        disk, meta = stale_cache.get(sid, (pd.Series(dtype=float), {}))
        if not disk.empty:
            pieces[sid] = disk
            provenance[sid] = {
                "source": "FRED stale last-valid cache",
                "fallback": True,
                "cache_age_hours": meta.get("cache_age_hours"),
                "fetched_at_utc": meta.get("fetched_at_utc"),
            }

    if not pieces:
        return pd.DataFrame(), "; ".join(errors[:6]) or "FRED cascade returned no data"
    out = pd.concat([pieces[sid].rename(sid) for sid in ids if sid in pieces], axis=1).sort_index()
    out.attrs["fred_provenance"] = provenance
    out.attrs["fred_errors"] = errors[:6]
    _cache_put(key, out.copy())
    return out, "; ".join(errors[:4]) if errors else None


def _align_level(level: pd.Series, target: pd.DatetimeIndex, max_age_days: int) -> pd.Series:
    s = pd.to_numeric(level, errors="coerce").dropna().sort_index()
    if s.empty or len(target) == 0:
        return pd.Series(index=target, dtype=float)
    idx = pd.to_datetime(s.index, errors="coerce")
    s = pd.Series(s.to_numpy(), index=idx).dropna().sort_index()
    s = s[~s.index.duplicated(keep="last")]
    try:
        # Bounded state carry: permitted for macro/funding *state variables* only.
        return s.reindex(target, method="ffill", tolerance=pd.Timedelta(days=int(max_age_days)))
    except Exception:
        union = s.index.union(target).sort_values()
        x = s.reindex(union).ffill(limit=max(int(max_age_days), 1))
        return x.reindex(target)


def _transform_aligned(level: pd.Series, transform: str) -> pd.Series:
    x = pd.to_numeric(level, errors="coerce")
    t = str(transform or "none").lower()
    if t == "bp_diff":
        return x.diff() * 100.0
    if t in {"diff", "change"}:
        return x.diff()
    if t in {"log_return", "logret"}:
        return np.log(x.where(x > 0)).diff()
    if t in {"pct_change", "return"}:
        return x.pct_change(fill_method=None)
    return x


def _fred_auto_forces(changes: pd.DataFrame, mode: str, analysis: dict[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    idx = _target_index(changes)
    if len(idx) == 0:
        return pd.DataFrame(), {}, pd.DataFrame(), pd.DataFrame()
    rows = [r for r in FRED_FORCE_CATALOG if r["tier"] == "balanced" or mode == "max"]
    ids = [r["series"] for r in rows]
    start = pd.Timestamp(idx.min()) - pd.Timedelta(days=45)
    try:
        raw, err = _fetch_fred_batch(ids, start, analysis=analysis)
    except TypeError:
        # Preserve compatibility with injected/custom provider callables and older tests.
        raw, err = _fetch_fred_batch(ids, start)
    provenance = raw.attrs.get("fred_provenance", {}) if isinstance(raw, pd.DataFrame) else {}
    audit: list[dict[str, Any]] = []
    out: list[pd.Series] = []
    meta: dict[str, dict[str, Any]] = {}
    aligned_levels: dict[str, pd.Series] = {}

    for r in rows:
        sid, force = r["series"], r["force"]
        prov = provenance.get(sid, {}) if isinstance(provenance, dict) else {}
        source = str(prov.get("source", "FRED cascade"))
        cache_age = prov.get("cache_age_hours", np.nan)
        fallback = bool(prov.get("fallback", False))
        if raw.empty or sid not in raw.columns or raw[sid].dropna().empty:
            audit.append({"Channel": "FRED", "Item": force, "Provider key": sid, "Status": "Unavailable", "Obs": 0, "Source": source, "Note": err or "series absent", "Cache age h": cache_age, "Fallback": fallback, "Last observation": None})
            continue
        lev = _align_level(raw[sid], idx, int(r["max_age"]))
        aligned_levels[sid] = lev
        shock = _transform_aligned(lev, str(r["transform"])).rename(force)
        n = int(shock.notna().sum())
        if n < 20:
            audit.append({"Channel": "FRED", "Item": force, "Provider key": sid, "Status": "Insufficient", "Obs": n, "Source": source, "Note": "too few aligned observations", "Cache age h": cache_age, "Fallback": fallback, "Last observation": pd.Timestamp(raw[sid].dropna().index.max()) if sid in raw and not raw[sid].dropna().empty else None})
            continue
        out.append(shock)
        meta[force] = {
            "force": force,
            "mechanism": r["mechanism"],
            "family": r["family"],
            "identification": "Observed public state/change proxy; associational, not a surprise measure",
            "source": f"FRED/{sid}",
            "source_kind": "auto_public",
            "input_kind": "shock",
            "transform": "none",
            "provider_key": sid,
            "description": r["label"],
            "provider_fallback": fallback,
            "provider_cache_age_hours": cache_age,
            "provider_source": source,
        }
        audit.append({"Channel": "FRED", "Item": force, "Provider key": sid, "Status": "Active (stale fallback)" if fallback else "Active", "Obs": n, "Source": source, "Note": r["label"], "Cache age h": cache_age, "Fallback": fallback, "Last observation": pd.Timestamp(raw[sid].dropna().index.max()) if not raw[sid].dropna().empty else None})

    # Derived macro forces from independently loaded public levels.
    def add_derived(name: str, s: pd.Series, mechanism: str, family: str, note: str):
        n = int(s.notna().sum())
        if n < 20:
            return
        out.append(s.rename(name))
        meta[name] = {
            "force": name, "mechanism": mechanism, "family": family,
            "identification": "Derived public state/change proxy; associational",
            "source": "Dependency Data Hub / FRED derived", "source_kind": "auto_derived",
            "input_kind": "shock", "transform": "none", "description": note,
        }
        audit.append({"Channel": "Derived macro", "Item": name, "Provider key": "", "Status": "Active", "Obs": n, "Source": "FRED derived", "Note": note})

    if "DFF" in aligned_levels and "ECBDFR" in aligned_levels:
        add_derived(
            "Fed-ECB policy divergence",
            (aligned_levels["DFF"] - aligned_levels["ECBDFR"]).diff() * 100.0,
            "Exogenous", "Monetary policy",
            "Daily change in the observed Fed-vs-ECB policy-rate differential; not a policy surprise.",
        )
    if all(k in aligned_levels for k in ("DGS2", "DGS5", "DGS10")):
        level = (aligned_levels["DGS2"] + aligned_levels["DGS5"] + aligned_levels["DGS10"]) / 3.0
        curvature = 2.0 * aligned_levels["DGS5"] - aligned_levels["DGS2"] - aligned_levels["DGS10"]
        add_derived("Yield-curve level", level.diff() * 100.0, "Exogenous", "Rates", "Parallel-ish US 2Y/5Y/10Y level change proxy.")
        add_derived("Yield-curve curvature", curvature.diff() * 100.0, "Exogenous", "Rates", "US 2Y/5Y/10Y curvature change proxy.")
    if "SOFR99" in aligned_levels and "SOFR" in aligned_levels:
        add_derived("Funding tail premium", (aligned_levels["SOFR99"] - aligned_levels["SOFR"]).diff() * 100.0, "Endogenous Market", "Funding", "Change in SOFR 99th-percentile minus median SOFR proxy.")

    # Actual policy-rate change events.  These are observed decisions/effective changes, not surprises.
    event_rows: list[dict[str, Any]] = []
    for sid, force, label in [("DFF", "Fed policy rate change", "Fed effective-rate change"), ("ECBDFR", "ECB policy rate change", "ECB deposit-rate change")]:
        lev = aligned_levels.get(sid)
        if lev is None or lev.empty:
            continue
        d = lev.diff()
        for dt, val in d[d.abs() >= 0.05].items():
            event_rows.append({"Date": pd.Timestamp(dt), "Force": force, "Mechanism": "Exogenous", "Family": "Monetary policy", "Label": label, "Observed change": float(val), "Identification": "Observed policy-rate change event (>=5 bp); not a surprise"})
    events = pd.DataFrame(event_rows)
    factor_df = pd.concat(out, axis=1) if out else pd.DataFrame(index=idx)
    return factor_df, meta, events, pd.DataFrame(audit)


def _gpr_auto_forces(changes: pd.DataFrame, timeout: float = 4.0, ttl: int = 21600) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], pd.DataFrame]:
    """Load the public daily AI-GPR family if available.

    Column matching is intentionally fuzzy because the publisher can extend the CSV schema.
    Values are converted to log changes; the level itself is not treated as a causal shock.
    """
    idx = _target_index(changes)
    if len(idx) == 0:
        return pd.DataFrame(), {}, pd.DataFrame()
    key = f"ai-gpr:{pd.Timestamp(idx.min()).date()}:{pd.Timestamp(idx.max()).date()}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        df = cached.copy()
    else:
        try:
            req = Request(AI_GPR_DAILY_URL, headers={"User-Agent": "QuantTerminal-DependencyDataHub/4.0.2"})
            with urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", errors="replace")
            df = pd.read_csv(StringIO(raw))
            _cache_put(key, df.copy())
        except Exception as exc:
            audit = pd.DataFrame([{"Channel": "Geopolitical", "Item": "AI-GPR daily", "Provider key": "AI-GPR", "Status": "Unavailable", "Obs": 0, "Source": "Iacoviello/Tong public CSV", "Note": f"{type(exc).__name__}: {str(exc)[:100]}"}])
            return pd.DataFrame(), {}, audit
    if df is None or df.empty:
        return pd.DataFrame(), {}, pd.DataFrame()
    cols = {str(c).strip().lower().replace("-", "_").replace(" ", "_"): c for c in df.columns}
    date_key = next((k for k in cols if k in {"date", "day", "observation_date", "datetime"} or "date" in k), None)
    if date_key is None:
        return pd.DataFrame(), {}, pd.DataFrame([{"Channel": "Geopolitical", "Item": "AI-GPR daily", "Provider key": "AI-GPR", "Status": "Unavailable", "Obs": 0, "Source": "Iacoviello/Tong public CSV", "Note": "date column not recognized"}])
    dt = pd.to_datetime(df[cols[date_key]], errors="coerce")
    base = df.copy(); base.index = dt; base = base.loc[~base.index.isna()].sort_index()
    out: list[pd.Series] = []; meta: dict[str, dict[str, Any]] = {}; audit_rows = []
    for force, aliases in AI_GPR_FORCE_ALIASES:
        key_match = next((k for k in cols if k in aliases), None)
        if key_match is None:
            # relaxed contains match, but avoid accidentally mapping every GPR component to the main index
            key_match = next((k for k in cols if any(a in k for a in aliases if len(a) >= 5)), None)
        if key_match is None:
            continue
        lev = _align_level(pd.to_numeric(base[cols[key_match]], errors="coerce"), idx, 7)
        shock = np.log(lev.where(lev > 0)).diff().rename(force)
        n = int(shock.notna().sum())
        if n < 20:
            continue
        out.append(shock)
        meta[force] = {
            "force": force, "mechanism": "Exogenous", "family": "Geopolitics",
            "identification": "Public geopolitical-risk index change; associational",
            "source": "Iacoviello/Tong AI-GPR", "source_kind": "auto_public",
            "input_kind": "shock", "transform": "none", "provider_key": str(cols[key_match]),
        }
        audit_rows.append({"Channel": "Geopolitical", "Item": force, "Provider key": str(cols[key_match]), "Status": "Active", "Obs": n, "Source": "Iacoviello/Tong AI-GPR public CSV", "Note": "daily log-change index proxy"})
    return (pd.concat(out, axis=1) if out else pd.DataFrame(index=idx), meta, pd.DataFrame(audit_rows))


def _import_yfinance():
    try:
        import yfinance as yf  # type: ignore
        return yf
    except Exception:
        return None


def _yahoo_history(symbol: str, start: pd.Timestamp, end: pd.Timestamp, ttl: int = 1800) -> pd.DataFrame:
    key = f"yf-hist:{symbol}:{start.date()}:{end.date()}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return cached.copy()
    yf = _import_yfinance()
    if yf is None:
        return pd.DataFrame()
    try:
        raw = yf.download(symbol, start=start.strftime("%Y-%m-%d"), end=(end + pd.Timedelta(days=2)).strftime("%Y-%m-%d"), auto_adjust=True, progress=False, threads=False, timeout=6)
        if raw is None or raw.empty:
            return pd.DataFrame()
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [str(c[0]) for c in raw.columns]
        raw.index = pd.to_datetime(raw.index, errors="coerce")
        if getattr(raw.index, "tz", None) is not None:
            raw.index = raw.index.tz_convert("UTC").tz_localize(None)
        out = pd.DataFrame(index=raw.index)
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c in raw.columns:
                out[c.lower()] = pd.to_numeric(raw[c], errors="coerce")
        out = out.dropna(how="all").sort_index()
        return _cache_put(key, out.copy())
    except Exception:
        return pd.DataFrame()


def _yahoo_metadata(symbol: str, ttl: int = 21600) -> dict[str, Any]:
    key = f"yf-meta:{symbol}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        return dict(cached)
    yf = _import_yfinance()
    if yf is None:
        return {}
    try:
        t = yf.Ticker(symbol)
        info: dict[str, Any] = {}
        try:
            raw = t.info
            if isinstance(raw, dict):
                info.update(raw)
        except Exception:
            pass
        try:
            fast = t.fast_info
            if fast is not None:
                for key2 in ["currency", "market_cap", "last_price", "ten_day_average_volume", "three_month_average_volume", "exchange", "timezone"]:
                    try:
                        val = fast[key2]
                    except Exception:
                        try:
                            val = getattr(fast, key2)
                        except Exception:
                            val = None
                    if val is not None and key2 not in info:
                        info[key2] = val
        except Exception:
            pass
        out = {
            "currency": info.get("currency"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "market_cap": info.get("marketCap", info.get("market_cap")),
            "enterprise_value": info.get("enterpriseValue"),
            "total_debt": info.get("totalDebt"),
            "total_cash": info.get("totalCash"),
            "debt_to_equity": info.get("debtToEquity"),
            "beta": info.get("beta"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "short_percent_float": info.get("shortPercentOfFloat"),
            "average_volume": info.get("averageVolume", info.get("three_month_average_volume", info.get("ten_day_average_volume"))),
            "exchange": info.get("exchange"),
            "timezone": info.get("exchangeTimezoneName", info.get("timezone")),
            "quote_type": info.get("quoteType"),
            "long_name": info.get("longName", info.get("shortName")),
        }
        out = {k: v for k, v in out.items() if v is not None and str(v) != "nan"}
        return _cache_put(key, out)
    except Exception:
        return {}


def _yahoo_top_holder_overlap(primary: str, peer: str, ttl: int = 21600) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Best-effort overlap of disclosed top institutional holders.

    This is a *top-holder proxy*, not a complete 13F ownership network. When percentage-held
    fields are unavailable, top-holder weights are normalized within each returned table.
    """
    key = f"yf-holders:{primary}:{peer}"
    cached = _cache_get(key, ttl)
    if cached is not None:
        mat, audit = cached
        return mat.copy(), audit.copy()
    yf = _import_yfinance()
    if yf is None:
        return pd.DataFrame(), pd.DataFrame()

    def table(symbol: str) -> dict[str, float]:
        try:
            df = yf.Ticker(symbol).institutional_holders
        except Exception:
            return {}
        if not isinstance(df, pd.DataFrame) or df.empty:
            return {}
        holder_col = next((c for c in df.columns if str(c).lower() in {"holder", "organization", "name"}), None)
        if holder_col is None:
            return {}
        pct_col = next((c for c in df.columns if "pct" in str(c).lower() or "% out" in str(c).lower() or "percent" in str(c).lower()), None)
        share_col = next((c for c in df.columns if str(c).lower() in {"shares", "position", "value"}), None)
        vals = pd.to_numeric(df[pct_col] if pct_col is not None else df[share_col] if share_col is not None else pd.Series(index=df.index, dtype=float), errors="coerce")
        tmp = pd.DataFrame({"holder": df[holder_col].astype(str), "w": vals}).dropna()
        tmp = tmp[tmp["w"] > 0]
        if tmp.empty:
            return {}
        if pct_col is None:
            total = float(tmp["w"].sum())
            if total <= 0:
                return {}
            tmp["w"] = tmp["w"] / total
        return tmp.groupby("holder")["w"].sum().to_dict()

    a, b = table(primary), table(peer)
    if not a or not b:
        audit = pd.DataFrame([{"Channel": "Ownership", "Item": f"{primary}/{peer}", "Provider key": "institutional_holders", "Status": "Unavailable", "Obs": 0, "Source": "Yahoo/yfinance", "Note": "top-holder tables unavailable"}])
        return pd.DataFrame(), audit
    common = set(a) & set(b)
    overlap = float(sum(min(float(a[h]), float(b[h])) for h in common))
    overlap = max(0.0, min(overlap, 1.0))
    mat = pd.DataFrame([[1.0, overlap], [overlap, 1.0]], index=[primary, peer], columns=[primary, peer])
    audit = pd.DataFrame([{"Channel": "Ownership", "Item": f"{primary}/{peer}", "Provider key": "institutional_holders", "Status": "Active", "Obs": len(common), "Source": "Yahoo/yfinance", "Note": "disclosed top-holder overlap proxy; incomplete ownership network"}])
    _cache_put(key, (mat.copy(), audit.copy()))
    return mat, audit


def _market_auto_forces(changes: pd.DataFrame, mode: str) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], pd.DataFrame]:
    idx = _target_index(changes)
    if len(idx) == 0:
        return pd.DataFrame(), {}, pd.DataFrame()
    out, meta, audit = [], {}, []
    start, end = pd.Timestamp(idx.min()) - pd.Timedelta(days=10), pd.Timestamp(idx.max())
    for r in MARKET_FORCE_CATALOG:
        if r["tier"] == "max" and mode != "max":
            continue
        force = r["force"]
        # If the frozen core already carries a superior/identical force proxy, custom/FRED data later wins.
        hist = _yahoo_history(r["symbol"], start, end)
        if hist.empty or "close" not in hist:
            audit.append({"Channel": "Yahoo market", "Item": force, "Provider key": r["symbol"], "Status": "Unavailable", "Obs": 0, "Source": "Yahoo/yfinance", "Note": "history unavailable"})
            continue
        lev = _align_level(hist["close"], idx, 7)
        s = np.log(lev.where(lev > 0)).diff().rename(force)
        n = int(s.notna().sum())
        if n < 20:
            continue
        out.append(s)
        meta[force] = {
            "force": force, "mechanism": r["mechanism"], "family": r["family"],
            "identification": "Tradable market proxy/associational",
            "source": f"Yahoo/{r['symbol']}", "source_kind": "auto_market",
            "input_kind": "shock", "transform": "none", "proxy_ticker": r["symbol"],
        }
        audit.append({"Channel": "Yahoo market", "Item": force, "Provider key": r["symbol"], "Status": "Active", "Obs": n, "Source": "Yahoo/yfinance", "Note": "log-return proxy"})
    return (pd.concat(out, axis=1) if out else pd.DataFrame(index=idx), meta, pd.DataFrame(audit))


def _auto_asset_and_liquidity(primary: str, peer: str, changes: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[str, pd.DataFrame], pd.DataFrame]:
    idx = _target_index(changes)
    if len(idx) == 0:
        return {}, {}, pd.DataFrame()
    start, end = pd.Timestamp(idx.min()) - pd.Timedelta(days=10), pd.Timestamp(idx.max())
    asset_meta: dict[str, dict[str, Any]] = {}
    histories: dict[str, pd.DataFrame] = {}
    audit: list[dict[str, Any]] = []
    for symbol in [primary, peer]:
        meta = _yahoo_metadata(symbol)
        hist = _yahoo_history(symbol, start, end)
        histories[symbol] = hist
        if meta:
            if not hist.empty and "close" in hist:
                last = _safe_num(hist["close"].dropna().iloc[-1]) if not hist["close"].dropna().empty else None
                av = _safe_num(meta.get("average_volume"))
                if last is not None and av is not None:
                    meta["adv_usd"] = last * av
            meta["metadata_source"] = "Yahoo/yfinance best-effort"
            asset_meta[symbol] = meta
            audit.append({"Channel": "Asset metadata", "Item": symbol, "Provider key": symbol, "Status": "Active", "Obs": 1, "Source": "Yahoo/yfinance", "Note": ", ".join(sorted(meta.keys()))})
        else:
            audit.append({"Channel": "Asset metadata", "Item": symbol, "Provider key": symbol, "Status": "Unavailable", "Obs": 0, "Source": "Yahoo/yfinance", "Note": "metadata unavailable"})

    liquidity: dict[str, pd.DataFrame] = {}
    metric_rows: dict[str, dict[str, pd.Series]] = {"DollarVolume": {}, "AmihudIlliquidity": {}, "VolumeShock": {}}
    for symbol, hist in histories.items():
        if hist.empty or "close" not in hist or "volume" not in hist:
            continue
        close = _align_level(hist["close"], idx, 7)
        volume = _align_level(hist["volume"], idx, 7)
        ret = np.log(close.where(close > 0)).diff()
        dollar = (close * volume).where((close > 0) & (volume > 0))
        amihud = (ret.abs() / (dollar / 1e6)).replace([np.inf, -np.inf], np.nan)
        vshock = np.log(volume.where(volume > 0)).diff()
        metric_rows["DollarVolume"][symbol] = dollar
        metric_rows["AmihudIlliquidity"][symbol] = amihud
        metric_rows["VolumeShock"][symbol] = vshock
    for metric, cols in metric_rows.items():
        if len(cols) < 2:
            continue
        df = pd.DataFrame(cols, index=idx)
        if df.dropna(how="all").shape[0] >= 30:
            liquidity[metric] = df
            audit.append({"Channel": "Liquidity", "Item": metric, "Provider key": f"{primary},{peer}", "Status": "Active", "Obs": int(df.dropna().shape[0]), "Source": "Yahoo OHLCV derived", "Note": "pair-scoped liquidity commonality proxy"})
    return asset_meta, liquidity, pd.DataFrame(audit)


def _fx_symbol(local: str, base: str) -> tuple[str, bool] | None:
    local, base = local.upper(), base.upper()
    if local == base:
        return None
    # Yahoo convention usually supports BASEQUOTE=X.  We first ask for local/base, then
    # caller may invert a base/local fallback.
    return f"{local}{base}=X", False


def _auto_fx_to_base(asset_meta: dict[str, dict[str, Any]], base: str, changes: pd.DataFrame) -> tuple[dict[str, pd.Series], pd.DataFrame]:
    idx = _target_index(changes)
    start, end = pd.Timestamp(idx.min()) - pd.Timedelta(days=10), pd.Timestamp(idx.max())
    currencies = sorted({str(v.get("currency", "")).upper() for v in asset_meta.values() if v.get("currency")})
    out: dict[str, pd.Series] = {}
    audit = []
    for cur in currencies:
        if not cur or cur == base:
            continue
        direct = f"{cur}{base}=X"
        inverse = f"{base}{cur}=X"
        h = _yahoo_history(direct, start, end)
        inv = False
        used = direct
        if h.empty or "close" not in h:
            h = _yahoo_history(inverse, start, end)
            inv, used = True, inverse
        if h.empty or "close" not in h:
            audit.append({"Channel": "FX normalization", "Item": cur, "Provider key": f"{direct}|{inverse}", "Status": "Unavailable", "Obs": 0, "Source": "Yahoo/yfinance", "Note": f"cannot resolve {base} per {cur}"})
            continue
        lev = _align_level(h["close"], idx, 7)
        if inv:
            lev = 1.0 / lev.where(lev != 0)
        out[cur] = lev
        audit.append({"Channel": "FX normalization", "Item": cur, "Provider key": used, "Status": "Active", "Obs": int(lev.notna().sum()), "Source": "Yahoo/yfinance", "Note": f"{base} per {cur}"})
    return out, pd.DataFrame(audit)


def _merge_frames(auto: pd.DataFrame, user: Any) -> pd.DataFrame:
    if isinstance(user, pd.Series):
        user = user.to_frame()
    if not isinstance(user, pd.DataFrame) or user.empty:
        return auto.copy()
    u = user.copy()
    try:
        u.index = pd.to_datetime(u.index, errors="coerce")
        u = u.loc[~u.index.isna()].sort_index()
    except Exception:
        return auto.copy()
    # User columns win on name collisions.
    a = auto.drop(columns=[c for c in u.columns if c in auto.columns], errors="ignore")
    return pd.concat([a, u], axis=1).sort_index()


def _merge_events(auto: pd.DataFrame, user: Any) -> pd.DataFrame:
    frames = [x for x in [auto, user if isinstance(user, pd.DataFrame) else pd.DataFrame(user) if isinstance(user, list) else pd.DataFrame()] if isinstance(x, pd.DataFrame) and not x.empty]
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    if "Date" in out.columns:
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
        out = out.dropna(subset=["Date"])
    subset = [c for c in ["Date", "Force", "Label"] if c in out.columns]
    if subset:
        out = out.drop_duplicates(subset=subset, keep="last")
    return out.sort_values("Date") if "Date" in out.columns else out


def _project_bridge(analysis: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    """Collect exact, non-invasive upstream bridge keys when present.

    No import of WorldMonitor/Options UI modules is attempted: those modules are large and may
    have rendering side effects.  The bridge instead accepts stable data contracts if another
    module has placed them in `analysis` or Streamlit session-state upstream.
    """
    force_keys = ["macro_force_series", "macro_surprise_series", "worldmonitor_force_series", "geopolitical_force_series", "options_dependency_series", "derivatives_force_series"]
    meta_keys = ["macro_force_metadata", "worldmonitor_force_metadata", "geopolitical_force_metadata", "options_dependency_metadata", "derivatives_force_metadata"]
    event_keys = ["macro_event_table", "worldmonitor_event_table", "geopolitical_event_table", "options_event_table", "derivatives_event_table"]
    series_parts, metadata, event_parts, audit = [], {}, [], []
    for k in force_keys:
        obj = analysis.get(k)
        if isinstance(obj, pd.Series):
            obj = obj.to_frame()
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            series_parts.append(obj)
            audit.append({"Channel": "Project bridge", "Item": k, "Provider key": k, "Status": "Active", "Obs": len(obj), "Source": "Quant Terminal upstream", "Note": f"{obj.shape[1]} series"})
    for k in meta_keys:
        obj = analysis.get(k)
        if isinstance(obj, dict):
            metadata.update({str(a): b for a, b in obj.items() if isinstance(b, dict)})
    for k in event_keys:
        obj = analysis.get(k)
        if isinstance(obj, pd.DataFrame) and not obj.empty:
            event_parts.append(obj)
            audit.append({"Channel": "Project bridge", "Item": k, "Provider key": k, "Status": "Active", "Obs": len(obj), "Source": "Quant Terminal upstream", "Note": "event table"})
    s = pd.concat(series_parts, axis=1) if series_parts else pd.DataFrame()
    e = pd.concat(event_parts, ignore_index=True, sort=False) if event_parts else pd.DataFrame()
    return s, metadata, e, pd.DataFrame(audit)


def build_dependency_data_hub(primary: str, peer: str, changes: pd.DataFrame, analysis: dict[str, Any] | None = None) -> DataHubResult:
    original = dict(analysis or {})
    mode = str(original.get("dependency_data_hub_mode", "injected-only") or "injected-only").lower().strip()
    if mode in {"off", "injected", "injected only", "injected-only", "none"}:
        return DataHubResult(original, pd.DataFrame(), {"mode": "injected-only", "active": False})
    mode = "balanced" if mode.startswith("bal") else "max"

    enriched = dict(original)
    audits = []

    fred_series, fred_meta, fred_events, fred_audit = _fred_auto_forces(changes, mode, original)
    gpr_series, gpr_meta, gpr_audit = _gpr_auto_forces(changes)
    market_series, market_meta, market_audit = _market_auto_forces(changes, mode)
    bridge_series, bridge_meta, bridge_events, bridge_audit = _project_bridge(original)

    auto_parts = [fred_series, gpr_series, market_series, bridge_series]
    auto_series = pd.concat([x for x in auto_parts if isinstance(x, pd.DataFrame) and not x.empty], axis=1) if any(isinstance(x, pd.DataFrame) and not x.empty for x in auto_parts) else pd.DataFrame()
    auto_series = auto_series.loc[:, ~auto_series.columns.duplicated(keep="last")] if not auto_series.empty else auto_series
    enriched["dependency_force_series"] = _merge_frames(auto_series, original.get("dependency_force_series"))

    auto_meta = {}
    auto_meta.update(fred_meta)
    auto_meta.update(gpr_meta)
    auto_meta.update(market_meta)
    auto_meta.update(bridge_meta)
    user_meta = original.get("dependency_force_metadata", {})
    if isinstance(user_meta, dict):
        for k, v in user_meta.items():
            if isinstance(v, dict):
                auto_meta[str(k)] = {**auto_meta.get(str(k), {}), **v}
    enriched["dependency_force_metadata"] = auto_meta

    enriched["dependency_event_table"] = _merge_events(_merge_events(fred_events, bridge_events), original.get("dependency_event_table"))

    # Pair-scoped structural/liquidity enrichment.
    auto_asset, auto_liq, asset_audit = _auto_asset_and_liquidity(primary, peer, changes)
    auto_ownership, ownership_audit = _yahoo_top_holder_overlap(primary, peer) if mode == "max" else (pd.DataFrame(), pd.DataFrame())
    user_asset = original.get("dependency_asset_metadata", {})
    merged_asset = {k: dict(v) for k, v in auto_asset.items()}
    if isinstance(user_asset, dict):
        for k, v in user_asset.items():
            if isinstance(v, dict):
                merged_asset[str(k)] = {**merged_asset.get(str(k), {}), **v}
    enriched["dependency_asset_metadata"] = merged_asset

    base = str(original.get("dependency_base_currency", "USD") or "USD").upper()
    enriched["dependency_base_currency"] = base
    auto_fx, fx_audit = _auto_fx_to_base(merged_asset, base, changes) if merged_asset else ({}, pd.DataFrame())
    user_fx = original.get("dependency_fx_to_base", {})
    if isinstance(user_fx, dict):
        auto_fx.update(user_fx)  # explicit user series wins
    enriched["dependency_fx_to_base"] = auto_fx

    user_liq = original.get("dependency_liquidity_series", {})
    merged_liq = dict(auto_liq)
    if isinstance(user_liq, dict):
        merged_liq.update(user_liq)
    enriched["dependency_liquidity_series"] = merged_liq

    user_ownership = original.get("dependency_ownership_matrix")
    enriched["dependency_ownership_matrix"] = user_ownership if isinstance(user_ownership, pd.DataFrame) and not user_ownership.empty else auto_ownership

    for x in [fred_audit, gpr_audit, market_audit, bridge_audit, asset_audit, ownership_audit, fx_audit]:
        if isinstance(x, pd.DataFrame) and not x.empty:
            audits.append(x)
    audit = pd.concat(audits, ignore_index=True, sort=False) if audits else pd.DataFrame()

    active = audit[audit["Status"].astype(str).str.startswith("Active")] if not audit.empty and "Status" in audit else pd.DataFrame()
    summary = {
        "mode": mode,
        "active": True,
        "auto_force_series": int(enriched["dependency_force_series"].shape[1]) if isinstance(enriched.get("dependency_force_series"), pd.DataFrame) else 0,
        "auto_event_rows": int(len(enriched["dependency_event_table"])) if isinstance(enriched.get("dependency_event_table"), pd.DataFrame) else 0,
        "asset_metadata_assets": int(len(merged_asset)),
        "liquidity_metrics": int(len(merged_liq)),
        "fx_currencies": int(len(auto_fx)),
        "ownership_proxy": bool(isinstance(enriched.get("dependency_ownership_matrix"), pd.DataFrame) and not enriched.get("dependency_ownership_matrix").empty),
        "active_provider_items": int(len(active)),
    }
    return DataHubResult(enriched, audit, summary)
