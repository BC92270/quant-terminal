"""Compatibility entrypoint for the packaged WorldMonitor runtime.

The koala73 project is a design and architecture reference only.  Quant
Terminal runs its own JARVIS intelligence engine, layer registry, providers,
country atlas and quant panels.  There is deliberately no renderer selector,
foreign frontend iframe, sign-in flow or secondary native runtime here.
"""

from __future__ import annotations

import streamlit as st

from worldmonitor import MODULE_VERSION
from worldmonitor import get_capabilities as _get_capabilities
from worldmonitor import render as _render_worldmonitor


def get_worldmonitor_capabilities() -> dict[str, object]:
    """Return a stable, secret-free capability snapshot for tests and diagnostics."""

    return _get_capabilities()


def _inject_worldmonitor_shell() -> None:
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none!important; }
        section[data-testid="stSidebar"], [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"] { display:none!important; }
        .block-container { max-width:100vw!important; padding:.35rem .70rem 1.2rem!important; }
        .wmj-system-rail { display:grid; grid-template-columns:minmax(250px,1.7fr) repeat(5,minmax(105px,.5fr));
          gap:1px; border:1px solid #273039; background:#273039; margin:0 0 6px; overflow:hidden;
          box-shadow:0 8px 40px rgba(0,0,0,.28); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }
        .wmj-system-rail>div { min-height:48px; padding:7px 11px; background:linear-gradient(180deg,#111517,#090c0e);
          display:flex; flex-direction:column; justify-content:center; }
        .wmj-brand { color:#f8fafc; font-size:.85rem; font-weight:950; letter-spacing:.15em; }
        .wmj-brand span { color:#32e889; }
        .wmj-sub { color:#66737d; font-size:.59rem; font-weight:800; letter-spacing:.10em; margin-top:3px; }
        .wmj-k { color:#77838c; font-size:.55rem; font-weight:900; letter-spacing:.12em; text-transform:uppercase; }
        .wmj-v { color:#dce4e9; font-size:.76rem; font-weight:900; margin-top:3px; }
        .wmj-v.live { color:#32e889; }
        @media(max-width:900px){ .wmj-system-rail{grid-template-columns:1fr 1fr}.wmj-system-rail>div:first-child{grid-column:1/-1} }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_system_rail() -> None:
    caps = get_worldmonitor_capabilities()
    st.markdown(
        f"""
        <div class="wmj-system-rail" data-worldmonitor-runtime="single-jarvis">
          <div><span class="wmj-brand">WORLD<span>MONITOR</span> · JARVIS</span><span class="wmj-sub">SITUATIONAL AWARENESS / QUANT INTELLIGENCE</span></div>
          <div><span class="wmj-k">Runtime</span><span class="wmj-v live">● ONLINE</span></div>
          <div><span class="wmj-k">Layers</span><span class="wmj-v">{caps['layer_count']}</span></div>
          <div><span class="wmj-k">Live-backed</span><span class="wmj-v">{caps['live_backed_layers']}</span></div>
          <div><span class="wmj-k">Country atlas</span><span class="wmj-v">{caps['country_profiles']}</span></div>
          <div><span class="wmj-k">Source catalog</span><span class="wmj-v">{caps['providers']['catalogued']}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_worldmonitor_bridge_v211() -> None:
    """Render the sole first-party JARVIS WorldMonitor workspace."""

    _inject_worldmonitor_shell()
    _render_system_rail()
    try:
        _render_worldmonitor()
    except Exception as exc:
        st.error("Le moteur WorldMonitor JARVIS est indisponible.")
        st.caption(f"{type(exc).__name__}: {str(exc)[:180]}")


__all__ = ["MODULE_VERSION", "get_worldmonitor_capabilities", "render_worldmonitor_bridge_v211"]
