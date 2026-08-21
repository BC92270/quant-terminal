"""Root-level compatibility shim for Quant Terminal Market Psychology integration."""
from __future__ import annotations

from html import escape
from typing import Any

from market_psychology import render_market_psychology_lab


def _fmt_score(value: Any) -> str:
    try:
        x = float(value)
        return f"{x:.1f}"
    except Exception:
        return "—"


def render_market_psychology_shell_header() -> None:
    """Render the autonomous Psychology shell header without mutating the normal ticker workspace.

    app.py can call this instead of the generic terminal header while
    ``market_psychology_lab_open`` is true. Values come only from non-sensitive
    Streamlit session state persisted by the Psychology UI.
    """
    import streamlit as st

    ctx = st.session_state.get("psychology_header_context", {})
    if not isinstance(ctx, dict):
        ctx = {}
    ticker = str(ctx.get("ticker") or st.session_state.get("psychology_symbol") or "SPY")
    state = str(ctx.get("state") or "RESEARCH")
    signal = str(ctx.get("signal") or "RESEARCH")
    score = _fmt_score(ctx.get("score"))
    score_name = str(ctx.get("score_name") or "Behavioral state")
    run = str(ctx.get("run") or "Ready")
    evidence = str(ctx.get("evidence") or "N/A")

    st.markdown(
        f"""
        <style>
          .psy-shell-v211{{
            display:grid;grid-template-columns:1.35fr .72fr .78fr .78fr .92fr .72fr;
            gap:0;border:1px solid rgba(20,70,108,.28);border-radius:13px;
            background:linear-gradient(90deg,#f7fafc 0%,#ffffff 100%);overflow:hidden;
            margin:0 0 14px 0;box-shadow:0 8px 30px rgba(0,0,0,.08);
          }}
          .psy-shell-v211>div{{padding:10px 14px;border-right:1px solid rgba(15,38,60,.07);min-width:0;}}
          .psy-shell-v211>div:last-child{{border-right:none;}}
          .psy-shell-kicker{{font-size:.56rem;letter-spacing:.22em;font-weight:900;color:#1b718d;text-transform:uppercase;}}
          .psy-shell-title{{font-size:1.02rem;line-height:1.05;font-weight:900;color:#142131;margin-top:2px;}}
          .psy-shell-label{{font-size:.52rem;letter-spacing:.18em;font-weight:900;color:#738191;text-transform:uppercase;}}
          .psy-shell-value{{font-size:.76rem;font-weight:850;color:#1c2938;margin-top:4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
          .psy-shell-state{{color:#c69016;}}
          .psy-shell-signal{{color:#1e7593;}}
          @media(max-width:1000px){{.psy-shell-v211{{grid-template-columns:1fr 1fr 1fr;}}}}
        </style>
        <div class="psy-shell-v211">
          <div><div class="psy-shell-kicker">Institutional Quant Workspace</div><div class="psy-shell-title">JARVIS<span style="font-weight:500">Terminal</span></div></div>
          <div><div class="psy-shell-label">Workspace</div><div class="psy-shell-value">Market Psychology · {escape(ticker)}</div></div>
          <div><div class="psy-shell-label">State</div><div class="psy-shell-value psy-shell-state">{escape(state)}</div></div>
          <div><div class="psy-shell-label">Signal</div><div class="psy-shell-value psy-shell-signal">{escape(signal)}</div></div>
          <div><div class="psy-shell-label">Price / Score</div><div class="psy-shell-value">{escape(score_name)} · {escape(score)} · Evidence {escape(evidence)}</div></div>
          <div><div class="psy-shell-label">Run</div><div class="psy-shell-value">{escape(run)}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


__all__ = ["render_market_psychology_lab", "render_market_psychology_shell_header"]
