"""Live Intelligence control-plane view."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..demo import forecasts_frame
from ..state import set_active_view
from .common import (
    AMBER,
    CYAN,
    GREEN,
    RED,
    bounded_table,
    card,
    evidence_block,
    esc,
    fmt_number,
    fmt_pct,
    provenance,
    section_header,
    style_figure,
)
from .institutional_control import governance_assessment


def _institutional_brief(snapshot: WorkspaceSnapshot) -> None:
    assessment = governance_assessment(snapshot)
    decision = assessment.decision
    state = snapshot.interaction.state.replace("_", " ").upper()
    gap = snapshot.audit["information_gap"]
    context = snapshot.audit.get("context_integrity", {})
    context_state = str(context.get("state", "MATCHED"))
    st.markdown(
        f'''<div class="mi-brief-grid">
          <div class="mi-brief-card"><div>Current state</div><p>{esc(state)} · descriptive fixture assessment, not a trade signal.</p></div>
          <div class="mi-brief-card"><div>What changed</div><p>NO PRIOR SNAPSHOT · change attribution is withheld until an append-only prior state exists.</p></div>
          <div class="mi-brief-card"><div>Contradiction</div><p>Collision {snapshot.interaction.collision_score:.0%}; opposing catalyst mass compresses the net directional interpretation.</p></div>
          <div class="mi-brief-card"><div>Unknown</div><p>Options unavailable; forecast calibration, live entitlement and historical PIT coverage absent.</p></div>
          <div class="mi-brief-card"><div>Governance posture</div><p>{esc(decision.state.value)} · context {esc(context_state)} · execution disabled · packet {esc(decision.packet_id[-10:])}.</p></div>
        </div>''',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2, gap="medium")
    with left:
        evidence_block("Evidence supporting the descriptive state", snapshot.interaction.evidence, tone="green")
    with right:
        evidence_block(
            "Contradictions and invalidation triggers",
            (
                "High opposing catalyst mass weakens one-sided interpretation.",
                "Invalidate absorption if bid replenishment falls or sell impact rises.",
                f"Escalate residual investigation at 70%; current fixture residual is {float(gap['unexplained_residual']):.0%}.",
            ),
            tone="amber",
        )
    st.caption(
        "Next evidence required: licensed PIT event lineage · sequenced venue-authorized L2 · realized forecast outcomes · "
        f"independent validation. Evidence root {decision.evidence_root[:16]}… · {len(assessment.ledger.records)} verified records."
    )


def _timeline(snapshot: WorkspaceSnapshot) -> go.Figure:
    timeline = snapshot.timeline.copy().sort_values("timestamp")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timeline["timestamp"],
            y=timeline["price"],
            mode="lines",
            name=f"{snapshot.symbol} fixture price",
            line=dict(color=CYAN, width=2.4),
            fill="tozeroy",
            fillcolor="rgba(85,232,245,.045)",
            hovertemplate="%{x|%H:%M UTC}<br>Price %{y:.2f}<extra></extra>",
        )
    )
    benchmark = 100.0 * timeline["benchmark"] / float(timeline["benchmark"].iloc[0])
    fig.add_trace(
        go.Scatter(
            x=timeline["timestamp"],
            y=benchmark,
            mode="lines",
            name="Nasdaq state · indexed",
            yaxis="y2",
            line=dict(color="rgba(255,201,102,.70)", width=1.4, dash="dot"),
            hovertemplate="%{x|%H:%M UTC}<br>Benchmark %{y:.2f}<extra></extra>",
        )
    )
    event_rows = []
    for event in snapshot.events:
        nearest = int((timeline["timestamp"] - pd.Timestamp(event.event_time)).abs().argmin())
        event_rows.append(
            {
                "timestamp": event.event_time,
                "price": float(timeline.iloc[nearest]["price"]),
                "event_id": event.event_id,
                "title": event.title,
                "source": event.source,
                "direction": event.direction,
                "novelty": event.novelty,
                "surprise": event.surprise_z,
            }
        )
    events = pd.DataFrame(event_rows)
    for direction, color, symbol in (
        ("positive", GREEN, "triangle-up"),
        ("negative", RED, "triangle-down"),
        ("mixed", AMBER, "diamond"),
    ):
        subset = events.loc[events["direction"] == direction]
        if subset.empty:
            continue
        custom = subset[["event_id", "title", "source", "novelty", "surprise"]].to_numpy()
        fig.add_trace(
            go.Scatter(
                x=subset["timestamp"],
                y=subset["price"],
                mode="markers",
                name=f"{direction.title()} catalyst",
                marker=dict(size=12, color=color, symbol=symbol, line=dict(width=1, color="#06131e")),
                customdata=custom,
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>%{x|%H:%M:%S UTC}<br>"
                    "Source %{customdata[2]}<br>Novelty %{customdata[3]:.0%}<br>"
                    "Surprise z %{customdata[4]}<extra>click to inspect</extra>"
                ),
            )
        )
    fig.update_layout(
        yaxis=dict(title="Fixture price"),
        yaxis2=dict(title="Benchmark index", overlaying="y", side="right", showgrid=False),
    )
    return style_figure(fig, title="Catalyst × Price Timeline · canonical fixture · 10-minute state", height=440)


def _pressure(snapshot: WorkspaceSnapshot) -> go.Figure:
    frame = snapshot.catalyst_contributions.sort_values("contribution")
    colors = [GREEN if value >= 0 else RED for value in frame["contribution"]]
    fig = go.Figure(
        go.Bar(
            x=frame["contribution"],
            y=frame["catalyst"],
            orientation="h",
            marker_color=colors,
            customdata=frame[["family", "kind", "confidence"]].to_numpy(),
            hovertemplate="%{y}<br>Contribution %{x:+.2f}<br>%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<extra></extra>",
        )
    )
    fig.add_vline(x=0.0, line_color="rgba(220,240,245,.28)", line_width=1)
    return style_figure(fig, title="Catalyst pressure · model-attributed fixture units", height=340, hovermode="closest")


def _gap_gauge(snapshot: WorkspaceSnapshot) -> go.Figure:
    gap = snapshot.audit["information_gap"]
    residual = float(gap["unexplained_residual"])
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=residual * 100.0,
            number={"suffix": "/100", "font": {"color": "#edf9fb", "size": 25}},
            title={"text": "Unexplained residual", "font": {"color": "rgba(202,224,231,.65)", "size": 11}},
            gauge={
                "axis": {"range": [0, 100], "tickcolor": "rgba(210,235,240,.35)"},
                "bar": {"color": GREEN if residual < 0.70 else RED},
                "bgcolor": "rgba(7,20,31,.70)",
                "bordercolor": "rgba(105,190,204,.12)",
                "steps": [
                    {"range": [0, 45], "color": "rgba(55,195,147,.12)"},
                    {"range": [45, 70], "color": "rgba(255,201,102,.12)"},
                    {"range": [70, 100], "color": "rgba(255,113,136,.12)"},
                ],
                "threshold": {"line": {"color": RED, "width": 2}, "thickness": 0.75, "value": 70},
            },
        )
    )
    return style_figure(fig, height=260, hovermode="closest")


def render_live_intelligence(snapshot: WorkspaceSnapshot) -> None:
    section_header(
        "NOW DESK / 01",
        "Live Intelligence",
        "CATALYST ARRIVAL → MARKET ABSORPTION → DISTRIBUTION · FIXTURE",
    )
    _institutional_brief(snapshot)
    left, right = st.columns([2.15, 1.0], gap="medium")
    with left:
        selection = st.plotly_chart(
            _timeline(snapshot),
            width="stretch",
            key="mi_live_timeline",
            on_select="rerun",
            selection_mode="points",
            config={"displaylogo": False, "scrollZoom": False},
        )
        try:
            point = selection.selection.points[0]
            custom = point.get("customdata") or []
            if custom and custom[0]:
                st.session_state["mi_selected_event"] = str(custom[0])
        except (AttributeError, IndexError, KeyError, TypeError):
            pass
        provenance("Observed shape: deterministic fixture. Event timestamps: UTC. Markers are selectable; selection is handed to Event Explorer.")
        selected_event = str(st.session_state.get("mi_selected_event", snapshot.events[0].event_id))
        if st.button(
            f"INSPECT SELECTED EVENT → {selected_event}",
            key="mi_live_open_selected_event",
            width="stretch",
            type="secondary",
        ):
            set_active_view(st.session_state, "events")
            st.rerun()
    with right:
        interaction = snapshot.interaction
        st.markdown(
            f'<div class="mi-state"><div class="mi-card-title">Interaction State</div>'
            f'<div class="mi-state-code">{esc(interaction.state.replace("_", " "))}</div>'
            f'<div class="mi-state-copy">{esc(interaction.explanation)}</div>'
            f'<div class="mi-chip-row"><span class="mi-chip">CONFIDENCE {esc(interaction.confidence)}</span>'
            f'<span class="mi-chip">COLLISION {interaction.collision_score:.0%}</span>'
            f'<span class="mi-chip">NET {interaction.catalyst_pressure:+.2f}</span></div></div>',
            unsafe_allow_html=True,
        )
        st.plotly_chart(_gap_gauge(snapshot), width="stretch", config={"displayModeBar": False})
        st.caption(snapshot.audit["information_gap"]["status"] + " · conservative descriptive state")

    c1, c2, c3 = st.columns([1.25, 1.0, 1.0], gap="medium")
    with c1:
        st.plotly_chart(_pressure(snapshot), width="stretch", config={"displaylogo": False})
    with c2:
        section_header("ABSORPTION SENSOR", "Microstructure State", "L2 · SIMULATED")
        m = snapshot.microstructure
        a, b = st.columns(2)
        with a:
            card("Order-flow imbalance", fmt_number(m.ofi, 0), "Cont-style best-quote events", tone="cyan")
            card("Microprice deviation", fmt_number((m.microprice or 0) - (m.mid or 0), 4), "Microprice minus midpoint", tone="green")
            card("Bid replenishment", fmt_number(m.bid_replenishment, 2), "Sequenced L2 fixture metric", tone="green")
        with b:
            card("Queue imbalance", fmt_number(m.queue_imbalance, 3), "[-1, +1] best-queue state", tone="cyan")
            card("Trade imbalance", fmt_number(m.trade_imbalance, 3), "Signed aggressive-volume proxy", tone="red")
            card("Anomaly percentile", fmt_pct(m.anomaly_percentile, 0), "Fixture reference distribution", tone="amber")
    with c3:
        section_header("KNOWN VS RESIDUAL", "Information Gap", "NO INSIDER INFERENCE")
        gap = snapshot.audit["information_gap"]
        card("Known catalyst intensity", fmt_pct(gap["known_catalyst_intensity"], 0), "Opposing events explain most measured state", tone="green")
        card("Related-asset anomaly", fmt_pct(gap["related_asset_anomaly"], 0), "Rates / Nasdaq propagation candidate", tone="amber")
        card("Options anomaly", "UNAVAILABLE", "No options feed in the fixture contract")

    bottom_left, bottom_right = st.columns([1.1, 1.35], gap="medium")
    with bottom_left:
        section_header("HISTORICAL CONTEXT", "Nearest state analogues", "SYNTHETIC · MULTIVARIATE")
        analogue = snapshot.analogues[["Episode", "Event", "Similarity", "Return +1h", "Return +1d", "Status"]].head(4).copy()
        bounded_table(
            analogue,
            height=245,
            formats={
                "Similarity": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%"),
                "Return +1h": st.column_config.NumberColumn(format="%+.2f%%"),
                "Return +1d": st.column_config.NumberColumn(format="%+.2f%%"),
            },
        )
        provenance("Analogue IDs and outcomes are synthetic fixture records. No historical sample or statistical confidence is claimed.")
    with bottom_right:
        focus_horizon = str(st.session_state.get("mi_horizon", "30m"))
        section_header(
            "LEVEL-0 BENCHMARK",
            "Multi-horizon forecast distribution",
            f"FOCUS {focus_horizon.upper()} · UNCALIBRATED · NOT CATALYST-CONDITIONED",
        )
        forecast = forecasts_frame(snapshot).copy()
        forecast.insert(0, "Focus", forecast["Horizon"].eq(focus_horizon).map({True: "● SELECTED", False: ""}))
        forecast = forecast.sort_values("Focus", ascending=False)[
            ["Focus", "Horizon", "P(up)", "Expected return", "Q05", "Q50", "Q95", "Expected volatility", "Calibration", "Sample"]
        ]
        bounded_table(
            forecast,
            height=245,
            formats={
                "P(up)": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%"),
                "Expected return": st.column_config.NumberColumn(format="%+.2f%%"),
                "Q05": st.column_config.NumberColumn(format="%+.2f%%"),
                "Q50": st.column_config.NumberColumn(format="%+.2f%%"),
                "Q95": st.column_config.NumberColumn(format="%+.2f%%"),
                "Expected volatility": st.column_config.NumberColumn(format="%.2f%%"),
            },
        )
        provenance("Distribution computed from trailing fixture returns only. It is a benchmark control, not a promoted predictive model.")
