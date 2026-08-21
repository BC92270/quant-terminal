"""Streamlit UI for Company Intelligence V3 Management / Transcripts."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .common import safe_float
from .management_transcripts import (
    _delta_table,
    _theme_delta,
    backfill_management_transcript,
    clear_transcript_provider_circuits,
    load_management_transcript_intelligence,
    transcript_backfill_candidates,
)


def _score_text(value) -> str:
    v = safe_float(value)
    return "N/A" if v is None else f"{v:.0f}/100"


def _num_text(value, decimals: int = 1) -> str:
    v = safe_float(value)
    return "N/A" if v is None else f"{v:.{decimals}f}"


def _quarter_label(record: dict) -> str:
    q = str(record.get("quarter") or "N/A")
    provider = str(record.get("provider") or "Unknown")
    date = record.get("date")
    if date is not None and not pd.isna(date):
        try:
            return f"{q} · {pd.Timestamp(date).date()} · {provider}"
        except Exception:
            pass
    return f"{q} · {provider}"


def _comparison_for_selection(records: list[dict], index: int):
    current = records[index]
    previous = records[index + 1] if index + 1 < len(records) else None
    return current, previous, _delta_table(current, previous), _theme_delta(current, previous)


def _render_tone_split(summary: dict):
    values = {
        "Prepared": safe_float(summary.get("prepared_tone")),
        "Q&A management": safe_float(summary.get("qa_management_tone")),
        "Overall management": safe_float(summary.get("management_tone")),
        "Guidance confidence": safe_float(summary.get("guidance_confidence")),
    }
    labels = [k for k, v in values.items() if v is not None]
    scores = [values[k] for k in labels]
    if not scores:
        return
    fig = go.Figure(go.Bar(x=scores, y=labels, orientation="h", text=[f"{x:.0f}" for x in scores], textposition="auto"))
    fig.add_vline(x=50, line_dash="dot", annotation_text="Neutral / midpoint")
    fig.update_layout(
        height=max(300, 58 * len(labels)),
        title="Management tone architecture",
        xaxis_title="Score (0–100)",
        xaxis_range=[0, 100],
        margin=dict(l=20, r=20, t=65, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_theme_chart(theme: pd.DataFrame):
    if not isinstance(theme, pd.DataFrame) or theme.empty:
        return
    view = theme.copy()
    view["Mentions"] = pd.to_numeric(view["Mentions"], errors="coerce").fillna(0)
    view = view.sort_values("Mentions", ascending=True)
    fig = go.Figure(go.Bar(
        x=view["Mentions"], y=view["Theme"], orientation="h",
        text=[str(int(x)) for x in view["Mentions"]], textposition="auto",
    ))
    fig.update_layout(
        height=max(360, 46 * len(view)),
        title="Transcript theme intensity",
        xaxis_title="Keyword / phrase mentions",
        margin=dict(l=20, r=20, t=65, b=40),
    )
    st.plotly_chart(fig, use_container_width=True)




def _render_cache_budget_controls(company: dict, bundle: dict) -> dict:
    """Render V3.2 cache/budget controls and return the possibly refreshed bundle."""
    runtime = bundle.get("runtime", {}) if isinstance(bundle, dict) else {}
    symbol = str(bundle.get("symbol") or runtime.get("symbol") or "").upper().strip() if isinstance(bundle, dict) else ""
    if not symbol:
        profile = company.get("profile", {}) if isinstance(company, dict) else {}
        symbol = str(profile.get("symbol") or profile.get("ticker") or "").upper().strip() if isinstance(profile, dict) else ""

    with st.expander("Transcript cache / provider budget — V3.2", expanded=not bool(bundle.get("available"))):
        c1, c2, c3 = st.columns(3)
        c1.metric("Persistent cache", f"{int(runtime.get('cache_entries') or 0)} quarter(s)")
        c2.metric("Cache hits", str(int(runtime.get('cache_hits') or 0)))
        c3.metric("Latest target", str(runtime.get("latest_target_quarter") or "N/A"))
        st.caption(str(runtime.get("probe_policy") or "Latest fiscal quarter only; historical backfill is explicit."))

        cached = runtime.get("cached_quarters", [])
        st.write("**Cached quarters:** " + (", ".join(cached) if cached else "None"))
        if runtime.get("cache_root"):
            st.caption(f"Persistent cache root: {runtime.get('cache_root')}")

        circuits = runtime.get("circuits", pd.DataFrame())
        if isinstance(circuits, pd.DataFrame) and not circuits.empty:
            st.markdown("**Provider circuits**")
            st.dataframe(circuits, use_container_width=True, hide_index=True)

        st.markdown("**Manual historical backfill — one fiscal quarter per action**")
        candidates = transcript_backfill_candidates(symbol, company, limit=12) if symbol else []
        if candidates:
            selected = st.selectbox(
                "Quarter to fetch",
                candidates,
                index=0,
                key="company_intelligence_transcript_backfill_quarter",
            )
            if st.button("Fetch one historical quarter", key="company_intelligence_transcript_backfill_button"):
                with st.spinner(f"Requesting {symbol} {selected} once across the provider waterfall..."):
                    result = backfill_management_transcript(symbol, company, selected)
                attempts = result.get("attempts", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
                if result.get("ok"):
                    st.success(f"{selected} is now persisted in the transcript cache.")
                    fresh = load_management_transcript_intelligence(symbol, company, max_quarters=4, probe_latest=False)
                    inst = company.setdefault("institutional", {}) if isinstance(company, dict) else {}
                    if isinstance(inst, dict):
                        inst["management_transcripts"] = fresh
                    bundle = fresh
                else:
                    st.warning(f"{selected} was not retrieved. No additional quarter was probed automatically.")
                if isinstance(attempts, pd.DataFrame) and not attempts.empty:
                    st.dataframe(attempts, use_container_width=True, hide_index=True)
        else:
            st.caption("No uncached quarter candidate is currently available from the fiscal-calendar resolver.")

        st.markdown("**Circuit maintenance**")
        st.caption("Clear circuits only after a provider quota reset, plan/key change, or entitlement upgrade. Normal reruns should leave them untouched.")
        if st.button("Clear transcript provider circuits", key="company_intelligence_clear_transcript_circuits"):
            if clear_transcript_provider_circuits():
                st.success("Transcript provider circuits cleared. The next rerun will make at most one latest-quarter probe per provider path.")
            else:
                st.warning("Circuit state could not be cleared from the persistent cache.")

    return bundle

def render_management_transcripts(company: dict):
    inst = company.get("institutional", {}) if isinstance(company, dict) else {}
    bundle = inst.get("management_transcripts", {}) if isinstance(inst, dict) else {}

    st.subheader("Management & Transcript Intelligence — V3.2")
    st.caption(
        "Transcript analytics are loaded lazily and remain separate from the V2 Core Fundamental Score and Institutional Overlay. "
        "The engine uses provider turn sentiment when available and otherwise applies a deterministic, auditable lexical model; it does not invent missing management commentary."
    )

    bundle = _render_cache_budget_controls(company, bundle)

    if not isinstance(bundle, dict) or not bundle.get("available"):
        st.info("No earnings-call transcript payload is currently available from the configured FMP / Alpha Vantage / Finnhub coverage.")
        st.caption(
            "V3.2 deliberately does not substitute news, SEC filings or model-generated prose for an unavailable transcript. "
            "Provider attempts are shown below with HTTP/API reasons so entitlement, rate-limit and empty-payload failures can be distinguished."
        )
        attempts = bundle.get("attempts", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        if isinstance(attempts, pd.DataFrame) and not attempts.empty:
            with st.expander("Transcript provider audit", expanded=True):
                st.dataframe(attempts, use_container_width=True, hide_index=True)
        return

    records = bundle.get("records", [])
    if not isinstance(records, list) or not records:
        st.info("Transcript bundle is empty after normalization.")
        return

    labels = [_quarter_label(r) for r in records]
    selected_label = st.selectbox(
        "Transcript period",
        labels,
        index=0,
        key="company_intelligence_management_transcript_period",
    )
    idx = labels.index(selected_label)
    current, previous, delta, theme_delta = _comparison_for_selection(records, idx)
    summary = current.get("summary", {}) if isinstance(current, dict) else {}
    confidence = bundle.get("confidence", {}) if idx == 0 else {}
    if idx != 0:
        # Historical period confidence is descriptive; avoid pretending the top-level
        # bundle confidence applies unchanged to a different selected quarter.
        confidence = {"overall": None}

    source = str(current.get("provider") or "Unknown")
    q = str(current.get("quarter") or "N/A")
    st.caption(f"Source: {source} · Selected fiscal quarter: {q}" + (f" · Comparison: {previous.get('quarter')}" if previous else " · No prior transcript loaded"))

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Management Tone", _score_text(summary.get("management_tone")))
    c2.metric("Guidance Confidence", _score_text(summary.get("guidance_confidence")))
    c3.metric("Q&A Pressure", _score_text(summary.get("qa_pressure")))
    c4.metric("Evasiveness", _score_text(summary.get("evasiveness")))
    qa_delta = safe_float(summary.get("prepared_to_qa_delta"))
    c5.metric("Prepared → Q&A", "N/A" if qa_delta is None else f"{qa_delta:+.1f} pts")
    c6.metric("Data Confidence", _score_text(confidence.get("overall")))

    st.caption(
        f"Management uncertainty: {_num_text(summary.get('management_uncertainty_per_100'), 2)} hits / 100 words · "
        f"Management turns: {summary.get('management_turns', 0)} · Analyst turns: {summary.get('analyst_turns', 0)} · "
        f"Provider sentiment coverage: {_num_text(summary.get('provider_sentiment_coverage'), 1)}%. "
        "Q&A Pressure and Evasiveness are descriptive risk diagnostics: higher values mean more pressure / avoidance, not a direct bearish signal."
    )

    _render_tone_split(summary)

    st.markdown("#### Quarter-over-quarter management delta")
    if isinstance(delta, pd.DataFrame) and not delta.empty:
        st.dataframe(delta, use_container_width=True, hide_index=True)
    else:
        st.caption("A prior transcript is required for quarter-over-quarter management diagnostics.")

    st.markdown("#### Guidance & outlook evidence")
    guidance = current.get("guidance", pd.DataFrame())
    if isinstance(guidance, pd.DataFrame) and not guidance.empty:
        st.dataframe(guidance, use_container_width=True, hide_index=True)
        st.caption("Evidence rows are short transcript excerpts selected mechanically from explicit guidance/outlook language; they are not generated summaries.")
    else:
        st.caption("No explicit guidance/outlook sentence was detected in the normalized transcript payload.")

    st.markdown("#### Theme map")
    theme = current.get("themes", pd.DataFrame())
    if isinstance(theme, pd.DataFrame) and not theme.empty:
        _render_theme_chart(theme)
        st.dataframe(theme_delta if isinstance(theme_delta, pd.DataFrame) and not theme_delta.empty else theme, use_container_width=True, hide_index=True)
        st.caption("Theme counts are lexical intensity measures. Tone is calculated only from transcript turns containing the theme and should be interpreted with the evidence coverage shown above.")
    else:
        st.caption("Theme analytics unavailable.")

    st.markdown("#### Q&A diagnostic")
    qa_rows = pd.DataFrame([
        {"Metric": "Q&A Pressure", "Value": summary.get("qa_pressure"), "Interpretation": "Higher = more negative/uncertain analyst questioning and/or evasive management answers."},
        {"Metric": "Evasiveness", "Value": summary.get("evasiveness"), "Interpretation": "Higher = more explicit non-answer / non-disclosure language in management Q&A."},
        {"Metric": "Prepared → Q&A delta", "Value": summary.get("prepared_to_qa_delta"), "Interpretation": "Negative = management tone weakened during Q&A versus prepared remarks."},
        {"Metric": "Analyst turns", "Value": summary.get("analyst_turns"), "Interpretation": "Coverage diagnostic, not a directional score."},
        {"Metric": "Q&A question turns", "Value": summary.get("qa_question_count"), "Interpretation": "Coverage diagnostic, not a directional score."},
    ])
    st.dataframe(qa_rows, use_container_width=True, hide_index=True)

    st.markdown("#### Speaker-level diagnostics")
    speakers = current.get("speakers", pd.DataFrame())
    if isinstance(speakers, pd.DataFrame) and not speakers.empty:
        st.dataframe(speakers, use_container_width=True, hide_index=True)
    else:
        st.caption("Speaker metadata unavailable after transcript normalization.")

    with st.expander("Transcript source / methodology audit", expanded=False):
        conf = bundle.get("confidence", {})
        if isinstance(conf, dict) and conf:
            st.dataframe(pd.DataFrame([
                {"Dimension": "Overall", "Score": conf.get("overall")},
                {"Dimension": "Source quality", "Score": conf.get("source_quality")},
                {"Dimension": "Transcript coverage", "Score": conf.get("coverage")},
                {"Dimension": "Speaker-role quality", "Score": conf.get("speaker_quality")},
                {"Dimension": "Analytics quality", "Score": conf.get("analytics_quality")},
                {"Dimension": "Historical comparison", "Score": conf.get("comparison")},
            ]), use_container_width=True, hide_index=True)
        attempts = bundle.get("attempts", pd.DataFrame())
        if isinstance(attempts, pd.DataFrame) and not attempts.empty:
            st.markdown("**Provider attempts**")
            st.dataframe(attempts, use_container_width=True, hide_index=True)

        st.markdown("**Methodology contract**")
        st.write(
            "Management Tone = word-weighted management turn tone. Prepared and Q&A phases are separated using transcript markers and speaker roles. "
            "Guidance Confidence uses only sentences with explicit outlook/guidance language. Q&A Pressure blends analyst challenge/uncertainty with management evasiveness. "
            "No V3 metric is blended into the Core Fundamental Score, Institutional Overlay or V2 What Changed engine at this stage."
        )

    with st.expander("Normalized transcript turns — audit sample", expanded=False):
        turns = current.get("turns", pd.DataFrame())
        if isinstance(turns, pd.DataFrame) and not turns.empty:
            cols = [c for c in ["Speaker", "Title", "Role", "Phase", "Content", "tone", "uncertainty_per_100", "evasive_hits"] if c in turns.columns]
            st.dataframe(turns[cols].head(40), use_container_width=True, hide_index=True)
