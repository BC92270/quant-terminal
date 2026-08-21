from __future__ import annotations

from html import escape
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .config import DEFAULT_SYMBOL
from .data import fetch_market_pack, fetch_news, fetch_options_snapshot
from .behavioral_data import build_behavioral_data_layer
from .engine import build_psychology_state, clip_score
from .validation import build_data_quality_table, build_forward_validation, build_latent_filter_diagnostics, research_protocol_table
from .walk_forward import build_walk_forward_validation_bundle, bundle_json_bytes
from .external_validation import ALLOWED_EXTERNAL_UNIVERSE, DEFAULT_EXTERNAL_UNIVERSE, external_bundle_json_bytes, run_external_batch
from .market_sessions import closed_session_validation_state
from .higher_order_beliefs import render_higher_order_beliefs


def _fmt_pct(x: Any) -> str:
    try:
        v = float(x)
        return f"{v:+.2%}" if np.isfinite(v) else "N/A"
    except Exception:
        return "N/A"


def _fmt_num(x: Any, digits: int = 2) -> str:
    try:
        v = float(x)
        return f"{v:,.{digits}f}" if np.isfinite(v) else "N/A"
    except Exception:
        return "N/A"


def _css() -> None:
    st.markdown(
        """
        <style>
        .psy-hero{
            border:1px solid rgba(90,205,255,.24);border-radius:22px;padding:20px 24px 18px 24px;
            background:radial-gradient(circle at 10% 0%,rgba(45,205,255,.14),transparent 28%),linear-gradient(180deg,rgba(3,13,29,.98),rgba(2,8,19,.98));
            box-shadow:0 0 45px rgba(40,165,255,.08);margin-bottom:12px;
        }
        .psy-kicker{color:#55e8ff;font-size:.70rem;font-weight:950;letter-spacing:.24em;text-transform:uppercase;}
        .psy-title{color:#f8fbff;font-size:2.05rem;font-weight:950;line-height:1.08;margin-top:5px;}
        .psy-sub{color:rgba(225,237,249,.70);font-size:.90rem;line-height:1.45;margin-top:8px;max-width:1200px;}
        .psy-regime{border:1px solid rgba(90,205,255,.18);border-radius:18px;padding:16px 18px;background:rgba(5,18,37,.76);margin:10px 0 14px 0;}
        .psy-regime-label{color:rgba(190,214,234,.62);font-size:.68rem;font-weight:900;letter-spacing:.14em;text-transform:uppercase;}
        .psy-regime-value{color:#f8fbff;font-size:1.35rem;font-weight:950;margin-top:3px;}
        .psy-regime-note{color:rgba(222,235,248,.68);font-size:.80rem;line-height:1.4;margin-top:5px;}
        .psy-card{border:1px solid rgba(90,205,255,.15);border-radius:15px;padding:11px 12px;background:rgba(3,12,27,.72);min-height:96px;}
        .psy-card-label{color:rgba(205,225,241,.62);font-size:.65rem;font-weight:900;letter-spacing:.10em;text-transform:uppercase;}
        .psy-card-value{color:#f8fbff;font-size:1.10rem;font-weight:950;margin-top:5px;}
        .psy-card-meta{color:#55e8ff;font-size:.68rem;font-weight:800;margin-top:3px;}
        .psy-section{color:#55e8ff;font-size:.74rem;font-weight:950;letter-spacing:.18em;text-transform:uppercase;margin:6px 0 9px 0;}
        .psy-ident{border-left:3px solid rgba(85,232,255,.60);padding:8px 12px;background:rgba(5,18,37,.56);color:rgba(225,237,249,.72);font-size:.78rem;line-height:1.45;margin:8px 0;}

        .psy-alarm-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:10px 0 14px 0;}
        .psy-alarm-chip{border:1px solid rgba(90,205,255,.14);border-radius:13px;padding:10px 12px;background:rgba(3,12,27,.76);position:relative;overflow:hidden;}
        .psy-alarm-chip:before{content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--alarm-color);}
        .psy-alarm-name{color:rgba(220,235,248,.68);font-size:.64rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
        .psy-alarm-value{color:#f8fbff;font-size:1.05rem;font-weight:950;margin-top:4px;}
        .psy-alarm-level{color:var(--alarm-color);font-size:.67rem;font-weight:950;letter-spacing:.09em;margin-top:2px;}
        .psy-alarm-delta{color:rgba(220,235,248,.58);font-size:.66rem;margin-top:2px;}
        .psy-alert-card{border:1px solid rgba(90,205,255,.14);border-radius:15px;padding:12px 13px;background:rgba(3,12,27,.72);min-height:138px;position:relative;overflow:hidden;}
        .psy-alert-card:before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:var(--alarm-color);}
        .psy-alert-top{display:flex;justify-content:space-between;gap:10px;align-items:center;}
        .psy-alert-title{color:#f8fbff;font-size:.78rem;font-weight:900;line-height:1.15;}
        .psy-alert-score{color:var(--alarm-color);font-size:1.25rem;font-weight:950;white-space:nowrap;}
        .psy-alert-track{height:6px;background:rgba(220,235,248,.08);border-radius:999px;overflow:hidden;margin:10px 0 8px 0;}
        .psy-alert-fill{height:100%;width:var(--alarm-width);background:var(--alarm-color);border-radius:999px;}
        .psy-alert-meta{color:rgba(220,235,248,.58);font-size:.66rem;line-height:1.35;}
        .psy-scenario-card{border:1px solid rgba(90,205,255,.14);border-radius:14px;padding:11px 12px;background:rgba(3,12,27,.68);margin-bottom:8px;}
        .psy-scenario-head{display:flex;justify-content:space-between;align-items:center;gap:12px;}
        .psy-scenario-name{color:#f8fbff;font-size:.75rem;font-weight:900;}
        .psy-scenario-status{font-size:.65rem;font-weight:950;letter-spacing:.08em;color:var(--alarm-color);}
        .psy-scenario-track{height:7px;background:rgba(220,235,248,.08);border-radius:999px;overflow:hidden;margin:8px 0 7px 0;}
        .psy-scenario-fill{height:100%;width:var(--scenario-width);background:var(--alarm-color);border-radius:999px;}
        .psy-scenario-note{color:rgba(220,235,248,.59);font-size:.67rem;line-height:1.35;}
        .psy-legend{display:flex;gap:14px;flex-wrap:wrap;color:rgba(220,235,248,.62);font-size:.67rem;margin:3px 0 9px 0;}
        .psy-dot{display:inline-block;width:8px;height:8px;border-radius:999px;margin-right:5px;vertical-align:middle;}

        .psy-latent-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px;margin:8px 0 12px 0;}
        .psy-latent-card{border:1px solid rgba(90,205,255,.14);border-radius:15px;padding:11px 12px;background:rgba(3,12,27,.74);position:relative;overflow:hidden;min-height:132px;}
        .psy-latent-card:before{content:"";position:absolute;top:0;left:0;right:0;height:3px;background:var(--state-color);}
        .psy-latent-name{color:rgba(220,235,248,.70);font-size:.65rem;font-weight:950;letter-spacing:.09em;text-transform:uppercase;}
        .psy-latent-value{color:#f8fbff;font-size:1.22rem;font-weight:950;margin-top:5px;}
        .psy-latent-state{color:var(--state-color);font-size:.66rem;font-weight:950;letter-spacing:.08em;margin-top:2px;}
        .psy-latent-meta{color:rgba(220,235,248,.58);font-size:.65rem;line-height:1.42;margin-top:6px;}
        .psy-quality-strip{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;margin:8px 0 12px 0;}
        .psy-quality-card{border:1px solid rgba(90,205,255,.13);border-radius:13px;padding:9px 11px;background:rgba(3,12,27,.62);}
        .psy-quality-label{color:rgba(210,228,242,.58);font-size:.62rem;font-weight:900;letter-spacing:.08em;text-transform:uppercase;}
        .psy-quality-value{color:#f8fbff;font-size:.95rem;font-weight:900;margin-top:4px;}
        </style>
        """,
        unsafe_allow_html=True,
    )



def _level_color(level: str) -> str:
    return {
        "CRITICAL": "#ff4d6d",
        "HIGH": "#ff9f43",
        "WATCH": "#ffd166",
        "NORMAL": "#4ade80",
        "ACTIVE": "#ff4d6d",
        "PARTIAL": "#55e8ff",
        "QUIET": "#4ade80",
        "GATED": "#7f8b99",
        "EXTREME": "#ff4d6d",
        "ELEVATED": "#ffd166",
        "LOW": "#7f8b99",
        "N/A": "#7f8b99",
    }.get(str(level).upper(), "#55e8ff")



def _render_evidence_quality(state: dict[str, Any]) -> None:
    diag = state.get("diagnostics", {}) if isinstance(state.get("diagnostics", {}), dict) else {}
    score = state.get("evidence_quality_score")
    label = str(state.get("evidence_quality_label", "N/A"))
    coverage = state.get("latent_coverage", 0)
    stability = state.get("latent_stability")
    model = str(diag.get("state_model", "N/A"))
    cards = [
        ("Evidence quality", f"{label} · {_fmt_num(score,0)}/100"),
        ("Latent coverage", f"{coverage}/5 historical mechanisms"),
        ("State persistence", f"{_fmt_num(stability,0)}%"),
        ("Filter", model),
    ]
    html = ["<div class='psy-quality-strip'>"]
    for lab, val in cards:
        html.append(
            f"<div class='psy-quality-card'><div class='psy-quality-label'>{escape(str(lab))}</div>"
            f"<div class='psy-quality-value'>{escape(str(val))}</div></div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def _render_latent_state_monitor(state: dict[str, Any]) -> None:
    table = state.get("latent_state", pd.DataFrame())
    history = state.get("history", pd.DataFrame())
    st.markdown("<div class='psy-section'>Latent state / shock monitor</div>", unsafe_allow_html=True)
    st.caption(
        "V2.0.1 calibration: RAW PROXY → CAUSAL NORMALIZED OBSERVATION → LATENT STATE. "
        "STRUCTURAL STATE describes the persistent level; ACUTE ALARM describes a new/rare directional event. "
        "Historical percentiles and normalization use only information available before each timestamp."
    )
    if table is None or table.empty:
        st.info("Latent-state diagnostics unavailable.")
        return

    html = ["<div class='psy-latent-grid'>"]
    for _, row in table.iterrows():
        structural = str(row.get("Structural state", "NORMAL"))
        acute = str(row.get("Acute alarm", "NORMAL"))
        structural_rank = int(row.get("Structural rank", 0) or 0)
        acute_rank = int(row.get("Acute rank", 0) or 0)
        visual = "CRITICAL" if max(structural_rank, acute_rank) >= 3 else "HIGH" if max(structural_rank, acute_rank) >= 2 else "WATCH" if max(structural_rank, acute_rank) >= 1 else "NORMAL"
        color = _level_color(visual)
        latent = float(row.get("Latent state", 50))
        raw = row.get("Raw observation")
        normalized = row.get("Normalized observation")
        pct = row.get("Percentile")
        shock_z = row.get("Shock z")
        shock_direction = str(row.get("Shock direction", "NEUTRAL"))
        velocity = row.get("5D velocity")
        persistence = row.get("Persistence")
        filter_memory = row.get("Filter memory")
        structural_duration = int(row.get("Structural duration", 0) or 0)
        acute_duration = int(row.get("Acute duration", 0) or 0)
        meta = (
            f"raw {_fmt_num(raw,1)} → norm {_fmt_num(normalized,1)} → latent {_fmt_num(latent,1)}<br>"
            f"P{_fmt_num(pct,0)} · shock {_fmt_num(shock_z,2)}σ · {escape(shock_direction)}<br>"
            f"velocity {_fmt_num(velocity,2)}/d · persistence {_fmt_num(persistence,0)}%<br>"
            f"filter memory {_fmt_num(filter_memory,0)}%"
        )
        if structural_duration > 0:
            meta += f"<br>structural duration {structural_duration}d"
        if acute_duration > 0:
            meta += f" · acute {acute_duration}d"
        html.append(
            f"<div class='psy-latent-card' style='--state-color:{color}'>"
            f"<div class='psy-latent-name'>{escape(str(row.get('Mechanism','')))}</div>"
            f"<div class='psy-latent-value'>{latent:.1f}</div>"
            f"<div class='psy-latent-state'>STRUCTURAL {escape(structural)} · ACUTE {escape(acute)}</div>"
            f"<div class='psy-latent-meta'>{meta}</div></div>"
        )
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)

    if history is None or history.empty:
        return
    options = [str(x) for x in table["Key"].tolist()]
    label_map = {str(r.get("Key")): str(r.get("Mechanism")) for _, r in table.iterrows()}
    default_key = options[0]
    try:
        ranked = table.copy()
        ranked["_visual_rank"] = pd.to_numeric(ranked.get("Structural rank", 0), errors="coerce").fillna(0) + 1.2 * pd.to_numeric(ranked.get("Acute rank", 0), errors="coerce").fillna(0)
        ranked = ranked.sort_values(["_visual_rank", "Latent state"], ascending=False)
        if not ranked.empty:
            default_key = str(ranked.iloc[0]["Key"])
    except Exception:
        pass
    focus = st.selectbox(
        "Latent-state focus",
        options,
        index=options.index(default_key) if default_key in options else 0,
        format_func=lambda x: label_map.get(x, x),
        key=f"psy_latent_focus_{state.get('symbol','market')}",
    )
    raw_col = f"{focus}_raw"
    normalized_col = f"{focus}_normalized"
    latent_col = f"{focus}_latent"
    shock_col = f"{focus}_shock_z"
    if latent_col not in history.columns:
        return

    fig = go.Figure()
    if raw_col in history.columns:
        fig.add_trace(go.Scatter(
            x=history["date"], y=history[raw_col], mode="lines", name="Raw proxy",
            line=dict(width=1, dash="dot"), opacity=.20,
        ))
    if normalized_col in history.columns:
        fig.add_trace(go.Scatter(
            x=history["date"], y=history[normalized_col], mode="lines", name="Causal normalized observation",
            line=dict(width=1.4, dash="dash"), opacity=.55,
        ))
    fig.add_trace(go.Scatter(
        x=history["date"], y=history[latent_col], mode="lines", name="Latent state",
        line=dict(width=3),
    ))
    if shock_col in history.columns:
        fig.add_trace(go.Bar(
            x=history["date"], y=history[shock_col], name="Innovation z",
            yaxis="y2", opacity=.22,
        ))
    fig.add_hline(y=58, line_dash="dot", opacity=.20)
    fig.add_hline(y=70, line_dash="dot", opacity=.25)
    fig.add_hline(y=82, line_dash="dot", opacity=.30)
    fig.update_layout(
        template="plotly_dark", height=430, hovermode="x unified",
        title=f"{label_map.get(focus, focus)} — raw proxy, calibrated observation and one-sided latent state",
        margin=dict(l=10, r=10, t=42, b=10),
        yaxis=dict(range=[0, 100], title="Calibrated behavioral state"),
        yaxis2=dict(title="Innovation z", overlaying="y", side="right", showgrid=False, range=[-4, 4]),
        legend=dict(orientation="h", y=1.08),
    )
    st.plotly_chart(fig, use_container_width=True)

    display_cols = [
        "Mechanism", "Raw observation", "Normalized observation", "Latent state",
        "Structural state", "Acute alarm", "Shock direction", "Shock z", "5D velocity",
        "Acceleration", "Percentile", "Persistence", "State uncertainty", "Kalman gain", "Filter memory",
        "Structural duration", "Acute duration", "Structural onset", "Acute onset",
    ]
    display = table[[c for c in display_cols if c in table.columns]].copy()
    for col in ["Structural onset", "Acute onset"]:
        if col in display.columns:
            display[col] = pd.to_datetime(display[col], errors="coerce").dt.date
    st.dataframe(display, use_container_width=True, hide_index=True)


