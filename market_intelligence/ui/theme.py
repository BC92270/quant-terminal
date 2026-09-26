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
            color: #67edf7; font-size: .74rem; font-weight: 850;
            letter-spacing: .19em; text-transform: uppercase;
        }
        .mi-title {
            color: #f3fbff; font-size: 1.68rem; line-height: 1.08;
            letter-spacing: -.025em; font-weight: 780; margin-top: 4px;
        }
        .mi-subtitle { color: rgba(225,242,248,.78); font-size: .84rem; margin-top: 7px; }
        .mi-status-grid {
            display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px;
            margin: 13px 0 2px;
        }
        .mi-status-card {
            border: 1px solid rgba(129, 191, 207, .14); border-radius: 11px;
            padding: 9px 10px; background: rgba(4, 13, 24, .68); min-height: 58px;
        }
        .mi-label { color: rgba(198, 220, 228, .72); font-size: .66rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
        .mi-value { color: #edfaff; font-size: .86rem; font-weight: 760; margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .mi-value-cyan { color: #59e5f2; }
        .mi-value-green { color: #5ce2b5; }
        .mi-value-red { color: #ff7288; }
        .mi-value-amber { color: #ffc96b; }
        .mi-alert {
            border: 1px solid rgba(255, 191, 82, .28); border-left: 3px solid #ffc35c;
            border-radius: 10px; padding: 10px 13px; margin: 8px 0 14px;
            color: rgba(244, 231, 199, .91); background: rgba(70, 47, 9, .22);
            font-size: .79rem; line-height: 1.5;
        }
        .mi-ops-strip {
            display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 1px;
            border: 1px solid rgba(96, 208, 224, .20); border-radius: 11px; overflow: hidden;
            margin: 0 0 14px; background: rgba(3, 14, 24, .90);
        }
        .mi-ops-strip > div { padding: 9px 10px; border-right: 1px solid rgba(96, 208, 224, .12); min-width: 0; }
        .mi-ops-strip > div:last-child { border-right: 0; }
        .mi-ops-strip span { display: block; color: rgba(185, 213, 223, .68); font-size: .64rem; font-weight: 850; letter-spacing: .13em; }
        .mi-ops-strip b { display: block; color: #e8f8fb; font-size: .70rem; margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .mi-section {
            display: flex; align-items: end; justify-content: space-between; gap: 18px;
            border-bottom: 1px solid rgba(85, 216, 232, .16); padding: 4px 0 8px; margin: 8px 0 12px;
        }
        .mi-section-kicker { color: #67edf7; font-size: .68rem; letter-spacing: .14em; font-weight: 850; text-transform: uppercase; }
        .mi-section-title { color: #f0f8fb; font-size: 1.03rem; font-weight: 760; margin-top: 2px; }
        .mi-section-meta { color: rgba(198,219,227,.68); font-size: .68rem; text-align: right; }
        .mi-card {
            border: 1px solid rgba(103, 185, 202, .15); border-radius: 13px;
            padding: 13px 14px; background: linear-gradient(145deg, rgba(7,20,33,.86), rgba(4,13,24,.74));
            min-height: 92px;
        }
        .mi-card-title { color: rgba(205,225,232,.76); font-size: .67rem; letter-spacing: .11em; font-weight: 850; text-transform: uppercase; }
        .mi-card-value { color: #f5fbfd; font-size: 1.12rem; line-height: 1.15; font-weight: 780; margin-top: 7px; }
        .mi-card-note { color: rgba(204,222,229,.70); font-size: .74rem; line-height: 1.42; margin-top: 7px; }
        .mi-state {
            border-radius: 14px; padding: 15px 16px; border: 1px solid rgba(255, 190, 88, .24);
            background: linear-gradient(145deg, rgba(55,39,13,.45), rgba(8,17,26,.86));
        }
        .mi-state-code { color: #ffd071; font-weight: 900; letter-spacing: .10em; font-size: .78rem; text-transform: uppercase; }
        .mi-state-copy { color: rgba(231,239,239,.78); font-size: .78rem; line-height: 1.48; margin-top: 8px; }
        .mi-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
        .mi-chip { border: 1px solid rgba(102,205,220,.24); background: rgba(20,76,86,.25); border-radius: 999px; padding: 5px 9px; color: #d2f6f8; font-size: .66rem; font-weight: 750; }
        .mi-provenance {
            border: 1px dashed rgba(117, 181, 194, .20); border-radius: 10px;
            padding: 9px 11px; color: rgba(198,219,226,.72); font-size: .72rem; line-height: 1.45;
            background: rgba(5,15,25,.46); margin-top: 9px;
        }
        .mi-contract-grid { display: grid; gap: 1px; border: 1px solid rgba(102,194,211,.16); border-radius: 10px; overflow: hidden; }
        .mi-contract-row { display: grid; grid-template-columns: minmax(130px,.7fr) minmax(0,2fr); gap: 12px; padding: 9px 11px; background: rgba(5,17,28,.70); }
        .mi-contract-row b { color: #dff8fa; font-size: .69rem; letter-spacing: .07em; text-transform: uppercase; }
        .mi-contract-row span { color: rgba(221,236,240,.78); font-size: .73rem; line-height: 1.4; overflow-wrap: anywhere; }
        .mi-workflow-label { color: rgba(191,220,229,.68); font-size: .68rem; font-weight: 850; letter-spacing: .16em; margin: 10px 0 5px; }
        .mi-workflow-foot {
            border-left: 2px solid rgba(255, 201, 102, .72); margin: 8px 0 14px; padding: 6px 10px;
            color: rgba(217,232,236,.76); font-size: .72rem; background: rgba(40,31,12,.20);
        }
        .mi-brief-grid { display: grid; grid-template-columns: repeat(5, minmax(0,1fr)); gap: 9px; margin-bottom: 12px; }
        .mi-brief-grid-four { grid-template-columns: repeat(4, minmax(0,1fr)); }
        .mi-brief-card { border: 1px solid rgba(100,190,207,.18); border-radius: 12px; padding: 12px; background: rgba(5,18,30,.76); min-height: 128px; }
        .mi-brief-card > div { color: #68e9f4; font-size: .66rem; font-weight: 850; letter-spacing: .12em; text-transform: uppercase; }
        .mi-brief-card > p { color: rgba(232,244,247,.88); font-size: .78rem; line-height: 1.48; margin: 8px 0 0; }
        .mi-evidence { border: 1px solid rgba(102,194,211,.18); border-left: 3px solid #55e8f5; border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; background: rgba(5,17,28,.72); }
        .mi-evidence > div { color: #dff8fa; font-size: .70rem; font-weight: 850; letter-spacing: .10em; text-transform: uppercase; }
        .mi-evidence ul { color: rgba(221,236,240,.80); font-size: .75rem; line-height: 1.48; padding-left: 18px; margin: 7px 0 0; }
        .mi-evidence-amber { border-left-color: #ffc966; }
        .mi-evidence-red { border-left-color: #ff7188; }
        .mi-evidence-green { border-left-color: #58dfac; }
        .mi-status-badge { border: 1px solid rgba(115,190,204,.17); border-radius: 10px; padding: 9px 10px; background: rgba(5,17,28,.70); min-height: 72px; }
        .mi-status-badge span { display:block; color:rgba(194,219,226,.70); font-size:.65rem; font-weight:850; letter-spacing:.11em; }
        .mi-status-badge b { display:block; color:#edf9fb; font-size:.77rem; margin-top:4px; }
        .mi-status-badge small { display:block; color:rgba(197,217,224,.64); font-size:.69rem; line-height:1.35; margin-top:4px; }
        .mi-status-badge-red b { color:#ff8ca0; } .mi-status-badge-amber b { color:#ffd47e; }
        .mi-status-badge-green b { color:#6be5ba; } .mi-status-badge-cyan b { color:#6eeaf5; }
        .mi-status-badge-muted b { color:rgba(218,232,236,.68); }
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
        [class*="st-key-mi_nav_"] button[kind="primary"],
        [class*="st-key-mi_desk_"] button[kind="primary"] {
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
        [class*="st-key-mi_desk_"] button {
            min-height: 46px !important; border-radius: 10px !important;
            font-size: .70rem !important; letter-spacing: .08em !important;
        }
        button:focus-visible, [role="button"]:focus-visible, input:focus-visible, select:focus-visible {
            outline: 2px solid #6beaf5 !important; outline-offset: 2px !important;
        }
        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
        }
        @media (max-width: 1200px) {
            .mi-ops-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
            .mi-brief-grid, .mi-brief-grid-four { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 1050px) {
            .mi-status-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
        @media (max-width: 760px) {
            .mi-status-grid, .mi-ops-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .mi-brief-grid, .mi-brief-grid-four { grid-template-columns: 1fr; }
            .mi-section { align-items: start; flex-direction: column; gap: 5px; }
            .mi-section-meta { text-align: left; }
            .mi-title { font-size: 1.38rem; }
            .mi-contract-row { grid-template-columns: 1fr; gap: 4px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
