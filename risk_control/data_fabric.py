"""Credential-aware enrichment fabric for Risk Monitor.

No credential is ever returned by this module.  Adapters are dormant when a
required key is absent and activate automatically once the corresponding
secret is configured in the environment or Streamlit secrets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from provider_config import resolve_secret


@dataclass(frozen=True)
class RiskDataCapability:
    capability: str
    provider: str
    secret_names: tuple[str, ...]
    coverage: str
    engine_hook: str


CAPABILITIES: tuple[RiskDataCapability, ...] = (
    RiskDataCapability("Historical OHLCV", "Twelve Data / Alpha Vantage", ("TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY"), "Prices, returns, realized risk", "ACTIVE THROUGH MARKET GATEWAY"),
    RiskDataCapability("NBBO / executable spread", "Tradier / Massive", ("TRADIER_API_TOKEN", "MASSIVE_API_KEY"), "Bid, ask, sizes and quote timestamp", "AUTO ENRICHMENT"),
    RiskDataCapability("Options IV / Greeks / OI", "ThetaData / Massive / Tradier", ("THETADATA_API_KEY", "MASSIVE_API_KEY", "TRADIER_API_TOKEN"), "Implied tail, skew, gamma and positioning", "AUTO ENRICHMENT"),
    RiskDataCapability("Futures curve / OI", "Massive / Databento", ("MASSIVE_API_KEY", "DATABENTO_API_KEY"), "Term structure, basis and roll stress", "CONTRACT READY"),
    RiskDataCapability("Order book / market depth", "Databento", ("DATABENTO_API_KEY",), "Depth, imbalance and calibrated impact", "CONTRACT READY"),
    RiskDataCapability("Macro factor matrix", "FRED / shared market gateway", ("FRED_API_KEY", "TWELVE_DATA_API_KEY", "ALPHA_VANTAGE_API_KEY"), "Rates, USD, vol and cross-asset factors", "CONTRACT READY"),
    RiskDataCapability("Portfolio positions", "Portfolio Lab contract", (), "Weights, hedges, Greeks, funding and limits", "INPUT CONTRACT READY"),
)


def risk_data_readiness(secrets: Mapping[str, Any] | None = None) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for capability in CAPABILITIES:
        configured = [name for name in capability.secret_names if resolve_secret(name, secrets)]
        if not capability.secret_names:
            state = "READY FOR INPUT"
        elif configured:
            state = "CONFIGURED"
        elif capability.capability == "Historical OHLCV":
            state = "ACTIVE FALLBACK"
        else:
            state = "READY FOR KEY"
        row = asdict(capability)
        row.update(
            {
                "State": state,
                "Activation": ", ".join(configured) if configured else " / ".join(capability.secret_names) or "Runtime payload",
            }
        )
        rows.append(
            {
                "Capability": row["capability"],
                "State": row["State"],
                "Provider": row["provider"],
                "Coverage": row["coverage"],
                "Engine hook": row["engine_hook"],
                "Activation": row["Activation"],
            }
        )
    return pd.DataFrame(rows)


def _flatten_chain(calls: pd.DataFrame, puts: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (calls, puts) if isinstance(frame, pd.DataFrame) and not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _option_summary(frame: pd.DataFrame, underlying_price: float | None) -> dict[str, Any]:
    if frame.empty:
        return {}
    bid = pd.to_numeric(frame.get("bid", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    ask = pd.to_numeric(frame.get("ask", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    mid = (bid + ask) / 2.0
    spreads = ((ask - bid) / mid.replace(0, np.nan)).where((bid > 0) & (ask >= bid))
    iv = pd.to_numeric(frame.get("impliedVolatility", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    if iv.notna().any() and float(iv.dropna().median()) > 3.0:
        iv = iv / 100.0
    oi = pd.to_numeric(frame.get("openInterest", pd.Series(index=frame.index, dtype=float)), errors="coerce").fillna(0.0)
    option_type = frame.get("option_type", pd.Series("", index=frame.index)).astype(str).str.lower()
    put_oi = float(oi[option_type.eq("put")].sum())
    call_oi = float(oi[option_type.eq("call")].sum())
    atm_iv = None
    strike = pd.to_numeric(frame.get("strike", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    reference = underlying_price
    if reference is None or not np.isfinite(reference):
        vendor_underlying = pd.to_numeric(frame.get("underlyingPrice", pd.Series(index=frame.index, dtype=float)), errors="coerce").dropna()
        reference = float(vendor_underlying.median()) if not vendor_underlying.empty else None
    if reference is not None and np.isfinite(reference) and strike.notna().any() and iv.notna().any():
        distance = (strike - float(reference)).abs()
        candidates = frame.loc[distance.nsmallest(min(10, distance.notna().sum())).index].index
        values = iv.reindex(candidates).dropna()
        atm_iv = float(values.median()) if not values.empty else None

    delta = pd.to_numeric(frame.get("delta_vendor", pd.Series(index=frame.index, dtype=float)), errors="coerce")
    put_mask = option_type.eq("put") & delta.notna()
    call_mask = option_type.eq("call") & delta.notna()
    put_25 = None
    call_25 = None
    if put_mask.any():
        put_index = (delta[put_mask].abs() - 0.25).abs().idxmin()
        put_25 = float(iv.loc[put_index]) if pd.notna(iv.loc[put_index]) else None
    if call_mask.any():
        call_index = (delta[call_mask].abs() - 0.25).abs().idxmin()
        call_25 = float(iv.loc[call_index]) if pd.notna(iv.loc[call_index]) else None
    return {
        "contracts": int(len(frame)),
        "median_spread_pct": float(spreads.median()) if spreads.notna().any() else None,
        "atm_iv": atm_iv,
        "put_call_oi": put_oi / call_oi if call_oi > 0 else None,
        "put_25d_iv": put_25,
        "call_25d_iv": call_25,
        "risk_reversal_25d": put_25 - call_25 if put_25 is not None and call_25 is not None else None,
        "iv_coverage": float(iv.notna().mean()),
        "greeks_coverage": float((delta.notna()).mean()),
    }


def _tradier_underlying_quote(ticker: str, token: str, sandbox: bool) -> dict[str, Any]:
    from derivatives_market_data import tradier_get_json

    payload = tradier_get_json(
        "/v1/markets/quotes",
        token,
        sandbox=sandbox,
        params={"symbols": str(ticker).upper().strip(), "greeks": "false"},
    )
    quote = (payload.get("quotes") or {}).get("quote") or {}
    if isinstance(quote, list):
        quote = quote[0] if quote else {}
    bid = pd.to_numeric(pd.Series([quote.get("bid")]), errors="coerce").iloc[0]
    ask = pd.to_numeric(pd.Series([quote.get("ask")]), errors="coerce").iloc[0]
    mid = (bid + ask) / 2.0 if pd.notna(bid) and pd.notna(ask) and ask >= bid else np.nan
    return {
        "bid": float(bid) if pd.notna(bid) else None,
        "ask": float(ask) if pd.notna(ask) else None,
        "mid": float(mid) if pd.notna(mid) else None,
        "spread_pct": float((ask - bid) / mid) if pd.notna(mid) and mid > 0 else None,
        "bid_size": quote.get("bidsize"),
        "ask_size": quote.get("asksize"),
        "trade_volume": quote.get("volume"),
        "description": quote.get("description"),
        "last": quote.get("last"),
        "quote_type": quote.get("type"),
    }


def load_risk_market_enrichment(
    ticker: str,
    *,
    underlying_price: float | None = None,
    secrets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Auto-load the best configured quote/options adapter, with sanitized errors."""

    from derivatives_market_data import (
        fetch_massive_option_chain,
        fetch_massive_option_expirations,
        fetch_thetadata_option_chain,
        fetch_thetadata_option_expirations,
        fetch_tradier_option_chain,
        fetch_tradier_option_expirations,
        get_tradier_sandbox,
    )

    ticker = str(ticker).upper().strip()
    token = resolve_secret(("TRADIER_API_TOKEN", "TRADIER_ACCESS_TOKEN"), secrets)
    massive = resolve_secret(("MASSIVE_API_KEY", "MASSIVEAPI_KEY"), secrets)
    theta = resolve_secret(("THETADATA_API_KEY", "THETA_DATA_API_KEY"), secrets)
    attempts: list[str] = []
    quote: dict[str, Any] = {}
    if token:
        try:
            quote = _tradier_underlying_quote(ticker, token, get_tradier_sandbox(secrets or {}))
        except Exception as exc:
            attempts.append(f"Tradier quote unavailable ({type(exc).__name__})")

    loaders = []
    if theta:
        loaders.append(("ThetaData / OPRA", lambda: fetch_thetadata_option_expirations(ticker, theta), lambda expiry: fetch_thetadata_option_chain(ticker, expiry, theta)))
    if massive:
        loaders.append(("Massive / OPRA", lambda: fetch_massive_option_expirations(ticker, massive), lambda expiry: fetch_massive_option_chain(ticker, expiry, massive)))
    if token:
        sandbox = get_tradier_sandbox(secrets or {})
        loaders.append(("Tradier / OPRA", lambda: fetch_tradier_option_expirations(ticker, token, sandbox=sandbox), lambda expiry: fetch_tradier_option_chain(ticker, expiry, token, sandbox=sandbox)))

    for provider, expiry_loader, chain_loader in loaders:
        try:
            expirations, _ = expiry_loader()
            if not expirations:
                attempts.append(f"{provider}: no active expiration")
                continue
            today = pd.Timestamp.now().normalize()
            dated = [(value, (pd.Timestamp(value) - today).days) for value in expirations]
            eligible = [item for item in dated if item[1] >= 21]
            expiration = min(eligible or dated, key=lambda item: abs(item[1] - 45))[0]
            calls, puts, context = chain_loader(expiration)
            frame = _flatten_chain(calls, puts)
            if frame.empty:
                attempts.append(f"{provider}: empty chain")
                continue
            return {
                "ok": True,
                "status": "LIVE" if "REAL" in str(context.recency).upper() else "ENTITLED",
                "provider": provider,
                "expiration": expiration,
                "quote": quote,
                "options": _option_summary(frame, underlying_price),
                "context": context.to_dict() if hasattr(context, "to_dict") else {},
                "attempts": attempts,
            }
        except Exception as exc:
            attempts.append(f"{provider} unavailable ({type(exc).__name__})")

    return {
        "ok": bool(quote),
        "status": "QUOTE_ONLY" if quote else "READY_FOR_KEY" if not loaders else "CONFIGURED_NO_DATA",
        "provider": "Tradier" if quote else None,
        "expiration": None,
        "quote": quote,
        "options": {},
        "context": {},
        "attempts": attempts,
    }