def _validation_bundle_matches_state(state: dict[str, Any]) -> dict[str, Any] | None:
    bundle = st.session_state.get("psy_oos_validation_bundle")
    if not isinstance(bundle, dict) or not bundle.get("available"):
        return None
    manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest", {}), dict) else {}
    if str(manifest.get("symbol", "")).upper() != str(state.get("symbol", "")).upper():
        return None

    # V2.5.1: compare the cached research bundle with the CLOSED-SESSION
    # validation view, not with the live State Map history.  The live layer may
    # legitimately contain today's still-forming US daily bar.
    validation_state, cutoff_meta = closed_session_validation_state(state)
    history = validation_state.get("history", pd.DataFrame())
    if isinstance(history, pd.DataFrame) and not history.empty:
        if int(manifest.get("rows", -1) or -1) != len(history):
            return None
        try:
            expected_end = pd.to_datetime(history["date"], errors="coerce", utc=True).max()
            manifest_end = pd.to_datetime(manifest.get("history_end"), errors="coerce", utc=True)
            if pd.notna(expected_end) and pd.notna(manifest_end) and expected_end.date() != manifest_end.date():
                return None
        except Exception:
            return None
    bundle_cutoff = bundle.get("validation_cutoff", {}) if isinstance(bundle.get("validation_cutoff", {}), dict) else {}
    if bundle_cutoff and bundle_cutoff.get("cutoff_date") != cutoff_meta.get("cutoff_date"):
        return None
    return bundle


def _alarm_predictive_lookup(state: dict[str, Any]) -> dict[str, str]:
    bundle = _validation_bundle_matches_state(state)
    if not bundle:
        return {}
    table = bundle.get("alarm_evidence", pd.DataFrame())
    if not isinstance(table, pd.DataFrame) or table.empty:
        return {}
    raw = {str(r.get("Alarm", "")): str(r.get("Predictive validation", "NOT TESTED")) for _, r in table.iterrows()}
    alias = {
        "TAIL / FEAR STRESS": "FEAR STRESS",
        "ATTENTION SHOCK": "ATTENTION SHOCK",
        "CROWDING / HERDING": "CROWDING / HERDING",
        "EXTRAPOLATION HEAT": "EXTRAPOLATION SURGE",
        "REFLEXIVE FEEDBACK": "REFLEXIVE HEAT",
    }
    return {live: raw.get(study, "NOT TESTED") for live, study in alias.items()}


def _evidence_style(value: Any) -> str:
    palette = {
        "HIGH": "background-color: rgba(74,222,128,.22); color:#dfffea; font-weight:800",
        "MODERATE": "background-color: rgba(85,232,255,.18); color:#e8fbff; font-weight:800",
        "LOW": "background-color: rgba(255,209,102,.18); color:#fff4d0; font-weight:800",
        "NONE": "background-color: rgba(255,77,109,.16); color:#ffdbe2; font-weight:800",
        "N/A": "background-color: rgba(150,165,180,.10); color:#bdc7d2; font-weight:800",
    }
    return palette.get(str(value), "")

def _render_top_alarm_strip(state: dict[str, Any], max_items: int = 4) -> None:
    alerts = state.get("alerts", pd.DataFrame())
    if alerts is None or alerts.empty:
        return
    show = alerts.head(max_items)
    predictive_lookup = _alarm_predictive_lookup(state)
    chips = ["<div class='psy-alarm-strip'>"]
    for _, row in show.iterrows():
        level = str(row.get("Level", "NORMAL"))
        color = _level_color(level)
        score = float(row.get("Score", 50))
        structural = str(row.get("Structural State", "NORMAL"))
        acute = str(row.get("Acute Alarm", "N/A"))
        delta = row.get("5D Delta")
        trend = str(row.get("Trend", "SNAPSHOT"))
        percentile = row.get("Percentile")
        shock_direction = str(row.get("Shock Direction", "SNAPSHOT"))
        if pd.notna(delta):
            delta_text = f"{float(delta):+.1f} pts / 5D · {trend}"
        else:
            delta_text = trend
        if pd.notna(percentile):
            delta_text += f" · P{float(percentile):.0f}"
        if shock_direction not in {"SNAPSHOT", "NEUTRAL", "N/A"}:
            delta_text += f" · {shock_direction}"
        predictive = predictive_lookup.get(str(row.get("Alarm", "")))
        predictive_line = f" · PREDICTIVE {predictive}" if predictive else ""
        chips.append(
            f"<div class='psy-alarm-chip' style='--alarm-color:{color}'>"
            f"<div class='psy-alarm-name'>{escape(str(row.get('Alarm','')))}</div>"
            f"<div class='psy-alarm-value'>{score:.1f}</div>"
            f"<div class='psy-alarm-level'>STRUCT {escape(structural)} · ACUTE {escape(acute)}</div>"
            f"<div class='psy-alarm-delta'>{escape(delta_text + predictive_line)}</div>"
            "</div>"
        )
    chips.append("</div>")
    st.markdown("".join(chips), unsafe_allow_html=True)

