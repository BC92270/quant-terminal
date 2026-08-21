from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import html
import json
import re
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from .config import AgentConfig, ConfigStore, OrganizationConfig, ProviderSettings
from .exports import decision_packet_json, decision_packet_markdown
from .interactive_graph import render_interactive_workflow
from .orchestrator import CommitteeOrchestrator
from .portfolio import PortfolioMandate, review_portfolio
from .quality import evaluate_committee, score_agent_report
from .schemas import CommitteeRun, NodeStatus
from .state import AuditStore
from .strategy import StrategySpec, run_strategy_backtest
from .tools import QuantContext, build_default_registry
from .visualization import TOOL_LABELS, workflow_graph_html


PROVIDERS = ["OpenAI", "Anthropic", "Google Gemini", "OpenRouter", "Mistral", "Groq", "Custom OpenAI-compatible", "Deterministic"]
DEFAULT_MODELS = {
    "OpenAI": "gpt-5.2",
    "Anthropic": "claude-sonnet-4-5",
    "Google Gemini": "gemini-2.5-pro",
    "OpenRouter": "openai/gpt-5.2",
    "Mistral": "mistral-large-latest",
    "Groq": "llama-3.3-70b-versatile",
    "Custom OpenAI-compatible": "your-model",
    "Deterministic": "deterministic",
}
VIEWS = ["Committee", "Workflow", "Strategy", "Portfolio", "Evidence", "Agents", "Settings"]
MISSION_PRESETS = {
    "Custom mission": "",
    "Security underwriting": "Souscris cet actif comme un hedge fund fondamental et quantitatif. Construis bull/base/bear, variant perception, valorisation, catalyseurs, risques, sizing et critères d’invalidation.",
    "Strategy validation": "Audite cette stratégie de bout en bout. Vérifie la règle, le look-ahead, les coûts, l’out-of-sample, la stabilité, la capacité, le risque portefeuille et décide de son prochain stage de recherche.",
    "Portfolio CRO review": "Agis comme CIO et CRO. Diagnostique les concentrations, facteurs, contributions au risque, liquidité, scénarios, violations de mandat et propose un rééquilibrage conditionnel financé.",
    "Hedge architecture": "Conçois une couverture robuste pour le risque dominant. Compare cash, futures et options, puis détaille coût, carry, convexité, Greeks, liquidité, efficacité par scénario et conditions de retrait.",
    "Macro war-game": "Construis un war-game macro bull/base/bear avec chocs de croissance, inflation, taux, liquidité et géopolitique. Traduis chaque scénario en impacts cross-asset et actions portefeuille.",
    "Red-team decision": "Contredis la thèse actuelle. Cherche les données manquantes, hypothèses fragiles, risques de foule, chemins de perte et raisons précises pour lesquelles le fonds devrait s’abstenir.",
}


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --q-bg: #05090f;
          --q-panel: #0a111b;
          --q-panel-2: #0d1723;
          --q-line: rgba(137, 173, 203, .16);
          --q-muted: #7f91a3;
          --q-text: #eaf1f7;
          --q-accent: #39d0bd;
          --q-blue: #5ba8ff;
          --q-warn: #f3b85b;
          --q-bad: #ff6b75;
        }
        [data-testid="stAppViewContainer"], [data-testid="stMain"] { background: var(--q-bg); }
        [data-testid="stAppViewContainer"]:before { content:""; position:fixed; inset:0; pointer-events:none; z-index:0;
          background:radial-gradient(circle at 18% 2%,rgba(21,119,156,.12),transparent 31%),radial-gradient(circle at 85% 18%,rgba(57,208,189,.07),transparent 28%);
        }
        [data-testid="stMainBlockContainer"] { max-width: 1500px; padding: 1rem 1.35rem 4rem; }
        [data-testid="stHeader"], [data-testid="stSidebar"] { display: none; }
        .qai-shell { color: var(--q-text); font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
        .qai-topbar {
          display:flex; align-items:center; justify-content:space-between; gap:18px; position:relative; overflow:hidden;
          border:1px solid var(--q-line); border-radius:16px; padding:13px 16px; margin-bottom:14px;
          background:linear-gradient(110deg,rgba(8,18,29,.96),rgba(7,14,23,.88)); box-shadow:0 16px 55px rgba(0,0,0,.22),inset 0 1px rgba(145,231,255,.05);
        }
        .qai-topbar:after { content:""; position:absolute; top:0; bottom:0; width:90px; left:-110px; background:linear-gradient(90deg,transparent,rgba(80,222,255,.07),transparent); animation:qaiScan 7s linear infinite; }
        .qai-brand { display:flex; align-items:center; gap:12px; }
        .qai-mark { width:46px; height:46px; border:1px solid rgba(57,208,189,.48); border-radius:50%; position:relative;
          display:grid; place-items:center; color:var(--q-accent); font:700 11px ui-monospace,monospace; background:rgba(57,208,189,.05); box-shadow:0 0 26px rgba(57,208,189,.12),inset 0 0 18px rgba(57,208,189,.08); }
        .qai-mark:before { content:""; position:absolute; inset:5px; border:1px dashed rgba(57,208,189,.65); border-radius:50%; animation:qaiSpin 8s linear infinite; }
        .qai-mark:after { content:""; width:5px; height:5px; border-radius:50%; background:var(--q-accent); box-shadow:0 0 12px var(--q-accent); }
        .qai-eyebrow { color:var(--q-accent); font:600 10px/1.2 ui-monospace, SFMono-Regular, monospace; letter-spacing:.16em; }
        .qai-title { color:var(--q-text); font-size:20px; font-weight:680; letter-spacing:-.03em; margin-top:2px; }
        .qai-title span { color:#60758a; font-weight:520; }
        .qai-statuses { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:7px; }
        .qai-chip { padding:6px 9px; border:1px solid var(--q-line); border-radius:7px; color:var(--q-muted);
          font:600 10px/1 ui-monospace, SFMono-Regular, monospace; letter-spacing:.05em; }
        .qai-chip.live { color:var(--q-accent); border-color:rgba(57,208,189,.28); background:rgba(57,208,189,.05); }
        .qai-chip.live:before { content:""; display:inline-block; width:5px; height:5px; border-radius:50%; background:var(--q-accent); margin-right:6px; box-shadow:0 0 10px var(--q-accent); animation:qaiPulse 1.8s ease-in-out infinite; }
        .qai-panel { background:linear-gradient(180deg, rgba(13,23,35,.96), rgba(8,14,23,.96));
          border:1px solid var(--q-line); border-radius:14px; padding:18px; }
        .qai-composer { border:1px solid rgba(91,168,255,.25); box-shadow:0 18px 70px rgba(0,0,0,.22); }
        .qai-mission-bar { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:11px 0 14px; }
        .qai-mission-cell { border:1px solid var(--q-line); border-radius:9px; padding:9px 10px; background:#07101a; }
        .qai-mission-cell small { display:block; color:#546b7f; font:650 7px ui-monospace,monospace; letter-spacing:1px; }
        .qai-mission-cell b { display:block; color:#bcd0df; font:650 10px ui-monospace,monospace; margin-top:5px; }
        .qai-kicker { color:var(--q-muted); font:600 10px/1.2 ui-monospace, SFMono-Regular, monospace;
          letter-spacing:.13em; text-transform:uppercase; margin-bottom:8px; }
        .qai-question-title { font-size:24px; line-height:1.2; letter-spacing:-.035em; margin:0 0 5px; color:var(--q-text); }
        .qai-sub { color:var(--q-muted); font-size:13px; line-height:1.55; }
        .qai-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:10px; margin:14px 0; }
        .qai-metric { background:rgba(255,255,255,.018); border:1px solid var(--q-line); border-radius:11px; padding:13px; min-height:78px; }
        .qai-metric-label { color:var(--q-muted); font:600 9px/1.2 ui-monospace, monospace; letter-spacing:.11em; text-transform:uppercase; }
        .qai-metric-value { color:var(--q-text); font-size:20px; font-weight:650; margin-top:8px; }
        .qai-metric-value.good { color:var(--q-accent); } .qai-metric-value.bad { color:var(--q-bad); }
        .qai-decision { padding:20px; border-left:3px solid var(--q-accent); margin:12px 0; }
        .qai-decision.watch { border-left-color:var(--q-warn); } .qai-decision.bad { border-left-color:var(--q-bad); }
        .qai-decision-label { font:700 11px/1 ui-monospace,monospace; color:var(--q-accent); letter-spacing:.14em; }
        .qai-decision.watch .qai-decision-label { color:var(--q-warn); }
        .qai-decision.bad .qai-decision-label { color:var(--q-bad); }
        .qai-decision-headline { color:var(--q-text); font-size:25px; font-weight:650; letter-spacing:-.035em; margin:9px 0; }
        .qai-list { margin:8px 0 0; padding:0; list-style:none; }
        .qai-list li { color:#c9d4de; font-size:13px; line-height:1.5; padding:7px 0 7px 18px; border-bottom:1px solid rgba(137,173,203,.08); position:relative; }
        .qai-list li:before { content:'›'; position:absolute; left:2px; color:var(--q-accent); }
        .qai-report-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
        .qai-agent-dot { width:7px;height:7px;border-radius:50%;background:var(--q-accent);display:inline-block;margin-right:7px;box-shadow:0 0 12px rgba(57,208,189,.5); }
        .qai-report-meta { color:var(--q-muted); font:600 10px/1.2 ui-monospace, monospace; }
        .qai-warning { background:rgba(243,184,91,.06); border:1px solid rgba(243,184,91,.22); border-radius:10px; padding:11px 13px; color:#d9c49c; font-size:12px; }
        .qai-empty { text-align:center; padding:48px 20px; color:var(--q-muted); border:1px dashed var(--q-line); border-radius:14px; }
        .qai-section-title { color:var(--q-text);font-size:15px;font-weight:650;margin:0 0 3px; }
        .qai-agent-card { border:1px solid var(--q-line); border-radius:11px; padding:12px; background:rgba(255,255,255,.015); margin-bottom:8px; }
        .qai-integrity { display:grid; grid-template-columns:140px 1fr; gap:16px; align-items:center; border:1px solid rgba(57,208,189,.18); border-radius:13px; padding:14px; background:linear-gradient(100deg,rgba(57,208,189,.045),rgba(91,168,255,.025)); margin:10px 0; }
        .qai-integrity-score { font:750 32px ui-monospace,monospace; color:var(--q-accent); letter-spacing:-2px; }
        .qai-integrity-score small { font-size:10px; color:#678095; letter-spacing:1px; }
        .qai-bars { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; }
        .qai-bar { color:#657d91; font:650 7px ui-monospace,monospace; letter-spacing:.7px; }
        .qai-bar i { display:block; height:3px; margin-top:5px; border-radius:2px; background:linear-gradient(90deg,var(--q-accent) var(--score),#162536 var(--score)); }
        @keyframes qaiSpin { to { transform:rotate(360deg); } }
        @keyframes qaiPulse { 50% { opacity:.35; transform:scale(.8); } }
        @keyframes qaiScan { to { left:calc(100% + 120px); } }
        div[data-testid="stRadio"] > div { gap:2px; padding:3px; border:1px solid var(--q-line); border-radius:10px; background:#070c13; flex-wrap:nowrap !important; overflow-x:auto; }
        div[data-testid="stRadio"] [role="radiogroup"] { display:flex !important; flex-wrap:nowrap !important; gap:2px !important; overflow-x:auto; }
        div[data-testid="stRadio"] label { padding:5px 7px !important; border-radius:7px; white-space:nowrap !important; }
        div[data-testid="stTextArea"] textarea, div[data-testid="stTextInput"] input,
        div[data-testid="stSelectbox"] > div > div, div[data-testid="stMultiSelect"] > div > div {
          background:#080f18 !important; border-color:var(--q-line) !important; color:var(--q-text) !important; border-radius:9px !important;
        }
        .stButton > button { border-radius:9px; border:1px solid var(--q-line); background:#0b1420; color:#dfeaf2; }
        .stButton > button[kind="primary"] { background:var(--q-accent); color:#04110f; border-color:var(--q-accent); font-weight:700; }
        div[data-testid="stExpander"] { border:1px solid var(--q-line); background:#080f17; border-radius:11px; }
        div[data-testid="stTabs"] button { font-size:12px; }
        @media (max-width: 900px) { .qai-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .qai-statuses { display:none; } .qai-mission-bar{grid-template-columns:repeat(2,minmax(0,1fr))}.qai-integrity{grid-template-columns:1fr}.qai-bars{grid-template-columns:1fr 1fr} }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _escape(value: Any) -> str:
    return html.escape(str(value or ""))


def _list(items: list[str]) -> str:
    clean = [item for item in items if str(item).strip()]
    if not clean:
        return '<div class="qai-sub">No material item reported.</div>'
    return '<ul class="qai-list">' + "".join(f"<li>{_escape(item)}</li>" for item in clean) + "</ul>"


def _run_from_state() -> CommitteeRun | None:
    value = st.session_state.get("qai_current_run")
    return value if isinstance(value, CommitteeRun) else None


def _session_snapshot() -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for key, value in st.session_state.items():
        lower = str(key).lower()
        if lower.startswith("qai_") or any(token in lower for token in ("api_key", "password", "secret", "token")):
            continue
        if callable(value):
            continue
        snapshot[str(key)] = value
    return snapshot


def _organization() -> OrganizationConfig:
    value = st.session_state.get("qai_organization")
    if isinstance(value, OrganizationConfig):
        return value
    value = ConfigStore().load()
    st.session_state["qai_organization"] = value
    return value


def _provider_settings() -> ProviderSettings:
    provider = str(st.session_state.get("qai_provider") or "OpenAI")
    return ProviderSettings(
        provider=provider,
        model=str(st.session_state.get("qai_model") or DEFAULT_MODELS.get(provider, "your-model")),
        base_url=str(st.session_state.get("qai_base_url") or ""),
        temperature=float(st.session_state.get("qai_temperature") or 0.15),
        timeout_seconds=int(st.session_state.get("qai_timeout") or 90),
        max_output_tokens=int(st.session_state.get("qai_max_tokens") or 2200),
    )


def _header(ticker: str, organization: OrganizationConfig) -> None:
    connected = bool(str(st.session_state.get("qai_api_key") or "").strip()) and str(st.session_state.get("qai_provider")) != "Deterministic"
    model = str(st.session_state.get("qai_model") or DEFAULT_MODELS["OpenAI"])
    enabled = sum(agent.enabled for agent in organization.agents)
    status = "MODEL CONNECTED" if connected else "DETERMINISTIC CORE"
    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    st.markdown(
        f"""
        <div class="qai-shell qai-topbar">
          <div class="qai-brand">
            <div class="qai-mark">AI</div>
            <div><div class="qai-eyebrow">JARVIS QUANT AI / NEURAL INVESTMENT OS</div><div class="qai-title">CIO Decision Room <span>· Fund Intelligence Core</span></div></div>
          </div>
          <div class="qai-statuses">
            <span class="qai-chip live">{status}</span><span class="qai-chip">{_escape(ticker)}</span>
            <span class="qai-chip">{_escape(model)}</span><span class="qai-chip">{enabled} DESKS</span><span class="qai-chip">{now}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_navigation() -> str:
    left, nav = st.columns([0.48, 9.52], vertical_alignment="center")
    with left:
        if st.button("←", key="qai_back", help="Return to Command Center", width="content"):
            st.session_state["quant_ai_open"] = False
            st.session_state["asset_class_selected"] = False
            st.rerun()
    with nav:
        view = st.radio(
            "Quant AI navigation",
            VIEWS,
            index=VIEWS.index(st.session_state.get("qai_view", "Committee")) if st.session_state.get("qai_view", "Committee") in VIEWS else 0,
            horizontal=True,
            label_visibility="collapsed",
            key="qai_nav",
        )
    st.session_state["qai_view"] = view
    return str(view)


def _composer(ticker: str, price_data: pd.DataFrame, analysis: dict[str, Any], organization: OrganizationConfig) -> None:
    st.markdown(
        """
        <div class="qai-panel qai-composer">
          <div class="qai-kicker">Investment question</div>
          <div class="qai-question-title">What should the fund decide?</div>
          <div class="qai-sub">The CIO selects relevant sections, runs independent desks, exposes dissent and returns an auditable proposal.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    default_query = (
        f"Analyse {ticker} comme un comité d’investissement. Évalue la thèse, le régime, "
        "les risques, les tests déterminants, l’implémentation et les conditions d’invalidation."
    )
    preset = st.selectbox(
        "Mission protocol",
        list(MISSION_PRESETS),
        key="qai_mission_preset",
        help="Loads an institutional decision contract; every mission remains editable.",
    )
    if st.session_state.get("qai_last_mission_preset") != preset:
        template = MISSION_PRESETS.get(preset, "")
        if template:
            loaded = f"{template} Actif ou univers courant : {ticker}."
            st.session_state["qai_query_input"] = loaded
            st.session_state["qai_query"] = loaded
        st.session_state["qai_last_mission_preset"] = preset
    query = st.text_area(
        "Question au CIO",
        value=st.session_state.get("qai_query", default_query),
        height=112,
        placeholder="Ex: Faut-il initier, renforcer, couvrir ou éviter cette exposition — et pourquoi ?",
        key="qai_query_input",
        label_visibility="collapsed",
    )
    st.session_state["qai_query"] = query
    st.markdown(
        f"""
        <div class="qai-mission-bar qai-shell">
          <div class="qai-mission-cell"><small>MISSION PROTOCOL</small><b>{_escape(preset.upper())}</b></div>
          <div class="qai-mission-cell"><small>DECISION ASSET</small><b>{_escape(ticker)}</b></div>
          <div class="qai-mission-cell"><small>GOVERNANCE</small><b>RISK GATE + HUMAN IC</b></div>
          <div class="qai-mission-cell"><small>DATA CONTRACT</small><b>NO SILENT ASSUMPTIONS</b></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    meta_a, meta_b, meta_c, action = st.columns([2.1, 1.3, 1.3, 1.6], vertical_alignment="bottom")
    with meta_a:
        st.caption(f"CONTEXT · {ticker} · {len(price_data) if isinstance(price_data, pd.DataFrame) else 0} MARKET OBSERVATIONS")
    with meta_b:
        st.selectbox("Coverage", ["Auto-select", "Full committee"], key="qai_coverage")
    with meta_c:
        st.selectbox("Output", ["Decision memo", "Risk review", "Strategy design"], key="qai_output_type")
    with action:
        run_clicked = st.button("RUN COMMITTEE", type="primary", key="qai_run", width="stretch")

    if not str(st.session_state.get("qai_api_key") or "").strip():
        st.markdown(
            '<div class="qai-warning">No API key is stored. The committee remains operational with deterministic analytics; connect your own provider in Settings for independent model reasoning.</div>',
            unsafe_allow_html=True,
        )
    if not run_clicked:
        return
    if not query.strip():
        st.warning("Enter an investment question before running the committee.")
        return

    context = QuantContext(
        ticker=ticker,
        price_data=price_data if isinstance(price_data, pd.DataFrame) else pd.DataFrame(),
        analysis=analysis if isinstance(analysis, dict) else {},
        session_state=_session_snapshot(),
        portfolio=st.session_state.get("qai_portfolio_book") if isinstance(st.session_state.get("qai_portfolio_book"), dict) else {},
        strategy=st.session_state.get("qai_strategy_spec") if isinstance(st.session_state.get("qai_strategy_spec"), dict) else {},
        portfolio_mandate=st.session_state.get("qai_portfolio_mandate") if isinstance(st.session_state.get("qai_portfolio_mandate"), dict) else {},
    )
    progress = st.progress(0.0, text="Preparing committee…")
    graph_slot = st.empty()
    graph_slot.markdown(workflow_graph_html(organization, None, "Planning committee coverage"), unsafe_allow_html=True)

    def update(label: str, value: float) -> None:
        progress.progress(min(max(value, 0.0), 1.0), text=label)
        graph_slot.markdown(workflow_graph_html(organization, None, label), unsafe_allow_html=True)

    orchestrator = CommitteeOrchestrator(
        organization,
        _provider_settings(),
        str(st.session_state.get("qai_api_key") or ""),
        build_default_registry(),
    )
    run = orchestrator.run(query.strip(), context, progress=update)
    st.session_state["qai_current_run"] = run
    graph_slot.markdown(workflow_graph_html(organization, run), unsafe_allow_html=True)
    try:
        AuditStore().append(run)
    except OSError as exc:
        run.warnings.append(f"Audit persistence unavailable: {exc}")
    progress.empty()


def _decision_class(decision: str) -> str:
    if decision in {"BUY", "STRONG BUY"}:
        return ""
    if decision in {"WATCH", "HOLD", "HEDGE", "ABSTAIN"}:
        return "watch"
    return "bad"


def _brief(run: CommitteeRun) -> None:
    brief = run.brief
    complete = sum(result.status == NodeStatus.COMPLETE for result in run.tools.values())
    quality = evaluate_committee(run, _organization())
    st.markdown(
        f"""
        <div class="qai-grid qai-shell">
          <div class="qai-metric"><div class="qai-metric-label">CIO decision</div><div class="qai-metric-value {_decision_class(brief.decision)}">{_escape(brief.decision)}</div></div>
          <div class="qai-metric"><div class="qai-metric-label">Confidence</div><div class="qai-metric-value">{brief.confidence:.0%}</div></div>
          <div class="qai-metric"><div class="qai-metric-label">Evidence</div><div class="qai-metric-value">{complete}/{len(run.tools)}</div></div>
          <div class="qai-metric"><div class="qai-metric-label">Committee</div><div class="qai-metric-value">{len(run.reports)} desks</div></div>
          <div class="qai-metric"><div class="qai-metric-label">Decision integrity</div><div class="qai-metric-value good">{quality.score}/100</div></div>
        </div>
        <div class="qai-panel qai-decision {_decision_class(brief.decision)} qai-shell">
          <div class="qai-decision-label">{_escape(brief.decision)} · HUMAN APPROVAL REQUIRED</div>
          <div class="qai-decision-headline">{_escape(brief.headline)}</div>
          <div class="qai-sub">{_escape(brief.executive_summary)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    bars = "".join(
        f'<div class="qai-bar">{_escape(item.name.upper())} · {item.score}<i style="--score:{item.score}%"></i></div>'
        for item in quality.dimensions
    )
    st.markdown(
        f'<div class="qai-integrity qai-shell"><div><div class="qai-kicker">DECISION INTEGRITY</div><div class="qai-integrity-score">{quality.score}<small>/100 · {_escape(quality.grade)}</small></div></div><div class="qai-bars">{bars}</div></div>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    with left:
        st.markdown(f'<div class="qai-panel qai-shell"><div class="qai-section-title">Investment case</div>{_list(brief.thesis)}<br><div class="qai-section-title">Catalysts</div>{_list(brief.catalysts)}</div>', unsafe_allow_html=True)
    with right:
        st.markdown(f'<div class="qai-panel qai-shell"><div class="qai-section-title">Risk & invalidation</div>{_list(brief.risks)}<br><div class="qai-section-title">Hard invalidation</div>{_list(brief.invalidation)}</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    impl, dissent = st.columns([1.2, 1])
    with impl:
        st.markdown(f'<div class="qai-panel qai-shell"><div class="qai-section-title">Implementation proposal</div><div class="qai-sub">{_escape(brief.sizing)} · {_escape(brief.time_horizon)}</div>{_list(brief.implementation)}</div>', unsafe_allow_html=True)
    with dissent:
        st.markdown(f'<div class="qai-panel qai-shell"><div class="qai-section-title">Dissent & missing evidence</div>{_list(brief.dissent + brief.missing_evidence)}</div>', unsafe_allow_html=True)
    if run.warnings:
        with st.expander(f"Run warnings · {len(run.warnings)}"):
            for warning in run.warnings:
                st.warning(warning)


def _reports(run: CommitteeRun) -> None:
    st.markdown("### Independent desk reports")
    st.caption("Each desk receives the question and its evidence bundle independently; the CIO sees the reports only after all desks finish.")
    for report in run.reports:
        report_quality = score_agent_report(report)
        with st.expander(f"{report.agent_name} · {report.stance} · {report.confidence:.0%} · Q{report_quality}"):
            st.markdown(
                f'<div class="qai-report-head qai-shell"><div><span class="qai-agent-dot"></span><strong>{_escape(report.agent_name)}</strong><div class="qai-sub">{_escape(report.role)}</div></div><div class="qai-report-meta">QUALITY {report_quality}/100 · {_escape(report.model)} · {report.latency_ms} ms</div></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f"**Thesis** — {report.thesis}")
            decision_tab, scenario_tab, control_tab = st.tabs(["DECISION LOGIC", "SCENARIOS", "CONTROL LOOP"])
            with decision_tab:
                cols = st.columns(3)
                with cols[0]:
                    st.markdown("**Why**")
                    for item in report.rationale:
                        st.markdown(f"- {item}")
                with cols[1]:
                    st.markdown("**Risks**")
                    for item in report.risks:
                        st.markdown(f"- {item}")
                with cols[2]:
                    st.markdown("**Invalidation**")
                    for item in report.invalidation:
                        st.markdown(f"- {item}")
            with scenario_tab:
                left, right = st.columns(2)
                with left:
                    st.markdown("**Bull / base / bear**")
                    for item in report.scenarios:
                        st.markdown(f"- {item}")
                with right:
                    st.markdown("**Declared assumptions**")
                    for item in report.assumptions:
                        st.markdown(f"- {item}")
            with control_tab:
                left, right = st.columns(2)
                with left:
                    st.markdown("**Recommended actions**")
                    for item in report.actions:
                        st.markdown(f"- {item}")
                with right:
                    st.markdown("**Monitoring / stop conditions**")
                    for item in report.monitoring:
                        st.markdown(f"- {item}")
            st.caption("Evidence: " + (", ".join(report.evidence_used) if report.evidence_used else "none connected"))
            if report.dissent:
                st.info(report.dissent)


def _decision_exports(run: CommitteeRun, organization: OrganizationConfig) -> None:
    quality = evaluate_committee(run, organization)
    markdown_packet = decision_packet_markdown(run, organization, quality)
    json_packet = decision_packet_json(run, organization, quality)
    with st.expander("Decision packet · audit & export", expanded=False):
        st.caption("Portable, secret-free decision record containing the plan, evidence, desk reports, interactions, risk gate and CIO conclusion.")
        a, b, c = st.columns([1, 1, 1.25])
        with a:
            st.download_button(
                "DOWNLOAD INVESTMENT MEMO",
                markdown_packet,
                file_name=f"quant_ai_{run.ticker}_{run.run_id}.md",
                mime="text/markdown",
                width="stretch",
            )
        with b:
            st.download_button(
                "DOWNLOAD AUDIT JSON",
                json_packet,
                file_name=f"quant_ai_{run.ticker}_{run.run_id}.json",
                mime="application/json",
                width="stretch",
            )
        with c:
            st.metric("Decision integrity", f"{quality.score}/100", quality.grade)
        if quality.blockers:
            st.markdown("**Open decision blockers**")
            for blocker in quality.blockers:
                st.markdown(f"- {blocker}")


def _evidence(run: CommitteeRun | None) -> None:
    if run is None:
        st.markdown('<div class="qai-empty">Run an investment committee to build an evidence ledger.</div>', unsafe_allow_html=True)
        return
    st.markdown("### Evidence ledger")
    st.caption("Every section adapter reports availability explicitly. Missing data remains visible and cannot silently become a model assumption.")
    rows = []
    for name, result in run.tools.items():
        rows.append({"tool": name, "status": result.status.value, "evidence": len(result.evidence), "warnings": len(result.warnings), "latency_ms": result.duration_ms})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for name, result in run.tools.items():
        with st.expander(f"{name} · {result.status.value}"):
            if result.warnings:
                for warning in result.warnings:
                    st.warning(warning)
            st.json(result.data, expanded=False)
            if result.evidence:
                st.dataframe(pd.DataFrame([asdict(item) for item in result.evidence]), hide_index=True, width="stretch")


def _graph_agent_editor(organization: OrganizationConfig, agent_id: str) -> None:
    agent = next((item for item in organization.agents if item.id == agent_id), None)
    if agent is None:
        return
    tool_names = build_default_registry().names()
    peer_ids = [item.id for item in organization.agents if item.id != agent.id]
    st.markdown(f"#### Neural desk editor · {agent.name}")
    st.caption("Changes made here update the same persistent organization used by the committee and Agent Studio.")
    with st.form(f"qai_graph_agent_editor_{agent.id}"):
        a, b, c = st.columns([1, 1, 1.2])
        with a:
            enabled = st.checkbox("Desk enabled", value=agent.enabled)
            priority = st.slider("Routing priority", 0, 100, int(agent.priority))
        with b:
            model = st.text_input("Model override", value=agent.model)
            risk_veto = st.checkbox("Can activate risk veto", value=agent.risk_veto)
        with c:
            consults = st.multiselect("Peer consultations", peer_ids, default=[item for item in agent.consults if item in peer_ids])
        tools = st.multiselect("Evidence engines", tool_names, default=[name for name in agent.tools if name in tool_names])
        mandate = st.text_area("Mandate", value=agent.mandate, height=110)
        rights = st.text_area("Decision rights", value=agent.decision_rights, height=80)
        guardrails = st.text_area("Guardrails · one per line", value="\n".join(agent.guardrails), height=80)
        saved = st.form_submit_button("APPLY DESK CONFIGURATION", type="primary", width="stretch")
    if saved:
        agent.enabled = bool(enabled)
        agent.priority = int(priority)
        agent.model = model.strip() or "inherit"
        agent.risk_veto = bool(risk_veto)
        agent.consults = list(consults)
        agent.tools = list(tools)
        agent.mandate = mandate.strip() or agent.mandate
        agent.decision_rights = rights.strip() or agent.decision_rights
        agent.guardrails = [item.strip() for item in guardrails.splitlines() if item.strip()]
        ConfigStore().save(organization)
        st.session_state["qai_organization"] = organization
        st.success(f"{agent.name} updated in the live committee topology.")
        st.rerun()


def _graph_cio_editor(organization: OrganizationConfig) -> None:
    st.markdown("#### CIO / governance editor")
    with st.form("qai_graph_cio_editor"):
        cio_prompt = st.text_area("CIO decision mandate", value=organization.cio_prompt, height=150)
        governance = st.text_area("Fund governance", value=organization.governance_prompt, height=120)
        saved = st.form_submit_button("APPLY CIO GOVERNANCE", type="primary", width="stretch")
    if saved:
        organization.cio_prompt = cio_prompt.strip() or organization.cio_prompt
        organization.governance_prompt = governance.strip() or organization.governance_prompt
        ConfigStore().save(organization)
        st.session_state["qai_organization"] = organization
        st.success("CIO governance updated.")
        st.rerun()


def _workflow(organization: OrganizationConfig, run: CommitteeRun | None) -> None:
    st.markdown("### Neural committee topology")
    st.caption("Drag nodes, pan, zoom, filter relationships, click any edge, or edit a desk directly from the graph. Every live edge comes from the actual execution ledger.")
    selected_default = st.session_state.get("qai_graph_selected")
    if not isinstance(selected_default, dict):
        selected_default = {"kind": "node", "id": "cio"}
    try:
        component_state = render_interactive_workflow(organization, run, selected_default)
    except Exception as exc:
        st.warning(f"Interactive workflow fallback: {type(exc).__name__}: {exc}")
        st.markdown(workflow_graph_html(organization, run), unsafe_allow_html=True)
        component_state = {"selected": selected_default, "action": None}

    selected = component_state.get("selected")
    if not isinstance(selected, dict):
        selected = selected_default
    st.session_state["qai_graph_selected"] = selected
    action = component_state.get("action")
    if isinstance(action, dict) and action.get("nonce") != st.session_state.get("qai_graph_action_nonce"):
        st.session_state["qai_graph_action_nonce"] = action.get("nonce")
        kind, node_id = str(action.get("kind") or ""), str(action.get("id") or "")
        if kind == "toggle_agent":
            agent = next((item for item in organization.agents if item.id == node_id), None)
            if agent is not None:
                agent.enabled = not agent.enabled
                ConfigStore().save(organization)
                st.session_state["qai_organization"] = organization
                st.toast(f"{agent.name}: {'enabled' if agent.enabled else 'disabled'}")
                st.rerun()
        elif kind in {"edit_agent", "edit_cio", "inspect_tool", "focus_node"}:
            selected = {"kind": "node", "id": node_id}
            st.session_state["qai_graph_selected"] = selected

    if run is None:
        st.info("Configuration mode: relationships are editable and marked as configured. Execute a committee mission to replace them with verified dispatch, report, challenge and veto traces.")
        config_tab, topology_tab = st.tabs(["SELECTED NODE CONFIG", "ORGANIZATION MAP"])
        with config_tab:
            selected_id = str(selected.get("id") or "cio")
            if selected_id == "cio":
                _graph_cio_editor(organization)
            else:
                _graph_agent_editor(organization, selected_id)
        with topology_tab:
            rows = [{"desk": agent.name, "enabled": agent.enabled, "priority": agent.priority, "model": agent.model, "tools": len(agent.tools), "consults": len(agent.consults)} for agent in organization.agents]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        return

    quality = evaluate_committee(run, organization)
    complete_tools = sum(result.status == NodeStatus.COMPLETE for result in run.tools.values())
    challenge_count = sum(event.kind in {"challenge", "veto"} for event in run.interactions)
    cols = st.columns(5)
    cols[0].metric("Request class", run.plan.request_kind.replace("_", " ").upper())
    cols[1].metric("Interactions", len(run.interactions))
    cols[2].metric("Evidence complete", f"{complete_tools}/{len(run.tools)}")
    cols[3].metric("Challenges / vetoes", challenge_count)
    cols[4].metric("Decision integrity", f"{quality.score}/100", quality.grade)

    selected_id = str(selected.get("id") or "cio")
    inspector, ledger, integrity = st.tabs(["LIVE NODE CONTROL", "INTERACTION LEDGER", "DECISION INTEGRITY"])
    with inspector:
        if selected.get("kind") == "edge":
            edge_index = int(selected_id) if selected_id.isdigit() else -1
            if 0 <= edge_index < len(run.interactions):
                st.json(run.interactions[edge_index].to_dict(), expanded=True)
        elif selected_id == "cio":
            st.markdown(f"**Decision:** {run.brief.decision} · **Confidence:** {run.brief.confidence:.0%}")
            st.write(run.brief.executive_summary)
            _graph_cio_editor(organization)
        elif any(agent.id == selected_id for agent in organization.agents):
            _graph_agent_editor(organization, selected_id)
        elif selected_id in run.tools:
            result = run.tools[selected_id]
            st.markdown(f"**{TOOL_LABELS.get(selected_id, selected_id)} · {result.status.value.upper()}**")
            for warning in result.warnings:
                st.warning(warning)
            st.json(result.data, expanded=False)
            if result.evidence:
                st.dataframe(pd.DataFrame([asdict(item) for item in result.evidence]), hide_index=True, width="stretch")
        elif selected_id == "human_ic":
            st.warning("Human Investment Committee is the final capital authority. Quant AI can recommend and document, never self-approve execution.")
    with ledger:
        rows = [event.to_dict() for event in run.interactions]
        st.dataframe(pd.DataFrame(rows)[["kind", "source", "target", "status", "message", "effect", "created_at"]], hide_index=True, width="stretch")
    with integrity:
        st.dataframe(pd.DataFrame([asdict(item) for item in quality.dimensions]), hide_index=True, width="stretch")
        if quality.blockers:
            st.markdown("**Blocking conditions**")
            for item in quality.blockers:
                st.markdown(f"- {item}")
        if quality.next_actions:
            st.markdown("**Next evidence actions**")
            for item in quality.next_actions:
                st.markdown(f"- {item}")


def _strategy_lab(ticker: str, price_data: pd.DataFrame) -> None:
    st.markdown("### Strategy validation lab")
    st.caption("Reproducible rules, shifted signals, transaction costs, chronological train/test and explicit overfitting warnings. A backtest can promote research—not approve capital.")
    current = StrategySpec.from_dict(st.session_state.get("qai_strategy_spec"))
    controls, overview = st.columns([1.05, 1.95])
    with controls:
        rule = st.selectbox(
            "Strategy rule",
            ["Moving-average trend", "Time-series momentum", "Mean reversion z-score", "Breakout", "Buy & hold benchmark"],
            index=["Moving-average trend", "Time-series momentum", "Mean reversion z-score", "Breakout", "Buy & hold benchmark"].index(current.rule),
            key="qai_strategy_rule",
        )
        name = st.text_input("Research name", value=current.name, key="qai_strategy_name")
        fast = st.number_input("Fast window", 2, 250, int(current.fast_window), key="qai_strategy_fast")
        slow = st.number_input("Slow window", 5, 500, int(current.slow_window), key="qai_strategy_slow")
        lookback = st.number_input("Lookback", 5, 500, int(current.lookback), key="qai_strategy_lookback")
        entry_z = st.number_input("Entry z-score", 0.25, 4.0, float(current.entry_z), 0.25, key="qai_strategy_z")
        allow_short = st.checkbox("Allow short exposure", value=current.allow_short, key="qai_strategy_short")
        cost = st.number_input("Fees / commissions (bps one-way)", 0.0, 200.0, float(current.cost_bps), 1.0, key="qai_strategy_cost")
        slippage = st.number_input("Slippage / impact (bps one-way)", 0.0, 500.0, float(current.slippage_bps), 1.0, key="qai_strategy_slippage")
        train_fraction = st.slider("Training fraction", 0.40, 0.85, float(current.train_fraction), 0.05, key="qai_strategy_train")
        trials = st.number_input("Configurations tried (declare all)", 1, 10000, int(current.trials_declared), key="qai_strategy_trials")
        run_test = st.button("RUN VALIDATION", type="primary", width="stretch", key="qai_strategy_run")

    if run_test:
        spec = StrategySpec(name, rule, int(fast), int(slow), int(lookback), float(entry_z), bool(allow_short), float(cost), float(slippage), float(train_fraction), int(trials))
        st.session_state["qai_strategy_spec"] = asdict(spec)
        st.session_state["qai_strategy_result"] = run_strategy_backtest(price_data, spec)
    result = st.session_state.get("qai_strategy_result")
    with overview:
        if result is None:
            st.markdown('<div class="qai-empty">Configure a reproducible rule and run the validation gate.</div>', unsafe_allow_html=True)
        else:
            summary = result.summary
            metrics = st.columns(5)
            metrics[0].metric("Research gate", f"{summary.get('validation_score', 0)}/100")
            metrics[1].metric("CAGR", f"{float(summary.get('cagr') or 0):.1%}")
            metrics[2].metric("Sharpe", f"{float(summary.get('sharpe') or 0):.2f}")
            metrics[3].metric("Max DD", f"{float(summary.get('max_drawdown') or 0):.1%}")
            metrics[4].metric("OOS Sharpe", f"{float(result.out_of_sample.get('sharpe') or 0):.2f}")
            st.caption(f"STATUS · {str(result.status).replace('_', ' ').upper()} · Methodology cannot override weak economic performance.")
            equity_chart = result.equity.replace([np.inf, -np.inf], np.nan).dropna(how="all")
            if len(equity_chart) >= 2 and equity_chart.notna().any().any():
                st.line_chart(equity_chart, height=300)
            train_tab, test_tab, walk_tab, robust_tab, diag_tab = st.tabs(["IN SAMPLE", "OUT OF SAMPLE", "WALK-FORWARD", "ROBUSTNESS", "VALIDATION GATES"])
            with train_tab:
                st.dataframe(pd.DataFrame([result.in_sample]), hide_index=True, width="stretch")
            with test_tab:
                st.dataframe(pd.DataFrame([result.out_of_sample]), hide_index=True, width="stretch")
            with walk_tab:
                walk_forward = getattr(result, "walk_forward", [])
                if walk_forward:
                    st.dataframe(pd.DataFrame(walk_forward), hide_index=True, width="stretch")
                else:
                    st.info("Walk-forward windows are unavailable for this sample.")
            with robust_tab:
                robust = getattr(result, "robustness", {})
                a, b, c = st.columns(3)
                a.metric("Positive neighbors", f"{float(robust.get('positive_oos_fraction') or 0):.0%}")
                b.metric("Median OOS Sharpe", f"{float(robust.get('median_oos_sharpe') or 0):.2f}")
                c.metric("Worst OOS Sharpe", f"{float(robust.get('worst_oos_sharpe') or 0):.2f}")
                variants = robust.get("variants") if isinstance(robust, dict) else []
                if variants:
                    st.dataframe(pd.DataFrame(variants), hide_index=True, width="stretch")
                bootstrap = robust.get("bootstrap_oos") if isinstance(robust, dict) else {}
                if bootstrap:
                    st.caption("BOOTSTRAP OOS · RESAMPLED RESEARCH DISTRIBUTION")
                    st.dataframe(pd.DataFrame([bootstrap]), hide_index=True, width="stretch")
            with diag_tab:
                for item in result.diagnostics:
                    st.markdown(f"- {item}")
                for warning in result.warnings:
                    st.warning(warning)
            export_a, export_b = st.columns(2)
            with export_a:
                st.download_button(
                    "DOWNLOAD VALIDATION JSON",
                    json.dumps(result.serializable(), ensure_ascii=False, indent=2, default=str),
                    file_name=f"strategy_validation_{ticker}.json",
                    mime="application/json",
                    width="stretch",
                )
            with export_b:
                st.download_button(
                    "DOWNLOAD EQUITY CURVE",
                    result.equity.to_csv(index=True),
                    file_name=f"strategy_equity_{ticker}.csv",
                    mime="text/csv",
                    width="stretch",
                    disabled=result.equity.empty,
                )
            if st.button("SEND STRATEGY TO COMMITTEE", width="stretch", key="qai_strategy_to_committee"):
                question = (
                    f"Valide la stratégie {result.spec.name} sur {ticker}. Décide si elle doit rester en recherche, "
                    "passer en paper trading ou faire l’objet d’une proposition de capital. Audite l’out-of-sample, "
                    "les coûts, le risque d’overfitting, la capacité, le portefeuille et les critères d’arrêt."
                )
                st.session_state["qai_query"] = question
                st.session_state["qai_query_input"] = question
                st.session_state["qai_view"] = "Committee"
                st.rerun()


def _default_portfolio() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"Ticker": "SPY", "Weight %": 35.0, "Expected return %": 8.0, "Volatility %": 18.0, "Asset class": "Equity ETF", "Liquidity": 98},
            {"Ticker": "NVDA", "Weight %": 18.0, "Expected return %": 14.0, "Volatility %": 45.0, "Asset class": "Equity", "Liquidity": 96},
            {"Ticker": "TLT", "Weight %": 20.0, "Expected return %": 4.5, "Volatility %": 16.0, "Asset class": "Bond", "Liquidity": 92},
            {"Ticker": "GLD", "Weight %": 12.0, "Expected return %": 5.0, "Volatility %": 15.0, "Asset class": "Commodity", "Liquidity": 93},
            {"Ticker": "CASH", "Weight %": 15.0, "Expected return %": 3.5, "Volatility %": 0.5, "Asset class": "Cash", "Liquidity": 100},
        ]
    )


def _portfolio_lab() -> None:
    st.markdown("### Whole-portfolio lab")
    st.caption("Mandate-aware concentration, approximate risk contribution, liquidity, scenario losses and a proposal-only rebalance. Replace the example book with the client portfolio.")
    mandate_raw = st.session_state.get("qai_portfolio_mandate") or asdict(PortfolioMandate())
    mandate = PortfolioMandate.from_dict(mandate_raw)
    mandate_cols = st.columns(6)
    nav = mandate_cols[0].number_input("NAV", 1_000.0, 10_000_000_000.0, float(mandate.nav), step=100_000.0)
    max_position = mandate_cols[1].number_input("Max position %", 1.0, 100.0, float(mandate.max_position_pct))
    min_cash = mandate_cols[2].number_input("Min cash %", 0.0, 100.0, float(mandate.min_cash_pct))
    max_gross = mandate_cols[3].number_input("Max gross %", 1.0, 500.0, float(mandate.max_gross_pct))
    max_vol = mandate_cols[4].number_input("Vol budget %", 1.0, 100.0, float(mandate.max_annual_vol_pct))
    turnover = mandate_cols[5].number_input("Turnover budget %", 1.0, 500.0, float(mandate.turnover_budget_pct))
    initial = st.session_state.get("qai_portfolio_frame")
    if not isinstance(initial, pd.DataFrame):
        initial = _default_portfolio()
    edited = st.data_editor(initial, num_rows="dynamic", hide_index=True, width="stretch", key="qai_portfolio_editor")
    if st.button("REVIEW PORTFOLIO", type="primary", width="stretch", key="qai_portfolio_review"):
        mandate = PortfolioMandate(float(nav), float(max_position), float(min_cash), float(max_gross), float(max_vol), float(turnover))
        book = {"holdings": edited.to_dict("records")}
        st.session_state["qai_portfolio_frame"] = edited
        st.session_state["qai_portfolio_book"] = book
        st.session_state["qai_portfolio_mandate"] = asdict(mandate)
        st.session_state["qai_portfolio_review_result"] = review_portfolio(book, mandate)
    review = st.session_state.get("qai_portfolio_review_result")
    if review is None:
        st.markdown('<div class="qai-empty">Load or edit a portfolio, define its mandate, then run the review.</div>', unsafe_allow_html=True)
        return
    metrics = review.metrics
    cards = st.columns(6)
    cards[0].metric("Status", review.status.upper())
    cards[1].metric("Gross", f"{float(metrics.get('gross_exposure') or 0):.1%}")
    cards[2].metric("Net", f"{float(metrics.get('net_exposure') or 0):.1%}")
    cards[3].metric("Approx. vol", f"{float(metrics.get('approximate_volatility') or 0):.1%}")
    cards[4].metric("Effective bets", f"{float(metrics.get('effective_bets') or 0):.1f}")
    cards[5].metric("Breaches", int(metrics.get("breach_count") or 0))
    if review.breaches:
        for breach in review.breaches:
            st.error(breach)
    scenario_tab, distribution_tab, risk_tab, rebalance_tab = st.tabs(["SCENARIOS", "DISTRIBUTION", "RISK CONTRIBUTION", "PROPOSAL-ONLY REBALANCE"])
    with scenario_tab:
        scenarios = pd.DataFrame(review.scenarios)
        scenarios["portfolio_return"] = scenarios["portfolio_return"].map(lambda value: f"{value:.1%}")
        st.dataframe(scenarios, hide_index=True, width="stretch")
    with distribution_tab:
        simulation = metrics.get("simulation") if isinstance(metrics.get("simulation"), dict) else {}
        if simulation:
            sim_cards = st.columns(4)
            sim_cards[0].metric("Loss probability", f"{float(simulation.get('probability_of_annual_loss') or 0):.1%}")
            sim_cards[1].metric("5th percentile", f"{float(simulation.get('p05_return') or 0):.1%}")
            sim_cards[2].metric("Expected shortfall", f"{float(simulation.get('expected_shortfall_95') or 0):.1%}")
            sim_cards[3].metric("5th percentile P&L", f"{float(simulation.get('p05_pnl_value') or 0):,.0f}")
            st.dataframe(pd.DataFrame([simulation]), hide_index=True, width="stretch")
            st.caption("Parametric distribution using the configured correlation approximation; replace with a connected covariance model for capital use.")
    with risk_tab:
        st.dataframe(pd.DataFrame(review.risk_contributions), hide_index=True, width="stretch")
    with rebalance_tab:
        proposal = pd.DataFrame(review.proposed_weights)
        if not proposal.empty:
            proposal["change"] = proposal["proposed_weight"] - proposal["current_weight"]
        st.dataframe(proposal, hide_index=True, width="stretch")
        st.caption("This is a concentration/cash remediation heuristic, not an optimizer and not an order.")
    for warning in review.warnings:
        st.warning(warning)
    export_a, export_b = st.columns(2)
    with export_a:
        st.download_button(
            "DOWNLOAD PORTFOLIO REVIEW",
            json.dumps(review.serializable(), ensure_ascii=False, indent=2, default=str),
            file_name="quant_ai_portfolio_review.json",
            mime="application/json",
            width="stretch",
        )
    with export_b:
        st.download_button(
            "DOWNLOAD REBALANCE PROPOSAL",
            pd.DataFrame(review.proposed_weights).to_csv(index=False),
            file_name="quant_ai_rebalance_proposal.csv",
            mime="text/csv",
            width="stretch",
        )
    if st.button("SEND PORTFOLIO TO COMMITTEE", width="stretch", key="qai_portfolio_to_committee"):
        question = (
            "Agis comme le CIO de ce portefeuille. Diagnostique les concentrations, contributions au risque, liquidité, "
            "scénarios de stress et violations de mandat. Propose un rééquilibrage conditionnel, ses coûts, ses hedges, "
            "les actifs qui le financent et les limites exigeant le veto du Chief Risk."
        )
        st.session_state["qai_query"] = question
        st.session_state["qai_query_input"] = question
        st.session_state["qai_view"] = "Committee"
        st.rerun()


def _agents(organization: OrganizationConfig) -> None:
    st.markdown("### Agent studio")
    st.caption("Every desk has its own mandate, tools, model override and governance. Organization changes persist; API keys never do.")
    with st.expander("CIO mandate", expanded=False):
        cio_prompt = st.text_area("CIO system prompt", value=organization.cio_prompt, height=150, key="qai_cio_prompt_editor")
        governance_prompt = st.text_area("Fund governance prompt", value=organization.governance_prompt, height=120, key="qai_governance_prompt_editor")
        if st.button("Save CIO mandate", key="qai_save_cio"):
            organization.cio_prompt = cio_prompt.strip()
            organization.governance_prompt = governance_prompt.strip()
            ConfigStore().save(organization)
            st.success("CIO mandate and fund governance saved.")
    tool_names = build_default_registry().names()
    for index, agent in enumerate(list(organization.agents)):
        badge = "ON" if agent.enabled else "OFF"
        with st.expander(f"{agent.name} · {agent.role} · {badge}"):
            with st.form(f"qai_agent_form_{agent.id}"):
                a, b = st.columns(2)
                with a:
                    name = st.text_input("Name", value=agent.name)
                    role = st.text_input("Role", value=agent.role)
                    enabled = st.checkbox("Enabled", value=agent.enabled)
                    risk_veto = st.checkbox("Risk veto", value=agent.risk_veto)
                with b:
                    model = st.text_input("Model override", value=agent.model, help="Use inherit to follow the session model.")
                    priority = st.slider("Priority", 0, 100, int(agent.priority))
                    max_turns = st.slider("Max model turns", 1, 12, int(agent.max_turns))
                    auto_include = st.checkbox("Auto include", value=agent.auto_include)
                mandate = st.text_area("Mandate / system prompt", value=agent.mandate, height=120)
                decision_rights = st.text_area("Decision rights", value=agent.decision_rights, height=80)
                evidence_policy = st.text_area("Evidence policy", value=agent.evidence_policy, height=90)
                tools = st.multiselect("Deterministic tools", tool_names, default=[name for name in agent.tools if name in tool_names])
                consult_options = [item.id for item in organization.agents if item.id != agent.id]
                consults = st.multiselect("Can consult after independent report", consult_options, default=[item for item in agent.consults if item in consult_options])
                required_outputs = st.text_area(
                    "Required outputs · one per line",
                    value="\n".join(agent.required_outputs),
                    height=110,
                )
                review_questions = st.text_area(
                    "Mandatory review questions · one per line",
                    value="\n".join(agent.review_questions),
                    height=110,
                )
                guardrails = st.text_area(
                    "Desk guardrails · one per line",
                    value="\n".join(agent.guardrails),
                    height=90,
                )
                save = st.form_submit_button("Save agent", type="primary")
            if save:
                organization.agents[index] = AgentConfig(
                    id=agent.id,
                    name=name.strip() or agent.name,
                    role=role.strip() or agent.role,
                    mandate=mandate.strip() or agent.mandate,
                    tools=tools,
                    reports_to=agent.reports_to,
                    consults=consults,
                    enabled=enabled,
                    risk_veto=risk_veto,
                    auto_include=auto_include,
                    priority=priority,
                    model=model.strip() or "inherit",
                    max_turns=max_turns,
                    user_created=agent.user_created,
                    decision_rights=decision_rights.strip() or agent.decision_rights,
                    evidence_policy=evidence_policy.strip() or agent.evidence_policy,
                    required_outputs=[item.strip() for item in required_outputs.splitlines() if item.strip()],
                    review_questions=[item.strip() for item in review_questions.splitlines() if item.strip()],
                    guardrails=[item.strip() for item in guardrails.splitlines() if item.strip()],
                )
                ConfigStore().save(organization)
                st.session_state["qai_organization"] = organization
                st.rerun()
            if agent.user_created and st.button("Delete custom agent", key=f"qai_delete_{agent.id}"):
                organization.agents = [item for item in organization.agents if item.id != agent.id]
                ConfigStore().save(organization)
                st.rerun()
    with st.expander("＋ Add specialist agent"):
        with st.form("qai_add_agent"):
            new_name = st.text_input("Agent name")
            new_role = st.text_input("Agent role")
            new_mandate = st.text_area("Mandate")
            new_tools = st.multiselect("Tools", tool_names)
            add = st.form_submit_button("Add to organization", type="primary")
        if add and new_name.strip():
            agent_id = re.sub(r"[^a-z0-9]+", "_", new_name.lower()).strip("_") or f"agent_{len(organization.agents)+1}"
            existing = {item.id for item in organization.agents}
            suffix = 2
            base = agent_id
            while agent_id in existing:
                agent_id = f"{base}_{suffix}"
                suffix += 1
            organization.agents.append(
                AgentConfig(agent_id, new_name.strip(), new_role.strip() or "Specialist", new_mandate.strip() or "Provide an independent evidence-based specialist report.", new_tools, user_created=True)
            )
            ConfigStore().save(organization)
            st.rerun()


def _history() -> None:
    st.markdown("### Decision history & audit")
    records = AuditStore().recent(30)
    if not records:
        st.markdown('<div class="qai-empty">No committee run has been archived yet.</div>', unsafe_allow_html=True)
        return
    rows = []
    for item in records:
        brief = item.get("brief") if isinstance(item.get("brief"), dict) else {}
        rows.append({"created_at": item.get("created_at"), "ticker": item.get("ticker"), "decision": brief.get("decision"), "confidence": brief.get("confidence"), "provider": item.get("provider"), "model": item.get("model"), "run_id": item.get("run_id")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for item in records[:10]:
        with st.expander(f"{item.get('ticker')} · {item.get('brief', {}).get('decision', 'N/A')} · {item.get('run_id')}"):
            st.markdown(f"**Question:** {item.get('query', '')}")
            st.json(item.get("brief", {}), expanded=False)


def _settings(organization: OrganizationConfig) -> None:
    st.markdown("### Model & privacy settings")
    st.caption("Bring your own provider. The API key stays in this Streamlit session only and is excluded from organization files and audit logs.")
    current_provider = str(st.session_state.get("qai_provider") or "OpenAI")
    provider = st.selectbox("Provider", PROVIDERS, index=PROVIDERS.index(current_provider) if current_provider in PROVIDERS else 0, key="qai_provider_select")
    if provider != current_provider:
        st.session_state["qai_provider"] = provider
        st.session_state["qai_model"] = DEFAULT_MODELS[provider]
        st.rerun()
    st.session_state["qai_provider"] = provider
    a, b = st.columns(2)
    with a:
        model = st.text_input("Model", value=str(st.session_state.get("qai_model") or DEFAULT_MODELS[provider]), help="Free-form: use any model identifier supported by your provider.")
        st.session_state["qai_model"] = model.strip()
        api_key = st.text_input("Session API key", value=str(st.session_state.get("qai_api_key") or ""), type="password", autocomplete="off")
        st.session_state["qai_api_key"] = api_key
    with b:
        base_url = st.text_input("Base URL (optional)", value=str(st.session_state.get("qai_base_url") or ""), help="Required for a custom OpenAI-compatible endpoint.")
        st.session_state["qai_base_url"] = base_url.strip()
        st.session_state["qai_temperature"] = st.slider("Temperature", 0.0, 1.0, float(st.session_state.get("qai_temperature") or 0.15), 0.05)
    c, d = st.columns(2)
    with c:
        st.session_state["qai_timeout"] = st.number_input("Provider timeout (seconds)", 15, 300, int(st.session_state.get("qai_timeout") or 90))
    with d:
        st.session_state["qai_max_tokens"] = st.number_input("Max output tokens / desk", 500, 8000, int(st.session_state.get("qai_max_tokens") or 2200), step=100)
    st.markdown("### Committee runtime")
    runtime_a, runtime_b, runtime_c, runtime_d = st.columns(4)
    with runtime_a:
        consultation_enabled = st.checkbox("Consultation round", value=organization.consultation_enabled)
    with runtime_b:
        consultation_rounds = st.number_input("Consultation rounds", 0, 3, int(organization.consultation_rounds))
    with runtime_c:
        parallel_agents = st.number_input("Parallel desks", 1, 16, int(organization.max_parallel_agents))
    with runtime_d:
        risk_signoff = st.checkbox("Require Risk sign-off", value=organization.require_risk_signoff)
    if st.button("Save committee runtime", key="qai_save_runtime"):
        organization.consultation_enabled = bool(consultation_enabled)
        organization.consultation_rounds = int(consultation_rounds)
        organization.max_parallel_agents = int(parallel_agents)
        organization.require_risk_signoff = bool(risk_signoff)
        ConfigStore().save(organization)
        st.session_state["qai_organization"] = organization
        st.success("Committee runtime saved.")
    if api_key:
        st.success("Provider key connected for this session. It will not be written to disk.")
    else:
        st.info("Deterministic analytics remain available without a provider key.")
    if st.button("Disconnect and clear session key", key="qai_disconnect"):
        st.session_state["qai_api_key"] = ""
        st.rerun()
    st.markdown("### Organization portability")
    st.caption("Export the entire desk topology and prompt system without provider secrets, or import a reviewed client configuration.")
    export_col, import_col = st.columns(2)
    with export_col:
        st.download_button(
            "EXPORT ORGANIZATION JSON",
            json.dumps(organization.to_dict(), ensure_ascii=False, indent=2),
            file_name="quant_ai_organization.json",
            mime="application/json",
            width="stretch",
        )
    with import_col:
        uploaded = st.file_uploader("Import organization JSON", type=["json"], key="qai_org_import")
    if uploaded is not None:
        try:
            raw = json.loads(uploaded.getvalue().decode("utf-8"))
            imported = OrganizationConfig.from_dict(raw)
            st.info(f"Import preview: {imported.name} · {len(imported.agents)} desks · version {imported.version}.")
            if not imported.agents:
                st.error("The imported configuration contains no valid agents.")
            elif st.button("APPLY IMPORTED ORGANIZATION", type="primary", key="qai_apply_org_import"):
                ConfigStore().save(imported)
                st.session_state["qai_organization"] = imported
                st.success("Imported organization activated. Provider keys were not imported.")
                st.rerun()
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            st.error(f"Invalid organization file: {exc}")
    st.markdown(
        """
        <div class="qai-warning">Governance: outputs are research proposals, never autonomous orders. Risk vetoes, missing evidence and agent disagreement remain visible in every run.</div>
        """,
        unsafe_allow_html=True,
    )


def render_quant_ai_terminal(ticker: str, price_data: pd.DataFrame, analysis: dict[str, Any]) -> None:
    _inject_css()
    st.session_state.setdefault("qai_provider", "OpenAI")
    st.session_state.setdefault("qai_model", DEFAULT_MODELS["OpenAI"])
    st.session_state.setdefault("qai_api_key", "")
    st.session_state.setdefault("qai_view", "Committee")
    organization = _organization()
    _header(ticker, organization)
    view = _render_navigation()
    if view == "Committee":
        _composer(ticker, price_data, analysis, organization)
        run = _run_from_state()
        if run is None:
            st.markdown('<div class="qai-empty">Ask a strategic question to activate the investment committee.<br><small>All relevant terminal sections will be selected automatically.</small></div>', unsafe_allow_html=True)
        else:
            _brief(run)
            _reports(run)
            _decision_exports(run, organization)
    elif view == "Evidence":
        _evidence(_run_from_state())
        st.divider()
        _history()
    elif view == "Workflow":
        _workflow(organization, _run_from_state())
    elif view == "Strategy":
        _strategy_lab(ticker, price_data)
    elif view == "Portfolio":
        _portfolio_lab()
    elif view == "Agents":
        _agents(organization)
    else:
        _settings(organization)
