"""Module-scoped visual system."""

from __future__ import annotations

import streamlit as st


def inject_market_intelligence_theme() -> None:
    st.markdown(
        """
        <style>
        .mi-shell {
            border: 1px solid rgba(69, 218, 234, .20);
            border-radius: 18px;
            padding: 18px 20px 16px;
            background:
                radial-gradient(circle at 82% -15%, rgba(31, 197, 218, .18), transparent 34%),
                linear-gradient(145deg, rgba(5, 16, 29, .98), rgba(7, 22, 37, .92));
            box-shadow: inset 0 1px 0 rgba(255,255,255,.035), 0 18px 44px rgba(0,0,0,.18);
            margin-bottom: 12px;
        }
        .mi-eyebrow {
            color: #55e8f5; font-size: .68rem; font-weight: 850;
            letter-spacing: .19em; text-transform: uppercase;
        }
        .mi-title {
            color: #f3fbff; font-size: 1.68rem; line-height: 1.08;
            letter-spacing: -.025em; font-weight: 780; margin-top: 4px;
        }
        .mi-subtitle { color: rgba(220,239,247,.69); font-size: .82rem; margin-top: 7px; }
        .mi-status-grid {
            display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px;
            margin: 13px 0 2px;
        }
        .mi-status-card {
            border: 1px solid rgba(129, 191, 207, .14); border-radius: 11px;
            padding: 9px 10px; background: rgba(4, 13, 24, .68); min-height: 58px;
        }
        .mi-label { color: rgba(176, 204, 214, .63); font-size: .57rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
        .mi-value { color: #edfaff; font-size: .86rem; font-weight: 760; margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .mi-value-cyan { color: #59e5f2; }
        .mi-value-green { color: #5ce2b5; }
        .mi-value-red { color: #ff7288; }
        .mi-value-amber { color: #ffc96b; }
        .mi-alert {
            border: 1px solid rgba(255, 191, 82, .28); border-left: 3px solid #ffc35c;
            border-radius: 10px; padding: 10px 13px; margin: 8px 0 14px;
            color: rgba(244, 231, 199, .91); background: rgba(70, 47, 9, .22);
            font-size: .76rem;
        }
        .mi-section {
            display: flex; align-items: end; justify-content: space-between; gap: 18px;
            border-bottom: 1px solid rgba(85, 216, 232, .16); padding: 4px 0 8px; margin: 8px 0 12px;
        }
        .mi-section-kicker { color: #55e8f5; font-size: .60rem; letter-spacing: .16em; font-weight: 850; text-transform: uppercase; }
        .mi-section-title { color: #f0f8fb; font-size: 1.03rem; font-weight: 760; margin-top: 2px; }
        .mi-section-meta { color: rgba(183,205,214,.55); font-size: .62rem; text-align: right; }
        .mi-card {
            border: 1px solid rgba(103, 185, 202, .15); border-radius: 13px;
            padding: 13px 14px; background: linear-gradient(145deg, rgba(7,20,33,.86), rgba(4,13,24,.74));
            min-height: 92px;
        }
        .mi-card-title { color: rgba(196,218,226,.68); font-size: .59rem; letter-spacing: .13em; font-weight: 850; text-transform: uppercase; }
        .mi-card-value { color: #f5fbfd; font-size: 1.12rem; line-height: 1.15; font-weight: 780; margin-top: 7px; }
        .mi-card-note { color: rgba(190,212,220,.60); font-size: .70rem; line-height: 1.35; margin-top: 7px; }
        .mi-state {
            border-radius: 14px; padding: 15px 16px; border: 1px solid rgba(255, 190, 88, .24);
            background: linear-gradient(145deg, rgba(55,39,13,.45), rgba(8,17,26,.86));
        }
        .mi-state-code { color: #ffd071; font-weight: 900; letter-spacing: .10em; font-size: .78rem; text-transform: uppercase; }
        .mi-state-copy { color: rgba(231,239,239,.78); font-size: .78rem; line-height: 1.48; margin-top: 8px; }
        .mi-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
        .mi-chip { border: 1px solid rgba(102,205,220,.18); background: rgba(20,76,86,.22); border-radius: 999px; padding: 4px 8px; color: #bfeff3; font-size: .59rem; font-weight: 750; }
        .mi-provenance {
            border: 1px dashed rgba(117, 181, 194, .20); border-radius: 10px;
            padding: 9px 11px; color: rgba(180,205,214,.60); font-size: .66rem;
            background: rgba(5,15,25,.46); margin-top: 9px;
        }
        .mi-gate-pass { color: #58dfac; font-weight: 800; }
        .mi-gate-wait { color: #ffc96b; font-weight: 800; }
        .mi-gate-fail { color: #ff7288; font-weight: 800; }
        .mi-small { color: rgba(183,205,214,.62); font-size: .68rem; }
        [class*="st-key-mi_nav_"] button {
            border-color: rgba(85, 232, 245, .22) !important;
            background: rgba(5, 20, 31, .82) !important;
            color: rgba(224, 243, 247, .88) !important;
            letter-spacing: .06em !important;
            font-size: .72rem !important;
        }
        [class*="st-key-mi_nav_"] button:disabled {
            border-color: rgba(85, 232, 245, .55) !important;
            background: linear-gradient(135deg, rgba(14, 101, 112, .68), rgba(7, 50, 62, .82)) !important;
            color: #ddfbff !important;
            opacity: 1 !important;
        }
        [class*="st-key-FormSubmitter-mi_context_form"] button,
        [class*="st-key-FormSubmitter-mi_research_configuration"] button {
            border-color: rgba(85, 232, 245, .42) !important;
            background: linear-gradient(135deg, #0a7884, #0b586b) !important;
            color: #effdff !important;
        }
        @media (max-width: 1050px) {
            .mi-status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