def _render_alarm_cards(state: dict[str, Any]) -> None:
    alerts = state.get("alerts", pd.DataFrame())
    if alerts is None or alerts.empty:
        st.info("Alarm mapping unavailable.")
        return
    st.markdown("<div class='psy-section'>Behavioral alarm board</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='psy-legend'>"
        "<span><b>STRUCTURAL</b> = persistent state level</span>"
        "<span><b>ACUTE</b> = new/rare directional event</span>"
        "<span><span class='psy-dot' style='background:#4ade80'></span>NORMAL</span>"
        "<span><span class='psy-dot' style='background:#ffd166'></span>WATCH / ELEVATED</span>"
        "<span><span class='psy-dot' style='background:#ff9f43'></span>HIGH</span>"
        "<span><span class='psy-dot' style='background:#ff4d6d'></span>CRITICAL / EXTREME</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    predictive_lookup = _alarm_predictive_lookup(state)
    rows = [alerts.iloc[i:i+4] for i in range(0, len(alerts), 4)]
    for block in rows:
        cols = st.columns(len(block))
        for col, (_, row) in zip(cols, block.iterrows()):
            level = str(row.get("Level", "NORMAL"))
            color = _level_color(level)
            score = float(row.get("Score", 50))
            structural = str(row.get("Structural State", "NORMAL"))
            acute = str(row.get("Acute Alarm", "N/A"))
            shock_direction = str(row.get("Shock Direction", "SNAPSHOT"))
            delta = row.get("5D Delta")
            trend = str(row.get("Trend", "SNAPSHOT"))
            percentile = row.get("Percentile")
            shock_z = row.get("Shock z")
            acute_duration = int(row.get("Acute Duration", 0) or 0)
            structural_duration = int(row.get("Structural Duration", 0) or 0)
            delta_text = f"5D {float(delta):+.1f} pts · {trend}" if pd.notna(delta) else trend
            if pd.notna(percentile):
                delta_text += f" · P{float(percentile):.0f}"
            if pd.notna(shock_z):
                delta_text += f" · shock {float(shock_z):+.1f}σ"
            if shock_direction not in {"SNAPSHOT", "NEUTRAL", "N/A"}:
                delta_text += f" · {shock_direction}"
            if structural_duration > 0:
                delta_text += f" · struct {structural_duration}d"
            if acute_duration > 0:
                delta_text += f" · acute {acute_duration}d"
            predictive = predictive_lookup.get(str(row.get("Alarm", "")))
            predictive_text = f"PREDICTIVE VALIDATION: {predictive}" if predictive else "PREDICTIVE VALIDATION: NOT TESTED"
            with col:
                st.markdown(
                    f"""
                    <div class='psy-alert-card' style='--alarm-color:{color};--alarm-width:{max(0,min(score,100)):.1f}%'>
                        <div class='psy-alert-top'>
                            <div class='psy-alert-title'>{escape(str(row.get('Alarm','')))}</div>
                            <div class='psy-alert-score'>{score:.0f}</div>
                        </div>
                        <div class='psy-alert-track'><div class='psy-alert-fill'></div></div>
                        <div class='psy-alert-meta'><b>STRUCTURAL:</b> {escape(structural)} · <b>ACUTE:</b> {escape(acute)}<br>
                        {escape(delta_text)}<br><b>{escape(predictive_text)}</b><br>{escape(str(row.get('Question','')))}<br>{escape(str(row.get('Trigger','')))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

def _render_scenarios(state: dict[str, Any], max_items: int = 6) -> None:
    scenarios = state.get("scenarios", pd.DataFrame())
    st.markdown("<div class='psy-section'>Scenario pattern monitor</div>", unsafe_allow_html=True)
    st.caption("Scenario match is template similarity, not probability. V2.0.1 requires hard necessary-condition gates before a scenario can become PARTIAL/WATCH/ACTIVE.")
    if scenarios is None or scenarios.empty:
        st.info("Scenario monitor unavailable.")
        return
    for _, row in scenarios.head(max_items).iterrows():
        status = str(row.get("Status", "QUIET"))
        color = _level_color(status)
        match = float(row.get("Match", 0))
        gate = str(row.get("Gate", "PASS"))
        gate_reason = str(row.get("Gate reason", ""))
        raw_match = row.get("Raw template match")
        gate_line = f"<b>Gate:</b> {escape(gate)}"
        if pd.notna(raw_match):
            gate_line += f" · raw template {_fmt_num(raw_match,0)}%"
        if gate_reason:
            gate_line += f" · {escape(gate_reason)}"
        st.markdown(
            f"""
            <div class='psy-scenario-card' style='--alarm-color:{color};--scenario-width:{max(0,min(match,100)):.1f}%'>
                <div class='psy-scenario-head'>
                    <div class='psy-scenario-name'>{escape(str(row.get('Scenario','')))}</div>
                    <div class='psy-scenario-status'>{escape(status)} · {match:.0f}% MATCH</div>
                </div>
                <div class='psy-scenario-track'><div class='psy-scenario-fill'></div></div>
                <div class='psy-scenario-note'>{gate_line}<br><b>Trajectory:</b> {escape(str(row.get('Trajectory','N/A')))} · persistence {_fmt_num(row.get('Persistence'),0)}%<br>
                {escape(str(row.get('Observed pattern','')))}<br><b>Watch:</b> {escape(str(row.get('What to watch','')))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

def _alarm_heatmap(state: dict[str, Any]) -> go.Figure | None:
    history = state.get("alarm_evolution", pd.DataFrame())
    if history is None or history.empty:
        return None
    cols = [c for c in ["attention", "fear", "herding", "extrapolation", "reflexivity"] if c in history.columns]
    if not cols:
        return None
    labels = {
        "attention": "Attention", "fear": "Fear", "herding": "Herding",
        "extrapolation": "Extrapolation", "reflexivity": "Reflexivity",
    }
    vals = history[cols].apply(pd.to_numeric, errors="coerce")
    levels = pd.DataFrame(index=history.index)
    pct = pd.DataFrame(index=history.index)
    for col in cols:
        sev_col = f"{col}_severity"
        pct_col = f"{col}_percentile"
        if sev_col in history.columns:
            levels[col] = pd.to_numeric(history[sev_col], errors="coerce").fillna(0)
        else:
            v = vals[col]
            levels[col] = np.where(v >= 82, 3, np.where(v >= 70, 2, np.where(v >= 58, 1, 0)))
        pct[col] = pd.to_numeric(history[pct_col], errors="coerce") if pct_col in history.columns else np.nan
    colorscale = [
        [0.00, "#173a2b"], [0.2499, "#173a2b"],
        [0.25, "#5a4b18"], [0.4999, "#5a4b18"],
        [0.50, "#6a3e18"], [0.7499, "#6a3e18"],
        [0.75, "#6a1c2b"], [1.00, "#6a1c2b"],
    ]
    state_matrix = vals[cols].T.to_numpy()
    pct_matrix = pct[cols].T.to_numpy()
    custom = np.stack([state_matrix, pct_matrix], axis=-1)
    fig = go.Figure(go.Heatmap(
        z=levels[cols].T.to_numpy(), x=history["date"], y=[labels[c] for c in cols],
        zmin=0, zmax=3, colorscale=colorscale, showscale=False, customdata=custom,
        hovertemplate="%{y}<br>%{x|%Y-%m-%d}<br>Latent=%{customdata[0]:.1f}<br>Percentile=%{customdata[1]:.0f}<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_dark", height=270, margin=dict(l=10, r=10, t=35, b=20),
        title="Adaptive acute-alarm evolution — directional rarity / shock", xaxis_title=None, yaxis_title=None,
    )
    return fig


def _render_alarm_events(state: dict[str, Any]) -> None:
    events = state.get("historical_alarm_events", pd.DataFrame())
    st.markdown("<div class='psy-section'>Observed historical alarm onsets</div>", unsafe_allow_html=True)
    st.caption("Only first acute HIGH/CRITICAL onsets are logged. Forward returns are descriptive research context, never part of current-state construction.")
    if events is None or events.empty:
        st.info("No historical threshold crossing detected in the selected research window.")
        return
    display = events.copy()
    display["Date"] = pd.to_datetime(display["Date"], errors="coerce").dt.date
    for col in ["5D forward", "20D forward"]:
        if col in display.columns:
            display[col] = display[col].map(_fmt_pct)
    st.dataframe(display, use_container_width=True, hide_index=True, height=min(410, 38 + 35 * len(display)))


def _render_alarm_monitor(state: dict[str, Any]) -> None:
    _render_alarm_cards(state)
    left, right = st.columns([1.10, .90])
    with left:
        fig = _alarm_heatmap(state)
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Alarm evolution unavailable.")
    with right:
        _render_scenarios(state, max_items=5)
    _render_alarm_events(state)

def _render_layer_cards(state: dict[str, Any]) -> None:
    layers = state.get("layers", pd.DataFrame())
    if layers is None or layers.empty:
        return
    cols = st.columns(len(layers))
    for col, (_, row) in zip(cols, layers.iterrows()):
        with col:
            st.markdown(
                f"""
                <div class='psy-card'>
                    <div class='psy-card-label'>{escape(str(row.get('Layer','')))}</div>
                    <div class='psy-card-value'>{_fmt_num(row.get('State'),1)} / 100</div>
                    <div class='psy-card-meta'>proxy quality {_fmt_num(row.get('Confidence'),0)}%</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def _radar(state: dict[str, Any]) -> go.Figure:
    s = state.get("scores", {})
    keys = [
        ("attention", "Attention"),
        ("salience", "Salience"),
        ("extrapolation", "Extrapolation"),
        ("confidence", "Confidence"),
        ("disagreement", "Disagreement"),
        ("fear", "Fear"),
        ("narrative", "Narrative"),
        ("herding", "Herding"),
        ("reflexivity", "Reflexivity"),
        ("risk_appetite", "Risk appetite"),
    ]
    theta = [label for _, label in keys]
    r = [clip_score(s.get(key, 50)) for key, _ in keys]
    theta2 = theta + [theta[0]]
    r2 = r + [r[0]]
    fig = go.Figure(go.Scatterpolar(r=r2, theta=theta2, fill="toself", name="Current state"))
    fig.update_layout(
        template="plotly_dark",
        height=500,
        margin=dict(l=25, r=25, t=35, b=25),
        polar=dict(radialaxis=dict(range=[0, 100], tickvals=[20, 40, 60, 80, 100])),
        showlegend=False,
        title="Behavioral state vector — no single aggregate psychology score",
    )
    return fig


def _history_chart(history: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for col, label in [
        ("attention", "Attention"),
        ("fear", "Fear"),
        ("herding", "Herding"),
        ("extrapolation", "Extrapolation"),
        ("reflexivity", "Reflexivity"),
    ]:
        if col in history.columns:
            fig.add_trace(go.Scatter(x=history["date"], y=history[col], mode="lines", name=label))
    fig.add_hline(y=58, line_dash="dot", opacity=.16)
    fig.add_hline(y=70, line_dash="dot", opacity=.22)
    fig.add_hline(y=82, line_dash="dot", opacity=.28)
    fig.update_layout(
        template="plotly_dark", height=480, hovermode="x unified",
        margin=dict(l=10, r=10, t=40, b=10),
        yaxis=dict(range=[0, 100], title="State intensity"),
        title="Historical latent-state timeline — one-sided filtered estimates",
    )
    return fig


def _mechanism_table(state: dict[str, Any]) -> pd.DataFrame:
    table = state.get("mechanism_table", pd.DataFrame())
    if table is None or table.empty:
        return pd.DataFrame()
    out = table[["key", "layer", "label", "score", "confidence", "status", "evidence", "identification"]].copy()
    out.columns = ["Key", "Layer", "Mechanism", "Score", "Proxy quality", "State", "Observed evidence", "Identification note"]
    latent = state.get("latent_state", pd.DataFrame())
    if latent is not None and not latent.empty and "Key" in latent.columns:
        keep = ["Key", "Raw observation", "Latent state", "Shock z", "Percentile", "5D velocity", "Persistence", "State uncertainty"]
        keep = [c for c in keep if c in latent.columns]
        out = out.merge(latent[keep], on="Key", how="left")
    return out.drop(columns=["Key"], errors="ignore")


def _render_overview(state: dict[str, Any]) -> None:
    _render_evidence_quality(state)
    _render_latent_state_monitor(state)
    _render_alarm_monitor(state)
    st.markdown("<div class='psy-section'>Layer state summary</div>", unsafe_allow_html=True)
    _render_layer_cards(state)
    st.markdown("<div class='psy-section'>State geometry</div>", unsafe_allow_html=True)
    left, right = st.columns([1.05, 1.15])
    with left:
        st.plotly_chart(_radar(state), use_container_width=True)
    with right:
        mt = _mechanism_table(state)
        if not mt.empty:
            cols = [c for c in ["Mechanism", "Score", "Proxy quality", "Raw observation", "Latent state", "Shock z", "Percentile", "State"] if c in mt.columns]
            st.dataframe(mt[cols], use_container_width=True, hide_index=True, height=460)

    history = state.get("history", pd.DataFrame())
    if history is not None and not history.empty:
        st.plotly_chart(_history_chart(history), use_container_width=True)


def _render_mechanisms(state: dict[str, Any]) -> None:
    mt = _mechanism_table(state)
    if mt.empty:
        st.info("Mechanism table unavailable.")
        return
    layer_order = ["Cognition", "Beliefs", "Preference / affect", "Social / reflexive", "Constraints"]
    for layer in layer_order:
        sub = mt[mt["Layer"] == layer]
        if sub.empty:
            continue
        st.markdown(f"<div class='psy-section'>{escape(layer)}</div>", unsafe_allow_html=True)
        st.dataframe(sub, use_container_width=True, hide_index=True)


def _render_narrative_options(state: dict[str, Any]) -> None:
    news = state.get("news", {}) if isinstance(state.get("news", {}), dict) else {}
    options = state.get("options", {})

    st.markdown("<div class='psy-section'>Narrative & belief NLP engine · semantic reliability</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='psy-ident'>V2.1.1 separates mathematical clusters from economic narrative labels, compresses syndicated articles at story level, "
        "uses target relevance weights, calibrates belief-inference confidence and refuses unresolved labels. The corpus remains a current snapshot: "
        "lifecycle/momentum are not a substitute for a persistent historical point-in-time archive.</div>",
        unsafe_allow_html=True,
    )

    q1, q2, q3, q4, q5, q6 = st.columns(6)
    q1.metric("Corpus", str(news.get("count", 0)), help=f"Raw provider rows: {news.get('raw_count', 0)}")
    q2.metric("Stories", str(news.get("story_count", news.get("count", 0))), help=f"Duplicate story docs: {news.get('duplicate_story_docs', 0)}")
    q3.metric("Providers / sources", f"{news.get('provider_count',0)} / {news.get('source_count',0)}")
    q4.metric("Resolved coverage", f"{_fmt_num(news.get('resolved_coverage'),0)}%")
    q5.metric("Semantic validity", f"{_fmt_num(news.get('semantic_validity_score'),0)}/100")
    q6.metric("NLP evidence", f"{_fmt_num(news.get('nlp_evidence_score'),0)}/100")

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Corpus quality", f"{_fmt_num(news.get('corpus_quality'),0)}/100")
    k2.metric("Provider diversity", f"{_fmt_num(news.get('provider_diversity_score'),0)}/100")
    k3.metric("Cluster separation", f"{_fmt_num(news.get('cluster_separation_score'),0)}/100")
    k4.metric("Cluster cohesion", f"{_fmt_num(news.get('cluster_cohesion_score'),0)}/100")
    k5.metric("Label confidence", f"{_fmt_num(news.get('label_confidence_score'),0)}/100")
    k6.metric("Belief extraction", f"{_fmt_num(news.get('belief_extraction_quality'),0)}/100")
    st.caption(
        f"Backend: {news.get('backend','N/A')} · dominant resolved narrative: {news.get('dominant_narrative','N/A')} · "
        f"lifecycle proxy: {news.get('dominant_lifecycle','N/A')} · story compression {float(news.get('story_compression',0)):.0%}"
    )

    narratives = news.get("narratives", pd.DataFrame())
    timeline = news.get("narrative_timeline", pd.DataFrame())
    beliefs = news.get("beliefs", pd.DataFrame())
    matrix = news.get("narrative_belief_matrix", pd.DataFrame())
    phase = news.get("narrative_phase_space", pd.DataFrame())

    left, right = st.columns([1.18, .82])
    with left:
        st.markdown("<div class='psy-section'>Validated economic narrative map</div>", unsafe_allow_html=True)
        if narratives is not None and not narratives.empty:
            top = narratives.head(10).copy()
            fig = go.Figure(go.Bar(
                y=top["Narrative"][::-1], x=top["Share"][::-1], orientation="h",
                text=[f"{x:.0%}" for x in top["Share"][::-1]], textposition="outside",
                customdata=np.column_stack([
                    top["Intensity"][::-1], top["Momentum 2D"][::-1], top["Consensus"][::-1],
                    top["Label confidence"][::-1], top["Lifecycle"][::-1], top["Stories"][::-1],
                ]),
                hovertemplate=("%{y}<br>Share %{x:.1%}<br>Intensity %{customdata[0]:.0f}<br>Momentum %{customdata[1]:+.1f}"
                               "<br>Consensus %{customdata[2]:.0f}<br>Label confidence %{customdata[3]:.0f}"
                               "<br>Lifecycle %{customdata[4]}<br>Stories %{customdata[5]}<extra></extra>"),
            ))
            fig.update_layout(
                template="plotly_dark", height=max(360, 50 * len(top)), margin=dict(l=10, r=30, t=20, b=30),
                xaxis=dict(tickformat=".0%", range=[0, max(.35, float(top["Share"].max()) * 1.30)]), showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
            display_cols = [c for c in [
                "Narrative", "Mentions", "Stories", "Share", "Intensity", "Momentum 2D", "Acceleration",
                "Persistence d", "Consensus", "Polarization", "Novelty", "Belief confidence", "Label confidence",
                "Sentiment", "Uncertainty", "Sources", "Providers", "Lifecycle",
            ] if c in top.columns]
            display = top[display_cols].copy()
            if "Share" in display.columns:
                display["Share"] = display["Share"].map(lambda x: f"{x:.1%}")
            st.dataframe(display, use_container_width=True, hide_index=True, height=360)
        else:
            st.info("No validated economic narratives identified in the current corpus.")

        if timeline is not None and not timeline.empty:
            st.markdown("<div class='psy-section'>Narrative share evolution inside current corpus</div>", unsafe_allow_html=True)
            fig_t = go.Figure()
            for name, sub in timeline.groupby("Narrative"):
                fig_t.add_trace(go.Scatter(x=sub["date"], y=sub["Share"], mode="lines+markers", name=str(name)))
            fig_t.update_layout(template="plotly_dark", height=340, hovermode="x unified", margin=dict(l=10, r=10, t=25, b=10), yaxis_tickformat=".0%")
            st.plotly_chart(fig_t, use_container_width=True)

    with right:
        st.markdown("<div class='psy-section'>Belief distribution</div>", unsafe_allow_html=True)
        bshares = pd.DataFrame({
            "Direction": ["Bullish", "Neutral / mixed", "Bearish"],
            "Share": [float(news.get("belief_bullish_share", 0)), float(news.get("belief_neutral_share", 0)), float(news.get("belief_bearish_share", 0))],
        })
        fig_b = go.Figure(go.Bar(x=bshares["Direction"], y=bshares["Share"], text=[f"{x:.0%}" for x in bshares["Share"]], textposition="outside"))
        fig_b.update_layout(template="plotly_dark", height=280, margin=dict(l=10, r=10, t=20, b=45), yaxis_tickformat=".0%", showlegend=False)
        st.plotly_chart(fig_b, use_container_width=True)
        m1, m2 = st.columns(2)
        m1.metric("Belief confidence", f"{_fmt_num(news.get('belief_confidence_mean'),0)}/100")
        m2.metric("Belief disagreement", f"{_fmt_num(news.get('belief_disagreement'),0)}/100")
        m3, m4 = st.columns(2)
        m3.metric("Narrative consensus", f"{_fmt_num(news.get('narrative_consensus'),0)}/100")
        m4.metric("Polarization", f"{_fmt_num(news.get('narrative_polarization'),0)}/100")
        m5, m6 = st.columns(2)
        m5.metric("Narrative momentum", f"{_fmt_num(news.get('narrative_momentum'),1)} pts")
        m6.metric("Persistence", f"{_fmt_num(news.get('narrative_persistence'),1)} d")

        st.markdown("<div class='psy-section'>Options / convexity footprint</div>", unsafe_allow_html=True)
        if isinstance(options, dict) and options.get("available"):
            rows = [
                ("Call volume", options.get("call_volume")), ("Put volume", options.get("put_volume")),
                ("Put/Call volume", options.get("put_call_volume")), ("Put/Call OI", options.get("put_call_oi")),
                ("Call IV mean", options.get("call_iv")), ("Put IV mean", options.get("put_iv")),
                ("Near-term share", options.get("near_term_share")), ("Rows", options.get("rows")),
            ]
            st.dataframe(pd.DataFrame(rows, columns=["Metric", "Value"]), use_container_width=True, hide_index=True)
            st.caption("Public yfinance option-chain snapshot. It is not a historical OPRA surface and must not be interpreted as institutional order flow.")
        else:
            st.info("Options snapshot unavailable for this instrument/session.")

    if matrix is not None and not matrix.empty:
        st.markdown("<div class='psy-section'>Narrative × belief matrix</div>", unsafe_allow_html=True)
        usable = matrix[matrix["Narrative"].astype(str) != "OTHER / UNRESOLVED"].copy().head(10)
        if not usable.empty:
            heat = usable.set_index("Narrative")[["Bullish", "Neutral / mixed", "Bearish"]]
            fig_m = go.Figure(go.Heatmap(
                z=heat.values, x=heat.columns.tolist(), y=heat.index.tolist(), zmin=0, zmax=1,
                text=np.vectorize(lambda x: f"{x:.0%}")(heat.values), texttemplate="%{text}",
                hovertemplate="%{y}<br>%{x}: %{z:.1%}<extra></extra>", colorbar=dict(title="Share"),
            ))
            fig_m.update_layout(template="plotly_dark", height=max(300, 42 * len(heat)), margin=dict(l=10, r=10, t=20, b=20))
            st.plotly_chart(fig_m, use_container_width=True)

    if phase is not None and not phase.empty:
        st.markdown("<div class='psy-section'>Narrative phase space · attention × consensus</div>", unsafe_allow_html=True)
        p = phase[phase["Narrative"].astype(str) != "OTHER / UNRESOLVED"].copy()
        if not p.empty:
            p["Momentum_abs"] = pd.to_numeric(p.get("Momentum"), errors="coerce").abs().fillna(0) + 5
            fig_p = go.Figure(go.Scatter(
                x=p["Share"], y=p["Consensus"], mode="markers+text", text=p["Narrative"], textposition="top center",
                marker=dict(size=np.clip(9 + p["Momentum_abs"].to_numpy() * 0.55, 10, 35),
                            color=pd.to_numeric(p["Sentiment"], errors="coerce").fillna(0), colorscale="RdBu", cmin=-1, cmax=1,
                            colorbar=dict(title="Sentiment"), line=dict(width=1)),
                customdata=np.column_stack([p["Momentum"], p["Label confidence"], p["Lifecycle"]]),
                hovertemplate=("%{text}<br>Attention share %{x:.1%}<br>Consensus %{y:.0f}/100"
                               "<br>Momentum %{customdata[0]:+.1f}<br>Label confidence %{customdata[1]:.0f}"
                               "<br>Lifecycle %{customdata[2]}<extra></extra>"),
            ))
            fig_p.add_hline(y=65, line_dash="dot", opacity=.25)
            fig_p.update_layout(template="plotly_dark", height=430, margin=dict(l=10, r=10, t=25, b=25),
                                xaxis=dict(title="Attention share", tickformat=".0%"), yaxis=dict(title="Consensus", range=[0,100]))
            st.plotly_chart(fig_p, use_container_width=True)

    st.markdown("<div class='psy-section'>Extracted beliefs — auditable document layer</div>", unsafe_allow_html=True)
    if beliefs is not None and not beliefs.empty:
        bdisplay = beliefs.copy()
        if "published" in bdisplay.columns:
            bdisplay["published"] = pd.to_datetime(bdisplay["published"], errors="coerce", utc=True)
        cols = [c for c in [
            "published", "provider", "source", "title", "narrative", "label_confidence", "relevance", "story_id", "story_size",
            "belief_direction", "belief_score", "belief_confidence", "magnitude", "inference_type", "conditionality",
            "horizon", "driver", "mental_model", "claim", "uncertainty", "semantic_novelty",
        ] if c in bdisplay.columns]
        st.dataframe(bdisplay[cols].head(100), use_container_width=True, hide_index=True, height=560)
    else:
        st.info("No belief records extracted.")

    with st.expander("Corpus / provider / semantic diagnostics", expanded=False):
        diagnostics = news.get("provider_diagnostics", [])
        if diagnostics:
            safe_rows = []
            for row in diagnostics:
                if not isinstance(row, dict):
                    continue
                safe_rows.append({"Provider": row.get("provider", "N/A"), "Status": row.get("status", "N/A"), "HTTP": row.get("http", ""), "Rows": row.get("rows", "")})
            if safe_rows:
                st.dataframe(pd.DataFrame(safe_rows), use_container_width=True, hide_index=True)
        hs = news.get("headline_scores", pd.DataFrame())
        if hs is not None and not hs.empty:
            st.dataframe(hs.head(120), use_container_width=True, hide_index=True)




def _render_institutional_data(state: dict[str, Any]) -> None:
    st.markdown("<div class='psy-section'>Observed Behavioral Data Layer · V2.2.1</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='psy-ident'>
        V2.2.1 hardens the observed-data layer with provider-waterfall breadth, Cboe schema repair, audited option-tenor denominators and completeness/freshness/identification scoring. These are not direct measures of fear,
        beliefs or crowd psychology. Cboe/FRED/CFTC observations are kept separate from the latent behavioral state, and public
        option-chain metrics never infer signed dealer gamma or institutional order flow.
        </div>
        """,
        unsafe_allow_html=True,
    )
    bdata = state.get("behavioral_data", {}) if isinstance(state.get("behavioral_data", {}), dict) else {}
    diag = state.get("diagnostics", {}) if isinstance(state.get("diagnostics", {}), dict) else {}

    vol = bdata.get("volatility_tail", {}) if isinstance(bdata.get("volatility_tail", {}), dict) else {}
    breadth = bdata.get("breadth", {}) if isinstance(bdata.get("breadth", {}), dict) else {}
    funding = bdata.get("funding_credit", {}) if isinstance(bdata.get("funding_credit", {}), dict) else {}
    positioning = bdata.get("positioning", {}) if isinstance(bdata.get("positioning", {}), dict) else {}
    opt = bdata.get("options_behavior", {}) if isinstance(bdata.get("options_behavior", {}), dict) else {}
    short_interest = bdata.get("short_interest", {}) if isinstance(bdata.get("short_interest", {}), dict) else {}
    vm = vol.get("metrics", {}) if isinstance(vol.get("metrics", {}), dict) else {}
    bm = breadth.get("metrics", {}) if isinstance(breadth.get("metrics", {}), dict) else {}
    fm = funding.get("metrics", {}) if isinstance(funding.get("metrics", {}), dict) else {}
    pm = positioning.get("metrics", {}) if isinstance(positioning.get("metrics", {}), dict) else {}
    om = opt.get("metrics", {}) if isinstance(opt.get("metrics", {}), dict) else {}

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Data availability", f"{_fmt_num(diag.get('behavioral_data_availability'),0)}%", help="Completeness-weighted coverage; unavailable blocks no longer count as fully covered.")
    q2.metric("Freshness", f"{_fmt_num(diag.get('behavioral_data_freshness'),0)}%", help="Cadence-aware freshness across daily, weekly and snapshot inputs.")
    q3.metric("Identification", f"{_fmt_num(diag.get('behavioral_data_identification'),0)}%", help="How directly the observed data constrains the intended behavioral mechanism.")
    q4.metric("Observed-data evidence", f"{_fmt_num(diag.get('behavioral_data_evidence'),0)}/100", help="Composite of availability, freshness and identification quality; not model confidence.")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tail stress", _fmt_num(vm.get("tail_stress_score"), 0), help="Cboe volatility structure / vol-of-vol / skew composite. Not direct emotion.")
    c2.metric("Breadth", _fmt_num(bm.get("breadth_score"), 0), help="Equal-weight, factor and sector participation proxy.")
    c3.metric("Funding stress", _fmt_num(fm.get("funding_stress_score"), 0), help="FRED credit spreads and financial-conditions composite.")
    c4.metric("Positioning crowding", _fmt_num(pm.get("positioning_crowding_score"), 0), help="CFTC leveraged-money positioning percentile distance from neutral.")

    left, right = st.columns([1.25, 1.0])
    with left:
        st.markdown("<div class='psy-section'>Volatility / Tail Structure</div>", unsafe_allow_html=True)
        tenors = []
        values = []
        for label, key in (("9D", "vix9d"), ("30D VIX", "vix"), ("3M", "vix3m")):
            val = vm.get(key)
            try:
                f = float(val)
                if np.isfinite(f):
                    tenors.append(label); values.append(f)
            except Exception:
                pass
        if values:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=tenors, y=values, mode="lines+markers+text", text=[f"{x:.1f}" for x in values], textposition="top center", name="Volatility"))
            fig.update_layout(height=295, margin=dict(l=18,r=18,t=34,b=18), title="Cboe SPX volatility term-structure gauges", yaxis_title="Volatility index", showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        vol_rows = [
            {"Metric": "VIX", "Value": vm.get("vix"), "Interpretation": "~30D SPX implied volatility"},
            {"Metric": "VIX9D", "Value": vm.get("vix9d"), "Interpretation": "short-horizon implied volatility"},
            {"Metric": "VIX3M", "Value": vm.get("vix3m"), "Interpretation": "3M implied volatility proxy"},
            {"Metric": "VVIX", "Value": vm.get("vvix"), "Interpretation": "volatility-of-VIX / uncertainty of vol"},
            {"Metric": "SKEW", "Value": vm.get("skew"), "Interpretation": "tail-pricing proxy"},
            {"Metric": "9D - 30D slope", "Value": vm.get("front_slope"), "Interpretation": "negative/positive depending on curve state"},
            {"Metric": "3M - 30D slope", "Value": vm.get("term_slope"), "Interpretation": "term-structure slope"},
            {"Metric": "Measurement coverage", "Value": f"{vol.get('coverage',0)}/{vol.get('coverage_total',5)}", "Interpretation": f"missing: {', '.join(vol.get('missing', [])) if vol.get('missing') else 'none'}"},
            {"Metric": "Tail measurement confidence", "Value": vm.get("tail_measurement_confidence"), "Interpretation": "coverage-based measurement confidence, not a probability"},
        ]
        st.dataframe(pd.DataFrame(vol_rows), use_container_width=True, hide_index=True)
        st.caption(str(vol.get("source_note", "")))

    with right:
        st.markdown("<div class='psy-section'>Breadth / Participation</div>", unsafe_allow_html=True)
        breadth_rows = [
            {"Metric": "RSP - SPY 20D", "Value": bm.get("equal_weight_rel_20d")},
            {"Metric": "QQEW - QQQ 20D", "Value": bm.get("nasdaq_equal_rel_20d")},
            {"Metric": "IWM - SPY 20D", "Value": bm.get("smallcap_rel_20d")},
            {"Metric": "SPHB - SPLV 20D", "Value": bm.get("highbeta_lowvol_rel_20d")},
            {"Metric": "Sectors positive 20D", "Value": bm.get("sector_positive_share_20d")},
            {"Metric": "Sectors > MA20", "Value": bm.get("sector_above_ma20_share")},
            {"Metric": "Sector dispersion 20D", "Value": bm.get("sector_dispersion_20d")},
            {"Metric": "Breadth score", "Value": bm.get("breadth_score")},
        ]
        st.dataframe(pd.DataFrame(breadth_rows), use_container_width=True, hide_index=True)
        st.caption(
            f"{breadth.get('source_note','')} · core {breadth.get('core_coverage',0)}/{breadth.get('core_total',7)} · "
            f"sectors {breadth.get('sector_coverage',0)}/{breadth.get('sector_total',11)}."
        )

    left2, right2 = st.columns([1.05, 1.0])
    with left2:
        st.markdown("<div class='psy-section'>CFTC Positioning</div>", unsafe_allow_html=True)
        ph = positioning.get("history", pd.DataFrame())
        if isinstance(ph, pd.DataFrame) and not ph.empty and "date" in ph.columns:
            fig = go.Figure()
            for col, name in (("lev_money_net_pct_oi", "Leveraged money"), ("asset_mgr_net_pct_oi", "Asset managers"), ("dealer_net_pct_oi", "Dealers")):
                if col in ph.columns:
                    fig.add_trace(go.Scatter(x=ph["date"], y=ph[col], mode="lines", name=name))
            fig.add_hline(y=0, line_dash="dot")
            fig.update_layout(height=310, margin=dict(l=18,r=18,t=34,b=18), title="CFTC TFF net positions as % open interest", yaxis_tickformat=".1%")
            st.plotly_chart(fig, use_container_width=True)
        as_of = pd.to_datetime(pm.get("as_of"), errors="coerce", utc=True)
        available_from = pd.to_datetime(pm.get("available_from"), errors="coerce", utc=True)
        as_of_text = as_of.date().isoformat() if not pd.isna(as_of) else "N/A"
        available_text = available_from.date().isoformat() if not pd.isna(available_from) else "N/A"
        p_rows = [
            {"Metric": "Report date", "Value": as_of_text},
            {"Metric": "Daily-usable from", "Value": available_text},
            {"Metric": "Leveraged money net / OI", "Value": _fmt_pct(pm.get("lev_money_net_pct_oi"))},
            {"Metric": "Leveraged money percentile", "Value": f"P{_fmt_num(pm.get('lev_money_percentile'),1)}"},
            {"Metric": "1W change", "Value": _fmt_pct(pm.get("lev_money_weekly_change"))},
            {"Metric": "Asset managers net / OI", "Value": _fmt_pct(pm.get("asset_mgr_net_pct_oi"))},
            {"Metric": "Dealers net / OI", "Value": _fmt_pct(pm.get("dealer_net_pct_oi"))},
            {"Metric": "Crowding score", "Value": f"{_fmt_num(pm.get('positioning_crowding_score'),1)}/100"},
        ]
        st.dataframe(pd.DataFrame(p_rows), use_container_width=True, hide_index=True)
        st.caption(
            f"{positioning.get('source','CFTC')} · {positioning.get('scope','Market-level positioning proxy')} · "
            f"availability policy: {positioning.get('availability_policy','legacy/unknown')}. V2.3.2 never aligns CFTC history to the Tuesday report date."
        )

    with right2:
        st.markdown("<div class='psy-section'>Funding / Credit Constraints</div>", unsafe_allow_html=True)
        f_rows = [
            {"Metric": "HY OAS", "Value": fm.get("hy_oas"), "Z": fm.get("hy_oas_z")},
            {"Metric": "IG OAS", "Value": fm.get("ig_oas"), "Z": fm.get("ig_oas_z")},
            {"Metric": "NFCI", "Value": fm.get("nfci"), "Z": fm.get("nfci_z")},
            {"Metric": "NFCI risk", "Value": fm.get("nfci_risk"), "Z": fm.get("nfci_risk_z")},
            {"Metric": "NFCI credit", "Value": fm.get("nfci_credit"), "Z": fm.get("nfci_credit_z")},
            {"Metric": "NFCI leverage", "Value": fm.get("nfci_leverage"), "Z": fm.get("nfci_leverage_z")},
            {"Metric": "STLFSI4", "Value": fm.get("stlfsi"), "Z": fm.get("stlfsi_z")},
            {"Metric": "Funding stress", "Value": fm.get("funding_stress_score"), "Z": None},
            {"Metric": "Arbitrage capacity", "Value": fm.get("arbitrage_capacity_score"), "Z": None},
        ]
        st.dataframe(pd.DataFrame(f_rows), use_container_width=True, hide_index=True)
        st.caption(str(funding.get("source_note", "")))

    st.markdown("<div class='psy-section'>Options Behavioral Footprint · Current Snapshot</div>", unsafe_allow_html=True)
    o1, o2, o3, o4, o5, o6 = st.columns(6)
    o1.metric("Put/Call volume", _fmt_num(om.get("put_call_volume"), 2))
    o2.metric("≤7D / loaded volume", _fmt_pct(om.get("dte_7_share")))
    o3.metric("0DTE / loaded volume", _fmt_pct(om.get("zero_dte_share")))
    o4.metric("OTM call share", _fmt_pct(om.get("otm_call_volume_share")))
    o5.metric("OTM put share", _fmt_pct(om.get("otm_put_volume_share")))
    o6.metric("Put-call IV skew", _fmt_num(om.get("put_call_iv_skew"), 3))
    o_rows = [
        {"Metric": "≤30D / loaded volume", "Value": om.get("dte_30_share")},
        {"Metric": "Tenor denominator", "Value": om.get("tenor_denominator_status")},
        {"Metric": "Loaded / listed expiries", "Value": f"{om.get('loaded_expiry_count',0)} / {om.get('listed_expiry_count',0)}"},
        {"Metric": "Max DTE loaded", "Value": om.get("max_dte_loaded")},
        {"Metric": "Loaded-chain volume denominator", "Value": om.get("tenor_denominator_volume")},
        {"Metric": "Top-5 strike OI share", "Value": om.get("oi_top5_strike_share")},
        {"Metric": "Option tail-demand score", "Value": om.get("option_tail_demand_score")},
        {"Metric": "Option lottery score", "Value": om.get("option_lottery_score")},
        {"Metric": "Convexity concentration", "Value": om.get("convexity_concentration_score")},
        {"Metric": "Chain rows", "Value": om.get("rows")},
    ]
    st.dataframe(pd.DataFrame(o_rows), use_container_width=True, hide_index=True)
    st.caption(str(opt.get("scope", "Current public option snapshot; not signed dealer order flow.")))

    st.markdown("<div class='psy-section'>Provider / Identification Status</div>", unsafe_allow_html=True)
    status_rows = [
        {"Block": "Volatility / tail", "Status": "OK" if vol.get("coverage",0) >= vol.get("coverage_total",5) else "PARTIAL" if vol.get("coverage",0) > 0 else "MISSING", "Coverage": f"{vol.get('coverage',0)}/{vol.get('coverage_total',5)}", "Identification": "Observed volatility-index prices; not direct fear."},
        {"Block": "Breadth / participation", "Status": "OK" if breadth.get("available") else "PARTIAL" if breadth.get("coverage",0) > 0 else "MISSING", "Coverage": f"{breadth.get('coverage',0)}/{breadth.get('coverage_total',0)} ETFs · core {breadth.get('core_coverage',0)}/{breadth.get('core_total',7)}", "Identification": "ETF-based breadth proxy; not constituent A/D breadth."},
        {"Block": "CFTC positioning", "Status": "OK" if positioning.get("available") else "MISSING", "Coverage": str(pm.get("as_of", "N/A")), "Identification": "Weekly broad-market futures positioning; not single-stock positioning."},
        {"Block": "Funding / credit", "Status": "OK" if funding.get("available") else "MISSING", "Coverage": f"{funding.get('coverage',0)}/{funding.get('coverage_total',0)} series", "Identification": "Observed public credit/financial-conditions data."},
        {"Block": "Options behavior", "Status": "OK" if opt.get("available") else "MISSING", "Coverage": f"{om.get('rows',0)} rows", "Identification": "Current public chain; no historical OPRA / signed dealer gamma."},
        {"Block": "Short interest / borrow", "Status": "OK" if short_interest.get("available") else "MISSING", "Coverage": short_interest.get("status", "N/A"), "Identification": short_interest.get("note", "Dedicated feed required.")},
    ]
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)

def _render_analogues(state: dict[str, Any]) -> None:
    memory = state.get("memory", {}) if isinstance(state.get("memory", {}), dict) else {}
    st.markdown("<div class='psy-section'>Behavioral Memory / Associative Retrieval · V2.3.2</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='psy-ident'>V2.3.2 retrieves prior <b>multi-domain market episodes</b>, not just similar price paths. "
        "State similarity, episode salience and recency are shown separately. Historical narrative/options data are admitted only when a point-in-time snapshot was actually archived; they are never backfilled. "
        "Funding history is explicitly down-weighted because standard FRED history is current-vintage rather than ALFRED vintage-locked.</div>",
        unsafe_allow_html=True,
    )
    if not memory.get("available"):
        st.warning(memory.get("reason", "Behavioral-memory retrieval unavailable."))
        return

    analogues = memory.get("analogues", pd.DataFrame())
    structural = memory.get("structural_analogues", memory.get("reliable_analogues", pd.DataFrame()))
    memory_candidates = memory.get("memory_candidates", pd.DataFrame())
    archive = memory.get("archive", {}) if isinstance(memory.get("archive", {}), dict) else {}
    best = memory.get("best_similarity")
    activation = memory.get("memory_activation_score")
    usable_domains = int(memory.get("historically_usable_domains", 0) or 0)
    domain_total = int(memory.get("domain_total", 8) or 8)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Memory candidates", str(len(memory_candidates)) if isinstance(memory_candidates, pd.DataFrame) else "0")
    c2.metric("Structural analogues", str(len(structural)) if isinstance(structural, pd.DataFrame) else "0")
    c3.metric("Best similarity", f"{_fmt_num(best,1)}/100")
    c4.metric("Memory activation", f"{_fmt_num(activation,1)}/100")
    c5.metric("Historical domains", f"{usable_domains}/{domain_total}")
    c6.metric("PIT snapshots", str(archive.get("snapshots", 0)))

    if float(memory.get("history_years", 0) or 0) < 4.0:
        st.info("SHORT MEMORY HORIZON — this run contains less than four years of history. Use 5Y (then 10Y) before locking retrieval thresholds or interpreting regime diversity.")

    if memory.get("no_structural_analogue", memory.get("no_reliable_analogue")):
        st.warning(
            f"NO STRUCTURAL ANALOGUE — no spaced episode clears adaptive similarity {memory.get('similarity_threshold',65):.0f}/100, "
            f"coverage {100*memory.get('min_coverage',.60):.0f}% and the observed-domain gate. Nearest states remain research context only."
        )
    else:
        st.success(
            f"Observed-domain structural analogues found. Memory candidates additionally require activation ≥ {memory.get('activation_threshold',55):.0f}/100. "
            "Narrative/options remain partial-domain until real PIT history accumulates; forward outcomes are descriptive, not forecasts."
        )

    tags = memory.get("current_tags", [])
    if tags:
        st.caption("Current retrieval cues: " + " · ".join(map(str, tags)))

    if analogues is None or not isinstance(analogues, pd.DataFrame) or analogues.empty:
        st.info("No spaced historical episode has sufficient overlapping domains.")
    else:
        st.markdown("<div class='psy-section'>Retrieved Episodes</div>", unsafe_allow_html=True)
        display_cols = [
            "date", "Similarity", "Activation", "Coverage", "Retrieval class", "Salience", "Recency",
            "Tags", "Why retrieved", "Main mismatch", "fwd_20d", "fwd_60d", "fwd_worst60",
        ]
        display = analogues[[c for c in display_cols if c in analogues.columns]].copy()
        if "date" in display.columns:
            display["date"] = pd.to_datetime(display["date"], errors="coerce").dt.date
        for col in ["Similarity", "Activation", "Coverage", "Salience", "Recency"]:
            if col in display.columns:
                display[col] = pd.to_numeric(display[col], errors="coerce").map(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
        for col in ["fwd_20d", "fwd_60d", "fwd_worst60"]:
            if col in display.columns:
                display[col] = display[col].map(_fmt_pct)
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown("<div class='psy-section'>Memory Retrieval Map · Similarity × Salience</div>", unsafe_allow_html=True)
        fig = go.Figure()
        plot_df = analogues.copy()
        plot_df["date_label"] = pd.to_datetime(plot_df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        activation_rank = pd.to_numeric(plot_df["Activation"], errors="coerce").rank(method="first", ascending=False)
        plot_df["visible_label"] = np.where(activation_rank <= 3, plot_df["date_label"], "")
        colors = pd.to_numeric(plot_df.get("fwd_60d", np.nan), errors="coerce")
        class_series = plot_df.get("Retrieval class", plot_df.get("Reliability", pd.Series("PARTIAL", index=plot_df.index))).astype(str)
        symbols = class_series.map({
            "MEMORY CANDIDATE": "diamond",
            "STRUCTURAL ANALOGUE": "circle",
            "PARTIAL": "square",
            "WEAK": "x",
        }).fillna("circle")
        fig.add_trace(go.Scatter(
            x=pd.to_numeric(plot_df["Similarity"], errors="coerce"),
            y=pd.to_numeric(plot_df["Salience"], errors="coerce"),
            mode="markers+text",
            text=plot_df["visible_label"],
            textposition="top center",
            marker={
                "size": np.clip(pd.to_numeric(plot_df["Activation"], errors="coerce").fillna(30) / 3.0, 10, 30),
                "color": colors,
                "symbol": symbols,
                "colorscale": "RdYlGn",
                "cmid": 0,
                "showscale": True,
                "colorbar": {"title": "60D fwd"},
                "line": {"width": 1, "color": "rgba(255,255,255,.45)"},
            },
            customdata=np.stack([
                plot_df["date_label"].astype(str),
                class_series,
                pd.to_numeric(plot_df["Coverage"], errors="coerce").fillna(np.nan),
                plot_df["Tags"].astype(str),
                pd.to_numeric(plot_df["Activation"], errors="coerce").fillna(np.nan),
            ], axis=1),
            hovertemplate="%{customdata[0]}<br>Similarity %{x:.1f}<br>Salience %{y:.1f}<br>Activation %{customdata[4]:.1f}<br>%{customdata[1]}<br>Coverage %{customdata[2]:.0f}%<br>%{customdata[3]}<extra></extra>",
        ))
        fig.add_vline(x=float(memory.get("similarity_threshold", 65)), line_dash="dot", opacity=.55)
        fig.update_layout(
            height=390,
            margin=dict(l=20, r=20, t=15, b=20),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="State similarity",
            yaxis_title="Episode salience",
            xaxis=dict(range=[0, 100], gridcolor="rgba(255,255,255,.07)"),
            yaxis=dict(range=[0, 100], gridcolor="rgba(255,255,255,.07)"),
            font=dict(color="rgba(230,240,250,.82)"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.markdown("<div class='psy-section'>Why Was This Episode Retrieved?</div>", unsafe_allow_html=True)
        labels = [pd.to_datetime(x, errors="coerce").strftime("%Y-%m-%d") for x in analogues["date"]]
        selected_label = st.selectbox("Episode diagnostic", labels, key="psy_memory_episode")
        selected_idx = labels.index(selected_label)
        row = analogues.iloc[selected_idx]
        sim_cols = [c for c in analogues.columns if str(c).startswith("sim::")]
        domain_rows = []
        for c in sim_cols:
            v = pd.to_numeric(pd.Series([row.get(c)]), errors="coerce").iloc[0]
            if pd.notna(v):
                domain_rows.append({"Domain": str(c).split("sim::",1)[1], "Similarity": float(v)})
        if domain_rows:
            ddf = pd.DataFrame(domain_rows).sort_values("Similarity", ascending=True)
            dfig = go.Figure(go.Bar(
                x=ddf["Similarity"], y=ddf["Domain"], orientation="h",
                text=ddf["Similarity"].map(lambda x: f"{x:.0f}"), textposition="outside",
            ))
            dfig.add_vline(x=float(memory.get("domain_cue_threshold",62)), line_dash="dot", opacity=.5)
            dfig.update_layout(
                height=max(280, 42*len(ddf)+80), margin=dict(l=20,r=35,t=10,b=20),
                xaxis=dict(range=[0,100], title="Domain similarity", gridcolor="rgba(255,255,255,.07)"),
                yaxis_title="", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="rgba(230,240,250,.82)"), showlegend=False,
            )
            st.plotly_chart(dfig, use_container_width=True, config={"displayModeBar": False})
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Strong matching cues**")
            st.write(row.get("Why retrieved", "N/A"))
            st.markdown("**Episode tags**")
            st.write(row.get("Tags", "N/A"))
        with cc2:
            st.markdown("**Main mismatches**")
            st.write(row.get("Main mismatch", "N/A"))
            st.markdown("**Retrieval class / coverage**")
            st.write(f"{row.get('Retrieval class', row.get('Reliability','N/A'))} · coverage {_fmt_num(row.get('Coverage'),1)}% · activation {_fmt_num(row.get('Activation'),1)}/100")

    ensemble = memory.get("ensemble", {}) if isinstance(memory.get("ensemble", {}), dict) else {}
    st.markdown("<div class='psy-section'>Analogue Ensemble · Descriptive Only</div>", unsafe_allow_html=True)
    e1,e2,e3,e4,e5,e6 = st.columns(6)
    e1.metric("Episodes", str(ensemble.get("count",0)))
    e2.metric("Median +20D", _fmt_pct(ensemble.get("median_20d")))
    e3.metric("Median +60D", _fmt_pct(ensemble.get("median_60d")))
    e4.metric("Positive +20D", _fmt_pct(ensemble.get("positive_20d_share")))
    e5.metric("Median worst 60D", _fmt_pct(ensemble.get("median_worst60")))
    e6.metric("Median future vol", _fmt_pct(ensemble.get("median_future_vol20")))
    st.caption("These outcomes are ex-post labels attached to already-historical episodes. They are never inputs to current memory retrieval and must not be interpreted as a forecast without walk-forward validation.")

    st.markdown("<div class='psy-section'>Memory Domain Coverage / Temporal Integrity</div>", unsafe_allow_html=True)
    domain_coverage = memory.get("domain_coverage", pd.DataFrame())
    if isinstance(domain_coverage, pd.DataFrame) and not domain_coverage.empty:
        st.dataframe(domain_coverage, use_container_width=True, hide_index=True)

    st.markdown("<div class='psy-section'>Point-in-Time Memory Archive</div>", unsafe_allow_html=True)
    a1,a2,a3,a4 = st.columns(4)
    a1.metric("Derived snapshots", str(archive.get("snapshots",0)))
    a2.metric("Narrative history", "READY" if archive.get("narrative_history_ready") else "BUILDING")
    a3.metric("Options history", "READY" if archive.get("options_history_ready") else "BUILDING")
    a4.metric("Archive write", str(archive.get("status","N/A")))
    st.caption(
        "The archive stores derived daily state summaries only — no raw articles, passwords or API keys. "
        "Narrative/options historical similarity remains unavailable until real snapshots accumulate; V2.3.2 never reconstructs them retrospectively. "
        "Runtime snapshots are stored in `market_psychology/memory/` and ignored by the package-level .gitignore."
    )
    st.caption(str(memory.get("method_note", "")))



def _render_external_replication(state: dict[str, Any]) -> None:
    """V2.5.3 frozen-spec cross-asset transfer test.

    This is deliberately separate from the SPY development/holdout family.  It does
    not tune any model parameter and it does not use Narrative/Options/Memory to claim
    cross-asset portability.
    """
    st.markdown("<div class='psy-section'>V2.5.3 · External replication · frozen specification</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='psy-ident'>"
        "SPY is the anchor research asset and is <b>not</b> counted as external evidence here. "
        "The exact frozen historical proxy → causal-normalization → latent-state → V2.4.1 walk-forward/holdout stack is replayed on untouched assets. "
        "No threshold or equation is re-estimated from external outcomes. The primary transfer test is <b>CORE ONLY</b>: Attention, Fear, Herding, Extrapolation and Reflexivity. "
        "Narrative/options and Behavioral Memory remain separate research families until their point-in-time archives are mature enough for a fair transfer claim. <b>V2.5.3 changes data resilience only</b>: each external target uses a true uncached provider waterfall for at most one bounded retry, then may fall back only to a validated closed-session local cache."
        "</div>",
        unsafe_allow_html=True,
    )

    with st.form("psy_external_replication_controls_v25"):
        ec1, ec2, ec3 = st.columns([1.7, .8, .9], vertical_alignment="bottom")
        with ec1:
            selected = st.multiselect(
                "Untouched external assets",
                list(ALLOWED_EXTERNAL_UNIVERSE),
                default=list(DEFAULT_EXTERNAL_UNIVERSE),
                help="QQQ / IWM / DIA are the preferred broad-market transfer set. Single names are optional portability stress tests and should not be used to tune the frozen specification.",
            )
        with ec2:
            ext_profile = st.selectbox(
                "External profile",
                ["STANDARD", "DEEP"],
                index=0,
                key="psy_external_profile_v25",
                help="STANDARD is recommended first. DEEP increases bootstrap draws only; it does not alter the frozen model.",
            )
        with ec3:
            run_external = st.form_submit_button("RUN EXTERNAL REPLICATION", use_container_width=True, type="primary")

    clean_selected = [str(x).upper() for x in selected if str(x).strip()]
    ext_fp = f"{'|'.join(clean_selected)}|5y|{ext_profile}|V2.5.3"
    if run_external:
        if not clean_selected:
            st.warning("Select at least one external asset.")
        elif len(clean_selected) > 4:
            st.warning("For provider/rate-limit discipline, run at most four external assets in one batch.")
        else:
            with st.spinner("Running frozen external replication. No model recalibration is performed…"):
                ext_bundle = run_external_batch(clean_selected, period="5y", profile=ext_profile)
            st.session_state["psy_external_validation_bundle_v25"] = ext_bundle
            st.session_state["psy_external_validation_fingerprint_v25"] = ext_fp

    ext_bundle = st.session_state.get("psy_external_validation_bundle_v25")
    if st.session_state.get("psy_external_validation_fingerprint_v25") != ext_fp:
        ext_bundle = None

    if not isinstance(ext_bundle, dict):
        st.info("Run the explicit external-replication batch above. Results are intentionally cached separately from the SPY research holdout and are never used to recalibrate it.")
        return

    asset_summary = ext_bundle.get("asset_summary", pd.DataFrame())
    if isinstance(asset_summary, pd.DataFrame) and not asset_summary.empty:
        a1, a2, a3, a4 = st.columns(4)
        ok = int(asset_summary["Status"].eq("OK").sum()) if "Status" in asset_summary.columns else 0
        stat = int(pd.to_numeric(asset_summary.get("Core stat replicated"), errors="coerce").fillna(0).sum()) if "Core stat replicated" in asset_summary.columns else 0
        directional = int(pd.to_numeric(asset_summary.get("Directional confirmations"), errors="coerce").fillna(0).sum()) if "Directional confirmations" in asset_summary.columns else 0
        robust = int(pd.to_numeric(asset_summary.get("Robust OOS"), errors="coerce").fillna(0).sum()) if "Robust OOS" in asset_summary.columns else 0
        a1.metric("External assets usable", f"{ok}/{len(asset_summary)}")
        a2.metric("External robust OOS", str(robust))
        a3.metric("External stat replications", str(stat))
        a4.metric("External directional confirmations", str(directional))
        st.dataframe(asset_summary, use_container_width=True, hide_index=True)
        source_modes = asset_summary.loc[asset_summary["Status"].eq("OK"), "Source mode"].astype(str).value_counts().to_dict() if "Source mode" in asset_summary.columns else {}
        if source_modes:
            source_note = " · ".join(f"{k}: {v}" for k, v in source_modes.items())
            st.caption(f"External target data sources · {source_note}. VALIDATED LOCAL CACHE is closed-session OHLCV previously fetched from a live provider; it never contains model outputs or outcomes.")
        ends = ext_bundle.get("validation_ends", []) if isinstance(ext_bundle.get("validation_ends", []), list) else []
        baseline_eligible = bool(ext_bundle.get("baseline_eligible"))
        baseline_reason = str(ext_bundle.get("baseline_reason", ""))
        if baseline_eligible:
            st.success(f"BASELINE ELIGIBILITY · {baseline_reason}")
        else:
            st.warning(f"BASELINE ELIGIBILITY · {baseline_reason or 'NOT ELIGIBLE'}")

        if ext_bundle.get("validation_end_aligned") and ends:
            st.caption(f"External validation-end alignment: FULLY ALIGNED · {ends[0]}")
        elif ends:
            st.warning("External validation-end alignment: PARTIAL / NOT BASELINE-ELIGIBLE · " + ", ".join(map(str, ends)))

    # Provider failures are explicit instead of silently dropping an asset.
    results_for_diag = [r for r in ext_bundle.get("results", []) if isinstance(r, dict)]
    if results_for_diag:
        diag_rows = []
        for r in results_for_diag:
            state_r = r.get("state", {}) if isinstance(r.get("state", {}), dict) else {}
            attempts = state_r.get("provider_attempts", r.get("provider_attempts", []))
            attempts = attempts if isinstance(attempts, list) else []
            if not attempts and not r.get("available"):
                diag_rows.append({"Asset": r.get("symbol"), "Provider": "N/A", "Status": "UNAVAILABLE", "HTTP": "", "Detail": r.get("reason", "")})
            for a in attempts:
                if not isinstance(a, dict):
                    continue
                diag_rows.append({
                    "Asset": r.get("symbol"),
                    "Provider": a.get("provider"),
                    "Status": a.get("status"),
                    "HTTP": a.get("http", ""),
                    "Rows": a.get("rows", ""),
                    "Pass": a.get("pass", ""),
                    "Detail": a.get("detail", ""),
                })
        with st.expander("External provider / validated-cache diagnostics", expanded=False):
            if diag_rows:
                st.dataframe(pd.DataFrame(diag_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No provider diagnostic rows were recorded for this batch.")

    support = ext_bundle.get("support", pd.DataFrame())
    if isinstance(support, pd.DataFrame) and not support.empty:
        st.markdown("<div class='psy-section'>Cross-asset external support map</div>", unsafe_allow_html=True)
        st.caption("This is a replication summary, not a new hypothesis test. CONSISTENT EXTERNAL SUPPORT requires at least two untouched assets with MODERATE/HIGH evidence and broadly consistent OOS sign. No parameter is changed in response to this table.")
        support_display = support.copy()
        if "Sign consensus" in support_display.columns:
            support_display["Sign consensus"] = pd.to_numeric(support_display["Sign consensus"], errors="coerce").map(lambda x: f"{x:.0%}" if pd.notna(x) else "N/A")
        st.dataframe(support_display, use_container_width=True, hide_index=True)

        # Fast visual map: fraction of evaluable external assets that reach MODERATE/HIGH.
        vis = support.copy()
        denom = pd.to_numeric(vis["Assets evaluable"], errors="coerce").replace(0, np.nan)
        vis["Support ratio"] = pd.to_numeric(vis["Moderate/High"], errors="coerce") / denom
        piv = vis.pivot_table(index="Mechanism", columns="Target", values="Support ratio", aggfunc="first")
        cnt = vis.pivot_table(index="Mechanism", columns="Target", values="Moderate/High", aggfunc="first")
        ncnt = vis.pivot_table(index="Mechanism", columns="Target", values="Assets evaluable", aggfunc="first")
        if not piv.empty:
            text = np.empty(piv.shape, dtype=object)
            for i, m in enumerate(piv.index):
                for j, t in enumerate(piv.columns):
                    a = cnt.loc[m, t] if m in cnt.index and t in cnt.columns else np.nan
                    n = ncnt.loc[m, t] if m in ncnt.index and t in ncnt.columns else np.nan
                    text[i, j] = f"{int(a)}/{int(n)}" if pd.notna(a) and pd.notna(n) and n else "N/A"
            fig = go.Figure(go.Heatmap(
                z=piv.to_numpy(dtype=float), x=list(piv.columns), y=list(piv.index),
                zmin=0, zmax=1,
                colorscale=[[0,"#431926"],[0.5,"#8f7520"],[1,"#188b79"]],
                text=text, texttemplate="%{text}",
                colorbar={"title": "MOD/HIGH ratio"},
                hovertemplate="%{y}<br>%{x}<br>external MOD/HIGH ratio %{z:.0%}<extra></extra>",
            ))
            fig.update_layout(height=330, margin=dict(l=20,r=20,t=15,b=50), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="rgba(230,240,250,.82)"))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    evidence_long = ext_bundle.get("evidence_long", pd.DataFrame())
    if isinstance(evidence_long, pd.DataFrame) and not evidence_long.empty:
        st.markdown("<div class='psy-section'>External asset evidence matrices</div>", unsafe_allow_html=True)
        for asset in [x for x in clean_selected if x in set(evidence_long["Asset"].astype(str))]:
            with st.expander(f"{asset} · frozen V2.4.1 evidence matrix", expanded=False):
                sub = evidence_long[evidence_long["Asset"].astype(str) == asset].copy()
                piv = sub.pivot_table(index="Mechanism", columns="Target", values="Evidence", aggfunc="first").reset_index()
                if not piv.empty:
                    cols = [c for c in piv.columns if c != "Mechanism"]
                    st.dataframe(piv.style.map(_evidence_style, subset=cols), use_container_width=True, hide_index=True)

    st.caption(str(ext_bundle.get("note", "")))
    st.download_button(
        "DOWNLOAD V2.5.3 EXTERNAL REPLICATION AUDIT JSON",
        data=external_bundle_json_bytes(ext_bundle),
        file_name="market_psychology_v2_5_2_external_replication.json",
        mime="application/json",
        use_container_width=True,
    )

def _render_validation(state: dict[str, Any]) -> None:
    quality = build_data_quality_table(state)
    st.markdown("<div class='psy-section'>Data quality / identification</div>", unsafe_allow_html=True)
    if not quality.empty:
        st.dataframe(quality, use_container_width=True, hide_index=True)

    st.markdown("<div class='psy-section'>Latent filter diagnostic — measurement layer</div>", unsafe_allow_html=True)
    filter_diag = build_latent_filter_diagnostics(state.get("history", pd.DataFrame()))
    if filter_diag.empty:
        st.info("Latent filter diagnostics unavailable.")
    else:
        st.dataframe(filter_diag, use_container_width=True, hide_index=True)
        st.caption("Noise reduction / persistence diagnose the filter mechanics only; they do not establish predictive value.")

    st.markdown("<div class='psy-section'>V2.4.1 · Point-in-time / walk-forward evidence classification</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='psy-ident'>"
        "The behavioral state, alarm and memory specifications remain frozen. V2.4.1 keeps the V2.4 chronology/inference unchanged and adds stricter evidence classification. V2.4.1 uses expanding chronological folds, "
        "purges each training sample by the forecast horizon, reserves a separate final holdout, applies train-derived quintile thresholds unchanged to test data, "
        "uses HAC/Newey-West inference for overlapping labels, moving-block bootstrap intervals and Benjamini-Hochberg FDR across the development hypothesis family. "
        "This section is allowed to return <b>NO EVIDENCE</b>."
        "</div>",
        unsafe_allow_html=True,
    )

    vcol1, vcol2 = st.columns([1.0, 1.6], vertical_alignment="bottom")
    with vcol1:
        validation_profile = st.selectbox(
            "Validation profile",
            ["STANDARD", "DEEP"],
            index=0,
            key="psy_validation_profile",
            help="DEEP increases moving-block bootstrap draws and evaluates the Memory Engine on a denser historical grid. It does not change the model specification.",
        )
    with vcol2:
        run_validation = st.button("RUN WALK-FORWARD / HOLDOUT", use_container_width=True, type="primary")

    # V2.5.1 validation clock: live monitoring can use an in-progress session,
    # while all research validation is hard-cut to the last fully closed US daily
    # bar under a conservative 16:30 ET finalization policy.
    validation_state, cutoff_meta = closed_session_validation_state(state)
    history = validation_state.get("history", pd.DataFrame())
    try:
        hist_end = str(pd.to_datetime(history["date"], errors="coerce", utc=True).max()) if isinstance(history, pd.DataFrame) and not history.empty else "N/A"
    except Exception:
        hist_end = "N/A"
    validation_fingerprint = f"{state.get('symbol','SPY')}|{len(history) if isinstance(history,pd.DataFrame) else 0}|{hist_end}|{cutoff_meta.get('cutoff_date')}|{validation_profile}|V2.5.1"

    removed = int(cutoff_meta.get("history_rows_removed", 0) or 0)
    live_last = cutoff_meta.get("history_source_last_date") or "N/A"
    closed_last = cutoff_meta.get("history_validation_last_date") or cutoff_meta.get("cutoff_date") or "N/A"
    cutoff_text = (
        f"Validation clock: last fully closed US daily session = {closed_last} · "
        f"policy {cutoff_meta.get('eligible_after_et','16:30')} ET finalization buffer."
    )
    if removed > 0:
        cutoff_text += f" Live monitoring contains {removed} later/in-progress row(s) through {live_last}; those rows are excluded from validation."
    st.caption(cutoff_text)

    if run_validation:
        with st.spinner("Running frozen V2.4 walk-forward/holdout calculations on fully closed daily sessions only…"):
            bundle = build_walk_forward_validation_bundle(validation_state, profile=validation_profile)
        if isinstance(bundle, dict):
            bundle["validation_cutoff"] = cutoff_meta
            manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest", {}), dict) else {}
            manifest["closed_session_cutoff"] = cutoff_meta
            manifest["live_monitoring_history_last_date"] = live_last
            bundle["manifest"] = manifest
        st.session_state["psy_oos_validation_bundle"] = bundle
        st.session_state["psy_oos_validation_fingerprint"] = validation_fingerprint

    bundle = st.session_state.get("psy_oos_validation_bundle")
    bundle_fp = st.session_state.get("psy_oos_validation_fingerprint")
    if not isinstance(bundle, dict) or bundle_fp != validation_fingerprint:
        nrows = len(history) if isinstance(history, pd.DataFrame) else 0
        if nrows < 450:
            st.warning("V2.4.1 requires roughly 450+ daily observations. Use 2Y/5Y/10Y history; 5Y is preferred for a meaningful final holdout.")
        else:
            st.info("Run the explicit V2.4.1 validation above. It is intentionally not executed on every Streamlit rerun because the Memory walk-forward is computationally heavier than the live state engine.")
    elif not bundle.get("available"):
        st.error(bundle.get("reason", "Walk-forward validation unavailable."))
    else:
        mech = bundle.get("mechanisms", {}) if isinstance(bundle.get("mechanisms", {}), dict) else {}
        manifest = bundle.get("manifest", {}) if isinstance(bundle.get("manifest", {}), dict) else {}
        dev = mech.get("development", pd.DataFrame())
        hold = mech.get("holdout", pd.DataFrame())
        confirm = mech.get("confirmation", pd.DataFrame())
        splits = mech.get("splits", pd.DataFrame())

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Walk-forward folds", str(max(0, int(len(splits) - (1 if isinstance(splits, pd.DataFrame) and not splits.empty and (splits["Partition"] == "HOLDOUT").any() else 0)))))
        k2.metric("Hypotheses", str(mech.get("hypotheses", 0)))
        k3.metric("FDR survivors", str(mech.get("fdr_survivors", 0)))
        k4.metric("Robust OOS", str(mech.get("robust_oos", 0)))
        k5.metric("Core stat replicated", str(mech.get("statistically_replicated", 0)), help="Statistical holdout replications inside the frozen core mechanism family only. Behavioral Memory has its own separate evidence family below.")
        k6.metric("Core directional confirmations", str(mech.get("directionally_confirmed", 0)), help="Same-sign core holdout effects that do not clear the strict statistical replication rule.")

        st.caption(
            f"Validation {bundle.get('version','V2.4.1')} · {manifest.get('profile','N/A')} · "
            f"history {str(manifest.get('history_start',''))[:10]} → {str(manifest.get('history_end',''))[:10]} · "
            f"minimum train {manifest.get('min_train_rows','N/A')} rows · final holdout {manifest.get('holdout_rows','N/A')} rows."
        )

        st.markdown("<div class='psy-section'>Chronological split / purge audit</div>", unsafe_allow_html=True)
        if isinstance(splits, pd.DataFrame) and not splits.empty:
            split_display = splits.copy()
            for c in ["Train end (pre-purge)", "Test start", "Test end"]:
                if c in split_display.columns:
                    split_display[c] = pd.to_datetime(split_display[c], errors="coerce").dt.date
            st.dataframe(split_display, use_container_width=True, hide_index=True)
        st.caption("For each mechanism/horizon test, V2.4.1 preserves the V2.4 purge rule and purges the final h training observations before the next test block so forward labels cannot overlap the test period.")

        coverage_table = mech.get("coverage", pd.DataFrame())
        if isinstance(coverage_table, pd.DataFrame) and not coverage_table.empty:
            st.markdown("<div class='psy-section'>Mechanism validation coverage</div>", unsafe_allow_html=True)
            cv = coverage_table.copy()
            if "Coverage" in cv.columns:
                cv["Coverage"] = pd.to_numeric(cv["Coverage"], errors="coerce").map(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
            for c in ["First valid", "Last valid"]:
                if c in cv.columns:
                    cv[c] = pd.to_datetime(cv[c], errors="coerce").dt.date
            st.dataframe(cv, use_container_width=True, hide_index=True)
            st.caption("A mechanism can have less validation history than the target price series. Long constant raw-proxy plateaus are treated as unavailable rather than as real neutral psychology.")

        evidence_matrix = mech.get("evidence_matrix", pd.DataFrame())
        if isinstance(evidence_matrix, pd.DataFrame) and not evidence_matrix.empty:
            st.markdown("<div class='psy-section'>Mechanism evidence matrix · OOS + holdout only</div>", unsafe_allow_html=True)
            styled = evidence_matrix.style.map(_evidence_style, subset=[c for c in evidence_matrix.columns if c != "Mechanism"])
            st.dataframe(styled, use_container_width=True, hide_index=True)
            st.caption("Objective classification only: HIGH requires repeated ROBUST OOS evidence plus at least one statistically replicated holdout result; MODERATE requires robust OOS plus holdout confirmation; LOW is development evidence without strong replication; NONE means no surviving predictive evidence; N/A means insufficient validation coverage.")
            evidence_details = mech.get("evidence_details", pd.DataFrame())
            if isinstance(evidence_details, pd.DataFrame) and not evidence_details.empty:
                with st.expander("Evidence matrix rule audit", expanded=False):
                    det = evidence_details.copy()
                    if "Coverage" in det.columns:
                        det["Coverage"] = pd.to_numeric(det["Coverage"], errors="coerce").map(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
                    st.dataframe(det, use_container_width=True, hide_index=True)

        st.markdown("<div class='psy-section'>Development walk-forward · full hypothesis family</div>", unsafe_allow_html=True)
        if isinstance(dev, pd.DataFrame) and not dev.empty:
            dev_display = dev.copy()
            pct_cols = []
            num_cols = ["OOS IC", "HAC t", "HAC p", "FDR q", "Bootstrap CI low", "Bootstrap CI high", "High - low", "Fold IC median", "Fold sign stability", "Tail event rate risk bucket", "Tail event baseline", "Tail event lift"]
            for c in num_cols:
                if c in dev_display.columns:
                    dev_display[c] = pd.to_numeric(dev_display[c], errors="coerce").round(4)
            st.dataframe(dev_display, use_container_width=True, hide_index=True)

            heat = dev.copy()
            heat["Column"] = heat["Target"].astype(str) + " · " + heat["Horizon"].astype(str)
            pivot = heat.pivot_table(index="Mechanism", columns="Column", values="OOS IC", aggfunc="first")
            if not pivot.empty:
                st.markdown("<div class='psy-section'>OOS IC map · mechanism × target</div>", unsafe_allow_html=True)
                fig = go.Figure(go.Heatmap(
                    z=pivot.to_numpy(dtype=float),
                    x=list(pivot.columns), y=list(pivot.index),
                    zmin=-0.35, zmax=0.35, zmid=0,
                    colorscale="RdBu", reversescale=True,
                    text=np.where(np.isfinite(pivot.to_numpy(dtype=float)), np.round(pivot.to_numpy(dtype=float), 2).astype(str), ""),
                    texttemplate="%{text}",
                    colorbar={"title": "OOS IC"},
                    hovertemplate="%{y}<br>%{x}<br>IC %{z:.3f}<extra></extra>",
                ))
                fig.update_layout(
                    height=350, margin=dict(l=20,r=20,t=15,b=70),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="rgba(230,240,250,.82)"),
                )
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info("No development walk-forward result survived the minimum observation requirements.")

        st.markdown("<div class='psy-section'>Final holdout replication</div>", unsafe_allow_html=True)
        if isinstance(confirm, pd.DataFrame) and not confirm.empty:
            conf_display = confirm.copy()
            for c in ["Dev IC", "Dev q", "Dev stability", "Holdout IC", "Holdout p", "Holdout CI low", "Holdout CI high"]:
                if c in conf_display.columns:
                    conf_display[c] = pd.to_numeric(conf_display[c], errors="coerce").round(4)
            st.dataframe(conf_display, use_container_width=True, hide_index=True)
            st.caption("STATISTICALLY REPLICATED requires ROBUST OOS development evidence, the same holdout sign, |holdout IC| ≥ 0.03, holdout p ≤ 0.10 and a holdout bootstrap CI excluding zero. DIRECTIONALLY CONFIRMED means same sign without that statistical precision. INCONCLUSIVE is insufficiently precise; FAILED REPLICATION requires statistically informative contradictory holdout evidence. None of these statuses is production approval.")
        elif isinstance(hold, pd.DataFrame) and not hold.empty:
            st.dataframe(hold, use_container_width=True, hide_index=True)
        else:
            st.info("A separate final holdout could not be formed at this history length.")

        st.markdown("<div class='psy-section'>Acute alarm event study · OOS evaluation windows</div>", unsafe_allow_html=True)
        alarm_evidence = bundle.get("alarm_evidence", pd.DataFrame())
        if isinstance(alarm_evidence, pd.DataFrame) and not alarm_evidence.empty:
            st.dataframe(alarm_evidence, use_container_width=True, hide_index=True)
            st.caption("Alarm severity remains a state-monitoring concept. Predictive validation is NONE unless the fixed alarm definition survives development FDR + bootstrap CI and then receives holdout confirmation; a red/critical alarm must not be interpreted as a trade instruction.")
        alarm_study = bundle.get("alarms", pd.DataFrame())
        if isinstance(alarm_study, pd.DataFrame) and not alarm_study.empty:
            alarm_display = alarm_study.copy()
            for c in ["Event mean", "Baseline mean", "Event - baseline", "Bootstrap CI low", "Bootstrap CI high", "Bootstrap p", "FDR q"]:
                if c in alarm_display.columns:
                    alarm_display[c] = pd.to_numeric(alarm_display[c], errors="coerce").round(4)
            st.dataframe(alarm_display, use_container_width=True, hide_index=True)
            st.caption("Alarm definitions are fixed by the live engine. Only first HIGH/CRITICAL onsets enter the event study; event outcomes are compared with the unconditional outcome distribution in the same chronological partition.")
        else:
            st.info("Too few HIGH/CRITICAL alarm onsets exist in the OOS windows for an event-study estimate.")

        st.markdown("<div class='psy-section'>Behavioral Memory · historical decision-time validation</div>", unsafe_allow_html=True)
        memory_val = bundle.get("memory", {}) if isinstance(bundle.get("memory", {}), dict) else {}
        if memory_val.get("available"):
            mem_evidence = memory_val.get("evidence", {}) if isinstance(memory_val.get("evidence", {}), dict) else {}
            mr1, mr2, mr3, mr4 = st.columns(4)
            mr1.metric("Role", str(mem_evidence.get("role", "CONTEXTUAL / DESCRIPTIVE")))
            raw_mem_status = str(mem_evidence.get("predictive_status", "NO PREDICTIVE EVIDENCE"))
            display_mem_status = "LIMITED STATISTICAL REPLICATION" if raw_mem_status == "STATISTICALLY REPLICATED" else raw_mem_status
            mr2.metric("Predictive status", display_mem_status, help="Behavioral Memory remains contextual/descriptive. LIMITED STATISTICAL REPLICATION means at least one pre-specified Memory relationship replicated statistically; it does not imply return-forecast validity.")
            mr3.metric("Dev FDR survivors", str(mem_evidence.get("development_fdr_survivors", 0)))
            mr4.metric("Holdout stat replications", str(mem_evidence.get("holdout_statistical_replications", 0)))
            st.caption(f"Holdout same-sign confirmations: {mem_evidence.get('holdout_directional_confirmations', 0)}. V2.4.1 reports them descriptively but does not upgrade Behavioral Memory's predictive status without statistical holdout replication.")
            mem_summary = memory_val.get("summary", pd.DataFrame())
            if isinstance(mem_summary, pd.DataFrame) and not mem_summary.empty:
                mem_display = mem_summary.copy()
                for c in ["Coverage", "Return IC", "Return p", "Return sign hit", "Vol IC", "Vol p", "Tail IC", "Tail p", "Median candidates", "Median similarity", "Median activation"]:
                    if c in mem_display.columns:
                        mem_display[c] = pd.to_numeric(mem_display[c], errors="coerce").round(4)
                st.dataframe(mem_display, use_container_width=True, hide_index=True)
            family = memory_val.get("fdr_family", pd.DataFrame())
            if isinstance(family, pd.DataFrame) and not family.empty:
                with st.expander("Memory FDR family", expanded=False):
                    st.dataframe(family.round(4), use_container_width=True, hide_index=True)
            st.caption(str(memory_val.get("temporal_note", "")))
            st.caption("At each historical evaluation date, analogue thresholds are re-estimated from prior states only, candidate forward outcomes must already have been observable by that date, and at least three admissible analogues are required before a memory forecast exists.")
        else:
            st.warning(memory_val.get("reason", "Behavioral Memory walk-forward validation unavailable."))

        st.markdown("<div class='psy-section'>Scenario validation status</div>", unsafe_allow_html=True)
        st.info(
            "FULL SCENARIO OOS VALIDATION REMAINS GATED. Several scenario definitions require historical disagreement, ambiguity, narrative concentration, higher-order beliefs and option-state inputs that do not yet have a long point-in-time archive. V2.4.1 does not reconstruct them retrospectively. Core latent mechanisms, acute alarms and observed-domain Behavioral Memory are validated now; full scenario validation activates only when those archived domains exist."
        )

        st.markdown("<div class='psy-section'>Version-lock / audit manifest</div>", unsafe_allow_html=True)
        manifest_rows = [
            {"Field": "Validation version", "Value": manifest.get("validation_version")},
            {"Field": "Profile", "Value": manifest.get("profile")},
            {"Field": "History", "Value": f"{manifest.get('history_start')} → {manifest.get('history_end')}"},
            {"Field": "Rows", "Value": manifest.get("rows")},
            {"Field": "Min train", "Value": manifest.get("min_train_rows")},
            {"Field": "Holdout", "Value": manifest.get("holdout_rows")},
            {"Field": "Bootstrap samples", "Value": manifest.get("bootstrap_samples")},
            {"Field": "Code hashes", "Value": " · ".join(f"{k}:{v}" for k,v in manifest.get("code_hashes",{}).items())},
        ]
        st.dataframe(pd.DataFrame(manifest_rows), use_container_width=True, hide_index=True)
        limitations = manifest.get("point_in_time_limitations", [])
        if limitations:
            st.caption("Point-in-time limitations: " + " · ".join(str(x) for x in limitations))
        st.download_button(
            "DOWNLOAD V2.4.1 VALIDATION AUDIT JSON",
            data=bundle_json_bytes(bundle),
            file_name=f"market_psychology_{state.get('symbol','SPY')}_v2_4_1_validation.json",
            mime="application/json",
            use_container_width=True,
        )

    _render_external_replication(state)

    with st.expander("Legacy full-sample diagnostic — IN-SAMPLE ONLY", expanded=False):
        validation = build_forward_validation(state.get("history", pd.DataFrame()))
        if validation.empty:
            st.info("Not enough historical state observations for the legacy in-sample diagnostic.")
        else:
            st.dataframe(validation, use_container_width=True, hide_index=True)
            st.caption("This table is retained only for continuity. It must never be used to override V2.4.1 walk-forward/holdout evidence.")

    st.markdown("<div class='psy-section'>Research protocol</div>", unsafe_allow_html=True)
    st.dataframe(research_protocol_table(), use_container_width=True, hide_index=True)


def render_market_psychology_lab(default_symbol: str = DEFAULT_SYMBOL) -> None:
    """
    Autonomous experimental behavioral-market workspace.

    Design rule: observed market variables are kept separate from latent psychological
    mechanisms. Low-identification mechanisms are explicitly flagged rather than hidden.
    """
    _css()
    st.markdown(
        """
        <div class='psy-hero'>
            <div class='psy-kicker'>MARKET PSYCHOLOGY LAB · FROZEN RESEARCH SPEC · V2.5.3</div>
            <div class='psy-title'>Behavioral State & Reflexivity Workstation</div>
            <div class='psy-sub'>
                Cognitive state, belief formation, affect/preferences, narratives, herding and reflexivity.
                This lab does not relabel VIX, options or flows as direct psychology: raw observations and latent inferences remain separated,
                with explicit confidence and identification limits. <b>V2.5.3 does not recalibrate the research engine.</b> The V2.4.1 state, alarm, memory and evidence specifications remain frozen; V2.5.3 retains the V2.5.1 closed-session cutoff and fixes external acquisition only. A separate <b>Higher-Order Beliefs</b> research overlay is available inside this Lab; it never feeds back into the frozen V2.5.3 baseline.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    default_symbol = str(st.session_state.get("psychology_symbol", default_symbol) or DEFAULT_SYMBOL).upper().strip()
    with st.form("market_psychology_controls_v1"):
        c1, c2, c3, c4 = st.columns([1.35, 1.0, 1.0, .8], vertical_alignment="bottom")
        with c1:
            symbol = st.text_input("Market / ticker", value=default_symbol, placeholder="SPY, QQQ, NVDA, TSLA...")
        with c2:
            period = st.selectbox("Research history", ["1y", "2y", "5y", "10y"], index=2, help="5Y is now the default research baseline for walk-forward/holdout validation. 1Y/2Y remain useful for faster exploratory state monitoring; narrative/options memory remains point-in-time archive only.")
        with c3:
            news_limit = st.selectbox("Current news sample", [20, 40, 60], index=1)
        with c4:
            run = st.form_submit_button("RUN LAB", use_container_width=True)

    symbol = str(symbol or DEFAULT_SYMBOL).upper().strip()
    if run:
        st.session_state["psychology_symbol"] = symbol

    with st.spinner("Building behavioral state from price, cross-asset, news and options proxies…"):
        # V2.3.2 validates the target history before news/options/breadth/CFTC/FRED.
        # A failed 5Y/10Y target request must not trigger dozens of additional
        # provider calls that can worsen rate limits.
        pack = fetch_market_pack(symbol, period=period)
        raw_target = pack.get(symbol, pd.DataFrame()) if isinstance(pack, dict) else pd.DataFrame()
        if raw_target is None or raw_target.empty:
            attempts = []
            try:
                attempts = list(raw_target.attrs.get("provider_attempts", []))
            except Exception:
                attempts = []
            st.error(f"No price data for {symbol} after the configured provider waterfall.")
            if attempts:
                with st.expander("Price provider diagnostic", expanded=True):
                    safe_rows = []
                    for row in attempts:
                        if not isinstance(row, dict):
                            continue
                        safe_rows.append({
                            "Provider": row.get("provider", "N/A"),
                            "Status": row.get("status", "N/A"),
                            "HTTP": row.get("http", ""),
                            "Rows": row.get("rows", ""),
                            "Detail": row.get("detail", row.get("api_code", "")),
                        })
                    if safe_rows:
                        st.dataframe(pd.DataFrame(safe_rows), use_container_width=True, hide_index=True)
                statuses = {str(r.get("status", "")) for r in attempts if isinstance(r, dict)}
                if "rate_limited" in statuses:
                    st.warning("At least one provider is rate-limited. V2.3.2 stops here instead of launching breadth/news/options calls, so retrying after the provider cooldown will not amplify the limit.")
                if str(period).lower() in {"5y", "10y"}:
                    st.caption("Long-history note: Massive history depth depends on plan entitlement, and Alpha Vantage full daily history requires premium access. Twelve Data/FMP/yfinance remain independent fallbacks when available.")
            return

        news_df = fetch_news(symbol, limit=int(news_limit))
        options = fetch_options_snapshot(symbol, max_expiries=3)
        behavioral_data = build_behavioral_data_layer(symbol, period, options)
        state = build_psychology_state(symbol, pack, news_df, options, behavioral_data=behavioral_data)

    if not state.get("available"):
        st.error(state.get("reason", "Market Psychology Lab unavailable."))
        return

    # Persist a non-sensitive shell context so app.py can render the Psychology header
    # before entering this autonomous workspace on subsequent reruns.
    _diag = state.get("diagnostics", {}) if isinstance(state.get("diagnostics", {}), dict) else {}
    _alerts = state.get("alerts", pd.DataFrame())
    _lead_score = None
    _lead_name = "Behavioral state"
    try:
        if _alerts is not None and not _alerts.empty:
            _lead_score = float(_alerts.iloc[0].get("Score"))
            _lead_name = str(_alerts.iloc[0].get("Alarm", "Behavioral state"))
    except Exception:
        _lead_score = None
    st.session_state["psychology_header_context"] = {
        "ticker": symbol,
        "state": str(state.get("regime", "MIXED / UNIDENTIFIED")),
        "signal": "RESEARCH / WATCH" if any(str(x).upper() in {"WATCH", "HIGH", "CRITICAL"} for x in (_alerts.get("Acute Alarm", []) if _alerts is not None and not _alerts.empty else [])) else "RESEARCH",
        "score": _lead_score,
        "score_name": _lead_name,
        "run": "Completed",
        "evidence": str(state.get("evidence_quality_label", "N/A")),
    }

    st.markdown(
        f"""
        <div class='psy-regime'>
            <div class='psy-regime-label'>Behavioral regime · {escape(symbol)}</div>
            <div class='psy-regime-value'>{escape(str(state.get('regime','MIXED / UNIDENTIFIED')))}</div>
            <div class='psy-regime-note'>{escape(str(state.get('regime_reason','')))}<br>
            Evidence quality: {escape(str(state.get('evidence_quality_label','N/A')))} ({_fmt_num(state.get('evidence_quality_score'),0)}/100) · 
            latent stability {_fmt_num(state.get('latent_stability'),0)}% · dominant observable mental-model proxy: {escape(str(state.get('mental_model','N/A')))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    diag = state.get("diagnostics", {})
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("20D return", _fmt_pct(diag.get("perf_20d")))
    m2.metric("20D vol", _fmt_pct(diag.get("vol_20d")))
    m3.metric("Current drawdown", _fmt_pct(diag.get("drawdown")))
    m4.metric("News corpus", str(diag.get("news_count", 0)), help=f"{diag.get('news_providers',0)} providers · {diag.get('news_sources',0)} sources")
    m5.metric("Options rows", str(diag.get("option_rows", 0)))
    st.caption(
        f"Price history source: {diag.get('price_provider', 'Unknown')} · point-in-time provider waterfall enabled · "
        f"observed-data availability {diag.get('behavioral_data_availability', 0):.0f}% · "
        f"evidence {diag.get('behavioral_data_evidence', 0):.0f}/100."
    )

    _render_top_alarm_strip(state, max_items=4)

    tabs = st.tabs([
        "State Map",
        "Mechanisms",
        "Institutional Data",
        "Narratives / Options",
        "Higher-Order Beliefs",
        "Memory / Analogues",
        "Validation / Identification",
    ])
    with tabs[0]:
        _render_overview(state)
    with tabs[1]:
        _render_mechanisms(state)
    with tabs[2]:
        _render_institutional_data(state)
    with tabs[3]:
        _render_narrative_options(state)
    with tabs[4]:
        render_higher_order_beliefs(state)
    with tabs[5]:
        _render_analogues(state)
    with tabs[6]:
        _render_validation(state)
