"""Shared presentation primitives and Plotly styling."""

from __future__ import annotations

from html import escape
from typing import Any, Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ..contracts import WorkspaceSnapshot


CYAN = "#55e8f5"
GREEN = "#58dfac"
RED = "#ff7188"
AMBER = "#ffc966"
GRID = "rgba(142,185,196,.10)"
PAPER = "rgba(0,0,0,0)"


def tone_for_status(status: str | None) -> str:
    """Map explicit institutional states to a visual tone without treating null as positive."""

    normalized = str(status or "").strip().upper().replace("-", "_").replace(" ", "_")
    if not normalized or normalized in {
        "N/A",
        "NONE",
        "NULL",
        "UNKNOWN",
        "UNAVAILABLE",
        "NOT_MEASURABLE",
        "NOT_APPLICABLE",
    }:
        return "muted"
    if normalized in {"NOT_ELIGIBLE", "PENDING_EVIDENCE", "NOT_STARTED"}:
        return "amber"
    if any(token in normalized for token in ("FAIL", "INVALID", "BREACH", "BLOCKED", "DEGRADED", "ERROR", "DISABLED")):
        return "red"
    if any(
        token in normalized
        for token in ("WAIT", "CLOSED", "RESEARCH", "SIMULATED", "DELAYED", "UNCALIBRATED", "WARNING", "INVESTIGATE")
    ):
        return "amber"
    if "ALARM" in normalized and "NO_ALARM" not in normalized:
        return "red"
    if any(token in normalized for token in ("PASS", "VALID", "ELIGIBLE", "STABLE", "LIVE")):
        return "green"
    return "cyan"


def esc(value: Any) -> str:
    return escape(str(value if value is not None else "—"))


def fmt_number(value: float | None, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    return f"{float(value):,.{digits}f}{suffix}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    return f"{float(value):+.{digits}%}"


def section_header(kicker: str, title: str, meta: str = "") -> None:
    st.markdown(
        f'<div class="mi-section"><div><div class="mi-section-kicker">{esc(kicker)}</div>'
        f'<div class="mi-section-title">{esc(title)}</div></div>'
        f'<div class="mi-section-meta">{esc(meta)}</div></div>',
        unsafe_allow_html=True,
    )


def card(label: str, value: str, note: str = "", *, tone: str = "") -> None:
    tone_class = f" mi-value-{tone}" if tone else ""
    st.markdown(
        f'<div class="mi-card"><div class="mi-card-title">{esc(label)}</div>'
        f'<div class="mi-card-value{tone_class}">{esc(value)}</div>'
        f'<div class="mi-card-note">{esc(note)}</div></div>',
        unsafe_allow_html=True,
    )


def status_badge(label: str, status: str, *, detail: str = "") -> None:
    tone = tone_for_status(status)
    st.markdown(
        f'<div class="mi-status-badge mi-status-badge-{esc(tone)}">'
        f'<span>{esc(label)}</span><b>{esc(status)}</b>'
        f'<small>{esc(detail)}</small></div>',
        unsafe_allow_html=True,
    )


def evidence_block(label: str, items: Iterable[str], *, tone: str = "cyan") -> None:
    rendered = "".join(f"<li>{esc(item)}</li>" for item in items)
    if not rendered:
        rendered = "<li>No admissible evidence in the current snapshot.</li>"
    st.markdown(
        f'<div class="mi-evidence mi-evidence-{esc(tone)}"><div>{esc(label)}</div><ul>{rendered}</ul></div>',
        unsafe_allow_html=True,
    )


def provenance(text: str) -> None:
    st.markdown(f'<div class="mi-provenance">{esc(text)}</div>', unsafe_allow_html=True)


def style_figure(fig: go.Figure, *, title: str = "", height: int = 380, hovermode: str = "x unified") -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=13, color="#e9f7fa"), x=0.01),
        height=height,
        margin=dict(l=18, r=18, t=50 if title else 24, b=22),
        paper_bgcolor=PAPER,
        plot_bgcolor=PAPER,
        font=dict(color="rgba(220,238,243,.74)", size=10),
        hovermode=hovermode,
        hoverlabel=dict(bgcolor="#071824", bordercolor="rgba(85,232,245,.25)", font_color="#ecf9fb"),
        legend=dict(orientation="h", y=1.08, x=0, font=dict(size=9)),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, showline=False)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, showline=False)
    return fig


def bounded_table(frame: pd.DataFrame, *, height: int = 360, formats: dict[str, Any] | None = None) -> None:
    if frame is None or frame.empty:
        st.info("No records available for this point-in-time view.")
        return
    st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        height=height,
        column_config=formats or {},
    )


def status_pill(status: str) -> str:
    return f'<span class="mi-chip">{esc(status.upper())}</span>'


def render_data_contract(snapshot: WorkspaceSnapshot) -> None:
    contract = snapshot.audit.get("data_contract", {})
    with st.expander("DATA CONTRACT · provenance and current limitations", expanded=False):
        rows = "".join(
            '<div class="mi-contract-row">'
            f'<b>{esc(key.replace("_", " ").title())}</b><span>{esc(value)}</span>'
            "</div>"
            for key, value in contract.items()
        )
        st.markdown(f'<div class="mi-contract-grid">{rows}</div>', unsafe_allow_html=True)
        st.caption(
            "This release validates architecture, deterministic calculations and UX on a canonical fixture. "
            "It does not establish live-provider coverage, alpha, calibration, promotion eligibility or execution readiness."
        )


def provider_health_frame(snapshot: WorkspaceSnapshot) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Provider / layer": item.provider,
                "Status": item.status.value.upper(),
                "Schema": item.schema_level,
                "As of": item.as_of.isoformat(),
                "Latency ms": item.latency_ms,
                "Detail": item.detail,
            }
            for item in snapshot.provider_health
        ]
    )
