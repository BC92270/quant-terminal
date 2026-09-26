"""Persistent workspace shell and 13-view navigation rail."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ..config import DESK_SEQUENCE, DESK_WORKFLOW, VIEW_BY_SLUG, VIEW_SPECS, WORKSPACE_VERSION
from ..contracts import WorkspaceSnapshot
from ..state import set_active_view
from .common import esc, fmt_number, fmt_pct


def render_shell_header(snapshot: WorkspaceSnapshot) -> None:
    price_tone = "green" if (snapshot.price_change or 0.0) >= 0.0 else "red"
    regime_probability = "N/A · DESCRIPTIVE" if snapshot.regime_probability is None else f"{snapshot.regime_probability:.0%}"
    collision = float(snapshot.interaction.collision_score)
    conflict_label = "HIGH" if collision >= 0.70 else "MEDIUM" if collision >= 0.40 else "LOW"
    st.markdown(
        f"""
        <div class="mi-shell">
          <div class="mi-eyebrow">Market Intelligence · Catalyst × Microstructure · Probabilistic Research</div>
          <div class="mi-title">{esc(snapshot.symbol)} <span style="color:rgba(190,215,224,.45)">/</span> Information absorption control plane</div>
          <div class="mi-subtitle">{esc(snapshot.instrument_name)} · {esc(WORKSPACE_VERSION)} · point-in-time contracts · panel-level failure isolation</div>
          <div class="mi-status-grid">
            <div class="mi-status-card"><div class="mi-label">Reference price</div><div class="mi-value mi-value-{price_tone}">{esc(fmt_number(snapshot.price, 2))} · {esc(fmt_pct(snapshot.price_change))}</div></div>
            <div class="mi-status-card"><div class="mi-label">Regime state</div><div class="mi-value mi-value-amber">{esc(snapshot.regime)}</div></div>
            <div class="mi-status-card"><div class="mi-label">Regime probability</div><div class="mi-value">{esc(regime_probability)}</div></div>
            <div class="mi-status-card"><div class="mi-label">Catalyst conflict</div><div class="mi-value mi-value-amber">{collision:.0%} · {esc(conflict_label)}</div></div>
            <div class="mi-status-card"><div class="mi-label">Microstructure</div><div class="mi-value mi-value-cyan">{esc(snapshot.microstructure_level)}</div></div>
            <div class="mi-status-card"><div class="mi-label">Fixture as-of</div><div class="mi-value">{esc(snapshot.as_of.strftime('%Y-%m-%d %H:%M UTC'))}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    context = snapshot.audit.get("context_integrity", {})
    if context.get("state") == "MISMATCH_BLOCKED":
        st.warning(
            f"Context isolation active: requested {context.get('requested_symbol')} is not the canonical "
            f"{context.get('fixture_symbol')} fixture. No market, event, order-book or forecast layer was relabelled "
            "or fused across instruments. The canonical fixture remains visible for research inspection only."
        )
    st.markdown(
        '<div class="mi-alert"><b>RESEARCH ONLY · EXPLICIT MIXED-DATA MODE</b> — '
        f'Market layer: {esc(snapshot.market_status)}. Catalyst layer: {esc(snapshot.catalyst_status)}. '
        'L2, events, analogues and conditional interpretations are deterministic fixtures until licensed '
        'point-in-time providers and shadow history are connected. No BUY/SELL instruction is produced.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'''<div class="mi-ops-strip">
          <div><span>MODE</span><b>RESEARCH ONLY</b></div>
          <div><span>MARKET</span><b>{esc(snapshot.market_status)}</b></div>
          <div><span>EVENTS</span><b>{esc(snapshot.catalyst_status)}</b></div>
          <div><span>BOOK</span><b>{esc(snapshot.microstructure_level)}</b></div>
          <div><span>FORECAST</span><b>UNCALIBRATED</b></div>
          <div><span>PROMOTION</span><b>CLOSED</b></div>
          <div><span>EXECUTION</span><b>DISABLED</b></div>
        </div>''',
        unsafe_allow_html=True,
    )


def render_context_controls(snapshot: WorkspaceSnapshot) -> None:
    horizons = tuple(dict.fromkeys(forecast.horizon for forecast in snapshot.forecasts)) or ("N/A",)
    if st.session_state.get("mi_horizon") not in horizons:
        st.session_state["mi_horizon"] = horizons[0]
    with st.form("mi_context_form", border=False):
        columns = st.columns([1.3, 1.15, 1.2, 1.25, 1.0], vertical_alignment="bottom")
        with columns[0]:
            symbol = st.text_input("INSTRUMENT", value=st.session_state.get("mi_selected_symbol", snapshot.symbol), max_chars=24)
        with columns[1]:
            st.selectbox(
                "FOCUS HORIZON · DISPLAY",
                horizons,
                key="mi_horizon",
                help="Selects the highlighted forecast and risk horizon from the available snapshot contracts. It does not retrain or promote a model.",
            )
        with columns[2]:
            st.selectbox("DATA POLICY", ("STRICT PIT · FAIL CLOSED",), disabled=True)
        with columns[3]:
            st.selectbox("REFRESH", ("MANUAL",), disabled=True)
        with columns[4]:
            apply_context = st.form_submit_button("APPLY CONTEXT", width="stretch", type="secondary")
    if apply_context:
        normalized = str(symbol or snapshot.symbol).upper().strip()[:24]
        if normalized:
            st.session_state["mi_selected_symbol"] = normalized
            st.rerun()


def render_navigation() -> str:
    active = str(st.session_state.get("mi_active_view", "live"))
    active_desk = VIEW_BY_SLUG[active].desk
    st.session_state["mi_active_desk"] = active_desk
    st.markdown('<div class="mi-workflow-label">INSTITUTIONAL RESEARCH WORKFLOW</div>', unsafe_allow_html=True)
    desk_columns = st.columns(len(DESK_SEQUENCE))
    for column, desk in zip(desk_columns, DESK_SEQUENCE):
        stage, help_text = DESK_WORKFLOW[desk]
        with column:
            clicked = st.button(
                f"● {stage}" if desk == active_desk else stage,
                key=f"mi_desk_{desk.lower()}",
                help=("Current workflow stage. " if desk == active_desk else "") + help_text,
                width="stretch",
                type="primary" if desk == active_desk else "secondary",
            )
        if clicked and desk != active_desk:
            first_view = next(spec.slug for spec in VIEW_SPECS if spec.desk == desk)
            set_active_view(st.session_state, first_view)
            st.rerun()
    stage, stage_question = DESK_WORKFLOW[active_desk]
    st.caption(f"{stage} · {stage_question}")
    specs = [spec for spec in VIEW_SPECS if spec.desk == active_desk]
    columns = st.columns(len(specs))
    for column, spec in zip(columns, specs):
        with column:
            clicked = st.button(
                f"● {spec.short_label}" if active == spec.slug else spec.short_label,
                key=f"mi_nav_{spec.slug}",
                help=("Current view. " if active == spec.slug else "") + spec.label,
                width="stretch",
                type="primary" if active == spec.slug else "secondary",
            )
        if clicked and spec.slug != active:
            set_active_view(st.session_state, spec.slug)
            st.rerun()
    st.markdown(
        '<div class="mi-workflow-foot">Evidence posture: <b>WAITING_EVIDENCE</b> · '
        'Human review: <b>NOT ELIGIBLE · PENDING EVIDENCE</b> · Execution path: <b>DISABLED</b></div>',
        unsafe_allow_html=True,
    )
    return active
