"""Public controller for the Company Intelligence package."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from .common import fmt_large_number
from .earnings import analyze_company_intelligence as _analyze_core
from .institutional_data import build_institutional_bundle
from .institutional_v2 import (
    build_what_changed,
    load_capital_allocation_intelligence,
    load_peer_intelligence,
)
from .institutional_ui import render_institutional_layer
from .management_transcripts import load_management_transcript_intelligence
from .management_ui import render_management_transcripts
from .ui_legacy import render_company_intelligence_mode as _render_core


def analyze_company_intelligence(ticker: str, latest_price: float) -> dict:
    """Preserve the existing analysis contract.

    Institutional data are loaded lazily in the Company Intelligence workspace rather
    than in analyze_ticker(), so Snapshot/Backtest/other modes do not pay the cost of
    ownership/SEC/segment requests on every run.
    """
    return _analyze_core(ticker, latest_price)


def _ensure_institutional(company: dict, ticker: str) -> dict:
    if not isinstance(company, dict):
        company = {}

    current = company.get("institutional")
    if isinstance(current, dict) and current.get("symbol") == str(ticker).upper().strip():
        return company

    company["institutional"] = build_institutional_bundle(ticker, company)
    return company


def _raw_peer_symbols(inst: dict) -> tuple[str, ...]:
    peers = inst.get("peers", pd.DataFrame()) if isinstance(inst, dict) else pd.DataFrame()
    if not isinstance(peers, pd.DataFrame) or peers.empty:
        return tuple()
    col = next((c for c in ["symbol", "Symbol", "ticker", "Ticker"] if c in peers.columns), None)
    if col is None:
        return tuple()
    values = []
    for x in peers[col].dropna().astype(str):
        s = x.upper().strip().replace(".", "-")
        if s and s not in values:
            values.append(s)
    return tuple(values[:30])


def _ensure_workspace_intelligence(company: dict, ticker: str, workspace: str) -> dict:
    """Load expensive V2 layers only when the corresponding workspace needs them."""
    inst = company.setdefault("institutional", {})

    if workspace in {"Peers", "What Changed?"} and not isinstance(inst.get("peer_intelligence"), dict):
        inst["peer_intelligence"] = load_peer_intelligence(ticker, _raw_peer_symbols(inst))

    if workspace in {"Capital Allocation", "What Changed?"} and not isinstance(inst.get("capital_allocation"), dict):
        inst["capital_allocation"] = load_capital_allocation_intelligence(ticker, company)

    if workspace == "Management / Transcripts" and not isinstance(inst.get("management_transcripts"), dict):
        inst["management_transcripts"] = load_management_transcript_intelligence(ticker, company, max_quarters=4)

    if workspace == "What Changed?":
        # Pure synthesis over already-loaded V2 data. V3 Management / Transcripts remains
        # deliberately outside the frozen V2 thesis engine until historical validation.
        inst["what_changed"] = build_what_changed(company)

    return company


def render_company_intelligence_mode(ticker: str, analysis: dict):
    analysis = analysis if isinstance(analysis, dict) else {}
    company = analysis.get("company_analysis", {})

    workspace = st.radio(
        "Company Intelligence Workspace",
        [
            "Core Financials",
            "Institutional Overview",
            "Ownership & Positioning",
            "Business / Ecosystem",
            "Peers",
            "Capital Allocation",
            "Governance / Filings",
            "Management / Transcripts",
            "What Changed?",
        ],
        horizontal=True,
        key=f"company_intelligence_workspace_{ticker}",
    )

    if workspace == "Core Financials":
        _render_core(ticker, analysis)
        return

    with st.spinner("Loading institutional company intelligence…"):
        company = _ensure_institutional(company, ticker)
        company = _ensure_workspace_intelligence(company, ticker, workspace)
        analysis["company_analysis"] = company

    scores = company.get("scores", {}) if isinstance(company, dict) else {}
    profile = company.get("profile", {}) if isinstance(company, dict) else {}

    st.subheader(f"Company Intelligence — {ticker}")
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    overlay = inst.get("overlay", {}) if isinstance(inst, dict) else {}
    overlay_score = overlay.get("score") if isinstance(overlay, dict) else None
    overlay_coverage = overlay.get("coverage") if isinstance(overlay, dict) else None

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Core Fundamental Score", f"{scores.get('company_score', 50)}/100")
    c2.metric("Institutional Overlay", "N/A" if overlay_score is None else f"{float(overlay_score):.0f}/100")
    c3.metric("Dimension Coverage", "N/A" if overlay_coverage is None else f"{float(overlay_coverage):.0f}%")
    c4.metric("Growth", f"{scores.get('growth_score', 50)}/100")
    c5.metric("Forward", f"{scores.get('forward_score', 50)}/100")
    c6.metric("Market Cap", fmt_large_number(profile.get("market_cap")))
    st.caption("Core Fundamental Score is not blended with the Institutional Overlay. Overlay validation remains separate until historical signal validation is complete.")

    if workspace == "Management / Transcripts":
        render_management_transcripts(company)
    else:
        render_institutional_layer(ticker, company, workspace)
