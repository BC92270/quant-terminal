"""Raw-to-structured event audit view."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from ..contracts import WorkspaceSnapshot
from ..demo import events_frame
from .common import bounded_table, card, esc, provenance, section_header


def render_event_explorer(snapshot: WorkspaceSnapshot) -> None:
    section_header("NOW DESK / 02", "Event Explorer", "RAW → NORMALIZED → VALIDATED → TRADABLE")
    frame = events_frame(snapshot)
    f1, f2, f3 = st.columns(3)
    with f1:
        selected_classes = st.multiselect(
            "EVENT CLASS",
            sorted(frame["event_class"].unique()),
            default=sorted(frame["event_class"].unique()),
            key="mi_event_classes",
        )
    with f2:
        selected_directions = st.multiselect(
            "DIRECTION",
            sorted(frame["direction"].unique()),
            default=sorted(frame["direction"].unique()),
            key="mi_event_directions",
        )
    with f3:
        min_novelty = st.slider("MIN NOVELTY", 0.0, 1.0, 0.0, 0.05, key="mi_event_min_novelty")
    filtered = frame.loc[
        frame["event_class"].isin(selected_classes)
        & frame["direction"].isin(selected_directions)
        & (frame["novelty"] >= min_novelty)
    ].copy()
    display = filtered[
        [
            "event_id", "timestamp", "entity", "source", "event_class", "subtype", "direction",
            "novelty", "surprise_z", "sentiment", "confidence", "cluster_id", "revision_id",
        ]
    ]
    selection = st.dataframe(
        display,
        width="stretch",
        hide_index=True,
        height=285,
        key="mi_event_grid",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "novelty": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%"),
            "confidence": st.column_config.ProgressColumn(min_value=0.0, max_value=1.0, format="%.0f%%"),
            "surprise_z": st.column_config.NumberColumn(format="%+.2f"),
            "sentiment": st.column_config.NumberColumn(format="%+.2f"),
        },
    )
    try:
        row_index = selection.selection.rows[0]
        selected_id = str(display.iloc[row_index]["event_id"])
        st.session_state["mi_selected_event"] = selected_id
    except (AttributeError, IndexError, KeyError, TypeError):
        selected_id = str(st.session_state.get("mi_selected_event", snapshot.events[0].event_id))
    event = next((item for item in snapshot.events if item.event_id == selected_id), snapshot.events[0])
    section_header("EVIDENCE RECORD", event.title, f"{event.event_id} · {event.revision_id}")
    left, center, right = st.columns([1.35, 1.0, 1.0], gap="medium")
    with left:
        st.markdown(
            f'<div class="mi-card"><div class="mi-card-title">Normalized source text</div>'
            f'<div class="mi-card-note" style="font-size:.79rem;color:rgba(232,242,244,.78)">{esc(event.text)}</div>'
            f'<div class="mi-chip-row"><span class="mi-chip">{esc(event.source)}</span>'
            f'<span class="mi-chip">{esc(event.event_class)}</span><span class="mi-chip">{esc(event.subtype)}</span></div></div>',
            unsafe_allow_html=True,
        )
    with center:
        card("Structured direction", event.direction.upper(), "Descriptive event implication, not a trading label")
        card("Novelty / sentiment", f"{event.novelty:.0%} / {event.sentiment:+.2f}", "Independent features; not collapsed into one score")
        card("Surprise", "N/A" if event.surprise_z is None else f"{event.surprise_z:+.2f}σ", "Only populated when a PIT expectation exists")
    with right:
        card("Extraction confidence", f"{event.confidence:.0%}", "Fixture validation confidence")
        card("Cluster / revision", f"{event.cluster_id} / {event.revision_id}", "Stable IDs preserve linkage")
        card("Validation warnings", "NONE" if not event.validation_flags else " · ".join(event.validation_flags), "Warnings stay attached to the event")
    lineage = pd.DataFrame(
        [
            {"Stage": "Publication", "Timestamp UTC": event.publication_time, "Rule": "source timestamp"},
            {"Stage": "First seen", "Timestamp UTC": event.first_seen_time, "Rule": "ingestion observation"},
            {"Stage": "Ingested", "Timestamp UTC": event.ingested_at, "Rule": "append-only arrival"},
            {"Stage": "Tradable", "Timestamp UTC": event.tradable_at, "Rule": "max(publication, first_seen) + buffer"},
            {"Stage": "Features ready", "Timestamp UTC": event.feature_computed_at, "Rule": "must be <= prediction cutoff"},
        ]
    )
    bounded_table(lineage, height=220)
    provenance("Every fixture event carries the full timestamp chain. Live ingestion remains unavailable until an official/licensed provider is configured.")
