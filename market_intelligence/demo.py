"""Deterministic research fixture and terminal-context adapter.

The first release intentionally ships without a mandatory news or L2 key.  It
therefore renders a fully labelled canonical fixture and, when available,
shows the existing Quant Terminal price context separately.  No silent switch
from missing live data to simulation is permitted.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .catalysts import assess_interaction, collision_metrics
from .contracts import (
    AvailabilityStatus,
    MicrostructureSnapshot,
    ProviderHealth,
    StructuredEvent,
    WorkspaceSnapshot,
    as_utc,
)
from .microstructure import microprice, order_flow_imbalance, queue_imbalance, trade_imbalance
from .models import empirical_distribution_forecasts


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "fed_nvda_collision.json"


def load_canonical_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalized_symbol(value: Any) -> str:
    symbol = str(value or "NVDA").upper().strip()
    return symbol[:24] or "NVDA"


def _terminal_price_context(price_data: Any, analysis: Any) -> dict[str, Any]:
    output = {
        "available": False,
        "price": None,
        "change": None,
        "as_of": None,
        "rows": 0,
        "source": "No inherited terminal price context",
    }
    if isinstance(price_data, pd.DataFrame) and not price_data.empty:
        columns = {str(column).casefold(): column for column in price_data.columns}
        close_column = columns.get("close") or columns.get("price") or columns.get("last")
        if close_column is not None:
            close = pd.to_numeric(price_data[close_column], errors="coerce").dropna()
            if not close.empty:
                output["available"] = True
                output["price"] = float(close.iloc[-1])
                output["change"] = (
                    float(close.iloc[-1] / close.iloc[-2] - 1.0) if len(close) > 1 and close.iloc[-2] else None
                )
                try:
                    stamp = price_data.index[-1]
                    parsed = pd.Timestamp(stamp)
                    if parsed.tzinfo is None:
                        parsed = parsed.tz_localize("UTC")
                    output["as_of"] = parsed.tz_convert("UTC").to_pydatetime()
                except Exception:
                    output["as_of"] = None
                output["rows"] = int(len(close))
                output["source"] = "Inherited Quant Terminal market-data context"
    if not output["available"] and isinstance(analysis, Mapping):
        for key in ("current_price", "price", "last_price"):
            try:
                candidate = float(analysis.get(key))
            except (TypeError, ValueError):
                continue
            if np.isfinite(candidate) and candidate > 0.0:
                output.update(
                    {
                        "available": True,
                        "price": candidate,
                        "source": "Inherited Quant Terminal analysis context",
                    }
                )
                break
    return output


def _events(raw_events: list[dict[str, Any]]) -> tuple[StructuredEvent, ...]:
    events: list[StructuredEvent] = []
    for raw in raw_events:
        item = dict(raw)
        item["validation_flags"] = tuple(item.get("validation_flags", ()))
        events.append(StructuredEvent(**item))
    return tuple(events)


def _narratives(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Narrative": "Higher for longer",
                "Intensity": 0.86,
                "Momentum": 0.31,
                "Acceleration": 0.08,
                "Sentiment": -0.67,
                "Novelty share": 0.58,
                "Source diversity": 0.82,
                "Exposure": f"Rates · Nasdaq · {symbol}",
                "Decay state": "ACCELERATING",
                "Status": "SIMULATED",
            },
            {
                "Narrative": "AI capex persistence",
                "Intensity": 0.74,
                "Momentum": 0.18,
                "Acceleration": -0.03,
                "Sentiment": 0.71,
                "Novelty share": 0.34,
                "Source diversity": 0.69,
                "Exposure": f"{symbol} · Semis · Datacenter",
                "Decay state": "PERSISTENT",
                "Status": "SIMULATED",
            },
            {
                "Narrative": "Duration-sensitive growth",
                "Intensity": 0.62,
                "Momentum": 0.24,
                "Acceleration": 0.05,
                "Sentiment": -0.48,
                "Novelty share": 0.47,
                "Source diversity": 0.73,
                "Exposure": "NDX · SMH · Long duration",
                "Decay state": "RISING",
                "Status": "SIMULATED",
            },
        ]
    )


def _analogues(symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Episode": "SYNTH-A01", "Event": "Hawkish macro + earnings beat", "Similarity": 0.89, "Event sim": 0.94, "Regime sim": 0.86, "Micro sim": 0.91, "Vol sim": 0.77, "Return +1h": 0.0032, "Return +1d": 0.014, "Status": "FIXTURE"},
            {"Episode": "SYNTH-A02", "Event": "Rates shock + bid absorption", "Similarity": 0.84, "Event sim": 0.82, "Regime sim": 0.91, "Micro sim": 0.88, "Vol sim": 0.76, "Return +1h": -0.0011, "Return +1d": 0.009, "Status": "FIXTURE"},
            {"Episode": "SYNTH-A03", "Event": f"{symbol} positive company shock", "Similarity": 0.78, "Event sim": 0.88, "Regime sim": 0.65, "Micro sim": 0.82, "Vol sim": 0.73, "Return +1h": 0.0048, "Return +1d": 0.021, "Status": "FIXTURE"},
            {"Episode": "SYNTH-A04", "Event": "Catalyst collision / elevated vol", "Similarity": 0.73, "Event sim": 0.79, "Regime sim": 0.72, "Micro sim": 0.69, "Vol sim": 0.74, "Return +1h": -0.0037, "Return +1d": -0.006, "Status": "FIXTURE"},
            {"Episode": "SYNTH-A05", "Event": "Macro decay / company dominance", "Similarity": 0.69, "Event sim": 0.71, "Regime sim": 0.63, "Micro sim": 0.72, "Vol sim": 0.70, "Return +1h": 0.0024, "Return +1d": 0.011, "Status": "FIXTURE"},
        ]
    )


def _relationships(symbol: str, as_of: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Source": "Federal Reserve", "Target": "US 2Y", "Relation": "policy sensitivity", "Edge status": "observed", "Weight": 0.92, "Lead/Lag": "0-5m", "Confidence": "HIGH", "Valid from": "2020-01-01T00:00:00Z", "Valid to": None, "Point-in-time safe": True, "Data source": "fixture"},
            {"Source": "US 2Y", "Target": "Nasdaq 100", "Relation": "rates sensitivity", "Edge status": "model_association", "Weight": -0.74, "Lead/Lag": "1-15m", "Confidence": "MEDIUM", "Valid from": "2020-01-01T00:00:00Z", "Valid to": None, "Point-in-time safe": True, "Data source": "fixture"},
            {"Source": "Nasdaq 100", "Target": symbol, "Relation": "index membership / beta", "Edge status": "economic_link", "Weight": 0.81, "Lead/Lag": "concurrent", "Confidence": "HIGH", "Valid from": "2020-01-01T00:00:00Z", "Valid to": None, "Point-in-time safe": True, "Data source": "fixture"},
            {"Source": symbol, "Target": "SMH", "Relation": "sector transmission", "Edge status": "economic_link", "Weight": 0.67, "Lead/Lag": "0-30m", "Confidence": "MEDIUM", "Valid from": "2020-01-01T00:00:00Z", "Valid to": None, "Point-in-time safe": True, "Data source": "fixture"},
            {"Source": symbol, "Target": "AI infrastructure", "Relation": "demand narrative", "Edge status": "hypothesis", "Weight": 0.54, "Lead/Lag": "1d-1w", "Confidence": "LOW", "Valid from": "2026-06-17T19:08:00Z", "Valid to": None, "Point-in-time safe": True, "Data source": "fixture"},
        ]
    )


def _patterns() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Pattern ID": "MI-PAT-001", "Signature": "Negative catalyst + rising bid replenishment", "Discovery": "Rule baseline", "Occurrences": 0, "OOS windows": 0, "Multiple-testing": "NOT RUN", "After costs": None, "Stability": "WAITING EVIDENCE", "Status": "RESEARCH_ONLY"},
            {"Pattern ID": "MI-PAT-002", "Signature": "High collision + compressed net pressure", "Discovery": "Fixture taxonomy", "Occurrences": 1, "OOS windows": 0, "Multiple-testing": "NOT APPLICABLE", "After costs": None, "Stability": "UNTESTED", "Status": "RESEARCH_ONLY"},
            {"Pattern ID": "MI-PAT-003", "Signature": "Chart-image continuation", "Discovery": "Proposed ViT challenger", "Occurrences": 0, "OOS windows": 0, "Multiple-testing": "NOT RUN", "After costs": None, "Stability": "NO DATA", "Status": "DISABLED"},
        ]
    )


def _model_registry(as_of: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Role": "BASELINE", "Model": "Empirical distribution", "Version": "1.0.0", "Status": "RESEARCH_ONLY", "Data cutoff": as_of, "Brier": None, "Log loss": None, "Coverage": "FIXTURE", "Drift": "N/A", "Rollback": "N/A"},
            {"Role": "CHALLENGER", "Model": "Logistic catalyst + micro", "Version": "not-trained", "Status": "WAITING_DATA", "Data cutoff": None, "Brier": None, "Log loss": None, "Coverage": "NONE", "Drift": "N/A", "Rollback": "NOT ELIGIBLE"},
            {"Role": "CHALLENGER", "Model": "DeepLOB representation", "Version": "not-trained", "Status": "DISABLED", "Data cutoff": None, "Brier": None, "Log loss": None, "Coverage": "NO LOB HISTORY", "Drift": "N/A", "Rollback": "NOT ELIGIBLE"},
            {"Role": "CHALLENGER", "Model": "Gated multimodal fusion", "Version": "not-trained", "Status": "DISABLED", "Data cutoff": None, "Brier": None, "Log loss": None, "Coverage": "NONE", "Drift": "N/A", "Rollback": "NOT ELIGIBLE"},
        ]
    )


def build_workspace_snapshot(
    ticker: str = "NVDA",
    price_data: Any = None,
    analysis: Any = None,
) -> WorkspaceSnapshot:
    raw = load_canonical_fixture()
    requested_symbol = _normalized_symbol(ticker)
    symbol = "NVDA"
    as_of = as_utc(raw["as_of"])
    context_matches_fixture = requested_symbol == symbol
    terminal_context = (
        _terminal_price_context(price_data, analysis)
        if context_matches_fixture
        else {
            "available": False,
            "price": None,
            "change": None,
            "as_of": None,
            "rows": 0,
            "source": f"Blocked: requested {requested_symbol} cannot be fused with the canonical {symbol} fixture",
        }
    )
    timeline = pd.DataFrame(raw["timeline"])
    timeline["timestamp"] = pd.to_datetime(timeline["timestamp"], utc=True)
    events = _events(raw["events"])
    contributions = pd.DataFrame(raw["catalyst_contributions"])
    quote_events = list(raw["quote_events"])
    last_quote = quote_events[-1]
    context = dict(raw["microstructure_context"])
    qi = queue_imbalance(last_quote["bid_size"], last_quote["ask_size"])
    mp = microprice(
        last_quote["best_bid"], last_quote["best_ask"], last_quote["bid_size"], last_quote["ask_size"]
    )
    ofi = order_flow_imbalance(quote_events)
    trade_imb = trade_imbalance(context["buy_volume"], context["sell_volume"])
    micro = MicrostructureSnapshot(
        symbol=symbol,
        as_of=as_of,
        window="30s",
        schema_level="L2",
        provider_status=AvailabilityStatus.SIMULATED,
        best_bid=last_quote["best_bid"],
        best_ask=last_quote["best_ask"],
        bid_size=last_quote["bid_size"],
        ask_size=last_quote["ask_size"],
        mid=(last_quote["best_bid"] + last_quote["best_ask"]) / 2.0,
        microprice=mp,
        spread=last_quote["best_ask"] - last_quote["best_bid"],
        ofi=ofi,
        queue_imbalance=qi,
        trade_imbalance=trade_imb,
        cancel_intensity=context["cancel_intensity"],
        add_intensity=context["add_intensity"],
        bid_replenishment=context["bid_replenishment"],
        ask_replenishment=context["ask_replenishment"],
        price_impact_proxy=context["price_impact_proxy"],
        anomaly_percentile=context["anomaly_percentile"],
        uncertainty_flags=("SIMULATED_L2_MESSAGES", "NO_LIVE_ENTITLEMENT_CHECK"),
    )
    interaction = assess_interaction(contributions["contribution"], context)
    forecasts = empirical_distribution_forecasts(
        symbol,
        timeline["price"],
        as_of=as_of,
        horizons=(("10m", 1), ("30m", 3), ("1h", 6), ("2h", 12)),
        provider_status=AvailabilityStatus.SIMULATED,
        regime_state="high_conflict_risk_off_transition",
        primary_drivers=("fixture price history", "unconditional empirical baseline"),
    )
    collision = collision_metrics(contributions["contribution"])
    related_asset_anomaly = 0.71
    known_intensity = min(1.0, collision["intensity"] / 3.0)
    unexplained_residual = max(
        0.0,
        min(1.0, (float(micro.anomaly_percentile or 0.0) + related_asset_anomaly) / 2.0 - 0.72 * known_intensity),
    )
    depth_ladder = pd.DataFrame(raw["depth_ladder"])
    audit = {
        "fixture_id": raw["fixture_id"],
        "fixture_status": raw["fixture_status"],
        "fixture_description": raw["description"],
        "terminal_context": terminal_context,
        "context_integrity": {
            "requested_symbol": requested_symbol,
            "fixture_symbol": symbol,
            "state": "MATCHED" if context_matches_fixture else "MISMATCH_BLOCKED",
            "fusion_allowed": bool(context_matches_fixture),
            "reason": (
                "Requested instrument matches the canonical fixture identity."
                if context_matches_fixture
                else f"The {symbol} fixture was not repainted or fused into requested instrument {requested_symbol}."
            ),
        },
        "quote_events": pd.DataFrame(quote_events),
        "depth_ladder": depth_ladder,
        "micro_context": context,
        "collision": collision,
        "information_gap": {
            "known_catalyst_intensity": known_intensity,
            "microstructure_anomaly": micro.anomaly_percentile,
            "options_anomaly": None,
            "related_asset_anomaly": related_asset_anomaly,
            "unexplained_residual": unexplained_residual,
            "status": "NO UNEXPLAINED-FLOW ALARM" if unexplained_residual < 0.70 else "INVESTIGATE",
        },
        "data_contract": {
            "market_context": "inherited terminal context" if terminal_context["available"] else "unavailable",
            "event_layer": "simulated canonical fixture",
            "microstructure_layer": "simulated sequenced L2 fixture",
            "forecast_layer": "empirical distribution baseline on fixture prices",
            "live_provider_calls": 0,
            "network_calls_at_import": 0,
        },
    }
    price = terminal_context["price"] if terminal_context["available"] else float(timeline["price"].iloc[-1])
    price_change = terminal_context["change"] if terminal_context["available"] else float(timeline["price"].iloc[-1] / timeline["price"].iloc[-2] - 1.0)
    market_status = "TERMINAL CONTEXT" if terminal_context["available"] else "SIMULATED FIXTURE"
    return WorkspaceSnapshot(
        symbol=symbol,
        instrument_name=raw["instrument_name"],
        as_of=as_of,
        price=price,
        price_change=price_change,
        regime="HIGH CONFLICT · RISK-OFF TRANSITION",
        regime_probability=None,
        overall_status="RESEARCH ONLY · MIXED CONTEXT / SIMULATED EVENT LAYER",
        market_status=market_status,
        catalyst_status="SIMULATED",
        microstructure_level="L2 · SIMULATED",
        timeline=timeline,
        events=events,
        catalyst_contributions=contributions,
        microstructure=micro,
        interaction=interaction,
        forecasts=forecasts,
        narratives=_narratives(symbol),
        analogues=_analogues(symbol),
        relationships=_relationships(symbol, as_of),
        patterns=_patterns(),
        model_registry=_model_registry(as_of),
        provider_health=(
            ProviderHealth(
                "Quant Terminal context",
                AvailabilityStatus.CACHED if terminal_context["available"] else AvailabilityStatus.UNAVAILABLE,
                terminal_context.get("as_of") or as_of,
                "OHLCV",
                detail=terminal_context["source"],
            ),
            ProviderHealth("Catalyst / news", AvailabilityStatus.SIMULATED, as_of, "EVENT", detail="Canonical deterministic fixture; no live provider connected"),
            ProviderHealth("Order book", AvailabilityStatus.SIMULATED, as_of, "L2", detail="Sequenced fixture messages; no venue entitlement asserted"),
            ProviderHealth("Forecast registry", AvailabilityStatus.RESEARCH_ONLY, as_of, "LEVEL 0", detail="Uncalibrated empirical baseline; not promotion-eligible"),
        ),
        audit=audit,
    )


def events_frame(snapshot: WorkspaceSnapshot) -> pd.DataFrame:
    return pd.DataFrame([event.to_record() for event in snapshot.events])


def forecasts_frame(snapshot: WorkspaceSnapshot) -> pd.DataFrame:
    return pd.DataFrame([forecast.to_record() for forecast in snapshot.forecasts])
