from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .registry import DEFAULT_PROXY_METADATA, force_registry


@dataclass
class ForceInputs:
    series: pd.DataFrame = field(default_factory=pd.DataFrame)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: pd.DataFrame = field(default_factory=pd.DataFrame)
    asset_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    fx_to_base: dict[str, pd.Series] = field(default_factory=dict)
    liquidity: dict[str, pd.DataFrame] = field(default_factory=dict)
    pnl_series: pd.DataFrame = field(default_factory=pd.DataFrame)
    ownership_matrix: pd.DataFrame = field(default_factory=pd.DataFrame)
    relationship_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    base_currency: str = "USD"


def _as_dataframe(obj: Any) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if isinstance(obj, pd.Series):
        return obj.to_frame()
    if isinstance(obj, dict):
        try:
            return pd.DataFrame(obj)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def _normalize_index(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    try:
        out.index = pd.to_datetime(out.index, errors="coerce")
        out = out.loc[~out.index.isna()]
        if getattr(out.index, "tz", None) is not None:
            out.index = out.index.tz_convert("UTC").tz_localize(None)
        out = out.sort_index()
        out = out[~out.index.duplicated(keep="last")]
    except Exception:
        return pd.DataFrame()
    return out


def _metadata_defaults(name: str) -> dict[str, Any]:
    return {
        "force": str(name),
        "mechanism": "Custom",
        "family": "Custom",
        "identification": "Associational",
        "source": "Injected",
        "input_kind": "shock",
        "transform": "none",
    }


def _transform_force_column(s: pd.Series, meta: dict[str, Any]) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    transform = str(meta.get("transform", "none") or "none").lower().strip()
    input_kind = str(meta.get("input_kind", "shock") or "shock").lower().strip()

    # If the caller explicitly marks a level, default to a sensible transformation.
    if transform == "none" and input_kind == "level":
        transform = "log_return" if bool(meta.get("positive_level", True)) else "diff"

    if transform in {"return", "simple_return", "pct_change"}:
        return x.pct_change(fill_method=None)
    if transform in {"log_return", "logret", "log-diff"}:
        positive = x.where(x > 0)
        return np.log(positive).diff()
    if transform in {"diff", "change"}:
        return x.diff()
    if transform in {"bp_diff", "bps", "basis_points"}:
        return x.diff() * 100.0
    if transform in {"zscore", "standardize"}:
        sd = float(x.std(ddof=1))
        return (x - float(x.mean())) / sd if np.isfinite(sd) and sd > 0 else x * np.nan
    return x


def collect_force_inputs(changes: pd.DataFrame, analysis: dict[str, Any] | None = None) -> ForceInputs:
    analysis = analysis or {}
    custom_series = _normalize_index(_as_dataframe(analysis.get("dependency_force_series")))
    custom_meta_raw = analysis.get("dependency_force_metadata", {})
    custom_meta = custom_meta_raw if isinstance(custom_meta_raw, dict) else {}

    series_parts: list[pd.Series] = []
    metadata: dict[str, dict[str, Any]] = {}

    # Existing market proxies are immediately usable and carry explicit "proxy" labels.
    for ticker, meta in DEFAULT_PROXY_METADATA.items():
        if ticker in changes.columns:
            name = str(meta["force"])
            s = pd.to_numeric(changes[ticker], errors="coerce").rename(name)
            series_parts.append(s)
            m = _metadata_defaults(name)
            m.update(meta)
            m.update({"source": ticker, "input_kind": "shock", "transform": "none", "proxy_ticker": ticker})
            metadata[name] = m

    # Caller-supplied force data can represent macro surprises, policy factors, flows,
    # geopolitics indices, positioning, derivatives state, alternative data, etc.
    if not custom_series.empty:
        for col in custom_series.columns:
            raw_meta = custom_meta.get(col, custom_meta.get(str(col), {}))
            m = _metadata_defaults(str(col))
            if isinstance(raw_meta, dict):
                m.update(raw_meta)
            name = str(m.get("force") or col)
            s = _transform_force_column(custom_series[col], m).rename(name)
            # If two inputs intentionally share a force name, the last injected one wins.
            metadata[name] = m | {"force": name, "source": m.get("source", "Injected")}
            series_parts = [z for z in series_parts if z.name != name]
            series_parts.append(s)

    force_series = pd.concat(series_parts, axis=1).sort_index() if series_parts else pd.DataFrame()
    if not force_series.empty:
        force_series = force_series.loc[:, ~force_series.columns.duplicated(keep="last")]

    events = _as_dataframe(analysis.get("dependency_event_table"))
    if not events.empty:
        events = events.copy()
        date_col = next((c for c in events.columns if str(c).lower() in {"date", "timestamp", "datetime"}), None)
        if date_col is not None:
            events[date_col] = pd.to_datetime(events[date_col], errors="coerce")
            events = events.dropna(subset=[date_col]).sort_values(date_col).rename(columns={date_col: "Date"})
        else:
            events = pd.DataFrame()

    asset_meta = analysis.get("dependency_asset_metadata", {})
    asset_meta = asset_meta if isinstance(asset_meta, dict) else {}

    fx_raw = analysis.get("dependency_fx_to_base", {})
    fx_to_base: dict[str, pd.Series] = {}
    if isinstance(fx_raw, dict):
        for currency, obj in fx_raw.items():
            if isinstance(obj, pd.Series):
                s = obj.copy()
            elif isinstance(obj, pd.DataFrame) and obj.shape[1] >= 1:
                s = obj.iloc[:, 0].copy()
            else:
                try:
                    s = pd.Series(obj)
                except Exception:
                    continue
            s = pd.to_numeric(s, errors="coerce")
            try:
                s.index = pd.to_datetime(s.index, errors="coerce")
                s = s.loc[~s.index.isna()].sort_index()
            except Exception:
                continue
            fx_to_base[str(currency).upper()] = s

    liquidity_raw = analysis.get("dependency_liquidity_series", {})
    liquidity: dict[str, pd.DataFrame] = {}
    if isinstance(liquidity_raw, dict):
        for metric, obj in liquidity_raw.items():
            df = _normalize_index(_as_dataframe(obj))
            if not df.empty:
                liquidity[str(metric)] = df.apply(pd.to_numeric, errors="coerce")

    pnl = _normalize_index(_as_dataframe(analysis.get("dependency_pnl_series")))
    if not pnl.empty:
        pnl = pnl.apply(pd.to_numeric, errors="coerce")

    ownership = _as_dataframe(analysis.get("dependency_ownership_matrix"))
    if not ownership.empty:
        ownership = ownership.apply(pd.to_numeric, errors="coerce")

    rel = _as_dataframe(analysis.get("dependency_relationship_table"))

    return ForceInputs(
        series=force_series,
        metadata=metadata,
        events=events,
        asset_metadata=asset_meta,
        fx_to_base=fx_to_base,
        liquidity=liquidity,
        pnl_series=pnl,
        ownership_matrix=ownership,
        relationship_table=rel,
        base_currency=str(analysis.get("dependency_base_currency", "USD") or "USD").upper(),
    )


def force_coverage_table(inputs: ForceInputs, changes: pd.DataFrame) -> pd.DataFrame:
    reg = force_registry().copy()
    active_series = set(inputs.series.columns)
    event_forces: set[str] = set()
    event_mechanisms: set[str] = set()
    event_families: set[str] = set()
    if not inputs.events.empty:
        for c, target in [("Force", event_forces), ("Mechanism", event_mechanisms), ("Family", event_families), ("Category", event_families)]:
            if c in inputs.events.columns:
                target.update(inputs.events[c].dropna().astype(str).tolist())

    # Presence maps prevent one generic metadata/liquidity channel from falsely activating
    # every registry row in that family.
    meta_keys: set[str] = set()
    if isinstance(inputs.asset_metadata, dict):
        for v in inputs.asset_metadata.values():
            if isinstance(v, dict):
                meta_keys.update(str(k).lower() for k, val in v.items() if val is not None)
    liq_names = {str(k).lower().replace("_", "") for k in inputs.liquidity}
    has_ownership = isinstance(inputs.ownership_matrix, pd.DataFrame) and not inputs.ownership_matrix.empty
    has_relationship = isinstance(inputs.relationship_table, pd.DataFrame) and not inputs.relationship_table.empty

    metadata_requirements = {
        "Currency translation": {"currency"}, "FX hedge overlay": {"currency"},
        "Market-hours alignment": {"timezone", "session_close", "exchange"},
        "Trading calendar": {"calendar"}, "Asset-type risk unit": {"asset_type", "quote_type"},
        "Market capitalization": {"market_cap"}, "Index weight": {"index_weight"},
        "Portfolio weight": {"portfolio_weight"}, "DV01 / duration": {"dv01", "duration"},
        "CS01 / spread duration": {"cs01", "spread_duration"},
        "Greeks / option sensitivities": {"delta", "gamma", "vega", "greeks"},
        "Benchmark membership": {"benchmark", "index_membership"},
        "Balance-sheet leverage": {"debt_to_equity", "total_debt"},
        "Customer concentration": {"customer_concentration"},
        "Ownership concentration / fragility": {"ownership_concentration"},
    }
    liquidity_requirements = {
        "Bid-ask spread": ("bidask", "spread"),
        "Market depth": ("depth",),
        "ADV / turnover": ("adv", "dollarvolume", "volumeshock", "turnover"),
        "Short interest": ("short",),
        "Borrow fee / securities lending": ("borrow", "securitieslending"),
    }

    statuses = []
    for _, row in reg.iterrows():
        force = str(row["Force"])
        channel = str(row["Input channel"])
        status = "Not connected"
        source = ""
        if force in active_series:
            meta = inputs.metadata.get(force, {})
            source = str(meta.get("source", "Injected"))
            kind = str(meta.get("source_kind", "")).lower()
            if kind == "auto_public":
                status = "Auto public series"
            elif kind == "auto_market":
                status = "Auto market series"
            elif kind == "auto_derived":
                status = "Auto derived series"
            elif meta.get("proxy_ticker"):
                status = "Active proxy"
            else:
                status = "Injected series"
        elif force in event_forces:
            status = "Injected/auto events"
            source = "dependency_event_table"
        elif not event_forces and (str(row["Mechanism"]) in event_mechanisms or str(row["Family"]) in event_families):
            status = "Injected/auto events"
            source = "dependency_event_table (broad-labelled)"
        elif force in {"Information diffusion / lead-lag", "Extreme moves / co-extremes (daily)"}:
            if changes is not None and isinstance(changes, pd.DataFrame) and changes.shape[1] >= 2 and len(changes) >= 30:
                status = "Derived in pair engine"
                source = "daily transformed returns"
        elif force == "Market liquidity" and inputs.liquidity:
            status = "Liquidity channel available"
            source = ", ".join(inputs.liquidity.keys())
        elif channel == "liquidity" and inputs.liquidity:
            tokens = liquidity_requirements.get(force, ())
            matched = [name for name in liq_names if any(tok in name for tok in tokens)]
            if matched:
                status = "Liquidity channel available"
                source = ", ".join(inputs.liquidity.keys())
        elif force == "Common institutional ownership" and has_ownership:
            status = "Ownership channel available"
            source = "dependency_ownership_matrix"
        elif force == "Supply-chain exposure" and has_relationship:
            status = "Relationship channel available"
            source = "dependency_relationship_table"
        elif channel == "metadata" and inputs.asset_metadata:
            required = metadata_requirements.get(force, set())
            if required and (required & meta_keys):
                status = "Metadata channel available"
                source = "dependency_asset_metadata"
        elif force == "P&L risk-space / sensitivities" and not inputs.pnl_series.empty:
            status = "P&L series available"
            source = "dependency_pnl_series"
        statuses.append((status, source))
    reg["Status"] = [x[0] for x in statuses]
    reg["Source"] = [x[1] for x in statuses]
    order = {
        "Injected series": 0, "Auto public series": 1, "Auto derived series": 2,
        "Auto market series": 3, "Active proxy": 4, "Injected/auto events": 5,
        "Derived in pair engine": 6, "Liquidity channel available": 7,
        "Ownership channel available": 8, "Relationship channel available": 9,
        "P&L series available": 10, "Metadata channel available": 11, "Not connected": 99,
    }
    reg["_order"] = reg["Status"].map(order).fillna(50)
    return reg.sort_values(["_order", "Mechanism", "Family", "Force"]).drop(columns="_order").reset_index(drop=True)

