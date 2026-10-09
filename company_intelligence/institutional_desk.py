"""High-density institutional shell for the Company Intelligence workspace.

The shell deliberately sits above the existing analytical engines.  It improves
navigation, hierarchy, provenance and failure handling without changing score
maths, provider contracts or research-governance boundaries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any, Mapping

import pandas as pd
import streamlit as st

from .common import fmt_large_number, safe_float
from .controller import (
    _ensure_institutional,
    _ensure_workspace_intelligence,
    _render_core,
    render_institutional_layer,
    render_management_transcripts,
)
from .mna_workbench import render_mna_workbench

try:  # The governed Research Lab is an optional live-workspace extension.
    from .research.ui import render_research_lab
except Exception:  # pragma: no cover - absent from the public base package.
    render_research_lab = None


DESK_VERSION = "CI DESK · 8.0 M&A"

_BASE_WORKSPACES = (
    "Core Financials",
    "Institutional Overview",
    "Ownership & Positioning",
    "Business / Ecosystem",
    "Peers",
    "M&A / Valuation",
    "Capital Allocation",
    "Governance / Filings",
    "Management / Transcripts",
)

_WORKSPACE_META = {
    "Core Financials": (
        "01 · Fundamentals",
        "Financial engine",
        "Statements, estimates, earnings quality, valuation and analyst consensus.",
    ),
    "Institutional Overview": (
        "02 · Decision room",
        "Institutional overview",
        "Evidence-weighted ownership, concentration, ecosystem and source coverage.",
    ),
    "Ownership & Positioning": (
        "03 · Holders",
        "Ownership & positioning",
        "13F context, holder breadth, concentration and informative insider activity.",
    ),
    "Business / Ecosystem": (
        "04 · Operating map",
        "Business & ecosystem",
        "Segments, geographies, customer dependencies and supplier relationships.",
    ),
    "Peers": (
        "05 · Relative view",
        "Peer intelligence",
        "Comparable-company context with explicit coverage and comparability limits.",
    ),
    "M&A / Valuation": (
        "06 · Transaction lab",
        "M&A & valuation workbench",
        "DES, relative value, financial analysis, governed deal scenarios and sourced intelligence.",
    ),
    "Capital Allocation": (
        "07 · Stewardship",
        "Capital allocation",
        "Cash deployment, dilution, distributions and balance-sheet discipline.",
    ),
    "Governance / Filings": (
        "08 · Primary evidence",
        "Governance & filings",
        "Filings, governance facts and auditable source-linked disclosures.",
    ),
    "Management / Transcripts": (
        "09 · Management signal",
        "Management & transcripts",
        "Guidance, language shifts, commitments and transcript evidence.",
    ),
    "Research Lab": (
        "10 · Governed research",
        "Research lab",
        "Falsifiable hypotheses, controlled evidence and research-only closure state.",
    ),
    "What Changed?": (
        "11 · Delta monitor",
        "What changed?",
        "A synthesis of material changes across the loaded institutional evidence.",
    ),
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _scalar(mapping: Mapping[str, Any], *keys: str) -> Any:
    """Return the first usable scalar without evaluating pandas objects as booleans."""
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, (pd.DataFrame, pd.Series)):
            continue
        if isinstance(value, (list, tuple, dict, set)) and not value:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return not value.empty
    if isinstance(value, (Mapping, list, tuple, set, str)):
        return len(value) > 0
    return True


def _score(value: Any) -> float | None:
    value = safe_float(value)
    if value is None or pd.isna(value):
        return None
    return max(0.0, min(100.0, float(value)))


def _short_text(value: Any, limit: int = 390) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _format_price(value: Any, currency: str) -> str:
    value = safe_float(value)
    if value is None or pd.isna(value):
        return "N/A"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency.upper(), "")
    return f"{symbol}{value:,.2f}" if symbol else f"{value:,.2f} {currency}".strip()


def _timestamp_label(value: Any) -> str:
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    numeric = safe_float(value)
    if numeric is not None and numeric > 1_000_000_000:
        try:
            return datetime.fromtimestamp(numeric, tz=timezone.utc).strftime("%d %b %Y · %H:%M UTC")
        except (OverflowError, OSError, ValueError):
            pass
    if isinstance(value, str) and value.strip():
        return _short_text(value, 40)
    return "Snapshot de session"


def _coverage(company: Mapping[str, Any]) -> tuple[float | None, str]:
    inst = _mapping(company.get("institutional"))
    overlay = _mapping(inst.get("overlay"))
    explicit = _score(overlay.get("coverage"))
    if explicit is not None:
        return explicit, "Institutional dimensions"

    confidence = _mapping(inst.get("confidence_detail"))
    explicit = _score(confidence.get("coverage"))
    if explicit is not None:
        return explicit, "Institutional sources"

    blocks = ("profile", "growth", "profitability", "valuation", "balance", "analysts", "forward", "sentiment")
    available = sum(bool(_mapping(company.get(block))) for block in blocks)
    if not available:
        return None, "Coverage unavailable"
    return 100.0 * available / len(blocks), "Core analytical blocks"


def build_desk_context(ticker: str, analysis: Mapping[str, Any]) -> dict[str, Any]:
    """Build display-only context from the existing analysis contract."""
    analysis = _mapping(analysis)
    company = _mapping(analysis.get("company_analysis"))
    profile = _mapping(company.get("profile"))
    raw = _mapping(company.get("raw_data"))
    info = _mapping(raw.get("info"))
    scores = _mapping(company.get("scores"))
    analysts = _mapping(company.get("analysts"))
    forward = _mapping(company.get("forward"))
    inst = _mapping(company.get("institutional"))
    overlay = _mapping(inst.get("overlay"))

    currency = str(_scalar(profile, "currency") or _scalar(info, "currency", "financialCurrency") or "USD")
    price = (
        _scalar(analysis, "latest_price", "price", "current_price")
        or _scalar(analysts, "current_price", "price")
        or _scalar(info, "currentPrice", "regularMarketPrice", "previousClose")
    )
    coverage, coverage_basis = _coverage(company)
    company_score = _score(scores.get("company_score"))
    if company_score is None:
        posture = "Evidence pending"
        posture_tone = "neutral"
    elif company_score >= 75:
        posture = "Constructive quality"
        posture_tone = "positive"
    elif company_score >= 55:
        posture = "Selective / balanced"
        posture_tone = "watch"
    else:
        posture = "Risk-led review"
        posture_tone = "negative"

    target_upside = safe_float(
        _scalar(forward, "target_mean_upside", "mean_target_upside", "target_upside")
        or _scalar(analysts, "upside_mean", "target_mean_upside", "mean_target_upside", "target_upside")
    )
    if target_upside is not None and abs(target_upside) <= 2.5:
        target_upside *= 100.0

    provider_flags = {
        "Core market": _present(info),
        "FMP estimates": _present(_mapping(raw.get("fmp")).get("enabled")),
        "SEC / filings": _present(raw.get("sec")) or _present(inst.get("filings")),
        "Institutional": _present(inst),
        "Transcripts": _present(inst.get("management_transcripts")),
    }

    return {
        "ticker": str(ticker or "N/A").upper().strip(),
        "company": company,
        "name": str(_scalar(profile, "name", "long_name", "longName", "shortName") or _scalar(info, "longName", "shortName") or ticker),
        "sector": str(_scalar(company, "sector") or _scalar(profile, "sector", "Sector") or _scalar(info, "sector") or "Sector not reported"),
        "industry": str(_scalar(company, "industry") or _scalar(profile, "industry", "Industry") or _scalar(info, "industry") or "Industry not reported"),
        "currency": currency,
        "price": price,
        "market_cap": _scalar(profile, "market_cap", "marketCap") or _scalar(info, "marketCap"),
        "as_of": _timestamp_label(_scalar(info, "regularMarketTime") or _scalar(company, "as_of", "updated_at") or _scalar(analysis, "as_of")),
        "scores": scores,
        "company_score": company_score,
        "overlay_score": _score(overlay.get("score")),
        "coverage": coverage,
        "coverage_basis": coverage_basis,
        "target_upside": target_upside,
        "posture": posture,
        "posture_tone": posture_tone,
        "diagnosis": _short_text(company.get("diagnosis") or "The evidence bundle is still loading; no thesis is asserted without data."),
        "provider_flags": provider_flags,
    }


def _inject_desk_css() -> None:
    st.markdown(
        """
