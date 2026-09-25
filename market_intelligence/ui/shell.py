"""Persistent workspace shell and 13-view navigation rail."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ..config import VIEW_SPECS, WORKSPACE_VERSION
from ..contracts import WorkspaceSnapshot
from ..state import set_active_view
from .common import esc, fmt_number, fmt_pct


def render_shell_header(snapshot: WorkspaceSnapshot) -> None:
    price_tone = "green" if (snapshot.price_change or 0.0) >= 0.0 else "red"
    regime_probability = "N/A · DESCRIPTIVE" if snapshot.regime_probability is None else f"{snapshot.regime_probability:.0%}"
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
            <div class="mi-status-card"><div class="mi-label">Catalyst conflict</div><div class="mi-value mi-value-amber">{snapshot.interaction.collision_score:.0%} · HIGH</div></div>
            <div class="mi-status-card"><div class="mi-label">Microstructure</div><div class="mi-value mi-value-cyan">{esc(snapshot.microstructure_level)}</div></div>
            <div class="mi-status-card"><div class="mi-label">Fixture as-of</div><div class="mi-value">{esc(snapshot.as_of.strftime('%Y-%m-%d %H:%M UTC'))}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="mi-alert"><b>RESEARCH ONLY · EXPLICIT MIXED-DATA MODE</b> — '
        f'Market layer: {esc(snapshot.market_status)}. Catalyst layer: {esc(snapshot.catalyst_status)}. '
        'L2, events, analogues and conditional interpretations are deterministic fixtures until licensed '
        'point-in-time providers and shadow history are connected. No BUY/SELL instruction is produced.</div>',
        unsafe_allow_html=True,
    )


def render_context_controls(snapshot: WorkspaceSnapshot) -> None:
    with st.form("mi_context_form", border=False):
        columns = st.columns([1.3, 1.15, 1.2, 1.25, 1.0], vertical_alignment="bottom")
        with columns[0]:
            symbol = st.text_input("INSTRUMENT", value=st.session_state.get("mi_selected_symbol", snapshot.symbol), max_chars=24)
        with columns[1]:
            st.selectbox(
                "RESEARCH HORIZON",
                ("10m", "30m", "1h", "2h", "1d", "5d"),
                key="mi_horizon",
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
    desks = ("NOW", "STATE", "FUSION", "GOVERN")
    for desk in desks:
        specs = [spec for spec in VIEW_SPECS if spec.desk == desk]
        st.caption(f"{desk} DESK")
        columns = st.columns(len(specs))
        for column, spec in zip(columns, specs):
            with column:
                clicked = st.button(
                    spec.short_label,
                    key=f"mi_nav_{spec.slug}",
                    help=spec.label,
                    width="stretch",
                    type="primary" if active == spec.slug else "secondary",
                    disabled=active == spec.slug,
                )
            if clicked:
                set_active_view(st.session_state, spec.slug)
                st.rerun()
    return active
