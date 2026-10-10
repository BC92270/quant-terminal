from __future__ import annotations

from typing import Iterable

import streamlit as st

from .utils import html_safe


def inject_institutional_css() -> None:
    """Install the section-scoped visual system used by Correlation Intelligence V5."""

    st.markdown(
        """
        <style>
        :root {
          --corr-bg: #071016;
          --corr-panel: rgba(9, 21, 29, .88);
          --corr-panel-soft: rgba(13, 29, 39, .66);
          --corr-line: rgba(129, 170, 188, .20);
          --corr-line-strong: rgba(68, 211, 255, .38);
          --corr-cyan: #45d9ff;
          --corr-mint: #52f2bd;
          --corr-amber: #ffbd59;
          --corr-red: #ff6b7a;
          --corr-text: #eef8fb;
          --corr-muted: #8faab5;
        }

        .corr-v5-shell {position:relative;margin:.35rem 0 1rem;padding:0;}
        .corr-v5-hero {
          position:relative;overflow:hidden;border:1px solid var(--corr-line-strong);
          border-radius:18px;padding:25px 26px 22px;
          background:
            radial-gradient(circle at 88% 8%, rgba(69,217,255,.14), transparent 35%),
            linear-gradient(135deg, rgba(8,24,33,.98), rgba(5,14,20,.96));
          box-shadow:0 18px 55px rgba(0,0,0,.28), inset 0 1px 0 rgba(255,255,255,.03);
        }
        .corr-v5-hero:after {
          content:"";position:absolute;inset:0;pointer-events:none;opacity:.32;
          background-image:linear-gradient(rgba(69,217,255,.04) 1px, transparent 1px),linear-gradient(90deg,rgba(69,217,255,.04) 1px,transparent 1px);
          background-size:34px 34px;mask-image:linear-gradient(90deg,transparent,#000 38%,#000);
        }
        .corr-v5-eyebrow {position:relative;z-index:1;font:700 .69rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.18em;color:var(--corr-cyan);text-transform:uppercase;}
        .corr-v5-title {position:relative;z-index:1;margin:8px 0 5px;color:var(--corr-text);font-size:clamp(1.65rem,3vw,2.65rem);font-weight:760;letter-spacing:-.035em;line-height:1.02;}
        .corr-v5-deck {position:relative;z-index:1;max-width:920px;color:#a9c0c9;font-size:.91rem;line-height:1.55;}
        .corr-v5-badges {position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:8px;margin-top:17px;}
        .corr-v5-badge {display:inline-flex;align-items:center;gap:7px;border:1px solid var(--corr-line);border-radius:999px;padding:6px 10px;background:rgba(3,12,17,.62);color:#bbd0d8;font:650 .67rem/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.06em;text-transform:uppercase;}
        .corr-v5-dot {width:7px;height:7px;border-radius:50%;background:var(--corr-mint);box-shadow:0 0 0 4px rgba(82,242,189,.09),0 0 14px rgba(82,242,189,.55);animation:corr-pulse 2.4s ease-in-out infinite;}
        .corr-v5-dot.amber {background:var(--corr-amber);box-shadow:0 0 0 4px rgba(255,189,89,.09),0 0 14px rgba(255,189,89,.45);}
        .corr-v5-dot.red {background:var(--corr-red);box-shadow:0 0 0 4px rgba(255,107,122,.09),0 0 14px rgba(255,107,122,.45);}

        .corr-v5-control-title {display:flex;align-items:center;justify-content:space-between;margin:.95rem 0 .35rem;padding:0 2px;color:#dff5fb;font:720 .74rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.13em;text-transform:uppercase;}
        .corr-v5-control-title span:last-child {color:#6e8b97;font-weight:600;letter-spacing:.05em;}

        .corr-v5-kpis {display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:13px 0 11px;}
        .corr-v5-kpi {position:relative;overflow:hidden;min-height:128px;border:1px solid var(--corr-line);border-radius:14px;padding:14px 14px 12px;background:linear-gradient(155deg,rgba(14,31,41,.90),rgba(6,16,22,.92));transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease;}
        .corr-v5-kpi:hover {transform:translateY(-2px);border-color:rgba(69,217,255,.44);box-shadow:0 12px 32px rgba(0,0,0,.22);}
        .corr-v5-kpi:before {content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,var(--corr-cyan),transparent);opacity:.72;}
        .corr-v5-kpi.amber:before {background:linear-gradient(90deg,var(--corr-amber),transparent);}
        .corr-v5-kpi.red:before {background:linear-gradient(90deg,var(--corr-red),transparent);}
        .corr-v5-kpi.mint:before {background:linear-gradient(90deg,var(--corr-mint),transparent);}
        .corr-v5-kpi-label {color:#809da8;font:700 .64rem/1.25 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.09em;text-transform:uppercase;}
        .corr-v5-kpi-value {margin-top:12px;color:#f5fbfd;font-size:1.43rem;font-weight:760;line-height:1.05;letter-spacing:-.025em;overflow-wrap:anywhere;}
        .corr-v5-kpi-sub {margin-top:9px;color:#86a1ab;font-size:.72rem;line-height:1.35;}

        .corr-v5-tape {display:flex;align-items:center;gap:14px;overflow-x:auto;border:1px solid rgba(69,217,255,.18);border-radius:12px;padding:9px 12px;background:rgba(5,18,25,.80);scrollbar-width:thin;}
        .corr-v5-tape-item {white-space:nowrap;color:#9db5be;font:650 .68rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;text-transform:uppercase;letter-spacing:.045em;}
        .corr-v5-tape-item b {color:#e9f8fb;font-weight:760;}
        .corr-v5-tape-sep {width:3px;height:3px;border-radius:50%;background:#486570;flex:0 0 auto;}

        .corr-v5-cap-grid {display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px;margin:10px 0 15px;}
        .corr-v5-cap {border:1px solid var(--corr-line);border-radius:11px;padding:10px 11px;background:rgba(7,19,26,.72);}
        .corr-v5-cap-head {display:flex;align-items:center;gap:7px;color:#d9edf2;font:700 .66rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;text-transform:uppercase;letter-spacing:.055em;}
        .corr-v5-cap-sub {margin-top:6px;color:#718e9a;font-size:.68rem;line-height:1.3;}

        .corr-v5-section {margin:6px 0 14px;padding:13px 14px;border-left:2px solid var(--corr-cyan);background:linear-gradient(90deg,rgba(69,217,255,.07),transparent 72%);border-radius:0 10px 10px 0;}
        .corr-v5-section-kicker {color:var(--corr-cyan);font:700 .64rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.15em;text-transform:uppercase;}
        .corr-v5-section-title {margin-top:5px;color:#edf8fb;font-size:1.18rem;font-weight:740;letter-spacing:-.015em;}
        .corr-v5-section-copy {margin-top:4px;color:#86a1ac;font-size:.76rem;line-height:1.45;max-width:980px;}

        .corr-v5-readiness {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0;}
        .corr-v5-readiness-card {border:1px solid var(--corr-line);border-radius:13px;padding:14px;background:rgba(8,21,28,.82);}
        .corr-v5-readiness-card .state {color:var(--corr-mint);font:700 .65rem/1.2 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.08em;text-transform:uppercase;}
        .corr-v5-readiness-card .state.amber {color:var(--corr-amber);}.corr-v5-readiness-card .state.red {color:var(--corr-red);}
        .corr-v5-readiness-card h4 {margin:7px 0 5px;color:#edf8fb;font-size:.91rem;}
        .corr-v5-readiness-card p {margin:0;color:#819da8;font-size:.72rem;line-height:1.42;}

        div[data-baseweb="tab-list"] {gap:4px;border:1px solid rgba(129,170,188,.16);border-radius:12px;padding:5px;background:rgba(4,14,20,.82);overflow-x:auto;}
        div[data-baseweb="tab-list"] button {border-radius:8px;white-space:nowrap;}
        div[data-baseweb="tab-list"] button[aria-selected="true"] {background:linear-gradient(135deg,rgba(69,217,255,.18),rgba(82,242,189,.08));}
        div[data-testid="stExpander"] {border-color:rgba(129,170,188,.20);border-radius:12px;background:rgba(6,18,25,.52);}
        div[data-testid="stDataFrame"] {border:1px solid rgba(129,170,188,.16);border-radius:10px;overflow:hidden;}
        div[data-testid="stMetric"] {border:1px solid rgba(129,170,188,.17);border-radius:11px;padding:10px 12px;background:rgba(7,20,27,.62);}
        div[data-testid="stDownloadButton"] button, div[data-testid="stButton"] button {border-radius:9px;font-weight:700;letter-spacing:.015em;}
        @keyframes corr-pulse {0%,100%{opacity:.72;transform:scale(.92)}50%{opacity:1;transform:scale(1.08)}}
        @media (max-width:1180px){.corr-v5-kpis,.corr-v5-cap-grid{grid-template-columns:repeat(3,minmax(0,1fr));}.corr-v5-readiness{grid-template-columns:repeat(2,minmax(0,1fr));}}
        @media (max-width:720px){.corr-v5-hero{padding:20px 17px}.corr-v5-kpis,.corr-v5-cap-grid,.corr-v5-readiness{grid-template-columns:1fr 1fr}.corr-v5-kpi{min-height:112px}.corr-v5-kpi-value{font-size:1.18rem}}
        @media (max-width:480px){.corr-v5-kpis,.corr-v5-cap-grid,.corr-v5-readiness{grid-template-columns:1fr}}
        @media (prefers-reduced-motion:reduce){.corr-v5-dot{animation:none}.corr-v5-kpi{transition:none}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(ticker: str, version: str = "5.0.0") -> None:
    st.markdown(
        f"""
        <div class="corr-v5-shell">
          <div class="corr-v5-hero">
            <div class="corr-v5-eyebrow">Cross-asset dependency command center / V{html_safe(version)}</div>
            <div class="corr-v5-title">{html_safe(ticker)} Correlation Intelligence</div>
            <div class="corr-v5-deck">Robust dependence, dynamic regimes, network transmission, tail concentration and portfolio diversification in one governed research cockpit.</div>
            <div class="corr-v5-badges">
              <span class="corr-v5-badge"><span class="corr-v5-dot"></span>Research engine online</span>
              <span class="corr-v5-badge"><span class="corr-v5-dot amber"></span>RESEARCH_ONLY</span>
              <span class="corr-v5-badge">No order authority</span>
              <span class="corr-v5-badge">No forward-fill across markets</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_control_title(right: str = "explicit inputs / governed rerun") -> None:
    st.markdown(
        f'<div class="corr-v5-control-title"><span>Research control plane</span><span>{html_safe(right)}</span></div>',
        unsafe_allow_html=True,
    )


def render_kpis(items: Iterable[dict[str, str]]) -> None:
    cards = []
    for item in items:
        accent = str(item.get("accent", ""))
        cards.append(
            f'<div class="corr-v5-kpi {html_safe(accent)}">'
            f'<div class="corr-v5-kpi-label">{html_safe(item.get("label", ""))}</div>'
            f'<div class="corr-v5-kpi-value">{html_safe(item.get("value", "—"))}</div>'
            f'<div class="corr-v5-kpi-sub">{html_safe(item.get("sub", ""))}</div>'
            "</div>"
        )
    st.markdown('<div class="corr-v5-kpis">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def render_tape(items: Iterable[tuple[str, str]]) -> None:
    parts = []
    for idx, (label, value) in enumerate(items):
        if idx:
            parts.append('<span class="corr-v5-tape-sep"></span>')
        parts.append(
            f'<span class="corr-v5-tape-item">{html_safe(label)} <b>{html_safe(value)}</b></span>'
        )
    st.markdown('<div class="corr-v5-tape">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def render_capability_ribbon(items: Iterable[dict[str, str]]) -> None:
    cards = []
    for item in items:
        state = str(item.get("state", "ready")).lower()
        dot_class = "red" if state in {"blocked", "missing", "failed"} else "amber" if state in {"adapter", "limited", "pending"} else ""
        cards.append(
            '<div class="corr-v5-cap">'
            f'<div class="corr-v5-cap-head"><span class="corr-v5-dot {dot_class}"></span>{html_safe(item.get("label", ""))}</div>'
            f'<div class="corr-v5-cap-sub">{html_safe(item.get("detail", ""))}</div>'
            "</div>"
        )
    st.markdown('<div class="corr-v5-cap-grid">' + "".join(cards) + "</div>", unsafe_allow_html=True)


def section_header(kicker: str, title: str, copy: str = "") -> None:
    st.markdown(
        f'<div class="corr-v5-section"><div class="corr-v5-section-kicker">{html_safe(kicker)}</div>'
        f'<div class="corr-v5-section-title">{html_safe(title)}</div>'
        f'<div class="corr-v5-section-copy">{html_safe(copy)}</div></div>',
        unsafe_allow_html=True,
    )


def render_readiness_cards(items: Iterable[dict[str, str]]) -> None:
    cards = []
    for item in items:
        state = str(item.get("state", "ready")).lower()
        state_class = "red" if state in {"blocked", "missing", "failed"} else "amber" if state in {"adapter", "limited", "pending"} else ""
        cards.append(
            '<div class="corr-v5-readiness-card">'
            f'<div class="state {state_class}">{html_safe(item.get("status", state))}</div>'
            f'<h4>{html_safe(item.get("title", ""))}</h4>'
            f'<p>{html_safe(item.get("detail", ""))}</p>'
            "</div>"
        )
    st.markdown('<div class="corr-v5-readiness">' + "".join(cards) + "</div>", unsafe_allow_html=True)