<style>
:root{
  --ci-ink:#edf4fb;--ci-muted:#8fa5b8;--ci-line:rgba(128,164,191,.20);
  --ci-panel:#07131f;--ci-panel-2:#0a1b29;--ci-cyan:#63d7e7;--ci-gold:#e4bf6b;
  --ci-green:#68d69a;--ci-red:#ff7c80;--ci-orange:#f0a762;
}
.ci-desk-root{height:0;overflow:hidden}
.ci-hero{position:relative;overflow:hidden;margin:2px 0 14px;padding:25px 28px 23px;border:1px solid rgba(118,163,195,.28);border-radius:20px;background:radial-gradient(circle at 87% 14%,rgba(47,183,201,.15),transparent 29%),radial-gradient(circle at 8% 100%,rgba(228,191,107,.10),transparent 28%),linear-gradient(135deg,#0b2030 0%,#06121d 48%,#071522 100%);box-shadow:0 24px 60px rgba(0,0,0,.28)}
.ci-hero:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.18;background-image:linear-gradient(rgba(120,170,200,.12) 1px,transparent 1px),linear-gradient(90deg,rgba(120,170,200,.12) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(90deg,transparent,#000 30%,#000)}
.ci-hero-top,.ci-identity,.ci-kpis,.ci-decision-grid,.ci-workspace-head{position:relative;z-index:1}
.ci-hero-top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.ci-brand{font-size:.65rem;letter-spacing:.22em;text-transform:uppercase;font-weight:900;color:var(--ci-gold)}
.ci-live{display:inline-flex;align-items:center;gap:7px;padding:5px 10px;border:1px solid rgba(99,215,231,.28);border-radius:999px;background:rgba(99,215,231,.07);color:#b8edf4;font-size:.64rem;letter-spacing:.10em;text-transform:uppercase;font-weight:800}.ci-live i{width:7px;height:7px;border-radius:50%;background:var(--ci-green);box-shadow:0 0 0 5px rgba(104,214,154,.10);animation:ci-pulse 2.4s ease-out infinite}
.ci-identity{display:flex;align-items:flex-end;justify-content:space-between;gap:22px;margin-top:20px}.ci-name{font-family:Georgia,serif;font-size:clamp(2.0rem,4vw,3.35rem);line-height:1;color:#fff;font-weight:800;letter-spacing:-.035em}.ci-name span{color:var(--ci-cyan)}.ci-meta{margin-top:9px;color:#9bb0c2;font-size:.79rem;letter-spacing:.02em}.ci-posture{text-align:right}.ci-posture .label{font-size:.58rem;text-transform:uppercase;letter-spacing:.18em;color:#7890a4;font-weight:900}.ci-posture .value{margin-top:5px;font-family:Georgia,serif;color:#eff7fb;font-size:1.26rem;font-weight:800}.ci-posture.positive .value{color:var(--ci-green)}.ci-posture.watch .value{color:var(--ci-gold)}.ci-posture.negative .value{color:var(--ci-red)}
.ci-kpis{display:grid;grid-template-columns:1.1fr 1fr 1fr 1fr 1.35fr;gap:9px;margin-top:21px}.ci-kpi{min-height:79px;padding:12px 14px;border:1px solid var(--ci-line);border-radius:13px;background:linear-gradient(180deg,rgba(14,35,51,.78),rgba(7,20,31,.72));backdrop-filter:blur(8px)}.ci-kpi .k{font-size:.57rem;text-transform:uppercase;letter-spacing:.16em;color:#8096a9;font-weight:900}.ci-kpi .v{font-family:Georgia,serif;color:#f5f8fb;font-size:1.35rem;font-weight:800;margin-top:5px}.ci-kpi .s{font-size:.64rem;color:#7f97aa;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ci-decision-grid{display:grid;grid-template-columns:1.35fr 1fr 1fr;gap:10px;margin:10px 0 18px}.ci-brief{padding:16px 17px;border:1px solid var(--ci-line);border-radius:15px;background:linear-gradient(145deg,rgba(10,29,43,.88),rgba(5,16,26,.92));min-height:116px}.ci-brief .eyebrow{font-size:.57rem;text-transform:uppercase;letter-spacing:.17em;color:var(--ci-gold);font-weight:900}.ci-brief h4{font-family:Georgia,serif;font-size:1.02rem;color:#eef5fa;margin:7px 0 6px}.ci-brief p{font-size:.73rem;line-height:1.55;color:#9db0c0;margin:0}.ci-brief .signal{color:var(--ci-cyan)}
.ci-workspace-head{display:flex;align-items:flex-end;justify-content:space-between;gap:15px;margin:22px 0 10px;padding:0 2px 10px;border-bottom:1px solid var(--ci-line)}.ci-workspace-head .eyebrow{font-size:.59rem;text-transform:uppercase;letter-spacing:.18em;color:var(--ci-gold);font-weight:900}.ci-workspace-head .title{font-family:Georgia,serif;font-size:1.55rem;color:#f3f6f9;margin:5px 0 0;font-weight:800}.ci-workspace-head p{max-width:660px;color:#8ea3b4;font-size:.74rem;line-height:1.5;margin:0;text-align:right}
[class*="st-key-company_intelligence_workspace_"] div[role="radiogroup"]{display:flex;flex-wrap:wrap;gap:7px;padding:9px;border:1px solid var(--ci-line);border-radius:15px;background:rgba(5,16,26,.78)}
[class*="st-key-company_intelligence_workspace_"] div[role="radiogroup"] label{min-height:38px;padding:6px 10px!important;border:1px solid transparent;border-radius:10px;background:rgba(14,31,45,.60);transition:transform .16s ease,border-color .16s ease,background .16s ease}
[class*="st-key-company_intelligence_workspace_"] div[role="radiogroup"] label:hover{transform:translateY(-1px);border-color:rgba(99,215,231,.35);background:rgba(22,48,65,.8)}
[class*="st-key-company_intelligence_workspace_"] div[role="radiogroup"] label:has(input:checked){border-color:rgba(99,215,231,.52);background:linear-gradient(135deg,rgba(44,148,166,.20),rgba(18,52,68,.72));box-shadow:inset 0 0 20px rgba(80,198,214,.06)}
div[data-testid="stMetric"]{padding:13px 14px;border:1px solid var(--ci-line);border-radius:12px;background:linear-gradient(180deg,rgba(10,27,41,.80),rgba(6,17,27,.88));box-shadow:none}div[data-testid="stMetricLabel"]{color:#8ba1b4}div[data-testid="stMetricValue"]{font-family:Georgia,serif;color:#f2f6fa}
div[data-testid="stDataFrame"],div[data-testid="stPlotlyChart"]{padding:6px;border:1px solid rgba(116,151,178,.18);border-radius:13px;background:rgba(5,15,24,.55)}
div[data-testid="stExpander"]{border:1px solid var(--ci-line);border-radius:12px;background:rgba(6,18,28,.58)}
@keyframes ci-pulse{0%{box-shadow:0 0 0 0 rgba(104,214,154,.36)}70%{box-shadow:0 0 0 8px rgba(104,214,154,0)}100%{box-shadow:0 0 0 0 rgba(104,214,154,0)}}
@media (prefers-reduced-motion:reduce){.ci-live i{animation:none}[class*="st-key-company_intelligence_workspace_"] div[role="radiogroup"] label{transition:none}}
@media(max-width:900px){.ci-hero{padding:20px}.ci-identity{align-items:flex-start;flex-direction:column}.ci-posture{text-align:left}.ci-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.ci-decision-grid{grid-template-columns:1fr}.ci-workspace-head{align-items:flex-start;flex-direction:column}.ci-workspace-head p{text-align:left}.ci-name{font-size:2.15rem}}
</style>
<div id="ci-v7-root" class="ci-desk-root"></div>
""",
        unsafe_allow_html=True,
    )


def _hero(ctx: Mapping[str, Any]) -> None:
    scores = _mapping(ctx.get("scores"))
    coverage = ctx.get("coverage")
    coverage_text = "N/A" if coverage is None else f"{coverage:.0f}%"
    overlay = ctx.get("overlay_score")
    overlay_text = "N/A" if overlay is None else f"{overlay:.0f}<small>/100</small>"
    company_score = ctx.get("company_score")
    company_score_text = "N/A" if company_score is None else f"{company_score:.0f}<small>/100</small>"
    target = ctx.get("target_upside")
    target_text = "N/A" if target is None else f"{target:+.1f}%"
    st.markdown(
        f"""
<section class="ci-hero">
  <div class="ci-hero-top"><div class="ci-brand">{DESK_VERSION} · single-name research</div><div class="ci-live"><i></i> evidence workspace · research only</div></div>
  <div class="ci-identity">
    <div><div class="ci-name">{escape(str(ctx['name']))} <span>{escape(str(ctx['ticker']))}</span></div><div class="ci-meta">{escape(str(ctx['sector']))} · {escape(str(ctx['industry']))} · As of {escape(str(ctx['as_of']))}</div></div>
    <div class="ci-posture {escape(str(ctx['posture_tone']))}"><div class="label">Derived research posture</div><div class="value">{escape(str(ctx['posture']))}</div></div>
  </div>
  <div class="ci-kpis">
    <div class="ci-kpi"><div class="k">Last price</div><div class="v">{escape(_format_price(ctx.get('price'), str(ctx.get('currency') or '')))}</div><div class="s">Observed market context</div></div>
    <div class="ci-kpi"><div class="k">Fundamental</div><div class="v">{company_score_text}</div><div class="s">Core composite · unchanged</div></div>
    <div class="ci-kpi"><div class="k">Institutional</div><div class="v">{overlay_text}</div><div class="s">Separate overlay</div></div>
    <div class="ci-kpi"><div class="k">Coverage</div><div class="v">{coverage_text}</div><div class="s">{escape(str(ctx.get('coverage_basis')))}</div></div>
    <div class="ci-kpi"><div class="k">Market cap / target</div><div class="v">{escape(fmt_large_number(ctx.get('market_cap')))}</div><div class="s">Mean target delta {escape(target_text)}</div></div>
  </div>
</section>
""",
        unsafe_allow_html=True,
    )

    forward = _score(scores.get("forward_score"))
    valuation = _score(scores.get("valuation_score"))
    quality = _score(scores.get("profitability_score"))
    catalyst = "Forward evidence unavailable."
    if forward is not None:
        catalyst = f"Forward score {forward:.0f}/100; validate the underlying estimates and revision breadth before relying on it."
    coverage = ctx.get("coverage")
    if coverage is None:
        risk = "Coverage is unavailable; no conclusion should be promoted from this snapshot."
    elif ctx.get("overlay_score") is None:
        risk = "The institutional overlay is not loaded in the core view; missing evidence remains N/A."
    elif coverage < 80:
        risk = f"Only {coverage:.0f}% of the expected evidence is covered; treat the posture as provisional."
    elif valuation is not None and valuation < 55:
        risk = f"Valuation support is weak ({valuation:.0f}/100); scenario sensitivity deserves priority."
    elif quality is not None and quality < 55:
        risk = f"Profitability quality is fragile ({quality:.0f}/100); inspect margins and cash conversion."
    else:
        risk = "Score dispersion, source freshness and downside scenarios still require human validation."

    st.markdown(
        f"""
<section class="ci-decision-grid">
  <article class="ci-brief"><div class="eyebrow">Decision brief · normalized evidence</div><h4>Current thesis pulse</h4><p>{escape(str(ctx.get('diagnosis')))}</p></article>
  <article class="ci-brief"><div class="eyebrow">Catalyst monitor</div><h4 class="signal">Forward confirmation</h4><p>{escape(catalyst)}</p></article>
  <article class="ci-brief"><div class="eyebrow">Risk radar</div><h4>What can break the view</h4><p>{escape(risk)}</p></article>
</section>
""",
        unsafe_allow_html=True,
    )


def _provenance_panel(ctx: Mapping[str, Any]) -> None:
    rows = [
        {"Evidence layer": label, "State": "AVAILABLE" if available else "NOT OBSERVED", "Policy": "Used when present; never imputed"}
        for label, available in _mapping(ctx.get("provider_flags")).items()
    ]
    with st.expander("Data lineage, coverage & governance", expanded=False):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(
            "Scores remain analytical research outputs. Missing coverage is kept unavailable; "
            "the institutional overlay is not blended into the core composite and order transmission stays disconnected."
        )


def _workspace_header(workspace: str) -> None:
    eyebrow, title, description = _WORKSPACE_META[workspace]
    st.markdown(
        f"""
<div class="ci-workspace-head"><div><div class="eyebrow">{escape(eyebrow)}</div><div class="title" role="heading" aria-level="2" aria-label="{escape(title)}">{escape(title)}</div></div><p>{escape(description)}</p></div>
""",
        unsafe_allow_html=True,
    )


def _render_degraded(workspace: str, error: Exception) -> None:
    st.error(f"{workspace} is temporarily degraded. The rest of the Company Intelligence desk remains available.")
    with st.expander("Technical diagnostic", expanded=False):
        st.code(f"{type(error).__name__}: {error}", language="text")


def _workspace_options() -> list[str]:
    options = list(_BASE_WORKSPACES)
    if callable(render_research_lab):
        options.append("Research Lab")
    options.append("What Changed?")
    return options


def render_company_intelligence_mode(ticker: str, analysis: dict) -> None:
    """Render the V8 institutional desk while preserving every existing engine."""
    analysis = analysis if isinstance(analysis, dict) else {}
    ticker = str(ticker or "N/A").upper().strip()
    _inject_desk_css()

    options = _workspace_options()
    workspace_key = f"company_intelligence_workspace_{ticker}"
    requested_workspace = st.session_state.get(workspace_key, options[0])
    if requested_workspace not in options:
        requested_workspace = options[0]

    company = analysis.get("company_analysis", {})
    prefetch_error: Exception | None = None
    if requested_workspace != "Core Financials":
        try:
            with st.spinner("Loading governed institutional evidence…"):
                company = _ensure_institutional(company, ticker)
                company = _ensure_workspace_intelligence(company, ticker, requested_workspace)
                analysis["company_analysis"] = company
        except Exception as error:  # Keep the shell and other workspaces available.
            prefetch_error = error

    context = build_desk_context(ticker, analysis)
    _hero(context)
    _provenance_panel(context)

    workspace = st.radio(
        "Company Intelligence Workspace",
        options,
        horizontal=True,
        key=workspace_key,
        label_visibility="collapsed",
    )
    _workspace_header(workspace)

    if workspace == "Core Financials":
        try:
            _render_core(ticker, analysis)
        except Exception as error:  # A local engine must not take down the full desk.
            _render_degraded(workspace, error)
        return

    if prefetch_error is not None:
        _render_degraded(workspace, prefetch_error)
        return

    company = analysis.get("company_analysis", company)
    try:
        if workspace == "Management / Transcripts":
            render_management_transcripts(company)
        elif workspace == "M&A / Valuation":
            render_mna_workbench(ticker, analysis)
        elif workspace == "Research Lab" and callable(render_research_lab):
            render_research_lab(company, ticker)
        else:
            render_institutional_layer(ticker, company, workspace)
    except Exception as error:
        _render_degraded(workspace, error)


__all__ = ["DESK_VERSION", "build_desk_context", "render_company_intelligence_mode"]
